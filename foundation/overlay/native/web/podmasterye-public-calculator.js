/* One mounted public calculator; the server is the only arithmetic authority. */
'use strict';
(()=>{
 const KEYS={calculator:'pm-public-cost-draft-v1',profit:'pm-public-profit-draft-v1'};
 const FIELDS={calculator:['product_name','sale_price','minutes','hourly_rate'],profit:['revenue','cost','expenses']};
 const q=s=>document.querySelector(s),memory={};let current=null;
 const el=(tag,value)=>{const e=document.createElement(tag);if(value!==undefined)e.textContent=value;return e;};
 function load(panel){
  if(memory[panel])return memory[panel];
  try{const v=JSON.parse(sessionStorage.getItem(KEYS[panel])||'null');if(v&&typeof v==='object')return v;}catch{}
  return null;
 }
 function store(panel,v){memory[panel]=v;try{sessionStorage.setItem(KEYS[panel],JSON.stringify(v));}catch{}}
 function rememberSave(calculation,id){try{sessionStorage.setItem('pm-calc-pending',JSON.stringify({requestId:id,calculation}));return true;}catch{return false;}}
 function makeTable(host,rows){
  const table=el('table'),thead=el('thead'),tr=el('tr');
  tr.append(el('th','Показатель'),el('th','Значение'));thead.append(tr);table.append(thead);
  const tbody=el('tbody');
  for(const [k,v,suffix] of rows){const r=el('tr');r.append(el('td',k),el('td',v==null?'—':v+suffix));tbody.append(r);}
  table.append(tbody);host.replaceChildren(table);
 }
 function mount({openPanel,api}){
  current?.dispose();current=null;
  const root=q('[data-calculator]');if(!root)return;
  const panel=root.dataset.calculator,form=root.querySelector('#calc-form'),rows=root.querySelector('#calc-rows'),result=root.querySelector('#calc-result'),status=root.querySelector('#calc-status'),save=root.querySelector('#calc-save');
  if(!FIELDS[panel]||!form||!result||!status)return;
  let active=true,timer=null,request=null,generation=0,calculation=null,saveRid=null;
  const controls=FIELDS[panel];
  function values(){
   const a=Object.fromEntries(controls.map(k=>[k,form.elements[k].value]));
   if(panel==='calculator'){
    a.name=a.product_name;delete a.product_name;
    a.items=[...rows.children].map(row=>Object.fromEntries([...row.querySelectorAll('input,select')].map(x=>[x.name,x.value])));
   }
   return a;
  }
  function persist(){store(panel,values());}
  function add(v={}){
   if(!rows||rows.children.length>=50)return null;
   const node=root.querySelector('#calc-row-template').content.firstElementChild.cloneNode(true);
   for(const field of node.querySelectorAll('input,select'))if(typeof v[field.name]==='string')field.value=v[field.name];
   node.querySelector('[data-remove-material]').onclick=()=>{node.remove();schedule();};
   rows.append(node);return node;
  }
  function invalidate(){
   generation++;clearTimeout(timer);request?.abort();request=null;calculation=null;saveRid=null;
   if(save)save.disabled=true;
   result.replaceChildren();status.textContent='';return generation;
  }
  function schedule(){
   invalidate();persist();
   if((!rows||rows.children.length)&&form.checkValidity())timer=setTimeout(calculate,280);
  }
  function restore(){
   const v=load(panel);
   if(v){
    for(const k of controls){const value=k==='product_name'?v.name:v[k];if(typeof value==='string')form.elements[k].value=value;}
    if(rows&&Array.isArray(v.items))for(const item of v.items.slice(0,50))if(item&&typeof item==='object')add(item);
   }
   if(rows&&!rows.children.length)add();
   schedule();
  }
  async function calculate(){
   if(!active)return false;
   const n=invalidate(),a=values();persist();
   if(rows&&!rows.children.length){status.textContent='Добавьте материал.';return false;}
   if(!form.checkValidity()){status.textContent='Заполните обязательные поля калькулятора.';return false;}
   const c=new AbortController();request=c;status.textContent='Выполняем расчёт…';
   try{
    const r=await api(panel==='profit'?'/api/calculator/profit':'/api/calculator',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(a),signal:c.signal});
    if(!active||n!==generation||c.signal.aborted)return false;
    if(panel==='calculator'){
     makeTable(result,[['Материалы',r.materials_rub,' ₽'],['Труд',r.labor_rub,' ₽'],['Полная себестоимость',r.full_cost_rub,' ₽'],['Прибыль до учёта труда',r.material_profit_rub,' ₽'],['Прибыль после учёта труда',r.profit_rub,' ₽'],['Материальная маржа',r.margin_percent,'%'],['Маржа с трудом',r.full_margin_percent,'%'],['Наценка к полной себестоимости',r.markup_percent,'%'],['Доход в час до учёта труда',r.income_per_hour_rub,' ₽']]);
     calculation=a;saveRid=crypto.randomUUID();save.disabled=false;
    }else{
     makeTable(result,[['Валовая прибыль',r.gross_profit_rub,' ₽'],['Общие затраты',r.total_cost_rub,' ₽'],['Прибыль по введённым данным',r.profit_rub,' ₽'],['Маржа',r.margin_percent,'%'],['Рентабельность затрат',r.return_on_cost_percent,'%']]);
    }
    status.textContent='Расчёт выполнен без ИИ. Монеты не расходуются.';return true;
   }catch(e){
    if(active&&n===generation&&!c.signal.aborted)status.textContent=e.message;
    return false;
   }
  }
  function transfer(){
   if(!calculation||!saveRid)return false;
   if(!rememberSave(calculation,saveRid)){status.textContent='Не удалось сохранить черновик в браузере.';return false;}
   return true;
  }
  if(save)save.onclick=()=>{
   if(!transfer())return;
   if(document.querySelector('#public-chat-pane'))void openPanel('login');
   else location.assign('/app/');
  };
  // Registration CTA preserves the valid calculation for explicit account-side confirmation.
  root.addEventListener('click',e=>{
   const a=e.target.closest('a[data-public-panel="register"]');
   if(a&&calculation)transfer();
  });
  root.querySelector('#calc-add')?.addEventListener('click',()=>{if(add())schedule();else status.textContent='До 50 материалов в одном расчёте.';});
  form.oninput=schedule;
  form.onsubmit=e=>{e.preventDefault();void calculate();};
  restore();
  current={
   panel,
   dispose(){active=false;clearTimeout(timer);request?.abort();persist();},
   async apply(a){
    if(!active||!a||a.panel!==panel)return false;
    if(a.action==='open')return true;
    if(a.action==='help'){const guide=root.querySelector('#calc-guide');guide.querySelector('.pm-calc-commands').open=true;guide.scrollIntoView({block:'start'});return true;}
    if(a.action==='set'&&controls.includes(a.field)&&typeof a.value==='string'){
     form.elements[a.field].value=a.value;schedule();form.elements[a.field].scrollIntoView({block:'nearest'});return true;
    }
    if(panel==='calculator'&&a.action==='material'&&a.item&&['name','unit','quantity','price','pack_quantity'].every(k=>typeof a.item[k]==='string')){
     const key=a.item.name.trim().toLocaleLowerCase('ru-RU');
     const candidates=[...rows.children].filter(x=>x.querySelector('[name=name]').value.trim().toLocaleLowerCase('ru-RU')===key);
     if(candidates.length>1){status.textContent='Есть несколько строк с этим названием. Объедините их вручную.';return false;}
     let node=candidates[0]||[...rows.children].find(x=>!x.querySelector('[name=name]').value&&!x.querySelector('[name=price]').value);
     if(!node)node=add(a.item);
     if(!node){status.textContent='До 50 материалов в одном расчёте.';return false;}
     for(const field of node.querySelectorAll('input,select'))field.value=a.item[field.name];
     schedule();node.scrollIntoView({block:'nearest'});return true;
    }
    if(panel==='calculator'&&a.action==='remove'&&typeof a.name==='string'){
     const matches=[...rows.children].filter(x=>x.querySelector('[name=name]').value.trim().toLocaleLowerCase('ru-RU')===a.name.trim().toLocaleLowerCase('ru-RU'));
     if(matches.length!==1){status.textContent=matches.length?'Несколько строк с таким названием. Удалите нужную вручную.':'Материал не найден в калькуляторе.';return false;}
     matches[0].remove();schedule();return true;
    }
    if(a.action==='calculate'){const ok=await calculate();(ok?result:status).scrollIntoView({block:'nearest'});return ok;}
    return false;
   }
  };
 }
 window.PMPublicCalculator={mount,unmount(){current?.dispose();current=null;},apply(a){return current?.apply(a)??false;}};
})();
