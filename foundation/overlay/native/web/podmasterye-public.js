/* Public layout: the guest chat stays mounted while the information panel changes. */
'use strict';
(()=>{
 const q=s=>document.querySelector(s),body=document.body,info=q('#public-info-pane'),content=q('#public-info-content');
 if(!info||!content)return;
 const compact=matchMedia('(max-width:960px)'),menu=q('#public-menu'),toggle=q('#public-menu-toggle');
 const chat=q('#public-chat-pane'),allowed=new Set(['about','support','contacts','payment','faq','privacy','login','register']);
 const staticKeys=new Set(['about','support','contacts','privacy']),panelCache=new Map();
 const initialKey=body.dataset.publicKey;
 function head(selector,attr){return document.head.querySelector(selector)?.getAttribute(attr)||'';}
 if(staticKeys.has(initialKey)&&!location.search)panelCache.set(initialKey,{
  key:initialKey,label:q('#public-panel-title').textContent,title:document.title,member:!chat,html:content.innerHTML,
  description:head('meta[name="description"]','content'),robots:head('meta[name="robots"]','content'),canonical:head('link[rel="canonical"]','href')
 });
 let seq=0,controller=null,guestSession=null,sessionPromise=null;
 let paymentCount='100',paymentController=null,paymentTimer=null;
 const routes={about:'/about/',support:'/support',contacts:'/contacts',payment:'/payment',faq:'/faq',privacy:'/privacy',login:'/login',register:'/register'};
 function mode(name){
  body.dataset.publicSurface=name;
  const left=q('#public-open-info'),right=q('#public-open-chat');
  if(left)left.textContent=name==='split'?'Свернуть':'Описание';
  if(right)right.textContent=name==='split'?'Свернуть':'Помощник';
 }
 function nav(open){body.dataset.publicNav=open?'open':'closed';toggle.setAttribute('aria-expanded',String(open));const label=open?'Свернуть меню':'Развернуть меню';toggle.setAttribute('aria-label',label);toggle.title=label;}
 nav(!compact.matches);mode(compact.matches||!chat?'info':'split');
 toggle.onclick=()=>nav(body.dataset.publicNav!=='open');
 compact.addEventListener('change',()=>{nav(!compact.matches);mode(compact.matches||!chat?'info':'split');});
 function showChat(){if(chat){mode(compact.matches?'chat':body.dataset.publicSurface==='info'?'split':'chat');if(compact.matches)nav(false);}else location.assign('/app/');}
 q('#public-open-chat').onclick=showChat;
 q('#public-open-info')?.addEventListener('click',()=>mode(compact.matches||body.dataset.publicSurface==='split'?'info':'split'));
 const consent=q('#cookie-choice');
 try{consent.hidden=!!localStorage.getItem('pm-cookie-choice');}catch{consent.hidden=false;}
 for(const [id,value] of [['cookie-accept','acknowledged'],['cookie-decline','necessary']])q('#'+id).onclick=()=>{try{localStorage.setItem('pm-cookie-choice',value);}catch{}consent.hidden=true;};
 async function api(path,options={}){
  const r=await fetch(path,{credentials:'same-origin',cache:'no-store',...options});
  const d=await r.json().catch(()=>({}));if(!r.ok){const e=Error(typeof d.detail==='string'?d.detail:typeof d.error==='string'?d.error:'Не удалось выполнить запрос.');e.status=r.status;throw e;}return d;
 }
 function session(){
  if(!sessionPromise)sessionPromise=api('/guest/session?state=1',{method:'POST'}).then(g=>{if(!g.chat)throw Error('Гостевая сессия недоступна.');guestSession=g;return g;}).catch(e=>{sessionPromise=null;throw e;});
  return sessionPromise;
 }
 function prepareRegistration(){
  const form=content.querySelector('form[action="/register"]');if(!form)return;
  const submit=form.querySelector('button[type=submit],button'),status=form.querySelector('#registration-status');
  submit.disabled=true;
  session().then(()=>{if(form.isConnected){submit.disabled=false;if(status)status.textContent='';}}).catch(e=>{if(form.isConnected&&status)status.textContent='Не удалось подготовить регистрацию. Обновите страницу. '+e.message;});
 }
 function preparePayment(){
  clearTimeout(paymentTimer);paymentController?.abort();
  const form=content.querySelector('#public-payment-form');if(!form)return;
  const input=form.elements.coins,out=form.querySelector('output'),pay=form.querySelector('button'),status=form.querySelector('#public-payment-status');
  const member=form.dataset.member==='1',initialNote=status.textContent;
  const currency=new Intl.NumberFormat('ru-RU',{style:'currency',currency:'RUB'});
  let confirmed=null;
  const valid=v=>/^[1-9]\d{0,6}$/.test(v)&&Number(v)<=8000000;
  async function refresh(){
   clearTimeout(paymentTimer);paymentController?.abort();
   confirmed=null;pay.disabled=true;out.textContent='—';const count=input.value;
   if(!valid(count)){status.textContent='Введите целое количество от 1 до 8 000 000.';return;}
   paymentCount=count;status.textContent='Рассчитываем сумму…';
   const c=new AbortController();paymentController=c;
   paymentTimer=setTimeout(async()=>{
    try{
     const data=await api('/api/coins/quote?coins='+encodeURIComponent(count),{signal:c.signal});
     if(c.signal.aborted||!form.isConnected||input.value!==count)return;
     if(typeof data.enabled!=='boolean'||!/^\d+\.\d{2}$/.test(data.total))throw Error('Некорректная сумма.');
     out.textContent=currency.format(Number(data.total));
     confirmed=data.enabled?count:null;pay.disabled=!data.enabled;
     status.textContent=data.enabled?(member?'После подтверждения платежа монеты поступят на ваш баланс.':'Войдите в аккаунт перед оплатой, чтобы монеты поступили на ваш баланс.'):'Приём платежей сейчас отключён. Оплата не производится.';
    }catch(e){if(!c.signal.aborted&&form.isConnected)status.textContent='Не удалось рассчитать сумму. Измените количество и повторите попытку.';}
   },120);
  }
  input.addEventListener('input',refresh);
  form.onsubmit=e=>{
   e.preventDefault();
   if(pay.disabled||confirmed!==input.value||!valid(confirmed))return;
   if(member){location.assign('/?account=wallet&resume=1&coins='+encodeURIComponent(confirmed)+'#buy-coins');return;}
   // This is only a selected quantity, not a payment or an idempotency key.
   try{sessionStorage.setItem('podmasterye-public-checkout-count',confirmed);}catch{}
   openPanel('login');
  };
  if(paymentCount==='100'){
   confirmed=form.dataset.enabled==='1'?'100':null;pay.disabled=!confirmed;
  }else{input.value=paymentCount;refresh();}
 }
 function updateNav(key){
  for(const a of menu.querySelectorAll('[data-public-panel]')){
   if(a.dataset.publicPanel===key)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');
  }
 }
 updateNav(body.dataset.publicKey);
 async function openPanel(key,{push=true,url}={}){
  if(!allowed.has(key))return;
  const dest=url||routes[key],n=++seq;
  controller?.abort();controller=new AbortController();const signal=controller.signal;
  clearTimeout(paymentTimer);paymentController?.abort();
  mode(compact.matches||!chat||body.dataset.publicSurface==='info'?'info':'split');if(compact.matches)nav(false);
  info.setAttribute('aria-busy','true');
  try{
   const cacheable=staticKeys.has(key)&&dest===routes[key];
   let data=cacheable?panelCache.get(key):null;
   if(!data){
    const r=await fetch(dest,{cache:'no-store',credentials:'same-origin',signal,headers:{Accept:'application/json','X-PM-Panel':'1'}});
    if(!r.ok)throw Error('Страница недоступна.');
    if(!(r.headers.get('content-type')||'').includes('application/json')){location.assign(dest);return;}
    data=await r.json();
   }
   if(n!==seq||signal.aborted)return;
   if(data.key!==key||data.member!==!chat||typeof data.html!=='string'){location.assign(dest);return;}
   // Parse only the small trusted server fragment, not the complete page.
   const template=document.createElement('template');template.innerHTML=data.html;
   if(template.content.querySelector('script,iframe,object,embed')||[...template.content.querySelectorAll('*')].some(el=>[...el.attributes].some(a=>/^on/i.test(a.name))))throw Error('Недопустимое содержимое страницы.');
   if(cacheable)panelCache.set(key,data);
   content.replaceChildren(template.content);content.dataset.panelKey=key;
   body.dataset.publicKey=key;q('#public-panel-title').textContent=data.label;content.scrollTop=0;updateNav(key);
   document.title=data.title;
   for(const [selector,attr,value] of [
    ['meta[name="description"]','content',data.description],['meta[name="robots"]','content',data.robots],
    ['link[rel="canonical"]','href',data.canonical],['meta[property="og:title"]','content',data.title],
    ['meta[property="og:description"]','content',data.description],['meta[property="og:url"]','content',data.canonical]]){
    const previous=document.head.querySelector(selector);if(previous&&typeof value==='string')previous.setAttribute(attr,value);
   }
   if(push&&location.pathname+location.search!==dest)history.pushState({panel:key},'',dest);
   prepareRegistration();preparePayment();
  }catch(err){if(!signal.aborted&&n===seq)location.assign(dest);}
  finally{if(n===seq)info.removeAttribute('aria-busy');}
 }
 document.addEventListener('click',e=>{
  const a=e.target.closest('a[data-public-panel],a[data-public-chat]');
  if(!a||e.defaultPrevented||e.button!==0||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey||a.target)return;
  const u=new URL(a.href,location.href);if(u.origin!==location.origin)return;
  if(a.hasAttribute('data-public-chat')){if(chat){e.preventDefault();if(body.dataset.publicSurface==='info'){mode(compact.matches?'chat':'split');if(compact.matches)nav(false);}}return;}
  const key=a.dataset.publicPanel;if(!allowed.has(key)||u.pathname!==routes[key])return;
  e.preventDefault();openPanel(key);
 });
 history.replaceState({panel:body.dataset.publicKey},'',location.href);
 addEventListener('popstate',()=>{const key=history.state?.panel||Object.keys(routes).find(k=>routes[k]===location.pathname)||(location.pathname==='/'?'about':null);if(key)openPanel(key,{push:false,url:location.pathname+location.search});else location.reload();});
 prepareRegistration();preparePayment();
 const f=q('#guest-form');if(!f)return;
 const input=f.elements.text,send=f.querySelector('button[type=submit]'),box=q('#guest-messages'),quota=q('#guest-quota'),status=q('#guest-status'),limit=q('#guest-limit'),intro=q('#guest-intro');
 let remaining=0,busy=false,ready=false,pending=null,temporary=null;
 function resize(){input.style.height='0px';input.style.height=Math.max(26,Math.min(input.scrollHeight,124))+'px';}
 function controls(){input.disabled=!ready||busy||remaining===0;send.disabled=!ready||busy||remaining===0;limit.hidden=!ready||remaining!==0;}
 function row(text,role){const el=document.createElement('div');el.className='message '+role;el.textContent=text;box.append(el);return el;}
 function scroll(){box.scrollTop=box.scrollHeight;}
 function render(data){
  remaining=data.quota.remaining;quota.textContent='Бесплатных сообщений осталось: '+remaining+' из '+data.quota.limit+'.';
  const fragment=document.createDocumentFragment();
  for(const t of data.turns)for(const [value,role] of [[t.text,'user'],[t.answer,'assistant']]){
   const el=document.createElement('div');el.className='message '+role;el.textContent=value;fragment.append(el);
  }
  box.replaceChildren(fragment);
  intro.hidden=!!data.turns.length;scroll();controls();
 }
 async function refresh(){const data=await api('/guest/chats/'+encodeURIComponent(guestSession.chat)+'/events');render(data);return data;}
 f.onsubmit=async e=>{
  e.preventDefault();const txt=input.value.trim();if(!ready||busy||!remaining||!txt)return;
  if(!pending||pending.text!==txt)pending={text:txt,request_id:crypto.randomUUID()};
  busy=true;controls();intro.hidden=true;temporary=row(txt,'user');scroll();status.textContent='Подмастерье думает…';
  try{
   const data=await api('/guest/chats/'+encodeURIComponent(guestSession.chat)+'/turns?state=1',{method:'POST',headers:{Accept:'application/json'},body:new URLSearchParams(pending)});
   pending=null;input.value='';resize();status.textContent='Подмастерье отвечает…';
   if(data.quota&&Array.isArray(data.turns))render(data);else await refresh();
   status.textContent='';
  }catch(err){
   temporary?.remove();status.textContent=err.message;
   try{const data=await refresh();if(pending&&data.turns.some(t=>t.requestId===pending.request_id)){pending=null;input.value='';resize();}}catch{}
  }finally{temporary=null;busy=false;controls();if(!input.disabled)input.focus();}
 };
 input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing&&!e.repeat){e.preventDefault();if(!send.disabled)f.requestSubmit(send);}});
 input.addEventListener('input',resize);
 session().then(async data=>{if(data.quota&&Array.isArray(data.turns))render(data);else await refresh();ready=true;controls();resize();}).catch(e=>{status.textContent='Не удалось открыть гостевой чат. Обновите страницу. '+e.message;});
})();
