"""Authenticated profile, session control, wallet history and financial review.

These routes extend the existing identity, wallet and provider receipts. They
do not create another authorization service or mutate workshop accounting.
"""
from datetime import datetime, timezone
from decimal import Decimal
import re
import time
from uuid import uuid4

from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import coins, finance_reporting as reporting, service_billing
from .identity import _principal, _secret_digest, AuthenticationError
from .coin_review import resolve_in_transaction


def initialize(identity):
    from .finance_schema import ensure
    with identity._write() as db:
        ensure(db)


def require_admin(db, token):
    actor, workspace = _principal(db, token)
    if not db.execute('SELECT 1 FROM identity_admins WHERE actor_id=?', (actor,)).fetchone():
        raise PermissionError('Требуются права администратора.')
    return actor, workspace


def profile(identity, token):
    with identity._lock:
        actor, _ = _principal(identity._db, token)
        login = identity._db.execute('SELECT login FROM identity_accounts WHERE actor_id=?', (actor,)).fetchone()[0]
        registered = identity._db.execute('SELECT created FROM identity_registration_dates WHERE actor_id=?', (actor,)).fetchone()
        administrator = bool(identity._db.execute('SELECT 1 FROM identity_admins WHERE actor_id=?', (actor,)).fetchone())
        return {'login': login, 'admin': administrator, 'registeredAt': registered[0] if registered else None}


def sessions(identity, token):
    with identity._lock:
        actor, _ = _principal(identity._db, token)
        current = _secret_digest(token)
        data = identity._db.execute("""SELECT m.id,s.digest,s.expires_at,p.remembered,m.created,m.last_seen
            FROM identity_sessions s JOIN identity_session_metadata m USING(digest)
            LEFT JOIN identity_session_preferences p USING(digest)
            WHERE s.actor_id=? AND s.expires_at>unixepoch()
            ORDER BY (s.digest=?) DESC,m.last_seen DESC,m.id""", (actor, current)).fetchall()
        return {'sessions': [{'id': sid, 'current': digest == current, 'expiresAt': expires,
            'remembered': bool(remembered), 'createdAt': created, 'lastSeenAt': last}
            for sid, digest, expires, remembered, created, last in data]}


def revoke_session(identity, token, *, action, session_id=None):
    if action not in ('revoke', 'others') or (action == 'revoke') != bool(session_id):
        raise ValueError('Некорректное действие с сеансом.')
    if session_id is not None and (not isinstance(session_id, str) or not re.fullmatch(r'[a-f0-9]{32}', session_id)):
        raise ValueError('Некорректный сеанс.')
    with identity._write() as db:
        actor, workspace = _principal(db, token)
        current = _secret_digest(token)
        if action == 'others':
            selected = [row[0] for row in db.execute('SELECT digest FROM identity_sessions WHERE actor_id=? AND digest<>?', (actor, current))]
        else:
            row = db.execute("""SELECT s.digest FROM identity_sessions s JOIN identity_session_metadata m USING(digest)
                WHERE s.actor_id=? AND m.id=?""", (actor, session_id)).fetchone()
            if row is None:
                raise LookupError('Сеанс недоступен.')
            selected = [row[0]]
        for digest in selected:
            db.execute('DELETE FROM usage_grants WHERE token_hash IN (SELECT token_hash FROM marketplace_retry_windows WHERE session_digest=?)', (digest,))
            db.execute('DELETE FROM identity_sessions WHERE actor_id=? AND digest=?', (actor, digest))
        coins.close_orders(db, workspace)
        return {'revoked': len(selected), 'signedOut': current in selected}


_HISTORY = """
    SELECT 'grant:'||issuer||':'||key AS id,created*1000 AS at,'grant' AS kind,
        'settled' AS state,amount AS amount,NULL AS reserved,reason AS reason,NULL AS rub
        FROM coin_grants WHERE workspace_id=? AND issuer!='yookassa'
    UNION ALL
    SELECT 'payment:'||id,created*1000,'purchase',status,
        CASE WHEN status IN ('succeeded','refunded') THEN quantity*1000000000000 ELSE NULL END,
        NULL,'Покупка монет',total FROM coin_checkouts WHERE workspace_id=?
    UNION ALL
    SELECT 'refund:'||r.refund_id,r.created*1000,'refund','settled',-c.quantity*1000000000000,
        NULL,'Возврат оплаты',r.amount FROM coin_refunds r JOIN coin_checkouts c ON c.id=r.checkout_id
        WHERE r.workspace_id=?
    UNION ALL
    SELECT 'attempt:'||a.attempt_id,a.started_ms,CASE WHEN a.charge IS NULL THEN 'reserve' ELSE 'charge' END,
        CASE WHEN a.charge IS NULL THEN 'pending' ELSE 'settled' END,
        CASE WHEN a.charge IS NULL THEN NULL ELSE -a.charge END,
        a.bound,
        CASE WHEN a.rate_version='deepseek-web-2026-11-27' THEN 'Интернет-поиск и чтение страницы'
             WHEN a.rate_version='deepseek-files-2026-11-25' THEN 'Распознавание файла или аудио'
             WHEN u.source LIKE '%illustrat%' OR a.period LIKE '%illustrat%' THEN 'Создание иллюстрации'
             ELSE 'Работа помощника' END,NULL
        FROM coin_attempts a JOIN coin_orders o USING(operation_id) JOIN usage_operations u USING(operation_id)
        WHERE o.workspace_id=?
"""


