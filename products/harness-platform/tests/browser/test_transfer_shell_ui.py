"""Actual browser checks: lifecycle controls and isolated analytics transport."""
import json
import re
import unittest
import time
from uuid import uuid4
from playwright.sync_api import expect
from test_podmasterye_independent_ui import IndependentUI,P
from platform_core.identity import AuthenticationError


class TransferShellUI(unittest.TestCase):
    setUpClass=classmethod(IndependentUI.setUpClass.__func__)
    setUp=IndependentUI.setUp
    tearDown=IndependentUI.tearDown
    sign_in=IndependentUI.sign_in
    ready=IndependentUI.ready

    def wait_analytics(self,expression):
        deadline=time.monotonic()+5
        while not self.page.evaluate(expression):
            if time.monotonic()>deadline:
                self.fail("Analytics condition failed: "+expression+"; actual="+str(self.page.evaluate("window.analyticsEvidence")))
            self.page.wait_for_timeout(50)

    def test_account_menu_keyboard_dark_mobile_and_one_wallet(self):
        self.sign_in();p=self.page
        p.locator('#assistant-form textarea').fill('Черновик сохраняется при открытии профиля')
        p.locator('#account-menu').focus();p.keyboard.press('Enter')
        expect(p.locator('#account-dropdown')).to_be_visible()
        p.keyboard.press('Escape');expect(p.locator('#account-dropdown')).to_be_hidden()
        expect(p.locator('#account-menu')).to_be_focused()
        p.set_viewport_size({'width':420,'height':900})
        p.locator('#theme-quick').click()
        expect(p.locator('#account-menu')).to_be_visible()
        p.locator('#account-menu').click();p.locator('#account-dropdown [data-account-open=wallet]').click()
        expect(p.locator('[data-account-section=wallet]')).to_be_visible()
        expect(p.locator('[data-wallet-available]')).to_have_text('10,00')
        expect(p.locator('#accounting-assumptions')).to_be_hidden()
        expect(p.locator('#assistant-form textarea')).to_have_value('Черновик сохраняется при открытии профиля')
        self.assertEqual(p.locator('#wallet-info').count(),1)
        self.assertFalse(p.evaluate('document.documentElement.scrollWidth>window.innerWidth+1'))

    def test_lifecycle_real_ui_preserves_wallet_revokes_and_restores_access(self):
        identity=self.app.state.identity
        administrator='lifecycle_admin_'+uuid4().hex[:8]
        identity.create_account(administrator,P)
        with identity._write() as db:
            db.execute('INSERT INTO identity_admins SELECT actor_id FROM identity_accounts WHERE login=?',(administrator,))
            actor=db.execute('SELECT actor_id FROM identity_accounts WHERE login=?',(self.login,)).fetchone()[0]
        token=identity.login(administrator,P);victim=identity.login(self.login,P);money=identity.wallet(victim)
        self.ctx.add_cookies([{'name':'podmaster_local_session','value':token,'url':self.origin,'httpOnly':True,'sameSite':'Strict'}])
        p=self.page;p.goto('/admin/statistics?q='+self.login)
        p.locator('[data-account-action=block][data-actor="'+actor+'"]').click()
        dialog=p.locator('#account-lifecycle-dialog');expect(dialog).to_be_visible()
        expect(dialog.locator('[data-account-preview]')).to_contain_text('Хозяйственные записи, файлы, деньги')
        dialog.locator('[name=reason]').fill('Проверка жизненного цикла синтетического аккаунта')
        dialog.locator('[data-account-confirm] button').click()
        expect(dialog.locator('[data-account-result]')).to_contain_text('Изменено аккаунтов: 1')
        with self.assertRaises(AuthenticationError):identity.validate_session(victim)
        with self.assertRaises(AuthenticationError):identity.login(self.login,P)
        dialog.locator('[data-account-close]').click()
        p.locator('[data-account-action=restore][data-actor="'+actor+'"]').click()
        dialog.locator('[name=reason]').fill('Восстановление синтетического аккаунта')
        dialog.locator('[data-account-confirm] button').click()
        expect(dialog.locator('[data-account-result]')).to_contain_text('Изменено аккаунтов: 1')
        restored=identity.login(self.login,P)
        self.assertEqual(identity.wallet(restored)['available'],money['available'])
        dialog.locator('[data-account-close]').click()
        p.locator('[data-account-select][value="'+actor+'"]').check()
        p.locator('[data-account-batch] [name=action]').select_option('delete')
        p.locator('[data-account-batch] button').click()
        expect(dialog.locator('[data-account-preview]')).to_contain_text('Не утверждена политика хранения')
        expect(dialog.locator('[data-account-confirm]')).to_be_hidden()

    def test_public_analytics_no_request_until_consent_one_spa_hit_and_withdrawal(self):
        p=self.page;external=[]
        p.route('**/api/analytics/config',lambda route:route.fulfill(status=200,content_type='application/json',body=json.dumps({'enabled':True,'counter':'987654321','origin':self.origin})))
        def tag(route):
            external.append(route.request.url)
            route.fulfill(status=200,content_type='text/javascript',body='window.analyticsEvidence=[];window.ym=function(){window.analyticsEvidence.push(Array.from(arguments));};')
        p.route(re.compile(r'https://mc\.yandex\.(?:ru|com)/'),tag)
        p.goto('/about/')
        expect(p.locator('#cookie-accept')).to_have_text('Разрешить аналитику')
        self.assertEqual(external,[])
        p.locator('#cookie-decline').click();p.reload()
        expect(p.locator('#cookie-choice')).to_be_hidden();self.assertEqual(external,[])
        p.locator('[data-privacy-options]').click();p.locator('#cookie-accept').click()
        self.wait_analytics('window.analyticsEvidence?.filter(x=>x[1]==="hit").length===1')
        self.assertEqual(len(external),1)
        p.locator('#public-menu a[data-public-panel=support]').click()
        self.wait_analytics('window.analyticsEvidence.filter(x=>x[1]==="hit").length===2')
        p.evaluate('document.dispatchEvent(new Event("master:pageview"))')
        self.assertEqual(p.evaluate('analyticsEvidence.filter(x=>x[1]==="hit").length'),2)
        p.locator('#public-menu a[data-public-panel=login]').click()
        self.wait_analytics('analyticsEvidence.some(x=>x[1]==="destruct")')
        self.assertEqual(p.evaluate('analyticsEvidence.filter(x=>x[1]==="hit").length'),2)
        p.locator('#public-menu a[data-public-panel=privacy]').click()
        self.wait_analytics('analyticsEvidence.filter(x=>x[1]==="hit").length===3')
        p.locator('[data-privacy-options]').click();p.locator('#cookie-decline').click()
        p.locator('#public-menu a[data-public-panel=about]').click()
        self.assertEqual(p.evaluate('analyticsEvidence.filter(x=>x[1]==="hit").length'),3)
        self.assertEqual(p.evaluate('analyticsEvidence.filter(x=>x[1]==="destruct").length'),2)
        self.assertTrue(all('?' not in value for value in p.evaluate('analyticsEvidence.filter(x=>x[1]==="hit").map(x=>x[2])')))
        p.goto('/admin');self.assertEqual(len(external),1)
