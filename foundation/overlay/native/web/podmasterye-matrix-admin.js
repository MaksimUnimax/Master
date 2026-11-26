'use strict';
(()=>{
const q=s=>document.querySelector(s),el=(tag,text)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;return n;};
let entries=[];
function fill(){
 const f=q('#matrix-edit-form'),r=entries.find(x=>x.id===f.elements.id.value);
 if(!r)return;
 q('#matrix-base').textContent='Тип: '+r.intent+' · '+(r.op||r.view||r.page||'')+' · версия '+r.revision+'\nБазовые фразы: '+r.baseAliases.join(' | ');
 f.elements.aliases.value=r.aliases.join('\n');f.elements.negatives.value=r.negatives.join('\n');
}
async function load(){
 if(!q('#matrix-edit-form'))return;
 try{
 const [m,s]=await Promise.all([api('/api/admin/matrix'),api('/api/admin/matrix/stats')]);
 entries=m.rows;
 const f=q('#matrix-edit-form'),select=f.elements.id,old=select.value;
 select.replaceChildren(...entries.map(r=>new Option(r.id+' · '+(r.baseAliases[0]||r.intent),r.id)));
 if(entries.some(r=>r.id===old))select.value=old;
 fill();
 q('#matrix-status').textContent='Версия '+m.version+' · '+entries.length+' записей';
 const fmt=v=>v??'Нет данных';
 table(q('#matrix-stats'),['Показатель','Значение'],[
 ['Запросов после обновления',s.turns],['Локальных',s.local],['Маршрутов к модели',s.model],['Без LLM, %',fmt(s.zeroLlmPercent)],['Реальных вызовов модели',s.calls],['Входные токены',s.input],['Из кэша',s.cache],['Выходные токены',s.output],['Неподтверждённых',s.pending],['Задержка p50/p95, мс',fmt(s.latencyMs.p50)+' / '+fmt(s.latencyMs.p95)],['Расход p50/p95, ₽',fmt(s.costRub.p50)+' / '+fmt(s.costRub.p95)],['Семейства схем',s.prefixFamilies],['Старые запросы вне статистики',s.legacyTurns]]);
 table(q('#matrix-reasons'),['Маршрут / причина','Запросов'],Object.entries(s.reasons));
 table(q('#matrix-hits'),['Шаблон','Срабатываний'],Object.entries(s.hits).sort((a,b)=>b[1]-a[1]).slice(0,30));
 }catch(e){q('#matrix-status').textContent=e.message;}
}
function init(){
 const f=q('#matrix-edit-form');if(!f)return;
 q('#matrix-refresh').onclick=load;f.elements.id.onchange=fill;
 f.onsubmit=async e=>{e.preventDefault();const r=entries.find(x=>x.id===f.elements.id.value);if(!r)return;
 const b=f.querySelector('button[type=submit]');b.disabled=true;
 const lines=k=>f.elements[k].value.split('\n').map(x=>x.trim()).filter(Boolean);
 try{await post('/api/admin/matrix/'+encodeURIComponent(r.id),{revision:r.revision,aliases:lines('aliases'),negatives:lines('negatives')});await load();q('#matrix-status').textContent+=' · изменения сохранены';}
 catch(err){q('#matrix-status').textContent=err.message;}finally{b.disabled=false;}
 };
 q('#matrix-reset').onclick=()=>{f.elements.aliases.value='';f.elements.negatives.value='';};
}
window.PMMatrix={load};init();
})();
