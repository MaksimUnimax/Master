"""Comparative, isolated browser smoke; reports measurements without speed gates.

Use the same installed native runtime and Chromium executable for both trees.
Each worker imports its target product in a fresh process, uses IndependentUI's
synthetic account/mail/server fixture and sends no assistant message.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
from urllib.parse import urlsplit


def percentile(values, quantile):
    values = sorted(values)
    position = (len(values) - 1) * quantile
    low = math.floor(position); high = math.ceil(position)
    return values[low] + (values[high] - values[low]) * (position - low)


def summary(samples):
    return {name: {"p50": round(statistics.median([r[name] for r in samples]), 3),
                   "p95": round(percentile([r[name] for r in samples], .95), 3),
                   "min": round(min(r[name] for r in samples), 3),
                   "max": round(max(r[name] for r in samples), 3)}
            for name in ("readyMs", "apiRequests", "assetTransferBytes", "assetEncodedBytes", "assetDecodedBytes")}


def worker(project, output, samples):
    project = project.resolve()
    sys.path.insert(0, str(project))
    sys.path.insert(1, str(project / "tests/browser"))
    import test_podmasterye_independent_ui as fixture
    from playwright.sync_api import expect

    # Explicitly isolate external configuration even if invoked on an operator host.
    os.environ.pop("CREDENTIALS_DIRECTORY", None)
    os.environ.pop("HARNESS_MODEL_GATEWAY_URL", None)
    os.environ.update(HARNESS_OPENROUTER_ENABLED="0", HARNESS_WEB_ENABLED="0",
                      HARNESS_OPENROUTER_KEY_FILE="", HARNESS_TELEGRAM_CONFIG_FILE=str(output.parent / "no-telegram-config"),
                      HARNESS_PROVIDER_KEYS_DIR=str(output.parent / "empty-provider-keys"),
                      PODMASTER_BROWSER_EVIDENCE=str(output.parent))
    os.chdir(project)
    cls = fixture.IndependentUI
    cls.setUpClass()
    case = cls("test_01_public_navigation_cookie_choices")
    setup = False
    try:
        case.setUp(); setup = True
        case.sign_in(); case.seed()
        page = case.page
        requests = []; failures = []
        page.on("request", lambda request: requests.append(request))
        page.on("response", lambda response: failures.append({"path": urlsplit(response.url).path, "status": response.status}) if response.status >= 400 else None)
        marker = "Черновик проверки производительности — не отправлять"

        def capture(label, started, first_request, resource_from=0):
            # A painted frame follows readiness; no networkidle/artificial sleep gate.
            page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => resolve()))")
            elapsed = (time.perf_counter() - started) * 1000
            resources = page.evaluate("""() => performance.getEntriesByType('resource').map(r => ({
                path:new URL(r.name).pathname, startTime:r.startTime,
                transferSize:r.transferSize, encodedBodySize:r.encodedBodySize,
                decodedBodySize:r.decodedBodySize, duration:r.duration
            }))""")
            resources = [r for r in resources if r["startTime"] >= resource_from]
            assets = [r for r in resources if r["path"].startswith(("/assets/", "/ui-assets/"))]
            api = [urlsplit(r.url).path for r in requests[first_request:] if urlsplit(r.url).path.startswith("/api/")]
            return {"label": label, "readyMs": round(elapsed, 3), "apiRequests": len(api),
                    "apiPaths": dict(Counter(api)), "assetRequests": len(assets),
                    "assetTransferBytes": sum(r["transferSize"] for r in assets),
                    "assetEncodedBytes": sum(r["encodedBodySize"] for r in assets),
                    "assetDecodedBytes": sum(r["decodedBodySize"] for r in assets), "assets": assets,
                    "draftRetained": page.locator("#assistant-form textarea").input_value() == marker}

        session = case.ctx.new_cdp_session(page)
        session.send("Network.clearBrowserCache")
        first = len(requests); started = time.perf_counter()
        page.reload(wait_until="domcontentloaded"); case.ready()
        cold = capture("coldReload", started, first)
        reloads = []
        for index in range(samples):
            page.locator("#assistant-form textarea").fill(marker)
            first = len(requests); started = time.perf_counter()
            page.reload(wait_until="domcontentloaded"); case.ready()
            reloads.append(capture("reload-" + str(index + 1), started, first))
        page.locator("#assistant-form textarea").fill(marker)
        navigations = []
        for index in range(samples):
            section = ("materials", "products", "summary")[index % 3]
            resource_from = page.evaluate("performance.now()")
            first = len(requests); started = time.perf_counter()
            with page.expect_response(lambda r: "/api/accounting?" in r.url and r.request.method == "GET") as received:
                page.locator('nav button[data-page="' + section + '"]').click()
            response = received.value
            if response.status != 200:
                raise RuntimeError("Navigation accounting response: " + str(response.status))
            # Reading the body waits for completion without Playwright's spare
            # Response.finished() close-watcher task surviving until teardown.
            response.body()
            expect(page.locator('[data-panel="' + section + '"]')).to_be_visible()
            navigations.append(capture(section + "-" + str(index + 1), started, first, resource_from))
        source_hashes = {name: hashlib.sha256((project / name).read_bytes()).hexdigest()
                         for name in ("platform_core/chat_api.py", "native/web/podmasterye.js", "native/web/podmasterye.css")}
        with case.app.state.identity._lock:
            db = case.app.state.identity._db
            counts = {table: db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                      for table in ("identity_accounts", "pm_materials", "pm_products", "pm_recipe", "pm_book_events", "coin_attempts")}
        value = {"project": str(project), "browser": cls.browser.version, "viewport": page.viewport_size,
                 "samplesPerPhase": samples, "fixture": "IndependentUI: one synthetic account, two materials, three products, two recipes; no provider",
                 "sourceHashes": source_hashes, "databaseCounts": counts, "coldReload": cold,
                 "reloads": reloads, "navigations": navigations,
                 "summary": {"reloads": summary(reloads), "navigations": summary(navigations)},
                 "draft": {"navigationPreserved": all(r["draftRetained"] for r in navigations),
                           "reloadPreserved": all(r["draftRetained"] for r in reloads)},
                 "httpFailures": failures, "pageErrors": case.errors,
                 "notes": ["readyMs ends after application readiness and one animation frame.",
                           "p95 uses linear interpolation; this small local sample is a smoke comparison, not an SLA.",
                           "transferSize includes response overhead; encoded/decoded body sizes include cached resource metadata.",
                           "Cold reload is separate from the warm reload distribution; navigation counts only newly requested resources."]}
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        case.tearDown()
    finally:
        if setup:
            case.doCleanups()
        cls.doClassCleanups()


def compare(baseline, candidate, output, samples):
    output.mkdir(parents=True, exist_ok=True)
    results = {}
    for name, project in (("baseline", baseline), ("candidate", candidate)):
        target = output / name / "measurements.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([sys.executable, str(Path(__file__).resolve()), "--project", str(project.resolve()),
                        "--output", str(target), "--samples", str(samples)], check=True)
        results[name] = json.loads(target.read_text())
    deltas = {}
    for phase in ("reloads", "navigations"):
        deltas[phase] = {}
        for metric in results["baseline"]["summary"][phase]:
            deltas[phase][metric] = {}
            for quantile in ("p50", "p95"):
                before = results["baseline"]["summary"][phase][metric][quantile]
                after = results["candidate"]["summary"][phase][metric][quantile]
                deltas[phase][metric][quantile] = {"baseline": before, "candidate": after,
                    "absolute": round(after - before, 3), "percent": round((after / before - 1) * 100, 2) if before else None}
    comparison = {"baseline": results["baseline"], "candidate": results["candidate"], "deltas": deltas}
    (output / "comparison.json").write_text(json.dumps(comparison, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"deltas": deltas, "draft": {k: v["draft"] for k, v in results.items()},
                      "httpFailures": {k: v["httpFailures"] for k, v in results.items()}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=9)
    args = parser.parse_args()
    if not 5 <= args.samples <= 10:
        parser.error("Use 5–10 samples per phase")
    if args.project:
        worker(args.project, args.output, args.samples)
    elif args.baseline and args.candidate:
        compare(args.baseline, args.candidate, args.output, args.samples)
    else:
        parser.error("Specify --project or both --baseline and --candidate")
