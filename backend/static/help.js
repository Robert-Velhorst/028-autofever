'use strict';
(() => {
  const copy = {
    nl: {
      title: 'Autofever · Een beetje hulp', heading: 'Een beetje hulp.<br>Meer rust.',
      intro: 'Een persoonlijk bericht voor jou. Je hebt geen account nodig om te reageren.',
      loading: 'Je bericht wordt opgehaald…', refresh: 'Gegevens vernieuwen', retry: 'Opnieuw ophalen',
      message: 'Het bericht', acknowledge: 'Ik heb dit gelezen', acknowledged: 'Lezen bevestigd',
      ackCopy: 'Deze leesbevestiging geldt voor het oorspronkelijke bericht, niet voor latere updates.',
      ackHint: 'Alleen openen telt niet als een bevestiging.', updates: 'Updates voor jou',
      tasks: 'Kun je iets doen?', tasksIntro: 'Kies wat lukt. Nee zeggen mag ook.',
      noTasks: 'Er zijn geen hulpvragen voor jou.', footer: 'Deze link geeft toegang tot jouw bericht. Deel hem niet. Bij opnieuw laden open je de oorspronkelijke link opnieuw.',
      noScript: 'Schakel JavaScript in om je persoonlijke bericht te openen en te reageren.',
      unavailable: 'Deze link is niet beschikbaar. Open de oorspronkelijke link, of vraag de afzender om een nieuwe.',
      fetching: 'Gegevens worden opgehaald…', saving: 'Je reactie wordt opgeslagen…', saved: 'Je reactie is opgeslagen.',
      conflict: 'Deze taak is intussen gewijzigd. Haal de actuele gegevens op.',
      unknown: 'De actuele stand kon niet worden opgehaald. Je reactie is mogelijk al opgeslagen. Haal de gegevens opnieuw op voordat je verdergaat.',
      available: 'Nog beschikbaar', declined: 'Je hebt aangegeven dat dit niet lukt.',
      acceptedByYou: 'Jij pakt dit op.', acceptedByOther: 'Iemand anders pakt dit op.',
      completed: 'Afgerond. Dank je wel.', closed: 'Deze hulpvraag is gesloten.',
      accept: 'Ik pak dit op', acceptAfterDecline: 'Ik kan toch helpen', decline: 'Lukt me niet', complete: 'Dit is gedaan',
      switchLanguage: 'Wissel naar Engels',
    },
    en: {
      title: 'Autofever · A little help', heading: 'A little help.<br>More peace of mind.',
      intro: 'A personal message for you. You do not need an account to respond.',
      loading: 'Loading your message…', refresh: 'Refresh information', retry: 'Try again',
      message: 'The message', acknowledge: 'I have read this', acknowledged: 'Reading confirmed',
      ackCopy: 'This confirmation applies to the original message, not to later updates.',
      ackHint: 'Opening the page alone does not count as confirmation.', updates: 'Updates for you',
      tasks: 'Can you help?', tasksIntro: 'Choose what works for you. It is okay to say no.',
      noTasks: 'There are no help requests for you.', footer: 'This link gives access to your message. Do not share it. If you reload, open the original link again.',
      noScript: 'Enable JavaScript to open your personal message and respond.',
      unavailable: 'This link is unavailable. Open the original link or ask the sender for a new one.',
      fetching: 'Loading the latest information…', saving: 'Saving your response…', saved: 'Your response has been saved.',
      conflict: 'This task has changed. Refresh to see the latest information.',
      unknown: 'The latest status could not be retrieved. Your response may already have been saved. Refresh before continuing.',
      available: 'Available', declined: 'You said you cannot help with this.',
      acceptedByYou: 'You are taking this on.', acceptedByOther: 'Someone else is taking this on.',
      completed: 'Completed. Thank you.', closed: 'This help request is closed.',
      accept: 'I can help', acceptAfterDecline: 'I can help after all', decline: 'I cannot help', complete: 'This is done',
      switchLanguage: 'Switch language to Dutch',
    }
  };
  const localeKey = 'autofever-language';
  let locale = 'nl';
  try { if (localStorage.getItem(localeKey) === 'en') locale = 'en'; } catch { /* Language choice remains available for this page. */ }
  const t = key => copy[locale][key];
  let noticeKey = 'loading';
  const setNotice = key => { noticeKey = key; notice.textContent = key ? t(key) : ''; };
  function applyLanguage() {
    const english = locale === 'en';
    document.documentElement.lang = locale;
    document.title = t('title');
    document.getElementById('page-title').innerHTML = t('heading');
    document.getElementById('page-intro').textContent = t('intro');
    document.getElementById('notice').textContent = t('loading');
    document.getElementById('message-title').textContent = t('message');
    document.getElementById('ack-copy').textContent = t('ackCopy');
    document.getElementById('ack-hint').textContent = t('ackHint');
    document.getElementById('updates').setAttribute('aria-label', t('updates'));
    document.getElementById('tasks-title').textContent = t('tasks');
    document.getElementById('tasks-intro').textContent = t('tasksIntro');
    document.getElementById('page-footer').textContent = t('footer');
    const noscript = document.getElementById('noscript-copy');
    if (noscript) noscript.textContent = t('noScript');
    const language = byId('language');
    language.textContent = english ? 'Nederlands' : 'English';
    language.lang = english ? 'nl' : 'en';
    language.setAttribute('aria-label', t('switchLanguage'));
    if (currentData) render(currentData);
    else if (!token) unavailable();
    else setNotice(noticeKey);
  }

  let token = location.hash.slice(1);
  history.replaceState(null, '', location.pathname); // Do not retain capability in page history.
  const byId = id => document.getElementById(id);
  const content = byId('content'), notice = byId('notice'), refresh = byId('refresh');
  let busy = false, linkGeneration = 0, currentData = null;

  function lock(value) {
    busy = value;
    content.setAttribute('aria-busy', String(value));
    document.querySelectorAll('button').forEach(button => {
      button.disabled = value || button.dataset.finished === 'true';
    });
  }

  function clear() {
    currentData = null;
    content.hidden = true;
    byId('message').textContent = '';
    byId('tasks').replaceChildren();
    byId('updates').replaceChildren();
  }

  function unavailable() {
    token = '';
    clear();
    refresh.hidden = true;
    setNotice('unavailable');
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
    currentData = data;
    noticeKey = '';
    byId('message').textContent = data.message;
    const ack = byId('acknowledge');
    ack.textContent = data.acknowledged ? t('acknowledged') : t('acknowledge');
    ack.dataset.finished = String(data.acknowledged);
    byId('tasks').replaceChildren();
    byId('updates').replaceChildren();
    if(data.updates?.length) {
      byId('updates').append(node('h2', t('updates')));
      for(const update of data.updates) {
        const article = node('article','','task');
        article.append(node('p',update.message),node('p',new Date(update.created_at*1000).toLocaleString(locale === 'en' ? 'en-GB' : 'nl-NL')));
        byId('updates').append(article);
      }
    }
    for (const task of data.tasks) {
      const article = node('article', '', 'task');
      article.append(node('h3', task.title), node('p', task.timing));
      if (task.description) article.append(node('p', task.description));
      let label = t('available');
      if (task.status === 'pending' && task.declined_by_you) label = t('declined');
      if (task.status === 'accepted') label = task.claimed_by_you ? t('acceptedByYou') : t('acceptedByOther');
      if (task.status === 'completed') label = t('completed');
      if (task.status === 'closed') label = t('closed');
      article.append(node('p', label, 'task-state'));
      const actions = node('div', '', 'actions');
      const add = (text, action, secondary = false) => {
        const button = node('button', text, secondary ? 'secondary' : '');
        button.addEventListener('click', () => update('/task-responses', {task_id: task.id, action}));
        actions.append(button);
      };
      if (task.status === 'pending') {
        add(task.declined_by_you ? t('acceptAfterDecline') : t('accept'), 'accept');
        if (!task.declined_by_you) add(t('decline'), 'decline', true);
      }
      if (task.status === 'accepted' && task.claimed_by_you) add(t('complete'), 'complete');
      article.append(actions);
      byId('tasks').append(article);
    }
    if (!data.tasks.length) byId('tasks').append(node('p', t('noTasks'), 'task'));
    content.hidden = false;
    refresh.hidden = false;
    refresh.textContent = t('refresh');
  }

  async function update(path = '', body) {
    if (busy || !token) return;
    const generation = linkGeneration;
    lock(true);
    setNotice(body === undefined ? 'fetching' : 'saving');
    try {
      const data = await request(path, body);
      if(generation !== linkGeneration) return;
      render(data);
      setNotice(body === undefined ? '' : 'saved');
    } catch (error) {
      if(generation !== linkGeneration) return;
      if (error.status === 404) unavailable();
      else {
        clear(); // Never leave stale controls usable after an unknown outcome.
        refresh.hidden = false;
        refresh.textContent = t('retry');
        setNotice(error.status === 409 ? 'conflict' : 'unknown');
      }
    } finally {
      if(generation === linkGeneration) {
        lock(false);
        if (body !== undefined) notice.focus();
      }
    }
  }

  byId('acknowledge').addEventListener('click', () => update('/acknowledgment', {}));
  byId('language').addEventListener('click', () => {
    locale = locale === 'nl' ? 'en' : 'nl';
    try { localStorage.setItem(localeKey, locale); } catch { /* Keep the selection for this page. */ }
    applyLanguage();
  });
  refresh.addEventListener('click', () => update());
  window.addEventListener('pagehide', clear);
  window.addEventListener('pageshow', event => { if (event.persisted) update(); });
  window.addEventListener('hashchange', () => {
    linkGeneration++;
    token = location.hash.slice(1);
    history.replaceState(null, '', location.pathname);
    busy = false;
    clear(); // Never show the previous person's data while switching links.
    if(/^[A-Za-z0-9_-]{43}$/.test(token)) update();
    else unavailable();
  });
  applyLanguage();
  if (/^[A-Za-z0-9_-]{43}$/.test(token)) update();
  else unavailable();
})();
