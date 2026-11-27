'use strict';
(function(){
const q=s=>document.querySelector(s),qa=s=>Array.from(document.querySelectorAll(s));
let data=null, generation=0, confirmed=null, requestId=null, busy=false, activeOp=null, formGeneration=0, correction=null;
const groupByPage={stock:'stock',purchases:'purchases',manufacture:'manufacture',sales:'sales',expenses:'expenses',journal:'all',workers:'workers',assets:'assets'};
const moneyLabels={sale_records:'Записей продаж',sales_quantity:'Продано, шт.',margin_percent:'Валовая маржа, %',valuation:'Переоценка партий',depreciation:'Амортизация',capex:'Капвложения',asset_proceeds:'Поступления от выбытия',asset_disposal:'Расход от выбытия',equipment_book_rub:'Остаточная стоимость оборудования',wip_inventory_rub:'Незавершённое производство',worker_payments:'Выплаты работникам',sale_fees:'Удержания по продажам',other_expenses:'Остальные расходы',revenue:'Выручка',cogs:'Себестоимость проданного',gross_profit:'Валовая прибыль',net_profit:'Чистая прибыль',
 expenses:'Прочие расходы',writeoffs:'Списания сырья',purchases:'Закупки',receipts:'Получено оплат',production_cash:'Прямые затраты выпуска',cashflow:'Денежный поток',
 raw_inventory_rub:'Сырьё на складе',finished_inventory_rub:'Готовые изделия',inventory_rub:'Стоимость запасов',current_receivables_rub:'Долги покупателей'};
const kindLabels={opening:'Начальный остаток',purchase:'Закупка',manufacture:'Выпуск',sale:'Продажа',payment:'Оплата',return:'Возврат',expense:'Расход',worker_payment:'Выплата',writeoff:'Списание',reverse:'Сторно',work_start:'Начало НЗП',work_finish:'Завершение НЗП',component_transfer:'Полуфабрикат в материалы',asset_acquire:'Оборудование',asset_retire:'Выбытие',depreciation:'Амортизация',sale_fee:'Удержание',sale_fee_refund:'Возврат удержания'};
const editable=new Set(['opening','purchase','manufacture','sale','payment','return','expense','worker_payment','writeoff','asset_acquire','asset_retire','work_start','work_finish','component_transfer','sale_fee','sale_fee_refund']);
function safeTable(host,cols,rows){
 if(!host)return;
 host.replaceChildren();
 if(!rows.length){const p=document.createElement('p');p.className='hint';p.textContent='Нет записей';host.append(p);return;}
 const wrap=document.createElement('div');wrap.className='table-scroll';const t=document.createElement('table'),h=t.createTHead().insertRow();
 for(const label of cols){const th=document.createElement('th');th.textContent=label;h.append(th);}
 for(const values of rows){const row=t.createTBody().insertRow();for(const v of values){const cell=row.insertCell();if(v instanceof Node)cell.append(v);else cell.textContent=v??'Не указано';}}
 wrap.append(t);host.append(wrap);
}
function action(label,op,args){const b=document.createElement('button');b.type='button';b.className='secondary compact';b.textContent=label;b.addEventListener('click',()=>open(op,args));return b;}
function button(label,fn){const b=document.createElement('button');b.type='button';b.className='secondary compact';b.textContent=label;b.onclick=fn;return b;}
function check(kind,id){const c=document.createElement('input');c.type='checkbox';c.dataset.catalogKind=kind;c.value=id;c.setAttribute('aria-label','Выбрать объект');return c;}
function bulk(kind){const ids=qa('input[data-catalog-kind="'+kind+'"]:checked').map(c=>c.value);if(!ids.length){status('Сначала выберите объекты.');return;}open('bulk_archive',{entity_kind:kind,entity_ids:ids.join(','),archived:true});}
function catalog(host,cols,rows,view){
 if(view!=='cards'){safeTable(host,cols,rows);return;}
 host.replaceChildren();if(!rows.length){host.textContent='Нет записей';return;}
 const grid=document.createElement('div');grid.className='catalog-cards';
 for(const row of rows){const card=document.createElement('article');card.className='settings-card';
  const title=document.createElement('h3');title.textContent=row[1];card.append(title);
  for(let i=0;i<row.length;i++){if(i===1)continue;const box=document.createElement('div');box.className='catalog-card-row';const label=document.createElement('small');label.textContent=cols[i];box.append(label);const v=row[i];if(v instanceof Node)box.append(v);else{const text=document.createElement('span');text.textContent=v??'—';box.append(text);}card.append(box);}grid.append(card);}
 host.append(grid);
}
function productArgs(p){return {entity_id:p.id,name:p.name,category:p.category,sale_price:p.sale_price,minutes:p.minutes,catalog_note:p.note};}
function eventActions(e){
 if(e.reversed||e.derived||e.external||e.kind==='reverse')return '—';
 const a=document.createElement('div');a.className='button-group';
 if(!['asset_acquire','asset_retire'].includes(e.kind))a.append(action('Сторно','reverse',{event:e.id}));
 if(editable.has(e.kind)){
  const args={...e.arguments};if(e.material_id&&Object.hasOwn(args,'material'))args.material=e.material_id;if(e.product_id&&Object.hasOwn(args,'product'))args.product=e.product_id;
  a.append(button('Изменить',()=>open(e.kind,args,null,{action:'edit',target:e.id})),button('Удалить',()=>open(e.kind,args,null,{action:'delete',target:e.id})));
 }
 if(e.kind==='sale_fee')a.append(action('Вернуть удержание','sale_fee_refund',{event:e.id}));
 return a;
}
function showProduct(id){
 const p=data.products.find(x=>x.id===id);if(!p)return;
 const dialog=q('#product-detail');const host=q('#product-detail-body');host.replaceChildren();q('#product-detail-title').textContent=p.name;
 if(p.has_photo){const img=document.createElement('img');img.className='product-photo';img.alt='Фото изделия';img.src='/api/accounting/photo/'+encodeURIComponent(id)+'?workshop='+encodeURIComponent(window.PMWorkshopId)+'&v='+Date.now();host.append(img);}
 const detail=document.createElement('div');host.append(detail);
 safeTable(detail,['Показатель','Значение'],[['Категория',p.category],['Сырьё, ₽',p.estimated_material_cost_rub],['Труд, ₽',p.planned_labor_rub],['Накладные, ₽',p.planned_overhead_rub],['Полная себестоимость, ₽',p.planned_full_cost_rub],['Плановая цена, ₽',p.sale_price],['Время, мин.',p.minutes],['Маржа материалов, %',p.material_margin_percent],['Заметка',p.note]]);
 const recipe=document.createElement('div');host.append(recipe);safeTable(recipe,['Материал','Расход','Единица'],p.recipe.map(r=>[r.material,r.usage,r.unit]));
 const history=document.createElement('div');host.append(history);safeTable(history,['Версия','Дата','Рецептура'],data.recipe_versions.filter(r=>r.product_id===id).map(r=>[r.id,r.day,r.recipe.map(m=>m.name+' × '+m.usage+' '+m.unit).join('; ')]));
 q('#product-edit').disabled=p.archived;q('#product-recipe').disabled=p.archived;
 q('#product-edit').onclick=()=>{dialog.close();open('product',productArgs(p));};
 q('#product-recipe').onclick=()=>{dialog.close();open('recipe_line',{product:p.id});};
 const form=q('#product-photo-form');form.hidden=p.archived;q('#product-photo-delete').disabled=!p.has_photo;q('#product-photo-status').textContent='';
 const save=async(content)=>{try{await post('/api/accounting/photo/'+encodeURIComponent(id),{content});await refresh();showProduct(id);}catch(e){q('#product-photo-status').textContent=e.message;}};
 form.onsubmit=async e=>{e.preventDefault();const f=form.elements.photo.files[0];if(!f||f.size>512*1024){q('#product-photo-status').textContent='Фото до 512 КБ.';return;}const arr=new Uint8Array(await f.arrayBuffer());let binary='';for(let i=0;i<arr.length;i+=8192)binary+=String.fromCharCode(...arr.subarray(i,i+8192));await save(btoa(binary));};
 q('#product-photo-delete').onclick=()=>{if(confirm('Удалить фото изделия?'))save(null);};
 if(!dialog.open)dialog.showModal();
}
function metricGrid(host,keys,values){
 if(!host)return;host.replaceChildren();const grid=document.createElement('div');grid.className='metric-grid';
 for(const k of keys){const card=document.createElement('div');card.className='metric';card.dataset.metric=k;const a=document.createElement('span');a.textContent=moneyLabels[k]||k;const b=document.createElement('strong');b.textContent=values[k]==null?'—':values[k]+(['sale_records','sales_quantity'].includes(k)?'':k==='margin_percent'?'%':' ₽');card.append(a,b);grid.append(card);}host.append(grid);
}
function setFilter(ui){
 if(ui?.entity){q('#catalog-filter').value=ui.entity;q('#catalog-category').value='';}
 if(ui?.filters){q('#period-from').value=ui.filters.from||'';q('#period-to').value=ui.filters.to||'';q('#event-offset').value='0';q('#period-preset').value=(!ui.filters.from&&!ui.filters.to)?'all':'custom';}
 if(ui?.highlight){qa('.metric').forEach(e=>e.classList.toggle('highlight',e.dataset.metric===ui.highlight));q('[data-panel]:not([hidden]) [data-metric="'+ui.highlight.replace(/[^a-z_]/g,'')+'"]')?.scrollIntoView({block:'nearest'});}
}
function query(){
 const p=new URLSearchParams();
 for(const [key,id] of [['start','period-from'],['end','period-to'],['horizon','plan-horizon'],['lead','plan-lead'],['safety','plan-safety'],['offset','event-offset'],['target_profit','unit-target']]){
  const v=q('#'+id)?.value;if(v)p.set(key,v);
 }
 p.set('event_group',groupByPage[q('nav button.active')?.dataset.page]||'all');
 p.set('limit','50');return p;
}
function render(){
 const d=data;if(!d)return;
 metricGrid(q('#summary'),['revenue','sale_records','sales_quantity','cogs','gross_profit','margin_percent','other_expenses','worker_payments','sale_fees','writeoffs','depreciation','net_profit','purchases','cashflow','inventory_rub','current_receivables_rub'],d.summary);
 metricGrid(q('#stock-metrics'),['raw_inventory_rub','finished_inventory_rub','wip_inventory_rub','inventory_rub'],d.summary);
 metricGrid(q('#finance-metrics'),Object.keys(moneyLabels),d.summary);
 metricGrid(q('#sales-metrics'),['revenue','sale_records','sales_quantity','cogs','gross_profit','sale_fees','receipts','current_receivables_rub'],d.summary);
 metricGrid(q('#purchase-metrics'),['purchases'],d.summary);
 metricGrid(q('#expense-metrics'),['expenses','worker_payments','sale_fees','writeoffs','depreciation'],d.summary);
 metricGrid(q('#assets-metrics'),['capex','depreciation','equipment_book_rub','asset_proceeds','asset_disposal'],d.summary);
 q('#finance-period').textContent='Период: '+(d.period.from==='0001-01-01'?'весь учёт':d.period.from)+' — '+d.period.to+' · валовая маржа '+(d.summary.margin_percent??'—')+'%';
 q('#accounting-assumptions').textContent=d.assumptions;
 const search=(q('#catalog-filter')?.value||'').trim().toLocaleLowerCase('ru');
 const cat=q('#catalog-category');const prev=cat.value;const cats=[...new Set([...d.materials,...d.products].map(x=>x.category).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'ru'));cat.replaceChildren(new Option('Все категории',''),...cats.map(x=>new Option(x,x)));cat.value=cats.includes(prev)?prev:'';
 const match=x=>(q('#show-archived')?.checked||!x.archived)&&(!cat.value||x.category===cat.value)&&(!search||[x.name,x.category].some(v=>(v||'').toLocaleLowerCase('ru').includes(search)));
 catalog(q('#materials'),['Выбор','Материал','Категория','Упаковка','Цена упаковки, ₽','Стартовый остаток','Остаток','Заметка','Действия'],d.materials.filter(match).map(m=>{
  const a=document.createElement('div');a.className='button-group';
  if(!m.archived)a.append(action('Изменить','material',{entity_id:m.id,name:m.name,unit:m.unit,pack:m.pack,pack_price:m.planned_pack_price,category:m.category,catalog_note:m.note}));
  a.append(action(m.archived?'Восстановить':'В архив','material_archive',{material:m.id,archived:!m.archived}));
  return [check('material',m.id),m.name+(m.archived?' · архив':''),m.category,m.pack+' '+m.unit,m.planned_pack_price,m.initial_quantity??'—',m.quantity,m.note,a];
 }),q('#material-view').value);
 catalog(q('#products'),['Выбор','Изделие','Категория','Рецептура','Сырьё, ₽','Труд и накладные, ₽','Полная себестоимость, ₽','Цена, ₽','Маржа материалов, %','Действия'],d.products.filter(match).map(p=>{
  const a=document.createElement('div');a.className='button-group';
  a.append(button('Карточка',()=>showProduct(p.id)));
  if(!p.archived)a.append(action('Изменить','product',productArgs(p)),action('Состав','recipe_line',{product:p.id}));
  a.append(action(p.archived?'Восстановить':'В архив','product_archive',{product:p.id,archived:!p.archived}));
  const costs=(p.planned_labor_rub===null||p.planned_overhead_rub===null)?'—':p.planned_labor_rub+' + '+p.planned_overhead_rub;
  return [check('product',p.id),p.name+(p.archived?' · архив':''),p.category,p.recipe.map(r=>r.material+' × '+r.usage+' '+r.unit).join('; '),p.estimated_material_cost_rub,costs,p.planned_full_cost_rub,p.sale_price,p.material_margin_percent,a];
 }),q('#product-view').value);
 safeTable(q('#stock-raw'),['Материал','Категория','Стартовый остаток','Стартовая цена','Остаток','Средняя цена ед., ₽','Стоимость, ₽','Действие'],d.materials.filter(match).map(m=>[m.name,m.category,m.initial_quantity,m.initial_unit_price_rub,(m.valued?m.quantity+' '+m.unit:'Нет учётных движений'),m.average_price_rub,m.value_rub,
  action('Списать','writeoff',{material:m.id})]));
 safeTable(q('#stock-finished'),['Изделие','Категория','Готово, шт.','Стоимость, ₽'],d.products.filter(match).map(p=>[p.name,p.category,p.quantity,p.value_rub]));
 safeTable(q('#production-batches'),['Дата','Изделие','Тип','Выпуск, шт.','Стоимость партии, ₽','Остаток, шт.','Остаток, ₽'],d.batches.map(b=>[b.day,b.product,b.phase==='wip'?'НЗП':'Готовые',b.initial_quantity,b.initial_value_rub,b.quantity,b.value_rub]));
 safeTable(q('#wip-list'),['Изделие','НЗП, шт.','Стоимость, ₽','Действие'],d.products.filter(p=>p.wip_quantity>0).map(p=>[p.name,p.wip_quantity,p.wip_value_rub,action('Завершить','work_finish',{product:p.id,quantity:p.wip_quantity})]));
 safeTable(q('#assets-list'),['Оборудование','Приобретено','Срок, мес.','Стоимость','Амортизация за период','Остаточная стоимость','Выбытие'],d.assets.map(a=>[a.name,a.acquired,a.months,a.cost_rub,a.period_depreciation_rub,a.book_value_rub,a.retired||action('Выбытие','asset_retire',{asset_id:a.id})]));
 safeTable(q('#correction-history'),['Дата','Тип','Причина','До: прибыль, ₽','После: прибыль, ₽','Результат'],d.corrections.map(c=>[c.day,({edit:'Изменение',delete:'Удаление',insert:'Внесение'})[c.action]||c.action,c.reason,c.result.before.net_profit,c.result.after.net_profit,c.result.summary]));
 safeTable(q('#distribution-table'),['Статья','Сумма, ₽','Доля выручки, %'],d.distribution.map(x=>[moneyLabels[x.key]||x.key,x.amount_rub,x.percent]));
 safeTable(q('#summary-purchases'),['Материал','Купить упаковок','Дата заказа'],d.planning.filter(p=>p.buy_packs>0).map(p=>[p.material,p.buy_packs,p.order_day]));
 const reminderRows=d.reminders.map(t=>[t.name,t.due,t.overdue?'Просрочено':'Срок близко']);
 for(const h of [q('#summary-reminders'),q('#tasks-reminders')])safeTable(h,['Задача','Срок','Статус'],reminderRows);
 const cp=d.cost_policy;q('#cost-policy-info').textContent='Накладные: '+cp.monthly_overhead+' ₽/мес. · амортизация в расчёте: '+cp.monthly_depreciation_rub+' ₽/мес. · на час: '+cp.hourly_overhead_rub+' ₽';
 safeTable(q('#consumption-period'),['Материал','Эквивалент по продажам','Упаковки'],d.consumption.filter(p=>!search||p.material.toLocaleLowerCase('ru').includes(search)).map(p=>[p.material,p.quantity+' '+p.unit,p.pack_equivalent]));
 const channel=(q('#sales-channel-filter')?.value||'').trim().toLocaleLowerCase('ru');
 const filteredSales=d.sales.filter(s=>(!channel||s.channel.toLocaleLowerCase('ru').includes(channel))&&(!cat.value||d.products.find(p=>p.id===s.product_id)?.category===cat.value)&&(!search||s.product.toLocaleLowerCase('ru').includes(search)));
 safeTable(q('#sales-current'),['Дата','Изделие','Канал','Продано','Возвращено','Цена/шт.','Реализация, ₽','COGS, ₽','Удержания, ₽','Прибыль, ₽','Получено после удержаний','Долг, ₽','Действия'],filteredSales.map(s=>{
  const a=document.createElement('div');a.className='button-group';if(Number(s.due_rub)>0)a.append(action('Оплата','payment',{sale:s.id}));
  if(s.returned<s.quantity)a.append(action('Возврат','return',{sale:s.id}));a.append(action('Удержание','sale_fee',{sale:s.id}));return [s.day,s.product,s.channel,s.quantity,s.returned,s.unit_price_rub,s.gross_rub,s.cogs_rub,s.fees_rub,s.profit_rub,s.net_receipts_rub,s.due_rub,a];
 }));
 for(const host of qa('[data-event-table]')){
  const current=groupByPage[q('nav button.active')?.dataset.page]||'all';
  if(host.dataset.eventTable!==current)continue;
  const visibleEvents=d.events.filter(e=>{
   const items=[d.materials.find(m=>m.id===e.material_id),d.products.find(p=>p.id===e.product_id)].filter(Boolean);
   return (!cat.value||items.some(x=>x.category===cat.value))&&(!search||[e.summary,e.note,...items.flatMap(x=>[x.name,x.category])].some(v=>(v||'').toLocaleLowerCase('ru').includes(search)));
  });
  safeTable(host,['Дата','Операция','Описание','Заметка','Статус','Действие'],visibleEvents.map(e=>[e.day,kindLabels[e.kind]||e.kind,e.summary,e.note,e.reversed?'Сторнирована':e.kind==='reverse'?'Корректировка':'Учтена',
   eventActions(e)]));
 }
 q('#journal-count').textContent='Показано '+d.events.length+' из '+d.event_count+' записей';
 q('#events-prev').disabled=d.offset===0;q('#events-next').disabled=d.offset+d.limit>=d.event_count;
 safeTable(q('#finance-monthly'),['Месяц','Выручка','COGS','Валовая прибыль','Прочие','Выплаты','Удержания','Списания','Амортизация','Переоценка','Выбытие','Чистая прибыль','Денежный поток'],d.monthly.map(v=>[v.month,v.revenue,v.cogs,v.gross_profit,v.other_expenses,v.worker_payments,v.sale_fees,v.writeoffs,v.depreciation,v.valuation,v.asset_disposal,v.net_profit,v.cashflow]));
 safeTable(q('#finance-products'),['Изделие','Чистые продажи, шт.','Выручка','COGS','Валовая прибыль','Маржа, %','После удержаний'],[...d.by_product].sort((a,b)=>(Number(b.margin_percent??-Infinity)-Number(a.margin_percent??-Infinity))).map(v=>[v.name,v.quantity,v.revenue,v.cogs,v.gross_profit,v.margin_percent,v.net_profit]));
 safeTable(q('#finance-channels'),['Канал','Чистые продажи, шт.','Выручка','COGS','Валовая прибыль','Удержания','После удержаний','Оплаты'],d.by_channel.map(v=>[v.name,v.quantity,v.revenue,v.cogs,v.gross_profit,v.sale_fees,v.net_profit,v.receipts]));
 safeTable(q('#finance-expenses'),['Статья','Расходы, ₽'],d.by_expense.map(v=>[v.name,v.expenses]));
 safeTable(q('#planning'),['Материал','Эквивалент продаж за 30 дней','Средний расход в день','Дней сырья','Купить упаковок','Дата заказа'],d.planning.filter(p=>!search||p.material.toLocaleLowerCase('ru').includes(search)).map(p=>[p.material,p.sold_equivalent_units+' '+p.unit+' / '+p.sold_equivalent_packs+' уп.',p.daily_forecast+' '+p.unit,p.raw_days??'Нет спроса',p.buy_packs,p.order_day??'—']));
 window.PMExtras?.render(d);
}
async function refresh(ui){
 if(!q('#period-from'))return;
 if(ui?.filters||ui?.entity)setFilter(ui);
 const n=++generation;
 const d=await api('/api/accounting?'+query());
 if(n!==generation)return;
 data=d;render();if(ui?.highlight)setFilter({highlight:ui.highlight});
}
function navigateBook(){
 if(!q('#event-offset'))return;
 q('#event-offset').value='0';
 refresh().catch(e=>status(e.message));
}
function status(text){const s=q('#accounting-status');if(s)s.textContent=text||'';}
function choices(t){
 if(t==='material')return data.materials.filter(x=>!x.archived||(['material_archive','recipe_line'].includes(activeOp)||correction)).map(x=>[x.id,x.name+' ('+x.unit+')'+(x.archived?' · архив':'')]);
 if(t==='product')return data.products.filter(x=>!x.archived||activeOp==='product_archive'||correction).map(x=>[x.id,x.name+(x.archived?' · архив':'')]);
 if(t==='asset')return data.assets.filter(a=>!a.retired||correction).map(a=>[a.id,a.name]);
 if(t==='task')return data.tasks.map(x=>[x.id,x.name]);
 if(t==='worker')return data.workers.filter(x=>!x.archived||activeOp==='worker').map(x=>[x.id,x.name]);
 if(t==='sale')return data.sales.map(x=>[x.id,x.day+' · '+x.product+' · '+x.channel+' · '+x.gross_rub+' ₽']);
 if(t==='unit')return data.units.map(x=>[x,x]);
 if(t==='category')return data.expense_categories.map(x=>[x,x]);
 if(t.startsWith('choice:'))return t.slice(7).split(',').map(x=>[x,({base:'Базовые единицы',pack:'Упаковки',active:'Активна',done:'Выполнена',archived:'Архив'})[x]||x]);
 return null;
}
function field(f,value){
 const label=document.createElement('label');label.textContent=f.label;
 let el,opts=choices(f.type);
 if(opts){
  el=document.createElement('select');const empty=new Option('Выберите…','');el.add(empty);
  for(const [v,l] of opts)el.add(new Option(l,v));
  // A free formulation may use a name instead of an ID. Never guess an inflected or ambiguous name.
  if(value!=null&&!opts.some(x=>x[0]===String(value))&&['material','product'].includes(f.type)){
   const items=f.type==='material'?data.materials:data.products;
   const found=items.filter(x=>x.name.toLocaleLowerCase('ru')===String(value).toLocaleLowerCase('ru'));
   if(found.length===1)value=found[0].id;else if(value){label.textContent+=' (уточните «'+String(value)+'»)';value='';}
  }
 }else{
  el=document.createElement('input');
  if(f.type==='date'||f.type==='future_date')el.type='date';
  else if(f.type==='bool'){el.type='checkbox';label.classList.add('check');}
  else if(f.type==='int'||f.type==='int0'){el.type='number';el.min=f.type==='int0'?'0':'1';el.max='1000000000000';el.step='1';}
  else{el.type='text';el.maxLength=f.type==='identifiers'?2000:f.type==='event'?128:240;if(f.type.includes('money'))el.inputMode='decimal';}
 }
 el.name=f.name;el.dataset.fieldType=f.type;if(f.name==='supplier')el.setAttribute('list','supplier-suggestions');
 if(f.type==='bool')el.checked=value===true;else{el.required=f.required;el.value=value??'';}
 label.append(el);return label;
}
function showPreview(p){
 confirmed=p;requestId=crypto.randomUUID();const v=p.preview;
 q('#book-preview').textContent=v.summary+(p.correction?'\nПрибыль: '+v.before.net_profit+' → '+v.after.net_profit+' ₽\nДенежный поток: '+v.before.cashflow+' → '+v.after.cashflow+' ₽\nЗапасы: '+v.before.inventory_rub+' → '+v.after.inventory_rub+' ₽':'');

 q('#book-confirm').disabled=false;q('#book-form-status').textContent='Проверьте предварительный расчёт. Запись появится после подтверждения.';
}
function open(op,args={},preview=null,edit=null){
 if(!data||!data.forms[op]||busy)return;
 if(preview?.workshop&&preview.workshop!==window.PMWorkshopId){status('Черновик относится к другой мастерской.');return;}
 const form=q('#book-form'),dialog=q('#book-dialog');activeOp=op;correction=edit;confirmed=null;requestId=null;formGeneration++;
 q('#book-title').textContent=(edit?(edit.action==='delete'?'Удалить с пересчётом: ':'Исправить: '):'')+data.forms[op].title;
 q('#book-fields').replaceChildren(...data.forms[op].fields.map(f=>field(f,Object.hasOwn(args,f.name)?args[f.name]:f.default)));
 const hideFields=edit?.action==='delete';q('#book-fields').hidden=!!hideFields;
 for(const f of q('#book-fields').querySelectorAll('input,select'))f.disabled=!!hideFields;
 q('#book-history-options').hidden=!editable.has(op);q('#book-historical-label').hidden=!!edit;
 q('#book-historical').checked=false;q('#book-correction-reason').value=edit?.reason||'';
 q('#book-correction-label').hidden=!edit;q('#book-correction-reason').required=!!edit;
 const catWrap=q('#book-category-wrap');const catSel=q('#book-category');
 const typ=op==='purchase'||op==='opening'||op==='writeoff'?'material':['sale','manufacture','work_start','work_finish'].includes(op)?'product':null;
 catWrap.hidden=!typ||!!edit;catSel.replaceChildren(new Option('Все категории',''));
 if(typ){const items=typ==='material'?data.materials:data.products;for(const c of [...new Set(items.map(x=>x.category).filter(Boolean))].sort())catSel.add(new Option(c,c));catSel.onchange=()=>{const sel=q('#book-fields [name="'+typ+'"]');if(!sel)return;const prev=sel.value;sel.replaceChildren(new Option('Выберите…',''));for(const item of items.filter(x=>!x.archived&&(!catSel.value||x.category===catSel.value)))sel.add(new Option(item.name,item.id));sel.value=prev;};}

 q('#book-preview').textContent='';q('#book-confirm').disabled=true;q('#book-form-status').textContent='';
 q('#book-assist').hidden=!!edit;
 if(preview?.revision&&preview?.preview)showPreview(preview);
 else if(preview?.missing?.length)q('#book-form-status').textContent='Уточните: '+preview.missing.join(', ');
 else if(preview?.validationError)q('#book-form-status').textContent=preview.validationError;
 const choice=q('#book-fields [name="entity_id"]');
 if(choice)choice.addEventListener('change',()=>{
  if(!choice.value)return;
  const list=op==='material'?data.materials:data.products;const item=list.find(x=>x.id===choice.value);
  if(!item)return;
  const values=op==='material'?{name:item.name,unit:item.unit,pack:item.pack,pack_price:item.planned_pack_price,category:item.category,catalog_note:item.note}:{name:item.name,category:item.category,sale_price:item.sale_price,minutes:item.minutes,catalog_note:item.note};
  for(const [key,value] of Object.entries(values))form.elements[key].value=value??'';
 });
 for(const [key,items,fields] of [['task_id',data.tasks,['name','description','due','priority','remind_days']],['worker_id',data.workers,['name','position','archived']]]){
  const select=q('#book-fields [name="'+key+'"]');
  if(select&&((op==='task'&&key==='task_id')||(op==='worker'&&key==='worker_id')))select.addEventListener('change',()=>{
   const item=items.find(x=>x.id===select.value);if(!item)return;
   for(const field of fields){const e=form.elements[field];if(!e)continue;if(e.type==='checkbox')e.checked=!!item[field];else e.value=item[field]??'';}
   if(op==='task')form.elements.task_category.value=item.category;
  });
 }
 if(!dialog.open)dialog.showModal();
}
function formArgs(){
 const result={};
 for(const el of q('#book-fields').querySelectorAll('input,select')){
  if(el.disabled)continue;const t=el.dataset.fieldType;
  if(t==='bool')result[el.name]=el.checked;
  else if(t==='int'||t==='int0'){if(el.value!=='')result[el.name]=Number(el.value);}
  else if(el.value!=='')result[el.name]=el.value;
 }
 return result;
}
function init(){
 if(!q('#book-dialog'))return;
 for(const b of qa('[data-book-op]'))b.onclick=()=>open(b.dataset.bookOp);
 q('#period-apply').onclick=()=>{q('#event-offset').value='0';refresh().catch(e=>status(e.message));};
 q('#period-clear').onclick=()=>{q('#period-from').value=q('#period-to').value='';q('#period-preset').value='all';q('#event-offset').value='0';refresh().catch(e=>status(e.message));};
 q('#catalog-filter').oninput=render;q('#sales-channel-filter').oninput=render;q('#catalog-category').onchange=render;
 for(const kind of ['product','material']){const select=q('#'+kind+'-view');select.value=localStorage.getItem('pm-'+kind+'-view')==='cards'?'cards':'list';select.onchange=()=>{localStorage.setItem('pm-'+kind+'-view',select.value);render();};}
 q('#bulk-products').onclick=()=>bulk('product');q('#bulk-materials').onclick=()=>bulk('material');
 q('#cost-policy-open').onclick=()=>open('cost_policy',data.cost_policy);
 q('#book-historical').onchange=()=>{const v=q('#book-historical').checked;q('#book-correction-label').hidden=!v;q('#book-correction-reason').required=v;};
 q('#product-detail-close').onclick=()=>q('#product-detail').close();

 q('#plan-apply').onclick=()=>refresh().catch(e=>status(e.message));
 q('#events-prev').onclick=()=>{q('#event-offset').value=Math.max(0,data.offset-data.limit);refresh().catch(e=>status(e.message));};
 q('#events-next').onclick=()=>{q('#event-offset').value=data.offset+data.limit;refresh().catch(e=>status(e.message));};
 q('#book-close').onclick=()=>{if(!busy)q('#book-dialog').close();};
 q('#book-assist').onclick=()=>{
  if(busy||correction||q('#book-historical').checked){q('#book-form-status').textContent='Историческую корректировку подтвердите вручную.';return;}
  window.PMAgent.begin('book.'+activeOp,formArgs());q('#book-dialog').close();
 };
 q('#book-dialog').addEventListener('cancel',e=>{if(busy)e.preventDefault();});
 q('#book-form').oninput=()=>{formGeneration++;confirmed=null;requestId=null;q('#book-confirm').disabled=true;q('#book-preview').textContent='';};
 q('#book-form').onsubmit=async e=>{
  e.preventDefault();if(busy)return;const n=++formGeneration,op=activeOp;busy=true;
  q('#book-check').disabled=true;q('#book-confirm').disabled=true;
  try{
    const edit=correction||(q('#book-historical').checked?{action:'insert',target:''}:null);
    const p=edit?await post('/api/accounting/correction/preview',{correction:{action:edit.action,target:edit.target,operation:op,arguments:edit.action==='delete'?{}:formArgs(),reason:q('#book-correction-reason').value}}):await post('/api/accounting/preview',{operation:op,arguments:formArgs()});
    if(n===formGeneration)showPreview(p);}

  catch(err){q('#book-form-status').textContent=err.message;}
  finally{busy=false;q('#book-check').disabled=false;}
 };
 q('#book-confirm').onclick=async()=>{
  if(!confirmed||busy)return;busy=true;q('#book-confirm').disabled=true;q('#book-check').disabled=true;
  const inputs=Array.from(q('#book-fields').querySelectorAll('input,select')).filter(e=>!e.disabled);inputs.forEach(e=>e.disabled=true);
  try{const r=confirmed.agentConfirmation?await window.PMAgent.confirm(confirmed.agentConfirmation.id):confirmed.correction?await post('/api/accounting/correction/commit',{requestId,correction:confirmed.correction,revision:confirmed.revision}):await post('/api/accounting/commit',{requestId,operation:confirmed.operation,arguments:confirmed.arguments,revision:confirmed.revision});
    confirmed=null;requestId=null;q('#book-dialog').close();status(r.summary||r.text);await refresh();}
  catch(err){q('#book-form-status').textContent=err.message;if(confirmed)q('#book-confirm').disabled=false;}
  finally{inputs.forEach(e=>e.disabled=false);busy=false;q('#book-check').disabled=false;}
 };
}
window.PMAccounting={init,refresh,navigate:navigateBook,open,setFilter,render};
})();
