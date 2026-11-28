"""Browser/API contract helpers over isolated common runtime and loopback HTTP.
These responses are synthetic and never constitute live marketplace evidence.
"""
import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch
from platform_core import market_quantity as quantity

def finish_fixture_job(case,job_id,*,fault=None):
    """Run the real queue/executor against explicitly synthetic loopback HTTP."""
    import httpx
    from platform_core.market_quantity_runtime import Backend
    from platform_core import market_quantity_providers as adapters
    from tests.fixtures.market_quantity_http import Laboratory
    async def run():
        with Laboratory() as lab, patch("platform_core.web_access.check_dns",return_value=None):
            lab.fault=fault;now=[time.time()]
            async with httpx.AsyncClient(transport=lab.transport) as client:
                state=SimpleNamespace(identity=case.app.state.identity,market_links=case.app.state.market_links,http=client)
                backend=Backend(state,clock=lambda:now[0],jitter=0)
                for _ in range(100):
                    with state.identity._lock:job=backend._row(state.identity._db,job_id)
                    if job["state"] in quantity.TERMINAL|{"denied","partial","needs_attention","uncertain","stopped"}:
                        case.assertEqual(lab.errors,[])
                        return job,list(lab.events)
                    now[0]=max(now[0]+.001,job["due"])
                    job=backend.claim(job_id=job_id)
                    case.assertIsNotNone(job)
                    with state.identity._lock:
                        _,encrypted=backend.guard(state.identity._db,job)
                        fields=state.market_links.unpack(job["workspace"],job["owner_cid"],job["provider"],encrypted)
                    context=backend.context(job,fields)
                    request=adapters.request(job["source"],json.loads(job["checkpoint"]),context)
                    lab.prepare(job["source"],request,context,lambda:now[0]);await backend.run(job)
                case.fail("Synthetic browser job did not settle")
    # Playwright's synchronous API owns an event loop in the calling thread.
    # The real async executor must run on its own loop, just as the collector
    # normally does outside a browser. Do not nest/patch the browser loop.
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda:asyncio.run(run())).result(timeout=60)
