"""Real browser acceptance for the integrated account and finance screens.

Uses the normal loopback app, exact SQLite ledger, authenticated routes and
the existing browser fixtures. All receipts/credentials are synthetic.
"""
from decimal import Decimal
import time
import unittest
from uuid import uuid4
from unittest.mock import AsyncMock, patch

from playwright.sync_api import expect
from test_podmasterye_independent_ui import IndependentUI, P
from platform_core import coins
from platform_core import checkout
from platform_core.identity import AuthenticationError


class FinanceUI(unittest.TestCase):
    setUpClass = classmethod(IndependentUI.setUpClass.__func__)
    setUp = IndependentUI.setUp
    tearDown = IndependentUI.tearDown
    sign_in = IndependentUI.sign_in
    ready = IndependentUI.ready

    def open_account(self, tab='profile'):
        self.page.evaluate('(tab) => window.MasterAccount.open(tab)', tab)
        expect(self.page.locator('[data-account-section="' + tab + '"]')).to_be_visible()

    def test_profile_security_sessions_and_draft_survive_navigation(self):
        self.sign_in()
        p = self.page
        p.locator('#assistant-form textarea').fill('Сохранённый черновик мастерской')
        p.locator('#account-menu').click()
        p.locator('#account-dropdown [data-account-open="profile"]').click()
        expect(p.locator('[data-account-section="profile"]')).to_be_visible()
        expect(p.locator('[data-account-login]')).to_contain_text(self.login)
        p.screenshot(path=str(self.evidence / 'account-profile.png'), animations='disabled')
        form = p.locator('[data-account-password]')
        form.locator('[name=current]').fill('wrong-password')
        form.locator('[name=password]').fill('new-fixture-password')
        form.locator('[name=confirmation]').fill('new-fixture-password')
        form.get_by_role('button', name='Изменить пароль').click()
        expect(p.locator('[data-account-message]')).to_contain_text('Проверьте текущий пароль')
        form.locator('[name=current]').fill(P)
        form.get_by_role('button', name='Изменить пароль').click()
        expect(p.locator('[data-account-message]')).to_contain_text('Пароль изменён')
        expect(form.locator('[name=current]')).to_have_value('')
        p.locator('[data-account-tab=security]').click()
        security = p.locator('[data-account-security]')
        security.locator('[name=enabled]').check()
        security.locator('[name=current]').fill('new-fixture-password')
        security.get_by_role('button', name='Сохранить защиту входа').click()
        expect(p.locator('[data-account-message]')).to_contain_text('сохранены')
        self.assertTrue(p.request.get('/api/profile/security').json()['enabled'])
        p.screenshot(path=str(self.evidence / 'account-security.png'), animations='disabled')
        other = self.app.state.identity.login(self.login, 'new-fixture-password')
        p.locator('[data-account-tab=sessions]').click()
        expect(p.locator('[data-account-sessions] li')).to_have_count(2)
        p.locator('[data-account-sessions]').get_by_role('button', name='Завершить', exact=True).click()
        expect(p.locator('[data-account-sessions] li')).to_have_count(1)
        with self.assertRaises(AuthenticationError):
            self.app.state.identity.validate_session(other)
        p.screenshot(path=str(self.evidence / 'account-sessions.png'), animations='disabled')
        p.locator('[data-account-tab=wallet]').click()
        expect(p.locator('[data-wallet-available]')).to_have_text('10,00')
        expect(p.locator('#assistant-form textarea')).to_have_value('Сохранённый черновик мастерской')
        self.assertEqual(p.request.get('/api/admin/finance').status, 403)

    def test_wallet_exact_history_pagination_and_shared_refresh(self):
        identity = self.app.state.identity
        identity.grant_coins(self.login, '9.54317045032', 'wallet-ui-precision', 'Точное начисление')
        for number in range(22):
            identity.grant_coins(self.login, '0.000000000001', 'wallet-page-' + str(number), 'Страница истории')
        self.sign_in()
        p = self.page
        self.open_account('wallet')
        expect(p.locator('[data-wallet-available]')).to_have_text('19,54')
        expect(p.locator('[data-wallet-history] tbody tr')).to_have_count(20)
        p.locator('[data-wallet-next]').click()
        expect(p.locator('[data-wallet-history] tbody tr')).to_have_count(4)
        exact = p.request.get('/api/wallet/balance').json()['available']
        self.assertEqual(Decimal(exact), Decimal('19.543170450342'))
        identity.grant_coins(self.login, '2', 'wallet-ui-refresh', 'Обновление баланса')
        p.evaluate('document.dispatchEvent(new Event("octo-wallet-refresh"))')
        expect(p.locator('#balance-label')).to_contain_text('21,54')
        expect(p.locator('[data-wallet-available]')).to_have_text('21,54')
        p.wait_for_load_state('networkidle')
        calls = []
        p.on('request', lambda request: calls.append(request.url) if request.url.endswith('/api/wallet/balance') else None)
        p.evaluate('async () => { await Promise.all(Array.from({length: 6}, () => window.MasterWallet.refresh())); }')
        self.assertEqual(len(calls), 1)
        p.screenshot(path=str(self.evidence / 'account-wallet-desktop.png'), animations='disabled')
        p.set_viewport_size({'width': 420, 'height': 900})
        p.locator('#close-nav').click()
        self.assertLessEqual(p.evaluate('document.documentElement.scrollWidth'), p.evaluate('document.documentElement.clientWidth'))

    def test_admin_review_shows_unknown_then_atomic_receipt(self):
        identity = self.app.state.identity
        identity.set_admin(self.login, True)
        token = identity.login(self.login, P)
        scope = identity.create_user_chat(token)
        operation, attempt = uuid4().hex, uuid4().hex
        with identity._write() as db:
            db.execute('INSERT INTO usage_operations VALUES(?,?,?,?,?,?)',
                (operation, scope.actor_id, scope.workspace_id, scope.chat_id, 'chat.turn', uuid4().hex))
            coins.reserve_order(db, scope.workspace_id, operation)
            db.execute('UPDATE coin_ruble_orders SET fx_e4=800000 WHERE operation_id=?', (operation,))
            db.execute('INSERT INTO coin_attempts(attempt_id,operation_id,bound,model,started_ms,rate_version,period) VALUES(?,?,?,?,?,?,?)',
                (attempt, operation, coins.UNIT, 'deepseek-flash', int(time.time() * 1000), 'deepseek-2026-11-18', 'peak'))
        self.ctx.add_cookies([{'name': 'podmaster_local_session', 'value': token, 'url': self.origin, 'httpOnly': True, 'sameSite': 'Strict'}])
        p = self.page
        p.goto('/admin/finance')
        expect(p.locator('[data-finance-summary]')).to_contain_text('Не подтверждено')
        p.locator('[data-finance-filters] [name=login]').fill(self.login)
        p.locator('[data-finance-filters]').get_by_role('button', name='Показать').click()
        expect(p.locator('[data-finance-rows] tbody tr')).to_have_count(1)
        p.locator('[data-finance-rows]').get_by_role('button', name='Сверить', exact=True).click()
        dialog = p.locator('[data-finance-review]')
        expect(dialog).to_be_visible()
        dialog.locator('[name=amount]').fill('0.001')
        dialog.locator('[name=currency]').select_option('USD')
        dialog.locator('[name=reference]').fill('synthetic-provider-invoice')
        dialog.get_by_role('button', name='Применить сверку').click()
        expect(dialog).not_to_be_visible()
        expect(p.locator('[data-finance-rows]')).to_contain_text('Учтено')
        self.assertEqual(identity.wallet(token)['available'], '9.92')
        self.assertEqual(identity.wallet(token)['reserved'], '0')
        with identity._lock:
            self.assertEqual(identity._db.execute('SELECT count(*) FROM finance_reconciliations WHERE attempt_id=?', (attempt,)).fetchone()[0], 1)

    def test_admin_payment_list_uses_verified_checkout_recovery(self):
        identity = self.app.state.identity
        identity.set_admin(self.login, True)
        token = identity.login(self.login, P)
        scope = identity.create_user_chat(token)
        order, provider_id, request_key = str(uuid4()), str(uuid4()), str(uuid4())
        with identity._write() as db:
            db.execute('''INSERT INTO coin_checkouts(id,workspace_id,request_key,quantity,total,provider_id,status)
                VALUES(?,?,?,?,?,?,?)''', (order,scope.workspace_id,request_key,5,'6.50',provider_id,'pending'))
        receipt = {'id':provider_id,'status':'succeeded','paid':True,'test':False,
            'metadata':{'order':order},'amount':{'value':'6.50','currency':'RUB'},
            'recipient':{'account_id':'fixture-shop'}}
        self.ctx.add_cookies([{'name':'podmaster_local_session','value':token,'url':self.origin,'httpOnly':True,'sameSite':'Strict'}])
        p = self.page
        provider = AsyncMock(return_value=receipt)
        with patch.object(checkout,'merchant',return_value=('fixture-shop','synthetic-credential')), patch.object(checkout,'provider',provider):
            p.goto('/admin/finance')
            p.locator('[data-finance-filters] [name=login]').fill(self.login)
            p.locator('[data-finance-filters]').get_by_role('button',name='Показать').click()
            expect(p.locator('[data-payment-rows] tbody tr')).to_have_count(1)
            expect(p.locator('[data-payment-rows]')).to_contain_text('6,50')
            p.locator('[data-payment-reconcile="'+order+'"]').click()
            expect(p.locator('[data-payment-status]')).to_have_text('ЮKassa: Оплачено')
            expect(p.locator('[data-payment-rows]')).to_contain_text('Оплачено')
            expect(p.locator('[data-payment-rows] [data-payment-reconcile]')).to_have_count(0)
            expect(p.locator('[data-finance-payments]')).to_contain_text('Поступило: 6,50 ₽')
            self.assertEqual(identity.wallet(token,balance_only=True)['available'],'15')
            provider.assert_awaited_once()
            with identity._lock:
                self.assertEqual(identity._db.execute('SELECT count(*) FROM finance_payment_reviews WHERE checkout_id=?',(order,)).fetchone()[0],1)
            p.screenshot(path=str(self.evidence/'admin-payment-recovery.png'),animations='disabled')
