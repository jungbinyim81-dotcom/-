const CACHE_NAME = "team4-20260623-1405";
const ASSETS = [
  "./",
  "./index.html",
  "./manifest.json",
  "./icon.svg",
  "./거래처처방현황통합관리_4팀.html",
  "./API_실적분석.html",
  "./팀개원처현황.html",
  "./월별_중점처활동분석.html",
  "./4월_중점처활동분석.html",
  "./5월_중점처활동분석.html",
  "./RnP규정.html",
  "./RnP결과.html",
  "./인센티브_통합대시보드.html",
  "./연간인센티브현황.html",
  "./전은성_연간인센상세.html",
  "./임대현_연간인센상세.html",
  "./황태영_연간인센상세.html",
  "./김혜성_연간인센상세.html",
  "./104기_2Q_팀여행인센티브.html",
  "./베믈리디_인센티브_대시보드.html",
  "./리알트리스_인센티브_대시보드.html",
  "./라베피드_인센티브_대시보드.html",
  "./104기_4-6월_순환기품목인센티브.html"
];

// 설치: 최신 자료 캐싱
self.addEventListener("install", e => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(ASSETS).catch(()=>{})));
});

// 페이지에서 SKIP_WAITING 요청 시 즉시 활성화
self.addEventListener("message", e => {
  if (e.data && e.data.type === "SKIP_WAITING") self.skipWaiting();
});

// 활성화: 옛 캐시 삭제 (자료 갱신 즉시 반영)
self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    ).then(()=> self.clients.claim())
  );
});

// 네트워크 우선 (최신성 보장), 실패 시 캐시 (오프라인)
self.addEventListener("fetch", e => {
  if (e.request.method !== "GET") return;
  e.respondWith(
    fetch(e.request).then(res => {
      const copy = res.clone();
      caches.open(CACHE_NAME).then(c => c.put(e.request, copy)).catch(()=>{});
      return res;
    }).catch(() => caches.match(e.request))
  );
});
