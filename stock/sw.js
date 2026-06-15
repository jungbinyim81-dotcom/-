const CACHE_NAME = "soxl-20260616-0555";
const ASSETS = ["./", "./index.html", "./manifest.json", "./icon.svg"];

self.addEventListener("install", e => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(ASSETS).catch(()=>{})));
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// data.json 은 네트워크 우선 (항상 최신) + 성공 시 캐시 저장, 실패 시 캐시 폴백
// (쿼리스트링 ?t= 때문에 캐시 키를 pathname 으로 고정해야 폴백이 동작함)
self.addEventListener("fetch", e => {
  if (e.request.method !== "GET") return;
  const url = new URL(e.request.url);
  if (url.pathname.endsWith('data.json') || url.pathname.endsWith('journal.json')) {
    e.respondWith(
      fetch(e.request).then(r => {
        if (r && r.ok) {
          const copy = r.clone();
          caches.open(CACHE_NAME).then(c => c.put(url.pathname, copy)).catch(()=>{});
        }
        return r;
      }).catch(() => caches.match(url.pathname, { ignoreSearch: true }))
    );
  } else {
    e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
  }
});
