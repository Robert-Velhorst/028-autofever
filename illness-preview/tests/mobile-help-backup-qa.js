async (page) => {
  const browser = page.context().browser();
  const context = await browser.newContext({viewport:{width:390,height:844},acceptDownloads:true});
  const p = await context.newPage();
  const errors=[];p.on('pageerror',e=>errors.push(e.message));
  const check=(ok,msg)=>{if(!ok)throw Error(msg)};
  const click=name=>p.getByRole('button',{name,exact:true}).click();
  const failures=[];
  try {
    await p.goto(page.url());
    await click('Profielen');
    await p.locator('article').first().getByRole('button',{name:'Bewerken',exact:true}).click();
    await p.locator('summary').filter({hasText:'Hulp'}).click();
    if(!await p.getByLabel('Wanneer?',{exact:true}).count())failures.push('No task timing editor');
    else {
      await p.getByLabel('Wanneer?',{exact:true}).first().fill('Vandaag vóór 18:00');
      await p.getByLabel('Herhalen',{exact:true}).first().selectOption('daily');
      await p.getByLabel('Reservepersoon',{exact:true}).first().selectOption('lou');
      await click('Profiel opslaan');await click('Thuis');
      await p.getByRole('button',{name:'Ik ben ziek',exact:false}).click();
      await p.getByText('Actieve preview. Deze berichten en taken zijn voorbereid; er is niets verstuurd.',{exact:true}).waitFor();
      const main=await p.locator('main').innerText();
      for(const expected of ['Vandaag vóór 18:00','Dagelijks','Reserve: Lou','Nog niet gevraagd'])check(main.includes(expected),'Task snapshot missing '+expected);
      await click('Ik ben hersteld');await click('Terug naar thuis');
    }
    if(!await p.getByRole('button',{name:'Instellingen',exact:true}).count())failures.push('No backup/restore settings');
    else {
      await click('Instellingen');
      await click('Grotere tekst');
      await p.getByRole('button',{name:'Grotere tekst',exact:true,pressed:true}).waitFor();
      await p.getByLabel('Wachtzin voor back-up',{exact:true}).fill('Mijn testzin met voldoende lengte 2026');
      await p.getByLabel('Herhaal de wachtzin',{exact:true}).fill('Mijn testzin met voldoende lengte 2026');
      const downloadPromise=p.waitForEvent('download');await click('Versleutelde back-up downloaden');
      const download=await downloadPromise;const stream=await download.createReadStream();const chunks=[];for await(const chunk of stream)chunks.push(chunk);const buffer=chunks[0].constructor.concat(chunks);
      check(!buffer.toString().includes('Vandaag vóór 18:00'),'Backup exposes task content');
      const envelope=JSON.parse(buffer.toString());check(envelope.format==='autofever-backup','No versioned backup envelope');
      const damaged={...envelope,body:(envelope.body[0]==='A'?'B':'A')+envelope.body.slice(1)};
      await p.getByLabel('Back-upbestand',{exact:true}).setInputFiles({name:'damaged.afbackup',mimeType:'application/json',buffer:buffer.constructor.from(JSON.stringify(damaged))});
      await p.getByLabel('Wachtzin van de back-up',{exact:true}).fill('Mijn testzin met voldoende lengte 2026');await click('Back-up controleren');
      await p.getByText('Back-up kon niet worden geopend.',{exact:false}).waitFor();
      check(!await p.getByRole('button',{name:'Gegevens vervangen',exact:true}).count(),'Tampered encrypted backup was accepted');
      await p.getByLabel('Back-upbestand',{exact:true}).setInputFiles({name:'autofever.afbackup',mimeType:'application/json',buffer});
      await p.getByLabel('Wachtzin van de back-up',{exact:true}).fill('Verkeerde wachtzin');await click('Back-up controleren');
      await p.getByText('Back-up kon niet worden geopend.',{exact:false}).waitFor();
      check(!await p.getByRole('button',{name:'Gegevens vervangen',exact:true}).count(),'Wrong password allowed replacement');
      await p.getByLabel('Wachtzin van de back-up',{exact:true}).fill('Mijn testzin met voldoende lengte 2026');await click('Back-up controleren');
      await p.getByRole('button',{name:'Gegevens vervangen',exact:true}).waitFor();
      p.once('dialog',d=>d.accept());await click('Gegevens vervangen');
      await p.getByText('Back-up teruggezet op deze browser.',{exact:true}).waitFor();
      await p.reload();await click('Instellingen');
      check(await p.getByRole('button',{name:'Grotere tekst',exact:true}).getAttribute('aria-pressed')==='true','Restoring a backup lost the readability preference');
      await click('Profielen');
      await p.locator('article').first().getByRole('button',{name:'Bewerken',exact:true}).click();
      await p.locator('summary').filter({hasText:'Hulp'}).click();
      check(await p.getByLabel('Wanneer?',{exact:true}).first().inputValue()==='Vandaag vóór 18:00','Restore lost task timing');
      for(const width of [320,390,430,1280]){await p.setViewportSize({width,height:844});check(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Horizontal overflow '+width);}
    }
    check(errors.length===0,'Browser errors: '+errors.join(';'));
    if(failures.length)throw Error(failures.join(';'));
    return 'PASS: task schedule and backup snapshot, honest unsent status, encrypted download, wrong password rejection, restore, responsive widths';
  }finally{await context.close();}
}
