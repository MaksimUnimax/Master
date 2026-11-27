"""Read-only projections of the one monetary ledger.

Customer debits, reservations, provider expenses and payment receipts stay
separate. Unknown provider amounts remain unknown, including old tariffs.
All calculations use integer pico-coins or Decimal, never binary floats.
"""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
from zoneinfo import ZoneInfo

from . import coins, service_billing


def _money(value):
    return format(value, 'f')


def _number(value):
    return value if type(value) is int and value >= 0 else 0


def decimal_amount(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return amount if amount.is_finite() and amount >= 0 else None


def source_kind(rate, model, source='', period=''):
    if rate == 'deepseek-web-2026-11-27':
        return 'web'
    if rate == 'deepseek-files-2026-11-25':
        return 'audio' if model == 'deepseek-asr' else 'files'
    if 'illustrat' in source or 'image' in source or 'illustrat' in period:
        return 'images'
    if service_billing.provider_for(rate) in ('DeepSeek', 'OpenRouter'):
        return 'tokens'
    return 'services'


def version(row):
    fields = ('attempt_id', 'operation_id', 'bound', 'charge', 'rate_version',
              'provider_id', 'usage_json', 'evidence', 'service_state', 'fx_e4')
    raw = json.dumps([row.get(key) for key in fields], ensure_ascii=True, separators=(',', ':'))
    return hashlib.sha256(raw.encode()).hexdigest()


def _provider_cost(row, usage):
    """Return confirmed supplier RUB and USD, without inventing a zero price."""
    fx = Decimal(row['fx_e4']) / 10000 if row.get('fx_e4') else None
    if row.get('review_amount') is not None:
        amount = Decimal(row['review_amount'])
        if row['review_currency'] == 'USD':
            return amount * fx if fx else None, amount
        return amount, amount / fx if fx else None
    if row.get('service'):
        if row['service_state'] == 'conflict':
            return None, None
        if row.get('actual_units') is None:
            return None, None
        if row['billing_owner'] == 'user':
            return Decimal(0), None
        if row.get('supplier_price') is None:
            return None, None
        return Decimal(row['actual_units'] * row['supplier_price']) / coins.UNIT, None
    rate, charge, evidence = row['rate_version'], row['charge'], row['evidence'] or ''
    if rate == 'openrouter-v1':
        try:
            usd = coins.provider_receipt(evidence)
        except (InvalidOperation, ValueError):
            usd = None
        if usd is not None and usd.is_finite() and usd >= 0:
            return usd * fx if fx else None, usd
        if charge == 0 and evidence in ('not_dispatched', 'client_disconnected_before_dispatch', 'openrouter-not-dispatched'):
            return Decimal(0), Decimal(0)
        return None, None
    if rate == 'deepseek-files-2026-11-25':
        amount = decimal_amount(usage.get('providerAmount'))
        if amount is not None:
            return amount, amount / fx if fx else None
        if charge == 0 and evidence and evidence != 'media-pages-unknown':
            return Decimal(0), Decimal(0)
        return None, None
    if rate not in service_billing.MODEL_RATES or charge is None:
        return None, None
    # Current direct DeepSeek debits are the immutable confirmed RUB amount.
    # Legacy orders priced coins per USD retain their historical conversion.
    if fx:
        amount = Decimal(charge) / coins.UNIT
        return amount, amount / fx
    conversion, markup = row.get('coins_per_usd'), row.get('markup')
    if conversion and markup is not None:
        usd = Decimal(charge) / coins.UNIT / conversion * 100 / (100 + markup)
        return None, usd
    return None, None


def rows(db, *, workspace=None, start_ms=None, end_ms=None, operation=None,
         operations=None, actor=None, chat=None):
    clauses, parameters = [], []
    for column, value, relation in (
        ('o.workspace_id', workspace, '='), ('a.started_ms', start_ms, '>='),
        ('a.started_ms', end_ms, '<'), ('a.operation_id', operation, '='),
        ('u.actor_id', actor, '='), ('u.chat_id', chat, '='),
    ):
        if value is not None:
            clauses.append(column + relation + '?')
            parameters.append(value)
    if operations is not None:
        selected = tuple(dict.fromkeys(operations))
        if not selected:
            return
        clauses.append('a.operation_id IN (' + ','.join('?' for _ in selected) + ')')
        parameters.extend(selected)
    sql = """SELECT a.*,o.workspace_id,o.markup,o.coins_per_usd,o.closed,
        u.actor_id,u.source,u.run_key,u.chat_id,r.fx_e4,i.login,
        d.service,d.owner AS billing_owner,d.actual_units,d.max_units,d.reported_units,
        d.state AS service_state,d.tariff AS service_tariff,d.receipt_id,
        d.price_units AS client_unit_price,t.price_units AS supplier_price,
        f.provider_currency AS review_currency,f.provider_amount AS review_amount,
        f.reference AS review_reference,
        EXISTS(SELECT 1 FROM usage_grants g WHERE g.operation_id=a.operation_id
            AND g.expires_at>unixepoch()) AS active_grant
        FROM coin_attempts a JOIN coin_orders o USING(operation_id)
        JOIN usage_operations u USING(operation_id)
        LEFT JOIN identity_accounts i ON i.actor_id=u.actor_id
        LEFT JOIN coin_ruble_orders r USING(operation_id)
        LEFT JOIN service_attempt_details d USING(attempt_id)
        LEFT JOIN service_tariffs t ON t.version=d.tariff
        LEFT JOIN finance_reconciliations f USING(attempt_id)"""
    if clauses:
        sql += ' WHERE ' + ' AND '.join(clauses)
    sql += ' ORDER BY a.started_ms DESC,a.attempt_id DESC'
    cursor = db.execute(sql, parameters)
    columns = [c[0] for c in cursor.description]
    for record in cursor:
        row = dict(zip(columns, record))
        try:
            usage = json.loads(row['usage_json']) if row['usage_json'] else {}
        except (ValueError, TypeError):
            usage = {}
        if not isinstance(usage, dict):
            usage = {}
        with localcontext() as ctx:
            ctx.prec = 64
            provider_rub, provider_usd = _provider_cost(row, usage)
        provider = service_billing.provider_for(row['rate_version'])
        kind = source_kind(row['rate_version'], row['model'], row['source'], row['period'])
        row.update(usage=usage, provider=provider, kind=kind, supplier_rub=provider_rub,
                   supplier_usd=provider_usd, version=version(row))
        yield row


def state_for(row):
    if row.get('service_state') == 'conflict':
        return 'conflict'
    if row['charge'] is not None:
        return 'settled'
    if row.get('service_state') == 'reserved':
        return 'reserved'
    if row.get('service_state') == 'dispatched' or row.get('active_grant'):
        return 'running'
    return 'pending'


def public_attempt(row, *, administrative=True):
    result = {
        'id': row['attempt_id'], 'operationId': row['operation_id'], 'at': row['started_ms'],
        'kind': row['kind'], 'state': state_for(row),
        'coins': coins.display(row['charge']) if row['charge'] is not None else None,
        'reservedCoins': coins.display(row['bound']) if row['charge'] is None else '0',
    }
    if administrative:
        result.update(login=row['login'], workspace=row['workspace_id'], provider=row['provider'],
            model=row['model'], tariff=row['rate_version'], period=row['period'],
            fxRubPerUsd=_money(Decimal(row['fx_e4']) / 10000) if row['fx_e4'] else None,
            providerRub=_money(row['supplier_rub']) if row['supplier_rub'] is not None else None,
            providerUsd=_money(row['supplier_usd']) if row['supplier_usd'] is not None else None,
            receiptId=row.get('receipt_id') or row['provider_id'], evidence=row.get('review_reference') or row['evidence'],
            version=row['version'], usage=row['usage'], source=row['source'],
            billingOwner=row.get('billing_owner') or 'platform',
            serviceTariff=row.get('service_tariff'), quantity=row.get('actual_units'),
            clientUnitRub=coins.display(row['client_unit_price']) if row.get('client_unit_price') is not None else None)
    return result


def summarize(records):
    value = dict(attempts=0, pending=0, input=0, cache=0, output=0, unknownCostAttempts=0)
    charged = held = 0
    rub = usd = Decimal(0)
    unknown_usd = 0
    units = {}
    for row in records:
        value['attempts'] += 1
        value['pending'] += int(row['charge'] is None or row.get('service_state') == 'conflict')
        charged += row['charge'] or 0
        held += row['bound'] if row['charge'] is None else 0
        usage = row['usage']
        value['input'] += _number(usage.get('input_tokens')) + _number(usage.get('cache_creation_input_tokens'))
        value['cache'] += _number(usage.get('cache_read_input_tokens'))
        value['output'] += _number(usage.get('output_tokens'))
        if row['supplier_rub'] is None:
            value['unknownCostAttempts'] += 1
        else:
            rub += row['supplier_rub']
        if row['supplier_usd'] is None:
            unknown_usd += 1
        else:
            usd += row['supplier_usd']
        unit = usage.get('unit')
        quantity = usage.get('quantity')
        if unit in ('seconds', 'pages') and type(quantity) is int and quantity >= 0:
            units[unit] = units.get(unit, 0) + quantity
        if row.get('service') and row.get('actual_units') is not None:
            key = service_billing.unit_for(row['provider']) or 'units'
            units[key] = units.get(key, 0) + row['actual_units']
        if row['kind'] == 'web' and row['evidence'] == 'web-completed':
            key = 'searches' if row['model'] == 'deepseek-search-api' else 'fetches'
            units[key] = units.get(key, 0) + 1
    return {**value, 'coins': coins.display(charged), 'reservedCoins': coins.display(held),
        'providerRub': _money(rub) if not value['unknownCostAttempts'] else None,
        'knownProviderRub': _money(rub), 'providerUsd': _money(usd) if not unknown_usd else None,
        'knownProviderUsd': _money(usd), 'costComplete': not value['unknownCostAttempts'],
        'rub': _money(rub), 'usd': _money(usd), 'rubIncomplete': bool(value['unknownCostAttempts']),
        'units': units}


def provider_meters(db, workspace=None):
    groups = {}
    for row in rows(db, workspace=workspace):
        groups.setdefault(row['provider'], []).append(row)
    result = {}
    for provider, records in groups.items():
        entry = summarize(records)
        entry['pendingAttempts'] = entry['pending']
        if service_billing.unit_for(provider):
            unit = service_billing.unit_for(provider)
            entry.update(unit=unit, quantity=entry['units'].get(unit, 0))
        for kind in ('web', 'files', 'audio', 'images'):
            selected = [r for r in records if r['kind'] == kind]
            if selected:
                child = summarize(selected)
                entry[kind] = {**child['units'], 'coins': child['coins'], 'providerRub': child['providerRub'],
                    'pending': child['pending'], 'costComplete': child['costComplete']}
        result[provider] = entry
    return result


def boundaries(start=None, end=None, zone='UTC'):
    try:
        timezone_ = ZoneInfo(zone)
        first = date.fromisoformat(start) if start else None
        last = date.fromisoformat(end) if end else None
        if (first and first.isoformat() != start) or (last and last.isoformat() != end) or (first and last and first > last):
            raise ValueError()
        def stamp(day):
            return int(datetime.combine(day, time.min, timezone_).timestamp() * 1000)
        return stamp(first) if first else None, stamp(last + timedelta(days=1)) if last else None
    except (KeyError, ValueError, OverflowError, TypeError):
        raise ValueError('Укажите корректный период и часовой пояс.') from None


def report(db, *, start=None, end=None, zone='UTC', login=None, provider=None, kind=None,
           state=None, operation=None, offset=0, limit=20, sort='date', direction='desc'):
    start_ms, end_ms = boundaries(start, end, zone)
    if type(offset) is not int or offset < 0 or offset > 1000000 or limit not in (10, 20, 50, 100):
        raise ValueError('Некорректная страница отчёта.')
    sort_fields = {'date': 'started_ms', 'account': 'login', 'provider': 'provider',
                   'coins': 'charge', 'cost': 'supplier_rub'}
    if sort not in sort_fields or direction not in ('asc', 'desc'):
        raise ValueError('Некорректная сортировка отчёта.')
    if state not in (None, '', 'reserved', 'running', 'pending', 'settled', 'conflict'):
        raise ValueError('Некорректное состояние операции.')
    data = [r for r in rows(db, start_ms=start_ms, end_ms=end_ms, operation=operation)
        if (not login or r['login'] == login) and (not provider or r['provider'] == provider)
        and (not kind or r['kind'] == kind)
        and (not state or state == state_for(r))]
    field = sort_fields[sort]
    known = sorted((r for r in data if r[field] is not None),
                   key=lambda r: (r[field], r['attempt_id']), reverse=direction == 'desc')
    data = known + [r for r in data if r[field] is None]
    providers, kinds, accounts = {}, {}, {}
    for row in data:
        providers.setdefault(row['provider'], []).append(row)
        kinds.setdefault(row['kind'], []).append(row)
        accounts.setdefault(row['login'] or 'Удалённый аккаунт', []).append(row)
    money_where = 'WHERE (? IS NULL OR created*1000>=?) AND (? IS NULL OR created*1000<?)'
    args = [start_ms, start_ms, end_ms, end_ms]
    if login:
        money_where += ' AND workspace_id=(SELECT workspace_id FROM identity_accounts WHERE login=?)'
        args.append(login)
    payments = db.execute('SELECT status,total,quantity FROM coin_checkouts ' + money_where, args).fetchall()
    purchased = sum((Decimal(total) for status, total, _ in payments if status in ('succeeded', 'refunded')), Decimal(0))
    refund_rows = db.execute('SELECT amount FROM coin_refunds ' + money_where, args).fetchall()
    refunds = sum((Decimal(amount) for amount, in refund_rows), Decimal(0))
    # Every wallet fits SQLite's integer range; a platform-wide sum need not.
    grants = sum(row[0] for row in db.execute("SELECT amount FROM coin_grants " + money_where + " AND issuer!='yookassa'", args))
    return {
        'timezone': zone, 'from': start, 'to': end, 'totals': summarize(data),
        'providers': {k: summarize(v) for k, v in providers.items()},
        'kinds': {k: summarize(v) for k, v in kinds.items()},
        'accounts': [{'login': k, **summarize(v)} for k, v in sorted(accounts.items())],
        'payments': {'receivedRub': _money(purchased), 'refundedRub': _money(refunds),
            'netRub': _money(purchased - refunds), 'bonusCoins': coins.display(grants),
            'pending': sum(status == 'pending' for status, _, _ in payments)},
        'rows': [public_attempt(row) for row in data[offset:offset + limit]],
        'offset': offset, 'limit': limit, 'total': len(data), 'hasMore': offset + limit < len(data),
    }
