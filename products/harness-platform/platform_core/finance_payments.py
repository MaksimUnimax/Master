"""Administrative views and verified recovery over the existing checkout engine."""
from contextlib import contextmanager
from decimal import Decimal
import hashlib
import json
import os
import re
import time
from uuid import uuid4

from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

from . import checkout, finance_reporting


SCHEMA = ("""CREATE TABLE IF NOT EXISTS finance_payment_reviews (
    id TEXT PRIMARY KEY, checkout_id TEXT NOT NULL REFERENCES coin_checkouts(id),
    actor_id TEXT NOT NULL, previous_version TEXT NOT NULL,
    previous_status TEXT NOT NULL, provider_status TEXT NOT NULL,
    provider_id TEXT NOT NULL, receipt_sha256 TEXT NOT NULL,
    amount TEXT NOT NULL, currency TEXT NOT NULL CHECK(currency='RUB'),
    created INTEGER NOT NULL,
    UNIQUE(checkout_id,previous_version,provider_status,receipt_sha256))""",)


def initialize(db):
    from .schema_migrations import apply
    apply(db, '20261127_finance_payments_v1', statements=SCHEMA)


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, sort_keys=True,
        separators=(',', ':')).encode()).hexdigest()


def configuration():
    auth = checkout.merchant()
    shop = os.getenv('YOOKASSA_SHOP_ID', '')
    return {'provider': 'ЮKassa', 'product': 'Мастерская',
        'enabled': os.getenv('YOOKASSA_PAYMENTS_ENABLED') == '1',
        'ready': bool(auth), 'fiscalConfigured': checkout.fiscal_policy() is not None,
        'pilotOnly': os.getenv('YOOKASSA_PILOT_ONLY') == '1',
        'shop': ('…' + shop[-4:]) if re.fullmatch(r'[1-9][0-9]{3,15}', shop) else None,
        'webhookPath': '/api/coins/yookassa'}


def _row(db, order):
    row = db.execute('SELECT id,workspace_id,request_key,quantity,total,provider_id,status,created FROM coin_checkouts WHERE id=?', (order,)).fetchone()
    if row is None:
        raise LookupError('Платёж недоступен.')
    return dict(zip(('id','workspace','requestKey','quantity','totalRub','providerId','state','created'), row))


def _version(row):
    return _hash([row[key] for key in ('id','workspace','requestKey','quantity','totalRub','providerId','state','created')])


def report(identity, token, *, login=None, state=None, start=None, end=None, zone='UTC', offset=0, limit=20):
    from .account_finance import require_admin
    if type(offset) is not int or offset < 0 or offset > 1000000 or limit not in (10,20,50,100):
        raise ValueError('Некорректная страница платежей.')
    if state not in (None, '', 'pending', 'succeeded', 'canceled', 'refunded'):
        raise ValueError('Некорректный статус платежа.')
    first, last = finance_reporting.boundaries(start, end, zone)
    clauses, params = [], []
    for clause, value in (('i.login=?',login), ('c.status=?',state), ('c.created*1000>=?',first), ('c.created*1000<?',last)):
        if value not in (None, ''):
            clauses.append(clause); params.append(value)
    sql = '''SELECT c.id,c.workspace_id,c.request_key,c.quantity,c.total,c.provider_id,c.status,c.created,i.login,
        r.refund_id,r.amount,r.created FROM coin_checkouts c
        LEFT JOIN identity_accounts i USING(workspace_id)
        LEFT JOIN coin_refunds r ON r.checkout_id=c.id'''
    if clauses:
        sql += ' WHERE ' + ' AND '.join(clauses)
    with identity._lock:
        require_admin(identity._db, token)
        data = identity._db.execute(sql + ' ORDER BY c.created DESC,c.id DESC', params).fetchall()
        result = []
        for record in data[offset:offset+limit]:
            row = dict(zip(('id','workspace','requestKey','quantity','totalRub','providerId','state','created'),record[:8]))
            row.update(login=record[8], refundId=record[9], refundRub=record[10], refundedAt=record[11], version=_version(row))
            row.pop('workspace')
            result.append(row)
        config = configuration()
    received = sum((Decimal(r[4]) for r in data if r[6] in ('succeeded','refunded')), Decimal(0))
    refunded = sum((Decimal(r[10]) for r in data if r[10] is not None), Decimal(0))
    return {'rows': result, 'total': len(data), 'offset': offset, 'limit': limit,
        'hasMore': offset+limit < len(data), 'configuration': config, 'timezone': zone,
        'receivedRub': format(received,'f'), 'refundedRub': format(refunded,'f')}


