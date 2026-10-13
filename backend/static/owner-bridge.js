'use strict';
window.AutofeverBridge = (() => {
  let ctx, state = {}, revision = 0, current = null, error = '', working = false, retentionDays = null;
  let composing = false, updateDraft = null, composingRecovery = false, recoveryDraft = null, retryTimer = null, retryEpoch = 0;
  let ownerAccessCandidate = null;
  const retryDelays = [1000, 5000, 15000];
  const labels = {queued:'In wachtrij · niet verstuurd',sending:'Wordt aangeboden · uitkomst nog onbekend',accepted:'Aangenomen door de bezorgdienst · bezorging niet bevestigd',failed:'Niet verstuurd · mislukt',uncertain:'Verzenduitkomst onzeker · controle nodig',cancelled:'Geannuleerd · niet verstuurd'};
  const button = (label, action, cls='secondary') => '<button type="button" class="'+cls+'" data-owner-action="'+action+'">'+label+'</button>';
  const escape = value => ctx.esc(value);
  const confirmText = message => window.confirm(window.AutofeverLocale?.translate(message) || message);
  const ownerDeletePhrase = value => ['VERWIJDER MIJN SERVERGEGEVENS','DELETE MY SERVER DATA'].includes(value);
  const accessPayload = value => {
    if(!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).sort().join(',') !== 'format,hours,token,version' || value.format !== 'autofever-owner-access' || value.version !== 1 || !/^[A-Za-z0-9_-]{43}$/.test(value.token) || !Number.isInteger(value.hours) || value.hours < 1 || value.hours > 168) throw {userMessage:'Dit is geen geldige Autofever-toegangsbackup.'};
    return {token:value.token,hours:value.hours};
  };
  const decodeAccessEnvelope = value => {
    if(!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).sort().join(',') !== 'body,format,iterations,iv,kdf,salt,version' || value.format !== 'autofever-owner-access' || value.version !== 1 || value.kdf !== 'PBKDF2-SHA256' || value.iterations !== 600000) throw {userMessage:'Dit versleutelde toegangsbestand heeft een onbekend formaat.'};
    const salt=ctx.from64(value.salt), iv=ctx.from64(value.iv), body=ctx.from64(value.body);
    if(salt.length!==16 || iv.length!==12 || body.length<16 || body.length>48*1024) throw {userMessage:'Het versleutelde toegangsbestand is ongeldig of te groot.'};
    return {salt,iv,body};
  };
  const localizedDate = value => new Date(value * 1000).toLocaleString(window.AutofeverLocale?.get() === 'en' ? 'en-GB' : 'nl-NL');

  async function save(next) {
    await ctx.checkedWrite({connection: await ctx.seal(next)}, {connection: revision});
    revision++;
    state = next;
  }
  function stopPendingRetry() {
    if (retryTimer !== null) clearTimeout(retryTimer);
    retryTimer = null;
    retryEpoch++;
  }
  function pendingKey(pending) {
    return pending ? pending.path + ':' + (pending.body.command || pending.body.episode_id) : '';
  }
  function schedulePendingRetry() {
    if (!state.pending || !navigator.onLine || working || retryTimer !== null) return;
    const key = pendingKey(state.pending);
    const attempt = Number.isInteger(state.pending.reconnect_attempts) ? state.pending.reconnect_attempts : 0;
    if (attempt >= retryDelays.length) return;
    const epoch = retryEpoch;
    retryTimer = setTimeout(() => {
      retryTimer = null;
      if (epoch !== retryEpoch || !navigator.onLine || !state.pending || pendingKey(state.pending) !== key || working) return;
      run(async () => {
        if (!state.pending || pendingKey(state.pending) !== key) return;
        const reconnect_attempts = Number.isInteger(state.pending.reconnect_attempts) ? state.pending.reconnect_attempts : 0;
        if (reconnect_attempts >= retryDelays.length) return;
        await save({...state,pending:{...state.pending,reconnect_attempts:reconnect_attempts+1}});
        await submitPending();
      });
    }, retryDelays[attempt]);
  }
  async function api(path, payload, token = state.token) {
    const response = await fetch('/api/v1/owner/' + path, {
      method: payload === undefined ? 'GET' : 'POST',
      headers: {Authorization:'Bearer '+token, ...(payload === undefined ? {} : {'Content-Type':'application/json'})},
      credentials:'omit', cache:'no-store', redirect:'error', signal:AbortSignal.timeout(15000),
      ...(payload === undefined ? {} : {body:JSON.stringify(payload)})
    });
    if (!response.ok) throw Object.assign(new Error('Server request failed'), {status:response.status,path});
    return (await response.json()).data;
  }
  function failure(exc) {
    if (exc.code === 'STALE') return 'De koppeling of het profiel is in een andere tab gewijzigd. Herlaad voordat je verdergaat.';
    if (exc.path === 'data-deletion' && exc.status === 409) return 'Servergegevens zijn niet gewist: er is een actieve of onzekere bezorgpoging. Los die eerst op en probeer daarna opnieuw.';
    if (exc.path === 'retention-setting' && exc.status === 400) return 'Kies uitzetten of een hele bewaartermijn van 1 tot 3650 dagen.';
    if (exc.path === 'episode-updates' && [400,413].includes(exc.status)) return 'Controleer je update: maximaal 2000 tekens en minstens één geldige ontvanger.';
    if (exc.status === 400) return 'Het opgeslagen profiel wordt nog niet ondersteund. Controleer ontvangers en gebruik per persoon één e-mail-, SMS- of WhatsApp-kanaal. Telefoonnummers beginnen met +landcode.';
    if (exc.status === 413) return 'Dit profiel is te groot voor de server. Verklein het voordat je opnieuw start.';
    if (exc.status === 404) return 'De toegang is niet beschikbaar. Controleer de privésleutel en de server; de lokale profielen zijn behouden.';
    if (exc.status === 409) return 'Deze actie kan nu niet. Controleer de actuele stand, eerdere verzendingen en gekozen ontvangers. Bij een oude database moet de beheerder eerst de update-migratie uitvoeren.';
    return exc.userMessage || 'De serveruitkomst is niet bevestigd. Controleer de uitkomst voordat je opnieuw iets start. Je profielen blijven bewaard.';
  }
  async function run(operation) {
    if (working) return;
    working = true;
    document.querySelectorAll('[data-owner-action],.activate,#owner-update input,#owner-update textarea,#owner-update button,#owner-recovery input,#owner-recovery textarea,#owner-recovery button,#owner-export input,#owner-export button,#owner-access-export input,#owner-access-export button,#owner-access-restore input,#owner-access-restore button,#owner-retention input,#owner-retention button,#owner-data-delete input,#owner-data-delete button').forEach(b => b.disabled = true);
    try { error = ''; await operation(); }
    catch (exc) { error = failure(exc); }
    finally { working = false; ctx.render(); ctx.focusHeading(); if(error) ctx.say(error,true); schedulePendingRetry(); }
  }
  async function submitPending() {
    const pending = state.pending;
    if (!pending) return;
    try {
      current = await api(pending.path, pending.body);
      stopPendingRetry();
      await save({...state,pending:null,...(pending.path === 'episode-updates' ? {updateDraft:null} : {}),...(pending.path === 'episode-closures' ? {recoveryDraft:null} : {})});
      if(pending.path === 'episode-updates') {composing = false; updateDraft = null;}
      if(pending.path === 'episode-closures') {composingRecovery = false; recoveryDraft = null;}
      ctx.say('Serverstand bijgewerkt. Een wachtrijstatus is geen bewijs van bezorging.');
    } catch (exc) {
      // These responses precede mutation; unknown/network outcomes retain the same command.
      if ([400,409,413,415].includes(exc.status)) {
        stopPendingRetry();
        await save({...state,pending:null});
      }
      throw exc;
    }
  }
  async function refresh() {
    current = await api('episode');
    if (state.pending?.path === 'episode-closures' && current?.id === state.pending.body.episode_id && current.state === state.pending.body.state) {
      stopPendingRetry();
      await save({...state,pending:null,recoveryDraft:null});
      composingRecovery = false; recoveryDraft = null;
    }
    if (state.pending?.path === 'episode-updates' && current?.id === state.pending.body.episode_id) {
      const submitted = state.pending.body;
      if(current.updates?.some(u => u.command === submitted.command && u.message === submitted.message &&
          JSON.stringify([...u.recipients].sort()) === JSON.stringify([...submitted.recipients].sort()))) {
        stopPendingRetry();
        await save({...state,pending:null,updateDraft:null});
        composing = false; updateDraft = null;
      }
    }
  }
  function preparationCheck(profile, contacts) {
    if (contacts.some(c => !c || c.channels.length !== 1 || !['Email','SMS','WhatsApp'].includes(c.channels[0]))) {
      throw {userMessage:'Kies vooraf per ontvanger één kanaal: e-mail, SMS of WhatsApp. Meerdere kanalen en push vereisen nog een aparte bezorginstelling.'};
    }
    for (const c of contacts) {
      if (c.channels[0] === 'Email' ? !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(c.email) : !/^\+[1-9][0-9]{6,14}$/.test(c.phone.replace(/[\s().-]/g,''))) {
        throw {userMessage:'Vul eerst een geldig adres of internationaal telefoonnummer in voor '+c.name+'.'};
      }
    }
    if (!profile.recipients.length || profile.tasks.some(t => !t.assignees.length)) throw {userMessage:'Stel eerst ontvangers en helpers in.'};
  }
  async function action(name) {
    await run(async () => {
      if (name === 'clear-owner-access-candidate') {
        ownerAccessCandidate = null;
        ctx.say('Herstelvoorbereiding gewist. Er is niets opgeslagen of verstuurd.');
        return;
      }
      if (name === 'restore-owner-access') {
        if (!ownerAccessCandidate) throw {userMessage:'Controleer eerst een geldig versleuteld toegangsbestand.'};
        if (state.pending) throw {userMessage:'Rond eerst de onzekere serveractie af voordat je een koppeling herstelt.'};
        const candidate = structuredClone(ownerAccessCandidate);
        const result = await api('episode', undefined, candidate.token);
        const retention = await api('retention', undefined, candidate.token);
        if(!retention || !(retention.retention_days===null || (Number.isInteger(retention.retention_days)&&retention.retention_days>=1&&retention.retention_days<=3650))) throw {userMessage:'De huidige server bevestigde de koppeling niet volledig. De bestaande koppeling is niet gewijzigd.'};
        await save({token:candidate.token,hours:candidate.hours,pending:null});
        current = result;
        retentionDays = retention.retention_days;
        ownerAccessCandidate = null;
        ctx.say('Serverkoppeling hersteld op deze browser. Profielen en openstaande lokale acties zijn niet teruggezet.');
        return;
      }
      if (!state.token) throw {userMessage:'Koppel eerst de lokale server bij Jouw gegevens.'};
      if (name === 'refresh') return refresh();
      if (name === 'resolve') return submitPending();
      if (state.pending) throw {userMessage:'Controleer eerst de uitkomst van je eerdere actie.'};
      if(name === 'compose') {
        if(current?.state !== 'active') throw {userMessage:'Haal eerst de actieve melding op.'};
        composing = true;
        updateDraft = updateDraft?.episode_id === current.id ? updateDraft :
          state.updateDraft?.episode_id === current.id ? structuredClone(state.updateDraft) :
          {episode_id:current.id,message:'',recipients:[]};
        return;
      }
      if(name === 'recover') {
        if(current?.state !== 'active') throw {userMessage:'Haal eerst de actuele actieve melding op.'};
        const savedMessage = current.snapshot.preparation?.profile.recovery;
        if(!savedMessage) throw {userMessage:'Deze melding heeft geen opgeslagen hersteltekst.'};
        const eligible = current.snapshot.recipients.filter(r => current.notifications.some(j => j.recipient === r.id && j.kind === 'illness' && j.status === 'accepted'));
        recoveryDraft = recoveryDraft?.episode_id === current.id ? structuredClone(recoveryDraft) :
          state.recoveryDraft?.episode_id === current.id ? structuredClone(state.recoveryDraft) :
          {episode_id:current.id,message:savedMessage,recipients:eligible.map(r=>r.id)};
        composingRecovery = true;
        return;
      }
      if(name === 'checkin') {
        if(current?.state !== 'active' || !current.checkin?.due) throw {userMessage:'Er staat nu geen check-in open. Haal de actuele serverstand op.'};
        await save({...state,pending:{path:'episode-checkins',body:{episode_id:current.id,command:crypto.randomUUID()}}});
      }
      if(name === 'save-update-draft') {
        await save({...state,updateDraft});
        ctx.say('Updateconcept versleuteld op dit apparaat bewaard. Niets verstuurd.');
        return;
      }
      if(name === 'hide-update') {composing = false; return;}
      if(name === 'save-recovery-draft') {
        await save({...state,recoveryDraft:structuredClone(recoveryDraft)});
        ctx.say('Herstelconcept versleuteld op dit apparaat bewaard. Niets verstuurd.');
        return;
      }
      if(name === 'hide-recovery') {composingRecovery = false; return;}
      if (name === 'activate') {
        const saved = await ctx.request(ctx.db.transaction('vault').objectStore('vault').get('data'));
        if ((saved?.revision || 0) !== ctx.getRevision()) throw {code:'STALE'};
        const data = saved ? await ctx.unseal(saved) : ctx.getData();
        const profile = structuredClone(data.profiles.find(p => p.id === data.defaultId));
        if (!profile) throw {userMessage:'Sla eerst een standaardprofiel op.'};
        const contacts = profile.recipients.map(id => data.contacts.find(c => c.id === id));
        preparationCheck(profile, contacts);
        await save({...state,pending:{path:'episodes',body:{command:crypto.randomUUID(),profile,contacts,link_ttl:state.hours * 3600}}});
      } else if (name === 'submit-recovery' || name === 'cancel') {
        if (!current || current.state !== 'active') throw {userMessage:'Haal eerst de actuele actieve melding op.'};
        if (name === 'submit-recovery') {
          const draft = structuredClone(recoveryDraft || {});
          if(draft.episode_id !== current.id || !draft.message?.trim() || !draft.recipients?.length) throw {userMessage:'Schrijf een herstelbericht en selecteer minstens één ontvanger.'};
          await save({...state,recoveryDraft:draft,pending:{path:'episode-closures',body:{episode_id:current.id,state:'recovered',recovery_message:draft.message.trim(),recovery_recipients:draft.recipients}}});
        } else {
          await save({...state,pending:{path:'episode-closures',body:{episode_id:current.id,state:'cancelled',recovery_message:null,recovery_recipients:[]}}});
        }
      } else if (name === 'submit-recovery-no-notice') {
        if (!current || current.state !== 'active') throw {userMessage:'Haal eerst de actuele actieve melding op.'};
        const eligible = current.snapshot.recipients.filter(r => current.notifications.some(j => j.recipient === r.id && j.kind === 'illness' && j.status === 'accepted'));
        if (eligible.length) throw {userMessage:'Er is nu een ontvanger beschikbaar. Haal de serverstand opnieuw op en controleer je keuze.'};
        const recovery = current.snapshot.preparation?.profile.recovery;
        if (!recovery) throw {userMessage:'Deze melding heeft geen opgeslagen hersteltekst.'};
        await save({...state,recoveryDraft:null,pending:{path:'episode-closures',body:{episode_id:current.id,state:'recovered',recovery_message:recovery,recovery_recipients:[]}}});
      }
      await submitPending();
    });
  }
  function renderHome(view) {
    if (view !== 'home' || (!state.token && !state.pending) || (!current && !error && !state.pending)) return false;
    let html = '<h1 class="compact-heading" id="owner-title">Jouw melding.</h1>';
    if (state.pending) {
      const attempts = Number.isInteger(state.pending.reconnect_attempts) ? state.pending.reconnect_attempts : 0;
      const retryNote = !navigator.onLine
        ? 'Geen verbinding. Je actie is versleuteld op dit apparaat bewaard. Autofever probeert dezelfde actie maximaal 3 keer opnieuw wanneer je weer online bent en Autofever open blijft.'
        : attempts >= retryDelays.length
          ? 'Automatische pogingen zijn gestopt. Je kunt dezelfde actie veilig opnieuw proberen via Uitkomst controleren.'
          : 'Autofever probeert dezelfde actie maximaal 3 keer met wachttijd opnieuw. De serveruitkomst is nog niet bevestigd.';
      html += '<p class="notice">De uitkomst van je laatste actie is nog niet bevestigd. Er wordt geen nieuwe melding gestart.</p><p class="hint">'+escape(retryNote)+'</p>'+button('Uitkomst controleren','resolve','primary');
    }
    if (error) html += '<p class="notice" role="status">'+escape(error)+'</p>';
    if (current) {
      const snap = current.snapshot, prepared = snap.preparation;
      const person = id => prepared?.contacts.find(c => c.id === id)?.name || id;
      if(composingRecovery && current.state === 'active' && !state.pending) {
        const eligible = snap.recipients.filter(r => current.notifications.some(j => j.recipient === r.id && j.kind === 'illness' && j.status === 'accepted'));
        recoveryDraft = recoveryDraft?.episode_id === current.id ? recoveryDraft : {episode_id:current.id,message:prepared?.profile.recovery || '',recipients:eligible.map(r=>r.id)};
        html += '<section class="editor-block"><h2>Herstelbericht</h2><p class="hint">Pas tekst en ontvangers aan voordat je de herstelmelding in de wachtrij zet. Kies alleen mensen van wie de oorspronkelijke ziekmelding door de bezorgdienst is aangenomen. Dat is geen bewijs van bezorging of lezen.</p>';
        if(!eligible.length) {
          html += '<p>Geen ontvangers beschikbaar: geen oorspronkelijke ziekmelding is door een bezorgdienst aangenomen.</p><p class="hint">Je kunt herstel wel vastleggen. Er wordt dan geen herstelbericht in de wachtrij gezet en niemand wordt geïnformeerd.</p><div class="actions">'+button('Herstel vastleggen zonder bericht','submit-recovery-no-notice','primary')+button('Editor sluiten','hide-recovery','text-button')+'</div>';
        } else {
          html += '<form id="owner-recovery"><label for="owner-recovery-message">Bericht bij herstel</label><textarea id="owner-recovery-message" name="message" maxlength="10000" required>'+escape(recoveryDraft.message)+'</textarea><fieldset><legend>Ontvangers van het herstelbericht</legend>';
          for(const r of eligible) html += '<label class="check"><input type="checkbox" name="recipient" value="'+escape(r.id)+'"'+(recoveryDraft.recipients.includes(r.id)?' checked':'')+'><span>'+escape(person(r.id))+'</span></label>';
          html += '</fieldset><p class="hint">De herstelmelding sluit deze ziekmelding. Er wordt niets naar andere personen gestuurd.</p><div class="actions"><button class="primary" type="submit">Herstelbericht in wachtrij zetten</button>'+button('Concept bewaren','save-recovery-draft')+button('Editor sluiten','hide-recovery','text-button')+'</div></form>';
        }
        html += '</section>';
      }
      html += '<h2>'+escape(prepared?.profile.name || 'Ziekmelding')+'</h2><p class="intro">'+({active:'Actief op de server.',recovered:'Herstel vastgelegd op de server.',cancelled:'Geannuleerd op de server.'}[current.state])+'</p>';
      if(composing && current.state === 'active' && !state.pending) {
        const eligible = snap.recipients.filter(r => current.notifications.some(j => j.recipient === r.id && j.kind === 'illness' && j.status === 'accepted'));
        html += '<section class="editor-block"><h2>Een kleine update</h2><p class="hint">Kies zelf wie deze tekst krijgt. Alleen ontvangers met een aangenomen oorspronkelijke ziekmelding kunnen worden geselecteerd. Aangenomen betekent niet bezorgd of gelezen.</p>';
        html += '<form id="owner-update"><label for="owner-update-message">Updatebericht</label><textarea id="owner-update-message" name="message" maxlength="2000" required>'+escape(updateDraft.message)+'</textarea><fieldset><legend>Ontvangers van deze update</legend>';
        for(const r of eligible) html += '<label class="check"><input type="checkbox" name="recipient" value="'+escape(r.id)+'"'+(updateDraft.recipients.includes(r.id)?' checked':'')+'><span>'+escape(person(r.id))+'</span></label>';
        if(!eligible.length) html += '<p>Nog niemand selecteerbaar: de oorspronkelijke berichten zijn nog niet aangenomen.</p>';
        html += '</fieldset><p class="hint">Concept bewaren slaat je tekst alleen versleuteld op dit apparaat op. Verzenden plaatst één bericht per gekozen persoon in de serverwachtrij. Maximaal 50 updates per ziekmelding; rond de vorige update eerst af.</p><div class="actions"><button class="primary" type="submit"'+(!eligible.length?' disabled':'')+'>Update in wachtrij zetten</button>'+button('Concept bewaren','save-update-draft')+button('Editor sluiten','hide-update','text-button')+'</div></form></section>';
      }
      if(current.updates?.length) {
        html += '<h2 class="section-gap">Jouw updates</h2>';
        for(const u of current.updates) html += '<section class="editor-block"><p class="long">'+escape(u.message)+'</p><p class="hint">Voor: '+escape(u.recipients.map(person).join(', '))+' · '+escape(localizedDate(u.created_at))+'</p></section>';
      }
      html += '<p class="hint">Status bij de laatste controle. Aangenomen door een bezorgdienst betekent niet bezorgd of gelezen.</p><h2 class="section-gap">Berichten</h2>';
      for (const recipient of snap.recipients) {
        html += '<section class="editor-block"><h3>'+escape(person(recipient.id))+'</h3><p class="long">'+escape(recipient.message)+'</p>';
        let updateNumber = 0;
        for(const job of current.notifications.filter(j => j.recipient === recipient.id)) html += '<p class="hint">'+(job.kind === 'recovery'?'Herstel':job.kind === 'update'?'Update '+(++updateNumber):'Ziekmelding')+' · '+escape(labels[job.status] || 'Onbekende status')+'</p>';
        html += '<p class="hint">'+(current.recipients.find(r => r.id===recipient.id)?.acknowledged?'Lezen expliciet bevestigd':'Lezen niet bevestigd')+'</p></section>';
      }
      if(current.recovery) html += '<h2 class="section-gap">Bericht bij herstel</h2><section class="editor-block"><p class="long">'+escape(current.recovery.message)+'</p><p class="hint">Ontvangers: '+escape(current.recovery.recipients.map(person).join(', '))+'</p></section>';
      else if(current.state === 'recovered') html += '<p class="hint">Herstel vastgelegd. Er is geen herstelbericht in de wachtrij gezet.</p>';
      html += '<h2 class="section-gap">Hulp</h2>';
      if (!snap.tasks.length) html += '<p>Geen hulpvragen ingesteld.</p>';
      for(const task of snap.tasks) {
        const status = current.tasks.find(t => t.id===task.id);
        const preference = prepared?.profile.tasks.find(t => t.id===task.id);
        const label = status.state==='accepted'?'Aangenomen door '+person(status.claimant):({pending:'Nog niet aangenomen',completed:'Afgerond',closed:'Gesloten'}[status.state]);
        html += '<section class="editor-block"><h3>'+escape(task.title)+'</h3><p class="long">'+escape(task.description || '')+'</p><p>'+escape(task.timing)+'</p><p>'+escape(label)+'</p>';
        if(status.declined_by.length) html += '<p class="hint">Kan niet helpen: '+escape(status.declined_by.map(person).join(', '))+'</p>';
        if(preference?.repeat && preference.repeat!=='once') html += '<p class="hint">Herhaling: '+escape({daily:'dagelijks',weekly:'wekelijks'}[preference.repeat])+' · bewaard, nog niet ingepland.</p>';
        if(preference?.backup) html += '<p class="hint">Reserve: '+escape(person(preference.backup))+' · nog niet automatisch gevraagd.</p>';
        html += '</section>';
      }
      if (prepared && current.checkin) {
        const nextCheckin = localizedDate(current.checkin.next_due_at);
        html += '<section class="editor-block" aria-live="polite"><h2>Check-in</h2>'+
          (current.checkin.due
            ? '<p class="notice">Tijd om even bij jezelf in te checken. Dit is alleen zichtbaar in Autofever; er wordt niemand anders bericht.</p>'+button('Ik ben nog ziek · volgende check-in plannen','checkin','primary')
            : '<p>Volgende check-in vanaf '+escape(nextCheckin)+'.</p>')+
          '<p class="hint">Elke '+escape(current.checkin.interval_hours)+' uur · je bevestiging start de volgende termijn.</p></section>';
      }
      if (prepared?.profile.duration) html += '<p class="hint">Verwachte terugkeer: '+escape(prepared.profile.duration)+'</p>';
      if (!state.pending) html += '<div class="actions">'+(current.state==='active'?button('Update schrijven','compose','primary')+button('Ik ben hersteld','recover')+button('Gebeurtenis annuleren','cancel','text-button'):button('Nieuwe ziekmelding','activate','primary'))+'</div>';
    }
    html += '<div class="actions">'+button('Serverstand ophalen','refresh')+'</div>';
    document.getElementById('main').innerHTML = html;
    document.querySelector('.app').classList.remove('editor-mode');
    document.querySelector('.bottom > .savebar')?.remove();
    document.querySelector('.preview-note').textContent = 'Lokale serverkoppeling · echte bezorgdiensten nog niet aangesloten';
    return true;
  }
  function decorate(view) {
    document.querySelector('.preview-note').textContent = 'Lokale serverkoppeling · echte bezorgdiensten nog niet aangesloten';
    if(view === 'home') {
      const activate = document.querySelector('.activate');
      if (activate) {activate.disabled = !state.token || !!state.pending; activate.querySelector('span').textContent = state.token?'Start je opgeslagen plan op de server.':'Koppel eerst de server bij Jouw gegevens.';}
      const hint = document.querySelector('.readiness > p.hint');
      if(hint) hint.textContent='De server bewaart de melding en wachtrij. Zonder bezorgdienst worden er geen berichten verstuurd. Check-ins zijn zichtbaar zodra je Autofever opent; herhaalde hulp en reservehelpers zijn nog niet geautomatiseerd.';
    }
    if (view !== 'settings') return;
    document.querySelector('main .intro').insertAdjacentHTML('afterend', '<section class="section-gap"><h2>Automatische bewaartermijn</h2><p class="hint">Standaard staat dit uit. Kies alleen als je wilt dat oude, afgesloten ziekmeldingen en hun servergeschiedenis automatisch uit de live database verdwijnen. Actieve meldingen en berichten met een open, lopende of onzekere bezorgstatus worden nooit opgeruimd. Bewaartermijn werkt pas automatisch wanneer de beheerder de dagelijkse Autofever-opschoontaak op de server heeft ingeschakeld. Exports, serverback-ups en kopieën bij ontvangers vallen hier niet onder.</p><form id="owner-retention"><label for="owner-retention-days">Bewaar geschiedenis na afsluiten (dagen; leeg = uit)</label><input id="owner-retention-days" type="number" min="1" max="3650" step="1" value="'+escape(retentionDays ?? '')+'"'+(!state.token?' disabled':'')+'><p class="hint">1 tot 3650 dagen. Een kortere termijn kan bij de eerstvolgende dagelijkse opschoningsrun direct geschiedenis verwijderen.</p><div class="actions"><button class="secondary" type="submit"'+(!state.token?' disabled':'')+'>Bewaartermijn opslaan</button></div></form></section>');
    document.querySelector('main .intro').insertAdjacentHTML('afterend', '<section class="section-gap"><h2>Servergegevens exporteren</h2><p class="hint">Dit bevat je serverhistorie: ziekte- en herstelberichten, contactgegevens, helperstatus en check-ins. De download wordt eerst met een aparte wachtzin versleuteld. Bewaar die wachtzin los van het bestand. Dit exporteert niet je lokale profielen; gebruik daarvoor de gewone Autofever-back-up.</p><form id="owner-export"><label for="owner-export-password">Wachtzin voor de serverexport</label><input id="owner-export-password" type="password" autocomplete="new-password" minlength="14" maxlength="1024" required><label for="owner-export-confirm">Herhaal de wachtzin</label><input id="owner-export-confirm" type="password" autocomplete="new-password" minlength="14" maxlength="1024" required><p class="hint">Minstens 14 tekens. De wachtzin wordt niet opgeslagen of naar de server gestuurd.</p><div class="actions"><button class="secondary" type="submit"'+(!state.token?' disabled':'')+'>Versleutelde serverexport downloaden</button></div></form></section><section class="section-gap"><h2>Lokale server koppelen</h2><p class="hint">Eenmalige privésleutel van de beheerder, geen nieuw account. Alleen deze server op dit adres. Bewaar de sleutel apart; de profielback-up bevat hem niet. De sleutel wordt hier versleuteld opgeslagen, met de browsersleutel op hetzelfde apparaat.</p>'+(state.token?'<p class="hint">Koppeling bewaard. Verlopen hulplinks sluiten na '+escape(state.hours)+' uur.</p>':'')+'<form id="owner-connect"><label for="owner-token">Privésleutel voor jouw meldingen</label><input id="owner-token" type="password" autocomplete="off" maxlength="43" required><label for="owner-hours">Geldigheid hulplink in uren</label><input id="owner-hours" type="number" min="1" max="168" value="'+escape(state.hours||24)+'" required><div class="actions"><button class="primary" type="submit">Koppeling controleren en bewaren</button></div></form><p class="hint">Terugzetten van een profielback-up wijzigt geen lopende servermelding. Meerdere kanalen per persoon en push zijn nog niet aangesloten; kies voor deze koppeling één beginkanaal.</p></section>');
    document.querySelector('#owner-connect').closest('section').insertAdjacentHTML('afterend',
      '<section class="section-gap"><h2>Serverkoppeling meenemen of herstellen</h2>'+
      '<p class="hint">Deze aparte herstelbackup bevat alleen je toegangssleutel en hulplinkduur; geen profielen, contacten, serverhistorie of openstaande acties. Versleutel hem met een sterke wachtzin en bewaar bestand en wachtzin apart. De wachtzin wordt niet opgeslagen of naar de server gestuurd.</p>'+
      '<p class="hint">Controleer bij terugzetten het adres in je browser: de sleutel wordt alleen gecontroleerd bij de Autofever-server die je nu hebt geopend. Terugzetten trekt een oud of verloren apparaat niet in. Vraag de vertrouwde beheerder om de sleutel te vervangen als een apparaat kwijt of gestolen is.</p>'+
      '<form id="owner-access-export"><label for="owner-access-export-password">Wachtzin voor toegangsbackup</label><input id="owner-access-export-password" type="password" autocomplete="new-password" minlength="14" maxlength="1024" required><label for="owner-access-export-confirm">Herhaal de wachtzin</label><input id="owner-access-export-confirm" type="password" autocomplete="new-password" minlength="14" maxlength="1024" required><div class="actions"><button class="secondary" type="submit"'+(!state.token?' disabled':'')+'>Versleutelde toegangsbackup downloaden</button></div></form>'+
      '<form id="owner-access-restore"><label for="owner-access-file">Versleuteld .afaccess-bestand</label><input id="owner-access-file" type="file" accept=".afaccess,application/json" required><label for="owner-access-restore-password">Wachtzin van de toegangsbackup</label><input id="owner-access-restore-password" type="password" autocomplete="new-password" minlength="14" maxlength="1024" required><div class="actions"><button class="secondary" type="submit">Toegangsbackup controleren</button></div></form>'+
      (ownerAccessCandidate?'<div class="editor-block" role="status"><p>Bestand ontgrendeld. Dit herstelt toegang bij <strong>'+escape(location.origin)+'</strong>. Er is nog geen serververzoek gedaan.</p>'+(state.token?'<p class="hint">Na bevestigen wordt de huidige serverkoppeling in deze browser vervangen.</p>':'')+'<div class="actions">'+button('Koppeling herstellen op deze server','restore-owner-access','primary')+button('Voorbereiding wissen','clear-owner-access-candidate','text-button')+'</div></div>':'<div id="owner-access-restore-preview" aria-live="polite"></div>')+
      '</section>');
    document.querySelector('#owner-export').closest('section').insertAdjacentHTML('afterend', '<section class="section-gap"><h2>Servergegevens wissen</h2><p class="hint">Dit verwijdert je live serverhistorie: ziekte- en herstelteksten, contactgegevens, helpers, check-ins en de berichtenwachtrij. Klaarstaande berichten worden verwijderd; eerder bezorgde berichten kunnen niet worden teruggehaald. Je lokale profielen en serverkoppeling blijven bewaard. Gegevens in operatorback-ups of bij ontvangers worden niet door deze actie gewist.</p><form id="owner-data-delete"><label for="owner-data-delete-confirm">Typ VERWIJDER MIJN SERVERGEGEVENS om te bevestigen</label><input id="owner-data-delete-confirm" type="text" autocomplete="off" maxlength="64" required><p class="hint">Niet mogelijk zolang een verzending bezig is of een provideruitkomst onzeker is; die moet eerst worden opgelost.</p><div class="actions"><button class="text-button" type="submit"'+(!state.token?' disabled':'')+'>Alle servergegevens verwijderen</button></div></form></section>');
  }
  document.addEventListener('click', event => {
    const control = event.target.closest('[data-owner-action]');
    if(control && ctx) {event.preventDefault(); action(control.dataset.ownerAction);}
  });
  window.addEventListener('online', schedulePendingRetry);
  window.addEventListener('offline', stopPendingRetry);
  document.addEventListener('input', event => {
    if(event.target.id === 'owner-data-delete-confirm') {
      document.querySelector('#owner-data-delete button[type="submit"]').disabled = !ownerDeletePhrase(event.target.value);
    }
  });
  const captureUpdate = event => {
    if(event.target.closest('#owner-update') && current) {
      const fields = new FormData(document.getElementById('owner-update'));
      updateDraft = {episode_id:current.id,message:String(fields.get('message')||''),recipients:fields.getAll('recipient')};
    }
  };
  const captureRecovery = event => {
    if(event.target.closest('#owner-recovery') && current) {
      const fields = new FormData(document.getElementById('owner-recovery'));
      recoveryDraft = {episode_id:current.id,message:String(fields.get('message')||''),recipients:fields.getAll('recipient')};
    }
  };
  document.addEventListener('input',captureUpdate);
  document.addEventListener('change',captureUpdate);
  document.addEventListener('input',captureRecovery);
  document.addEventListener('change',captureRecovery);
  document.addEventListener('submit', event => {
    if(event.target.id === 'owner-retention' && ctx) {
      event.preventDefault(); event.stopImmediatePropagation();
      run(async () => {
        if(!state.token || state.pending) throw {userMessage:'Koppel eerst de server en rond een eventuele onzekere actie af.'};
        const raw=document.getElementById('owner-retention-days').value.trim();
        const days=raw===''?null:Number(raw);
        if(days!==null && (!Number.isInteger(days)||days<1||days>3650)) throw {userMessage:'Kies uitzetten of een hele bewaartermijn van 1 tot 3650 dagen.'};
        if(days!==null && (retentionDays===null || days<retentionDays) &&
           !confirmText('Deze kortere bewaartermijn kan bij de volgende dagelijkse serveropschoning oude, afgesloten geschiedenis definitief uit de live database verwijderen. Back-ups en ontvangerkopieën blijven bestaan. Doorgaan?')) return;
        const result=await api('retention-setting',{retention_days:days});
        if(result?.retention_days!==days) throw {userMessage:'De server heeft de nieuwe bewaartermijn niet bevestigd. Haal de instelling opnieuw op.'};
        retentionDays=days;
        ctx.say(days===null?'Automatische bewaartermijn uitgezet.':'Bewaartermijn opgeslagen. Opschonen gebeurt alleen wanneer de servertaak actief is.');
      });
      return;
    }
    if(event.target.id === 'owner-data-delete' && ctx) {
      event.preventDefault(); event.stopImmediatePropagation();
      run(async () => {
        if(!state.token || state.pending) throw {userMessage:'Koppel eerst de server en rond een eventuele onzekere actie af.'};
        if(!ownerDeletePhrase(document.getElementById('owner-data-delete-confirm').value)) throw {userMessage:'Typ de bevestigingszin exact over om de servergegevens te wissen.'};
        if(!confirmText('Alle live serverepisoden, contactgegevens, helperreacties, check-ins en wachtrijberichten voor deze eigenaar wissen? Lokale profielen blijven bestaan; al bezorgde berichten en operatorback-ups niet.')) return;
        const result=await api('data-deletion',{confirmation:'DELETE_MY_SERVER_DATA'});
        if(!Number.isInteger(result?.deleted_episodes) || result.deleted_episodes<0) throw {userMessage:'De server gaf geen geldige wisbevestiging. Controleer de serverstand voordat je verdergaat.'};
        await save({...state,pending:null,updateDraft:null});
        current=null;
        ctx.say('Serverhistorie gewist. Je lokale profielen en serverkoppeling zijn behouden.');
      });
      return;
    }
    if(event.target.id === 'owner-recovery' && ctx) {
      event.preventDefault(); event.stopImmediatePropagation();
      captureRecovery({target:event.target});
      action('submit-recovery');
      return;
    }
    if(event.target.id === 'owner-update' && ctx) {
      event.preventDefault(); event.stopImmediatePropagation();
      captureUpdate({target:event.target});
      run(async () => {
        if(state.pending || current?.state !== 'active') throw {userMessage:'Controleer eerst je lopende actie en melding.'};
        const draft = structuredClone(updateDraft);
        if(!draft.message.trim() || !draft.recipients.length) throw {userMessage:'Schrijf een update en selecteer minstens één ontvanger.'};
        await save({...state,updateDraft:draft,pending:{path:'episode-updates',body:{episode_id:current.id,command:crypto.randomUUID(),message:draft.message.trim(),recipients:draft.recipients}}});
        await submitPending();
      });
      return;
    }
    if(event.target.id === 'owner-export' && ctx) {
      event.preventDefault(); event.stopImmediatePropagation();
      run(async () => {
        if(!state.token || state.pending) throw {userMessage:'Koppel eerst de server en los een eventuele onzekere actie op.'};
        const password=document.getElementById('owner-export-password').value;
        const confirm=document.getElementById('owner-export-confirm').value;
        if(password.length<14 || password!==confirm) throw {userMessage:'Gebruik minstens 14 tekens en vul tweemaal dezelfde wachtzin in.'};
        const exported=await api('export');
        if(exported?.format!=='autofever-owner-export' || exported.version!==1 || !Array.isArray(exported.episodes)) throw {userMessage:'De serverexport heeft een onbekend formaat. Er is geen bestand gemaakt.'};
        const salt=crypto.getRandomValues(new Uint8Array(16)), iv=crypto.getRandomValues(new Uint8Array(12));
        const plain=new TextEncoder().encode(JSON.stringify(exported));
        const encrypted=await crypto.subtle.encrypt({name:'AES-GCM',iv},await ctx.backupKey(password,salt),plain);
        const envelope={format:'autofever-owner-export',version:1,kdf:'PBKDF2-SHA256',iterations:600000,salt:ctx.to64(salt),iv:ctx.to64(iv),body:ctx.to64(new Uint8Array(encrypted))};
        const blob=new Blob([JSON.stringify(envelope)],{type:'application/json'}), url=URL.createObjectURL(blob), link=document.createElement('a');
        link.href=url;link.download='autofever-server-'+new Date().toISOString().slice(0,10)+'.afexport';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
        event.target.reset();ctx.say('Versleutelde serverexport aangeboden als download. Bewaar de wachtzin apart.');
      });
      return;
    }
    if(event.target.id === 'owner-access-export' && ctx) {
      event.preventDefault(); event.stopImmediatePropagation();
      const form=event.target;
      run(async () => {
        try {
          if(!state.token || state.pending) throw {userMessage:'Koppel eerst de server en los een eventuele onzekere actie op.'};
          const password=document.getElementById('owner-access-export-password').value;
          const confirm=document.getElementById('owner-access-export-confirm').value;
          if(password.length<14 || password!==confirm) throw {userMessage:'Gebruik minstens 14 tekens en vul tweemaal dezelfde wachtzin in.'};
          const payload={format:'autofever-owner-access',version:1,token:state.token,hours:state.hours};
          const salt=crypto.getRandomValues(new Uint8Array(16)),iv=crypto.getRandomValues(new Uint8Array(12));
          const encrypted=await crypto.subtle.encrypt({name:'AES-GCM',iv},await ctx.backupKey(password,salt),new TextEncoder().encode(JSON.stringify(payload)));
          const envelope={format:'autofever-owner-access',version:1,kdf:'PBKDF2-SHA256',iterations:600000,salt:ctx.to64(salt),iv:ctx.to64(iv),body:ctx.to64(new Uint8Array(encrypted))};
          const blob=new Blob([JSON.stringify(envelope)],{type:'application/json'}),url=URL.createObjectURL(blob),link=document.createElement('a');
          link.href=url;link.download='autofever-toegang-'+new Date().toISOString().slice(0,10)+'.afaccess';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
          ctx.say('Versleutelde toegangsbackup aangeboden als download. Bewaar de wachtzin apart.');
        } finally {form.reset();}
      });
      return;
    }
    if(event.target.id === 'owner-access-restore' && ctx) {
      event.preventDefault(); event.stopImmediatePropagation();
      const form=event.target;
      run(async () => {
        try {
          const file=document.getElementById('owner-access-file').files[0];
          const password=document.getElementById('owner-access-restore-password').value;
          if(!file || !file.name.toLowerCase().endsWith('.afaccess') || file.size<1 || file.size>64*1024) throw {userMessage:'Kies een geldig .afaccess-bestand van maximaal 64 KB.'};
          if(password.length<14 || password.length>1024) throw {userMessage:'Vul de wachtzin van minstens 14 tekens in.'};
          let envelope;
          try { envelope=JSON.parse(await file.text()); } catch { throw {userMessage:'Het toegangsbestand is geen leesbare back-up.'}; }
          const {salt,iv,body}=decodeAccessEnvelope(envelope);
          let plaintext;
          try { plaintext=await crypto.subtle.decrypt({name:'AES-GCM',iv},await ctx.backupKey(password,salt),body); }
          catch { throw {userMessage:'Bestand of wachtzin klopt niet. Er is niets opgeslagen of naar een server gestuurd.'}; }
          ownerAccessCandidate=accessPayload(JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(plaintext)));
          ctx.say('Bestand gecontroleerd. Controleer het serveradres en bevestig apart om de koppeling te herstellen. Er is nog geen serververzoek gedaan.');
        } catch(exc) {
          if(exc.userMessage) throw exc;
          throw {userMessage:'De toegangsbackup kon niet veilig worden gelezen. Er is niets opgeslagen of verstuurd.'};
        } finally {form.reset();}
      });
      return;
    }
    if(event.target.id !== 'owner-connect' || !ctx) return;
    event.preventDefault(); event.stopImmediatePropagation();
    run(async () => {
      if(state.pending) throw {userMessage:'Controleer eerst de uitkomst van je eerdere actie. Wissel nu niet van sleutel.'};
      const token = document.getElementById('owner-token').value.trim();
      const hours = Number(document.getElementById('owner-hours').value);
      if(!/^[A-Za-z0-9_-]{43}$/.test(token) || !Number.isInteger(hours) || hours < 1 || hours > 168) throw {userMessage:'Gebruik de volledige privésleutel en een geldigheid van 1 tot 168 uur.'};
      const result = await api('episode',undefined,token);
      const retention = await api('retention',undefined,token);
      if(!retention || !(retention.retention_days===null || (Number.isInteger(retention.retention_days)&&retention.retention_days>=1&&retention.retention_days<=3650))) throw {userMessage:'De server gaf geen geldige bewaartermijn terug.'};
      await save({token,hours,pending:null}); current = result;
      retentionDays = retention.retention_days;
      ctx.say('Koppeling gecontroleerd en bewaard. Er is niets verstuurd.');
    });
  },true);
  return {
    async init(context) {
      ctx = context;
      const saved = await ctx.request(ctx.db.transaction('vault').objectStore('vault').get('connection'));
      if(saved) {state = await ctx.unseal(saved); revision = saved.revision || 0;}
      if(state.token) {try {await refresh();const retention=await api('retention');retentionDays=retention.retention_days;} catch(exc) {error = failure(exc);}}
      schedulePendingRetry();
    },
    handles:name => ['activate','recover','cancel'].includes(name), action, renderHome, decorate
  };
})();
