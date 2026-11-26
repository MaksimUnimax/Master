'use strict';
(function(){
const q=s=>document.querySelector(s),qa=s=>Array.from(document.querySelectorAll(s));
let data=null, generation=0, confirmed=null, requestId=null, busy=false, activeOp=null, formGeneration=0;
const groupByPage={stock:'stock',purchases:'purchases',manufacture:'manufacture',sales:'sales',expenses:'expenses',journal:'all'};
const moneyLabels={revenue:'Выручка',cogs:'Себестоимость проданного',gross_profit:'Валовая прибыль',net_profit:'Чистая прибыль',
 expenses:'Прочие расходы',writeoffs:'Списания сырья',purchases:'Закупки',receipts:'Получено оплат',production_cash:'Прямые затраты выпуска',cashflow:'Денежный поток',
 raw_inventory_rub:'Сырьё на складе',finished_inventory_rub:'Готовые изделия',inventory_rub:'Стоимость запасов',current_receivables_rub:'Долги покупателей'};
const kindLabels={opening:'Начальный остаток',purchase:'Закупка',manufacture:'Выпуск',sale:'Продажа',payment:'Оплата',return:'Возврат',expense:'Расход',writeoff:'Списание',reverse:'Сторно'};
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
function metricGrid(host,keys,values){
 if(!host)return;host.replaceChildren();const grid=document.createElement('div');grid.className='metric-grid';
 for(const k of keys){const card=document.createElement('div');card.className='metric';card.dataset.metric=k;const a=document.createElement('span');a.textContent=moneyLabels[k]||k;const b=document.createElement('strong');b.textContent=values[k]==null?'—':values[k]+' ₽';card.append(a,b);grid.append(card);}host.append(grid);
}
function setFilter(ui){
 if(ui?.entity){q('#catalog-filter').value=ui.entity;}
 if(ui?.filters){q('#period-from').value=ui.filters.from||'';q('#period-to').value=ui.filters.to||'';q('#event-offset').value='0';}
 if(ui?.highlight){qa('.metric').forEach(e=>e.classList.toggle('highlight',e.dataset.metric===ui.highlight));q('[data-metric="'+ui.highlight.replace(/[^a-z_]/g,'')+'"]')?.scrollIntoView({block:'nearest'});}
}
function query(){
 const p=new URLSearchParams();
 for(const [key,id] of [['start','period-from'],['end','period-to'],['horizon','plan-horizon'],['lead','plan-lead'],['safety','plan-safety'],['offset','event-offset']]){
  const v=q('#'+id)?.value;if(v)p.set(key,v);
 }
 p.set('event_group',groupByPage[q('nav button.active')?.dataset.page]||'all');
 p.set('limit','50');return p;
}
function render(){
 const d=data;if(!d)return;
 metricGrid(q('#summary'),['revenue','gross_profit','net_profit','cashflow','inventory_rub','current_receivables_rub'],d.summary);
 metricGrid(q('#stock-metrics'),['raw_inventory_rub','finished_inventory_rub','inventory_rub'],d.summary);
 metricGrid(q('#finance-metrics'),Object.keys(moneyLabels),d.summary);
 metricGrid(q('#sales-metrics'),['revenue','cogs','gross_profit','receipts','current_receivables_rub'],d.summary);
 metricGrid(q('#purchase-metrics'),['purchases'],d.summary);
 metricGrid(q('#expense-metrics'),['expenses','writeoffs'],d.summary);
 q('#finance-period').textContent='Период: '+(d.period.from==='0001-01-01'?'весь учёт':d.period.from)+' — '+d.period.to+' · валовая маржа '+(d.summary.margin_percent??'—')+'%';
 q('#accounting-assumptions').textContent=d.assumptions;
 const search=(q('#catalog-filter')?.value||'').trim().toLocaleLowerCase('ru');
 const match=x=>!search||[x.name,x.category].some(v=>(v||'').toLocaleLowerCase('ru').includes(search));
 safeTable(q('#materials'),['Материал','Категория','Упаковка','План. цена упаковки, ₽','Действие'],d.materials.filter(match).map(m=>[m.name,m.category,m.pack+' '+m.unit,m.planned_pack_price,
  action('Изменить','material',{entity_id:m.id,name:m.name,unit:m.unit,pack:m.pack,pack_price:m.planned_pack_price,category:m.category})]));
 safeTable(q('#products'),['Изделие','Категория','Рецептура','Текущая стоимость сырья, ₽','Цена продажи, ₽','Действие'],d.products.filter(match).map(p=>[p.name,p.category,p.recipe.map(r=>r.material+' × '+r.usage+' '+r.unit).join('; '),p.estimated_material_cost_rub,p.sale_price,
  action('Изменить','product',{entity_id:p.id,name:p.name,category:p.category,sale_price:p.sale_price,minutes:p.minutes})]));
 safeTable(q('#stock-raw'),['Материал','Категория','Остаток','Средняя цена ед., ₽','Стоимость, ₽','Действие'],d.materials.filter(match).map(m=>[m.name,m.category,(m.valued?m.quantity+' '+m.unit:'Нет учётных движений'),m.average_price_rub,m.value_rub,
  action('Списать','writeoff',{material:m.id})]));
 safeTable(q('#stock-finished'),['Изделие','Категория','Готово, шт.','Стоимость, ₽'],d.products.filter(match).map(p=>[p.name,p.category,p.quantity,p.value_rub]));
 safeTable(q('#production-batches'),['Дата','Изделие','Выпуск, шт.','Стоимость партии, ₽','Остаток, шт.','Остаток, ₽'],d.batches.map(b=>[b.day,b.product,b.initial_quantity,b.initial_value_rub,b.quantity,b.value_rub]));
 safeTable(q('#consumption-period'),['Материал','Эквивалент по продажам','Упаковки'],d.consumption.filter(p=>!search||p.material.toLocaleLowerCase('ru').includes(search)).map(p=>[p.material,p.quantity+' '+p.unit,p.pack_equivalent]));
 const channel=(q('#sales-channel-filter')?.value||'').trim().toLocaleLowerCase('ru');
 const filteredSales=d.sales.filter(s=>!channel||s.channel.toLocaleLowerCase('ru').includes(channel));
 safeTable(q('#sales-current'),['Дата','Изделие','Канал','Продано','Возвращено','Реализация, ₽','Получено, ₽','Долг, ₽','Действия'],filteredSales.map(s=>{
  const a=document.createElement('div');a.className='button-group';if(Number(s.due_rub)>0)a.append(action('Оплата','payment',{sale:s.id}));
  if(s.returned<s.quantity)a.append(action('Возврат','return',{sale:s.id}));return [s.day,s.product,s.channel,s.quantity,s.returned,s.gross_rub,s.paid_rub,s.due_rub,a];
 }));
 for(const host of qa('[data-event-table]')){
  const current=groupByPage[q('nav button.active')?.dataset.page]||'all';
  if(host.dataset.eventTable!==current)continue;
  safeTable(host,['Дата','Операция','Описание','Заметка','Статус','Действие'],d.events.map(e=>[e.day,kindLabels[e.kind]||e.kind,e.summary,e.note,e.reversed?'Сторнирована':e.kind==='reverse'?'Корректировка':'Учтена',
   !e.reversed&&e.kind!=='reverse'?action('Сторно','reverse',{event:e.id}):'—']));
 }
 q('#journal-count').textContent='Показано '+d.events.length+' из '+d.event_count+' записей';
 q('#events-prev').disabled=d.offset===0;q('#events-next').disabled=d.offset+d.limit>=d.event_count;
 safeTable(q('#finance-monthly'),['Месяц','Выручка','COGS','Валовая прибыль','Расходы','Списания','Чистая прибыль','Денежный поток'],d.monthly.map(v=>[v.month,v.revenue,v.cogs,v.gross_profit,v.expenses,v.writeoffs,v.net_profit,v.cashflow]));
 safeTable(q('#finance-products'),['Изделие','Чистые продажи, шт.','Выручка','COGS','Валовая прибыль'],d.by_product.map(v=>[v.name,v.quantity,v.revenue,v.cogs,v.gross_profit]));
 safeTable(q('#finance-channels'),['Канал','Чистые продажи, шт.','Выручка','COGS','Валовая прибыль','Оплаты'],d.by_channel.map(v=>[v.name,v.quantity,v.revenue,v.cogs,v.gross_profit,v.receipts]));
 safeTable(q('#finance-expenses'),['Статья','Расходы, ₽'],d.by_expense.map(v=>[v.name,v.expenses]));
 safeTable(q('#planning'),['Материал','Эквивалент продаж за 30 дней','Средний расход в день','Дней сырья','Купить упаковок','Дата заказа'],d.planning.filter(p=>!search||p.material.toLocaleLowerCase('ru').includes(search)).map(p=>[p.material,p.sold_equivalent_units+' '+p.unit+' / '+p.sold_equivalent_packs+' уп.',p.daily_forecast+' '+p.unit,p.raw_days??'Нет спроса',p.buy_packs,p.order_day??'—']));
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
 if(t==='material')return data.materials.map(x=>[x.id,x.name+' ('+x.unit+')']);
 if(t==='product')return data.products.map(x=>[x.id,x.name]);
 if(t==='sale')return data.sales.map(x=>[x.id,x.day+' · '+x.product+' · '+x.channel+' · '+x.gross_rub+' ₽']);
 if(t==='unit')return data.units.map(x=>[x,x]);
 if(t==='category')return data.expense_categories.map(x=>[x,x]);
 if(t.startsWith('choice:'))return t.slice(7).split(',').map(x=>[x,x==='base'?'Базовые единицы':'Упаковки']);
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
  if(f.type==='date')el.type='date';
  else if(f.type==='bool'){el.type='checkbox';label.classList.add('check');}
  else if(f.type==='int'||f.type==='int0'){el.type='number';el.min=f.type==='int0'?'0':'1';el.max='1000000000000';el.step='1';}
  else{el.type='text';el.maxLength=f.type==='event'?128:240;if(f.type.includes('money'))el.inputMode='decimal';}
 }
 el.name=f.name;el.dataset.fieldType=f.type;
 if(f.type==='bool')el.checked=value===true;else{el.required=f.required;el.value=value??'';}
 label.append(el);return label;
}
function showPreview(p){
 confirmed=p;requestId=crypto.randomUUID();q('#book-preview').textContent=p.preview.summary;
 q('#book-confirm').disabled=false;q('#book-form-status').textContent='Проверьте предварительный расчёт. Запись появится после подтверждения.';
}
function open(op,args={},preview=null){
 if(!data||!data.forms[op]||busy)return;
 const form=q('#book-form'),dialog=q('#book-dialog');activeOp=op;confirmed=null;requestId=null;formGeneration++;
 q('#book-title').textContent=data.forms[op].title;
 q('#book-fields').replaceChildren(...data.forms[op].fields.map(f=>field(f,Object.hasOwn(args,f.name)?args[f.name]:f.default)));
 q('#book-preview').textContent='';q('#book-confirm').disabled=true;q('#book-form-status').textContent='';
 if(preview?.revision&&preview?.preview)showPreview(preview);
 const choice=q('#book-fields [name="entity_id"]');
 if(choice)choice.addEventListener('change',()=>{
  if(!choice.value)return;
  const list=op==='material'?data.materials:data.products;const item=list.find(x=>x.id===choice.value);
  if(!item)return;
  const values=op==='material'?{name:item.name,unit:item.unit,pack:item.pack,pack_price:item.planned_pack_price,category:item.category}:{name:item.name,category:item.category,sale_price:item.sale_price,minutes:item.minutes};
  for(const [key,value] of Object.entries(values))form.elements[key].value=value??'';
 });
 if(!dialog.open)dialog.showModal();
}
function formArgs(){
 const result={};
 for(const el of q('#book-fields').querySelectorAll('input,select')){
  const t=el.dataset.fieldType;
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
 q('#period-clear').onclick=()=>{q('#period-from').value=q('#period-to').value='';q('#event-offset').value='0';refresh().catch(e=>status(e.message));};
 q('#catalog-filter').oninput=render;q('#sales-channel-filter').oninput=render;
 q('#plan-apply').onclick=()=>refresh().catch(e=>status(e.message));
 q('#events-prev').onclick=()=>{q('#event-offset').value=Math.max(0,data.offset-data.limit);refresh().catch(e=>status(e.message));};
 q('#events-next').onclick=()=>{q('#event-offset').value=data.offset+data.limit;refresh().catch(e=>status(e.message));};
 q('#book-close').onclick=()=>{if(!busy)q('#book-dialog').close();};
 q('#book-dialog').addEventListener('cancel',e=>{if(busy)e.preventDefault();});
 q('#book-form').oninput=()=>{formGeneration++;confirmed=null;requestId=null;q('#book-confirm').disabled=true;q('#book-preview').textContent='';};
 q('#book-form').onsubmit=async e=>{
  e.preventDefault();if(busy)return;const n=++formGeneration,op=activeOp;busy=true;
  q('#book-check').disabled=true;q('#book-confirm').disabled=true;
  try{const p=await post('/api/accounting/preview',{operation:op,arguments:formArgs()});if(n===formGeneration)showPreview(p);}
  catch(err){q('#book-form-status').textContent=err.message;}
  finally{busy=false;q('#book-check').disabled=false;}
 };
 q('#book-confirm').onclick=async()=>{
  if(!confirmed||busy)return;busy=true;q('#book-confirm').disabled=true;q('#book-check').disabled=true;
  const inputs=Array.from(q('#book-fields').querySelectorAll('input,select'));inputs.forEach(e=>e.disabled=true);
  try{const r=await post('/api/accounting/commit',{requestId,operation:confirmed.operation,arguments:confirmed.arguments,revision:confirmed.revision});
    confirmed=null;requestId=null;q('#book-dialog').close();status(r.summary);await refresh();}
  catch(err){q('#book-form-status').textContent=err.message;if(confirmed)q('#book-confirm').disabled=false;}
  finally{inputs.forEach(e=>e.disabled=false);busy=false;q('#book-check').disabled=false;}
 };
}
window.PMAccounting={init,refresh,navigate:navigateBook,open,setFilter};
})();