def _target(identity, token, order, version):
    from .account_finance import require_admin
    with identity._lock:
        require_admin(identity._db, token)
        row = _row(identity._db, order)
        if row['state'] != 'pending':
            return {'state': row['state'], 'replayed': True}
        if _version(row) != version:
            raise ValueError('Платёж изменился. Обновите список перед проверкой.')
        if not row['providerId']:
            raise ValueError('Идентификатор ЮKassa ещё не подтверждён. Исход создания требует отдельной сверки.')
        if not checkout._ID.fullmatch(row['providerId']):
            raise ValueError('Идентификатор ЮKassa требует проверки.')
        return row


class _TransactionStore:
    """Let the original checkout verifier share the caller's audit transaction."""
    def __init__(self, db):
        self.db = db

    @contextmanager
    def _write(self):
        if not self.db.in_transaction:
            raise RuntimeError('Payment review requires an open transaction')
        yield self.db


def _apply_verified(identity, token, original, version, verified, shop):
    from .account_finance import require_admin
    with identity._write() as db:
        actor, _ = require_admin(db, token)
        current = _row(db, original['id'])
        if current['state'] != 'pending':
            return {'state': current['state'], 'replayed': True}
        if _version(current) != version:
            raise ValueError('Платёж изменился во время проверки. Обновите список.')
        if verified.get('id') != original['providerId']:
            raise HTTPException(502, 'ЮKassa вернула другой платёж.')
        current_auth = checkout.merchant()
        if not current_auth or current_auth[0] != shop:
            raise ValueError('Конфигурация платежей изменилась. Повторите проверку после её подтверждения.')
        state, _, _ = checkout.apply_payment(_TransactionStore(db), original['id'], verified, shop)
        receipt = {key: verified.get(key) for key in ('id','status','paid','test','amount','recipient')}
        receipt['order'] = verified.get('metadata',{}).get('order')
        db.execute('''INSERT OR IGNORE INTO finance_payment_reviews
            VALUES(?,?,?,?,?,?,?,?,?,?,?)''', (uuid4().hex, original['id'], actor, version,
            original['state'], state, original['providerId'], _hash(receipt), original['totalRub'], 'RUB', int(time.time())))
        return {'state': state, 'replayed': False}


async def reconcile(identity, token, *, checkoutId, version):
    if not isinstance(checkoutId,str) or not checkout._ID.fullmatch(checkoutId) or not isinstance(version,str) or not re.fullmatch(r'[a-f0-9]{64}',version):
        raise ValueError('Некорректный платёж или версия.')
    original = await run_in_threadpool(_target, identity, token, checkoutId, version)
    if original.get('replayed'):
        return original
    auth = checkout.merchant()
    if not auth:
        raise HTTPException(503, 'Проверка платежа недоступна: отдельная конфигурация ЮKassa не активна.')
    # GET only. Unknown creation never initiates a replacement provider payment.
    verified = await checkout.provider('GET', '/' + original['providerId'], auth)
    if not isinstance(verified,dict) or any(not isinstance(verified.get(key),dict) for key in ('metadata','amount','recipient')):
        raise HTTPException(502, 'ЮKassa вернула неполную квитанцию.')
    return await run_in_threadpool(_apply_verified, identity, token, original, version, verified, auth[0])