def history(identity, token, *, offset=0, limit=20, kind=None):
    if type(offset) is not int or offset < 0 or offset > 1000000 or limit not in (10, 20, 50, 100):
        raise ValueError('Некорректная страница истории.')
    if kind not in (None, '', 'grant', 'purchase', 'refund', 'charge', 'reserve'):
        raise ValueError('Некорректный тип операции.')
    with identity._write() as db:
        _, workspace = _principal(db, token)
        coins.close_orders(db, workspace)
        available, reserved = coins.balances(db, workspace)
        where = ' WHERE (? IS NULL OR ?=\'\' OR kind=?)'
        args = (workspace,) * 4 + (kind, kind, kind)
        total = db.execute('SELECT count(*) FROM (' + _HISTORY + ')' + where, args).fetchone()[0]
        records = db.execute('SELECT * FROM (' + _HISTORY + ')' + where + ' ORDER BY at DESC,id DESC LIMIT ? OFFSET ?',
                             args + (limit, offset)).fetchall()
        data = [{'id': uid, 'at': at, 'kind': item_kind, 'state': state,
                 'coins': format(Decimal(amount) / coins.UNIT, 'f') if amount is not None else None,
                 'reservedCoins': coins.display(held) if held is not None and state == 'pending' else '0',
                 'originalReserveCoins': coins.display(held) if held is not None else None,
                 'reason': reason, 'rub': rub}
                for uid, at, item_kind, state, amount, held, reason, rub in records]
        return {'rows': data, 'total': total, 'offset': offset, 'limit': limit,
                'hasMore': offset + limit < total, 'available': coins.display(available),
                'reserved': coins.display(reserved), 'salePrice': coins.sale_pricing(db)}


def guest_expense(db, start=None, end=None):
    from .guest_selector import metric_sums, ZONE
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='guest_filter_daily'").fetchone():
        return {'available': False, 'costComplete': False}
    if not start and not end:
        data = metric_sums(db, "day='total'", ())
        coverage = True
    else:
        data = metric_sums(db, "day!='total' AND (? IS NULL OR day>=?) AND (? IS NULL OR day<=?)", (start, start, end, end))
        first = db.execute("SELECT min(day) FROM guest_filter_daily WHERE day!='total'").fetchone()[0]
        coverage = bool(first and start and start >= first)
    return {'available': True, **data, 'provider': 'DeepSeek', 'costCenter': 'guest-classifier',
        'timezone': str(ZONE), 'customerCoins': '0', 'costComplete': coverage and data['unknown'] == 0,
        'coverageComplete': coverage, 'providerRub': data['rub'] if coverage and data['unknown'] == 0 else None,
        'knownProviderRub': data['rub']}


def admin_report(identity, token, **filters):
    with identity._lock:
        require_admin(identity._db, token)
        result = reporting.report(identity._db, **filters)
        result['guest'] = guest_expense(identity._db, filters.get('start'), filters.get('end'))
        # Guest calls are a platform expense, never a debit against an arbitrary
        # customer. Keep them explicit when looking at an individual account.
        result['guest']['includedInCustomerTotals'] = False
        return result


def _reference(value):
    if not isinstance(value, str) or not re.fullmatch(r'[\w .:/-]{5,160}', value):
        raise ValueError('Укажите идентификатор подтверждающей квитанции, без секретов.')
    if re.search(r'(?i)(?:sk-[a-z0-9]|bearer\s|password|secret|api[_ -]?key|token[: /])', value):
        raise ValueError('В основании сверки нельзя сохранять секреты.')
    return value


