const C='gagyebu-20260825-0517';
self.addEventListener('install',e=>{self.skipWaiting();
 e.waitUntil(caches.open(C).then(c=>c.addAll(['./','./manifest.json','./icon.svg'])))});
self.addEventListener('activate',e=>{e.waitUntil(
 caches.keys().then(k=>Promise.all(k.filter(x=>x!==C).map(x=>caches.delete(x))))
 .then(()=>self.clients.claim()))});
self.addEventListener('fetch',e=>{if(e.request.method!=='GET')return;
 e.respondWith(fetch(e.request).then(r=>{const cp=r.clone();
  caches.open(C).then(c=>c.put(e.request,cp));return r})
 .catch(()=>caches.match(e.request).then(r=>r||caches.match('./'))))});
