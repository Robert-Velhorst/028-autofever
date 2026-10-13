async (page) => {
  const check = (value,message) => { if(!value) throw Error(message); };
  const browser = page.context().browser();
  const context = await browser.newContext({viewport:{width:390,height:844}});
  const helper = await context.newPage();
  const pageErrors = [];
  helper.on('pageerror', error => pageErrors.push(error.message));
  helper.on('console', message => { if(message.type() === 'error') pageErrors.push(message.text()); });
  const message = 'Oorspronkelijk bericht: breng alsjeblieft soep.';
  const latest = {
    message,
    acknowledged: false,
    updates: [{message:'Nederlandse update blijft ongewijzigd.',created_at:1800000000}],
    tasks: [{id:'soup',title:'Soep brengen',description:'Zet de soep bij de deur.',timing:'Vandaag',status:'pending',declined_by_you:false,claimed_by_you:false}]
  };
  await helper.route('**/api/v1/recipient**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith('/task-responses')) {
      latest.tasks[0].status = request.postDataJSON().action === 'complete' ? 'completed' : 'accepted';
      latest.tasks[0].claimed_by_you = true;
    }
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({data:structuredClone(latest)})});
  });
  try {
    const target = new URL('../backend/static/help.html', page.url());
    target.hash = 'a'.repeat(43);
    await helper.goto(target.href);
    try { await helper.getByRole('heading',{name:'Kun je iets doen?'}).waitFor({timeout:5000}); }
    catch { throw Error(`Dutch helper page did not render; title=${await helper.title()}, body=${await helper.locator('body').innerText()}, errors=${pageErrors.join(' | ')}`); }
    check(await helper.locator('html').getAttribute('lang') === 'nl','Dutch should remain the default language');
    check(await helper.getByText(message,{exact:true}).count() === 1,'Sender-authored message was not shown as written');
    await helper.getByRole('button',{name:'Wissel naar Engels',exact:true}).click();
    await helper.getByRole('heading',{name:'Can you help?'}).waitFor();
    check(await helper.locator('html').getAttribute('lang') === 'en','Document language was not updated');
    check((await helper.title()).includes('A little help'),'Document title was not translated');
    check(await helper.getByRole('button',{name:'I can help',exact:true}).count() === 1,'Task action was not translated');
    check(await helper.getByText(message,{exact:true}).count() === 1,'Changing interface language altered the sender-authored message');
    await helper.getByRole('button',{name:'I can help',exact:true}).click();
    await helper.getByText('You are taking this on.',{exact:true}).waitFor();
    await helper.getByRole('button',{name:'This is done',exact:true}).click();
    await helper.getByText('Completed. Thank you.',{exact:true}).waitFor();
    await helper.goto(target.href);
    await helper.getByRole('heading',{name:'Can you help?'}).waitFor();
    check(await helper.locator('html').getAttribute('lang') === 'en','English preference did not persist on this device');
    await helper.getByRole('button',{name:'Switch language to Dutch',exact:true}).click();
    await helper.getByRole('heading',{name:'Kun je iets doen?'}).waitFor();
    check(await helper.getByRole('button',{name:'Ik heb dit gelezen',exact:true}).count() === 1,'Dutch message acknowledgment was not restored');
    for(const width of [320,390,1280]) {
      await helper.setViewportSize({width,height:844});
      check(await helper.evaluate(() => document.documentElement.scrollWidth <= innerWidth),`Horizontal overflow at ${width}px`);
    }
    check(pageErrors.length === 0,`Browser reported errors: ${pageErrors.join(' | ')}`);
    return 'PASS: Dutch/English helper UI, task actions, user-authored message preservation and local language preference';
  } finally { await context.close(); }
}
