"""Run the complete existing UI/agent scenarios with explicit evidence.

No live seller or paid model is used: native tests use their loopback model
protocol fixture, and marketplace browser tests use their loopback HTTP fixture.
Run from products/harness-platform with pinned production dependencies.
"""
import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import time
import unittest


class EvidenceResult(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.cases=[];self.started={}
    def startTest(self,test):
        self.started[test.id()]=time.monotonic();super().startTest(test)
    def record(self,test,status,detail=None):
        self.cases.append({"id":test.id(),"status":status,"seconds":round(time.monotonic()-self.started.get(test.id(),time.monotonic()),3),**({"detail":detail} if detail else {})})
    def addSuccess(self,test):super().addSuccess(test);self.record(test,"pass")
    def addFailure(self,test,err):super().addFailure(test,err);self.record(test,"fail",self._exc_info_to_string(err,test))
    def addError(self,test,err):super().addError(test,err);self.record(test,"error",self._exc_info_to_string(err,test))
    def addSkip(self,test,reason):super().addSkip(test,reason);self.record(test,"skipped",reason)
    def addSubTest(self,test,subtest,err):
        super().addSubTest(test,subtest,err)
        self.record(subtest,"pass" if err is None else "fail",None if err is None else self._exc_info_to_string(err,test))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind",choices=("browser","native"))
    parser.add_argument("--evidence",required=True)
    parser.add_argument("--engine",choices=("chromium","opera"),default="chromium")
    parser.add_argument("--headed",action="store_true",help="Use the actual windowed browser; on Linux supply DISPLAY, e.g. via xvfb-run")
    a=parser.parse_args();root=Path(__file__).resolve().parents[1]
    os.chdir(root);sys.path[:0]=[str(root),str(root/"tests/browser")]
    evidence=Path(a.evidence).resolve();evidence.mkdir(parents=True,exist_ok=True)
    os.environ.update(PODMASTERYE_MARKET_WORKER="0",HARNESS_DIALOG_ENGINE="native")
    if a.kind=="browser":
        if a.headed and sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
            raise RuntimeError("Headed browser acceptance requires DISPLAY; launch with xvfb-run")
        key="PLAYWRIGHT_OPERA_EXECUTABLE_PATH" if a.engine=="opera" else "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"
        binary=os.environ.get(key)
        if not binary or not Path(binary).is_file():raise RuntimeError("An explicit installed browser executable is required")
        if a.engine=="opera" and "opera" not in str(Path(binary).resolve()).lower():raise RuntimeError("Opera acceptance requires the actual Opera executable")
        os.environ.update(PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=binary,PODMASTER_BROWSER_ENGINE=a.engine,PODMASTER_BROWSER_EVIDENCE=str(evidence),PODMASTER_BROWSER_HEADLESS="0" if a.headed else "1")
        modules=["tests.browser."+p.stem for p in sorted((root/"tests/browser").glob("test_*.py"))]+["tests.test_market_dual_browser"]
    else:
        modules=["tests."+name for name in ("test_podmasterye_foundation","test_podmasterye_agent_first","test_podmasterye_matrix_v11","test_podmasterye_owner_v18","test_podmasterye_owner_v19","test_podmasterye_owner_v21","test_podmasterye_seasonal_mcp","test_market_dual_contract","test_market_dual_native","test_podmasterye_market_links","test_podmasterye_admin_v12")]
    suite=unittest.TestSuite();ids=[]
    for module_name in modules:
        module=importlib.import_module(module_name)
        for cls in vars(module).values():
            if isinstance(cls,type) and issubclass(cls,unittest.TestCase) and cls.__module__==module_name:
                # Inherited helpers are shared; execute each declared scenario
                # once instead of counting copies imported by other modules.
                for method in sorted(k for k,v in cls.__dict__.items() if k.startswith("test_") and callable(v)):
                    case=cls(method);ids.append(case.id());suite.addTest(case)
    source_files=sorted(p for folder in ("platform_core","native","tests") for p in (root/folder).rglob("*") if p.is_file() and p.suffix in (".py",".mjs",".js",".json",".css") and "__pycache__" not in p.parts)
    fingerprints={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}
    (evidence/"source-sha256.json").write_text(json.dumps(fingerprints,indent=2)+"\n")
    (evidence/"suite.json").write_text(json.dumps({"kind":a.kind,"engine":a.engine if a.kind=="browser" else "native","headless":not a.headed if a.kind=="browser" else None,"tests":ids,"model":"local protocol fixture only","marketplace":"synthetic HTTP only"},indent=2)+"\n")
    with (evidence/"regression.log").open("w") as log:
        result=unittest.TextTestRunner(stream=log,verbosity=2,resultclass=EvidenceResult).run(suite)
    summary={"tests_run":result.testsRun,"failures":len(result.failures),"errors":len(result.errors),"skipped":len(result.skipped),"passed":result.wasSuccessful() and not result.skipped,"cases":result.cases}
    (evidence/"result.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False)+"\n")
    print(json.dumps({k:v for k,v in summary.items() if k!="cases"}),flush=True)
    for case,message in result.failures+result.errors:print(case.id()+"\n"+message,flush=True)
    return 0 if summary["passed"] else 1


if __name__=="__main__":raise SystemExit(main())
