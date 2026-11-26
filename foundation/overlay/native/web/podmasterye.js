'use strict';
const $=s=>document.querySelector(s);
const member=document.body.dataset.mode==='member',admin=document.body.dataset.admin==='1';
async function api(url,options={}){
  if(window.PMWorkshopId&&/^\/api\/(accounting|production|integrations|materials|calculator\/save)(?:[/?]|$)/.test(url)){const u=new URL(url,location.origin);u.searchParams.set('workshop',window.PMWorkshopId);url=u.pathname+u.search;}
  const r=await fetch(url,{cache:'no-store',credentials:'same-origin',...options});
  const d=await r.json().catch(()=>({}));
  if(!r.ok)throw new Error(r.status===402?'Для запроса к ИИ пополните баланс.':d.error||d.detail||'Не удалось выполнить запрос.');
  return d;
}
const post=(url,data)=>api(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
function row(parent,text,role='assistant',receipt){
  const node=document.createElement('div');node.className='message '+role;node.textContent=text;
  parent.append(node);
  if(admin&&receipt?.modelCost){const line=document.createElement('small');line.className='receipt';const cost=receipt.modelCost;
    const u=receipt.modelUsage?.tokens;
    line.textContent='Расходы ИИ: '+(cost.rub!=null?cost.rub+' ₽':cost.usd!=null?cost.usd+' USD':'не подтверждены')+(u?' · вход '+u.input+' · кэш '+u.cache+' · выход '+u.output:'');parent.append(line);}
  parent.scrollTop=parent.scrollHeight;
}
function navigate(name,reveal=true){for(const el of document.querySelectorAll('[data-panel]'))el.hidden=el.dataset.panel!==name;for(const el of document.querySelectorAll('[data-page]'))el.classList.toggle('active',el.dataset.page===name);const pager=$('#event-pager');if(pager)pager.hidden=!['stock','purchases','manufacture','sales','expenses','journal','workers','assets'].includes(name);const filters=$('#accounting-filters');if(filters)filters.hidden=['admin','wallet','settings','integrations','tasks'].includes(name);window.PMExtras?.navigate(name,reveal);}
function table(host,cols,values){host.replaceChildren();const t=document.createElement('table'),h=t.createTHead().insertRow();for(const c of cols){const th=document.createElement('th');th.textContent=c;h.append(th);}const b=t.createTBody();for(const vals of values){const r=b.insertRow();for(const v of vals)r.insertCell().textContent=v??'Не указано';}host.append(t);}
async function refresh(ui){return window.PMAccounting.refresh(ui);}
async function wallet(){
  const w=await api('/api/wallet');$('#balance-label').textContent='Баланс: '+w.available+' монет';
  $('#wallet-info').textContent='Доступно '+w.available+' · в резерве '+w.reserved+' · цена монеты '+w.salePrice.rubPerCoin+' ₽';
  table($('#wallet-history'),['Списание, монет','Статус'],w.charges.map(c=>[c.coins,c.pending?'В обработке':'Учтено']));
  if(admin&&$('#pricing-form'))$('#pricing-form').elements.markupPercent.value=w.salePrice.markupPercent;
}
function formRecipe(d){const f=$('#recipe-form');for(const key of ['product','material','pack_quantity','usage_quantity','pack_price','unit'])f.elements[key].value=d[key]??(key==='unit'?d.base_unit||'шт':'');navigate('products');$('#recipe-status').textContent='Проверьте данные и сохраните форму.';}
async function initMember(){
  await window.PMExtras.initWorkshops();
  window.PMAccounting.init();
  window.PMExtras.initMember();
  for(const b of document.querySelectorAll('[data-page]'))b.onclick=()=>{navigate(b.dataset.page);window.PMAccounting.navigate();};
  const query=new URLSearchParams(location.search);const initial=query.get('account')==='wallet'?'wallet':query.get('section')==='admin'&&admin?'admin':'summary';navigate(initial,initial!=='summary'||!!sessionStorage.getItem('pm-calc-pending'));
  document.addEventListener('octo-wallet-refresh',()=>wallet().catch(()=>{}));
  await Promise.all([refresh(),wallet()]);
  const chat=(await post('/api/workshops/chat',{workshop:window.PMWorkshopId})).chatId;
  const messages=$('#messages');
  const h=await api('/api/chats/'+encodeURIComponent(chat)+'/messages');for(const m of h)row(messages,m.text,m.role,m);
  const f=$('#assistant-form');let pending=null;
  f.onsubmit=async e=>{e.preventDefault();const input=f.elements.text,txt=input.value.trim();if(!txt)return;const b=f.querySelector('button');b.disabled=true;if(!pending||pending.text!==txt){pending={requestId:crypto.randomUUID(),text:txt};row(messages,txt,'user');}input.value='';$('#assistant-status').textContent='Обрабатываю…';
    try{const m=await post('/api/chats/'+encodeURIComponent(chat)+'/turns',pending);pending=null;if(m.workshop&&m.workshop!==window.PMWorkshopId)throw new Error('Ответ относится к другой мастерской.');row(messages,m.text,m.role,m);if(m.ui?.page)navigate(m.ui.page);await Promise.all([refresh(m.ui),wallet()]);if(m.draft)formRecipe(m.draft);if(m.accountingDraft){const d=m.accountingDraft;window.PMAccounting.open(d.operation,d.arguments,d);}$('#assistant-status').textContent='';}
    catch(err){if(pending)input.value=txt;$('#assistant-status').textContent=err.message;}finally{b.disabled=false;}};
  f.querySelector('button').disabled=false;
  $('#recipe-form').onsubmit=async e=>{e.preventDefault();const f=e.target,o=Object.fromEntries(new FormData(f));o.pack_quantity=Number(o.pack_quantity);o.usage_quantity=Number(o.usage_quantity);o.pack_price=o.pack_price.trim()||null;
    const b=f.querySelector('button');b.disabled=true;try{await post('/api/production/recipe',{requestId:crypto.randomUUID(),recipe:o});await refresh();$('#recipe-status').textContent='Сохранено.';}catch(err){$('#recipe-status').textContent=err.message;}finally{b.disabled=false;}};
  if(admin){
    $('#pricing-form').onsubmit=async e=>{e.preventDefault();try{await post('/api/admin/coin-pricing',Object.fromEntries(new FormData(e.target)));await wallet();}catch(err){alert(err.message);}};
    $('#credit-form').onsubmit=async e=>{e.preventDefault();try{await post('/api/admin/coin-grants',{...Object.fromEntries(new FormData(e.target)),requestId:crypto.randomUUID()});await wallet();}catch(err){alert(err.message);}};
    $('#account-costs').onsubmit=async e=>{e.preventDefault();try{$('#account-costs-result').textContent=JSON.stringify(await api('/api/admin/accounts/'+encodeURIComponent(e.target.elements.login.value)+'/wallet'),null,2);}catch(err){$('#account-costs-result').textContent=err.message;}};
  }
}
async function initGuest(){
  const registration=document.querySelector('form[action="/register"]');
  if(registration){
    const status=$('#registration-status');
    try{await api('/guest/session',{method:'POST'});registration.querySelector('button').disabled=false;status.textContent='';}
    catch(err){status.textContent='Не удалось подготовить регистрацию. Обновите страницу. '+err.message;}
    return;
  }
  const f=$('#guest-form');if(!f)return;
  const g=await api('/guest/session',{method:'POST'});
  f.onsubmit=async e=>{e.preventDefault();const txt=f.elements.text.value.trim(),b=f.querySelector('button');if(!txt)return;b.disabled=true;row($('#guest-messages'),txt,'user');f.elements.text.value='';
    try{await api('/guest/chats/'+encodeURIComponent(g.chat)+'/turns',{method:'POST',headers:{Accept:'application/json'},body:new URLSearchParams({text:txt,request_id:crypto.randomUUID()})});
    const result=await api('/guest/chats/'+encodeURIComponent(g.chat)+'/events');const last=result.turns.at(-1);if(last)row($('#guest-messages'),last.answer??last.text??'Ответ получен.');}catch(err){row($('#guest-messages'),err.message);}finally{b.disabled=false;}};
}
(member?initMember():initGuest()).catch(err=>{const box=$('#assistant-status')||$('#guest-messages');if(box)box.textContent=err.message;});
