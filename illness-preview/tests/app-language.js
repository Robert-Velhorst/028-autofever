async (page) => {
  const check=(value,message)=>{if(!value)throw Error(message);};
  const browser=page.context().browser();
  const context=await browser.newContext({viewport:{width:390,height:844}});
  const app=await context.newPage();
  const errors=[];
  app.on('pageerror',error=>errors.push(error.message));
  app.on('console',message=>{if(message.type()==='error')errors.push(message.text());});
  const base=new URL(page.url());
  const ownerUrl=new URL('/owner',base).href;
  const senderMessage='Ik ben onverwacht ziek. Laat me vooral even weten hoe het gaat.';
  let episode={
    id:'synthetic-episode',state:'active',
    snapshot:{preparation:{profile:{name:'Synthetic episode',duration:'',recovery:'',tasks:[]},contacts:[{id:'maya',name:'Maya'}]},recipients:[{id:'maya',message:senderMessage}],tasks:[]},
    notifications:[{recipient:'maya',kind:'illness',status:'accepted'}],
    recipients:[{id:'maya',acknowledged:false}],tasks:[],updates:[],
    checkin:{due:true,next_due_at:1800000000,interval_hours:4}
  };
  const responses=[];
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
      responses.push({path,method:request.method()});
      if(path.endsWith('/episode')) return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({data:episode})});
      if(path.endsWith('/retention')) return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({data:{retention_days:null}})});
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
    check(errors.length===0,`Browser errors: ${errors.join(' | ')}`);
    for(const width of [320,390,1280]) {
      await app.setViewportSize({width,height:844});
      check(await app.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`Horizontal overflow at ${width}px`);
    }
    return 'PASS: profile/settings/owner interface localization, unsaved input preservation, private message preservation and mobile widths';
  } finally { await context.close(); }
}
