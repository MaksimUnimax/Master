(()=>{'use strict';
  const label={deepseek:'DeepSeek',openrouter:'OpenRouter'},efforts={auto:'Автоматически',off:'Без рассуждений',low:'Низкие',medium:'Средние',high:'Высокие',max:'Максимальные'};
  const json=async(url,data)=>{
    const options={credentials:'same-origin',headers:{Accept:'application/json'}};
    if(data!==undefined){options.method='POST';options.headers['Content-Type']='application/json';options.body=JSON.stringify(data);}
    const response=await fetch(url,options);let value={};try{value=await response.json();}catch{}
    if(!response.ok)throw Error(value.error||value.detail||'Запрос не выполнен (HTTP '+response.status+').');return value;
  };
  const find=(host,id)=>host.querySelector('[data-ai="'+id+'"]');
  const text=(host,id,value)=>{const target=find(host,id);if(target)target.textContent=value||'';};
  function action(host,node,run){if(!node)return;node.addEventListener(node.tagName==='FORM'?'submit':'click',async event=>{
    event.preventDefault();if(node.dataset.busy==='1')return;node.dataset.busy='1';node.setAttribute('aria-busy','true');
    const buttons=node.tagName==='FORM'?[...node.querySelectorAll('button')]:[node];const states=buttons.map(b=>b.disabled);buttons.forEach(b=>b.disabled=true);text(host,'status','');
    try{await run(node);}catch(error){text(host,'status',error.message);}finally{node.dataset.busy='0';node.removeAttribute('aria-busy');buttons.forEach((b,i)=>b.disabled=states[i]);}
  });}
  const options=(select,rows,value)=>{select.replaceChildren(...rows.map(([id,title])=>new Option(title,id)));if([...select.options].some(o=>o.value===value))select.value=value;};
  function user(host){
    if(host.dataset.ready)return;host.dataset.ready='1';let style,models,images;
    const styleForm=find(host,'preferences'),modelForm=find(host,'model'),imageForm=find(host,'image-model');
    function displayStyle(value){style=value;for(const key of ['address','tone','detail'])options(styleForm.elements[key],value.options[key].map(x=>[x,x]),value.current[key]);}
    function filterModels(){if(!models)return;const needle=modelForm.elements.search.value.toLocaleLowerCase(),price=modelForm.elements.price.value;
      const list=models.models.filter(m=>m.chat&&(!needle||(m.name+' '+m.family+' '+m.id).toLocaleLowerCase().includes(needle))&&(price==='all'||(price==='free')===m.free));
      options(modelForm.elements.model,[['default','По настройке администратора'],...(models.directAvailable===false?[]:[['direct','DeepSeek · прямой маршрут']]),...list.map(m=>[m.id,m.name+' · '+(m.free?'бесплатно':'платно')])],models.inherited?'default':models.model);
    }
    async function loadModels(refresh=false){models=await json('/api/model-settings'+(refresh?'?refresh=1':''));filterModels();
      text(host,'model-current',models.inherited?'Используется общая модель.':'Выбрано: '+models.model);
      text(host,'model-notice',[models.catalogMessage,models.choiceMessage,!models.enabled?'OpenRouter сейчас недоступен.':''].filter(Boolean).join(' '));
    }
    async function loadImages(){images=await json('/api/assistant/illustrations/settings');options(imageForm.elements.model,[['','Генератор не выбран'],...images.models.map(m=>[m.id,m.name+' · '+(m.free?'бесплатно':'платно')])],images.current.model);
      text(host,'image-notice',images.message||(!images.models.length?'Нет доступных генераторов с подтверждённой совместимостью.':''));}
    action(host,styleForm,async form=>{if(!style)throw Error('Дождитесь загрузки настроек общения.');displayStyle(await json('/api/assistant/preferences',{...Object.fromEntries(new FormData(form)),revision:style.current.revision}));text(host,'status','Настройки общения сохранены.');});
    action(host,find(host,'reset-style'),async()=>{if(!style)throw Error('Дождитесь загрузки настроек общения.');displayStyle(await json('/api/assistant/preferences',{...style.defaults,revision:style.current.revision}));text(host,'status','Настройки общения восстановлены.');});
    modelForm.elements.search.addEventListener('input',filterModels);modelForm.elements.price.addEventListener('change',filterModels);
    action(host,modelForm,async form=>{if(!models)throw Error('Дождитесь загрузки моделей.');models=await json('/api/model-settings',{model:form.elements.model.value,revision:models.revision||0});filterModels();text(host,'status','Выбор модели сохранён.');text(host,'model-current',models.inherited?'Используется общая модель.':'Выбрано: '+models.model);text(host,'model-notice',models.choiceMessage||'');});
    action(host,find(host,'refresh-models'),()=>loadModels(true));
    action(host,imageForm,async form=>{if(!images)throw Error('Дождитесь загрузки генераторов.');await json('/api/assistant/illustrations/settings',{model:form.elements.model.value,revision:images.current.revision});await loadImages();text(host,'status','Генератор сохранён.');});
    Promise.allSettled([json('/api/assistant/preferences').then(displayStyle),loadModels(),loadImages()]).then(results=>{const failures=results.filter(x=>x.status==='rejected');if(failures.length)text(host,'status',failures.map(x=>x.reason.message).join(' '));});
  }
  function keys(host){
    async function refresh(){const state=await json('/api/admin/provider-keys');for(const name of Object.keys(label)){const value=state[name];text(host,'key-state-'+name,label[name]+': '+(value?.configured?'ключ сохранён.':'ключ не настроен.')+(name==='openrouter'&&!value?.enabled?' Маршрут пока недоступен.':''));}}
    for(const form of host.querySelectorAll('[data-ai="provider-key"]'))action(host,form,async()=>{await json('/api/admin/provider-keys/'+form.dataset.provider,{key:form.elements.key.value});form.reset();await refresh();text(host,'status','Ключ сохранён.');});refresh().catch(error=>text(host,'status',error.message));
  }
  function adminModels(host){let catalog=[],current;const form=find(host,'default-model');
    const source=m=>m.id.includes('/')?(m.free?'openrouter-free':'openrouter-paid'):'deepseek';
    function detail(){const model=catalog.find(m=>m.id===form.elements.model.value);options(form.elements.effort,(model?.efforts||[]).map(x=>[x,efforts[x]||x]),model?.id===current?.model?current.effort:model?.defaultEffort);}
    function select(){const rows=catalog.filter(m=>m.chat&&source(m)===form.elements.source.value);options(form.elements.model,rows.map(m=>[m.id,m.name]),current?.model);form.querySelector('button[type=submit]').disabled=!rows.length;detail();}
    function list(){const needle=find(host,'admin-model-search').value.toLocaleLowerCase();const table=document.createElement('table');const head=table.createTHead().insertRow();for(const title of ['Модель','Тариф и ограничения','Совместимость','Доступ']){const th=document.createElement('th');th.textContent=title;head.append(th);}
      const body=table.createTBody();for(const model of catalog.filter(m=>(m.name+' '+m.family+' '+m.id).toLocaleLowerCase().includes(needle))){const row=body.insertRow();row.insertCell().textContent=model.name+' ('+model.id+')';const price=row.insertCell();price.className='pm-ai-tariff';price.textContent=[model.free?'Бесплатно':'Платно',model.rates?.length?'USD за токен: вход '+model.rates[0]+', выход '+model.rates[1]+'; за запрос '+model.rates[2]:model.id.includes('/')?'Тариф не подтверждён':'Тариф прямого шлюза',model.imagePrice?'USD за изображение: '+model.imagePrice[0]:'',model.contextLimit?'Контекст: '+model.contextLimit+' токенов':'',model.maxCompletionTokens?'Ответ: до '+model.maxCompletionTokens+' токенов':''].filter(Boolean).join('\n');
        const chat=model.compatibility?.chat,image=model.compatibility?.image;row.insertCell().textContent=[model.advertisedChat?(chat?.inherited?'Действующий прямой маршрут':chat?.verified?'Чат проверен':'Чат: ожидает приёмки'):'',model.advertisedImage?(image?.verified?'Иллюстрации проверены':'Иллюстрации: ожидает приёмки'):''].filter(Boolean).join(' · ');
        const button=document.createElement('button');button.type='button';button.textContent=model.allowed?'Отключить':'Разрешить';action(host,button,async()=>{await json('/api/admin/ai-models',{model:model.id,enabled:!model.allowed,revision:model.permissionRevision});await refresh(false);});row.insertCell().append(button);}
      find(host,'admin-model-list').replaceChildren(table);}
    async function refresh(force){const [data,value]=await Promise.all([json('/api/admin/ai-models'+(force?'?refresh=1':'')),json('/api/admin/chat-default?details=1')]);catalog=data.models;current=value;form.elements.source.value=current.source;select();list();text(host,'default-current','Сейчас: '+current.model+' · '+(efforts[current.effort]||current.effort));text(host,'status',data.message);}
    form.elements.source.addEventListener('change',select);form.elements.model.addEventListener('change',detail);find(host,'admin-model-search').addEventListener('input',list);
    action(host,form,async()=>{current=await json('/api/admin/chat-default',Object.fromEntries(new FormData(form)));text(host,'default-current','Сейчас: '+current.model+' · '+(efforts[current.effort]||current.effort));text(host,'status','Общая модель сохранена.');});action(host,find(host,'refresh-admin-models'),()=>refresh(true));refresh(false).catch(error=>text(host,'status',error.message));
  }
  function balances(host){let snapshot;
    function show(value){snapshot=value;const target=find(host,'balances');target.replaceChildren();for(const [name,provider] of Object.entries(value.providers)){const card=document.createElement('div');card.className='pm-ai-balance';const title=document.createElement('h3');title.textContent=label[name]||name;const amount=document.createElement('strong');amount.textContent=provider.amounts.map(a=>a.amount+' '+a.currency).join(' + ')||'Нет данных';const status=document.createElement('p');status.textContent=[provider.updatedAt?'Последнее успешное обновление: '+new Date(provider.updatedAt*1000).toLocaleString('ru-RU'):'',provider.error].filter(Boolean).join(' · ');card.append(title,amount,status);target.append(card);}
      find(host,'balance-interval').elements.intervalMinutes.value=value.intervalMinutes;const form=find(host,'balance-alerts'),alerts=value.telegramAlerts;for(const name of Object.keys(label))form.elements[name].value=alerts.thresholdsUsd?.[name]||alerts.thresholdUsd;form.elements.cnyPerUsd.value=alerts.cnyPerUsd||'';text(host,'telegram-status',alerts.enabled?'Оповещения включены.':alerts.linked?'Telegram подключён. Сохраните настройки оповещений.':'Подключите Telegram администратора.');find(host,'telegram-test').disabled=!alerts.linked;}
    const refresh=async(path='',data)=>show(await json('/api/admin/provider-balances'+path,data));
    action(host,find(host,'refresh-balances'),()=>refresh('/refresh',{}));
    action(host,find(host,'balance-interval'),form=>refresh('/settings',{intervalMinutes:form.elements.intervalMinutes.valueAsNumber}));
    action(host,find(host,'balance-alerts'),form=>refresh('/alert-settings',{thresholdUsd:form.elements.deepseek.value,thresholdsUsd:{deepseek:form.elements.deepseek.value,openrouter:form.elements.openrouter.value},cnyPerUsd:form.elements.cnyPerUsd.value}));
    action(host,find(host,'telegram-test'),async()=>{await refresh('/telegram-test',{});text(host,'status','Сообщение с балансами отправлено.');});
    action(host,find(host,'telegram-connect'),async()=>{const response=await json('/api/admin/provider-balances/telegram-connect',{}),url=new URL(response.url,location.origin);if(!(url.origin===location.origin&&url.pathname==='/telegram/return')&&!(url.origin==='https://oauth.telegram.org'&&url.pathname==='/auth'))throw Error('Недопустимый адрес подключения Telegram.');sessionStorage.setItem('podmasterye.telegram.return','/admin');location.href=url.href;});refresh().catch(error=>text(host,'status',error.message));
  }
  function mount(){document.querySelectorAll('[data-pm-ai-settings]').forEach(user);for(const host of document.querySelectorAll('[data-pm-ai-admin]')){if(host.dataset.ready)continue;host.dataset.ready='1';({keys,models:adminModels,balances})[host.dataset.pmAiAdmin]?.(host);}}
  function message(host,value){const sources=[...(value.savedIllustrations||[]),...(value.illustration?[value.illustration]:[])];for(const source of new Set(sources)){let url;try{url=new URL(source,location.origin);}catch{continue;}if(url.origin!==location.origin||!/^\/api\/chats\/[A-Za-z0-9_-]+\/illustrations\/[a-f0-9]{32}$/.test(url.pathname))continue;const link=document.createElement('a');link.className='pm-ai-artifact';link.href=url.pathname;link.target='_blank';link.rel='noopener';const image=document.createElement('img');image.className='pm-ai-illustration';image.alt='Иллюстрация Подмастерья';image.src=url.pathname;image.loading='lazy';link.append(image);host.append(link);}}
  window.PMAI={mount,message};document.addEventListener('DOMContentLoaded',mount);if(document.readyState!=='loading')mount();
})();
