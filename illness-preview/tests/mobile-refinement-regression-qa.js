async (page) => {
  const context=await page.context().browser().newContext({viewport:{width:390,height:844}});
  const p=await context.newPage();const errors=[];p.on('pageerror',e=>errors.push(e.message));
  const check=(ok,msg)=>{if(!ok)throw Error(msg)};
  const click=name=>p.getByRole('button',{name,exact:true}).click();
  const open=async name=>{const s=p.locator('summary').filter({hasText:name});if(!await s.evaluate(s=>s.parentElement.open))await s.click();};
  try{
    await p.goto(page.url());
    await click('Profielen');await p.locator('article').first().getByRole('button',{name:'Bewerken',exact:true}).click();
    await p.getByLabel('Standaardbericht',{exact:true}).fill('Standaardbericht dat bewaard moet blijven.');
    await open('Personen');await p.getByLabel('Ander bericht voor Maya',{exact:true}).check();
    await p.getByLabel('Eigen bericht voor Maya',{exact:true}).fill('<img src=x onerror=alert(1)> Alleen voor Maya.');
    await open('Hulp');await click('Hulptaak toevoegen');
    check(await p.getByLabel('Wat is er nodig?',{exact:true}).last().evaluate(e=>e===document.activeElement),'New task did not receive focus');
    await p.getByLabel('Wat is er nodig?',{exact:true}).last().fill('Soep bij de deur');
    await p.getByLabel('Toelichting',{exact:true}).last().fill('Geen bel, graag.');
    await p.locator('.task-block').last().getByLabel('Maya',{exact:true}).check();
    await p.getByLabel('Wanneer?',{exact:true}).last().fill('Rond lunchtijd');
    await p.locator('.task-block').nth(1).getByRole('button',{name:'Taak verwijderen',exact:true}).click();
    check(await p.getByLabel('Wat is er nodig?',{exact:true}).last().inputValue()==='Soep bij de deur','Removing a task wiped another task');
    check(await p.getByLabel('Standaardbericht',{exact:true}).inputValue()==='Standaardbericht dat bewaard moet blijven.','Task edits wiped the message');
    await click('Profiel opslaan');await click('Thuis');await p.getByRole('button',{name:'Ik ben ziek',exact:false}).click();
    await p.getByText('Actieve preview. Deze berichten en taken zijn voorbereid; er is niets verstuurd.',{exact:true}).waitFor();
    check((await p.locator('main').innerText()).includes('<img src=x onerror=alert(1)> Alleen voor Maya.'),'Custom message missing or HTML not escaped: '+await p.locator('main').innerText());
    check(await p.locator('main img').count()===0,'User text became executable HTML');
    await click('Update schrijven');await p.getByLabel('Bericht',{exact:true}).fill('Dit updateconcept moet blijven.');await click('Thuis');
    await p.reload();await click('Update schrijven');check(await p.getByLabel('Bericht',{exact:true}).inputValue()==='Dit updateconcept moet blijven.','Update draft lost');
    await click('Update bewaren in preview');await p.getByRole('heading',{name:'Bewaarde updates',exact:true}).waitFor();
    await click('Ik ben hersteld');await click('Terug naar thuis');
    await click('Profielen');await p.locator('article').first().getByRole('button',{name:'Bewerken',exact:true}).click();
    await p.getByLabel('Standaardbericht',{exact:true}).fill('Discard this edit');
    p.once('dialog',d=>d.accept());await click('Concept verwerpen');
    await p.locator('article').first().getByRole('button',{name:'Bewerken',exact:true}).click();
    check(await p.getByLabel('Standaardbericht',{exact:true}).inputValue()==='Standaardbericht dat bewaard moet blijven.','Discard changed the published profile');
    check(await p.locator('main h1').evaluate(el=>el.getBoundingClientRect().top>=document.querySelector('main').getBoundingClientRect().top),'Reopening the editor retained stale scroll and hid its heading');
    for(const width of [320,390,430,1280]){await p.setViewportSize({width,height:844});check(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Overflow '+width);}
    await p.setViewportSize({width:390,height:844});await click('Thuis');
    check(errors.length===0,errors.join('\n'));
    return 'PASS: task edits preserve inputs, new task focus, per-person override, escaped HTML, update draft, recovery, explicit discard, mobile screenshots and widths';
  }finally{await context.close();}
}
