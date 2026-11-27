(() => {
  'use strict';
  const root = document.querySelector('[data-account-finance]');
  if (!root) return;
  const $ = selector => root.querySelector(selector);
  let tab = 'profile', offset = 0, limit = 20, kind = '', balanceRequest = null;
  let generation = 0, needsBalance = false, profileLoaded = false, securityLoaded = false;
  const formatDate = value => value ? new Date(value).toLocaleString('ru-RU') : 'Не сохранено';
  const amount = window.MasterCoins.format;
  const message = (text = '', error = false) => { const el = $('[data-account-message]'); el.textContent = text; el.dataset.error = String(error); };
  async function request(url, options = {}) {
    const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store', ...options});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || data.detail || (response.status === 401 ? 'Войдите в аккаунт ещё раз.' : 'Не удалось выполнить запрос.'));
    return data;
  }
  const post = (url, data) => request(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)});
  const form = (url, data) => request(url, {method: 'POST', body: new URLSearchParams(data)});
  function presentBalance(data) {
    const top = document.querySelector('#balance-label');
    if (top) { top.textContent = 'Баланс: ' + amount(data.available) + ' монет'; top.title = data.available + ' монет'; }
    $('[data-wallet-available]').textContent = amount(data.available);
    $('[data-wallet-available]').title = data.available + ' монет';
    if (data.reserved != null) { $('[data-wallet-reserved]').textContent = amount(data.reserved); $('[data-wallet-reserved]').title = data.reserved + ' монет'; }
  }
  async function refreshBalance() {
    if (balanceRequest) return balanceRequest;
    balanceRequest = request('/api/wallet/balance').then(data => { presentBalance(data); return data; }).finally(() => {
      balanceRequest = null;
      if (needsBalance) { needsBalance = false; refreshBalance().catch(() => {}); }
    });
    return balanceRequest;
  }
  function invalidateBalance() {
    if (balanceRequest) needsBalance = true;
    else refreshBalance().catch(() => {});
    if (tab === 'wallet' && !root.closest('[data-panel]')?.hidden) loadHistory().catch(e => message(e.message, true));
  }
  async function loadProfile() {
    const data = await request('/api/profile');
    $('[data-account-login]').textContent = data.login + (data.admin ? ' · Администратор' : '');
    $('[data-account-created]').textContent = data.registeredAt ? 'Зарегистрирован ' + formatDate(data.registeredAt * 1000) : '';
    profileLoaded = true;
  }
  async function loadSecurity() {
    const data = await request('/api/profile/security');
    $('[data-account-email]').textContent = data.email || 'Почта ещё не подтверждена.';
    $('[data-account-security-info]').textContent = data.admin ? 'Для администратора обязательны код из письма и приложение-аутентификатор.' : data.email ? 'Настройте дополнительное подтверждение входа.' : 'Войдите с подтверждением почты, чтобы изменить настройку.';
    const target = $('[data-account-security]');
    target.hidden = data.admin || !data.email;
    target.elements.enabled.checked = data.enabled;
    securityLoaded = true;
  }
  async function loadSessions() {
    const data = await request('/api/profile/sessions'), list = $('[data-account-sessions]');
    list.replaceChildren();
    for (const item of data.sessions) {
      const li = document.createElement('li'), content = document.createElement('div'), title = document.createElement('strong'), detail = document.createElement('small');
      title.textContent = item.current ? 'Этот сеанс' : 'Другой сеанс';
      detail.textContent = 'Последняя активность: ' + formatDate(item.lastSeenAt * 1000) + ' · действует до ' + formatDate(item.expiresAt * 1000) + (item.remembered ? ' · вход запомнен' : '');
      content.append(title, detail); li.append(content);
      if (!item.current) {
        const button = document.createElement('button'); button.type = 'button'; button.className = 'secondary'; button.textContent = 'Завершить';
        button.addEventListener('click', () => perform(button, async () => { await post('/api/profile/sessions', {action: 'revoke', sessionId: item.id}); await loadSessions(); message('Сеанс завершён.'); }));
        li.append(button);
      }
      list.append(li);
    }
    $('[data-account-revoke-others]').disabled = !data.sessions.some(item => !item.current);
  }
  async function loadHistory() {
    const current = ++generation;
    const query = new URLSearchParams({offset: String(offset), limit: String(limit), kind});
    const data = await request('/api/wallet/history?' + query);
    if (current !== generation) return;
    presentBalance(data);
    const host = $('[data-wallet-history]'); host.replaceChildren();
    if (!data.rows.length) { const p = document.createElement('p'); p.textContent = 'Операций этого типа пока нет.'; host.append(p); }
    else {
      const table = document.createElement('table'), head = table.createTHead().insertRow(), body = table.createTBody();
      for (const name of ['Дата', 'Операция', 'Монеты', 'Состояние']) { const th = document.createElement('th'); th.textContent = name; head.append(th); }
      const states = {settled: 'Учтено', pending: 'Ожидает подтверждения', succeeded: 'Оплачено', canceled: 'Отменено', refunded: 'Возвращено'};
      for (const item of data.rows) {
        const row = body.insertRow(); row.insertCell().textContent = formatDate(item.at); row.insertCell().textContent = item.reason;
        const value = row.insertCell(); value.textContent = item.kind === 'reserve' ? amount(item.reservedCoins) + ' в резерве' : item.coins == null ? '—' : amount(item.coins);
        if (item.coins != null) { const exact = document.createElement('small'); exact.textContent = item.coins.replace('.', ','); value.append(exact); }
        if (item.originalReserveCoins != null && item.kind !== 'reserve') { const reserve = document.createElement('small'); reserve.textContent = 'Резерв перед запросом: ' + item.originalReserveCoins.replace('.', ','); value.append(reserve); }
        const status = row.insertCell(); status.textContent = states[item.state] || item.state;
        if (item.rub != null) { const rub = document.createElement('small'); rub.textContent = item.rub + ' ₽'; status.append(rub); }
      }
      host.append(table);
    }
    $('[data-wallet-page]').textContent = data.total ? String(data.offset + 1) + '–' + Math.min(data.offset + data.limit, data.total) + ' из ' + data.total : '0 операций';
    $('[data-wallet-prev]').disabled = offset === 0; $('[data-wallet-next]').disabled = !data.hasMore;
  }
  async function perform(button, callback) {
    if (button.disabled) return;
    button.disabled = true; message();
    try { await callback(); } catch (error) { message(error.message, true); } finally { button.disabled = false; }
  }
  function select(next = 'profile') {
    if (!['profile', 'security', 'sessions', 'wallet'].includes(next)) next = 'profile';
    tab = next; message();
    for (const button of root.querySelectorAll('[data-account-tab]')) button.setAttribute('aria-current', button.dataset.accountTab === next ? 'page' : 'false');
    for (const section of root.querySelectorAll('[data-account-section]')) section.hidden = section.dataset.accountSection !== next;
    const load = next === 'profile' ? (profileLoaded ? Promise.resolve() : loadProfile()) : next === 'security' ? (securityLoaded ? Promise.resolve() : loadSecurity()) : next === 'sessions' ? loadSessions() : loadHistory();
    load.catch(error => message(error.message, true));
  }
  for (const button of root.querySelectorAll('[data-account-tab]')) button.addEventListener('click', () => select(button.dataset.accountTab));
  $('[data-account-password]').addEventListener('submit', event => {
    event.preventDefault(); const target = event.currentTarget, button = target.querySelector('button');
    perform(button, async () => {
      if (target.elements.password.value !== target.elements.confirmation.value) throw new Error('Новые пароли не совпадают.');
      await form('/api/profile/password', Object.fromEntries(new FormData(target))); target.reset(); message('Пароль изменён. Остальные сеансы завершены.');
    });
  });
  $('[data-account-security]').addEventListener('submit', event => {
    event.preventDefault(); const target = event.currentTarget;
    perform(target.querySelector('button'), async () => {
      await form('/api/profile/security', {current: target.elements.current.value, enabled: String(target.elements.enabled.checked)});
      target.elements.current.value = ''; await loadSecurity(); message('Настройки безопасности сохранены.');
    });
  });
  $('[data-account-revoke-others]').addEventListener('click', event => perform(event.currentTarget, async () => {
    await post('/api/profile/sessions', {action: 'others'}); await loadSessions(); message('Остальные сеансы завершены.');
  }));
  $('[data-wallet-refresh]').addEventListener('click', event => perform(event.currentTarget, loadHistory));
  $('[data-wallet-kind]').addEventListener('change', event => { kind = event.target.value; offset = 0; loadHistory().catch(e => message(e.message, true)); });
  $('[data-wallet-limit]').addEventListener('change', event => { limit = Number(event.target.value); offset = 0; loadHistory().catch(e => message(e.message, true)); });
  $('[data-wallet-prev]').addEventListener('click', () => { offset = Math.max(0, offset - limit); loadHistory().catch(e => message(e.message, true)); });
  $('[data-wallet-next]').addEventListener('click', () => { offset += limit; loadHistory().catch(e => message(e.message, true)); });
  document.addEventListener('octo-wallet-refresh', invalidateBalance);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) invalidateBalance(); });
  window.addEventListener('focus', invalidateBalance);
  window.MasterWallet = Object.freeze({refresh: refreshBalance, invalidate: invalidateBalance, format: amount});
  window.MasterAccount = Object.freeze({select, open(next) { document.dispatchEvent(new CustomEvent('master-account-open', {detail: {tab: next || 'profile'}})); }});
})();
