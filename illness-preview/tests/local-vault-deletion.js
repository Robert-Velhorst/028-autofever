async (page) => {
  const browser = page.context().browser();
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const a = await context.newPage();
  const b = await context.newPage();
  const check = (value, message) => { if (!value) throw Error(message); };
  try {
    await a.goto(page.url());
    await a.getByRole('heading').first().waitFor();
    await b.addInitScript(() => { window.BroadcastChannel = undefined; });
    await b.goto(page.url());
    await b.getByRole('heading').first().waitFor();
    await b.getByRole('button', { name: 'Profielen', exact: true }).click();
    await b.locator('article').first().getByRole('button', { name: 'Bewerken', exact: true }).click();
    await b.getByLabel('Standaardbericht', { exact: true }).fill('Verouderde tab mag dit niet terugschrijven');

    a.once('dialog', dialog => dialog.accept());
    await a.getByRole('button', { name: 'Instellingen', exact: true }).click();
    await a.getByLabel('Typ WIS LOKALE DATA om te bevestigen').fill('WIS LOKALE DATA');
    await a.getByRole('button', { name: 'Alle Autofever-gegevens op deze browser wissen' }).click();
    await a.getByRole('button', { name: 'Instellingen', exact: true }).waitFor();
    await a.waitForFunction(() => document.querySelector('#local-delete-confirm') === null);

    await b.getByRole('button', { name: 'Profiel opslaan', exact: true }).click();
    await b.getByText(/gewist in een andere tab/i).waitFor();
    check(await b.getByLabel('Standaardbericht', { exact: true }).inputValue() === 'Verouderde tab mag dit niet terugschrijven', 'Stale editor input was lost instead of clearly rejected');
    const keys = await a.evaluate(() => new Promise((resolve, reject) => {
      const request = indexedDB.open('autofever-editable-preview-v1');
      request.onerror = () => reject(request.error);
      request.onsuccess = () => {
        const tx = request.result.transaction('vault');
        const read = tx.objectStore('vault').getAllKeys();
        read.onsuccess = () => resolve(read.result);
        read.onerror = () => reject(read.error);
      };
    }));
    check(!keys.includes('data') && !keys.includes('concepts') && !keys.includes('connection'), 'Local deletion left saved personal records or the server connection');
    return 'PASS: confirmed local deletion clears saved records and server connection; stale tab cannot restore data';
  } finally { await context.close(); }
}
