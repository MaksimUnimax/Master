/* Account controls share the lifecycle preview, version check and audit API. */
(()=>{'use strict';
  const all=document.querySelector('[data-account-select-all]'),form=document.querySelector('[data-account-batch]');
  if(!all||!form)return;
  const rows=[...document.querySelectorAll('[data-account-select]')],dialog=document.querySelector('#account-lifecycle-dialog');
  const preview=dialog.querySelector('[data-account-preview]'),confirmation=dialog.querySelector('[data-account-confirm]');
  const result=dialog.querySelector('[data-account-result]'),problem=document.querySelector('[data-account-problem]');
  const names={block:'Блокировка',archive:'Архивация',restore:'Восстановление',delete:'Предпросмотр удаления'};
  let snapshot=null,action=null,busy=false,changed=false,pending=null;
  const element=(tag,text)=>{const el=document.createElement(tag);el.textContent=text;return el;};
  async function request(path,data){
    const r=await fetch('/api/admin/accounts/'+path,{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    const d=await r.json();if(!r.ok)throw Error(d.error||'Не удалось выполнить действие.');return d;
  }
  function selected(){return rows.filter(row=>row.checked).map(row=>row.value);}
  function update(){const n=selected().length;all.checked=n>0&&n===rows.length;all.indeterminate=n>0&&n<rows.length;all.disabled=!rows.length;form.querySelector('button').disabled=n===0;document.querySelector('[data-account-selected]').textContent=n?'Выбрано: '+n:'';}
  all.addEventListener('change',()=>{rows.forEach(row=>row.checked=all.checked);update();});rows.forEach(row=>row.addEventListener('change',update));
  async function inspect(actors,kind){
    if(busy)return;busy=true;problem.textContent='';
    try{
      snapshot=await request('preview',{actors,action:kind});action=kind;changed=false;pending=null;confirmation.reset();result.textContent='';preview.replaceChildren();
      dialog.querySelector('h2').textContent=names[kind]+' · проверка последствий';
      for(const item of snapshot.items){
        const box=element('section','');box.className='account-card';box.append(element('h3',item.login||item.actor));
        if(item.wallet){const balances=element('p','Монеты: доступно '+window.MasterCoins.format(item.wallet.available)+' · в резерве '+window.MasterCoins.format(item.wallet.reserved));balances.title='Точно: '+item.wallet.available+' / '+item.wallet.reserved;box.append(balances,element('p','Незавершённых платежей: '+item.wallet.pendingPayments+' · запросов без подтверждённого расхода: '+item.wallet.unconfirmedAttempts));}
        for(const text of item.effects||[])box.append(element('p',text));
        if(!item.allowed)box.append(element('p',item.blockedReason||'Операция недоступна.'));
        if(item.records){const details=element('details','');details.append(element('summary','Связанные записи и файлы'));const list=element('ul','');for(const [table,count]of Object.entries(item.records))if(count)list.append(element('li',table+': '+count));details.append(list);const files=item.nativeFiles;details.append(element('p',files?.complete?'Файлов: '+files.files+' · байт: '+files.bytes:'Точная проверка файлов недоступна; удаление запрещено.'));box.append(details);}
        preview.append(box);
      }
      confirmation.hidden=kind==='delete';confirmation.querySelector('button').disabled=!snapshot.items.some(item=>item.allowed);
      dialog.showModal();
    }catch(error){problem.textContent=error.message;}finally{busy=false;}
  }
  form.addEventListener('submit',event=>{event.preventDefault();inspect(selected(),form.elements.action.value);});
  for(const button of document.querySelectorAll('[data-account-action]'))button.addEventListener('click',()=>inspect([button.dataset.actor],button.dataset.accountAction));
  confirmation.addEventListener('submit',async event=>{
    event.preventDefault();if(busy||changed||!snapshot)return;
    const payload={items:snapshot.items.filter(item=>item.allowed).map(({actor,expected})=>({actor,expected})),action,reason:confirmation.elements.reason.value.trim()};
    if(!payload.items.length||!payload.reason)return;
    const signature=JSON.stringify(payload);if(pending?.signature!==signature)pending={signature,id:crypto.randomUUID()};
    busy=true;confirmation.querySelector('button').disabled=true;result.textContent='Выполняем…';
    try{
      const reply=await request('lifecycle',{requestId:pending.id,...payload});changed=reply.changed>0;
      const labels=new Map(snapshot.items.map(item=>[item.actor,item.login||item.actor]));
      result.replaceChildren(element('p','Изменено аккаунтов: '+reply.changed));
      for(const item of reply.items)result.append(element('p',labels.get(item.actor)+': '+(item.ok?'готово':item.error)));
      if(changed){confirmation.hidden=true;dialog.querySelector('[data-account-close]').textContent='Обновить список';}
      else result.append(element('p','Если данные изменились, закройте окно и проверьте последствия снова.'));
    }catch(error){result.textContent=error.message+' Повтор запроса использует тот же идентификатор.';}
    finally{busy=false;confirmation.querySelector('button').disabled=changed;}
  });
  dialog.querySelector('[data-account-close]').addEventListener('click',()=>{if(!busy)dialog.close();});
  dialog.addEventListener('cancel',event=>{if(busy)event.preventDefault();});
  dialog.addEventListener('close',()=>{if(changed)location.reload();});
  update();
})();
