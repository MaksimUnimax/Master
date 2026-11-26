/* Adapter for the copied Octoport file-drafts, file-cost and voice controls.
 * All file inspection, recognition, caching and billing remain in the native implementation.
 */
import { fileDrafts } from './file-drafts.js';
import { prepareFile } from './file-cost.js';
import { mountVoice } from './voice.js';

export async function mountComposer(form,chat,api){
 const text=form.elements.text,send=form.querySelector('button[type=submit]'),picker=form.querySelector('input[type=file]'),add=form.querySelector('#attach-file'),list=form.querySelector('#attachment-drafts'),status=document.querySelector('#assistant-status');
 let busy=false,uploads=0,live=true;
 const readyFiles=new Map(),draftAttachments=new Map();
 const account={selected:chat,guest:false,hasChat:id=>live&&id===chat,api};
 const drafts=fileDrafts(account);
 const updateState=()=>{
   send.disabled=!live||busy||uploads>0;
   add.disabled=!live||busy||uploads>0;
   text.readOnly=busy;
   for(const b of list.querySelectorAll('button'))b.disabled=busy;
 };
 function resize(){
   text.style.height='0px';
   text.style.height=Math.max(26,Math.min(text.scrollHeight,124))+'px';
 }
 function remove(id){
   const a=draftAttachments.get(id);
   if(a?.previewUrl)URL.revokeObjectURL(a.previewUrl);
   drafts.remove(id);draftAttachments.delete(id);readyFiles.delete(id);
 }
 const conversation={draftAttachments,fileUploads:{update(fn){const state={};fn(state);for(const [id,v] of Object.entries(state))if(v.status==='ready')readyFiles.set(id,v.receiptId);}},
   releaseDraftAttachment:remove};
 function render(){
   list.replaceChildren();
   for(const [id,a] of draftAttachments){
     const chip=document.createElement('div');chip.className='pm-file-chip';
     if(a.previewUrl){const img=document.createElement('img');img.src=a.previewUrl;img.alt='';chip.append(img);}
     const title=document.createElement('span');title.textContent=a.file.name+' · '+Math.max(1,Math.ceil(a.file.size/1024))+' КБ';title.title=a.file.name;
     const b=document.createElement('button');b.type='button';b.className='secondary';b.textContent='×';b.setAttribute('aria-label','Убрать '+a.file.name);
     b.onclick=async()=>{
       if(busy)return;b.disabled=true;
       try{const receipt=readyFiles.get(id);if(receipt)await api('/api/chats/'+encodeURIComponent(chat)+'/files/'+receipt,{method:'DELETE'});remove(id);render();}
       catch(e){status.textContent=e.message;b.disabled=false;}
     };
     chip.append(title,b);list.append(chip);
   }
   list.hidden=!draftAttachments.size;updateState();
 }
 const shell={disposed:false,addAttachments(ids){render();return ids.every(id=>readyFiles.has(id));}};
 const uploadAbort=new AbortController();
 async function upload(files){
   if(busy||uploads||!live)return;
   const chosen=Array.from(files);
   if(chosen.length+draftAttachments.size>10){status.textContent='Можно прикрепить до 10 файлов.';return;}
   uploads++;updateState();
   try{
     for(const file of chosen){
       if(!live)break;
       if(!file.size||file.size>8*1024*1024){status.textContent='Файл пуст или больше 8 МиБ: '+file.name;continue;}
       status.textContent='Загрузка: '+file.name;
       try{
         const query=new URLSearchParams({sessionId:chat,name:file.name});
         const r=await api('/api/session/uploadFileBinary?'+query,{method:'POST',signal:uploadAbort.signal,headers:{'Content-Type':'application/octet-stream'},body:file});
         if(!r.ok)throw Error(r.error?.message||'Файл не принят.');
         if(!live)break;
         const id=crypto.randomUUID(),receipt=r.value.receiptId;
         if(!/^[a-f0-9]{32}$/.test(receipt))throw Error('Некорректная квитанция загрузки.');
         const a={id,file,kind:r.value.image?'image':'file',...(r.value.image?{previewUrl:URL.createObjectURL(file)}:{})};
         draftAttachments.set(id,a);readyFiles.set(id,receipt);drafts.ready(chat,id,receipt);render();status.textContent='';
       }catch(e){if(live)status.textContent=e.message;}
     }
   }finally{uploads--;render();picker.value='';}
 }
 add.onclick=()=>picker.click();
 picker.onchange=()=>upload(picker.files);
 text.addEventListener('paste',e=>{const files=Array.from(e.clipboardData?.files||[]);if(files.length){e.preventDefault();void upload(files);}});
 form.addEventListener('dragover',e=>{if(Array.from(e.dataTransfer?.types||[]).includes('Files')){e.preventDefault();e.dataTransfer.dropEffect=busy?'none':'copy';}});
 form.addEventListener('drop',e=>{if(e.dataTransfer?.files.length){e.preventDefault();void upload(e.dataTransfer.files);}});
 text.addEventListener('keydown',e=>{
   if(e.key!=='Enter'||e.shiftKey||e.isComposing||e.keyCode===229)return;
   e.preventDefault();if(!e.repeat&&!send.disabled&&(text.value.trim()||readyFiles.size))form.requestSubmit(send);
 });
 text.addEventListener('input',resize);
 window.addEventListener('resize',resize);
 const shutdown=()=>{live=false;shell.disposed=true;uploadAbort.abort();for(const a of draftAttachments.values())if(a.previewUrl)URL.revokeObjectURL(a.previewUrl);updateState();};
 window.addEventListener('pagehide',shutdown,{once:true});
 window.addEventListener('storage',e=>{if(e.key==='podmasterye.logout'&&e.newValue)shutdown();});
 document.querySelector('form[action="/logout"]')?.addEventListener('submit',()=>{try{localStorage.setItem('podmasterye.logout',crypto.randomUUID());}catch{}shutdown();});
 await drafts.restore(chat,shell,conversation);render();resize();
 mountVoice(account);
 return {
   ready:()=>live&&!busy&&!uploads,
   ids:()=>Array.from(readyFiles.values()),
   files:()=>Array.from(draftAttachments.entries()).filter(([id])=>readyFiles.has(id)).map(([id,a])=>({attachmentId:readyFiles.get(id),name:a.file.name,bytes:a.file.size})),
   lock(){busy=true;updateState();},
   unlock(){busy=false;updateState();},
   async prepare(ids){for(const receipt of ids)await prepareFile(api,chat,receipt,'auto',uploadAbort.signal);},
   committed(ids){const set=new Set(ids);for(const [id,receipt] of readyFiles)if(set.has(receipt))remove(id);render();},
   resize,
 };
}
