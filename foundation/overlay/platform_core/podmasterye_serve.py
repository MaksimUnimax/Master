"""Start the inherited scoped DeepSeek gateway using Podmasterye state only."""
import argparse,asyncio,os
from pathlib import Path
from urllib.parse import urlsplit
from .serve import run_app, PRODUCT
from .guest_registration import RegistrationStore
from .operation_grants import initialize_grants

async def serve(state,port):
    state=state.resolve()
    state.mkdir(mode=0o700,parents=True,exist_ok=True)
    database,journal=state/"stage.sqlite3",state/"usage.jsonl"
    os.environ.update(HARNESS_PROVIDER_KEYS_DIR=str(state/"provider-keys"),HARNESS_CHAT_MODEL="deepseek-flash",HARNESS_OFFLINE_MODEL="0",HARNESS_USAGE_JOURNAL=str(journal))
    os.environ["HARNESS_TELEGRAM_CONFIG_FILE"]=str(state/"telegram.json")
    for k in ("HARNESS_PROVIDER_RELAY_URL","HARNESS_PROVIDER_RELAY_KEY_FILE","HARNESS_ACCEPTANCE_GATEWAY","HARNESS_ACCEPTANCE_KEY_FILE","HARNESS_OPENROUTER_KEY_FILE"):
        os.environ.pop(k,None)
    with RegistrationStore(database):initialize_grants(database)
    gateway=await asyncio.create_subprocess_exec("node",str(PRODUCT/"native/scoped-gateway.mjs"),str(database),str(journal),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE)
    try:
        url=(await asyncio.wait_for(gateway.stdout.readline(),10)).decode().strip()
        p=urlsplit(url)
        if p.scheme!="http" or p.hostname!="127.0.0.1" or not p.port:raise RuntimeError("Scoped gateway failed")
        os.environ["HARNESS_MODEL_GATEWAY_URL"]=url
        await run_app(database,state,port)
    finally:
        if gateway.returncode is None:
            gateway.stdin.close()
            try:await asyncio.wait_for(gateway.wait(),8)
            except TimeoutError:gateway.kill();await gateway.wait()

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--state",type=Path,required=True);p.add_argument("--port",type=int,default=18971)
    a=p.parse_args();os.umask(0o077);asyncio.run(serve(a.state,a.port))

if __name__=="__main__":main()
