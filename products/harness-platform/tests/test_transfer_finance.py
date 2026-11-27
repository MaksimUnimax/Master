"""Finance/profile acceptance against SQLite and real HTTP route boundaries.

Provider transports are not contacted. Synthetic provider receipts exercise
the production ledger, versioned migrations, reserves and audit transactions.
"""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from uuid import uuid4

from starlette.applications import Starlette
from starlette.testclient import TestClient
from starlette.responses import JSONResponse

from platform_core import account_finance as api, coins, finance_reporting as reporting, service_billing, service_catalog
from platform_core.account_access import AccountAccess
from platform_core.account_lifecycle import initialize as initialize_lifecycle
from platform_core.chat_api import _body, _token
from platform_core.finance_schema import ensure
from platform_core.identity import AuthenticationError, IdentityStore
from platform_core.operation_grants import ensure_operation_schema


class Finance(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'finance.sqlite3'
        self.store = IdentityStore(self.path)
        self.addCleanup(self.store.close)
        self.store.create_account('admin', 'password')
        self.store.create_account('alice', 'password')
        self.store.create_account('bob', 'password')
        AccountAccess(self.store)
        self.store.set_admin('admin', True)
        self.admin = self.store.login('admin', 'password')
        self.alice = self.store.login('alice', 'password')
        self.bob = self.store.login('bob', 'password')
        self.scope = self.store.create_user_chat(self.alice)
        self.bob_scope = self.store.create_user_chat(self.bob)
        with self.store._write() as db:
            initialize_lifecycle(db)

    def attempt(self, *, rate='deepseek-2026-11-18', charge=None, bound='1', model='deepseek-flash',
                evidence=None, usage=None, source='chat.turn', period='peak', scope=None, fx=800000):
        scope = scope or self.scope
        operation, attempt = uuid4().hex, uuid4().hex
        with self.store._write() as db:
            db.execute('INSERT INTO usage_operations VALUES(?,?,?,?,?,?)',
                (operation, scope.actor_id, scope.workspace_id, scope.chat_id, source, uuid4().hex))
            coins.reserve_order(db, scope.workspace_id, operation)
            db.execute('UPDATE coin_ruble_orders SET fx_e4=? WHERE operation_id=?', (fx, operation))
            db.execute('INSERT INTO coin_attempts(attempt_id,operation_id,bound,charge,model,started_ms,rate_version,period,usage_json,evidence) VALUES(?,?,?,?,?,?,?,?,?,?)',
                (attempt, operation, coins.parse_amount(bound, allow_zero=True),
                 coins.parse_amount(charge, allow_zero=True) if charge is not None else None,
                 model, int(time.time() * 1000), rate, period, json.dumps(usage or {}), evidence))
        return operation, attempt

    def record(self, attempt):
        with self.store._lock:
            return next(row for row in reporting.rows(self.store._db) if row['attempt_id'] == attempt)

    def test_exact_wallet_history_and_provider_confidentiality(self):
        self.attempt(charge='0.123456789012', evidence='completed', usage={'input_tokens': 11, 'cache_read_input_tokens': 12, 'output_tokens': 13})
        self.attempt(bound='0.456789012345')
        self.attempt(charge='2', scope=self.bob_scope)
        wallet = self.store.wallet(self.alice)
        self.assertEqual(wallet['available'], '9.419754198643')
        self.assertEqual(wallet['reserved'], '0.456789012345')
        self.assertNotIn('providerMeters', wallet)
        self.assertTrue(all('meter' not in row for row in wallet['charges']))
        history = api.history(self.store, self.alice)
        self.assertEqual(history['total'], 3)
        self.assertEqual(sum(Decimal(row['coins'] or '0') for row in history['rows']), Decimal('9.876543210988'))
        self.assertTrue(all('providerUsd' not in row and 'workspace' not in row for row in history['rows']))
        admin = self.store.wallet(self.admin, account_login='alice')
        self.assertEqual(admin['providerMeters']['DeepSeek']['coins'], '0.123456789012')
        self.assertEqual(admin['providerMeters']['DeepSeek']['unknownCostAttempts'], 1)

    def test_supplier_customer_currency_units_and_unknown_are_separate(self):
        self.attempt(rate='openrouter-v1', model='test/model', charge='1', evidence='openrouter-usd:0.05', period='assistant.illustration')
        self.attempt(rate='deepseek-files-2026-11-25', model='deepseek-ocr', charge='0.5', evidence='media-receipt',
            usage={'unit': 'pages', 'quantity': 3, 'providerAmount': '0.9'})
        self.attempt(rate='deepseek-web-2026-11-27', model='deepseek-search-api', charge='0.006', evidence='web-completed')
        self.attempt(rate='unreviewed-future-tariff', model='unknown', charge='0.25', evidence='completed')
        report = api.admin_report(self.store, self.admin)
        self.assertEqual(report['totals']['coins'], '1.756')
        self.assertEqual(Decimal(report['totals']['knownProviderRub']), Decimal('4.906'))
        self.assertIsNone(report['totals']['providerRub'])
        self.assertFalse(report['totals']['costComplete'])
        self.assertEqual(report['totals']['unknownCostAttempts'], 1)
        self.assertEqual(report['kinds']['images']['providerRub'], '4.00')
        self.assertEqual(report['kinds']['files']['units'], {'pages': 3})
        self.assertEqual(report['kinds']['web']['units'], {'searches': 1})
        self.assertEqual(report['providers']['Не определён']['coins'], '0.25')
        self.assertEqual(sum(Decimal(row['coins']) for row in report['providers'].values()), Decimal(report['totals']['coins']))

    def test_pagination_filters_and_payments_are_not_double_counted(self):
        with self.store._write() as db:
            for n in range(25):
                coins.grant(db, 'fixture', str(n), self.scope.workspace_id, '0.000000000001', 'Точное начисление')
            db.execute("INSERT INTO coin_checkouts(id,workspace_id,request_key,quantity,total,provider_id,status) VALUES('pay',?,'pay',5,'6.50','provider-pay','succeeded')", (self.scope.workspace_id,))
            coins.grant(db, 'yookassa', 'provider-pay', self.scope.workspace_id, '5', 'Покупка монет')
        first = api.history(self.store, self.alice, limit=10)
        second = api.history(self.store, self.alice, limit=10, offset=10)
        self.assertEqual(first['total'], 27)
        self.assertFalse({row['id'] for row in first['rows']} & {row['id'] for row in second['rows']})
        purchases = api.history(self.store, self.alice, kind='purchase')
        self.assertEqual(len(purchases['rows']), 1)
        report = api.admin_report(self.store, self.admin, login='alice')
        self.assertEqual(report['payments']['receivedRub'], '6.50')
        self.assertEqual(report['payments']['bonusCoins'], '10.000000000025')
        for options in ({'limit': 7}, {'offset': -1}, {'kind': 'sql'}):
            with self.assertRaises(ValueError):
                api.history(self.store, self.alice, **options)

    def test_report_states_filters_and_exact_sorting(self):
        first_op, first = self.attempt(charge='0.000000000002', evidence='completed')
        _, second = self.attempt(charge='0.000000000001', evidence='completed')
        running_op, running = self.attempt()
        _, pending = self.attempt()
        with self.store._write() as db:
            db.execute('INSERT INTO usage_grants VALUES(?,?,?)',
                       ('report-active-grant', running_op, int(time.time()) + 60))
        report = api.admin_report(self.store, self.admin, sort='coins', direction='asc')
        self.assertEqual([r['id'] for r in report['rows'][:2]], [second, first])
        self.assertEqual({r['id'] for r in api.admin_report(self.store, self.admin, state='running')['rows']}, {running})
        self.assertEqual({r['id'] for r in api.admin_report(self.store, self.admin, state='pending')['rows']}, {pending})
        self.assertEqual([r['id'] for r in api.admin_report(self.store, self.admin, operation=first_op)['rows']], [first])
        with self.store._lock:
            scoped = list(reporting.rows(self.store._db, operations=[first_op],
                workspace=self.scope.workspace_id, actor=self.scope.actor_id, chat=self.scope.chat_id))
            self.assertEqual([r['attempt_id'] for r in scoped], [first])
            self.assertEqual(list(reporting.rows(self.store._db, operations=[first_op], actor=self.bob_scope.actor_id)), [])
        for filters in ({'sort': 'evidence'}, {'direction': 'other'}, {'state': 'invented'}):
            with self.assertRaises(ValueError):
                api.admin_report(self.store, self.admin, **filters)

    def test_verified_refund_after_spend_keeps_negative_balance_exact(self):
        from platform_core.checkout import apply_full_refund
        payment_id, refund_id = str(uuid4()), str(uuid4())
        with self.store._write() as db:
            db.execute("INSERT INTO coin_checkouts(id,workspace_id,request_key,quantity,total,provider_id,status) VALUES('refund-order',?,'refund-key',5,'6.50',?,'succeeded')", (self.scope.workspace_id,payment_id))
            coins.grant(db, 'yookassa', payment_id, self.scope.workspace_id, '5', 'Покупка монет')
        self.attempt(charge='10.5', bound='11', evidence='completed')
        amount = {'value': '6.50', 'currency': 'RUB'}
        refund = {'id': refund_id, 'payment_id': payment_id, 'status': 'succeeded', 'amount': amount}
        payment = {'id': payment_id, 'metadata': {'order': 'refund-order'}, 'amount': amount,
            'refunded_amount': amount, 'recipient': {'account_id': 'fixture-shop'}, 'test': False, 'status': 'succeeded'}
        apply_full_refund(self.store, 'refund-order', refund, payment, 'fixture-shop')
        apply_full_refund(self.store, 'refund-order', refund, payment, 'fixture-shop')
        self.assertEqual(self.store.wallet(self.alice, balance_only=True)['available'], '-0.5')
        rows = api.history(self.store, self.alice)['rows']
        self.assertEqual(sum(Decimal(row['coins'] or '0') for row in rows), Decimal('-0.5'))
        report = api.admin_report(self.store, self.admin, login='alice')
        self.assertEqual(report['payments']['receivedRub'], '6.50')
        self.assertEqual(report['payments']['refundedRub'], '6.50')
        self.assertEqual(report['payments']['netRub'], '0.00')
        self.assertEqual(coins.display(-1), '-0.000000000001')
        with self.assertRaises(coins.InsufficientCoins):
            self.attempt()

    def test_platform_totals_exceed_sqlite_integer_range_without_rounding(self):
        self.store.grant_coins('alice', '7999990', 'large-wallet-alice', 'Fixture total')
        self.store.grant_coins('bob', '7999990', 'large-wallet-bob', 'Fixture total')
        report = api.admin_report(self.store, self.admin)
        self.assertEqual(report['payments']['bonusCoins'], '16000010')

    def test_reconciliation_owns_version_and_is_atomic_idempotent(self):
        _, attempt = self.attempt(bound='1')
        data = dict(attemptId=attempt, version=self.record(attempt)['version'], amount='0.005', currency='USD', reference='invoice-123')
        with self.assertRaises(PermissionError):
            api.reconcile(self.store, self.alice, **data)
        result = api.reconcile(self.store, self.admin, **data)
        self.assertEqual(result['coins'], '0.4')
        self.assertTrue(api.reconcile(self.store, self.admin, **data)['replayed'])
        for change in ({'reference': 'invoice-456'}, {'amount': '0.006'}, {'currency': 'RUB'}):
            with self.assertRaises(ValueError):
                api.reconcile(self.store, self.admin, **{**data, **change})
        with self.store._lock:
            self.assertEqual(self.store._db.execute('SELECT count(*) FROM finance_reconciliations').fetchone()[0], 1)
        self.assertEqual(self.store.wallet(self.alice)['available'], '9.6')
        self.assertEqual(self.store.wallet(self.alice)['reserved'], '0')
        self.assertEqual(self.record(attempt)['supplier_usd'], Decimal('0.005'))

    def test_reconciliation_active_stale_unknown_and_excess(self):
        operation, attempt = self.attempt(bound='1')
        data = dict(attemptId=attempt, version=self.record(attempt)['version'], amount='0.02', currency='USD', reference='invoice-123')
        with self.store._write() as db:
            db.execute('INSERT INTO usage_grants VALUES(?,?,?)', ('grant1', operation, int(time.time()) + 60))
        with self.assertRaisesRegex(ValueError, 'active'):
            api.reconcile(self.store, self.admin, **data)
        with self.store._write() as db:
            db.execute('DELETE FROM usage_grants')
        with self.assertRaisesRegex(ValueError, 'reservation'):
            api.reconcile(self.store, self.admin, **data)
        with self.assertRaisesRegex(ValueError, 'изменилась'):
            api.reconcile(self.store, self.admin, **{**data, 'version': '0' * 64})
        _, unknown = self.attempt(rate='unknown-tariff', bound='1')
        with self.assertRaisesRegex(ValueError, 'адаптер'):
            api.reconcile(self.store, self.admin, **{**data, 'attemptId': unknown, 'version': self.record(unknown)['version']})
        self.assertEqual(self.store.wallet(self.alice)['reserved'], '2')

    def test_media_late_cost_excess_retains_supplier_receipt(self):
        _, attempt = self.attempt(rate='deepseek-files-2026-11-25', model='deepseek-asr', bound='0.5')
        data = dict(attemptId=attempt, version=self.record(attempt)['version'], amount='0.9', currency='RUB', reference='media-receipt-123')
        self.assertEqual(api.reconcile(self.store, self.admin, **data)['coins'], '0.5')
        row = self.record(attempt)
        self.assertEqual(row['supplier_rub'], Decimal('0.9'))
        self.assertEqual(self.store.wallet(self.alice)['available'], '9.5')

    def test_concurrent_reconciliation_does_not_double_debit(self):
        _, attempt = self.attempt(bound='2')
        data = dict(attemptId=attempt, version=self.record(attempt)['version'], amount='0.01', currency='USD', reference='concurrent-invoice')
        def reconcile():
            with IdentityStore(self.path) as store:
                return api.reconcile(store, self.admin, **data)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: reconcile(), range(2)))
        self.assertEqual(sorted(r['replayed'] for r in results), [False, True])
        self.assertEqual(self.store.wallet(self.alice)['available'], '9.2')

    def test_sessions_are_isolated_and_revoke_only_target_authority(self):
        other = self.store.login('alice', 'password')
        data = api.sessions(self.store, self.alice)['sessions']
        self.assertEqual(len(data), 2)
        target = next(row['id'] for row in data if not row['current'])
        bob_session = api.sessions(self.store, self.bob)['sessions'][0]['id']
        with self.assertRaises(LookupError):
            api.revoke_session(self.store, self.alice, action='revoke', session_id=bob_session)
        api.revoke_session(self.store, self.alice, action='revoke', session_id=target)
        with self.assertRaises(AuthenticationError):
            self.store.validate_session(other)
        self.store.validate_session(self.alice)
        self.store.validate_session(self.bob)
        self.assertTrue(all('digest' not in row for row in data))

    def test_password_and_security_keep_existing_auth_contract(self):
        other = self.store.login('alice', 'password')
        self.assertIsNone(self.store.change_password(self.alice, 'wrong', 'new-password'))
        renewed = self.store.change_password(self.alice, 'password', 'new-password')
        for previous in (self.alice, other):
            with self.assertRaises(AuthenticationError):
                self.store.validate_session(previous)
        self.store.validate_session(renewed)
        self.assertEqual(len(api.sessions(self.store, renewed)['sessions']), 1)
        access = AccountAccess(self.store)
        with self.assertRaises(Exception) as error:
            access.configure(self.admin, 'password', False)
        self.assertEqual(getattr(error.exception, 'status', None), 403)

    def test_blocked_account_cannot_create_session_or_financial_reserve(self):
        with self.store._write() as db:
            db.execute("UPDATE account_lifecycle SET status='blocked' WHERE actor_id=?", (self.scope.actor_id,))
        with self.assertRaises(AuthenticationError):
            self.store.login('alice', 'password')
        with self.assertRaises(AuthenticationError):
            self.store.wallet(self.alice)
        with self.assertRaises(AuthenticationError):
            self.attempt()
        self.store.validate_session(self.bob)

    def test_migration_repeat_retains_money_and_session_identity(self):
        self.attempt(bound='0.123456789012')
        before = api.sessions(self.store, self.alice)
        balance = self.store.wallet(self.alice)
        with self.store._write() as db:
            ensure(db)
            ensure(db)
        with IdentityStore(self.path) as reopened:
            self.assertEqual(api.sessions(reopened, self.alice), before)
            self.assertEqual(reopened.wallet(self.alice)['available'], balance['available'])
            self.assertEqual(reopened.wallet(self.alice)['reserved'], '0.123456789012')
            self.assertEqual(reopened._db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(reopened._db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_upgrade_from_unmodified_production_snapshot_preserves_every_ledger_row(self):
        baseline = Path(__file__).resolve().parents[4] / 'baseline/products/harness-platform'
        # The acceptance checkout includes the frozen production source. This
        # test builds its real schema, rather than a hand-made approximation.
        if not (baseline / 'platform_core/identity.py').exists():
            self.skipTest('requires the frozen production source for upgrade acceptance')
        old_path = Path(self.temp.name) / 'old.sqlite3'
        source = r'''
import json,sys
from platform_core.identity import IdentityStore
from platform_core import coins
with IdentityStore(sys.argv[1]) as store:
    store.create_account('legacy','password')
    token=store.login('legacy','password')
    scope=store.create_user_chat(token)
    with store._write() as db:
        db.execute('INSERT INTO usage_operations VALUES(?,?,?,?,?,?)',('old-op',scope.actor_id,scope.workspace_id,scope.chat_id,'chat.turn','old-rid'))
        coins.reserve_order(db,scope.workspace_id,'old-op')
        db.execute('INSERT INTO coin_attempts(attempt_id,operation_id,bound,model,started_ms,rate_version,period) VALUES(?,?,?,?,?,?,?)',('old-attempt','old-op',123456789012,'deepseek-flash',1795760000000,'deepseek-2026-11-18','peak'))
    print(json.dumps({'token':token,'wallet':store.wallet(token)}))
'''
        old = json.loads(subprocess.run([sys.executable, '-c', source, str(old_path)], cwd=baseline,
            capture_output=True, text=True, check=True).stdout)
        preserved = ('identity_accounts', 'identity_sessions', 'identity_session_preferences', 'coin_grants', 'coin_orders', 'coin_ruble_orders', 'coin_attempts', 'usage_operations')
        with sqlite3.connect(old_path) as db:
            before = {name: db.execute('SELECT * FROM ' + name + ' ORDER BY rowid').fetchall() for name in preserved}
        with IdentityStore(old_path) as upgraded:
            self.assertEqual(upgraded.wallet(old['token'])['available'], old['wallet']['available'])
            self.assertEqual(upgraded.wallet(old['token'])['reserved'], '0.123456789012')
            after = {name: upgraded._db.execute('SELECT * FROM ' + name + ' ORDER BY rowid').fetchall() for name in preserved}
            self.assertEqual(before, after)
            session = api.sessions(upgraded, old['token'])['sessions'][0]
            self.assertTrue(session['current'])
            self.assertIsNone(session['createdAt'])
            self.assertEqual(upgraded._db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_registered_generic_service_uses_one_wallet_and_exact_tariff(self):
        service_catalog.register('fixture-service', 'Fixture Service', 'items', 'fixture-service-v1')
        key = 'synthetic-service-credential'
        with self.store._write() as db:
            tariff = service_billing.configure(db, 'fixture-service', key, package_rub='1.25', package_units=10,
                available_units=10, evidence='invoice-fixture-123', enabled=True, expected=None)
            plan = service_billing.quote(db, 'fixture-service', key, 3)
            self.assertEqual(plan['bound'], 375000000000)
            service_billing.reserve(db, self.scope, 'service-operation', 'service-attempt', 'fixture.service', 'r1', 'group1', plan, key)
        self.assertEqual(self.store.wallet(self.alice)['reserved'], '0.375')
        with self.store._write() as db:
            service_billing.dispatch(db, 'service-attempt', key)
            self.assertTrue(service_billing.settle(db, 'service-attempt', 2, 'receipt-123', 'verified-receipt'))
            self.assertTrue(service_billing.settle(db, 'service-attempt', 2, 'receipt-123', 'verified-receipt'))
        self.assertEqual(self.store.wallet(self.alice)['available'], '9.75')
        self.assertEqual(self.store.wallet(self.alice)['reserved'], '0')
        meters = self.store.wallet(self.admin, account_login='alice')['providerMeters']['Fixture Service']
        self.assertEqual(meters['coins'], '0.25')
        self.assertEqual(meters['providerRub'], '0.25')
        self.assertEqual(meters['quantity'], 2)

    def test_exact_starting_balance_and_parallel_reserves(self):
        service_catalog.register('fixture-budget', 'Fixture Budget', 'items', 'fixture-budget-v1')
        key = 'synthetic-budget-credential'
        with self.store._write() as db:
            service_billing.configure(db, 'fixture-budget', key, package_rub='10', package_units=10,
                available_units=10, evidence='budget-invoice-123', enabled=True, expected=None)
        self.attempt(charge='9')
        with self.store._write() as db:
            plan = service_billing.quote(db, 'fixture-budget', key, 1)
            service_billing.require_balance(db, self.scope.workspace_id, plan['bound'])
        def reserve(number):
            with IdentityStore(self.path) as store:
                with store._write() as db:
                    try:
                        fresh = service_billing.quote(db, 'fixture-budget', key, 1)
                        service_billing.reserve(db, self.scope, 'parallel-op-' + str(number), 'parallel-attempt-' + str(number),
                            'fixture.budget', 'r' + str(number), 'parallel-group', fresh, key)
                        return True
                    except service_billing.WalletShortfall:
                        return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, (1, 2)))
        self.assertEqual(sorted(results), [False, True])
        wallet = self.store.wallet(self.alice)
        self.assertEqual((wallet['available'], wallet['reserved']), ('0', '1'))
        with self.store._write() as db:
            pending = db.execute("SELECT attempt_id FROM service_attempt_details WHERE state='reserved'").fetchone()[0]
            self.assertTrue(service_billing.settle(db, pending, 0, None, 'not_dispatched', not_dispatched=True))
        self.assertEqual(self.store.wallet(self.alice)['available'], '1')
        self.assertEqual(self.store.wallet(self.alice)['reserved'], '0')

    def test_balance_below_minimum_is_rejected_without_a_paid_attempt(self):
        self.attempt(charge='9.000000000001')
        with self.store._write() as db:
            before = db.execute('SELECT count(*) FROM coin_attempts').fetchone()[0]
            with self.assertRaises(service_billing.WalletShortfall) as error:
                service_billing.require_balance(db, self.scope.workspace_id, coins.UNIT)
            self.assertEqual(error.exception.required - error.exception.available, 1)
            self.assertEqual(db.execute('SELECT count(*) FROM coin_attempts').fetchone()[0], before)

    def test_unknown_operation_can_confirm_zero_without_assuming_it(self):
        _, attempt = self.attempt(rate='openrouter-v1', model='fixture/model', bound='1')
        before = self.record(attempt)
        self.assertIsNone(before['supplier_rub'])
        data = dict(attemptId=attempt, version=before['version'], amount='0', currency='USD', reference='provider-statement-zero')
        with self.assertRaises(ValueError):
            api.reconcile(self.store, self.admin, **{**data, 'reference': 'Bearer synthetic-secret'})
        self.assertEqual(api.reconcile(self.store, self.admin, **data)['coins'], '0')
        self.assertEqual(self.record(attempt)['supplier_rub'], Decimal(0))
        self.assertEqual(self.store.wallet(self.alice)['available'], '10')

    def test_http_role_boundaries_and_no_cross_account_history(self):
        self.attempt(charge='0.01')
        async def authentication(_request, _exc):
            return JSONResponse({'error': 'authentication'}, status_code=401)
        app = Starlette(routes=api.routes(_token, _body), exception_handlers={AuthenticationError: authentication})
        app.state.identity = self.store
        with TestClient(app) as client:
            alice = {'Authorization': 'Bearer ' + self.alice}
            admin = {'Authorization': 'Bearer ' + self.admin}
            self.assertEqual(client.get('/api/profile').status_code, 401)
            self.assertEqual(client.get('/api/admin/finance', headers=alice).status_code, 403)
            self.assertEqual(client.get('/api/admin/finance', headers=admin).status_code, 200)
            response = client.get('/api/wallet/history?login=bob', headers=alice)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['total'], 2)
            self.assertEqual(client.post('/api/profile', headers=alice, json={'admin': True}).status_code, 405)
            self.assertEqual(client.post('/api/profile/sessions', headers=alice, json={'action': 'others', 'actor': 'bob'}).status_code, 400)


if __name__ == '__main__':
    unittest.main()
