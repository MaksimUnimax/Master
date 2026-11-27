#!/usr/bin/env python3
"""Read-only production backup, local-copy anonymization and migration proof.

No keys/configuration files are copied. The tool never opens the source writable.
The backup command is stdlib-only. Verify runs the candidate schema initializers
and native history reader without starting paid, Telegram or timer operations.
Reports contain counts, integer totals and hashes, never account/chat contents.
"""
import argparse
import asyncio
import base64
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys


def quoted(name):
    return '"' + name.replace('"', '""') + '"'


def digest(value):
    def encode(item):
        if isinstance(item, bytes):
            return {'bytes': base64.b64encode(item).decode()}
        raise TypeError(type(item).__name__)
    raw = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'), default=encode)
    return hashlib.sha256(raw.encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def readonly(path):
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=20)
    db.execute('PRAGMA query_only=ON')
    return db


def tables(db):
    return [r[0] for r in db.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def snapshot(db, previous=None):
    result = {}
    for table in previous or tables(db):
        columns = previous[table]['columns'] if previous else [r[1] for r in db.execute('PRAGMA table_info(' + quoted(table) + ')')]
        rows = db.execute('SELECT ' + ','.join(map(quoted, columns)) + ' FROM ' + quoted(table)).fetchall()
        result[table] = {'columns': columns, 'rows': len(rows), 'sha256': digest(sorted((digest(r) for r in rows)))}
    assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',), 'SQLite integrity failure'
    assert not db.execute('PRAGMA foreign_key_check').fetchall(), 'SQLite foreign-key failure'
    return result


FINANCIAL = {
    'coin_grants': ('issuer', 'key', 'workspace_id', 'amount', 'created'),
    'coin_orders': ('operation_id', 'workspace_id', 'cap', 'markup', 'coins_per_usd', 'budget_hit', 'closed', 'created'),
    'coin_attempts': ('attempt_id', 'operation_id', 'bound', 'charge', 'model', 'started_ms', 'rate_version', 'period'),
    'coin_ruble_orders': ('operation_id', 'fx_e4'),
    'coin_checkouts': ('id', 'workspace_id', 'request_key', 'quantity', 'total', 'status', 'created'),
    'coin_refunds': ('refund_id', 'payment_id', 'checkout_id', 'workspace_id', 'amount', 'created'),
    'usage_operations': ('operation_id', 'actor_id', 'workspace_id', 'chat_id', 'source', 'run_key'),
    'guest_filter_daily': ('day', 'calls', 'receipts', 'rejected', 'input', 'cache', 'output', 'usd', 'rub'),
}


def financial(db):
    existing = set(tables(db))
    hashes = {}
    for table, columns in FINANCIAL.items():
        if table in existing:
            rows = db.execute('SELECT ' + ','.join(map(quoted, columns)) + ' FROM ' + quoted(table)).fetchall()
            hashes[table] = digest(sorted(digest(r) for r in rows))
    if 'coin_orders' not in existing:
        return {'hashes': hashes}
    wallets = db.execute('SELECT workspace_id,available,held FROM coin_wallet_balances').fetchall()
    attempts = db.execute('SELECT bound,charge FROM coin_attempts').fetchall()
    return {'hashes': hashes, 'walletSha256': digest(sorted(wallets)),
        'wallets': len(wallets), 'availableUnits': sum(r[1] for r in wallets),
        'reservedUnits': sum(r[2] for r in wallets), 'attempts': len(attempts),
        'chargedUnits': sum(r[1] or 0 for r in attempts),
        'pendingAttempts': sum(r[1] is None for r in attempts),
        'pendingBoundUnits': sum(r[0] for r in attempts if r[1] is None)}


def shape(value):
    if isinstance(value, dict):
        return {k: shape(v) for k, v in value.items()}
    if isinstance(value, list):
        return [shape(v) for v in value]
    return '<string>' if isinstance(value, str) else value


def native_shape(db):
    if 'native_batches' not in tables(db):
        return None
    rows = db.execute('SELECT scope_key,revision,request_id,action,created_at,events FROM native_batches ORDER BY scope_key,revision').fetchall()
    return digest([(*r[:-1], shape(json.loads(r[-1]))) for r in rows])


class Redactor:
    # Technical relation identifiers remain stable inside the server-only copy.
    # All credentials, contacts and free text are replaced irreversibly.
    identifiers = {'actor', 'actor_id', 'owner_id', 'workspace', 'workspace_id', 'workshop', 'account',
        'chat', 'chat_id', 'id', 'rid', 'request', 'request_id', 'request_key', 'run_key',
        'operation_id', 'attempt_id', 'scope_key', 'claimed_actor', 'key', 'payment_id',
        'refund_id', 'checkout_id', 'product', 'material', 'event', 'target', 'reverse_of'}
    metadata = {'source', 'issuer', 'model', 'provider', 'rate_version', 'period', 'day',
        'action', 'kind', 'status', 'route', 'effort', 'version', 'unit', 'color', 'type'}
    amounts = {'amount', 'total', 'price', 'sale_price', 'hourly_rate', 'threshold',
        'cny_per_usd', 'usd', 'rub', 'providerAmount', 'packageRub', 'coins', 'cost',
        'revenue', 'net_profit', 'unit_price', 'pack_price', 'quantity'}
    protocol = {'type', 'kind', 'role', 'model', 'provider', 'reasoningEffort', 'action',
        'status', 'effort', 'op', 'unit', 'view', 'page', 'form', 'format', 'operation',
        'toolName', 'target', 'id', 'callId', 'toolCallId', 'rpcId', 'turn', 'step',
        'requestId', 'required', 'enum', 'version', 'blockType', 'source'}
    evidence = {'completed', 'not_dispatched', 'client_disconnected_before_dispatch',
        'openrouter-not-dispatched', 'web-completed', 'media-receipt', 'media-pages-unknown'}

    def __init__(self):
        self.salt = os.urandom(32)
        self.blobs = {}
        self.forbidden = set()
        self.origins = {}
        self.origin = 'journal'

    def opaque(self, value, *, sensitive=False):
        raw = value.encode() if isinstance(value, str) else value
        credential_column = self.origin.rsplit('.',1)[-1] in {
            'login','email','address','password','secret','confirmation_token','verifier','signature','bot'}
        credential_value = isinstance(value,str) and bool(re.match(r'(?:sk-|live_|Bearer |\d{5,}:)', value))
        if len(raw) >= 8 and (sensitive or credential_column or credential_value):
            self.forbidden.add(raw)
            self.origins.setdefault(raw, set()).add(self.origin)
        return 'anon_' + hashlib.sha256(self.salt + raw).hexdigest()[:24]

    def json_value(self, value, key=''):
        if isinstance(value, dict):
            return {k: self.json_value(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [self.json_value(v, key) for v in value]
        if not isinstance(value, str) or not value:
            return value
        if key in self.amounts and re.fullmatch(r'-?\d+(?:\.\d+)?', value):
            return value
        if key in self.protocol and re.fullmatch(r'[A-Za-z0-9_.:/-]{1,120}', value) and not value.startswith(('sk-', 'Bearer')):
            return value
        try:
            nested = json.loads(value)
        except (ValueError, TypeError):
            return self.opaque(value, sensitive=key.lower() in {'email','password','token','api_key','authorization','signature','secret'})
        return json.dumps(self.json_value(nested), ensure_ascii=False, separators=(',', ':'))

    def value(self, table, column, value):
        self.origin = table + '.' + column
        if value is None:
            return None
        if isinstance(value, bytes):
            if value not in self.blobs:
                self.blobs[value] = os.urandom(len(value))
                if len(value) >= 8:
                    self.forbidden.add(value)
                    self.origins.setdefault(value, set()).add(self.origin)
            return self.blobs[value]
        if column == 'recipient' and table == 'telegram_recipients':
            return -1000000000000
        if not isinstance(value, str) or not value:
            return value
        if column in self.identifiers or column in self.metadata:
            return value
        if column in self.amounts and re.fullmatch(r'-?\d+(?:\.\d+)?', value):
            return value
        if column == 'evidence':
            if value in self.evidence:
                return value
            match = re.match(r'^(openrouter-(?:reviewed-|review-)?usd:[0-9.]+)(?::|$)', value)
            if match:
                return match[1] + (':' + self.opaque(value) if value != match[1] else '')
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            if column == 'email' or column == 'address':
                return self.opaque(value) + '@example.invalid'
            return self.opaque(value)
        return json.dumps(self.json_value(parsed), ensure_ascii=False, separators=(',', ':'))


def sanitize(path, redactor):
    db = sqlite3.connect(path)
    db.execute('PRAGMA secure_delete=ON')
    before = snapshot(db)
    money = financial(db)
    journal = native_shape(db)
    for table in ('chat_files', 'marketplace_file_drafts', 'native_spills', 'pm_product_photos'):
        if table in before and before[table]['rows']:
            raise RuntimeError('Attachment redaction requires a reviewed format adapter: ' + table)
    with db:
        for table in tables(db):
            # The FAQ copy contains public product text, not visitor submissions.
            if table == 'public_faq':
                continue
            columns = [r[1] for r in db.execute('PRAGMA table_info(' + quoted(table) + ')')]
            for row in db.execute('SELECT rowid,* FROM ' + quoted(table)).fetchall():
                values = [redactor.value(table, col, val) for col, val in zip(columns, row[1:])]
                if values != list(row[1:]):
                    db.execute('UPDATE ' + quoted(table) + ' SET ' + ','.join(quoted(c) + '=?' for c in columns) + ' WHERE rowid=?', values + [row[0]])
    db.execute('VACUUM')
    after = snapshot(db)
    assert {k:v['rows'] for k,v in before.items()} == {k:v['rows'] for k,v in after.items()}, 'Anonymization lost rows'
    assert financial(db) == money, 'Anonymization changed financial facts'
    assert native_shape(db) == journal, 'Anonymization changed native event structure'
    db.close()
    return {'rows': {k:v['rows'] for k,v in after.items()}, 'financial': money,
            'nativeShape': journal, 'sanitizedSha256': file_hash(path)}


def backup(source, target):
    source, target = source.resolve(), target.resolve()
    assert source != target and not target.is_relative_to(source), 'Copies must be outside source'
    target.mkdir(parents=True, mode=0o700, exist_ok=False)
    files = [source / 'stage.sqlite3', *sorted((source / 'chats').rglob('*.sqlite3'))]
    files += [p for p in (source/'web-admission.sqlite3', source/'stage.sqlite3.public-faq.sqlite3') if p.exists()]
    assert all(p.resolve().is_relative_to(source) for p in files), 'Unexpected source symlink'
    usage = source / 'usage.jsonl'
    source_files = files + ([usage] if usage.exists() else [])
    before = {str(p.relative_to(source)): file_hash(p) for p in source_files}
    redactor, report = Redactor(), {}
    with ExitStack() as stack:
        connections = []
        for path in files:
            db = readonly(path)
            stack.callback(db.close)
            db.execute('BEGIN')
            db.execute('SELECT count(*) FROM sqlite_schema').fetchone()
            connections.append((path, db))
        for path, db in connections:
            destination = target / path.relative_to(source)
            destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            with sqlite3.connect(destination) as copied:
                db.backup(copied)
        usage_raw = usage.read_text() if usage.exists() else ''
    after = {str(p.relative_to(source)): file_hash(p) for p in source_files}
    for path in files:
        relative = str(path.relative_to(source))
        report[relative] = sanitize(target / relative, redactor)
    if usage_raw:
        entries = [redactor.json_value(json.loads(line)) for line in usage_raw.splitlines() if line.strip()]
        (target/'usage.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in entries))
    for path in target.rglob('*'):
        if path.is_file():
            payload = path.read_bytes()
            residues = [{'sha256': hashlib.sha256(secret).hexdigest(), 'length': len(secret),
                         'origins': sorted(redactor.origins.get(secret, ())) }
                        for secret in redactor.forbidden if secret in payload]
            if residues:
                raise RuntimeError('Redaction residue in ' + str(path.relative_to(target)) + ': ' + json.dumps(residues[:5]))
    result = {'sourceHashesBefore': before, 'sourceHashesAfter': after,
        'sourceUnchanged': before == after, 'copies': report,
        'credentialsCopied': False, 'attachmentsPresent': False}
    (target/'backup-report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    assert before == after, 'Source changed concurrently; repeat proof at a stable checkpoint'
    print(json.dumps({'sourceUnchanged': result['sourceUnchanged'],
        'sourceHashesBefore': before, 'sourceHashesAfter': after,
        'copies': {k:{'tables':len(v['rows']), 'rows':sum(v['rows'].values()),
                     'financial':v['financial'], 'nativeShape':v['nativeShape']}
                  for k,v in report.items()}, 'credentialResidue': False}, ensure_ascii=False, indent=2))


def initialize_copy(root):
    from platform_core.guest_registration import RegistrationStore
    from platform_core import podmasterye_domain, account_lifecycle, ai_settings, podmasterye_timer, account_finance
    from platform_core.account_access import AccountAccess
    with RegistrationStore(root/'stage.sqlite3') as identity:
        podmasterye_domain.init(identity)
        with identity._write() as db:
            account_lifecycle.initialize(db)
            ai_settings.initialize(db)
            podmasterye_timer.initialize(db)
        account_finance.initialize(identity)
        AccountAccess(identity, keyfile=root/'absent-auth.key')


async def read_native(root):
    from platform_core.chat_worker import ChatWorker
    from platform_core.storage import Scope
    with readonly(root/'stage.sqlite3') as db:
        scopes = db.execute('SELECT a.actor_id,c.workspace_id,c.chat_id FROM chats c JOIN identity_accounts a USING(workspace_id)').fetchall()
    worker = ChatWorker(root/'stage.sqlite3', root/'chats')
    try:
        counts = []
        for scope in scopes:
            rows = await worker.request(Scope(*scope), 'history', limit=50)
            counts.append(len(rows))
        return {'chats': len(scopes), 'visibleMessages': sum(counts)}
    finally:
        await worker.close()


def verify(baseline, output, node_modules):
    baseline, output = baseline.resolve(), output.resolve()
    assert baseline != output and not output.is_relative_to(baseline), 'Output must be separate'
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    upgraded = output/'upgraded'
    shutil.copytree(baseline, upgraded)
    # No inherited provider, bot, payment, key, proxy or gateway configuration.
    for name in tuple(os.environ):
        if name.startswith(('HARNESS_', 'PODMASTERYE_', 'YOOKASSA_', 'DEEPSEEK_', 'OPENROUTER_', 'TELEGRAM_')):
            os.environ.pop(name)
    os.environ.update(HARNESS_NODE_MODULES=str(node_modules), HARNESS_DIALOG_ENGINE='native')
    files = sorted(baseline.rglob('*.sqlite3'))
    old = {}
    for path in files:
        with readonly(path) as db:
            old[str(path.relative_to(baseline))] = snapshot(db)
    initialize_copy(upgraded)
    initialize_copy(upgraded)
    native = asyncio.run(read_native(upgraded))
    for relative, previous in old.items():
        with readonly(upgraded/relative) as db:
            assert snapshot(db, previous) == previous, 'Migration changed original data: ' + relative
    first = {}
    for path in files:
        relative = str(path.relative_to(baseline))
        with readonly(upgraded/relative) as db:
            first[relative] = snapshot(db)
    restored = output/'restored'
    shutil.copytree(upgraded, restored)
    initialize_copy(restored)
    restored_native = asyncio.run(read_native(restored))
    for relative, previous in first.items():
        with readonly(restored/relative) as db:
            assert snapshot(db, previous) == previous, 'Restore/reopen changed data: ' + relative
    assert native == restored_native, 'Native history changed after restore'
    with readonly(restored/'stage.sqlite3') as db:
        money = financial(db)
        migrations = [r[0] for r in db.execute('SELECT version FROM platform_schema_migrations ORDER BY version')]
    result = {'passed': True, 'originalTablesUnchanged': sum(len(v) for v in old.values()),
        'databaseCopies': len(files), 'restorePassed': True, 'native': native,
        'financial': money, 'migrations': migrations, 'paidOrExternalCalls': 0}
    (output/'migration-report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    os.umask(0o077)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    command = sub.add_parser('backup')
    command.add_argument('--source', type=Path, required=True)
    command.add_argument('--target', type=Path, required=True)
    command = sub.add_parser('verify')
    command.add_argument('--baseline', type=Path, required=True)
    command.add_argument('--output', type=Path, required=True)
    command.add_argument('--node-modules', type=Path, required=True)
    args = vars(parser.parse_args())
    globals()[args.pop('command')](**args)


if __name__ == '__main__':
    main()
