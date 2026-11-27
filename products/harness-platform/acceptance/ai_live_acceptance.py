"""Bounded, explicit live acceptance through a running Workshop candidate.

Default mode writes a source inventory only and performs no network request.
Execution requires its exact digest, a separately started candidate process, an
existing dedicated acceptance account/chat and a local session file. No key is
read, copied, installed, or sent to this script. No database writes are made by
the script; normal /turns requests use the existing gateway and monetary ledger.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from urllib.parse import urlsplit
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[3]
PRODUCT = ROOT / "products/harness-platform"
sys.path.insert(0, str(PRODUCT))
UNIT = 10**12
PHASES = (
    ("chat", "Ответь одной короткой фразой: проверка связи выполнена. Не используй инструменты."),
    ("search", "Найди в интернете официальный сайт IANA. Сделай один поиск, дай одну ссылку и одно короткое предложение. Не читай страницы."),
    ("fetch", "Прочитай https://www.iana.org/domains/reserved и укажи в одном предложении, для чего зарезервирован example.com. Добавь ссылку на прочитанную страницу. Не делай поиск."),
)


def source_inventory():
    entries = {}
    folders = (PRODUCT / "platform_core", PRODUCT / "native", ROOT / "integrations/harness-native-lab/gateway")
    for folder in folders:
        for path in sorted(folder.rglob("*")):
            if not path.is_file() or path.suffix not in (".py", ".mjs", ".js", ".json", ".html", ".css"):
                continue
            if "node_modules" in path.parts or "__pycache__" in path.parts or path.name.endswith(".test.mjs"):
                continue
            entries[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not any(p.endswith("platform_core/podmasterye_scoped.py") for p in entries):
        raise RuntimeError("Candidate source root is incomplete")
    encoded = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return {"sha256": hashlib.sha256(encoded).hexdigest(), "files": entries}


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def session(path):
    if path.stat().st_mode & 0o077:
        raise RuntimeError("Session file must have mode 0600")
    token = path.read_text().strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        raise RuntimeError("Invalid session file format")
    return token


def verify_process(pid, database):
    process = Path("/proc") / str(pid)
    working = (process / "cwd").resolve(strict=True)
    if working != ROOT and ROOT not in working.parents:
        raise RuntimeError("Server process does not run from this candidate")
    command = (process / "cmdline").read_bytes().split(b"\0")
    if not any(command[i:i+2] == [b"-m", b"platform_core.podmasterye_serve"] for i in range(len(command)-1)):
        raise RuntimeError("Use the unchanged Workshop production launcher for live acceptance")
    opened = []
    for path in (process / "fd").iterdir():
        try:
            opened.append(path.resolve(strict=True))
        except (OSError, RuntimeError):
            continue
    if database.resolve() not in opened:
        raise RuntimeError("Candidate process has not opened the supplied database")
    return (process / "stat").read_text().rsplit(")", 1)[1].split()[19]


def account(db, token, chat, budget):
    digest = hashlib.sha256(token.encode("ascii")).digest()
    row = db.execute("""SELECT a.actor_id,a.workspace_id,a.login FROM identity_sessions s
        JOIN identity_accounts a USING(actor_id) JOIN chats c ON c.workspace_id=a.workspace_id
        WHERE s.digest=? AND s.expires_at>unixepoch() AND c.chat_id=?""", (digest, chat)).fetchone()
    if not row or not row[2].startswith("ai_acceptance_"):
        raise RuntimeError("An existing dedicated ai_acceptance_ account and its own chat are required")
    if db.execute("""SELECT 1 FROM usage_grants g JOIN usage_operations o USING(operation_id)
            WHERE o.workspace_id=? AND g.expires_at>unixepoch()""", (row[1],)).fetchone():
        raise RuntimeError("Acceptance account has another active operation")
    from platform_core import model_choices
    if model_choices.selection(db, row[1])[0] != "direct":
        raise RuntimeError("Acceptance account must already select the direct DeepSeek route")
    # A dedicated wallet is a second hard bound independent of caller maxCoins.
    # Do not top up, edit balances, or reuse a previously billed account here.
    granted = db.execute("SELECT COALESCE(SUM(amount),0) FROM coin_grants WHERE workspace_id=?", (row[1],)).fetchone()[0]
    if not 0 < granted <= int(budget * UNIT):
        raise RuntimeError("Dedicated acceptance wallet must contain no more than the approved budget")
    if db.execute("""SELECT 1 FROM coin_attempts a JOIN coin_orders o USING(operation_id)
            WHERE o.workspace_id=? LIMIT 1""", (row[1],)).fetchone():
        raise RuntimeError("Use a fresh acceptance wallet with no previous provider attempts")
    return row


def ledger(db, workspace, chat, request_ids):
    from platform_core import finance_reporting
    operations = [r[0] for r in db.execute("""SELECT operation_id FROM usage_operations
        WHERE workspace_id=? AND chat_id=? AND run_key IN (%s)""" % ",".join("?" for _ in request_ids),
        (workspace, chat, *request_ids))] if request_ids else []
    rows = list(finance_reporting.rows(db, operations=operations))
    summary = finance_reporting.summarize(rows)
    public = [finance_reporting.public_attempt(r) for r in rows]
    web = []
    for operation in operations:
        for kind, status, raw in db.execute(
                "SELECT kind,status,result FROM web_requests WHERE operation_id=?", (operation,)):
            body = json.loads(raw) if raw else {}
            sources = [{k: r[k] for k in ("url", "title") if k in r}
                       for r in body.get("results", []) if isinstance(r, dict)]
            web.append({"operationId": operation, "kind": kind, "status": status, "sources": sources})
    return {"summary": summary, "attempts": public, "web": web}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--expected-source-sha256")
    parser.add_argument("--base-url")
    parser.add_argument("--server-pid", type=int)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--session-file", type=Path)
    parser.add_argument("--admin-session-file", type=Path)
    parser.add_argument("--chat-id")
    parser.add_argument("--budget-rub", default="5")
    args = parser.parse_args()
    inventory = source_inventory()
    save(args.output / "source-manifest.json", inventory)
    if not args.execute:
        print(json.dumps({"mode": "prepared-only", "sourceSha256": inventory["sha256"],
                          "networkRequests": 0, "budgetRubMaximum": "5"}))
        return 0
    if args.expected_source_sha256 != inventory["sha256"]:
        parser.error("Exact approved candidate source digest is required")
    if not all((args.base_url, args.server_pid, args.database, args.session_file, args.chat_id)):
        parser.error("Execution requires candidate process, database, session, chat, and loopback URL")
    url = urlsplit(args.base_url)
    if url.scheme != "http" or url.hostname != "127.0.0.1" or not url.port or url.path not in ("", "/") or url.username or url.password or url.query or url.fragment:
        parser.error("Only an explicit loopback candidate URL is accepted")
    if not re.fullmatch(r"(?:[0-4](?:\.[0-9]{1,12})?|5(?:\.0{1,12})?)", args.budget_rub) or Decimal(args.budget_rub) <= 0:
        parser.error("Budget must be positive and no greater than 5 RUB")
    budget = Decimal(args.budget_rub)
    required_state = ROOT.parent / "live-acceptance/state"
    if args.database.resolve().parent != required_state.resolve() or required_state.is_symlink():
        parser.error("Database must be in this candidate's isolated sibling live-acceptance/state directory")
    start_process = verify_process(args.server_pid, args.database)
    token = session(args.session_file)
    report = {"startedAt": datetime.now(timezone.utc).isoformat(), "sourceSha256": inventory["sha256"],
              "budgetRub": str(budget), "state": "running", "phases": [],
              "providerStatus": {"openrouter": "not-read"},
              "execution": {"transport": "running-candidate-native-gateway", "fixtureTransport": False,
                            "isolatedState": True, "productionDatabaseUsed": False,
                            "providerCredentialsReadByScript": False, "walletCappedAtBudget": False}}
    save(args.output / "results.json", report)
    request_ids = []
    import httpx
    with sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True) as db, \
            httpx.Client(base_url=args.base_url, timeout=100, trust_env=False, follow_redirects=False) as client:
        try:
            actor, workspace, login = account(db, token, args.chat_id, budget)
        except Exception as error:
            report.update(state="failed", failure=type(error).__name__ + ": " + str(error)[:800],
                          finishedAt=datetime.now(timezone.utc).isoformat())
            save(args.output / "results.json", report)
            print(json.dumps({"state": "failed", "failure": report["failure"], "networkRequests": 0}))
            return 1
        report["execution"]["walletCappedAtBudget"] = True
        report["account"] = {"actor": actor, "workspace": workspace, "login": login, "chat": args.chat_id}
        headers = {"Authorization": "Bearer " + token}
        try:
            if args.admin_session_file:
                admin_headers = {"Authorization": "Bearer " + session(args.admin_session_file)}
                status = client.get("/api/admin/provider-keys", headers=admin_headers)
                status.raise_for_status()
                # Preserve only configuration booleans. No model catalogue or
                # live OpenRouter generation is requested by this acceptance.
                report["providerStatus"] = {name: {k: bool(row[k]) for k in ("configured", "enabled") if k in row}
                    for name, row in status.json().items() if name in ("deepseek", "openrouter")}
            spent = Decimal(0)
            run = "ai_live_" + uuid4().hex[:16]
            for phase, question in PHASES:
                if source_inventory()["sha256"] != inventory["sha256"] or verify_process(args.server_pid, args.database) != start_process:
                    raise RuntimeError("Candidate source or process changed during acceptance")
                remaining = budget - spent
                if remaining <= 0:
                    raise RuntimeError("Acceptance budget exhausted")
                rid = run + "_" + phase
                request_ids.append(rid)
                item = {"phase": phase, "requestId": rid, "question": question,
                        "maxCoins": format(remaining, "f")}
                report["phases"].append(item)
                save(args.output / "results.json", report)
                response = client.post(f"/api/chats/{args.chat_id}/turns", headers=headers,
                    json={"requestId": rid, "text": question, "maxCoins": item["maxCoins"]})
                item["status"] = response.status_code
                answer = response.json()
                item["text"] = str(answer.get("text", answer.get("error", "")))[:4000]
                report["ledger"] = ledger(db, workspace, args.chat_id, request_ids)
                save(args.output / "results.json", report)
                response.raise_for_status()
                summary = report["ledger"]["summary"]
                if summary["pending"] or not summary["costComplete"]:
                    raise RuntimeError("Unconfirmed cost/outcome: no retry and no next paid phase")
                spent = max(Decimal(summary["coins"]), Decimal(summary["providerRub"]))
                if spent > budget:
                    raise RuntimeError("Confirmed cost exceeds acceptance budget")
                if not report["ledger"]["attempts"]:
                    raise RuntimeError("No metered native provider attempt was recorded")
                if phase in ("search", "fetch") and not any(
                        row["kind"] == phase and row["status"] == 200 for row in report["ledger"]["web"]):
                    raise RuntimeError("Native agent did not complete the required " + phase)
                before = [r["id"] for r in report["ledger"]["attempts"]]
                replay = client.post(f"/api/chats/{args.chat_id}/turns", headers=headers,
                    json={"requestId": rid, "text": question, "maxCoins": item["maxCoins"]})
                replay.raise_for_status()
                after = ledger(db, workspace, args.chat_id, request_ids)
                if [r["id"] for r in after["attempts"]] != before or replay.json() != answer:
                    raise RuntimeError("Replay changed the result or produced another provider attempt")
                item["replayWithoutNewAttempt"] = True
                save(args.output / "results.json", report)
            report["state"] = "passed"
        except Exception as error:
            report["state"] = "failed"
            report["failure"] = type(error).__name__ + ": " + str(error)[:800]
            # Reads only: an ambiguous operation stays reserved for the normal
            # reconciliation path. This script never clears a charge or retry.
            report["ledger"] = ledger(db, workspace, args.chat_id, request_ids)
        finally:
            report["finishedAt"] = datetime.now(timezone.utc).isoformat()
            save(args.output / "results.json", report)
    print(json.dumps({"state": report["state"], "sourceSha256": inventory["sha256"],
                      "cost": report.get("ledger", {}).get("summary", {}), "output": str(args.output)}))
    return 0 if report["state"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
