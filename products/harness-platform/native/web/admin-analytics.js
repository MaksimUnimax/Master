'use strict';
(()=>{
  const host=document.querySelector('[data-analytics-settings]');if(!host)return;
  const check=host.querySelector('input'),button=host.querySelector('button'),status=host.querySelector('[role=status]');
  let settings;
  async function request(options){const r=await fetch('/api/admin/analytics',{credentials:'same-origin',cache:'no-store',...options});const d=await r.json();if(!r.ok)throw Error(d.error||'Не удалось обновить настройки.');return d;}
  function show(d){settings=d;check.checked=d.enabled;button.disabled=false;status.textContent=d.enabled?'Сбор включён только после согласия посетителя.':'Сбор посещений отключён.';}
  host.addEventListener('submit',async event=>{event.preventDefault();button.disabled=true;try{show(await request({method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:check.checked,revision:settings.revision})}));}catch(e){status.textContent=e.message;button.disabled=false;}});
  request().then(show).catch(e=>{status.textContent=e.message;});
})();
