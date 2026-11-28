'use strict';
// Compatibility entry point for account/admin navigation; marketplace content is
// the same component used inline in chat. Collection never runs in a browser.
(()=>{
const q=s=>document.querySelector(s);
async function load(){const host=q('#market-list');if(!host||!window.PMMarketUI)return;window.PMMarketUI.workspace(host,{w:window.PMWorkshopId});}
function configView(d){
 q('#tg-config-status').textContent=d.configured?'Бот настроен.':'Бот не настроен.';
 q('#tg-config-details').hidden=!d.configured;
 q('#tg-config-bot').textContent=d.bot_username?'@'+d.bot_username:d.bot_id?'ID '+d.bot_id:'—';
 q('#tg-config-token').textContent=d.token_saved?'Сохранён (скрыт)':'Не добавлен';
 q('#tg-config-mode').textContent=d.auth_mode==='oidc'?'Telegram Login OIDC':'Telegram Login Widget';
 q('#tg-config-binding').textContent=d.linked?'Подключён, доставка подтверждена':'Не подключён';
 q('#tg-config-address').textContent='Домен: '+d.origin+' · Адрес возврата: '+d.callback;
 q('#tg-config-edit').textContent=d.configured?'Изменить настройки бота':'Настроить бота';
 const f=q('#tg-config-form');
 f.elements.auth_mode.value=d.auth_mode;
 f.elements.bot_username.value=d.bot_username?'@'+d.bot_username:'';
 f.elements.bot_token.placeholder=d.token_saved?'Введите новый токен':'';
 f.elements.auth_mode.dispatchEvent(new Event('change'));
 q('#tg-config-editor').open=!d.configured;
 q('#tg-config-error').textContent='';
}
async function loadConfig(){if(!q('#tg-config-form'))return;try{configView(await api('/api/admin/podmasterye/telegram-config'));}catch(e){q('#tg-config-error').textContent=e.message;}}
function init(){
 const f=q('#tg-config-form');if(f){
  const mode=f.elements.auth_mode;
  function controls(){const widget=mode.value==='widget';f.elements.bot_username.closest('label').hidden=!widget;f.elements.client_secret.closest('label').hidden=widget;f.elements.bot_username.required=widget;f.elements.client_secret.required=!widget;}
  mode.onchange=controls;controls();
  f.onsubmit=async e=>{e.preventDefault();const b=f.querySelector('button');b.disabled=true;
   try{const a={auth_mode:mode.value,bot_token:f.elements.bot_token.value};if(mode.value==='widget')a.bot_username=f.elements.bot_username.value;else a.client_secret=f.elements.client_secret.value;const saved=await post('/api/admin/podmasterye/telegram-config',a);f.reset();configView(saved);}
   catch(err){q('#tg-config-error').textContent=err.message;}finally{b.disabled=false;}
  };
 }
}
window.PMMarket={load,loadConfig};
init();
})();
