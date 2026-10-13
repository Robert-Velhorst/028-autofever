'use strict';
(() => {
  let token = location.hash.slice(1);
  history.replaceState(null, '', location.pathname); // Do not retain capability in page history.
  const byId = id => document.getElementById(id);
  const content = byId('content'), notice = byId('notice'), refresh = byId('refresh');
  let busy = false;

  function lock(value) {
    busy = value;
    content.setAttribute('aria-busy', String(value));
    document.querySelectorAll('button').forEach(button => {
      button.disabled = value || button.dataset.finished === 'true';
    });
  }

  function clear() {
    content.hidden = true;
    byId('message').textContent = '';
    byId('tasks').replaceChildren();
  }

  function unavailable() {
    token = '';
    clear();
    refresh.hidden = true;
    notice.textContent = 'Deze link is niet beschikbaar. Open de oorspronkelijke link, of vraag de afzender om een nieuwe.';
  }

  async function request(path, body) {
    const response = await fetch('/api/v1/recipient' + path, {
      method: body === undefined ? 'GET' : 'POST',
      headers: {Authorization: 'Bearer ' + token, ...(body === undefined ? {} : {'Content-Type': 'application/json'})},
      credentials: 'omit', cache: 'no-store', redirect: 'error',
      signal: AbortSignal.timeout(15000),
      ...(body === undefined ? {} : {body: JSON.stringify(body)})
    });
    if (!response.ok) throw Object.assign(new Error('Request failed'), {status: response.status});
    return (await response.json()).data;
  }

  function node(tag, text, className) {
    const element = document.createElement(tag);
    element.textContent = text;
    if (className) element.className = className;
    return element;
  }

  function render(data) {
    byId('message').textContent = data.message;
    const ack = byId('acknowledge');
    ack.textContent = data.acknowledged ? 'Lezen bevestigd' : 'Ik heb dit gelezen';
    ack.dataset.finished = String(data.acknowledged);
    byId('tasks').replaceChildren();
    for (const task of data.tasks) {
      const article = node('article', '', 'task');
      article.append(node('h3', task.title), node('p', task.timing));
      if (task.description) article.append(node('p', task.description));
      let label = 'Nog beschikbaar';
      if (task.status === 'pending' && task.declined_by_you) label = 'Je hebt aangegeven dat dit niet lukt.';
      if (task.status === 'accepted') label = task.claimed_by_you ? 'Jij pakt dit op.' : 'Iemand anders pakt dit op.';
      if (task.status === 'completed') label = 'Afgerond. Dank je wel.';
      if (task.status === 'closed') label = 'Deze hulpvraag is gesloten.';
      article.append(node('p', label, 'task-state'));
      const actions = node('div', '', 'actions');
      const add = (text, action, secondary = false) => {
        const button = node('button', text, secondary ? 'secondary' : '');
        button.addEventListener('click', () => update('/task-responses', {task_id: task.id, action}));
        actions.append(button);
      };
      if (task.status === 'pending') {
        add(task.declined_by_you ? 'Ik kan toch helpen' : 'Ik pak dit op', 'accept');
        if (!task.declined_by_you) add('Lukt me niet', 'decline', true);
      }
      if (task.status === 'accepted' && task.claimed_by_you) add('Dit is gedaan', 'complete');
      article.append(actions);
      byId('tasks').append(article);
    }
    if (!data.tasks.length) byId('tasks').append(node('p', 'Er zijn geen hulpvragen voor jou.', 'task'));
    content.hidden = false;
    refresh.hidden = false;
    refresh.textContent = 'Gegevens vernieuwen';
  }

  async function update(path = '', body) {
    if (busy || !token) return;
    lock(true);
    notice.textContent = body === undefined ? 'Gegevens worden opgehaald…' : 'Je reactie wordt opgeslagen…';
    try {
      render(await request(path, body));
      notice.textContent = body === undefined ? '' : 'Je reactie is opgeslagen.';
    } catch (error) {
      if (error.status === 404) unavailable();
      else {
        clear(); // Never leave stale controls usable after an unknown outcome.
        refresh.hidden = false;
        refresh.textContent = 'Opnieuw ophalen';
        notice.textContent = error.status === 409
          ? 'Deze taak is intussen gewijzigd. Haal de actuele gegevens op.'
          : 'De actuele stand kon niet worden opgehaald. Je reactie is mogelijk al opgeslagen. Haal de gegevens opnieuw op voordat je verdergaat.';
      }
    } finally {
      lock(false);
      if (body !== undefined) notice.focus();
    }
  }

  byId('acknowledge').addEventListener('click', () => update('/acknowledgment', {}));
  refresh.addEventListener('click', () => update());
  window.addEventListener('pagehide', clear);
  window.addEventListener('pageshow', event => { if (event.persisted) update(); });
  if (/^[A-Za-z0-9_-]{43}$/.test(token)) update();
  else unavailable();
})();
