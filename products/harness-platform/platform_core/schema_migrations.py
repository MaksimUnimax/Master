"""Versioned, transactional migrations shared by all built-in capabilities.

No executescript: SQLite executescript commits an outer transaction. A migration
and its journal entry therefore use the same SAVEPOINT, including during upgrade
of an existing database. Registered migration bodies are immutable.
"""
import hashlib
import inspect
import json
import re


class MigrationError(RuntimeError):
    pass


def apply(db, version, statements=(), upgrade=None):
    if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", version):
        raise ValueError("Invalid migration version")
    statements = tuple(statements)
    body = inspect.getsource(upgrade) if upgrade is not None else ""
    checksum = hashlib.sha256(json.dumps([statements, body], ensure_ascii=False,
                                        separators=(",", ":")).encode()).hexdigest()
    savepoint = "platform_migration_" + hashlib.sha256(version.encode()).hexdigest()[:16]
    db.execute("SAVEPOINT " + savepoint)
    try:
        db.execute("""CREATE TABLE IF NOT EXISTS platform_schema_migrations (
            version TEXT PRIMARY KEY, checksum TEXT NOT NULL,
            applied_at INTEGER NOT NULL DEFAULT(unixepoch()))""")
        row = db.execute("SELECT checksum FROM platform_schema_migrations WHERE version=?",
                         (version,)).fetchone()
        if row is not None:
            if row[0] != checksum:
                raise MigrationError("Previously applied migration changed: " + version)
        else:
            for statement in statements:
                db.execute(statement)
            if upgrade is not None:
                upgrade(db)
            failures = db.execute("PRAGMA foreign_key_check").fetchmany(1)
            if failures:
                raise MigrationError("Foreign key integrity check failed: " + version)
            db.execute("INSERT INTO platform_schema_migrations(version,checksum) VALUES(?,?)",
                       (version, checksum))
    except BaseException:
        db.execute("ROLLBACK TO " + savepoint)
        db.execute("RELEASE " + savepoint)
        raise
    db.execute("RELEASE " + savepoint)
    return row is None


def applied(db):
    return [dict(version=row[0], checksum=row[1], appliedAt=row[2]) for row in
            db.execute("SELECT version,checksum,applied_at FROM platform_schema_migrations ORDER BY version")]
