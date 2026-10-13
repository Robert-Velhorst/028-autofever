async (page) => {
  const failures = [];
  const browser = page.context().browser();
  const check = (value, message) => { if (!value) throw Error(message); };
  const test = async (name, fn) => {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const p = await context.newPage();
    try {
      await p.goto(page.url());
      await p.getByRole('button', { name: 'Profielen', exact: true }).waitFor();
      await p.getByRole('heading').first().waitFor();
      await fn(p);
      console.log('PASS ' + name);
    } catch (error) { failures.push(name + ': ' + error.message); console.log('FAIL ' + name + ': ' + error.message); }
    finally { await context.close(); }
  };
  const edit = async p => {
    await p.getByRole('button', { name: 'Profielen', exact: true }).click();
    await p.locator('article').first().getByRole('button', { name: 'Bewerken', exact: true }).click();
  };
  await test('Concept survives navigation and reload without changing live profile', async p => {
    await edit(p);
    await p.getByLabel('Standaardbericht', { exact: true }).fill('Dit is mijn nog niet gepubliceerde concept.');
    await p.getByRole('button', { name: 'Thuis', exact: true }).click();
    await p.reload();
    await edit(p);
    check(await p.getByLabel('Standaardbericht', { exact: true }).inputValue() === 'Dit is mijn nog niet gepubliceerde concept.', 'Unpublished text was lost');
    await p.getByRole('button', { name: 'Thuis', exact: true }).click();
    await p.getByRole('button', { name: 'Ik ben ziek', exact: false }).click();
    await p.getByText('Actieve preview. Deze berichten en taken zijn voorbereid; er is niets verstuurd.', { exact: true }).waitFor();
    check((await p.locator('main').innerText()).includes('Ik ben onverwacht ziek en neem rust.'), 'Published profile was not used for activation');
    check(!(await p.locator('main').innerText()).includes('Dit is mijn nog niet gepubliceerde concept.'), 'Draft leaked into activation');
  });
  await test('Optional message editor stays hidden until requested', async p => {
    await edit(p);
    const people = p.locator('summary').filter({ hasText: 'Personen' });
    if (await people.count()) await people.click();
    check(!await p.getByLabel('Eigen bericht voor Maya', { exact: true }).isVisible(), 'Empty override occupies mobile space');
    await p.getByLabel('Ander bericht voor Maya', { exact: true }).check();
    check(await p.getByLabel('Eigen bericht voor Maya', { exact: true }).isVisible(), 'Override toggle did not reveal editor');
  });
  await test('Email delivery choice requires an email address', async p => {
    await p.getByRole('button', { name: 'Personen', exact: true }).click();
    await p.getByRole('button', { name: 'Persoon toevoegen', exact: true }).click();
    await p.getByLabel('Naam', { exact: true }).fill('Kanaalcontrole');
    await p.getByLabel('Groep', { exact: true }).fill('Vrienden');
    await p.getByLabel('Email', { exact: true }).check();
    await p.getByRole('button', { name: 'Persoon opslaan', exact: true }).click();
    await p.waitForTimeout(200);
    check(await p.getByLabel('E-mailadres', { exact: true }).isVisible(), 'Invalid contact was saved');
    check((await p.locator('[role=alert]').innerText()).toLowerCase().includes('e-mail'), 'No actionable email error');
    await p.getByRole('button', { name: 'Thuis', exact: true }).click();
    await p.reload();
    await p.getByRole('button', { name: 'Personen', exact: true }).click();
    await p.getByRole('button', { name: 'Persoon toevoegen', exact: true }).click();
    check(await p.getByLabel('Naam', { exact: true }).inputValue() === 'Kanaalcontrole', 'Contact concept was lost');
    await p.getByLabel('E-mailadres', { exact: true }).fill('contact@example.invalid');
    await p.getByRole('button', { name: 'Persoon opslaan', exact: true }).click();
    await p.getByRole('heading', { name: 'Jouw mensen.', exact: true }).waitFor();
    check((await p.locator('main').innerText()).includes('Kanaalcontrole'), 'Valid contact could not be saved');
  });
  await test('Home exposes incomplete saved configuration before activation', async p => {
    check((await p.locator('main').innerText()).includes('Ontbrekende gegevens'), 'Readiness omissions hidden until activation');
    check((await p.locator('main').innerText()).includes('3 ontvangers'), 'Recipient count missing');
  });
  await test('Navigation moves accessible focus to page heading', async p => {
    await p.getByRole('button', { name: 'Personen', exact: true }).click();
    check(await p.evaluate(() => document.activeElement.tagName === 'H1'), 'Focus left on stale navigation instead of new page');
  });
  if (failures.length) throw Error(failures.join('\n'));
  return 'PASS: 5 checks — persisted separate concept, optional override, email validation, readiness and accessible navigation';
}
