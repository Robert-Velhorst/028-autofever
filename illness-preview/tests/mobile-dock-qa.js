async(page)=>{
 const context=await page.context().browser().newContext({viewport:{width:390,height:844}});const p=await context.newPage();
 try{await p.goto(page.url());await p.getByRole('button',{name:'Profielen',exact:true}).click();await p.locator('article').first().getByRole('button',{name:'Bewerken',exact:true}).click();
 const obscured=await p.locator('summary,input,textarea').evaluateAll(elements=>elements.filter(el=>{const r=el.getBoundingClientRect();if(!r.width||!r.height)return false;const y=r.y+r.height/2;const main=document.querySelector('main').getBoundingClientRect();if(y<Math.max(0,main.top)||y>Math.min(innerHeight,main.bottom))return false;const top=document.elementFromPoint(r.x+r.width/2,y);return top&&!el.contains(top)&&top!==el;}).map(el=>el.textContent||el.id));
 if(obscured.length)throw Error('Save controls cover editor content: '+obscured.join(', '));
 for(const s of await p.locator('summary').all()){await s.scrollIntoViewIfNeeded();await s.click();}
 return 'PASS: visible editor controls are not covered by the save bar';
 }finally{await context.close();}
}
