/* One appearance preference across every HTML document. */
(()=>{
 const root=document.documentElement,media=matchMedia('(prefers-color-scheme:dark)');
 const modes=['light','dark','system'];
 const pref=()=>{try{const v=localStorage.getItem('pm-theme');return modes.includes(v)?v:'light';}catch{return 'light';}};
 function apply(){const mode=pref();const shade=mode==='system'?(media.matches?'dark':'light'):mode;root.dataset.theme=shade;root.dataset.appearance=shade;root.style.colorScheme=shade;document.querySelectorAll('[data-pm-theme]').forEach(b=>{b.setAttribute('aria-label',shade==='dark'?'Включить светлую тему':'Включить тёмную тему');b.textContent=shade==='dark'?'☀':'◐';});}
 function set(mode){if(!modes.includes(mode))return;try{localStorage.setItem('pm-theme',mode);}catch{}apply();}
 window.PMTheme={apply,set,pref};
 media.addEventListener('change',apply);window.addEventListener('storage',e=>{if(e.key==='pm-theme')apply();});window.addEventListener('pageshow',apply);
 document.addEventListener('DOMContentLoaded',()=>{apply();document.querySelectorAll('[data-pm-theme]').forEach(b=>b.addEventListener('click',()=>set(root.dataset.theme==='dark'?'light':'dark')));});
 apply();
})();
