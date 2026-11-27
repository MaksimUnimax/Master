"""Dedicated-counter configuration, consent boundary and concurrency checks."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from platform_core import analytics
from platform_core.identity import IdentityStore
from platform_core.podmasterye_domain import Conflict


class AnalyticsConfiguration(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.path=Path(self.directory.name)/'metrika.json'
        self.identity=IdentityStore(Path(self.directory.name)/'identity.sqlite3');self.addCleanup(self.identity.close)
        self.identity.create_account('admin-fixture','fixture-password')
        self.identity.create_account('user-fixture','fixture-password')
        with self.identity._write() as db:
            db.execute("INSERT INTO identity_admins SELECT actor_id FROM identity_accounts WHERE login='admin-fixture'")
        self.admin=self.identity.login('admin-fixture','fixture-password')
        self.user=self.identity.login('user-fixture','fixture-password')
        self.origin=patch.dict(os.environ,{'PODMASTERYE_PUBLIC_ORIGIN':'https://mastersckaya.ru'})
        self.origin.start();self.addCleanup(self.origin.stop)

    def configure(self,enabled,revision=None):
        return analytics.configure(self.identity,self.admin,self.path,enabled,revision or analytics.snapshot(self.path)['revision'])

    def test_disabled_until_dedicated_config_and_explicit_enable(self):
        self.assertEqual(analytics.public_configuration(self.path,'mastersckaya.ru'),{'enabled':False})
        with self.assertRaises(ValueError):self.configure(True)
        self.path.write_text(json.dumps({'counter':'987654321','token':'synthetic-report-token'}))
        self.assertFalse(analytics.snapshot(self.path)['enabled'])
        current=self.configure(True)
        self.assertTrue(current['enabled'])
        public=analytics.public_configuration(self.path,'mastersckaya.ru')
        self.assertEqual(public,{'enabled':True,'counter':'987654321','origin':'https://mastersckaya.ru'})
        self.assertNotIn('token',repr(public))
        self.assertEqual(self.path.stat().st_mode&0o777,0o600)
        for host in ('test.invalid','www.mastersckaya.ru','podmasterye.185-219-43-9.sslip.io'):
            self.assertEqual(analytics.public_configuration(self.path,host),{'enabled':False})
        self.configure(False)
        self.assertFalse(analytics.public_configuration(self.path,'mastersckaya.ru')['enabled'])

    def test_unknown_origin_foreign_counter_role_and_stale_edit_fail_closed(self):
        self.path.write_text(json.dumps({'counter':'987654321','token':'synthetic-report-token'}))
        first=analytics.snapshot(self.path)
        with self.assertRaises(PermissionError):
            analytics.configure(self.identity,self.user,self.path,True,first['revision'])
        with patch.dict(os.environ,{'PODMASTERYE_PUBLIC_ORIGIN':''}):
            with self.assertRaises(ValueError):self.configure(True)
        self.configure(True)
        with self.assertRaises(Conflict):self.configure(False,first['revision'])
        self.path.write_text(json.dumps({'counter':'114504756','token':'synthetic-report-token','analyticsEnabled':True}))
        self.assertEqual(analytics.public_configuration(self.path,'mastersckaya.ru'),{'enabled':False})
        with self.assertRaises(ValueError):analytics.snapshot(self.path)

    def test_malformed_configuration_does_not_load_external_counter(self):
        for value in ('not json','[]',json.dumps({'counter':12,'token':'synthetic'})):
            self.path.write_text(value)
            self.assertEqual(analytics.public_configuration(self.path,'mastersckaya.ru'),{'enabled':False})
