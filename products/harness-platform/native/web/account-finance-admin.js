(() => {
  'use strict';
  const root = document.querySelector('[data-finance]');
  if (!root) return;
  const $ = selector => root.querySelector(selector), filter = $('[data-finance-filters]');
  let offset = 0, rows = [], selected = null, generation = 0, paymentOffset = 0, paymentGeneration = 0;
  const kinds = {tokens: 'Токены', web: 'Интернет', files: 'Файлы', audio: 'Аудио', images: 'Изображения', services: 'Другие услуги'};
  const value = amount => amount == null ? 'Не подтверждено' : String(amount).replace('.', ',');
  async function request(url, options = {}) {
    const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store', ...options});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || data.detail || 'Не удалось получить данные.');
    return data;
  }
  function table(host, columns, values) {
    host.replaceChildren(); const table = document.createElement('table'), head = table.createTHead().insertRow(), body = table.createTBody();
    for (const name of columns) { const th = document.createElement('th'); th.textContent = name; head.append(th); }
    for (const cells of values) { const row = body.insertRow(); for (const item of cells) { const td = row.insertCell(); if (item instanceof Node) td.append(item); else td.textContent = item ?? '—'; } }
    host.append(table);
  }
  function card(title, amount, caption = '') {
    const block = document.createElement('div'), heading = document.createElement('span'), number = document.createElement('strong'), note = document.createElement('small');
    heading.textContent = title; number.textContent = amount; note.textContent = caption; block.append(heading, number, note); return block;
  }
  async function load() {
    const current = ++generation, params = new URLSearchParams(new FormData(filter));
    params.set('offset', String(offset)); params.set('zone', Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC');
    $('[data-finance-status]').textContent = 'Загружаем финансовый отчёт…';
    try {
      const data = await request('/api/admin/finance?' + params);
      if (current !== generation) return;
      rows = data.rows;
      const totals = data.totals;
      $('[data-finance-summary]').replaceChildren(
        card('Расход поставщиков, ₽', value(totals.providerRub), totals.costComplete ? 'Все суммы подтверждены' : 'Подтверждено: ' + value(totals.knownProviderRub) + ' ₽'),
        card('Списано монет', value(totals.coins)), card('В резерве, монет', value(totals.reservedCoins)),
        card('Не завершено', String(totals.pending), 'Неизвестный расход: ' + totals.unknownCostAttempts));
      const summary = meter => [value(meter.providerRub), value(meter.coins), value(meter.reservedCoins), meter.input + ' / ' + meter.cache + ' / ' + meter.output, Object.entries(meter.units).map(([k, n]) => k + ': ' + n).join(', ') || '—', meter.pending];
      table($('[data-finance-breakdown]'), ['Поставщик / услуга', 'Расход, ₽', 'Монеты', 'Резерв', 'Вход / кеш / выход', 'Единицы', 'На сверке'], [
        ...Object.entries(data.providers).map(([name, meter]) => [name, ...summary(meter)]),
        ...Object.entries(data.kinds).map(([name, meter]) => [kinds[name] || name, ...summary(meter)])]);
      const details = item => {
        const detail = document.createElement('details'), title = document.createElement('summary'), text = document.createElement('p');
        title.textContent = item.model; text.textContent = 'Операция: ' + item.operationId + '\nТариф: ' + item.tariff + ' · ' + item.period + '\nКурс ₽/USD: ' + (item.fxRubPerUsd || 'Не сохранён') + '\nКвитанция: ' + (item.receiptId || 'Не сохранена') + '\nОснование: ' + (item.evidence || 'Ожидается') + '\nИспользование: ' + JSON.stringify(item.usage);
        text.className = 'finance-receipt'; detail.append(title, text); return detail;
      };
      const action = item => {
        if (item.state !== 'pending') return ({conflict: 'Конфликт квитанции', reserved: 'Зарезервировано', running: 'Выполняется', settled: 'Учтено'})[item.state] || item.state;
        if (!['deepseek-2026-11-18', 'openrouter-v1', 'deepseek-web-2026-11-27', 'deepseek-files-2026-11-25'].includes(item.tariff)) return 'Нужен адаптер сверки';
        const button = document.createElement('button'); button.type = 'button'; button.className = 'secondary'; button.textContent = 'Сверить';
        button.addEventListener('click', () => {
          selected = item; const form = $('[data-finance-review-form]'); form.reset();
          form.elements.currency.value = item.tariff.startsWith('deepseek-files') || item.tariff.startsWith('deepseek-web') ? 'RUB' : 'USD';
          $('[data-finance-review-info]').textContent = item.provider + ' · ' + item.login + '\nРезерв: ' + item.reservedCoins + ' монет. Операция: ' + item.operationId;
          $('[data-finance-review-error]').textContent = ''; $('[data-finance-review]').showModal();
        }); return button;
      };
      table($('[data-finance-rows]'), ['Дата / аккаунт', 'Поставщик / услуга', 'Квитанция', 'Расход, ₽', 'Монеты', 'Резерв', 'Состояние'], rows.map(item => [
        new Date(item.at).toLocaleString('ru-RU') + '\n' + (item.login || 'Удалённый аккаунт'),
        item.provider + ' · ' + (kinds[item.kind] || item.kind), details(item), value(item.providerRub), value(item.coins), value(item.reservedCoins), action(item)]));
      $('[data-finance-page]').textContent = data.total ? (offset + 1) + '–' + Math.min(offset + data.limit, data.total) + ' из ' + data.total : '0 операций';
      $('[data-finance-prev]').disabled = offset === 0; $('[data-finance-next]').disabled = !data.hasMore;
      $('[data-finance-payments]').textContent = 'Поступило: ' + value(data.payments.receivedRub) + ' ₽ · Возвраты: ' + value(data.payments.refundedRub) + ' ₽ · Итого: ' + value(data.payments.netRub) + ' ₽ · Начисления: ' + value(data.payments.bonusCoins) + ' монет · Незавершённых оплат: ' + data.payments.pending;
      const guest = data.guest;
      $('[data-finance-guest]').textContent = guest.available ? 'Вызовы: ' + guest.calls + ' · Подтверждённый расход: ' + value(guest.knownProviderRub) + ' ₽ · Неизвестных: ' + guest.unknown + (guest.costComplete ? '' : ' · Данные неполные') + ' · Календарь ' + guest.timezone : 'Статистика ещё не накоплена.';
      $('[data-finance-status]').textContent = 'Часовой пояс отчёта: ' + data.timezone + '. Период — по началу операции, созданию платежа или подтверждению возврата. Разбивка по видам услуг входит в суммы поставщиков один раз.';
      await loadPayments();
    } catch (error) { if (current === generation) $('[data-finance-status]').textContent = error.message; }
  }
  async function loadPayments() {
    const current = ++paymentGeneration, paymentFilter = $('[data-payment-filters]');
    const params = new URLSearchParams(new FormData(paymentFilter));
    for (const key of ['start', 'end', 'login']) if (filter.elements[key].value) params.set(key, filter.elements[key].value);
    params.set('offset', String(paymentOffset)); params.set('zone', Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC');
    $('[data-payment-status]').textContent = 'Загружаем платежи…';
    try {
      const data = await request('/api/admin/payments?' + params);
      if (current !== paymentGeneration) return;
      const config = data.configuration;
      $('[data-payment-configuration]').textContent = 'ЮKassa · ' + config.product + (config.shop ? ' · магазин ' + config.shop : '') +
        ' · Приём: ' + (config.enabled ? 'включён' : 'выключен') + ' · Проверка платежей: ' + (config.ready ? 'доступна' : 'недоступна') +
        ' · Чек: ' + (config.fiscalConfigured ? 'настроен' : 'не настроен') + (config.pilotOnly ? ' · Контрольный режим' : '');
      const states = {pending: 'Ожидает оплаты или сверки', succeeded: 'Оплачено', canceled: 'Отменено', refunded: 'Возвращено'};
      const identifiers = item => {
        const detail = document.createElement('details'), title = document.createElement('summary'), text = document.createElement('p');
        title.textContent = 'Идентификаторы'; text.className = 'finance-receipt';
        text.textContent = 'Заказ: ' + item.id + '\nЮKassa: ' + (item.providerId || 'Ещё не получен') + '\nКлюч запроса: ' + item.requestKey +
          (item.refundId ? '\nВозврат: ' + item.refundId + ' · ' + value(item.refundRub) + ' ₽' : '');
        detail.append(title, text); return detail;
      };
      const action = item => {
        if (item.state !== 'pending') return 'Подтверждено';
        if (!item.providerId) return 'Неизвестен исход создания';
        if (!config.ready) return 'Проверка недоступна';
        const button = document.createElement('button'); button.type = 'button'; button.className = 'secondary';
        button.textContent = 'Проверить в ЮKassa'; button.dataset.paymentReconcile = item.id;
        button.addEventListener('click', async () => {
          if (button.disabled) return; button.disabled = true; $('[data-payment-status]').textContent = 'Проверяем платёж…';
          try {
            const verified = await request('/api/admin/payments/reconcile', {method: 'POST', headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({checkoutId: item.id, version: item.version})});
            await load(); $('[data-payment-status]').textContent = 'ЮKassa: ' + (states[verified.state] || verified.state);
          } catch (error) { $('[data-payment-status]').textContent = error.message; } finally { button.disabled = false; }
        }); return button;
      };
      table($('[data-payment-rows]'), ['Создан / аккаунт', 'Монеты', 'Сумма, ₽', 'Статус', 'Идентификаторы', 'Проверка'], data.rows.map(item => [
        new Date(item.created * 1000).toLocaleString('ru-RU') + '\n' + (item.login || 'Удалённый аккаунт'),
        String(item.quantity), value(item.totalRub), states[item.state] || item.state, identifiers(item), action(item)]));
      $('[data-payment-page]').textContent = data.total ? (paymentOffset + 1) + '–' + Math.min(paymentOffset + data.limit, data.total) + ' из ' + data.total : '0 платежей';
      $('[data-payment-prev]').disabled = paymentOffset === 0; $('[data-payment-next]').disabled = !data.hasMore;
      $('[data-payment-status]').textContent = 'Поступило по выбранным платежам: ' + value(data.receivedRub) + ' ₽ · Возвращено: ' + value(data.refundedRub) + ' ₽';
    } catch (error) { if (current === paymentGeneration) $('[data-payment-status]').textContent = error.message; }
  }
  filter.addEventListener('submit', event => { event.preventDefault(); offset = paymentOffset = 0; load(); });
  $('[data-finance-prev]').addEventListener('click', () => { offset = Math.max(0, offset - Number(filter.elements.limit.value)); load(); });
  $('[data-finance-next]').addEventListener('click', () => { offset += Number(filter.elements.limit.value); load(); });
  $('[data-payment-filters]').addEventListener('submit', event => { event.preventDefault(); paymentOffset = 0; loadPayments(); });
  $('[data-payment-prev]').addEventListener('click', () => { paymentOffset = Math.max(0, paymentOffset - Number($('[data-payment-filters]').elements.limit.value)); loadPayments(); });
  $('[data-payment-next]').addEventListener('click', () => { paymentOffset += Number($('[data-payment-filters]').elements.limit.value); loadPayments(); });
  $('[data-finance-review-cancel]').addEventListener('click', () => $('[data-finance-review]').close());
  $('[data-finance-review-form]').addEventListener('submit', async event => {
    event.preventDefault(); if (!selected) return;
    const target = event.currentTarget, button = target.querySelector('button[type=submit]'); if (button.disabled) return;
    button.disabled = true; $('[data-finance-review-error]').textContent = '';
    try {
      await request('/api/admin/finance/reconcile', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
        attemptId: selected.id, version: selected.version, amount: target.elements.amount.value.trim(),
        currency: target.elements.currency.value, reference: target.elements.reference.value.trim()})});
      $('[data-finance-review]').close(); selected = null; await load();
    } catch (error) { $('[data-finance-review-error]').textContent = error.message; } finally { button.disabled = false; }
  });
  load();
})();
