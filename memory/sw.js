const CACHE = "jsmem-20260803-0836";
const ASSETS = ["./","./index.html","./manifest.json","./icon.svg","./apple-touch-icon.png","./icon-192.png","./icon-512.png","./icon-maskable-512.png","./splash-1125x2436.png","./splash-1170x2532.png","./splash-1179x2556.png","./splash-1242x2688.png","./splash-1284x2778.png","./splash-1290x2796.png","./splash-1536x2048.png","./splash-1668x2388.png","./splash-2048x2732.png","./splash-750x1334.png","./splash-828x1792.png"];
self.addEventListener("install", e => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS).catch(()=>{})));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
  ).then(()=> self.clients.claim()));
});
self.addEventListener("fetch", e => {
  if (e.request.method !== "GET") return;
  e.respondWith(
    fetch(e.request).then(res => {
      const copy = res.clone();
      caches.open(CACHE).then(c => c.put(e.request, copy)).catch(()=>{});
      return res;
    }).catch(() => caches.match(e.request))
  );
});
