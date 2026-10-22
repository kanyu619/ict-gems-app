// ICT Gems App – Offline-Speicher. Version 86ba8f15e9 (ändert sich bei jedem Neubau)
const C='gems-86ba8f15e9', CORE=['./','index.html','manifest.webmanifest','icon-192.png','icon-512.png'];
self.addEventListener('install',e=>{e.waitUntil(caches.open(C).then(c=>c.addAll(CORE)));self.skipWaiting()});
self.addEventListener('activate',e=>{e.waitUntil(caches.keys().then(k=>Promise.all(k.filter(x=>x!==C).map(x=>caches.delete(x)))));self.clients.claim()});
self.addEventListener('fetch',e=>{
  if(e.request.method!=='GET')return;
  if(e.request.mode==='navigate'){ // neueste Version bei Netz, sonst gespeicherte
    e.respondWith(fetch(e.request).then(r=>{caches.open(C).then(c=>c.put('index.html',r.clone()));return r}).catch(()=>caches.match('index.html')));return}
  e.respondWith(caches.match(e.request).then(m=>m||fetch(e.request).then(r=>{const cp=r.clone();caches.open(C).then(c=>c.put(e.request,cp));return r})));
});
