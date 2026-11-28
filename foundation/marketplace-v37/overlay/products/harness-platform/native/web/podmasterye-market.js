'use strict';
// One set of presentation adapters in the cabinet and inline in chat. All
// calculations, permissions, secrets, progress and job transitions are server-owned.
(()=>{
const definitions={
 ozon:{title:'Ozon',fields:[['client_id','Client-Id Seller API'],['api_key','Api-Key Seller API']]},
 wb:{title:'Wildberries',fields:[['token','API-токен Wildberries']]},
 yandex_market:{title:'Яндекс Маркет',fields:[['api_key','API-ключ Яндекс Маркета']]}
};
const states={ready:'Готово',complete:'Готово',completed:'Готово',verified:'Доступ подтверждён',saved:'Ключ сохранён; доступ ещё не проверен',collecting:'Собираем данные',running:'Собираем данные',queued:'В очереди',pending:'В очереди',waiting_retry:'Ожидаем допустимого времени повтора',rate_limited:'Площадка ограничила частоту запросов',deferred:'Повтор отложен',waiting_for_provider:'Ожидаем площадку',partial:'Неполные данные',incomplete:'Неполные данные',denied:'Нет необходимого доступа',uncertain:'Исход запроса не подтверждён',needs_attention:'Требуется проверка',stopped:'Сбор остановлен',cancelled:'Сбор остановлен',error:'Ошибка сбора',failed:'Ошибка сбора',not_collected:'Не собрано',no_data_confirmed:'Отсутствие данных подтверждено',zero:'Отсутствие данных подтверждено',unconfirmed:'Доступ не подтверждён',unknown:'Не определено',no_data:'Нет данных для расчёта'};
const labels={ordered:'Заказано',delivered:'Доставлено',cancelled:'Отменено',canceled:'Отменено',nonbuyout:'Не выкуплено',physical_returns:'Физически возвращено',calendar_returns:'Возвраты реализации',losses:'Подтверждённые потери',estimated_losses:'Ожидаемые потери',estimated_delivered:'Доставлено, прогноз',estimated_physical_returns:'Физические возвраты, прогноз',unredeemed:'Не выкуплено',returned:'Физически возвращено',physical_returned:'Физически возвращено',net:'Чистые продажи, факт',actual_net:'Чистые продажи, факт',forecast_net:'Чистые продажи, прогноз',estimated_net:'Чистые продажи, прогноз',predicted_net:'Чистые продажи, прогноз',known_losses:'Подтверждённые потери',expected_losses:'Ожидаемые потери',unmapped:'Не сопоставлено',unknown:'Не подтверждено'};
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=String(text);if(cls)n.className=cls;return n;};
const button=(text,fn)=>{const b=el('button',text,'secondary');b.type='button';b.onclick=fn;return b;};
const field=(text,input)=>{const l=el('label',text);l.append(input);return l;};
const input=(type,value='')=>{const i=el('input');i.type=type;i.value=value;return i;};
const requestId=()=>crypto.randomUUID();
const list=d=>Array.isArray(d)?d:d?.rows||d?.items||d?.products||d?.rates||d?.catalog||[];
const dateText=v=>{if(v==null||v==='')return 'Не указано';const d=new Date(typeof v==='number'?v*1000:v);return Number.isNaN(d.valueOf())?String(v):d.toLocaleString('ru-RU');};
const sourceLabel=s=>definitions[s]?.title||({all_marketplaces:'Все маркетплейсы',ledger:'Проведённые продажи мастерской'})[s]||s;
const statusWatches=new WeakMap();
const controlNotices=new WeakMap();
let chatWatchHost=null;
function validContext(w){if(w&&window.PMWorkshopId!==w)throw Error('Открыта другая мастерская. Обновите карточку в текущем чате.');}
async function call(name,args={},w=window.PMWorkshopId,id=requestId(),channel='ui'){
 validContext(w);return post('/api/integrations/marketplaces/operations',{operation:name,arguments:args,requestId:id,channel});
}
async function download(operation,args,w){
 validContext(w);const params=new URLSearchParams({workshop:w}),r=await fetch('/api/integrations/marketplaces/export?'+params,{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json'},body:JSON.stringify({operation,arguments:args})});
 if(!r.ok){const d=await r.json().catch(()=>({}));throw Error(d.detail||d.error||'Не удалось выгрузить отчёт.');}
 const url=URL.createObjectURL(await r.blob()),a=el('a');a.href=url;a.download='marketplace-report.zip';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function table(host,columns,rows){
 const wrap=el('div',null,'table-scroll'),t=el('table'),head=t.createTHead().insertRow();
 for(const [label] of columns)head.append(el('th',label));const body=t.createTBody();
 for(const row of rows){const tr=body.insertRow();for(const [,getter] of columns){const cell=tr.insertCell(),v=typeof getter==='function'?getter(row):row[getter];if(v instanceof Node)cell.append(v);else cell.textContent=v==null?'Не подтверждено':String(v);}}
 if(!rows.length)host.append(el('p','Нет строк для отображения. Полнота указана отдельно.','hint'));else{wrap.append(t);host.append(wrap);}
}
function stateBox(host,d){
 const state=d.state||d.status||'not_collected';host.append(el('p',states[state]||state,'hint'));
 if(d.message)host.append(el('p',d.message));
 const next=d.next_retry_at??d.nextRetryAt;if(next!=null&&Number(next)!==0&&['waiting_retry','rate_limited','deferred','waiting_for_provider','needs_attention','stopped'].includes(state))host.append(el('p','Следующая попытка не ранее '+dateText(next)+'. Уже сохранённый прогресс сохранится.','hint'));
 const observed=d.last_success??d.last_success_at??d.observed_at??d.collected;if(observed!=null)host.append(el('p','Последнее успешное обновление: '+dateText(observed),'hint'));
 const done=d.completed_windows??d.progress?.complete??d.progress?.completed??d.progress?.done,total=d.total_windows??d.progress?.total;
 if(done!=null)host.append(el('p','Обработано периодов: '+done+(total!=null?' из '+total:'; общий объём ещё уточняется'),'hint'));
 if(d.progress?.earliest_completed_window)host.append(el('p','Начало подтверждённой истории: '+d.progress.earliest_completed_window,'hint'));
 if(d.history){if(d.history.message)host.append(el('p',d.history.message,'hint'));if(d.history.paused)host.append(el('p','Регулярное обновление этого магазина остановлено.','hint'));else if(d.history.next_update_at)host.append(el('p','Следующее регулярное обновление: '+dateText(d.history.next_update_at),'hint'));}
 if(d.stale)host.append(el('p','Снимок изменяемых данных устарел. Дождитесь обновления перед планированием.','hint'));
 for(const warning of d.warnings||[])host.append(el('p',typeof warning==='string'?warning:warning.message||warning.reason,'hint'));
 if(d.last_complete_snapshot||d.last_good_snapshot)host.append(el('p','Последний полный снимок сохранён. Текущее незавершённое обновление его не заменяет.','hint'));
}
function coverage(host,value){
 if(value==null){host.append(el('p','Полнота истории не подтверждена. Неизвестные количества не равны нулю.','hint'));return;}
 if(Array.isArray(value)){table(host,[['Площадка / источник',r=>sourceLabel(r.provider||r.source||r.store_id||'')],['С',r=>r.from??r.start??r.date_from],['По',r=>r.to??r.end??r.date_to],['Покрытие',r=>states[r.state||r.status]||r.reason||(r.complete===true?'Полное':'Неполное')]],value);return;}
 host.append(el('p',value.complete===true?'Выбранный период подтверждён полностью.':'Выбранный период подтверждён не полностью.','hint'));
 if(value.reason)host.append(el('p',value.reason,'hint'));
 if(value.gaps?.length)table(host,[['Не загружено с',r=>r.from??r.start],['По',r=>r.to??r.end],['Причина','reason']],value.gaps);
 if(value.windows)coverage(host,value.windows);
}
function statusView(host,d,{w,channel='ui',refresh}={}){
 host.replaceChildren();stateBox(host,d);
 for(const notice of controlNotices.get(host)||[])host.append(el('p',notice,'error'));
 for(const blocked of d.blocked_jobs||[])host.append(el('p','Задание '+blocked.job_id+': '+blocked.message,'error'));
 const groups=d.groups||(d.group?[d.group]:(d.job_id&&d.jobs?.length?[d]:[])),groupIds=new Set(groups.map(x=>x.job_id||x.id));
 const jobs=(d.jobs||d.tasks||(d.job?[d.job]:(d.job_id||d.id?[d]:[]))).filter(x=>!groupIds.has(x.job_id||x.id));
 const details=el('details');if(groups.length&&jobs.length)details.append(el('summary','Отдельные источники и периоды'));
 for(const job of [...groups,...jobs]){
  const id=job.job_id||job.id;if(!id)continue;
  const isGroup=groupIds.has(id),box=el('section',null,'settings-card');box.append(el('h4',(isGroup?'Сбор истории ':'Задание ')+id));stateBox(box,job);
  const controls=el('div',null,'button-group'),status=el('p');status.setAttribute('role','status');
  for(const [action,label] of [['cancel','Остановить'],['resume','Продолжить'],['retry','Повторить']])controls.append(button(label,async()=>{
   try{validContext(w);const result=await call('market_sync_control',{job_id:id,action},w,requestId(),channel);const notices=(result.blocked_jobs||[]).map(x=>'Задание '+x.job_id+': '+x.message);controlNotices.set(host,notices);status.textContent=notices.join(' ')||states[result.state||result.status]||'Состояние задания обновлено';if(refresh)await refresh();}
   catch(e){controlNotices.set(host,[e.message]);status.textContent=e.message;}
  }));
  box.append(controls,status);(groups.length&&!isGroup?details:host).append(box);
 }
 if(groups.length&&jobs.length)host.append(details);
 if(d.stores?.length)table(host,[['Площадка',r=>sourceLabel(r.provider)],['Магазин',r=>r.name||r.store_id],['Статус',r=>states[r.state||r.status]||r.state||r.status||(r.verified?'Доступ подтверждён':'Не подтверждён')],['Обновлено',r=>dateText(r.last_success??r.observed_at??r.checked)]],d.stores);
 if('coverage' in d)coverage(host,d.coverage);
}
function watchStatus(host,d,args,{w,channel='ui'}={}){
 if(channel==='chat'&&chatWatchHost!==host){const old=statusWatches.get(chatWatchHost);if(old)clearTimeout(old);chatWatchHost=host;}
 const previous=statusWatches.get(host);if(previous)clearTimeout(previous);
 const waiting=['queued','pending','collecting','running','waiting_retry','rate_limited','deferred','waiting_for_provider'];
 if(!waiting.includes(d.state||d.status)&&![...(d.jobs||[]),...(d.groups||[])].some(x=>waiting.includes(x.state||x.status)))return;
 const timer=setTimeout(async()=>{
  if(!host.isConnected||window.PMWorkshopId!==w)return;
  try{const next=await call('market_sync_status',args,w,requestId(),channel);if(!host.isConnected||window.PMWorkshopId!==w)return;const refresh=async()=>{const value=await call('market_sync_status',args,w,requestId(),channel);statusView(host,value,{w,channel,refresh});watchStatus(host,value,args,{w,channel});};statusView(host,next,{w,channel,refresh});watchStatus(host,next,args,{w,channel});}
  catch(e){if(host.isConnected)host.append(el('p','Не удалось обновить отображение: '+e.message+'. Сбор на сервере сохраняет своё состояние.','hint'));}
 },document.hidden?30000:5000);statusWatches.set(host,timer);
}
function select(options,value){const s=el('select');for(const [v,label] of options){const o=el('option',label);o.value=v;s.append(o);}if(value!=null)s.value=value;return s;}
function scopeSelect(value='all_marketplaces'){return select([['all_marketplaces','Все маркетплейсы'],...Object.entries(definitions).map(([key,d])=>[key,d.title])],value);}
function secretFields(host,provider){
 host.replaceChildren();for(const [key,label] of definitions[provider].fields){const i=input('password');i.name=key;i.autocomplete='new-password';i.maxLength=8192;i.dataset.privateField='true';i.required=true;host.append(field(label,i));}
 if(provider==='yandex_market')host.append(el('p','Для полного сбора истории нужен ключ с доступом «Просмотр всех данных». Фактические разрешения проверит сервер.','hint'));
 host.append(el('p','Ключ отправляется только в защищённое хранилище сервера. Он не входит в сообщения и контекст Подмастерья.','hint'));
}
function connectionForm(host,card={},opts={}){
 const w=card.workshop||opts.w||window.PMWorkshopId,channel=opts.channel||'ui',current=card.connection;
 const action=card.action==='rotate'?'rotate':card.action==='disconnect'?'disconnect':card.action==='verify'?'verify':'create';
 const form=el('form',null,'panel');form.dataset.marketConnectionForm=action;
 const title=action==='create'?'Подключить маркетплейс':action==='rotate'?'Заменить ключ':action==='disconnect'?'Отключить магазин':'Проверить доступ';
 form.append(el('h4',title+(current?' · '+current.name:'')));
 const provider=select(Object.entries(definitions).map(([p,v])=>[p,v.title]),current?.provider||card.provider||'ozon');provider.name='provider';
 const name=input('text',current?.name||'');name.name='name';name.maxLength=80;name.required=true;
 const secrets=el('div',null,'fields');
 if(action==='create'){form.append(field('Площадка',provider),field('Название магазина',name));secretFields(secrets,provider.value);provider.onchange=()=>secretFields(secrets,provider.value);form.append(secrets);}
 if(action==='rotate'){secretFields(secrets,current.provider);form.append(secrets);}
 if(action==='disconnect')form.append(el('p','Новые запросы этого подключения будут остановлены. Подтвердите отключение выбранного магазина.'));
 const status=el('p');status.setAttribute('role','status');const submit=el('button',action==='disconnect'?'Подтвердить отключение':action==='verify'?'Проверить':'Сохранить ключ');submit.type='submit';
 const cancel=button('Отмена',()=>{form.reset();form.replaceChildren(el('p','Действие отменено. Ключ не сохранён.'));});
 form.append(submit,cancel,status);let busy=false,pendingId=null,pendingSignature=null;
 form.addEventListener('input',()=>{pendingId=null;pendingSignature=null;});
 form.onsubmit=async e=>{
  e.preventDefault();if(busy)return;
  try{
   validContext(w);busy=true;submit.disabled=true;
   const payload={action,requestId:''};
   if(current){payload.connection_id=current.id;payload.version=current.version;}
   if(action==='create'){payload.provider=provider.value;payload.name=name.value.trim();}
   if(action==='create'||action==='rotate')payload.fields=Object.fromEntries(definitions[current?.provider||provider.value].fields.map(([key])=>[key,form.elements[key].value.trim()]));
   // The secret body remains only in this submission; never attach it to a
   // chat request, DOM dataset, storage, error, analytics event or retry log.
   const signature=JSON.stringify([action,payload.connection_id,payload.version,payload.name,payload.provider]);
   if(!pendingId||pendingSignature!==signature){pendingId=requestId();pendingSignature=signature;}payload.requestId=pendingId;
   const result=await post('/api/integrations/marketplaces/connection',payload);
   for(const i of secrets.querySelectorAll('input'))i.value='';
   pendingId=null;pendingSignature=null;
   status.textContent=action==='disconnect'?'Подключение отключено.':action==='verify'?(states[result.state||result.status]||'Проверка поставлена в очередь.'):'Ключ сохранён. Проверка и первичная история выполняются на сервере.';
   if(result.job_id){const jobs=el('div'),args={job_id:result.job_id};form.append(jobs);const refresh=async()=>{const d=await call('market_sync_status',args,w,requestId(),channel);statusView(jobs,d,{w,channel,refresh});watchStatus(jobs,d,args,{w,channel});};statusView(jobs,result,{w,channel,refresh});watchStatus(jobs,result,args,{w,channel});}
   if(opts.onSaved)await opts.onSaved(result);
  }catch(err){status.textContent=err.message;}
  finally{busy=false;submit.disabled=false;}
 };
 host.append(form);return form;
}
function connectionsView(host,card,{w,channel='ui',refresh}={}){
 host.replaceChildren();
 const create=el('div');host.append(button('Подключить маркетплейс',()=>{create.replaceChildren();connectionForm(create,{action:'connect',workshop:w},{w,channel,onSaved:refresh});}),create);
 for(const c of card.connections||[]){
  const box=el('section',null,'settings-card');box.append(el('h4',c.name+' · '+sourceLabel(c.provider)),el('p','ID подключения: '+c.id,'hint'));
  if(!c.checked)box.append(el('p',states.saved+'. Проверка выполняется в общей очереди.','hint'));
  if(c.checked)box.append(el('p','Проверено: '+dateText(c.checked),'hint'));
  for(const [key,value] of Object.entries(c.checks||{}))box.append(el('p',key+': '+(states[value]||value),'hint'));
  if(c.details?.scopes?.length)box.append(el('p','Доступ: '+c.details.scopes.map(s=>['ALL_METHODS_READ_ONLY','all-methods:read-only'].includes(s)?'Просмотр всех данных':s).join(', '),'hint'));
  for(const s of c.details?.campaigns||[])box.append(el('p',(s.name?s.name+' · ':'')+'ID магазина: '+s.campaignId+' · ID кабинета: '+s.businessId+(s.placementType?' · '+s.placementType:''),'hint'));
  const controls=el('div',null,'button-group'),formHost=el('div');
  for(const [action,label] of [['verify','Проверить доступ'],['rotate','Заменить ключ'],['disconnect','Отключить']])controls.append(button(label,()=>{formHost.replaceChildren();connectionForm(formHost,{action,connection:c,workshop:w},{w,channel,onSaved:refresh});}));
  box.append(controls,formHost);host.append(box);
 }
 if(!card.connections?.length)host.append(el('p','Подключённых магазинов пока нет.','hint'));
}
function mappingForm(host,row,{w,channel='ui',onSaved}={}){
 const form=el('form',null,'panel');form.append(el('h4','Сопоставить артикул '+row.sku));
 const product=select([['','Не сопоставлено — снять связь']]);product.name='product';product.disabled=true;form.append(field('Изделие мастерской',product));
 api('/api/accounting/seasonal/sources').then(data=>{if(!product.isConnected)return;for(const p of data.products||[]){const o=el('option',p.name);o.value=p.id;product.append(o);}product.value=row.product_id||'';product.disabled=false;}).catch(e=>{status.textContent=e.message;});
 const check=el('button','Проверить сопоставление');check.type='submit';const save=button('Подтвердить',async()=>{
  if(!draft)return;save.disabled=true;
  try{validContext(w);const result=await post('/api/integrations/marketplaces/mapping-confirm',{arguments:draft.arguments,revision:draft.revision,requestId:confirmationId});status.textContent=result.summary;draft=null;if(onSaved)await onSaved();}
  catch(e){status.textContent=e.message;save.disabled=false;}
 });save.disabled=true;const status=el('p');status.setAttribute('role','status');let draft=null,confirmationId=null;
 product.oninput=()=>{draft=null;save.disabled=true;};form.onsubmit=async e=>{e.preventDefault();try{if(product.disabled)throw Error('Список изделий ещё не загружен.');const r=await call('market_mapping',{source:row.store_id||row.source,sku:row.sku,product:product.value||null},w,requestId(),channel);draft=r.marketDraft;confirmationId=requestId();status.textContent=draft.summary;save.disabled=false;}catch(err){status.textContent=err.message;}};
 form.append(check,save,button('Отмена',()=>form.remove()),status);host.append(form);
}
function resultView(host,operation,d,{w,channel='ui',refresh}={}){
 if(operation==='market_sync_status'||operation==='market_sync_request'||operation==='market_sync_control'){statusView(host,d,{w,channel,refresh});return;}
 host.replaceChildren();stateBox(host,d);
 if(d.totals){const pairs=Object.entries(d.totals).filter(([,v])=>v===null||typeof v!=='object');table(host,[['Показатель',r=>labels[r[0]]||r[0]],['Количество',r=>r[1]]],pairs);}
 if('coverage' in d)coverage(host,d.coverage);
 const rows=list(d);
 if(operation==='market_catalog'){
  table(host,[['Площадка',r=>sourceLabel(r.provider)],['Магазин','store_id'],['Артикул','sku'],['Название','name'],['Изделие',r=>r.product_id||'Не связано'],['Действие',r=>button('Сопоставить',()=>{const box=el('div');host.append(box);mappingForm(box,r,{w,channel,onSaved:refresh});})]],rows);
 }else if(operation==='market_loss_rates'){
  table(host,[['Товар / группа',r=>r.sku||r.product_id||r.category_id||r.store_id],['Уровень',r=>({sku:'Артикул',category:'Категория',store:'Магазин'})[r.source_level||r.level]||r.source_level||r.level],['Потеряно',r=>r.numerator??r.lost],['Исходно заказано',r=>r.denominator??r.ordered],['Потери, %',r=>r.loss_rate_percent??r.order_loss_rate??r.loss_rate??r.rate],['Период',r=>[r.from||r.start,r.to||r.end].filter(Boolean).join(' — ')],['Статус',r=>states[r.state||r.status]||r.reason||'Не подтверждён'],['Основание',r=>{const detail=el('details');detail.append(el('summary','Покрытие и выборка'));coverage(detail,r.coverage);if(r.maturity_days!=null)detail.append(el('p','Минимальная зрелость: '+r.maturity_days+' дней. Незавершённые заказы остаются предварительными.','hint'));detail.append(el('p',r.sample_sufficient?'Выборка достаточна по серверному критерию.':'Выборка недостаточна; неподтверждённый коэффициент не используется.','hint'));if(r.fallback_attempts)table(detail,[['Уровень','level'],['Потери','numerator'],['Исходно заказано','denominator'],['Достаточность',x=>x.sample_sufficient?'Да':'Нет']],r.fallback_attempts);return detail;}]],rows);
 }else{
  table(host,[['Товар / период',r=>r.day||r.month||r.product||r.product_name||r.sku||r.name||r.key||sourceLabel(r.provider)],['Заказано','ordered'],['Доставлено','delivered'],['Доставлено, прогноз','estimated_delivered'],['Отменено','cancelled'],['Не выкуплено','nonbuyout'],['Возвраты реализации','calendar_returns'],['Физически возвращено','physical_returns'],['Чистые продажи, факт','net'],['Чистые продажи, прогноз','estimated_net']],rows);
 }
 const total=d.total??d.total_rows??d.row_count;if(total!=null)host.append(el('p','Показано '+rows.length+' из '+total+'. Итоги рассчитаны сервером по всему набору.','hint'));
 if(d.problems?.length)for(const problem of d.problems)host.append(el('p',typeof problem==='string'?problem:problem.message||problem.reason||problem.kind,'hint'));
}
function reportForm(host,operation,{w,channel='ui',args={}}={}){
 const box=el('section',null,'panel'),form=el('form'),fields=el('div',null,'fields'),source=scopeSelect(args.source),from=input('date',args.from||new Date().toISOString().slice(0,7)+'-01'),to=input('date',args.to||new Date().toISOString().slice(0,10)),group=select([['product','По изделиям'],['marketplace','По площадкам'],['day','По дням'],['month','По месяцам']],args.group_by||'product'),unmapped=input('checkbox'),reload=input('checkbox');reload.checked=!!args.refresh;
 unmapped.checked=!!args.unmapped_only;fields.append(field('Источник',source));
 if(operation==='market_sales'||operation==='market_sync_request')fields.append(field('С даты',from),field('По дату',to));
 if(operation==='market_sync_request')fields.append(field('Обновить уже загруженные данные',reload));
 if(operation==='market_sales')fields.append(field('Группировка',group));
 const product=select([['','Все изделия']]);
 if(['market_sales','market_loss_rates'].includes(operation)){
  fields.append(field('Изделие',product));api('/api/accounting/seasonal/sources').then(data=>{if(!product.isConnected)return;for(const p of data.products||[]){const o=el('option',p.name);o.value=p.id;product.append(o);}product.value=args.product||'';}).catch(()=>{});
 }
 const search=input('search',args.search||'');search.maxLength=160;
 if(operation==='market_catalog')fields.append(field('Артикул или название',search),field('Только несвязанные артикулы',unmapped));
 const submit=el('button',operation==='market_sync_request'?'Запустить сбор':'Показать');submit.type='submit';const status=el('p');status.setAttribute('role','status');const out=el('div'),pager=el('div',null,'button-group');let offset=0,lastArgs=null,busy=false;
 // Store choices are read from the same local status projection, never from a
 // new provider request. A provider-wide selection remains the default.
 call('market_sync_status',{},w,requestId(),channel).then(d=>{if(!source.isConnected)return;for(const s of d.stores||[]){if(!s.verified)continue;const o=el('option',sourceLabel(s.provider)+' · '+s.name);o.value=s.store_id||s.id;source.append(o);}if(args.source)source.value=args.source;}).catch(()=>{});
 const run=async(reuse=false)=>{
  if(busy)return;busy=true;submit.disabled=true;
  try{validContext(w);const a=reuse?{...lastArgs,offset}:{source:source.value};
   if(!reuse){offset=0;if(operation==='market_sales'||operation==='market_sync_request'){if(from.value)a.from=from.value;if(to.value)a.to=to.value;}
    if(operation==='market_sync_request')a.refresh=reload.checked;if(operation==='market_sales')a.group_by=group.value;if(['market_sales','market_loss_rates'].includes(operation)&&product.value)a.product=product.value;if(operation==='market_catalog'){a.unmapped_only=unmapped.checked;if(search.value.trim())a.search=search.value.trim();}
    if(['market_sales','market_loss_rates','market_catalog'].includes(operation))Object.assign(a,{offset,limit:30});}
   lastArgs=a;const d=await call(operation,a,w,requestId(),channel);const refresh=operation==='market_sync_request'?async()=>{const state=await call('market_sync_status',{source:a.source},w,requestId(),channel);resultView(out,'market_sync_status',state,{w,channel,refresh});watchStatus(out,state,{source:a.source},{w,channel});}:()=>run(true);resultView(out,operation,d,{w,channel,refresh});if(operation==='market_sync_request')watchStatus(out,d,d.job_id?{job_id:d.job_id}:{source:a.source},{w,channel});status.textContent=operation==='market_sync_request'?'Задание сохранено. Можно закрыть страницу или продолжить управление в другом канале.':'Локальные данные. Запрос к маркетплейсу и модели не выполнялся.';
   const total=d.total??d.total_rows??d.row_count??0;prev.disabled=offset===0;next.disabled=offset+list(d).length>=total;
  }catch(e){status.textContent=e.message;}finally{busy=false;submit.disabled=false;}
 };
 const prev=button('Назад',()=>{offset=Math.max(0,offset-30);run(true);}),next=button('Далее',()=>{offset+=30;run(true);});prev.disabled=next.disabled=true;
 if(['market_sales','market_loss_rates','market_catalog'].includes(operation))pager.append(prev,next);
 form.onsubmit=e=>{e.preventDefault();run();};form.append(fields,submit);
 if(['market_sales','market_loss_rates','market_catalog'].includes(operation))form.append(button('Экспорт полного отчёта',async()=>{try{if(!lastArgs)await run();if(lastArgs)await download(operation,lastArgs,w);}catch(e){status.textContent=e.message;}}));
 box.append(form,status,out,pager);host.append(box);return {run,out};
}
async function qualityForm(host,{w}={}){
 const d=await api('/api/accounting'),policy=d.quality_policy||{},form=el('form',null,'panel'),fields=el('div',null,'fields'),ret=input('number',policy.return_defect_percent??''),scrap=input('number',policy.production_scrap_percent??'');
 for(const i of [ret,scrap]){i.min=0;i.step='0.01';}ret.max=100;scrap.max=99.99;
 fields.append(field('Брак среди физических возвратов, %',ret),field('Потери сырья при производстве, %',scrap));
 form.append(el('p','Это два независимых коэффициента. Пустое поле означает «не задан»; коэффициент отмен заказов здесь не меняется.','hint'),fields);
 const status=el('p');status.setAttribute('role','status');let preview=null,id=null;
 const confirm=button('Подтвердить коэффициенты',async()=>{if(!preview)return;confirm.disabled=true;try{validContext(w);const r=await post('/api/accounting/commit',{requestId:id,operation:'quality_policy',arguments:preview.arguments,revision:preview.revision});status.textContent=r.summary||'Коэффициенты сохранены.';preview=null;}catch(e){status.textContent=e.message;}});confirm.disabled=true;
 const check=el('button','Проверить изменение');check.type='submit';form.onsubmit=async e=>{e.preventDefault();try{validContext(w);preview=await post('/api/accounting/preview',{operation:'quality_policy',arguments:{return_defect_percent:ret.value===''?null:ret.value,production_scrap_percent:scrap.value===''?null:scrap.value}});id=requestId();status.textContent=preview.preview?.summary||'Проверьте оба значения и подтвердите.';confirm.disabled=false;}catch(err){status.textContent=err.message;}};
 for(const i of [ret,scrap])i.oninput=()=>{preview=null;confirm.disabled=true;};form.append(check,confirm,button('Отмена',()=>{ret.value=policy.return_defect_percent??'';scrap.value=policy.production_scrap_percent??'';preview=null;confirm.disabled=true;status.textContent='Изменение отменено.';}),status);host.append(form);
}
async function forecastForm(host,{w,channel='ui'}={}){
 const data=await api('/api/accounting/seasonal/sources'),form=el('form',null,'panel'),fields=el('div',null,'fields'),source=select(data.sources.map(s=>[s.id,s.title]));
 const metric=select([['net','Чистые продажи'],['delivered','Доставленные изделия']]),metricField=field('Основание плана',metric);
 source.onchange=()=>{metricField.hidden=source.value==='ledger';if(metricField.hidden)metric.value='net';};source.onchange();
 const now=new Date(),previous=String(now.getUTCFullYear()-1)+'-'+String(now.getUTCMonth()+1).padStart(2,'0'),future=String(now.getUTCFullYear()+1)+'-'+String(now.getUTCMonth()+1).padStart(2,'0');
 const start=input('month',previous),end=input('month',previous),target=input('month',future),growth=input('number','0'),reserve=input('number','0'),lead=input('number','7'),wip=input('checkbox'),empty=input('checkbox');wip.checked=true;growth.min=-100;growth.max=1000;reserve.min=0;reserve.max=100;lead.min=0;lead.max=365;
 for(const [label,i] of [['Источник',source],['История с месяца',start],['История по месяц',end],['Начало плана',target],['Изменение продаж, %',growth],['Страховой запас, %',reserve],['Срок поставки, дней',lead],['Учесть незавершённые изделия',wip],['Для учёта: месяцы без продаж считать нулевыми',empty]])fields.append(field(label,i));fields.append(metricField);
 const status=el('p');status.setAttribute('role','status');const out=el('div');let params=null;
 const run=el('button','Рассчитать план');run.type='submit';form.onsubmit=async e=>{e.preventDefault();run.disabled=true;try{validContext(w);params={source:source.value,history_from:start.value,history_to:end.value,target_from:target.value,growth:Number(growth.value),reserve:Number(reserve.value),lead:Number(lead.value),include_wip:wip.checked,accept_empty_ledger:source.value==='ledger'&&empty.checked,metric:source.value==='ledger'?'net':metric.value};const d=await post('/api/accounting/seasonal/plan',params);out.replaceChildren();status.textContent=d.complete?'План рассчитан. Фактические остатки и проводки не изменены.':'Расчёт неполный. Сначала устраните причины ниже.';table(out,[['Месяц','month'],['Покрытие',r=>states[r.state]||r.state]],d.coverage||[]);for(const p of d.problems||[])out.append(el('p',[p.month,p.sku,p.reason].filter(Boolean).join(' · '),'hint'));for(const warning of d.warnings||[])out.append(el('p',warning,'hint'));table(out,[['Материал','material'],['Полезная норма','nominalNeed'],['Потери сырья','productionScrap'],['Общий расход','need'],['Купить упаковок','buyPacks'],['Купить единиц','buyQuantity'],['Остаток','closing']],d.totals||[]);for(const month of d.months||[]){const detail=el('details');detail.append(el('summary',month.historyMonth+' → '+month.targetMonth));table(detail,[['Изделие','product'],['Продать','forecastSales'],['Замена брака возвратов','returnDefectReplacements'],['Обеспечить','replacementDemand'],['Из готового запаса','fromReady'],['Изготовить','produce']],month.products||[]);out.append(detail);}}catch(err){status.textContent=err.message;}finally{run.disabled=false;}};
 form.append(fields,run,button('Экспорт плана',async()=>{try{if(!params)throw Error('Сначала рассчитайте план.');await download('material_forecast',params,w);}catch(e){status.textContent=e.message;}}),status,out);host.append(form);
}
function workspace(host,{w=window.PMWorkshopId,channel='ui',tab='sync'}={}){
 host.replaceChildren();const nav=el('div',null,'button-group'),body=el('div');host.append(nav,body);
 const tabs=[['sync','История и обновления'],['connections','Подключения'],['sales','Продажи'],['loss_rates','Коэффициенты потерь'],['catalog','Артикулы'],['quality','Коэффициенты брака'],['planning','План закупок']];
 let generation=0;
 const show=async name=>{
  const current=++generation;body.replaceChildren();
  try{validContext(w);
   if(name==='quality'){await qualityForm(body,{w,channel});return;}
   if(name==='planning'){await forecastForm(body,{w,channel});return;}
   if(name==='connections'){const d=await call('market_connection',{action:'list'},w,requestId(),channel);if(current===generation)connectionsView(body,d.marketCard,{w,channel,refresh:()=>show(name)});return;}
   if(name==='sync'){
    const stat=el('div');body.append(stat);const refresh=async()=>{const d=await call('market_sync_status',{},w,requestId(),channel);if(current===generation&&stat.isConnected){statusView(stat,d,{w,channel,refresh});watchStatus(stat,d,{}, {w,channel});}};
    body.append(button('Обновить состояние',refresh));await refresh();if(current!==generation)return;
    const details=el('details');details.append(el('summary','Собрать выбранный период'));reportForm(details,'market_sync_request',{w,channel});body.append(details);
    body.append(el('p','Первичная история и регулярное обновление выполняются сервером. Закрытие вкладки или чата не останавливает сбор.','hint'));return;
   }
   const op=name==='sales'?'market_sales':name==='loss_rates'?'market_loss_rates':'market_catalog';const r=reportForm(body,op,{w,channel});await r.run();
  }catch(e){if(current===generation)body.append(el('p',e.message,'error'));}
 };
 for(const [name,label] of tabs)nav.append(button(label,()=>show(name)));show(tab);return {show};
}
function renderReceipt(host,receipt){
 const w=receipt.workshop||receipt.marketCard?.workshop||window.PMWorkshopId,opts={w,channel:'chat'};
 if(receipt.marketResults)for(const item of receipt.marketResults){const box=el('div');host.append(box);renderReceipt(box,{...item,workshop:w});}
 if(receipt.marketCard){const card=receipt.marketCard,box=el('div',null,'pm-market-card');host.append(box);
  if(card.kind==='connection'){
   if(card.action==='list'){const refresh=async()=>{const d=await call('market_connection',{action:'list'},w,requestId(),'chat');connectionsView(box,d.marketCard,{...opts,refresh});};connectionsView(box,card,{...opts,refresh});}
   else connectionForm(box,card,opts);
  }else if(card.kind==='sync'){const refresh=async()=>{try{const d=await call('market_sync_status',card.arguments||{},w,requestId(),'chat');statusView(box,d,{...opts,refresh});watchStatus(box,d,card.arguments||{},opts);}catch(e){box.replaceChildren(el('p',e.message,'error'));}};refresh();}
  else if(card.kind==='export'){const status=el('p');status.setAttribute('role','status');box.append(button('Скачать отчёт ZIP',async()=>{try{await download(card.operation,card.arguments,w);status.textContent='Отчёт подготовлен для скачивания.';}catch(e){status.textContent=e.message;}}),status);}
  else workspace(box,{...opts,tab:card.tab||'sync'});
 }
 if(receipt.marketResult&&!receipt.marketCard){const r=receipt.marketResult,box=el('div',null,'pm-market-result');host.append(box);const statusArgs=r.operation==='market_sync_control'?{job_id:r.arguments.job_id}:r.operation==='market_sync_request'?(r.result.job_id?{job_id:r.result.job_id}:{source:r.arguments.source||'all_marketplaces'}):r.arguments;const sync=['market_sync_status','market_sync_request','market_sync_control'].includes(r.operation);const refresh=async()=>{const d=await call(sync?'market_sync_status':r.operation,statusArgs,w,requestId(),'chat');resultView(box,r.operation,d,{...opts,refresh});if(sync)watchStatus(box,d,statusArgs,opts);};resultView(box,r.operation,r.result,{...opts,refresh});if(sync)watchStatus(box,r.result,statusArgs,opts);}
 const open=button('Управлять маркетплейсами здесь',()=>{const box=el('div');host.append(box);workspace(box,opts);open.remove();});host.append(open);
}
window.PMMarketUI={call,workspace,renderReceipt,connectionForm,resultView,statusView,mappingForm,download,states};
})();
