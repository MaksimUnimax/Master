"""Additive finance/profile extension over the existing identity and coin ledger.

The application-wide migration registry owns versions. No money is moved and
no historical receipt is rewritten by this migration.
"""
from . import service_billing

SCHEMA = (
    *service_billing.SCHEMA,
    """CREATE TABLE IF NOT EXISTS identity_session_metadata (
        digest BLOB PRIMARY KEY REFERENCES identity_sessions(digest) ON DELETE CASCADE,
        id TEXT NOT NULL UNIQUE, created INTEGER, last_seen INTEGER)""",
    """CREATE TABLE IF NOT EXISTS finance_reconciliations (
        id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL UNIQUE REFERENCES coin_attempts(attempt_id),
        actor_id TEXT NOT NULL, previous_version TEXT NOT NULL,
        provider_currency TEXT NOT NULL CHECK(provider_currency IN ('USD','RUB')),
        provider_amount TEXT NOT NULL, reference TEXT NOT NULL,
        charge INTEGER NOT NULL CHECK(charge>=0), created INTEGER NOT NULL,
        UNIQUE(attempt_id,previous_version))""",
    """CREATE INDEX IF NOT EXISTS finance_reconciliation_created
        ON finance_reconciliations(created)""",
    """CREATE INDEX IF NOT EXISTS finance_attempt_started
        ON coin_attempts(started_ms,attempt_id)""",
    """CREATE INDEX IF NOT EXISTS finance_checkout_created
        ON coin_checkouts(workspace_id,created,id)""",
)


def upgrade(db):
    required = {
        'identity_sessions': {'digest', 'actor_id', 'expires_at'},
        'coin_attempts': {'attempt_id', 'operation_id', 'bound', 'charge', 'rate_version'},
        'coin_checkouts': {'id', 'workspace_id', 'status', 'total'},
    }
    for table, columns in required.items():
        actual = {row[1] for row in db.execute(f'PRAGMA table_info({table})')}
        if not columns <= actual:
            raise ValueError('Unsupported finance source schema: ' + table)
    # The real creation time of a legacy session is unknown. Do not fabricate it.
    db.execute("""INSERT INTO identity_session_metadata(digest,id,created,last_seen)
        SELECT digest,lower(hex(randomblob(16))),NULL,NULL FROM identity_sessions
        WHERE digest NOT IN (SELECT digest FROM identity_session_metadata)""")


def ensure(db):
    from .operation_grants import ensure_operation_schema
    from .schema_migrations import apply
    ensure_operation_schema(db)
    apply(db, '20261127_finance_v1', statements=SCHEMA, upgrade=upgrade)
    from .finance_payments import initialize
    initialize(db)
