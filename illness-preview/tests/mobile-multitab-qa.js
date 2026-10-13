async(page)=>{
 const context=await page.context().browser().newContext({viewport:{width:390,height:844}});const a=await context.newPage(),b=await context.newPage();
 const entry=page.url();
 const edit=async(p,index)=>{await p.getByRole('button',{name:'Profielen',exact:true}).click();await p.locator('article').nth(index).getByRole('button',{name:'Bewerken',exact:true}).click();};
 try{await a.goto(entry);await a.getByRole('heading').first().waitFor();await b.goto(entry);await b.getByRole('heading').first().waitFor();
 await edit(a,0);await edit(b,1);
 await a.getByLabel('Naam van het profiel',{exact:true}).fill('Opgeslagen door tab A');await a.getByRole('button',{name:'Profiel opslaan',exact:true}).click();await a.getByRole('heading',{name:'Jouw profielen.',exact:true}).waitFor();
 await b.getByLabel('Standaardbericht',{exact:true}).fill('Concept in tab B');await b.getByRole('button',{name:'Profiel opslaan',exact:true}).click();
 await b.waitForTimeout(300);await a.reload();await a.getByRole('button',{name:'Profielen',exact:true}).click();
 if(!(await a.locator('main').innerText()).includes('Opgeslagen door tab A'))throw Error('Stale tab overwrote a published profile from another tab');
 if(!(await b.locator('#toast').innerText()).includes('andere tab'))throw Error('No actionable conflict warning');
 if(await b.getByLabel('Standaardbericht',{exact:true}).inputValue()!=='Concept in tab B')throw Error('Conflict destroyed unsaved input');
 return 'PASS: stale tab cannot overwrite saved data; conflicting input remains available';
 }finally{await context.close();}
}
