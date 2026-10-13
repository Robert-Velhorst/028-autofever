'use strict';
window.AutofeverBridge = (() => {
  let ctx, state = {}, revision = 0, current = null, error = '', working = false;
  let composing = false, updateDraft = null;
  const labels = {queued:'In wachtrij · niet verstuurd',sending:'Wordt aangeboden · uitkomst nog onbekend',accepted:'Aangenomen door de bezorgdienst · bezorging niet bevestigd',failed:'Niet verstuurd · mislukt',uncertain:'Verzenduitkomst onzeker · controle nodig',cancelled:'Geannuleerd · niet verstuurd'};
  const button = (label, action, cls='secondary') => '<button type="button" class="'+cls+'" data-owner-action="'+action+'">'+label+'</button>';
  const escape = value => ctx.esc(value);

  async function save(next) {
    await ctx.checkedWrite({connection: await ctx.seal(next)}, {connection: revision});
    revision++;
    state = next;
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
    document.querySelectorAll('[data-owner-action],.activate,#owner-update input,#owner-update textarea,#owner-update button').forEach(b => b.disabled = true);
    try { error = ''; await operation(); }
    catch (exc) { error = failure(exc); }
    finally { working = false; ctx.render(); ctx.focusHeading(); if(error) ctx.say(error,true); }
  }
  async function submitPending() {
    const pending = state.pending;
    if (!pending) return;
    try {
      current = await api(pending.path, pending.body);
      await save({...state,pending:null,...(pending.path === 'episode-updates' ? {updateDraft:null} : {})});
      if(pending.path === 'episode-updates') {composing = false; updateDraft = null;}
      ctx.say('Serverstand bijgewerkt. Een wachtrijstatus is geen bewijs van bezorging.');
    } catch (exc) {
      // These responses precede mutation; unknown/network outcomes retain the same command.
      if ([400,409,413,415].includes(exc.status)) await save({...state,pending:null});
      throw exc;
    }
  }
  async function refresh() {
    current = await api('episode');
    if (state.pending?.path === 'episode-closures' && current?.id === state.pending.body.episode_id && current.state === state.pending.body.state) {
      await save({...state,pending:null});
    }
    if (state.pending?.path === 'episode-updates' && current?.id === state.pending.body.episode_id) {
      const submitted = state.pending.body;
      if(current.updates?.some(u => u.command === submitted.command && u.message === submitted.message &&
          JSON.stringify([...u.recipients].sort()) === JSON.stringify([...submitted.recipients].sort()))) {
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
      if (name === 'activate') {
        const saved = await ctx.request(ctx.db.transaction('vault').objectStore('vault').get('data'));
        if ((saved?.revision || 0) !== ctx.getRevision()) throw {code:'STALE'};
        const data = saved ? await ctx.unseal(saved) : ctx.getData();
        const profile = structuredClone(data.profiles.find(p => p.id === data.defaultId));
        if (!profile) throw {userMessage:'Sla eerst een standaardprofiel op.'};
        const contacts = profile.recipients.map(id => data.contacts.find(c => c.id === id));
        preparationCheck(profile, contacts);
        await save({...state,pending:{path:'episodes',body:{command:crypto.randomUUID(),profile,contacts,link_ttl:state.hours * 3600}}});
      } else if (name === 'recover' || name === 'cancel') {
        if (!current || current.state !== 'active') throw {userMessage:'Haal eerst de actuele actieve melding op.'};
        const recovery = current.snapshot.preparation?.profile.recovery;
        if (name === 'recover' && !recovery) throw {userMessage:'Deze melding heeft geen opgeslagen hersteltekst.'};
        await save({...state,pending:{path:'episode-closures',body:{episode_id:current.id,state:name === 'recover'?'recovered':'cancelled',recovery_message:name === 'recover'?recovery:null}}});
      }
      await submitPending();
    });
  }
  function renderHome(view) {
    if (view !== 'home' || (!state.token && !state.pending) || (!current && !error && !state.pending)) return false;
    let html = '<h1 class="compact-heading">Jouw melding.</h1>';
    if (state.pending) html += '<p class="notice">De uitkomst van je laatste actie is nog niet bevestigd. Er wordt geen nieuwe melding gestart.</p>'+button('Uitkomst controleren','resolve','primary');
    if (error) html += '<p class="notice" role="status">'+escape(error)+'</p>';
    if (current) {
      const snap = current.snapshot, prepared = snap.preparation;
      const person = id => prepared?.contacts.find(c => c.id === id)?.name || id;
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
        for(const u of current.updates) html += '<section class="editor-block"><p class="long">'+escape(u.message)+'</p><p class="hint">Voor: '+escape(u.recipients.map(person).join(', '))+' · '+escape(new Date(u.created_at*1000).toLocaleString('nl-NL'))+'</p></section>';
      }
      html += '<p class="hint">Status bij de laatste controle. Aangenomen door een bezorgdienst betekent niet bezorgd of gelezen.</p><h2 class="section-gap">Berichten</h2>';
      for (const recipient of snap.recipients) {
        html += '<section class="editor-block"><h3>'+escape(person(recipient.id))+'</h3><p class="long">'+escape(recipient.message)+'</p>';
        let updateNumber = 0;
        for(const job of current.notifications.filter(j => j.recipient === recipient.id)) html += '<p class="hint">'+(job.kind === 'recovery'?'Herstel':job.kind === 'update'?'Update '+(++updateNumber):'Ziekmelding')+' · '+escape(labels[job.status] || 'Onbekende status')+'</p>';
        html += '<p class="hint">'+(current.recipients.find(r => r.id===recipient.id)?.acknowledged?'Lezen expliciet bevestigd':'Lezen niet bevestigd')+'</p></section>';
      }
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
        const nextCheckin = new Date(current.checkin.next_due_at*1000).toLocaleString('nl-NL');
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
    document.querySelector('main .intro').insertAdjacentHTML('afterend', '<section class="section-gap"><h2>Lokale server koppelen</h2><p class="hint">Eenmalige privésleutel van de beheerder, geen nieuw account. Alleen deze server op dit adres. Bewaar de sleutel apart; de profielback-up bevat hem niet. De sleutel wordt hier versleuteld opgeslagen, met de browsersleutel op hetzelfde apparaat.</p>'+(state.token?'<p class="hint">Koppeling bewaard. Verlopen hulp-links sluiten na '+escape(state.hours)+' uur.</p>':'')+'<form id="owner-connect"><label for="owner-token">Privésleutel voor jouw meldingen</label><input id="owner-token" type="password" autocomplete="off" maxlength="43" required><label for="owner-hours">Geldigheid hulplink in uren</label><input id="owner-hours" type="number" min="1" max="168" value="'+escape(state.hours||24)+'" required><div class="actions"><button class="primary" type="submit">Koppeling controleren en bewaren</button></div></form><p class="hint">Terugzetten van een profielback-up wijzigt geen lopende servermelding. Meerdere kanalen per persoon en push zijn nog niet aangesloten; kies voor deze koppeling één beginkanaal.</p></section>');
  }
  document.addEventListener('click', event => {
    const control = event.target.closest('[data-owner-action]');
    if(control && ctx) {event.preventDefault(); action(control.dataset.ownerAction);}
  });
  const captureUpdate = event => {
    if(event.target.closest('#owner-update') && current) {
      const fields = new FormData(document.getElementById('owner-update'));
      updateDraft = {episode_id:current.id,message:String(fields.get('message')||''),recipients:fields.getAll('recipient')};
    }
  };
  document.addEventListener('input',captureUpdate);
  document.addEventListener('change',captureUpdate);
  document.addEventListener('submit', event => {
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
    if(event.target.id !== 'owner-connect' || !ctx) return;
    event.preventDefault(); event.stopImmediatePropagation();
    run(async () => {
      if(state.pending) throw {userMessage:'Controleer eerst de uitkomst van je eerdere actie. Wissel nu niet van sleutel.'};
      const token = document.getElementById('owner-token').value.trim();
      const hours = Number(document.getElementById('owner-hours').value);
      if(!/^[A-Za-z0-9_-]{43}$/.test(token) || !Number.isInteger(hours) || hours < 1 || hours > 168) throw {userMessage:'Gebruik de volledige privésleutel en een geldigheid van 1 tot 168 uur.'};
      const result = await api('episode',undefined,token);
      await save({token,hours,pending:null}); current = result;
      ctx.say('Koppeling gecontroleerd en bewaard. Er is niets verstuurd.');
    });
  },true);
  return {
    async init(context) {
      ctx = context;
      const saved = await ctx.request(ctx.db.transaction('vault').objectStore('vault').get('connection'));
      if(saved) {state = await ctx.unseal(saved); revision = saved.revision || 0;}
      if(state.token) {try {await refresh();} catch(exc) {error = failure(exc);}}
    },
    handles:name => ['activate','recover','cancel'].includes(name), action, renderHome, decorate
  };
})();