def reconcile(identity, token, *, attemptId, version, amount, currency, reference):
    reference = _reference(reference)
    if currency not in ('USD', 'RUB') or not isinstance(amount, str) or not re.fullmatch(r'[0-9]{1,7}(?:\.[0-9]{1,12})?', amount):
        raise ValueError('Укажите подтверждённую сумму и валюту квитанции.')
    if not isinstance(attemptId, str) or not 1 <= len(attemptId) <= 160 or not isinstance(version, str) or not re.fullmatch(r'[a-f0-9]{64}', version):
        raise ValueError('Некорректная операция сверки.')
    with identity._write() as db:
        actor, _ = require_admin(db, token)
        old = db.execute('SELECT previous_version,provider_amount,provider_currency,reference,charge FROM finance_reconciliations WHERE attempt_id=?', (attemptId,)).fetchone()
        if old:
            if tuple(old[:4]) != (version, amount, currency, reference):
                raise ValueError('Операция уже сверена с другими параметрами.')
            return {'state': 'settled', 'coins': coins.display(old[4]), 'replayed': True}
        operation = db.execute('SELECT operation_id FROM coin_attempts WHERE attempt_id=?', (attemptId,)).fetchone()
        if not operation:
            raise LookupError('Финансовая операция недоступна.')
        row = next((r for r in reporting.rows(db, operation=operation[0]) if r['attempt_id'] == attemptId), None)
        if not row or row['version'] != version:
            raise ValueError('Операция изменилась. Обновите её состояние перед сверкой.')
        if row['rate_version'] not in service_billing.MODEL_RATES:
            raise ValueError('Для этого тарифа требуется зарегистрированный адаптер квитанции.')
        if row['charge'] is not None:
            raise ValueError('Подтверждённое списание нельзя изменить.')
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='web_attempt_state'").fetchone():
            if db.execute("SELECT 1 FROM web_attempt_state WHERE attempt_id=? AND phase IN ('reserved','dispatched') AND lease_until>?", (attemptId, int(time.time()*1000))).fetchone():
                raise ValueError('Интернет-запрос ещё выполняется.')
        charge = resolve_in_transaction(db, attemptId, amount, reference, currency=currency)
        db.execute('INSERT INTO finance_reconciliations VALUES(?,?,?,?,?,?,?,?,?)',
                   (uuid4().hex, attemptId, actor, version, currency, amount, reference, charge, int(time.time())))
        return {'state': 'settled', 'coins': coins.display(charge), 'replayed': False}


def routes(token_for, body):
    async def own_profile(req):
        return JSONResponse(await run_in_threadpool(profile, req.app.state.identity, token_for(req, allow_cookie=True)))

    async def own_sessions(req):
        token = token_for(req, allow_cookie=True)
        try:
            if req.method == 'POST':
                data = await body(req, 'action', optional=('sessionId',))
                result = await run_in_threadpool(revoke_session, req.app.state.identity, token,
                    action=data['action'], session_id=data.get('sessionId'))
            else:
                result = await run_in_threadpool(sessions, req.app.state.identity, token)
            return JSONResponse(result)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None

    async def own_history(req):
        token = token_for(req, allow_cookie=True)
        try:
            q = req.query_params
            result = await run_in_threadpool(history, req.app.state.identity, token,
                offset=int(q.get('offset', 0)), limit=int(q.get('limit', 20)), kind=q.get('kind'))
            return JSONResponse(result)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None

    async def financial_report(req):
        token = token_for(req, allow_cookie=True)
        try:
            q = req.query_params
            filters = {key: q[key] for key in ('start', 'end', 'zone', 'login', 'provider', 'kind', 'state', 'operation', 'sort', 'direction') if q.get(key)}
            filters.update(offset=int(q.get('offset', 0)), limit=int(q.get('limit', 20)))
            return JSONResponse(await run_in_threadpool(admin_report, req.app.state.identity, token, **filters))
        except AuthenticationError:
            raise
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None

    async def financial_reconcile(req):
        token = token_for(req, allow_cookie=True)
        data = await body(req, 'attemptId', 'version', 'amount', 'currency', 'reference')
        try:
            return JSONResponse(await run_in_threadpool(reconcile, req.app.state.identity, token, **data))
        except AuthenticationError:
            raise
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from None
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    async def payment_report(req):
        from . import finance_payments
        token = token_for(req, allow_cookie=True)
        try:
            q = req.query_params
            filters = {key: q[key] for key in ('start','end','zone','login','state') if q.get(key)}
            filters.update(offset=int(q.get('offset',0)), limit=int(q.get('limit',20)))
            return JSONResponse(await run_in_threadpool(finance_payments.report, req.app.state.identity, token, **filters))
        except AuthenticationError:
            raise
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None

    async def payment_reconcile(req):
        from . import finance_payments
        token = token_for(req, allow_cookie=True)
        data = await body(req, 'checkoutId', 'version')
        try:
            return JSONResponse(await finance_payments.reconcile(req.app.state.identity, token, **data))
        except AuthenticationError:
            raise
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from None
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    return [Route('/api/profile', own_profile),
            Route('/api/profile/sessions', own_sessions, methods=['GET', 'POST']),
            Route('/api/wallet/history', own_history),
            Route('/api/admin/finance', financial_report),
            Route('/api/admin/finance/reconcile', financial_reconcile, methods=['POST']),
            Route('/api/admin/payments', payment_report),
            Route('/api/admin/payments/reconcile', payment_reconcile, methods=['POST'])]
