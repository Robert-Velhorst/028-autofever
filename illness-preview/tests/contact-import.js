async (page) => {
  const browser = page.context().browser();
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const p = await context.newPage();
  const check = (value, message) => { if (!value) throw Error(message); };
  const externalRequests = [];
  p.on('request', request => { if (new URL(request.url()).origin !== new URL(page.url()).origin) externalRequests.push(request.url()); });
  const vcard = [
    'BEGIN:VCARD', 'VERSION:3.0', 'FN:Noor Example', 'N:Example;Noor;;;',
    'ORG:Software\\, Team', 'TEL;TYPE=CELL:+31612345678',
    'EMAIL;TYPE=HOME:noor@example.invalid', 'EMAIL;TYPE=WORK:noor.work@example.invalid', 'END:VCARD',
    'BEGIN:VCARD', 'VERSION:2.1', 'N:Voorbeeld;Rosa;;;',
    'EMAIL;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:rosa=2Eexample@example.invalid', 'END:VCARD'
  ].join('\r\n');
  const upload = async () => p.locator('#vcard-file').evaluate((input, contents) => {
    const transfer = new DataTransfer();
    transfer.items.add(new File([contents], 'contacts.vcf', { type: 'text/vcard' }));
    input.files = transfer.files;
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }, vcard);
  try {
    await p.goto(page.url());
    await p.getByRole('button', { name: 'Personen', exact: true }).click();
    await p.getByRole('button', { name: 'Importeer vCard', exact: true }).click();
    await upload();
    const review = p.locator('#vcard-review');
    await review.getByRole('heading', { name: 'Controleer de import' }).waitFor();
    check((await review.innerText()).includes('2 contacten gevonden · 0 bestaand of dubbel · 2 geselecteerd'), 'Review did not show parsed contacts and safe defaults');
    check(await review.getByLabel('E-mailadres').first().locator('option').count() === 3, 'Multiple email choices were discarded');
    check(await review.getByLabel('Groep', { exact: true }).first().inputValue() === 'Software, Team', 'Escaped vCard organization was not decoded');
    check((await review.innerText()).includes('rosa.example@example.invalid'), 'Quoted-printable vCard email was not decoded');
    await p.setViewportSize({ width: 320, height: 740 });
    check(await p.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), 'Import review overflows a 320px phone viewport');
    await review.getByRole('button', { name: 'Importeer 2 contacten', exact: true }).click();
    await p.getByText('2 contacten lokaal toegevoegd. Kies later zelf een bezorgkanaal en profiel.', { exact: true }).waitFor();
    check((await p.locator('main').innerText()).includes('Nog geen bezorgkanaal gekozen'), 'Imported contacts were automatically given a delivery channel');
    await p.getByRole('button', { name: 'Profielen', exact: true }).click();
    await p.locator('article').first().getByRole('button', { name: 'Bewerken', exact: true }).click();
    check(await p.locator('input[name=recipient]:checked').count() === 3, 'Import silently added contacts to an existing profile');
    await p.reload();
    await p.getByRole('button', { name: 'Personen', exact: true }).click();
    check((await p.locator('main').innerText()).includes('Noor Example') && (await p.locator('main').innerText()).includes('Rosa Voorbeeld'), 'Imported contacts did not persist locally');
    await p.getByRole('button', { name: 'Importeer vCard', exact: true }).click();
    await upload();
    const duplicateReview = p.locator('#vcard-review');
    await duplicateReview.getByRole('heading', { name: 'Controleer de import' }).waitFor();
    check((await duplicateReview.innerText()).includes('2 bestaand of dubbel · 0 geselecteerd'), 'Duplicate contacts were not excluded');
    check(await duplicateReview.getByRole('button', { name: 'Importeer 0 contacten', exact: true }).isDisabled(), 'Duplicate-only import remained actionable');
    await duplicateReview.getByRole('button', { name: 'Annuleren', exact: true }).click();
    check((await p.locator('main').innerText()).includes('Noor Example'), 'Cancel removed existing imported contacts');
    check(await p.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), 'Import review overflows a 390px mobile viewport');
    check(externalRequests.length === 0, 'Local contact import made a request outside the app origin');
  } finally { await context.close(); }
  return 'PASS: vCard parsing, duplicate review, explicit import, local persistence, no channel/recipient consent, cancellation and mobile layout';
}
