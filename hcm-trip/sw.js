const CACHE = "hcm-trip-20261005-1634";
const ASSETS = ["./", "./index.html", "./manifest.json", "./icon.svg", "./icon-180.png", "./icon-192.png", "./icon-512.png"];
self.addEventListener("install", e => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS).catch(() => {})));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k.startsWith("hcm-trip-") && k !== CACHE).map(k => caches.delete(k)))
  ).then(() => self.clients.claim()));
});
// 네트워크 우선, 실패하면 캐시 (현지에서 데이터가 끊겨도 마지막으로 본 화면·지도는 보임)
self.addEventListener("fetch", e => {
  if (e.request.method !== "GET") return;
  e.respondWith(
    fetch(e.request).then(res => {
      if (res.ok || res.type === "opaque") {          // 오류 응답은 캐시하지 않음 (지도 타일은 opaque)
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, copy)).catch(() => {});
      }
      return res;
    }).catch(() => caches.match(e.request, { ignoreSearch: true }))
  );
});
