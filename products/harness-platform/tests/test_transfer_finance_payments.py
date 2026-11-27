"""Admin payment recovery through the original checkout engine; no live calls."""
import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock, patch
from uuid import uuid4
import unittest

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from platform_core import account_finance, finance_payments as payments, checkout
from platform_core.chat_api import _body, _token
from platform_core.identity import AuthenticationError
from tests import test_transfer_finance as fixture


class Payments(unittest.TestCase):
    setUp = fixture.Finance.setUp

    def seed(self, *, state='pending', known=True):
        order, provider, request = str(uuid4()), str(uuid4()), str(uuid4())
        with self.store._write() as db:
            db.execute('''INSERT INTO coin_checkouts(id,workspace_id,request_key,quantity,total,provider_id,status)
                VALUES(?,?,?,?,?,?,?)''', (order,self.scope.workspace_id,request,5,'6.50',provider if known else None,state))
        row = next(r for r in payments.report(self.store,self.admin)['rows'] if r['id']==order)
        receipt = {'id':provider,'status':'succeeded','paid':True,'test':False,
            'metadata':{'order':order},'amount':{'value':'6.50','currency':'RUB'},
            'recipient':{'account_id':'fixture-shop'}}
        return {'checkoutId':order,'version':row['version']}, receipt

    def test_verified_recovery_and_repeat_credit_once_with_audit(self):
        data, receipt = self.seed()
        provider = AsyncMock(return_value=receipt)
        with patch.object(checkout,'merchant',return_value=('fixture-shop','synthetic-credential')), patch.object(checkout,'provider',provider):
            first = asyncio.run(payments.reconcile(self.store,self.admin,**data))
            second = asyncio.run(payments.reconcile(self.store,self.admin,**data))
        self.assertEqual(first,{'state':'succeeded','replayed':False})
        self.assertEqual(second,{'state':'succeeded','replayed':True})
        provider.assert_awaited_once_with('GET','/'+receipt['id'],('fixture-shop','synthetic-credential'))
        self.assertEqual(self.store.wallet(self.alice, balance_only=True)['available'],'15')
        self.assertEqual(self.store._db.execute('SELECT count(*) FROM finance_payment_reviews').fetchone()[0],1)

    def test_disabled_unknown_and_stale_never_create_a_provider_payment(self):
        data, _ = self.seed()
        unknown, _ = self.seed(known=False)
        provider = AsyncMock()
        with patch.object(checkout,'provider',provider), patch.object(checkout,'merchant',return_value=None):
            with self.assertRaises(HTTPException) as unavailable:
                asyncio.run(payments.reconcile(self.store,self.admin,**data))
            self.assertEqual(unavailable.exception.status_code,503)
            with self.assertRaises(ValueError):
                asyncio.run(payments.reconcile(self.store,self.admin,**unknown))
            with self.assertRaises(ValueError):
                asyncio.run(payments.reconcile(self.store,self.admin,**{**data,'version':'0'*64}))
        provider.assert_not_called()
        self.assertEqual(self.store.wallet(self.alice, balance_only=True)['available'],'10')

    def test_mismatched_receipt_or_malformed_response_never_credits(self):
        data, receipt = self.seed()
        variants=[]
        for key,value in (('id',str(uuid4())),('amount',{'value':'9.99','currency':'RUB'}),
                          ('recipient',{'account_id':'different-shop'}),('metadata',{'order':str(uuid4())}),('test',True)):
            variants.append({**deepcopy(receipt),key:value})
        variants.append([])
        with patch.object(checkout,'merchant',return_value=('fixture-shop','synthetic-credential')):
            for variant in variants:
                with self.subTest(variant_type=type(variant).__name__), patch.object(checkout,'provider',AsyncMock(return_value=variant)):
                    with self.assertRaises(HTTPException):
                        asyncio.run(payments.reconcile(self.store,self.admin,**data))
        self.assertEqual(self.store.wallet(self.alice, balance_only=True)['available'],'10')
        self.assertEqual(self.store._db.execute('SELECT count(*) FROM finance_payment_reviews').fetchone()[0],0)

    def test_admin_role_rechecked_after_provider_response(self):
        data, receipt = self.seed()
        async def provider(*_args):
            self.store.set_admin('admin',False)
            return receipt
        with patch.object(checkout,'merchant',return_value=('fixture-shop','synthetic-credential')), patch.object(checkout,'provider',provider):
            with self.assertRaises(AuthenticationError):
                asyncio.run(payments.reconcile(self.store,self.admin,**data))
        self.assertEqual(self.store.wallet(self.alice, balance_only=True)['available'],'10')
        self.assertEqual(self.store._db.execute('SELECT status FROM coin_checkouts WHERE id=?',(data['checkoutId'],)).fetchone()[0],'pending')

    def test_concurrent_recovery_never_double_credits(self):
        data, receipt = self.seed()
        async def provider(*_args):
            await asyncio.sleep(0)
            return receipt
        async def both():
            return await asyncio.gather(*(payments.reconcile(self.store,self.admin,**data) for _ in range(2)))
        with patch.object(checkout,'merchant',return_value=('fixture-shop','synthetic-credential')), patch.object(checkout,'provider',provider):
            result = asyncio.run(both())
        self.assertEqual(sorted(r['replayed'] for r in result),[False,True])
        self.assertEqual(self.store.wallet(self.alice, balance_only=True)['available'],'15')
        self.assertEqual(self.store._db.execute('SELECT count(*) FROM finance_payment_reviews').fetchone()[0],1)

    def test_payment_report_filters_pagination_and_secret_boundary(self):
        for _ in range(11):
            self.seed()
        with patch.object(checkout,'merchant',return_value=('fixture-shop','do-not-return-this-credential')):
            first=payments.report(self.store,self.admin,login='alice',limit=10)
            second=payments.report(self.store,self.admin,login='alice',limit=10,offset=10)
        self.assertEqual((first['total'],len(first['rows']),len(second['rows'])),(11,10,1))
        self.assertFalse({r['id'] for r in first['rows']} & {r['id'] for r in second['rows']})
        self.assertNotIn('do-not-return-this-credential',str(first))
        self.assertTrue(first['configuration']['ready'])
        self.assertFalse(any('url' in r or 'confirmationToken' in r or 'email' in r for r in first['rows']))
        self.assertEqual(payments.report(self.store,self.admin,login='bob')['total'],0)
        with self.assertRaises(PermissionError):
            payments.report(self.store,self.alice)

    def test_http_roles_and_strict_reconcile_fields(self):
        data, receipt = self.seed()
        async def authentication(_request,_exc):
            return JSONResponse({'error':'authentication'},status_code=401)
        app=Starlette(routes=account_finance.routes(_token,_body),exception_handlers={AuthenticationError:authentication})
        app.state.identity=self.store
        with TestClient(app) as client, patch.object(checkout,'provider',AsyncMock(return_value=receipt)) as provider:
            admin={'Authorization':'Bearer '+self.admin};alice={'Authorization':'Bearer '+self.alice}
            self.assertEqual(client.get('/api/admin/payments').status_code,401)
            self.assertEqual(client.get('/api/admin/payments',headers=alice).status_code,403)
            self.assertEqual(client.get('/api/admin/payments',headers=admin).json()['total'],1)
            self.assertEqual(client.post('/api/admin/payments/reconcile',headers=alice,json=data).status_code,403)
            self.assertEqual(client.post('/api/admin/payments/reconcile',headers=admin,json={**data,'amount':'999'}).status_code,400)
            provider.assert_not_called()


if __name__=='__main__':
    unittest.main()
