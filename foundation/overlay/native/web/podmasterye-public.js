/* Public layout: the guest chat stays mounted while the information panel changes. */
'use strict';
(()=>{
 const q=s=>document.querySelector(s),body=document.body,info=q('#public-info-pane'),content=q('#public-info-content');
 if(!info||!content)return;
 const compact=matchMedia('(max-width:960px)'),menu=q('#public-menu'),toggle=q('#public-menu-toggle');
 const chat=q('#public-chat-pane'),allowed=new Set(['about','support','contacts','payment','faq','privacy','login','register']);
 let seq=0,controller=null,guestSession=null,sessionPromise=null;
 const routes={about:'/about/',support:'/support',contacts:'/contacts',payment:'/payment',faq:'/faq',privacy:'/privacy',login:'/login',register:'/register'};
 function mode(name){
  body.dataset.publicSurface=name;
  const left=q('#public-open-info'),right=q('#public-open-chat');
  if(left)left.textContent=name==='split'?'Свернуть':'Описание';
  if(right)right.textContent=name==='split'?'Свернуть':'Помощник';
 }
 function nav(open){body.dataset.publicNav=open?'open':'closed';toggle.setAttribute('aria-expanded',String(open));}
 nav(!compact.matches);mode(compact.matches||!chat?'info':'split');
 toggle.onclick=()=>nav(body.dataset.publicNav!=='open');
 q('#public-menu-close').onclick=()=>nav(false);
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
  if(!sessionPromise)sessionPromise=api('/guest/session',{method:'POST'}).then(g=>{if(!g.chat)throw Error('Гостевая сессия недоступна.');guestSession=g;return g;}).catch(e=>{sessionPromise=null;throw e;});
  return sessionPromise;
 }
 function prepareRegistration(){
  const form=content.querySelector('form[action="/register"]');if(!form)return;
  const submit=form.querySelector('button[type=submit],button'),status=form.querySelector('#registration-status');
  submit.disabled=true;
  session().then(()=>{if(form.isConnected){submit.disabled=false;if(status)status.textContent='';}}).catch(e=>{if(form.isConnected&&status)status.textContent='Не удалось подготовить регистрацию. Обновите страницу. '+e.message;});
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
  mode(compact.matches||!chat||body.dataset.publicSurface==='info'?'info':'split');if(compact.matches)nav(false);
  info.setAttribute('aria-busy','true');
  try{
   const r=await fetch(dest,{cache:'no-store',credentials:'same-origin',signal,headers:{Accept:'text/html'}});
   if(!r.ok)throw Error('Страница недоступна.');
   const doc=new DOMParser().parseFromString(await r.text(),'text/html');
   if(n!==seq||signal.aborted)return;
   const next=doc.querySelector('#public-info-content'),heading=doc.querySelector('#public-panel-title');
   if(!next||!heading||next.dataset.panelKey!==key){location.assign(dest);return;}
   // Only server-rendered public fragments; scripts and event attributes are not accepted.
   if(next.querySelector('script,iframe,object,embed')||[...next.querySelectorAll('*')].some(el=>[...el.attributes].some(a=>/^on/i.test(a.name))))throw Error('Недопустимое содержимое страницы.');
   content.replaceChildren(...[...next.childNodes].map(node=>document.importNode(node,true)));
   content.dataset.panelKey=key;body.dataset.publicKey=key;q('#public-panel-title').textContent=heading.textContent;info.scrollTop=0;updateNav(key);
   document.title=doc.title;
   for(const selector of ['meta[name="description"]','meta[name="robots"]','link[rel="canonical"]','meta[property="og:title"]','meta[property="og:description"]','meta[property="og:url"]']){
    const previous=document.head.querySelector(selector),fresh=doc.head.querySelector(selector);
    if(previous&&fresh)previous.replaceWith(document.importNode(fresh,true));
   }
   if(push&&location.pathname+location.search!==dest)history.pushState({panel:key},'',dest);
   prepareRegistration();
  }catch(err){if(!signal.aborted&&n===seq)location.assign(dest);}
  finally{if(n===seq)info.removeAttribute('aria-busy');}
 }
 document.addEventListener('click',e=>{
  const a=e.target.closest('a[data-public-panel],a[data-public-chat]');
  if(!a||e.defaultPrevented||e.button!==0||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey||a.target)return;
  const u=new URL(a.href,location.href);if(u.origin!==location.origin)return;
  if(a.hasAttribute('data-public-chat')){if(chat){e.preventDefault();mode(compact.matches?'chat':body.dataset.publicSurface==='info'?'split':body.dataset.publicSurface);if(compact.matches)nav(false);}return;}
  const key=a.dataset.publicPanel;if(!allowed.has(key)||u.pathname!==routes[key])return;
  e.preventDefault();openPanel(key);
 });
 history.replaceState({panel:body.dataset.publicKey},'',location.href);
 addEventListener('popstate',()=>{const key=history.state?.panel||Object.keys(routes).find(k=>routes[k]===location.pathname)||(location.pathname==='/'?'about':null);if(key)openPanel(key,{push:false,url:location.pathname+location.search});else location.reload();});
 prepareRegistration();
 const f=q('#guest-form');if(!f)return;
 const input=f.elements.text,send=f.querySelector('button[type=submit]'),box=q('#guest-messages'),quota=q('#guest-quota'),status=q('#guest-status'),limit=q('#guest-limit'),intro=q('#guest-intro');
 let remaining=0,busy=false,ready=false,pending=null,temporary=null;
 function resize(){input.style.height='0px';input.style.height=Math.max(26,Math.min(input.scrollHeight,124))+'px';}
 function controls(){input.disabled=!ready||busy||remaining===0;send.disabled=!ready||busy||remaining===0;limit.hidden=!ready||remaining!==0;}
 function row(text,role){const el=document.createElement('div');el.className='message '+role;el.textContent=text;box.append(el);return el;}
 function scroll(){box.scrollTop=box.scrollHeight;}
 function render(data){
  remaining=data.quota.remaining;quota.textContent='Бесплатных сообщений осталось: '+remaining+' из '+data.quota.limit+'.';
  box.replaceChildren();for(const t of data.turns){row(t.text,'user');row(t.answer,'assistant');}
  intro.hidden=!!data.turns.length;scroll();controls();
 }
 async function refresh(){const data=await api('/guest/chats/'+encodeURIComponent(guestSession.chat)+'/events');render(data);return data;}
 f.onsubmit=async e=>{
  e.preventDefault();const txt=input.value.trim();if(!ready||busy||!remaining||!txt)return;
  if(!pending||pending.text!==txt)pending={text:txt,request_id:crypto.randomUUID()};
  busy=true;controls();intro.hidden=true;temporary=row(txt,'user');scroll();status.textContent='Подмастерье думает…';
  try{
   await api('/guest/chats/'+encodeURIComponent(guestSession.chat)+'/turns',{method:'POST',headers:{Accept:'application/json'},body:new URLSearchParams(pending)});
   pending=null;input.value='';resize();status.textContent='Подмастерье отвечает…';await refresh();status.textContent='';
  }catch(err){
   temporary?.remove();status.textContent=err.message;
   try{const data=await refresh();if(pending&&data.turns.some(t=>t.requestId===pending.request_id)){pending=null;input.value='';resize();}}catch{}
  }finally{temporary=null;busy=false;controls();if(!input.disabled)input.focus();}
 };
 input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing&&!e.repeat){e.preventDefault();if(!send.disabled)f.requestSubmit(send);}});
 input.addEventListener('input',resize);
 session().then(async()=>{await refresh();ready=true;controls();resize();}).catch(e=>{status.textContent='Не удалось открыть гостевой чат. Обновите страницу. '+e.message;});
})();
