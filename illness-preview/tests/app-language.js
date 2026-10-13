async (page) => {
  const check=(value,message)=>{if(!value)throw Error(message);};
  const browser=page.context().browser();
  const context=await browser.newContext({viewport:{width:390,height:844}});
  const app=await context.newPage();
  const errors=[];
  app.on('pageerror',error=>errors.push(error.message));
  let offlineActionInProgress=false;
  app.on('console',message=>{
    if(message.type()!=='error') return;
    if(offlineActionInProgress && /net::ERR_INTERNET_DISCONNECTED/.test(message.text())) return;
    errors.push(message.text());
  });
  const base=new URL(page.url());
  const ownerUrl=new URL('/owner',base).href;
  const senderMessage='Ik ben onverwacht ziek. Laat me vooral even weten hoe het gaat.';
  let episode={
    id:'synthetic-episode',state:'active',
    snapshot:{preparation:{profile:{name:'Synthetic episode',duration:'',recovery:'I am feeling better. Thank you!',tasks:[]},contacts:[{id:'maya',name:'Maya'},{id:'jules',name:'Jules'}]},recipients:[{id:'maya',message:senderMessage},{id:'jules',message:'I am sick and will not be able to join the meeting.'}],tasks:[]},
    notifications:[{recipient:'maya',kind:'illness',status:'accepted'},{recipient:'jules',kind:'illness',status:'accepted'}],
    recipients:[{id:'maya',acknowledged:false},{id:'jules',acknowledged:false}],tasks:[],updates:[],
    checkin:{due:true,next_due_at:1800000000,interval_hours:4}
  };
  const responses=[];
  const updateRequests=[];
  const closureRequests=[];
  app.on('request',request=>{
    if(new URL(request.url()).pathname.endsWith('/episode-updates')) updateRequests.push(request.postDataJSON());
    if(new URL(request.url()).pathname.endsWith('/episode-closures')) closureRequests.push(request.postDataJSON());
  });
  try {
    await app.goto(base.href);
    await app.getByRole('heading',{name:'Neem de rust die je nodig hebt.',exact:false}).waitFor();
    check(await app.locator('html').getAttribute('lang')==='nl','Dutch should be the default language');
    await app.getByRole('button',{name:'Switch language to English',exact:true}).click();
    await app.getByRole('heading',{name:'Take the rest you need.',exact:false}).waitFor();
    check(await app.locator('html').getAttribute('lang')==='en','Language toggle did not apply English');
    check(await app.getByRole('navigation',{name:'Main navigation'}).count()===1,'Main navigation was not translated');
    await app.reload();
    await app.getByRole('heading',{name:'Take the rest you need.',exact:false}).waitFor();
    check(await app.locator('html').getAttribute('lang')==='en','English preference did not persist after reload');
    await app.getByRole('button',{name:'Profiles',exact:true}).click();
    await app.getByRole('heading',{name:'Your profiles.'}).waitFor();
    await app.locator('article').first().getByRole('button',{name:'Edit',exact:true}).click();
    const message=app.locator('#profile-message');
    const senderText='Ik ben ziek en wil graag rust.';
    await message.fill(senderText);
    await app.getByRole('button',{name:'Switch language to Dutch',exact:true}).click();
    check(await app.locator('html').getAttribute('lang')==='nl','Language toggle did not switch document language');
    await app.getByLabel('Standaardbericht',{exact:true}).waitFor();
    check(await message.inputValue()===senderText,'Changing language lost unsaved form input');
    check(await app.locator('.message-preview').first().textContent()===senderText,'Language toggle changed sender-authored message preview');
    await app.getByRole('button',{name:'Switch language to English',exact:true}).click();
    await app.getByLabel('Default message',{exact:true}).waitFor();
    check(await app.locator('.message-preview').first().textContent()===senderText,'Switching back to English changed sender-authored message');
    await app.getByRole('button',{name:'Settings',exact:true}).click();
    await app.getByRole('heading',{name:'Your details.'}).waitFor();

    const previewResponse=await context.request.get(new URL('.',base).href);
    let html=await previewResponse.text();
    html=html.replace('<head>','<head><script src="/backend/static/owner-bridge.js"></script>');
    html=html.replace('<script src="./i18n.js"></script>','<script src="/illness-preview/i18n.js"></script>');
    await app.route(ownerUrl,route=>route.fulfill({status:200,contentType:'text/html',body:html}));
    const bridgeResponse=await context.request.get(new URL('../backend/static/owner-bridge.js',base).href);
    const bridge=await bridgeResponse.text();
    await app.route('**/backend/static/owner-bridge.js',route=>route.fulfill({status:200,contentType:'text/javascript',body:bridge}));
    await app.route('**/api/v1/owner/**',async route=>{
      const request=route.request(),path=new URL(request.url()).pathname;
      responses.push({path,method:request.method(),authorized:request.headers()['authorization']==='Bearer '+'A'.repeat(43)});
      if(path.endsWith('/episode')) return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({data:episode})});
      if(path.endsWith('/retention')) return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({data:{retention_days:null}})});
      if(path.endsWith('/episode-updates')) {
        if(updateRequests.length===1) return route.abort('internetdisconnected');
        const body=request.postDataJSON();
        episode.updates.push({command:body.command,message:body.message,recipients:body.recipients,created_at:1800000000});
        return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({data:episode})});
      }
      if(path.endsWith('/episode-closures')) {
        const body=request.postDataJSON();
        episode.state=body.state;
        episode.recovery=body.recovery_recipients.length ? {message:body.recovery_message,recipients:body.recovery_recipients} : null;
        for(const recipient of body.recovery_recipients) episode.notifications.push({recipient,kind:'recovery',status:'queued'});
        return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({data:episode})});
      }
      return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({data:{}})});
    });
    await app.goto(ownerUrl);
    await app.getByRole('button',{name:'Settings',exact:true}).click();
    await app.getByRole('heading',{name:'Your details.'}).waitFor();
    await app.getByRole('heading',{name:'Export server data'}).waitFor();
    await app.getByRole('heading',{name:'Delete server data'}).waitFor();
    await app.getByLabel('Type DELETE MY SERVER DATA to confirm',{exact:true}).waitFor();
    await app.getByLabel('Private key for your notifications',{exact:true}).fill('A'.repeat(43));
    await app.getByLabel('Helper-link validity in hours',{exact:true}).fill('24');
    await app.getByRole('button',{name:'Check and save connection',exact:true}).click();
    try { await app.getByText('Connection checked and saved. Nothing was sent.',{exact:true}).waitFor({timeout:5000}); }
    catch { throw Error(`Owner connection failed. Body: ${await app.locator('body').innerText()}. Responses: ${JSON.stringify(responses)}. Errors: ${errors.join(' | ')}`); }
    await app.getByRole('button',{name:'Home',exact:true}).click();
    try { await app.getByRole('heading',{name:'Your notification.'}).waitFor({timeout:5000}); }
    catch { throw Error(`Owner view did not render. Body: ${await app.locator('body').innerText()}. Responses: ${JSON.stringify(responses)}. Errors: ${errors.join(' | ')}`); }
    await app.getByText(senderMessage,{exact:true}).waitFor();
    await app.getByText('Time for a check-in. This is visible only in Autofever; nobody else is notified.',{exact:true}).waitFor();
    check(responses.length>0&&responses.every(item=>item.method==='GET'),'Opening the due check-in triggered a server write or notification action');
    check(await app.getByRole('button',{name:/still sick/}).count()===1,'Owner check-in confirmation action was not available');
    await app.getByRole('button',{name:'Switch language to Dutch',exact:true}).click();
    await app.getByText('Dit is alleen zichtbaar in Autofever; er wordt niemand anders bericht.',{exact:false}).waitFor();
    check(await app.getByText(senderMessage,{exact:true}).count()===1,'Changing owner language altered sender-authored content');
    await app.getByRole('button',{name:'Instellingen',exact:true}).click();
    await app.getByRole('heading',{name:'Servergegevens exporteren'}).waitFor();
    await app.getByLabel('Typ VERWIJDER MIJN SERVERGEGEVENS om te bevestigen',{exact:true}).waitFor();
    await app.getByRole('button',{name:'Switch language to English',exact:true}).click();
    await app.getByRole('button',{name:'Home',exact:true}).click();
    await app.getByRole('button',{name:'Write an update',exact:true}).click();
    await app.locator('#owner-update-message').fill('I will be offline briefly; this update should be queued once.');
    await app.locator('#owner-update input[name="recipient"][value="maya"]').check();
    offlineActionInProgress=true;
    await context.setOffline(true);
    await app.getByRole('button',{name:'Queue update',exact:true}).click();
    await app.getByText('No connection. Your action is saved encrypted on this device. Autofever will retry the same action up to 3 times when you are online again, while Autofever stays open.',{exact:true}).waitFor();
    check(episode.updates.length===0,'Offline update was presented as accepted before the server responded');
    await context.setOffline(false);
    await app.getByText('Server status updated. A queue status is not proof of delivery.',{exact:true}).waitFor({timeout:8000});
    offlineActionInProgress=false;
    check(updateRequests.length===2,'Reconnect did not retry the pending update exactly once');
    check(JSON.stringify(updateRequests[0])===JSON.stringify(updateRequests[1]),'Reconnect generated a new command instead of retrying the same idempotent command');
    await app.getByText('I will be offline briefly; this update should be queued once.',{exact:true}).waitFor();
    check(episode.updates.length===1,'Reconnect created a duplicate update');
    await app.getByRole('button',{name:'I have recovered',exact:true}).click();
    await app.getByRole('heading',{name:'Recovery message',exact:true}).waitFor();
    await app.locator('#owner-recovery-message').fill('Glad to be back. Thanks for your help!');
    await app.locator('#owner-recovery input[name="recipient"][value="jules"]').uncheck();
    await app.getByRole('button',{name:'Queue recovery notice',exact:true}).click();
    await app.getByText('Recovery recorded on the server.',{exact:true}).waitFor();
    await app.getByText('Glad to be back. Thanks for your help!',{exact:true}).waitFor();
    check(closureRequests.length===1,'Recovery editor did not submit exactly one closure request');
    check(closureRequests[0].recovery_message==='Glad to be back. Thanks for your help!','Custom recovery message was not preserved');
    check(JSON.stringify(closureRequests[0].recovery_recipients)===JSON.stringify(['maya']),'Recovery recipients did not respect the explicit subset');
    check(episode.notifications.filter(item=>item.kind==='recovery').map(item=>item.recipient).join(',')==='maya','A nonselected person received a recovery notice');
    episode.state='active';
    episode.recovery=null;
    episode.notifications=episode.notifications.filter(item=>item.kind!=='recovery').map(item=>({...item,status:'failed'}));
    await app.getByRole('button',{name:'Refresh server status',exact:true}).click();
    await app.getByRole('button',{name:'I have recovered',exact:true}).click();
    await app.getByRole('button',{name:'Record recovery without a message',exact:true}).click();
    await app.getByText('Recovery recorded. No recovery notice was queued.',{exact:true}).waitFor();
    check(closureRequests.length===2&&closureRequests[1].recovery_recipients.length===0,'No-notice recovery did not send an explicit empty recipient set');
    check(episode.notifications.every(item=>item.kind!=='recovery'),'No recovery notice should be queued when no initial notice was accepted');

    // A separately encrypted access backup must be inert until an explicit restore.
    await app.getByRole('button',{name:'Switch language to Dutch',exact:true}).click();
    await app.getByRole('button',{name:'Instellingen',exact:true}).click();
    await app.locator('#owner-access-export-password').fill('Synthetic passphrase 2026');
    await app.locator('#owner-access-export-confirm').fill('Synthetic passphrase 2026');
    await app.evaluate(()=>{
      const original=URL.createObjectURL.bind(URL);
      URL.createObjectURL=blob=>{window.__autofeverAccessBackup=blob.text();return original(blob);};
    });
    const beforeExport=responses.length;
    const [download]=await Promise.all([
      app.waitForEvent('download'),
      app.locator('#owner-access-export button[type="submit"]').click()
    ]);
    check(download.suggestedFilename().endsWith('.afaccess'),'Owner access backup did not use the .afaccess extension');
    const accessEnvelopeText=await app.evaluate(()=>window.__autofeverAccessBackup);
    const accessEnvelope=JSON.parse(accessEnvelopeText);
    check(accessEnvelope.format==='autofever-owner-access'&&accessEnvelope.version===1&&accessEnvelope.kdf==='PBKDF2-SHA256','Access backup envelope metadata is invalid');
    check(!accessEnvelopeText.includes('A'.repeat(43)),'Plain owner capability appeared in the access backup envelope');
    check(responses.length===beforeExport,'Exporting access metadata made an unexpected server request');

    await app.evaluate(()=>new Promise((resolve,reject)=>{
      const request=indexedDB.open('autofever-editable-preview-v1');
      request.onerror=()=>reject(request.error);
      request.onsuccess=()=>{const tx=request.result.transaction('vault','readwrite');tx.objectStore('vault').delete('connection');tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);};
    }));
    await app.reload();
    await app.getByRole('button',{name:'Instellingen',exact:true}).click();
    await app.getByRole('heading',{name:'Jouw gegevens.'}).waitFor();
    const requestCountBeforeImport=responses.length;
    await app.locator('#owner-access-file').setInputFiles({name:'recovery.afaccess',mimeType:'application/json',buffer:Buffer.from(accessEnvelopeText)});
    await app.locator('#owner-access-restore-password').fill('Incorrect synthetic phrase');
    await app.locator('#owner-access-restore button[type="submit"]').click();
    await app.getByText('Bestand of wachtzin klopt niet. Er is niets opgeslagen of naar een server gestuurd.',{exact:true}).waitFor();
    check(responses.length===requestCountBeforeImport,'Wrong passphrase triggered a server request');
    await app.locator('#owner-access-file').setInputFiles({name:'recovery.afaccess',mimeType:'application/json',buffer:Buffer.from(accessEnvelopeText)});
    await app.locator('#owner-access-restore-password').fill('Synthetic passphrase 2026');
    await app.locator('#owner-access-restore button[type="submit"]').click();
    await app.getByText('Bestand gecontroleerd. Controleer het serveradres en bevestig apart om de koppeling te herstellen. Er is nog geen serververzoek gedaan.',{exact:true}).waitFor();
    check(responses.length===requestCountBeforeImport,'Decrypting a valid file contacted the server before confirmation');
    await app.getByRole('button',{name:'Koppeling herstellen op deze server',exact:true}).click();
    await app.getByText('Serverkoppeling hersteld op deze browser. Profielen en openstaande lokale acties zijn niet teruggezet.',{exact:true}).waitFor();
    check(responses.length===requestCountBeforeImport+2,'Explicit restore did not make exactly the two read-only verification requests');
    check(responses.slice(-2).every(item=>item.method==='GET'&&item.authorized&&(item.path.endsWith('/episode')||item.path.endsWith('/retention'))),'Access restore did not make only authorized, read-only verification requests');
    check(errors.length===0,`Browser errors: ${errors.join(' | ')}`);
    for(const width of [320,390,1280]) {
      await app.setViewportSize({width,height:844});
      check(await app.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`Horizontal overflow at ${width}px`);
    }
    return 'PASS: profile/settings localization, encrypted reconnect retry, access backup and explicit same-origin restore, editable recovery text and recipient subset, no premature acceptance, privacy and mobile widths';
  } finally { await context.close(); }
}
