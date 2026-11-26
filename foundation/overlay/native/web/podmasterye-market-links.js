'use strict';
(()=>{
const defs={
 ozon:{title:'Ozon',fields:[['client_id','Client-Id продавца'],['api_key','Api-Key продавца'],['performance_id','Client ID Performance'],['performance_secret','Client Secret Performance']]},
 wb:{title:'Wildberries',fields:[['token','API-токен WB']]}
};
const q=s=>document.querySelector(s),el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
function button(text,fn){const b=el('button',text,'secondary');b.type='button';b.onclick=fn;return b;}
function fields(host,p){host.replaceChildren();for(const [key,label] of defs[p].fields){
 const l=el('label',label),i=el('input');i.name=key;i.type='password';i.autocomplete='new-password';i.maxLength=8192;l.append(i);host.append(l);
 }
 host.append(el('p',p==='ozon'?'Seller API — полная пара Client-Id и Api-Key. Performance API — отдельная пара Client ID и Client Secret. Можно добавить одну пару, затем вторую.':'Для заказов и продаж нужен токен с доступом к статистике; для рекламы — к продвижению.','hint'));
}
function values(form,p){return Object.fromEntries(defs[p].fields.map(([key])=>[key,form.elements[key]?.value.trim()||'']).filter(x=>x[1]));}
const statusNames={saved:'Ключи сохранены, связь не проверена',verified:'Связь подтверждена',partial:'Подтверждена часть доступов',unconfirmed:'Связь не подтверждена'};
const checkNames={verified:'Подтверждён',denied:'Отказ в доступе',unconfirmed:'Не подтверждён'};
let busy=false;
async function action(fn,message){
 if(busy)return;busy=true;const status=q('#market-status');
 try{await fn();await load();status.textContent=message;}catch(e){status.textContent=e.message;}finally{busy=false;}
}
function card(c){
 const box=el('section',null,'settings-card');box.append(el('h3',c.name+' · '+defs[c.provider].title),el('p',statusNames[c.status]||c.status,'hint'));
 if(c.checked)box.append(el('p','Проверено: '+new Date(c.checked*1000).toLocaleString('ru-RU'),'hint'));
 for(const [k,v] of Object.entries(c.checks))box.append(el('p',k+': '+(checkNames[v]||v)));
 const configured=new Set(c.configuredFields);
 box.append(el('p',defs[c.provider].fields.map(([k,t])=>t+': '+(configured.has(k)?'сохранён':'не указан')).join(' · '),'hint'));
 const controls=el('div',null,'button-group'),url='/api/integrations/marketplaces/'+encodeURIComponent(c.id);
 controls.append(button('Проверить связь',()=>action(()=>post(url+'/check',{}),'Проверка завершена. Смотрите статусы доступов.')));
 const edit=el('form',null,'panel');edit.hidden=true;
 const fh=el('div',null,'fields');fields(fh,c.provider);edit.append(fh,el('p','Пустые поля сохраняют прежние значения. Для Ozon указывайте целиком заменяемую пару.','hint'));
 const save=el('button','Сохранить новые ключи');save.type='submit';edit.append(save,button('Отмена',()=>{edit.reset();edit.hidden=true;}));
 edit.onsubmit=e=>{e.preventDefault();action(()=>post(url+'/keys',{version:c.version,fields:values(edit,c.provider)}),'Новые ключи сохранены. Повторите проверку.');};
 controls.append(button('Изменить ключи',()=>{edit.hidden=!edit.hidden;if(edit.hidden)edit.reset();}),button('Удалить',()=>{if(confirm('Удалить подключение «'+c.name+'» из этой мастерской?'))action(()=>post(url+'/remove',{version:c.version}),'Подключение удалено.');}));
 box.append(controls,edit);return box;
}
async function load(){const host=q('#market-list');if(!host)return;
 try{const d=await api('/api/integrations/marketplaces');host.replaceChildren(...d.connections.map(card));if(!d.connections.length)host.append(el('p','Нет подключённых маркетплейсов.','hint'));}
 catch(e){q('#market-status').textContent=e.message;}
}
function configView(d){q('#tg-config-status').textContent=(d.configured?'Настройки бота сохранены.':'Бот не настроен.')+' Домен: '+d.origin+' · адрес возврата: '+d.callback;}
async function loadConfig(){if(!q('#tg-config-form'))return;try{configView(await api('/api/admin/podmasterye/telegram-config'));}catch(e){q('#tg-config-status').textContent=e.message;}}
function init(){
 const form=q('#market-add');
 if(form){
  const provider=form.elements.provider,host=q('#market-key-fields');
  fields(host,provider.value);provider.onchange=()=>fields(host,provider.value);
  form.onsubmit=e=>{e.preventDefault();action(async()=>{await post('/api/integrations/marketplaces',{provider:provider.value,name:form.elements.name.value,fields:values(form,provider.value)});form.reset();fields(host,provider.value);},'Ключи сохранены. Нажмите «Проверить связь».');};
 }
 const f=q('#tg-config-form');if(f){
  const mode=f.elements.auth_mode;
  function controls(){const widget=mode.value==='widget';f.elements.bot_username.closest('label').hidden=!widget;f.elements.client_secret.closest('label').hidden=widget;f.elements.bot_username.required=widget;f.elements.client_secret.required=!widget;}
  mode.onchange=controls;controls();
  f.onsubmit=async e=>{e.preventDefault();const b=f.querySelector('button');b.disabled=true;
   try{const a={auth_mode:mode.value,bot_token:f.elements.bot_token.value};if(mode.value==='widget')a.bot_username=f.elements.bot_username.value;else a.client_secret=f.elements.client_secret.value;configView(await post('/api/admin/podmasterye/telegram-config',a));f.reset();controls();}
   catch(err){q('#tg-config-status').textContent=err.message;}finally{b.disabled=false;}
  };
 }
}
window.PMMarket={load,loadConfig};
init();
})();
