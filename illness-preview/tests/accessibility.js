async (page) => {
  const context = await page.context().browser().newContext({ viewport: { width: 390, height: 844 } });
  const p = await context.newPage();
  const check = (value, message) => { if (!value) throw Error(message); };
  const click = name => p.getByRole('button', { name, exact: true }).click();
  try {
    await p.goto(page.url());
    await click('Instellingen');
    check(await p.getByRole('button', { name: 'Grotere tekst', exact: true }).count() === 1, 'Larger-text setting is missing');
    await p.getByRole('button', { name: 'Grotere tekst', exact: true }).focus();
    await p.keyboard.press('Enter');
    await p.getByRole('button', { name: 'Grotere tekst', exact: true, pressed: true }).waitFor();
    await click('Hoog contrast');
    await p.getByRole('button', { name: 'Hoog contrast', exact: true, pressed: true }).waitFor();
    await p.reload();
    await click('Instellingen');
    check(await p.getByRole('button', { name: 'Grotere tekst', exact: true }).getAttribute('aria-pressed') === 'true', 'Larger text did not persist');
    check(await p.getByRole('button', { name: 'Hoog contrast', exact: true }).getAttribute('aria-pressed') === 'true', 'High contrast did not persist');
    await click('Profielen');
    await p.locator('article').first().getByRole('button', { name: 'Bewerken', exact: true }).click();
    const help=p.locator('summary').filter({hasText:'Hulp'});
    await help.focus();await p.keyboard.press('Enter');
    check(await p.getByRole('button',{name:'Hulptaak toevoegen',exact:true}).isVisible(),'Keyboard cannot expand help section');
    check(await p.getByLabel('Standaardbericht', { exact: true }).evaluate(el => parseFloat(getComputedStyle(el).fontSize) >= 20), 'Editing text did not grow');
    for (const size of [{ width: 320, height: 568 }, { width: 390, height: 430 }, { width: 430, height: 844 }, { width: 1280, height: 800 }]) {
      await p.setViewportSize(size);
      await p.getByLabel('Standaardbericht', { exact: true }).focus();
      check(await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Page overflows at ' + JSON.stringify(size));
      check(await p.locator('main').evaluate(el => el.scrollWidth <= el.clientWidth), 'Editor overflows at ' + JSON.stringify(size));
      check(await p.getByRole('button', { name: 'Profiel opslaan', exact: true }).isVisible(), 'Save button is inaccessible at ' + JSON.stringify(size));
    }
    await p.setViewportSize({ width: 390, height: 844 });
    // Turning the preferences off restores the saved default presentation.
    await p.getByRole('button', { name: 'Thuis', exact: true }).click();
    await click('Instellingen');
    await click('Grotere tekst');
    await click('Hoog contrast');
    await p.reload();await click('Instellingen');
    check(await p.getByRole('button', { name: 'Grotere tekst', exact: true }).getAttribute('aria-pressed') === 'false', 'Larger text cannot be turned off');
    return 'PASS: optional large text and contrast, persistence, editor typography and small-screen reflow';
  } finally { await context.close(); }
}
