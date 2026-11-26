'use strict';
(function(){
const q=s=>document.querySelector(s), qa=s=>Array.from(document.querySelectorAll(s));
const el=(tag,txt,cls)=>{const n=document.createElement(tag);if(txt!=null)n.textContent=txt;if(cls)n.className=cls;return n;};
let list=null, state=null, imported=null, importRid=null;
const colorNames={green:'Зелёная',blue:'Синяя',amber:'Янтарная',violet:'Фиолетовая',gray:'Серая'};
function btn(label,fn,cls='secondary compact'){const b=el('button',label,cls);b.type='button';b.onclick=fn;return b;}
function textStatus(id,s){const n=q(id);if(n)n.textContent=s||'';}
function rowTable(host,cols,rows){
 if(!host)return;host.replaceChildren();
 if(!rows.length){host.append(el('p','Нет записей','hint'));return;}
 const wrap=el('div',null,'table-scroll'),t=el('table'),h=t.createTHead().insertRow(),body=t.createTBody();
 for(const c of cols)h.append(el('th',c));
 for(const cells of rows){const row=body.insertRow();for(const v of cells){const c=row.insertCell();if(v instanceof Node)c.append(v);else c.textContent=v??'—';}}
 wrap.append(t);host.append(wrap);
}
function current(){return list?.workshops.find(w=>w.id===window.PMWorkshopId);}
async function initWorkshops(){
 list=await api('/api/workshops');
 const requested=new URLSearchParams(location.search).get('workshop');
 const valid=list.workshops.find(w=>w.id===requested&&!w.archived);
 window.PMWorkshopId=(valid||list.workshops.find(w=>w.id===list.default&&!w.archived)||list.workshops.find(w=>!w.archived)).id;
 const select=q('#workshop-select');
 if(select){select.replaceChildren(...list.workshops.filter(w=>!w.archived).map(w=>new Option(w.name+(w.demo?' · демо':''),w.id)));select.value=window.PMWorkshopId;select.onchange=()=>switchTo(select.value);}
 const name=q('#workshop-caption');if(name)name.textContent=current()?.name||'Мастерская';
 return window.PMWorkshopId;
}
function switchTo(w){if(!w)return;location.href='/app/?workshop='+encodeURIComponent(w);}
function navigateExtra(name){
 if(name==='integrations')loadSources().catch(e=>textStatus('#source-status',e.message));
 if(name==='settings')renderWorkshopSettings();
 if(name==='products'||name==='materials')document.body.classList.toggle('pm-catalog-page',true);else document.body.classList.remove('pm-catalog-page');
 if(matchMedia('(max-width:820px)').matches)document.body.classList.remove('pm-mobile-nav');
}
async function changeWorkshop(action,args){
 const result=await post('/api/workshops/change',{requestId:crypto.randomUUID(),action,arguments:args});
 if(action==='create'||action==='demo')switchTo(result.id);
 else if(action==='archive'&&result.id===window.PMWorkshopId)switchTo(list.default);
 else{list=await api('/api/workshops');const select=q('#workshop-select');select.replaceChildren(...list.workshops.filter(w=>!w.archived).map(w=>new Option(w.name+(w.demo?' · демо':''),w.id)));select.value=window.PMWorkshopId;renderWorkshopSettings();if(action==='update'){q('#workshop-caption').textContent=result.name;const o=Array.from(q('#workshop-select').options).find(x=>x.value===result.id);if(o)o.textContent=result.name+(result.demo?' · демо':'');}await window.PMAccounting.refresh();}
}
function renderWorkshopSettings(populate=true){
 const w=current();if(!w)return;
 const form=q('#workshop-settings');if(form&&populate)for(const k of ['name','description','color','hourly_rate'])form.elements[k].value=w[k]??'';
 const host=q('#workshop-list');
 if(host)rowTable(host,['Мастерская','Выручка, ₽','Прибыль, ₽','Продано, шт.','Действия'],list.workshops.map(x=>{
  const a=el('div',null,'button-group');if(!x.archived)a.append(btn('Открыть',()=>switchTo(x.id)));
  if(x.id!==list.default)a.append(btn(x.archived?'Восстановить':'В архив',async()=>{if(!confirm(x.archived?'Восстановить мастерскую?':'Архивировать мастерскую без удаления истории?'))return;try{await changeWorkshop(x.archived?'restore':'archive',{id:x.id});}catch(e){textStatus('#workshop-status',e.message);}}));
  return [x.name+(x.demo?' · демо':'')+(x.archived?' · архив':''),x.revenue,x.profit,x.sales,a];
 }));
}
function setTheme(mode){window.PMTheme.set(mode);}
function initLayout(){
 const consent=q('#cookie-choice');if(consent&&!localStorage.getItem('pm-cookie-choice')&&document.body.dataset.mode!=='member'){
   consent.hidden=false;
   for(const [id,value] of [['cookie-accept','acknowledged'],['cookie-decline','necessary']])q('#'+id).onclick=()=>{localStorage.setItem('pm-cookie-choice',value);consent.hidden=true;};
 }
 setTheme(localStorage.getItem('pm-theme')||'light');
 matchMedia('(prefers-color-scheme:dark)').addEventListener('change',()=>{if(localStorage.getItem('pm-theme')==='system')setTheme('system');});
 const theme=q('#theme-select');if(theme){theme.value=localStorage.getItem('pm-theme')||'light';theme.onchange=()=>setTheme(theme.value);}
 const toggle=(kind)=>{const mobile=matchMedia('(max-width:820px)').matches;if(mobile){document.body.classList.toggle('pm-mobile-'+kind);document.body.classList.remove('pm-mobile-'+(kind==='nav'?'helper':'nav'));}else{const c='pm-'+kind+'-hidden';document.body.classList.toggle(c);localStorage.setItem(c,document.body.classList.contains(c)?'1':'0');}};
 if(q('#toggle-nav')){if(localStorage.getItem('pm-nav-hidden')==='1')document.body.classList.add('pm-nav-hidden');q('#toggle-nav').onclick=()=>toggle('nav');}
 if(q('#toggle-helper')){if(localStorage.getItem('pm-helper-hidden')==='1')document.body.classList.add('pm-helper-hidden');q('#toggle-helper').onclick=()=>toggle('helper');}
 if(q('#close-helper'))q('#close-helper').onclick=()=>toggle('helper');
 const themeChange=q('#theme-quick');if(themeChange)themeChange.onclick=()=>setTheme(document.documentElement.dataset.theme==='dark'?'light':'dark');
}
function charts(host,rows){
 if(!host)return;host.replaceChildren();if(!rows.length){host.append(el('p','Нет данных за период','hint'));return;}
 const max=Math.max(1,...rows.map(x=>Math.abs(Number(x.value)||0)));
 const box=el('div',null,'chart-block');
 for(const x of rows){const l=el('div',null,'bar-line'),t=el('div',null,'bar-track'),f=el('div',null,'bar-fill'+(Number(x.value)<0?' negative':''));f.style.width=Math.min(100,Math.abs(Number(x.value)||0)*100/max)+'%';t.append(f);l.append(el('span',x.label),t,el('span',x.value+' ₽','chart-value'));box.append(l);}
 host.append(box);
}
function open(op,args){window.PMAccounting.open(op,args);}
function render(d){
 state=d;
 if(q('#workshop-caption')&&d.workshop){q('#workshop-caption').textContent=d.workshop.name;document.documentElement.dataset.workshopColor=d.workshop.color;}
 const f=q('#recipe-form');
 const materials=d.materials.filter(m=>!m.archived),products=d.products.filter(p=>!p.archived);
 for(const [id,items] of [['recipe-materials',materials],['recipe-products',products]]){const node=q('#'+id);node.replaceChildren(...items.map(x=>{const o=el('option');o.value=x.name;return o;}));}
 f.elements.material.onchange=()=>{const m=materials.find(x=>x.name===f.elements.material.value);if(m){f.elements.unit.value=m.unit;f.elements.pack_quantity.value=m.pack;f.elements.pack_price.value=m.planned_pack_price??'';textStatus('#recipe-status','Текущая средняя цена единицы: '+(m.average_price_rub??'нет движения')+' ₽. В форме — плановая цена упаковки.');}};
 rowTable(q('#recipe-lines'),['Изделие','Материал','Расход','Действие'],d.products.filter(p=>!p.archived).flatMap(p=>p.recipe.map(r=>{
  const a=el('div',null,'button-group');a.append(btn('Изменить',()=>open('recipe_line',{product:p.id,material:r.material_id,usage:r.usage})),btn('Удалить строку',()=>open('recipe_line',{product:p.id,material:r.material_id,usage:0})));
  return [p.name,r.material,r.usage+' '+r.unit,a];
 })));
 const taskStatus=q('#task-filter')?.value||'active';
 rowTable(q('#tasks-list'),['Задача','Срок','Важность','Категория','Статус','Действия'],d.tasks.filter(t=>taskStatus==='all'||t.status===taskStatus).map(t=>{
  const a=el('div',null,'button-group');a.append(btn('Изменить',()=>open('task',{task_id:t.id,name:t.name,description:t.description,due:t.due||'',priority:t.priority,task_category:t.category,remind_days:t.remind_days})));
  a.append(btn(t.status==='active'?'Выполнено':'Возобновить',()=>open('task_state',{task_id:t.id,task_status:t.status==='active'?'done':'active'})));
  if(t.status!=='archived')a.append(btn('В архив',()=>open('task_state',{task_id:t.id,task_status:'archived'})));
  return [t.name+(t.description?' — '+t.description:''),t.due?t.due+(t.overdue?' · просрочено':''):'—',t.priority,t.category,{active:'Активна',done:'Выполнена',archived:'Архив'}[t.status],a];
 }));
 rowTable(q('#workers-list'),['Имя','Должность','Выплаты за период, ₽','Действия'],d.workers.map(w=>{
  const a=el('div',null,'button-group');a.append(btn('Изменить',()=>open('worker',{worker_id:w.id,name:w.name,position:w.position,archived:w.archived})));
  if(!w.archived)a.append(btn('Выплата',()=>open('worker_payment',{worker_id:w.id})));
  a.append(btn(w.archived?'Восстановить':'В архив',()=>open('worker',{worker_id:w.id,name:w.name,position:w.position,archived:!w.archived})));
  return [w.name+(w.archived?' · архив':''),w.position,w.payments_rub,a];
 }));
 rowTable(q('#unit-rates'),['Канал','Процент, %','Фиксировано, ₽','Действие'],d.channel_rates.map(r=>[r.channel,r.commission_percent,r.fixed_fee_rub,btn('Изменить',()=>open('channel_rates',{channel:r.channel,commission:r.commission_percent,fixed_fee:r.fixed_fee_rub}))]));
 rowTable(q('#unit-table'),['Изделие','Канал','Продано за 90 дн.','Цена','Факт. COGS/шт.','Факт. удержания/шт.','Факт. прибыль/шт.','Поступления за период','Материалы','Накладные','Полная себест.','План. поступление','План. прибыль','Цена для цели'],d.unit_economics.map(u=>[u.product,u.channel,u.quantity_90d,u.average_price_rub,u.actual_cogs_per_unit_rub,u.actual_fees_per_unit_rub,u.actual_profit_per_unit_rub,u.actual_receipts_rub,u.planned_material_cost_rub,u.planned_overhead_rub,u.planned_full_cost_rub,u.planned_proceeds_rub,u.planned_profit_rub,u.recommended_price_rub]));
 textStatus('#unit-period',d.unit_period.from+' — '+d.unit_period.to+' · целевая прибыль '+d.target_profit+' ₽. При неизвестных тарифах цена не рассчитывается.');
 charts(q('#summary-chart'),d.monthly.flatMap(m=>[{label:m.month+' выручка',value:m.revenue},{label:m.month+' прибыль',value:m.net_profit}]));
 charts(q('#summary-distribution'),d.distribution.map(x=>({label:({cogs:'Себестоимость',other_expenses:'Прочие расходы',worker_payments:'Выплаты',sale_fees:'Удержания',writeoffs:'Списания',valuation:'Переоценка',depreciation:'Амортизация',asset_disposal:'Выбытие',net_profit:'Прибыль'})[x.key]||x.key,value:x.amount_rub})));
 charts(q('#finance-chart'),d.monthly.flatMap(m=>[{label:m.month+' выручка',value:m.revenue},{label:m.month+' прибыль',value:m.net_profit}]));
 charts(q('#stock-categories'),d.stock_categories.map(c=>({label:c.name,value:c.value_rub})));
 charts(q('#finance-distribution'),d.distribution.map(x=>({label:({cogs:'Себестоимость',other_expenses:'Прочие расходы',worker_payments:'Выплаты',sale_fees:'Удержания',writeoffs:'Списания',valuation:'Переоценка',depreciation:'Амортизация',asset_disposal:'Выбытие',net_profit:'Прибыль'})[x.key]||x.key,value:x.amount_rub})));
 for(const link of qa('a[data-workshop-export]'))link.href=link.dataset.workshopExport+'?workshop='+encodeURIComponent(window.PMWorkshopId);
 const opts=q('#supplier-suggestions');if(opts)opts.replaceChildren(...d.suppliers.map(n=>{const x=el('option');x.value=n;return x;}));
 if(q('#workshop-settings')&&!q('[data-panel="settings"]').hidden)renderWorkshopSettings(false);
}
async function loadSources(){
 const host=q('#sources-list');if(!host)return;
 const d=await api('/api/integrations');host.replaceChildren();
 if(!d.sources.length){host.append(el('p','Нет подключённых магазинов','hint'));return;}
 for(const s of d.sources){
  const card=el('section',null,'settings-card');card.append(el('h3',s.name+' · '+(s.enabled?'подключён':'отключён')));
  card.append(el('p','Ожидают обработки: '+s.pending+' · '+(s.auto_produce?'Недостающие изделия могут выпускаться автоматически':'Только готовый остаток'),'hint'));
  const actions=el('div',null,'button-group');
  const run=async(action,args)=>{try{const r=await post('/api/integrations/change',{action,arguments:{id:s.id,...args}});if(r.apiKey)showKey(r.apiKey);await loadSources();await window.PMAccounting.refresh();}catch(e){textStatus('#source-status',e.message);}};
  actions.append(btn(s.enabled?'Отключить':'Включить',()=>{if(confirm(s.enabled?'Отключить приём заказов?':'Включить приём заказов?'))run(s.enabled?'disable':'enable',{});}),
   btn('Перевыпустить ключ',()=>{if(confirm('Старый ключ перестанет действовать. Продолжить?'))run('rotate',{});}),
   btn('Повторить обработку',()=>run('retry',{})),
   btn(s.auto_produce?'Запретить автовыпуск':'Разрешить автовыпуск',()=>{if(confirm('Изменить политику выпуска для новых и ожидающих заказов?'))run('configure',{auto_produce:!s.auto_produce});}));
  actions.append(btn('Копировать адрес API',async()=>{try{await navigator.clipboard.writeText(location.origin+'/api/hook/order');textStatus('#source-status','Адрес скопирован.');}catch{ textStatus('#source-status',location.origin+'/api/hook/order'); }}));
  card.append(actions,el('h3','Артикулы'));const offerHost=el('div');card.append(offerHost);
  rowTable(offerHost,['Артикул','Название','Цена, ₽','Остаток источника','Изделие'],s.offers.map(o=>{
   const a=el('div',null,'button-group'),sel=el('select');sel.add(new Option('Не привязан',''));
   for(const p of (state?.products||[]).filter(p=>!p.archived))sel.add(new Option(p.name,p.id));sel.value=o.product_id||'';
   a.append(sel,btn('Связать',()=>{if(sel.value)run('map',{offer:o.offer_id,product:sel.value});}));
   if(!o.product_id)a.append(btn('Создать изделие',()=>{if(confirm('Создать изделие «'+o.name+'» из артикула? Рецептуру необходимо заполнить отдельно.'))run('create_product',{offer:o.offer_id,name:o.name});}));
   return [o.offer_id,o.name,o.price,o.external_stock,a];
  }));
  card.append(el('h3','Последние заказы'));const orders=el('div');card.append(orders);
  rowTable(orders,['Номер','Дата','Строк','Статус','Причина'],s.orders.map(o=>[o.order_ref,o.day,o.items,{posted:'Учтён',pending_mapping:'Нужна привязка',pending_stock:'Не проведён'}[o.status]||o.status,o.error]));
  host.append(card);
 }
}
function showKey(key){const box=q('#source-key-box');box.hidden=false;q('#source-key').textContent=key;q('#source-copy').onclick=async()=>{try{await navigator.clipboard.writeText(key);textStatus('#source-status','Ключ скопирован.');}catch{ textStatus('#source-status','Скопируйте ключ вручную.'); }};q('#source-hide').onclick=()=>{box.hidden=true;q('#source-key').textContent='';q('#source-copy').onclick=null;};}
function initMember(){
 initLayout();
 const task=q('#task-filter');if(task)task.onchange=()=>{if(state)render(state);};
 const archived=q('#show-archived');if(archived)archived.onchange=()=>window.PMAccounting.render();
 q('#unit-apply')?.addEventListener('click',()=>window.PMAccounting.refresh().catch(e=>textStatus('#accounting-status',e.message)));
 const quick=q('#period-preset');if(quick)quick.onchange=()=>{
  const today=state?.today;if(!today)return;
  const [y,m,d]=today.split('-').map(Number);
  const fmt=x=>x.getUTCFullYear()+'-'+String(x.getUTCMonth()+1).padStart(2,'0')+'-'+String(x.getUTCDate()).padStart(2,'0');
  let from='',to=today;
  if(quick.value==='month')from=fmt(new Date(Date.UTC(y,m-1,1)));
  if(quick.value==='previous'){from=fmt(new Date(Date.UTC(y,m-2,1)));to=fmt(new Date(Date.UTC(y,m-1,0)));}
  if(quick.value==='quarter')from=fmt(new Date(Date.UTC(y,m-3,1)));
  if(quick.value==='year')from=fmt(new Date(Date.UTC(y,0,1)));
  if(quick.value==='all')to='';
  q('#period-from').value=from;q('#period-to').value=to;q('#event-offset').value='0';window.PMAccounting.refresh().catch(e=>textStatus('#accounting-status',e.message));
 };
 const ws=q('#workshop-settings');if(ws)ws.onsubmit=async e=>{e.preventDefault();const b=ws.querySelector('button');if(b.disabled)return;const args={id:window.PMWorkshopId,...Object.fromEntries(new FormData(ws))};b.disabled=true;textStatus('#workshop-status','Сохраняю…');try{await changeWorkshop('update',args);textStatus('#workshop-status','Настройки сохранены.');}catch(err){textStatus('#workshop-status',err.message);}finally{b.disabled=false;}};
 const create=q('#workshop-create');if(create)create.onsubmit=async e=>{e.preventDefault();try{await changeWorkshop('create',Object.fromEntries(new FormData(create)));}catch(err){textStatus('#workshop-status',err.message);}};
 q('#workshop-demo')?.addEventListener('click',async()=>{try{await changeWorkshop('demo',{});}catch(e){textStatus('#workshop-status',e.message);}});
 const source=q('#source-create');if(source)source.onsubmit=async e=>{e.preventDefault();try{const r=await post('/api/integrations/change',{action:'create',arguments:{name:source.elements.name.value,auto_produce:source.elements.auto_produce.checked}});showKey(r.apiKey);source.reset();await loadSources();}catch(err){textStatus('#source-status',err.message);}};
 const imp=q('#import-form');if(imp)imp.onsubmit=async e=>{
  e.preventDefault();imported=null;importRid=null;q('#import-commit').disabled=true;
  const file=imp.elements.file.files[0];if(!file||file.size>512*1024){textStatus('#import-status','Выберите CSV или XLSX до 512 КБ.');return;}
  const b=imp.querySelector('button');b.disabled=true;
  try{let binary='';const arr=new Uint8Array(await file.arrayBuffer());for(let i=0;i<arr.length;i+=8192)binary+=String.fromCharCode(...arr.subarray(i,i+8192));
   imported=await post('/api/materials/import/preview',{filename:file.name,content:btoa(binary)});importRid=crypto.randomUUID();
   rowTable(q('#import-preview'),['Материал','Единица','Упаковка','Цена, ₽','Остаток','Стоимость, ₽'],imported.rows.map(r=>[r.name,r.unit,r.pack,r.pack_price,r.initial_quantity,r.initial_total]));
   textStatus('#import-status','Проверено '+imported.count+' строк. Подтвердите загрузку.');q('#import-commit').disabled=false;
  }catch(err){textStatus('#import-status',err.message);}finally{b.disabled=false;}
 };
 q('#import-commit')?.addEventListener('click',async()=>{if(!imported)return;const b=q('#import-commit');b.disabled=true;
  try{const r=await post('/api/materials/import/commit',{requestId:importRid,rows:imported.rows,revision:imported.revision});imported=null;importRid=null;q('#import-preview').replaceChildren();textStatus('#import-status','Загружено материалов: '+r.count);await window.PMAccounting.refresh();}
  catch(e){textStatus('#import-status',e.message);b.disabled=false;}});
 const pending=sessionStorage.getItem('pm-calc-pending');
 if(pending&&q('#calc-pending')){q('#calc-pending').hidden=false;q('#calc-accept').onclick=async()=>{try{const v=JSON.parse(pending);await post('/api/calculator/save',v);sessionStorage.removeItem('pm-calc-pending');q('#calc-pending').hidden=true;await window.PMAccounting.refresh();textStatus('#accounting-status','Изделие из калькулятора сохранено.');}catch(e){textStatus('#accounting-status',e.message);}};q('#calc-discard').onclick=()=>{sessionStorage.removeItem('pm-calc-pending');q('#calc-pending').hidden=true;};}
}
function initCalculator(){
 const form=q('#calc-form');if(!form)return;
 initLayout();let calc=null;let saveRid=null;let generation=0;let timer=null;
 const rows=q('#calc-rows');
 function add(values={}){const line=el('div',null,'calc-line');
  for(const [key,label] of [['name','Материал'],['quantity','Количество'],['unit','Единица'],['price','Цена за ед., ₽']]){
   const wrap=el('label',label),input=el(key==='unit'?'select':'input');input.name=key;input.required=true;
   if(key==='unit')for(const u of ['шт','г','кг','мл','л','мм','см','м','см²','дм²','м²','компл'])input.add(new Option(u,u));else if(key!=='name')input.inputMode='decimal';
   input.value=values[key]??(key==='unit'?'шт':'');wrap.append(input);line.append(wrap);
  }
  line.append(btn('×',()=>{line.remove();schedule();},'secondary compact'));rows.append(line);
 }
 function invalidate(){generation++;calc=null;saveRid=null;q('#calc-save').disabled=true;q('#calc-result').replaceChildren();textStatus('#calc-status','');clearTimeout(timer);return generation;}
 function schedule(){invalidate();if(rows.children.length&&form.checkValidity())timer=setTimeout(()=>calculate(),350);}
 add({name:'',quantity:'1',unit:'шт',price:''});
 q('#calc-add').onclick=()=>{if(rows.children.length<50){add();schedule();}};
 form.oninput=schedule;
 form.onsubmit=e=>{e.preventDefault();calculate();};
 async function calculate(){const n=invalidate();if(!rows.children.length){textStatus('#calc-status','Добавьте материал.');return;}try{
  const items=Array.from(rows.children).map(row=>Object.fromEntries(Array.from(row.querySelectorAll('input,select')).map(x=>[x.name,x.value])));
  const a={name:form.elements.product_name.value,items,sale_price:form.elements.sale_price.value,minutes:form.elements.minutes.value,hourly_rate:form.elements.hourly_rate.value};
  const r=await post('/api/calculator',a);if(n!==generation)return;calc=a;saveRid=crypto.randomUUID();
  const h=q('#calc-result');h.replaceChildren();
  rowTable(h,['Показатель','Значение'],[['Материалы',r.materials_rub+' ₽'],['Труд',r.labor_rub+' ₽'],['Полная себестоимость',r.full_cost_rub+' ₽'],['Прибыль до учёта труда',r.material_profit_rub+' ₽'],['Прибыль после учёта труда',r.profit_rub+' ₽'],['Материальная маржа',r.margin_percent==null?'—':r.margin_percent+'%'],['Маржа с трудом',r.full_margin_percent==null?'—':r.full_margin_percent+'%'],['Наценка к полной себестоимости',r.markup_percent==null?'—':r.markup_percent+'%'],['Доход в час до учёта труда',r.income_per_hour_rub==null?'—':r.income_per_hour_rub+' ₽']]);
  q('#calc-save').disabled=false;textStatus('#calc-status','Расчёт выполнен без ИИ.');
 }catch(err){if(n===generation)textStatus('#calc-status',err.message);}}
 q('#calc-save').onclick=()=>{if(!calc)return;sessionStorage.setItem('pm-calc-pending',JSON.stringify({requestId:saveRid,calculation:calc}));location.href='/app/';};
}
window.PMExtras={initWorkshops,initMember,initLayout,initCalculator,render,navigate:navigateExtra,switchTo};
document.addEventListener('DOMContentLoaded',()=>{if(q('#calc-form'))initCalculator();else if(document.body.dataset.mode!=='member')initLayout();});
})();
