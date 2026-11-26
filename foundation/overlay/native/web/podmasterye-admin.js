'use strict';
const $=s=>document.querySelector(s);
async function api(url,options={}){
 const r=await fetch(url,{credentials:'same-origin',cache:'no-store',...options});
 const d=await r.json().catch(()=>({}));
 if(!r.ok)throw Error(d.error||d.detail||'Ошибка запроса (HTTP '+r.status+')');
 return d;
}
const post=(url,data)=>api(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
function table(host,cols,values){host.replaceChildren();const t=document.createElement('table'),h=t.createTHead().insertRow();for(const c of cols){const th=document.createElement('th');th.textContent=c;h.append(th);}const b=t.createTBody();for(const vals of values){const r=b.insertRow();for(const v of vals)r.insertCell().textContent=v??'—';}host.append(t);}
function error(e){$('#admin-problem').textContent=e.message;}
function action(el,fn){if(!el)return;el.addEventListener(el.tagName==='FORM'?'submit':'click',async e=>{e.preventDefault();const b=el.tagName==='FORM'?el.querySelector('button[type=submit],button:not([type])'):el;if(b?.disabled)return;if(b)b.disabled=true;$('#admin-problem').textContent='';try{await fn(el);}catch(e){error(e);}finally{if(b)b.disabled=false;}});}
function txt(id,value){const e=document.getElementById(id);if(e)e.textContent=value;}
const fmt=new Intl.NumberFormat('ru-RU',{maximumFractionDigits:9});
async function keyState(){const d=await api('/api/admin/provider-keys');txt('ai-provider-status',d.deepseek.configured?'Ключ DeepSeek настроен.':'Ключ DeepSeek не добавлен.');}
if($('#deepseek-key-form')){
 keyState().catch(error);
 action($('#deepseek-key-form'),async f=>{await post('/api/admin/provider-keys/deepseek',{key:f.elements.key.value});f.reset();txt('deepseek-key-status','Ключ сохранён.');await keyState();});
}
async function refreshUsage(){
 const d=await api('/api/admin/podmasterye/usage');
 txt('ai-provider-status',(d.configured&&d.gateway?'DeepSeek подключён.':'DeepSeek не подключён.')+' · Отдельная статистика сервиса.');
 const cols=['Период / аккаунт','Вызовы','Вход','Кэш','Выход','Расход, ₽','Расход, USD','Монеты','Не подтверждено'];
 const values=(label,b)=>[label,b.attempts,b.input,b.cache,b.output,b.rub+(b.rubIncomplete?' (неполная)':''),b.usd,b.coins,b.pending];
 table($('#ai-usage-periods'),cols,Object.entries(d.periods).map(([k,b])=>values(({all:'За всё время',today:'Сегодня',month:'Этот месяц'})[k],b)));
 table($('#ai-usage-accounts'),cols,d.accounts.map(b=>values(b.login,b)));
 table($('#ai-usage-media'),['Режим','Попыток','Подтверждённые единицы','Расход, ₽','На сверке'],(d.media||[]).map(b=>[b.mode,b.attempts,b.quantity+(b.unit==='seconds'?' с':' стр.'),b.rub,b.pending]));
}
function renderCharge(c){
 const li=document.createElement('li');li.textContent=(c.pending?'На сверке':'Списано')+' · '+c.coins+' монет · '+(c.chatId?'Чат '+c.chatId.slice(-8):c.operationId||c.requestId||'');
 if(c.meter){const detail=document.createElement('details'),summary=document.createElement('summary');summary.textContent='Расход модели · '+(c.meter.rubPerUsd?c.meter.rubPerUsd+' ₽/USD':'прежний тариф');detail.append(summary);
 if(c.meter.providerUsd!=null){const p=document.createElement('p');p.textContent='Себестоимость · $'+c.meter.providerUsd;detail.append(p);}
 for(const a of c.meter.attempts||[]){const p=document.createElement('p'),u=a.usage;p.textContent='DeepSeek · '+a.model+' · '+(u?(u.unit?(u.quantity??'Не подтверждено')+(u.unit==='seconds'?' с':' стр.'):'Вход '+(u.input_tokens??0)+' · Кэш '+(u.cache_read_input_tokens??0)+' · Выход '+(u.output_tokens??0)):'Ожидается сверка расхода');if(a.providerUsd!=null)p.append(' · $'+a.providerUsd);detail.append(p);}li.append(detail);}
 return li;
}
if($('#ai-usage-refresh')){action($('#ai-usage-refresh'),refreshUsage);refreshUsage().catch(error);}
action($('#account-costs'),async f=>{const login=f.elements.login.value.trim();const w=await api('/api/admin/accounts/'+encodeURIComponent(login)+'/wallet');txt('account-costs-result',login+' · Доступно '+w.available+' · В резерве '+w.reserved);const m=w.providerMeters?.DeepSeek||{input:0,cache:0,output:0,coins:'0'};txt('account-meters','DeepSeek · вход '+m.input+' · кэш '+m.cache+' · выход '+m.output+' · списано '+m.coins+' монет');$('#charges').replaceChildren(...w.charges.map(renderCharge));});
function pricing(d){const f=$('#pricing-form');f.elements.markupPercent.value=d.markupPercent;txt('sale-price','Цена покупки: '+(1+Number(d.markupPercent)/100).toLocaleString('ru-RU',{maximumFractionDigits:4})+' ₽. При расходе 1 монета = 1 ₽.');}
if($('#pricing-form')){api('/api/admin/coin-pricing').then(pricing).catch(error);action($('#pricing-form'),async f=>{pricing(await post('/api/admin/coin-pricing',{markupPercent:f.elements.markupPercent.value}));f.querySelector('output').textContent='Цена сохранена.';});}
let pendingGrant;
action($('#credit-form'),async f=>{const fields=Object.fromEntries(new FormData(f)),signature=JSON.stringify(fields);if(pendingGrant?.signature!==signature)pendingGrant={signature,id:crypto.randomUUID()};await post('/api/admin/coin-grants',{...fields,requestId:pendingGrant.id});pendingGrant=null;f.reset();f.querySelector('output').textContent='Монеты начислены.';});
const modelLabels={off:'Выключено',low:'Низкое',high:'Высокое',max:'Максимальное'};
let modelChoices=[],currentModel;
function modelCurrent(v){currentModel=v;txt('current-model','Сейчас: '+v.model+' · рассуждение: '+(modelLabels[v.effort]||v.effort));}
function modelEfforts(){const f=$('#default-model'),m=modelChoices.find(x=>x.id===f.elements.model.value);if(!m)return;f.elements.effort.replaceChildren(...m.efforts.map(x=>new Option(modelLabels[x]||x,x)));f.elements.effort.value=m.id===currentModel?.model&&m.efforts.includes(currentModel.effort)?currentModel.effort:m.defaultEffort;}
if($('#default-model')){
 api('/api/admin/chat-default').then(modelCurrent).catch(error);
 $('#default-model').elements.model.onchange=modelEfforts;
 action($('#refresh-models'),async()=>{const [d,current]=await Promise.all([api('/api/admin/chat-models'),api('/api/admin/chat-default')]);modelCurrent(current);modelChoices=d.models.filter(x=>x.family==='DeepSeek'&&x.chat);const f=$('#default-model');f.elements.model.replaceChildren(...modelChoices.map(x=>new Option(x.name,x.id)));f.hidden=!modelChoices.length;if(modelChoices.some(x=>x.id===current.model))f.elements.model.value=current.model;modelEfforts();txt('model-status',d.catalogMessage||'Каталог обновлён.');});
 action($('#default-model'),async f=>{modelCurrent(await post('/api/admin/chat-default',{model:f.elements.model.value,effort:f.elements.effort.value}));txt('model-status','Настройки сохранены.');});
}
async function balances(kind='',data=null){const url='/api/admin/provider-balances'+kind;const d=kind?await post(url,data||{}):await api(url);const f=$('#balance-settings'),a=$('#balance-alert-settings'),v=d.providers.deepseek,alerts=d.telegramAlerts;txt('balance-deepseek',v.amounts.map(x=>x.amount+' '+x.currency).join(' · ')||'—');txt('balance-deepseek-status',[v.updatedAt?'Обновлено '+new Date(v.updatedAt*1000).toLocaleString('ru-RU'):'',v.error].filter(Boolean).join(' · ')||'Ожидает обновления');f.elements.intervalMinutes.value=d.intervalMinutes;a.elements.thresholdUsd.value=alerts.thresholdUsd;a.elements.cnyPerUsd.value=alerts.cnyPerUsd??'';txt('balance-telegram-status',alerts.enabled?'Оповещения включены.':alerts.linked?'Telegram привязан. Сохраните порог.':'Telegram не подключён.');for(const e of [...f.elements,...a.elements])e.disabled=false;$('#balance-telegram-test').disabled=!alerts.linked;if(kind)txt('balance-message',kind==='/telegram-test'?'Сообщение отправлено.':'Настройки и баланс обновлены.');}
if($('#balance-settings')){
 balances().catch(error);
 action($('#balance-refresh'),()=>balances('/refresh'));
 action($('#balance-settings'),f=>balances('/settings',{intervalMinutes:f.elements.intervalMinutes.valueAsNumber}));
 action($('#balance-alert-settings'),f=>balances('/alert-settings',{thresholdUsd:f.elements.thresholdUsd.valueAsNumber.toFixed(2),cnyPerUsd:f.elements.cnyPerUsd.value}));
 action($('#balance-telegram-test'),()=>balances('/telegram-test'));
 action($('#balance-telegram-connect'),async()=>{const d=await post('/api/admin/provider-balances/telegram-connect',{}),u=new URL(d.url,location.origin);if(!(u.origin===location.origin&&u.pathname==='/telegram/return')&&!(u.origin==='https://oauth.telegram.org'&&u.pathname==='/auth'))throw Error('Недопустимый адрес авторизации.');location.href=u.href;});
}
let guestRevision=0;
async function guests(){const v=++guestRevision,period=$('#guest-period').value,custom=['day','range'].includes(period),from=$('#guest-from'),to=$('#guest-to');$('#guest-from-label').hidden=!custom;$('#guest-to-label').hidden=period!=='range';const params=new URLSearchParams({period});if(custom)params.set('from',from.value);if(period==='range')params.set('to',to.value);if(custom&&(!from.value||period==='range'&&(!to.value||from.value>to.value))){txt('guest-coverage','Укажите корректный период.');return;}
 try{const d=await api('/api/admin/guest-activity?'+params);if(v!==guestRevision)return;for(const x of [from,to]){x.min=d.earliest;x.max=d.today;if(!x.value)x.value=d.today;}for(const x of document.querySelectorAll('[data-guest]')){const n=d[x.dataset.guest];x.textContent=n==null?'—':(d.unknown>0&&['tokens','rub','usd'].includes(x.dataset.guest)?'≥ ':'')+fmt.format(n);}txt('guest-coverage',[d.from+' — '+d.to,d.activityPartial?'Частичный период учёта гостей.':'',d.costPartial?'Частичный период учёта расходов.':'',d.unknown?'Без квитанции: '+d.unknown:''].filter(Boolean).join(' · '));}catch(e){txt('guest-coverage',e.message);}
}
if($('#guest-period')){for(const id of ['guest-period','guest-from','guest-to'])$('#'+id).addEventListener('change',guests);guests();}
document.addEventListener('DOMContentLoaded',()=>{window.PMMatrix?.load();window.PMMarket?.loadConfig();});
