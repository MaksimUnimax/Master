/* One consent and pageview controller for public panels. No private-page tracking. */
'use strict';
(()=>{
  if(window.MasterAnalytics || /^\/(?:admin|api|app)(?:\/|$)/.test(location.pathname))return;
  const paths=new Set(['/','/about','/about/','/kalkulyator','/kalkulyator-pribyli/','/support','/contacts','/payment','/faq','/privacy']);
  let config={enabled:false},ready=false,initializing=null,loaded=false,active=false,last=null,tag=null;
  const read=()=>{try{return localStorage.getItem('pm-cookie-choice');}catch{return null;}};
  const consent=()=>read()==='analytics';
  const banner=()=>document.querySelector('#cookie-choice');
  const safePath=()=>paths.has(location.pathname)?location.pathname:null;
  function render(force=false){
    const box=banner();if(!box)return;
    const saved=read();box.hidden=!force&&['analytics','necessary'].includes(saved);
    box.querySelector('p').textContent=config.enabled?
      'Необходимые cookie поддерживают вход. С вашего согласия Яндекс Метрика считает посещения публичных страниц. Содержимое чата и учёта не передаётся.':
      'Мы используем необходимые cookie для входа и сохранения настроек. Сбор аналитики сейчас отключён.';
    const allow=document.querySelector('#cookie-accept');if(allow)allow.textContent=config.enabled?'Разрешить аналитику':'Понятно';
  }
  function stop(){
    const wasActive=active;last=null;active=false;
    if(wasActive&&loaded&&typeof window.ym==='function')window.ym(config.counter,'destruct');
    else if(window.ym?.a)window.ym.a=[];
  }
  function hit(){
    const path=safePath();
    if(!config.enabled||!consent()||!path){if(active)stop();return;}
    if(!loaded)return;
    if(!active){
      window.ym(config.counter,'init',{defer:true,webvisor:false,clickmap:false,trackLinks:false,
        accurateTrackBounce:false,url:config.origin+path,referrer:config.origin+'/'});
      active=true;
    }
    if(last===path)return;
    const previous=last;last=path;
    window.ym(config.counter,'hit',config.origin+path,{title:'Мастерская',referer:config.origin+(previous||'/')});
  }
  async function start(){
    if(!ready||!config.enabled||!consent()||!safePath()){if(active)stop();return;}
    if(loaded){hit();return;}
    if(initializing)return initializing;
    window.ym ||= function(){(window.ym.a ||= []).push(arguments);};window.ym.l ||= Date.now();
    initializing=new Promise(resolve=>{
      tag=document.createElement('script');tag.async=true;tag.referrerPolicy='origin';
      tag.src='https://mc.yandex.ru/metrika/tag.js?id='+encodeURIComponent(config.counter);
      tag.onload=()=>{loaded=true;initializing=null;hit();resolve();};
      tag.onerror=()=>{initializing=null;tag.remove();tag=null;resolve();};
      document.head.append(tag);
    });
    return initializing;
  }
  function choose(value){
    try{localStorage.setItem('pm-cookie-choice',value);}catch{}
    if(value==='analytics')start();else stop();
    const box=banner();if(box)box.hidden=true;
  }
  document.querySelector('#cookie-accept')?.addEventListener('click',()=>choose(config.enabled?'analytics':'necessary'));
  document.querySelector('#cookie-decline')?.addEventListener('click',()=>choose('necessary'));
  document.addEventListener('click',event=>{if(event.target.closest('[data-privacy-options]')){event.preventDefault();render(true);}});
  document.addEventListener('master:pageview',()=>{if(consent())start();else stop();});
  addEventListener('storage',event=>{if(event.key==='pm-cookie-choice'){render();if(consent())start();else stop();}});
  window.MasterAnalytics={view:()=>start(),preferences:()=>render(true)};
  fetch('/api/analytics/config',{credentials:'same-origin',cache:'no-store'})
    .then(r=>r.ok?r.json():{enabled:false}).then(value=>{
      if(value.enabled===true&&/^[1-9]\d{0,17}$/.test(value.counter)&&value.origin===location.origin)config=value;
    }).catch(()=>{}).finally(()=>{ready=true;render();start();});
})();
