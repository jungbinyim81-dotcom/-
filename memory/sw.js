const CACHE = "jsmem-20260815-2015";
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
  // HTML 문서는 브라우저 HTTP 캐시까지 건너뛰고 항상 새로 받는다.
  // (GitHub Pages 가 max-age 를 걸어두어 수정본이 몇 분간 안 내려오던 문제)
  const isDoc = e.request.mode === "navigate" || e.request.destination === "document";
  const req = isDoc
    ? new Request(e.request.url, {cache: "no-store", credentials: "same-origin"})
    : e.request;
  e.respondWith(
    fetch(req).then(res => {
      const copy = res.clone();
      caches.open(CACHE).then(c => c.put(e.request, copy)).catch(()=>{});
      return res;
    }).catch(() => caches.match(e.request).then(r => r || caches.match("./index.html")))
  );
});
