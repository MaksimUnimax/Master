'use strict';
const $=s=>document.querySelector(s);
const member=document.body.dataset.mode==='member',admin=document.body.dataset.admin==='1';
async function api(url,options={}){
  if(window.PMWorkshopId&&/^\/api\/(accounting|production|integrations|materials|calculator\/save)(?:[/?]|$)/.test(url)){const u=new URL(url,location.origin);u.searchParams.set('workshop',window.PMWorkshopId);url=u.pathname+u.search;}
  const r=await fetch(url,{cache:'no-store',credentials:'same-origin',...options});
  const d=await r.json().catch(()=>({}));
  if(!r.ok){
    const messages={
      provider_key:admin?'DeepSeek не подключён. Добавьте API-ключ в администрировании → API-ключи.':'DeepSeek не подключён. Обратитесь к администратору сервиса.',
      provider_connection:'Шлюз DeepSeek недоступен. Попробуйте позже.',
      provider_access:'DeepSeek отклонил доступ. Администратору нужно проверить API-ключ.',
      provider_balance:'Недостаточно средств на аккаунте провайдера DeepSeek.',
      turn_unconfirmed:'Результат запроса не подтверждён. Повтор автоматически заблокирован до сверки.',
      model_wait_cancelled:'Ожидание запроса отменено.',
    };
    const e=new Error(r.status===402?'Для запроса к ИИ пополните баланс.':messages[d.error]||d.error||d.detail||'Не удалось выполнить запрос.');
    e.status=r.status;e.code=d.error;throw e;
  }
  return d;
}
const post=(url,data)=>api(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
function row(parent,text,role='assistant',receipt){
  const node=document.createElement('div');node.className='message '+role;node.textContent=text;
  parent.append(node);
  if(receipt?.attachments?.length){
    const box=document.createElement('div');box.className='pm-message-files';
    for(const f of receipt.attachments){
      const a=document.createElement(f.download?'a':'span');a.textContent=f.name+' · '+Math.max(1,Math.ceil(f.bytes/1024))+' КБ';
      if(f.download){const url=new URL(f.download,location.origin);if(url.origin!==location.origin||!/^\/api\/chats\/[A-Za-z0-9_-]+\/files\/[a-f0-9]{32}$/.test(url.pathname))continue;a.href=url.pathname;a.download=f.name;}
      box.append(a);
    }
    node.append(box);
  }
  if(admin&&receipt?.modelCost){const line=document.createElement('small');line.className='receipt';const cost=receipt.modelCost;
    const u=receipt.modelUsage?.tokens;
    line.textContent='Расходы ИИ: '+(cost.rub!=null?cost.rub+' ₽':cost.usd!=null?cost.usd+' USD':'не подтверждены')+(u?' · вход '+u.input+' · кэш '+u.cache+' · выход '+u.output:'');parent.append(line);}
  parent.scrollTop=parent.scrollHeight;
}
function navigate(name,reveal=true){for(const el of document.querySelectorAll('[data-panel]'))el.hidden=el.dataset.panel!==name;for(const el of document.querySelectorAll('[data-page]'))el.classList.toggle('active',el.dataset.page===name);const pager=$('#event-pager');if(pager)pager.hidden=!['stock','purchases','manufacture','sales','expenses','journal','workers','assets'].includes(name);const filters=$('#accounting-filters');if(filters)filters.hidden=['admin','wallet','settings','integrations','tasks'].includes(name);window.PMExtras?.navigate(name,reveal);if(name==='integrations'){refreshTelegram();window.PMMarket?.load();}}
function table(host,cols,values){host.replaceChildren();const t=document.createElement('table'),h=t.createTHead().insertRow();for(const c of cols){const th=document.createElement('th');th.textContent=c;h.append(th);}const b=t.createTBody();for(const vals of values){const r=b.insertRow();for(const v of vals)r.insertCell().textContent=v??'Не указано';}host.append(t);}
async function refresh(ui){return window.PMAccounting.refresh(ui);}
async function wallet(){
  const w=await api('/api/wallet');$('#balance-label').textContent='Баланс: '+w.available+' монет';
  $('#wallet-info').textContent='Доступно '+w.available+' · в резерве '+w.reserved+' · цена монеты '+w.salePrice.rubPerCoin+' ₽';
  table($('#wallet-history'),['Списание, монет','Статус'],w.charges.map(c=>[c.coins,c.pending?'В обработке':'Учтено']));
}
function formRecipe(d){const f=$('#recipe-form');for(const key of ['product','material','pack_quantity','usage_quantity','pack_price','unit'])f.elements[key].value=d[key]??(key==='unit'?d.base_unit||'шт':'');navigate('products');$('#recipe-status').textContent='Проверьте данные и сохраните форму.';}
const agentForms={
 recipe:['#recipe-form',['product','material','unit','pack_quantity','usage_quantity','pack_price']],
 workshop_create:['#workshop-create',['name','description']],
 workshop_settings:['#workshop-settings',['name','description','color','hourly_rate']],
 source_create:['#source-create',['name','auto_produce']]
};
const agentControls={filters:{start:'period-from',end:'period-to',search:'catalog-filter',category:'catalog-category',channel:'sales-channel-filter',task_status:'task-filter',show_archived:'show-archived',product_view:'product-view',material_view:'material-view'},planning:{horizon:'plan-horizon',lead:'plan-lead',safety:'plan-safety'},unit_target:{target_profit:'unit-target'}};
let agentContext=null;
function beginAgent(form,args){
 agentContext={form,arguments:args};
 window.PMExtras.showHelper();
 $('#assistant-status').textContent='Опишите, какие поля нужно заполнить или изменить.';
 $('#assistant-form textarea').focus();
}
window.PMAgent={begin:beginAgent};
function initAgent(){
 for(const [name,[selector,keys]] of Object.entries(agentForms)){
  const f=$(selector);if(!f)continue;
  const b=document.createElement('button');b.type='button';b.className='secondary';b.textContent='Заполнить помощником';
  b.dataset.agentForm=name;
  b.onclick=()=>{const a={};for(const k of keys){const e=f.elements[k];if(e.type==='checkbox')a[k]=e.checked;else if(e.value!=='')a[k]=e.type==='number'?Number(e.value):e.value;}beginAgent(name,a);};f.append(b);
 }
 for(const [name,anchor] of [['filters','period-apply'],['planning','plan-apply'],['unit_target','unit-apply']]){
  const control=$('#'+anchor);if(!control)continue;
  const b=document.createElement('button');b.type='button';b.className='secondary compact';b.dataset.agentForm=name;b.textContent='Помощник';
  b.onclick=()=>{const a={};for(const [k,id] of Object.entries(agentControls[name])){const e=$('#'+id);if(!e||!e.getClientRects().length)continue;if(e.type==='checkbox')a[k]=e.checked;else if(e.value!=='')a[k]=e.type==='number'?Number(e.value):e.value;}beginAgent(name,a);};
  control.after(b);
 }
}
async function applyAgentDraft(d){
 if(d.workshop!==window.PMWorkshopId)throw Error('Черновик другой мастерской.');
 if(agentForms[d.form]){
  const [selector,keys]=agentForms[d.form],f=$(selector);
  for(const [k,v] of Object.entries(d.arguments)){if(!keys.includes(k))continue;const e=f.elements[k];if(e.type==='checkbox')e.checked=v;else e.value=v;}
  f.scrollIntoView({block:'nearest'});
 }else if(agentControls[d.form]){
  for(const [k,v] of Object.entries(d.arguments)){
   const id=agentControls[d.form][k],e=id&&$('#'+id);if(!e)continue;
   if(e.type==='checkbox')e.checked=v;else e.value=v;
   if(['task_status','show_archived','product_view','material_view'].includes(k))e.dispatchEvent(new Event('change'));
  }
  if(d.form==='filters'&&('start' in d.arguments||'end' in d.arguments)){$('#period-preset').value='custom';$('#event-offset').value='0';}
  await refresh();
 }
}
function telegramState(d){
 const s=$('#pm-telegram-status');if(!s)return;
 s.textContent=d.linked?'Telegram подключён.':d.configured?'Нет подтверждённой привязки аккаунта.':'Telegram не настроен.';
 if(d.sent)s.textContent+=' Сообщение отправлено.';
 for(const b of document.querySelectorAll('[data-pm-telegram]'))b.disabled=b.dataset.pmTelegram==='connect'?(!d.configured||d.hasBinding):b.dataset.pmTelegram==='disconnect'?!d.hasBinding:!d.linked;
}
async function refreshTelegram(){try{telegramState(await api('/api/integrations/telegram'));}catch(e){$('#pm-telegram-status').textContent=e.message;}}
async function initMember(){
  await window.PMExtras.initWorkshops();
  window.PMAccounting.init();
  window.PMExtras.initMember();
  initAgent();
  for(const b of document.querySelectorAll('[data-pm-telegram]'))b.onclick=async()=>{
   const action=b.dataset.pmTelegram;if(action==='disconnect'&&!confirm('Отключить Telegram только в Подмастерье?'))return;
   b.disabled=true;try{
     if(action==='connect'){
      const a=await post('/api/integrations/telegram/connect',{});
      const u=new URL(a.url,location.origin);
      if(u.origin!==location.origin&&u.origin!=='https://oauth.telegram.org')throw Error('Недопустимый адрес авторизации.');
      location.href=u.href;return;
     }
     if(action==='disconnect'){await post('/api/integrations/telegram/disconnect',{});await refreshTelegram();}
     else telegramState(await post('/api/integrations/telegram',{action}));
   }catch(e){$('#pm-telegram-status').textContent=e.message;b.disabled=false;}
  };
  for(const b of document.querySelectorAll('[data-page]'))b.onclick=()=>{navigate(b.dataset.page);window.PMExtras.showWork(true);window.PMAccounting.navigate();};
  const query=new URLSearchParams(location.search);const initial=query.get('account')==='wallet'?'wallet':query.get('section')==='integrations'?'integrations':'summary';navigate(initial,initial!=='summary'||!!sessionStorage.getItem('pm-calc-pending'));
  document.addEventListener('octo-wallet-refresh',()=>wallet().catch(()=>{}));
  await Promise.all([refresh(),wallet()]);
  const chat=(await post('/api/workshops/chat',{workshop:window.PMWorkshopId})).chatId;
  const messages=$('#messages');
  const h=await api('/api/chats/'+encodeURIComponent(chat)+'/messages');for(const m of h)row(messages,m.text,m.role,m);
  function viewContext(){
   const page=$('nav button.active')?.dataset.page;
   if(!['summary','materials','products','stock','purchases','manufacture','sales','expenses','finance','journal','planning','workers','assets','unit','tasks','settings','integrations'].includes(page))return undefined;
   const out={page};
   const panel=document.querySelector('[data-panel="'+page+'"]');
   const metric=panel?.querySelector('.metric.highlight')?.dataset.metric;
   if(metric)out.metric=metric;
   for(const [k,id] of [['start','period-from'],['end','period-to'],['search','catalog-filter'],['category','catalog-category'],['channel','sales-channel-filter']]){
    const e=$('#'+id);if(e?.value&&e.getClientRects().length)out[k]=e.value;
   }
   return out;
  }
  const f=$('#assistant-form');let pending=null;
  const {mountComposer}=await import('/assets/podmasterye-composer.js');
  const composer=await mountComposer(f,chat,api);
  f.onsubmit=async e=>{
    e.preventDefault();
    if(!composer.ready())return;
    const input=f.elements.text,txt=input.value.trim(),ids=composer.ids(),files=composer.files();
    if(!txt&&!ids.length)return;
    composer.lock();
    const signature=JSON.stringify([txt,ids]);
    if(!pending||pending.signature!==signature||agentContext){
      pending={signature,body:{requestId:crypto.randomUUID(),text:txt,viewContext:viewContext(),...(ids.length?{attachments:ids}:{}),...(agentContext?{formContext:agentContext}:{})}};
      agentContext=null;
    }
    try{
      $('#assistant-status').textContent=ids.length?'Проверяю вложения…':'Обрабатываю…';
      if(ids.length)await composer.prepare(ids);
      $('#assistant-status').textContent='Обрабатываю…';
      const m=await post('/api/chats/'+encodeURIComponent(chat)+'/turns',pending.body);
      pending=null;
      composer.committed(ids);input.value='';composer.resize();
      row(messages,txt,'user',{attachments:files.map(file=>({...file,download:'/api/chats/'+encodeURIComponent(chat)+'/files/'+file.attachmentId}))});
      if(m.workshop&&m.workshop!==window.PMWorkshopId)throw new Error('Ответ относится к другой мастерской.');
      row(messages,m.text,m.role,m);
      if(m.ui?.page)navigate(m.ui.page);
      await Promise.all([refresh(m.ui),wallet()]);
      if(m.formDraft)await applyAgentDraft(m.formDraft);
      if(m.draft)formRecipe(m.draft);
      if(m.accountingDraft){const d=m.accountingDraft;window.PMAccounting.open(d.operation,d.arguments,d);}
      $('#assistant-status').textContent='';
    }catch(err){
      $('#assistant-status').textContent=err.message;
      // Keep the exact draft and request ID after refusal, cancellation or unknown outcome.
      if(pending){input.value=txt;composer.resize();}
      await wallet().catch(()=>{});
    }finally{composer.unlock();}
  };
  $('#recipe-form').onsubmit=async e=>{e.preventDefault();const f=e.target,o=Object.fromEntries(new FormData(f));o.pack_quantity=Number(o.pack_quantity);o.usage_quantity=Number(o.usage_quantity);o.pack_price=o.pack_price.trim()||null;
    const b=f.querySelector('button');b.disabled=true;try{await post('/api/production/recipe',{requestId:crypto.randomUUID(),recipe:o});await refresh();$('#recipe-status').textContent='Сохранено.';}catch(err){$('#recipe-status').textContent=err.message;}finally{b.disabled=false;}};

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
