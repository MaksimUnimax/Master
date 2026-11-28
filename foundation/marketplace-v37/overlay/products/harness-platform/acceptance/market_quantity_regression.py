#!/usr/bin/env python3
"""Full candidate regression with per-case evidence and an immutable code guard.

Run against a candidate checkout with the pinned production Python/Node runtime.
Tests use their isolated state directories and synthetic protocol fixtures.
This runner never uses the production database or seller credentials.
"""
import argparse
from contextlib import redirect_stderr,redirect_stdout
from datetime import datetime,timezone
import hashlib
import importlib.metadata
import inspect
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from acceptance.market_dual_regression import EvidenceResult


def fingerprints():
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
            for directory in ("platform_core","native","tests","acceptance")
            for p in sorted((ROOT/directory).rglob("*"))
            if p.is_file() and p.suffix in (".py",".mjs",".js",".json",".css")
            and "__pycache__" not in p.parts}


def flatten(suite):
    for item in suite:
        if isinstance(item,unittest.TestSuite):yield from flatten(item)
        else:yield item


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence",required=True)
    parser.add_argument("--candidate-sha",required=True)
    args=parser.parse_args();os.chdir(ROOT)
    if len(args.candidate_sha)!=40 or any(c not in "0123456789abcdef" for c in args.candidate_sha):
        parser.error("--candidate-sha must be a full Git SHA")
    output=Path(args.evidence).resolve();output.mkdir(parents=True,exist_ok=True)
    # All application fixtures must opt out of an unrelated background worker.
    # The executor/Collector scenarios explicitly start their own real worker.
    os.environ.update(PODMASTERYE_MARKET_WORKER="0",HARNESS_DIALOG_ENGINE="native")
    started=datetime.now(timezone.utc).isoformat();before=fingerprints()
    (output/"source-sha256.json").write_text(json.dumps(before,indent=2)+"\n")
    suite=unittest.TestLoader().discover(str(ROOT/"tests"),pattern="test_*.py")
    cases=list(flatten(suite));scenario_origins=set()
    for case in cases:
        method=getattr(type(case),getattr(case,"_testMethodName",""),None)
        try:scenario_origins.add((str(Path(inspect.getsourcefile(method)).relative_to(ROOT)),method.__code__.co_firstlineno))
        except (TypeError,ValueError,AttributeError):scenario_origins.add((case.id(),0))
    (output/"suite.json").write_text(json.dumps({"tests":[case.id() for case in cases],
        "discovered_executions":len(cases),"distinct_declared_scenarios":len(scenario_origins),
        "model":"synthetic native protocol fixture only","marketplace":"synthetic loopback HTTP only",
        "candidate_sha":args.candidate_sha},indent=2)+"\n")
    wall=time.monotonic()
    with (output/"regression.log").open("w") as log,redirect_stdout(log),redirect_stderr(log):
        result=unittest.TextTestRunner(stream=log,verbosity=2,resultclass=EvidenceResult).run(suite)
    syntax=[];node=shutil.which("node")
    for directory in ("native","tests"):
        for path in sorted((ROOT/directory).rglob("*")):
            if not path.is_file() or path.suffix not in (".mjs",".js"):continue
            if node:
                process=subprocess.run([node,"--check",str(path)],capture_output=True,text=True,timeout=30)
                syntax.append({"path":str(path.relative_to(ROOT)),"returncode":process.returncode,
                               "stderr":process.stderr[-8000:]})
            else:syntax.append({"path":str(path.relative_to(ROOT)),"returncode":None,"stderr":"node executable unavailable"})
    after=fingerprints();changed=sorted(k for k in before.keys()|after.keys() if before.get(k)!=after.get(k))
    versions={}
    for package in ("httpx","starlette","mcp","cryptography","openpyxl","playwright"):
        try:versions[package]=importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:versions[package]=None
    summary={"candidate_sha":args.candidate_sha,"started_at":started,
        "finished_at":datetime.now(timezone.utc).isoformat(),"wall_seconds":round(time.monotonic()-wall,3),
        "tests_run":result.testsRun,"distinct_declared_scenarios":len(scenario_origins),
        "failures":len(result.failures),"errors":len(result.errors),"skipped":len(result.skipped),
        "unexpected_successes":len(result.unexpectedSuccesses),"expected_failures":len(result.expectedFailures),
        "source_changed":changed,"js_files":len(syntax),"js_failures":sum(v["returncode"]!=0 for v in syntax),
        "runtime":{"python":sys.version,"python_executable":sys.executable,"platform":platform.platform(),"packages":versions},
        "cases":result.cases,"js_syntax":syntax}
    summary["passed"]=result.wasSuccessful() and not result.skipped and not result.expectedFailures and not changed and summary["js_failures"]==0
    (output/"result.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({k:v for k,v in summary.items() if k not in ("cases","js_syntax","runtime")}),flush=True)
    return 0 if summary["passed"] else 1


if __name__=="__main__":raise SystemExit(main())
