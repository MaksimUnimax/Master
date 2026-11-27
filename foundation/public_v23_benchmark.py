"""Isolated browser benchmark of the public composition; no live accounts/API traffic."""
import os,sys,time,statistics,json,tempfile,threading,socket
from pathlib import Path
import uvicorn
from playwright.sync_api import sync_playwright,expect
from platform_core.chat_api import create_app
from urllib.parse import urlsplit
from unittest.mock import patch
root=Path(sys.argv[1])
revision=sys.argv[2]
rows=[]
with tempfile.TemporaryDirectory(prefix="pm-perf-") as tmp, patch.dict(os.environ,{"HARNESS_PROVIDER_KEYS_DIR":tmp+"/no-keys","HARNESS_OFFLINE_MODEL":"1","YOOKASSA_PAYMENTS_ENABLED":"0"}):
    app=create_app(Path(tmp)/"data.sqlite3",Path(tmp)/"chats")
    sock=socket.socket();sock.bind(("127.0.0.1",0));sock.listen(32)
    origin="http://127.0.0.1:"+str(sock.getsockname()[1])
    server=uvicorn.Server(uvicorn.Config(app,log_level="warning",access_log=False))
    thread=threading.Thread(target=server.run,kwargs={"sockets":[sock]},daemon=True);thread.start()
    deadline=time.monotonic()+20
    while not server.started:
        if time.monotonic()>deadline:raise RuntimeError("startup")
        time.sleep(.05)
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,args=["--no-sandbox"])
            for i in range(3):
                ctx=browser.new_context(viewport={"width":1440,"height":900})
                page=ctx.new_page()
                cdp=ctx.new_cdp_session(page)
                cdp.send("Network.enable")
                cdp.send("Network.emulateNetworkConditions",{"offline":False,"latency":150,"downloadThroughput":1_000_000,"uploadThroughput":500_000})
                requests=[];responses=[]
                page.on("request",lambda r:requests.append(urlsplit(r.url).path))
                page.on("response",lambda r:responses.append({"path":urlsplit(r.url).path,"status":r.status}))
                t=time.monotonic()
                page.goto(origin+"/",wait_until="domcontentloaded",timeout=30000)
                expect(page.locator("#guest-form button[type=submit]")).to_be_enabled(timeout=20000)
                ready=round((time.monotonic()-t)*1000,1)
                first_requests=list(requests)
                if page.locator("#cookie-decline").is_visible():page.locator("#cookie-decline").click()
                nav=page.locator("#public-menu")
                times=[]
                n0=len(requests)
                for k,title in [("contacts","Контакты и реквизиты"),("about","Подмастерье — программа учёта производства и себестоимости"),("contacts","Контакты и реквизиты"),("about","Подмастерье — программа учёта производства и себестоимости")]:
                    start=time.monotonic();nav.locator('a[data-public-panel="'+k+'"]').click()
                    expect(page.locator("#public-info-content h1")).to_have_text(title,timeout=15000)
                    times.append(round((time.monotonic()-start)*1000,1))
                panel_requests=requests[n0:]
                scroller=page.locator("#public-info-pane") if page.locator("#public-info-pane").evaluate("e=>e.scrollHeight>e.clientHeight+5") else page.locator("#public-info-content")
                # Same 120-frame scripted scrolling stress, including style and layout work.
                cdp.send("Performance.enable")
                def metrics():return {m["name"]:m["value"] for m in cdp.send("Performance.getMetrics")["metrics"]}
                a=metrics()
                frames=scroller.evaluate("""e=>new Promise(resolve=>{let last=0,n=0,dt=[],max=e.scrollHeight-e.clientHeight;function tick(t){if(last)dt.push(t-last);last=t;e.scrollTop=max*(0.5+0.5*Math.sin(n*.075));if(++n<121)requestAnimationFrame(tick);else resolve({dt,max,top:e.scrollTop});}requestAnimationFrame(tick);})""")
                b=metrics()
                dt=frames["dt"]
                row={"round":i+1,"ready_ms":ready,"initial_requests":first_requests,"panel_ms":times,"panel_requests":panel_requests,"scroll":{"range":frames["max"],"frames":len(dt),"p95_ms":round(sorted(dt)[int(len(dt)*.95)-1],2),"over_33ms":sum(x>33.34 for x in dt),"layout_ms":round(1000*(b.get("LayoutDuration",0)-a.get("LayoutDuration",0)),2),"style_ms":round(1000*(b.get("RecalcStyleDuration",0)-a.get("RecalcStyleDuration",0)),2)}}
                rows.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
                ctx.close()
            browser.close()
    finally:
        server.should_exit=True;thread.join(timeout=10);sock.close()
(root/(revision+".json")).write_text(json.dumps(rows,ensure_ascii=False,indent=2))
print("DONE",revision,flush=True)
