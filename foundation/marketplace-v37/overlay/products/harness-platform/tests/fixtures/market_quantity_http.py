"""Loopback HTTP fault laboratory. All provider values are synthetic fixtures.

Only HTTP transport destinations are substituted. Adapter, executor, limiter,
queue, generation checks and both SQLite commits are production code.
"""
import asyncio
from contextlib import AbstractContextManager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
from threading import Thread
from urllib.parse import urlsplit

import httpx
from .market_quantity_cases import response_for


class LoopbackTransport(httpx.AsyncBaseTransport):
    def __init__(self,port):
        self.port=port;self.http=httpx.AsyncHTTPTransport(retries=0)
    async def handle_async_request(self,request):
        data=await request.aread()
        target=request.url.copy_with(scheme="http",host="127.0.0.1",port=self.port)
        clone=httpx.Request(request.method,target,content=data,headers=request.headers,extensions=request.extensions)
        # Timeouts are only shortened for a deliberately delayed fixture socket.
        # Actual requests still traverse TCP and the executor sees httpx's real
        # transport exception; neither its retry nor error handling is mocked.
        if getattr(self,"short_timeout",False):clone.extensions["timeout"]={"connect":.05,"read":.05,"write":.05,"pool":.05}
        return await self.http.handle_async_request(clone)
    async def aclose(self):await self.http.aclose()


class Laboratory(AbstractContextManager):
    def __init__(self):
        self.template=None;self.spec=None;self.context=None;self.clock=lambda:0
        self.fault=None;self.events=[];self.errors=[];self.calls={}
        self.resolve_request=None
        parent=self
        class Handler(BaseHTTPRequestHandler):
            protocol_version="HTTP/1.1"
            def log_message(self,*args):pass
            def date_time_string(self,timestamp=None):
                # Server Date and Retry-After share the laboratory's clock.
                # Production time remains real; accelerated tests must not
                # accidentally introduce a growing clock-skew offset.
                from email.utils import formatdate
                return formatdate(parent.clock() if timestamp is None else timestamp,usegmt=True)
            def do_GET(self):self.reply()
            def do_POST(self):self.reply()
            def reply(self):
                size=int(self.headers.get("Content-Length","0"));body=self.rfile.read(size)
                if parent.resolve_request:
                    tid,spec,ctx=parent.resolve_request(self.command,self.path,body,self.headers)
                else:spec=parent.spec;tid=parent.template;ctx=parent.context
                if not spec:
                    self.send_error(500);return
                event={"at":parent.clock(),"template":tid,"stage":spec["stage"],"method":self.command,
                       "path":urlsplit(self.path).path,"generate":bool(spec.get("generate")),"download":bool(spec.get("download"))}
                key=(tid,spec["stage"]);parent.calls[key]=parent.calls.get(key,0)+1
                event["ordinal"]=parent.calls[key]
                if self.command!=spec["method"] or urlsplit(self.path).path!=urlsplit(spec["url"]).path:
                    parent.errors.append("unexpected request path/method")
                if spec.get("download") and spec.get("auth")=="none":
                    if urlsplit(self.path).query!=urlsplit(spec["url"]).query:parent.errors.append("signed query was modified")
                    if any(self.headers.get(name) for name in ("Authorization","Api-Key","Client-Id")):parent.errors.append("credential sent to object download")
                if spec.get("json") is not None:
                    try:
                        if json.loads(body)!=spec["json"]:parent.errors.append("unexpected request body")
                    except ValueError:parent.errors.append("invalid outgoing JSON")
                fault=parent.fault(event) if parent.fault else None
                if fault=="disconnect":
                    event["status"]="disconnect";parent.events.append(event)
                    self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
                if fault=="timeout":
                    import time
                    event["status"]="timeout";parent.events.append(event)
                    time.sleep(.12)
                    fault={"status_code":503,"headers":{},"payload":{}}
                response=fault or response_for(tid,spec,ctx)
                status=response["status_code"]
                if "status" not in event:event["status"]=status;parent.events.append(event)
                raw=response.get("content")
                if raw is None:raw=json.dumps(response.get("payload"),ensure_ascii=False).encode() if status!=204 else b""
                try:
                    self.send_response(status)
                    for k,v in response.get("headers",{}).items():self.send_header(k,str(v))
                    self.send_header("Content-Length",str(len(raw)));self.end_headers()
                    if raw:self.wfile.write(raw)
                except (BrokenPipeError,ConnectionResetError):pass
        self.server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
        self.thread=Thread(target=self.server.serve_forever,kwargs={"poll_interval":.02},daemon=True)
        self.transport=LoopbackTransport(self.server.server_port)
    def __enter__(self):self.thread.start();return self
    def __exit__(self,*args):self.server.shutdown();self.server.server_close();self.thread.join(2)
    def prepare(self,tid,spec,context,clock):
        self.template=tid;self.spec=spec;self.context=context;self.clock=clock
