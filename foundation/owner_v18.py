"""Product-specific adaptations of the audited upstream. Never modify Octoport."""
def apply(root):
    def edit(rel,a,b):
        f=root/rel;s=f.read_text()
        if s.count(a)!=1:raise RuntimeError(f"v18 anchor {rel}: {a[:70]} ({s.count(a)})")
        f.write_text(s.replace(a,b,1))
    f=root/"platform_core/telegram_integration.py";s=f.read_text()
    a=s.index("    const path = sessionStorage.getItem('podmasterye.telegram.return');")
    b=s.index("  } catch (e)",a)
    s=s[:a]+"""    let target='/app/?section=integrations';
    try {
      const saved=sessionStorage.getItem('podmasterye.telegram.return');
      sessionStorage.removeItem('podmasterye.telegram.return');
      if(saved){
        const u=new URL(saved,location.origin);
        if(u.origin===location.origin&&u.pathname==='/admin')target='/admin';
        else if(u.origin===location.origin&&u.pathname==='/app/'&&u.searchParams.get('section')==='integrations'){
          const w=u.searchParams.get('workshop');
          if(w&&/^[A-Za-z0-9_-]{1,128}$/.test(w))target+='&workshop='+encodeURIComponent(w);
        }
      }
    } catch {}
    location.replace(target);
"""+s[b:]
    s=s.replace("result.error);","(result.error || result.detail || 'Не удалось подтвердить подключение.'));")
    s=s.replace("Подтверждаем подключение…</p>","Подтверждаем подключение и проверяем доставку…</p>")
    old='uid = await tg.verified_user(state.telegram.http, cfg, fields["code"], verifier, nonce)'
    assert s.count(old)==1
    s=s.replace(old, """if cfg.proxy_port:
                async with httpx.AsyncClient(proxy=f"http://127.0.0.1:{cfg.proxy_port}",timeout=12,trust_env=False,follow_redirects=False) as client:
                    uid = await tg.verified_user(client, cfg, fields["code"], verifier, nonce)
            else:
                uid = await tg.verified_user(state.telegram.http, cfg, fields["code"], verifier, nonce)""")
    old='except tg.DeliveryError:\n            raise HTTPException(409,"Доставка в Telegram не подтверждена. Разрешите сообщения и повторите подключение.") from None'
    assert s.count(old)==1
    s=s.replace(old,"""except tg.DeliveryError as error:
            logging.getLogger(__name__).warning("Telegram connection delivery failed: %s",error.status)
            message = "Разрешите боту отправлять сообщения и подключите Telegram заново." if error.status in ("blocked","rejected") else "Не удалось подтвердить доставку через Telegram. Повторите подключение после проверки связи."
            raise HTTPException(409,message) from None""")
    f.write_text(s)
    edit("platform_core/telegram_api.py",'proxy_port = data.get("connect_proxy_port")',"""proxy_port = data.get("connect_proxy_port")
        if proxy_port is None and os.getenv("PODMASTERYE_TELEGRAM_PROXY_PORT"):
            proxy_port = int(os.environ["PODMASTERYE_TELEGRAM_PROXY_PORT"])""")
    # Public static assets are safe to cache only under a verified content hash.
    edit("platform_core/chat_api.py",'                else:\n                    headers["Cache-Control"] = "no-store"','''                elif scope.get("path", "").startswith("/assets/") and headers.get("Cache-Control") == "private, max-age=31536000, immutable":
                    pass
                else:
                    headers["Cache-Control"] = "no-store"''')
    edit("platform_core/chat_api.py","        async def send_private(message):","""        from time import perf_counter
        started=perf_counter()
        async def send_private(message):""")
    edit("platform_core/chat_api.py",'                headers = MutableHeaders(scope=message)','''                headers = MutableHeaders(scope=message)
                if scope.get("path","").startswith(("/admin","/api/admin/")):
                    headers["Server-Timing"]=f"app;dur={(perf_counter()-started)*1000:.2f}"''')
