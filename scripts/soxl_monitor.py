# -*- coding: utf-8 -*-
"""
SOXL 모니터링 - GitHub Actions용 (클라우드 실행)
- 데스크탑 OFF여도 GitHub 서버에서 자동 실행
- 가격 수집 → 분석 → data.json/index.html 생성 → 자동 커밋 → 텔레그램 알림

환경변수 (GitHub Secrets):
- TELEGRAM_BOT_TOKEN: 텔레그램 봇 토큰
- TELEGRAM_CHAT_ID: 빛날빈님 채팅 ID
- POSITION_JSON: 포지션 정보 JSON 문자열 (전체)
"""
import sys
import os
import json
import time
import urllib.request
import urllib.parse
from datetime import datetime, timedelta

import yfinance as yf
import pandas as pd
import numpy as np

# ====== 경로 ======
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(REPO_ROOT, 'stock')
os.makedirs(APP_DIR, exist_ok=True)

# ====== 환경변수 ======
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')
POSITION_JSON_STR = os.environ.get('POSITION_JSON', '')
FORCE_BRIEFING = os.environ.get('FORCE_BRIEFING', '').lower() in ('true', '1', 'yes')

# 포지션 로드 (Secret에서 JSON 문자열로)
if POSITION_JSON_STR:
    try:
        POSITION = json.loads(POSITION_JSON_STR)
    except Exception as e:
        print(f"[경고] POSITION_JSON 파싱 실패: {e}")
        POSITION = {"포지션": {}}
else:
    POSITION = {"포지션": {}}

# ====== 티커 ======
TICKERS = {
    "SOXL": "SOXL", "SOXX": "SOXX", "NVDA": "NVDA",
    "하이닉스": "000660.KS", "삼성전자": "005930.KS",
    "환율": "KRW=X", "VIX": "^VIX", "필반": "^SOX",
    "10년물": "^TNX", "단기금리": "^IRX", "DXY": "DX-Y.NYB",
    "HYG": "HYG", "BTC": "BTC-USD", "TLT": "TLT", "MOVE": "^MOVE",
    "SKEW": "^SKEW", "MSFT": "MSFT", "GOOG": "GOOG", "META": "META",
}

# ====== 이벤트 일정 ======
FOMC_2026 = ["2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
             "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09"]
CPI_2026 = ["2026-01-14", "2026-02-11", "2026-03-11", "2026-04-15",
            "2026-05-13", "2026-06-11", "2026-07-15", "2026-08-12",
            "2026-09-10", "2026-10-15", "2026-11-13", "2026-12-10"]
ISM_2026 = ["2026-01-02", "2026-02-02", "2026-03-02", "2026-04-01",
            "2026-05-01", "2026-06-01", "2026-07-01", "2026-08-03",
            "2026-09-01", "2026-10-01", "2026-11-02", "2026-12-01"]
NFP_2026 = ["2026-01-02", "2026-02-06", "2026-03-06", "2026-04-03",
            "2026-05-01", "2026-06-05", "2026-07-03", "2026-08-07",
            "2026-09-04", "2026-10-02", "2026-11-06", "2026-12-04"]


def 다음이벤트(일정, 이름):
    오늘 = datetime.now().date()
    for d_str in 일정:
        d = datetime.strptime(d_str, "%Y-%m-%d").date()
        if d >= 오늘:
            return {"이름": 이름, "일자": d_str, "남은일": (d - 오늘).days}
    return None


def 다음목요일():
    오늘 = datetime.now().date()
    delta = (3 - 오늘.weekday()) % 7
    if delta == 0:
        delta = 7
    return 오늘 + timedelta(days=delta)


def TSMC매출_다음():
    오늘 = datetime.now().date()
    for 월차 in range(0, 3):
        년 = 오늘.year + (오늘.month - 1 + 월차) // 12
        월 = (오늘.month - 1 + 월차) % 12 + 1
        try:
            d = datetime(년, 월, 10).date()
            if d >= 오늘:
                return {"이름": "TSMC매출", "일자": d.strftime("%Y-%m-%d"),
                        "남은일": (d - 오늘).days}
        except ValueError:
            continue
    return None


def 가격수집():
    결과 = {}
    for 이름, 티커 in TICKERS.items():
        # 야후가 GitHub Actions(데이터센터 IP)를 가끔 차단/레이트리밋 → 빈 데이터로 옴.
        # 재시도로 완화하고, 그래도 실패하면 None(이후 직전값폴백에서 마지막 정상값으로 대체).
        hist = None
        마지막에러 = None
        for 시도 in range(3):
            try:
                t = yf.Ticker(티커)
                h = t.history(period="3mo")
                if h is not None and len(h) >= 1:
                    hist = h
                    break
                마지막에러 = "빈 데이터(야후 차단/레이트리밋 추정)"
            except Exception as e:
                마지막에러 = f"{type(e).__name__}: {e}"
            time.sleep(1.5 * (시도 + 1))
        if hist is None:
            결과[이름] = None
            print(f"  [{이름}] 실패: {마지막에러}")
            continue
        try:
            현재가 = float(hist['Close'].iloc[-1])
            전일가 = float(hist['Close'].iloc[-2]) if len(hist) >= 2 else 현재가
            등락 = ((현재가 - 전일가) / 전일가) * 100
            spark = [round(float(x), 4) for x in hist['Close'].tail(60).tolist()]
            결과[이름] = {
                "현재가": round(현재가, 4), "전일가": round(전일가, 4),
                "등락률": round(등락, 2), "스파크라인": spark, "티커": 티커,
                "일자": str(hist.index[-1].date()),  # 마지막 거래일 (검증 일지용)
            }
            print(f"  [{이름:8}] {현재가:>12,.2f}  ({등락:+.2f}%)")
        except Exception as e:
            결과[이름] = None
            print(f"  [{이름}] 파싱 실패: {e}")
    return 결과


def 직전값폴백(가격):
    """이번 회차에서 yfinance가 실패(None)한 종목은 직전 data.json의 마지막 정상값으로 대체.
    야후가 GitHub IP를 가끔 차단 → null 박힌 채 커밋되면 PWA가 통째로 깨지므로, 직전 정상값을 유지한다.
    (이게 '정기적으로 데이터 오류' 재발의 근본 차단. 대체된 종목은 stale=True로 표시.)"""
    try:
        with open(os.path.join(APP_DIR, 'data.json'), encoding='utf-8') as f:
            기존 = json.load(f)
    except Exception:
        기존 = {}
    직전 = {}
    for 구역 in ('시장', '금리'):
        for k, v in (기존.get(구역) or {}).items():
            if isinstance(v, dict) and '현재가' in v:
                직전[k] = v
    대체 = []
    for 이름 in list(가격.keys()):
        if 가격.get(이름) is None and 직전.get(이름):
            복사 = dict(직전[이름])
            복사['stale'] = True       # 직전 정상값(현 회차 수집 실패)
            가격[이름] = 복사
            대체.append(이름)
    if 대체:
        print(f"  [폴백] 수집 실패 종목 직전 정상값 사용: {', '.join(대체)}")
    return 가격


def 포지션손익(가격):
    결과 = []
    총평가손익_KRW = 0
    총투자금 = 0
    환율 = 가격["환율"]["현재가"] if 가격.get("환율") else 1500
    KR종목 = ["하이닉스", "삼성전자"]

    for 종목, info in POSITION.get("포지션", {}).items():
        가격정보 = 가격.get(종목)
        if not info.get("활성") or 가격정보 is None:
            결과.append({
                "종목": 종목, "활성": False,
                "메모": info.get("메모", ""),
                "투자금": info.get("투자금_KRW", 0),
            })
            총투자금 += info.get("투자금_KRW", 0)
            continue

        진입가 = info["진입가_KRW"] if 종목 in KR종목 else info["진입가_USD"]
        현재가 = 가격정보["현재가"]
        통화 = "KRW" if 종목 in KR종목 else "USD"

        if 진입가 == 0:
            결과.append({"종목": 종목, "활성": True, "에러": "진입가 0"})
            총투자금 += info["투자금_KRW"]
            continue

        손익률 = ((현재가 - 진입가) / 진입가) * 100
        수량 = info["수량"]
        평가손익 = (현재가 - 진입가) * 수량
        평가손익_KRW = 평가손익 * 환율 if 통화 == "USD" else 평가손익
        총평가손익_KRW += 평가손익_KRW
        총투자금 += info["투자금_KRW"]

        손절선 = 진입가 * (1 + info["손절선_퍼센트"] / 100)
        익절선 = 진입가 * (1 + info["익절선_퍼센트"] / 100)
        결과.append({
            "종목": 종목, "활성": True, "통화": 통화,
            "통화기호": "$" if 통화 == "USD" else "₩",
            "진입가": round(진입가, 2), "현재가": round(현재가, 2),
            "손익률": round(손익률, 2), "수량": 수량,
            "평가손익": round(평가손익, 2),
            "평가손익_KRW": round(평가손익_KRW, 0),
            "손절선": round(손절선, 2), "익절선": round(익절선, 2),
            "손절까지_퍼센트": round(((현재가 - 손절선) / 현재가) * 100, 1),
            "익절까지_퍼센트": round(((익절선 - 현재가) / 현재가) * 100, 1),
            "스파크라인": 가격정보["스파크라인"],
            "투자금": info["투자금_KRW"], "메모": info.get("메모", ""),
            "손절_퍼센트": info["손절선_퍼센트"],
            "익절_퍼센트": info["익절선_퍼센트"],
        })

    return {
        "포지션": 결과,
        "총평가손익_KRW": round(총평가손익_KRW, 0),
        "총투자금": 총투자금,
        "총손익률": round((총평가손익_KRW / 총투자금 * 100) if 총투자금 else 0, 2),
    }


def 텔레그램(text):
    if not BOT_TOKEN or not CHAT_ID:
        print("  [텔레그램 미설정 - 스킵]")
        return False
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = urllib.parse.urlencode({
            'chat_id': CHAT_ID, 'text': text,
            'parse_mode': 'HTML', 'disable_web_page_preview': 'true',
        }).encode()
        resp = urllib.request.urlopen(
            urllib.request.Request(url, data=data, method='POST'),
            timeout=15
        )
        body = resp.read().decode('utf-8')
        if '"ok":true' in body:
            print(f"  [텔레그램 OK] {text[:40]}...")
            return True
        else:
            print(f"  [텔레그램 응답 비정상] {body[:200]}")
            return False
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8') if hasattr(e, 'read') else ''
        print(f"  [텔레그램 HTTP {e.code}] {body[:300]}")
        return False
    except Exception as e:
        print(f"  [텔레그램 실패] {type(e).__name__}: {e}")
        return False


def 분석실행(가격, 이벤트):
    """SOXL 트레이딩 신호 (수일~수주 스윙, 모멘텀 추종). 0~100.

    원칙(빛날빈님 기준): SOXL은 3배 레버리지+음의복리 트레이딩 종목.
    신호는 '단기 가격행동·모멘텀·당일 매크로 충격·근접 촉매'만으로 채점한다.
    장기 관점(금리/달러 절대레벨, 200일선 회귀, MU/TSM 펀더멘털, TLT/MOVE 유동성,
    SKEW 꼬리위험)은 매매 신호에서 제외 → '참고' 탭으로만. 추세를 거스르는
    mean-reversion 감점은 두지 않는다(상승추세 = 가점).
    배점: 모멘텀30 + 달러20 + VIX15 + 금리충격15 + 촉매회피12 + 위험선호8 = 100
    """
    점수 = 0; 근거 = []; 감점 = []

    # 1. 반도체 단기 모멘텀 (30) — 핵심 추세추종 (필반 5일)
    sox = 가격.get("필반")
    sp = sox.get("스파크라인", []) if sox else []
    if len(sp) >= 5:
        m = (sp[-1] - sp[-5]) / sp[-5] * 100
        if m >= 5: 점수 += 30; 근거.append(f"반도체 5일 +{m:.1f}% (강한 상승추세)")
        elif m >= 2: 점수 += 24; 근거.append(f"반도체 5일 +{m:.1f}% (상승)")
        elif m >= 0: 점수 += 16
        elif m >= -2: 점수 += 8; 감점.append(f"반도체 5일 {m:.1f}% (약세)")
        else: 감점.append(f"반도체 5일 {m:.1f}% (하락추세, 진입 회피)")

    # 2. DXY 당일 방향 (20) — SOXL 최대 적, 레벨 아닌 '오늘 움직임'
    dxy = 가격.get("DXY")
    if dxy:
        c = dxy["등락률"]
        if c <= -0.4: 점수 += 20; 근거.append(f"DXY {c:+.2f}% (약달러, 강호재)")
        elif c <= 0: 점수 += 15; 근거.append(f"DXY {c:+.2f}% (약세)")
        elif c <= 0.4: 점수 += 8
        elif c <= 0.8: 점수 += 3; 감점.append(f"DXY +{c:.2f}% (강달러 압박)")
        else: 감점.append(f"DXY +{c:.2f}% (급등, 진입 회피)")

    # 3. VIX 변동성 (15) — 3배 레버리지 리스크
    vix = 가격.get("VIX")
    if vix:
        v = vix["현재가"]
        if v < 16: 점수 += 15; 근거.append(f"VIX {v:.1f} (안정)")
        elif v < 20: 점수 += 11
        elif v < 26: 점수 += 5; 감점.append(f"VIX {v:.1f} (변동성 주의)")
        else: 감점.append(f"VIX {v:.1f} (공포, 레버리지 위험)")

    # 4. 금리 10년물 당일 충격 (15) — 레벨 아닌 bp 변화
    t10 = 가격.get("10년물")
    if t10:
        bp = (t10["현재가"] - t10["전일가"]) * 100
        if bp <= -5: 점수 += 15; 근거.append(f"10년물 {bp:.0f}bp (급락 호재)")
        elif bp < 5: 점수 += 11
        elif bp <= 12: 점수 += 5; 감점.append(f"10년물 +{bp:.0f}bp (상승 압박)")
        else: 감점.append(f"10년물 +{bp:.0f}bp (급등, 진입 회피)")

    # 5. 근접 촉매 회피 (12) — FOMC/CPI 임박 시 신규진입 자제
    fomc = 이벤트.get("다음FOMC"); cpi = 이벤트.get("다음CPI")
    가까움 = None
    if fomc and cpi: 가까움 = fomc if fomc["남은일"] <= cpi["남은일"] else cpi
    elif fomc: 가까움 = fomc
    elif cpi: 가까움 = cpi
    if 가까움:
        남 = 가까움["남은일"]; nm = 가까움.get("이름", "이벤트")
        if 남 > 7: 점수 += 12
        elif 남 > 3: 점수 += 7; 감점.append(f"{nm} D-{남}일")
        else: 감점.append(f"{nm} D-{남}일 (임박, 신규진입 회피)")

    # 6. 위험선호 (8) — HYG/BTC 5일 동반
    hyg = 가격.get("HYG"); btc = 가격.get("BTC")
    def _r5(x):
        s = x.get("스파크라인", []) if x else []
        return (s[-1] - s[-5]) / s[-5] * 100 if len(s) >= 5 else 0
    if hyg and btc:
        h5, b5 = _r5(hyg), _r5(btc)
        if h5 >= 0.3 and b5 >= 2: 점수 += 8; 근거.append("HYG/BTC 동반 강세 (위험선호)")
        elif h5 >= 0 and b5 >= 0: 점수 += 4
        else: 감점.append("HYG/BTC 약세 (위험회피)")

    점수 = max(0, min(100, int(round(점수))))
    if 점수 >= 65:
        신호 = "green"; 결정 = "진입/홀드 우위"; 설명 = "단기 추세·매크로 우호. 트레이딩 진입/홀드 구간"
    elif 점수 >= 45:
        신호 = "yellow"; 결정 = "관망"; 설명 = "신호 혼재. 추세 확실해질 때까지 대기"
    else:
        신호 = "red"; 결정 = "신규진입 회피·정리"; 설명 = "단기 역풍. 신규진입 회피, 보유분 리스크 관리"

    return {
        "점수": 점수, "신호": 신호, "결정": 결정, "설명": 설명,
        "근거": 근거[:3], "감점": 감점[:3],
    }


def 알림체크(data, 점수, 포지션):
    """조건 만족하는 알림 텔레그램 발송"""
    오늘 = datetime.now().strftime("%Y-%m-%d %H:%M")
    이벤트 = data["이벤트"]
    알림목록 = []

    # 1. 손절/익절 근접
    for p in 포지션["포지션"]:
        if not p.get("활성") or "손익률" not in p:
            continue
        if abs(p["손절까지_퍼센트"]) <= 10:
            알림목록.append(
                f"🔴 <b>[손절 근접] {p['종목']}</b>\n"
                f"손익 {p['손익률']:+.2f}%\n"
                f"현재 {p['통화기호']}{p['현재가']:.2f} → 손절 {p['통화기호']}{p['손절선']:.2f}\n"
                f"룰: 즉시 정리, 추가 매수 금지"
            )
        if abs(p["익절까지_퍼센트"]) <= 10:
            알림목록.append(
                f"🟢 <b>[익절 근접] {p['종목']}</b>\n"
                f"손익 {p['손익률']:+.2f}%\n"
                f"현재 {p['통화기호']}{p['현재가']:.2f} → 익절 {p['통화기호']}{p['익절선']:.2f}\n"
                f"룰: 도달 시 즉시 매도, '조금만 더' 금지"
            )

    # 2. 금리 급등
    t10 = data["시장"]["환율"] and None
    t10 = data["금리"]["10년물"]
    if t10:
        bp = (t10["현재가"] - t10["전일가"]) * 100
        if bp >= 10:
            알림목록.append(
                f"⚠ <b>[금리 급등] 10년물 +{bp:.0f}bp</b>\n"
                f"현재 {t10['현재가']:.2f}% (전일 {t10['전일가']:.2f}%)\n"
                f"SOXL 예상 영향 약 {-4.6 * bp/100:.1f}%"
            )

    # 3. DXY 급등
    dxy = data["금리"].get("DXY")
    if dxy and dxy["등락률"] >= 0.8:
        알림목록.append(
            f"⚠ <b>[달러 급등] DXY +{dxy['등락률']:.2f}%</b>\n"
            f"현재 {dxy['현재가']:.1f}\n"
            f"SOXL 최대 적 (베타 -15). 매수 보류"
        )

    # 4. 이벤트 D-1
    for k, info in [("다음FOMC", "FOMC"), ("다음CPI", "CPI")]:
        ev = 이벤트.get(k)
        if ev and ev["남은일"] <= 1:
            알림목록.append(
                f"⚠ <b>[{info} D-{ev['남은일']}]</b>\n"
                f"{ev['일자']} 발표 임박\n"
                f"룰: 신규 진입 금지, 보유 포지션 점검"
            )

    # 5. 정기 브리핑 (UTC 20:50 = 한국 05:50 또는 수동 실행 시)
    # GitHub Actions cron은 5~15분 지연 흔하므로 UTC 20~21시 범위로 잡음
    utc_hour = datetime.utcnow().hour
    아침브리핑타이밍 = utc_hour in (20, 21) or FORCE_BRIEFING
    if 아침브리핑타이밍 and 포지션["총투자금"] > 0:
        총손익 = 포지션["총평가손익_KRW"]
        총퍼센트 = 포지션["총손익률"]
        손익부호 = "+" if 총손익 >= 0 else ""

        # 종목별 손익 라인
        포지션라인 = []
        for p in 포지션["포지션"]:
            if not p.get("활성") or "손익률" not in p:
                continue
            부호 = "+" if p["평가손익_KRW"] >= 0 else ""
            이모지 = "🟢" if p["손익률"] >= 0 else "🔴"
            포지션라인.append(
                f"{이모지} {p['종목']}: {p['손익률']:+.2f}% ({부호}{p['평가손익_KRW']:,.0f}원)"
            )

        프리픽스 = "🔧 [수동 실행] " if FORCE_BRIEFING else "📊 "
        브리핑 = (
            f"{프리픽스}<b>SOXL 브리핑</b>\n"
            f"{오늘}\n\n"
            f"<b>트레이딩 신호: {점수['점수']}/100</b> ({점수['결정']})\n\n"
            f"<b>총 평가손익: {손익부호}{총손익:,.0f}원</b> ({총퍼센트:+.2f}%)\n"
            + "\n".join(포지션라인) + "\n\n"
            f"<b>호재</b>\n• " + "\n• ".join(점수['근거']) if 점수['근거'] else "호재: 없음"
        )
        브리핑 += (
            f"\n\n<b>위험</b>\n• " + "\n• ".join(점수['감점']) if 점수['감점'] else "\n\n위험: 없음"
        )

        # 반도체 장기축적 / 단기매매 신호 (SOXX·하이닉스·삼성전자)
        축적 = (data.get("분석") or {}).get("반도체축적") or {}
        축적라인 = []
        _이모지 = lambda s: "🟢" if s == "green" else ("🟡" if s == "yellow" else "🔴")
        for s in 축적.get("종목", []):
            축적라인.append(
                f"{s['종목']}: 축적 {_이모지(s['축적신호'])}{s['축적점수']}/5({s['축적결정']}) · "
                f"단기 {_이모지(s['단기신호'])}{s['단기점수']}/100({s['단기결정']})"
            )
        if 축적라인:
            브리핑 += "\n\n<b>반도체 축적(장기)/매매(단기)</b>\n" + "\n".join(축적라인)

        알림목록.insert(0, 브리핑)

    # 발송 (장중 30분마다 돌아도 같은 조건부 알림이 반복되지 않도록 쿨다운)
    # - 정기 브리핑: 항상 발송(아침 1회 타이밍에만 만들어짐)
    # - 조건부 알림(손절/익절/금리/DXY/이벤트): 동일 알림은 4시간에 1번만
    상태경로 = os.path.join(APP_DIR, 'alert_state.json')
    쿨다운초 = 4 * 3600
    try:
        with open(상태경로, encoding='utf-8') as f:
            상태 = json.load(f)
    except Exception:
        상태 = {}
    지금 = datetime.utcnow()

    발송수 = 0
    for msg in 알림목록:
        정기 = ("SOXL 브리핑" in msg)
        if not 정기:
            키 = msg.split("\n", 1)[0].strip()  # 알림 헤더로 동일 알림 식별
            마지막 = 상태.get(키)
            if 마지막:
                try:
                    if (지금 - datetime.fromisoformat(마지막)).total_seconds() < 쿨다운초:
                        print(f"  스킵(쿨다운): {키}")
                        continue
                except Exception:
                    pass
        if 텔레그램(msg):
            발송수 += 1
            if not 정기:
                상태[키] = 지금.isoformat()
            time.sleep(0.5)  # 텔레그램 rate limit 방지
    try:
        with open(상태경로, 'w', encoding='utf-8') as f:
            json.dump(상태, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  alert_state 저장 실패: {e}")
    print(f"  텔레그램 {발송수}건 발송")


def 반도체축적분석():
    """SOXX·하이닉스·삼성전자 장기축적(5)+단기매매(100). 클라우드용 자체 1y fetch.
    철학: SOXL 중단기 수익을 반도체 1~2년 장기로 굴림 → '지금 모으기 좋은가' + '단기 타이밍'."""
    def _close(tkr, period):
        try:
            return yf.Ticker(tkr).history(period=period)['Close'].dropna()
        except Exception:
            return None
    mu = _close("MU", "3mo")
    mu30 = (float(mu.iloc[-1]) - float(mu.iloc[-21])) / float(mu.iloc[-21]) * 100 if mu is not None and len(mu) >= 21 else 0
    fx = _close("KRW=X", "1mo")
    환율5 = (float(fx.iloc[-1]) - float(fx.iloc[-6])) / float(fx.iloc[-6]) * 100 if fx is not None and len(fx) >= 6 else 0
    sox = _close("^SOX", "1mo")
    필반5 = (float(sox.iloc[-1]) - float(sox.iloc[-6])) / float(sox.iloc[-6]) * 100 if sox is not None and len(sox) >= 6 else 0
    vx = _close("^VIX", "5d")
    vix = float(vx.iloc[-1]) if vx is not None and len(vx) else None

    종목맵 = [("SOXX", "SOXX", "USD", "$"), ("하이닉스", "000660.KS", "KRW", "₩"), ("삼성전자", "005930.KS", "KRW", "₩")]
    결과 = []
    for 이름, 티커, 통화, 기호 in 종목맵:
        h = _close(티커, "1y")
        if h is None or len(h) < 60:
            continue
        현재 = float(h.iloc[-1])
        ma200 = float(h.rolling(200).mean().iloc[-1]) if len(h) >= 200 else float(h.mean())
        이격200 = (현재 - ma200) / ma200 * 100
        delta = h.diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss.replace(0, 1e-9)
        rsi = float((100 - (100 / (1 + rs))).iloc[-1])
        고 = float(h.max()); 저 = float(h.min())
        위치 = (현재 - 저) / (고 - 저) * 100 if 고 > 저 else 50
        mom5 = (현재 - float(h.iloc[-6])) / float(h.iloc[-6]) * 100 if len(h) >= 6 else 0

        축적 = 0.0
        if 이격200 < -5: 축적 += 1.5
        elif 이격200 < 10: 축적 += 1.0
        elif 이격200 < 30: 축적 += 0.5
        if rsi < 35: 축적 += 1.0
        elif rsi < 55: 축적 += 0.7
        elif rsi < 70: 축적 += 0.3
        if 위치 < 35: 축적 += 1.0
        elif 위치 < 65: 축적 += 0.6
        elif 위치 < 85: 축적 += 0.3
        if 현재 > ma200 and 이격200 < 30: 축적 += 1.0
        elif 현재 <= ma200: 축적 += 0.5
        if mu30 >= 5: 축적 += 0.3
        if 통화 == "KRW":
            if 환율5 <= 0: 축적 += 0.2
        else:
            축적 += 0.2
        축적 = round(min(5.0, 축적), 1)
        if 축적 >= 4.0: 축적신호 = "green"; 축적결정 = "적극 매수"
        elif 축적 >= 2.5: 축적신호 = "yellow"; 축적결정 = "분할 매수"
        else: 축적신호 = "red"; 축적결정 = "관망/비중축소"

        단기 = 0
        if mom5 >= 2: 단기 += 25
        elif mom5 >= 0: 단기 += 18
        elif mom5 >= -2: 단기 += 10
        else: 단기 += 3
        if rsi < 30: 단기 += 18
        elif rsi < 45: 단기 += 20
        elif rsi < 60: 단기 += 15
        elif rsi < 70: 단기 += 8
        else: 단기 += 2
        if 필반5 >= 2: 단기 += 20
        elif 필반5 >= 0: 단기 += 14
        elif 필반5 >= -2: 단기 += 7
        if 통화 == "KRW":
            if 환율5 <= -0.5: 단기 += 20
            elif 환율5 <= 0.5: 단기 += 13
            else: 단기 += 5
        else:
            단기 += 13
        if vix is not None:
            if vix < 18: 단기 += 15
            elif vix < 25: 단기 += 8
            else: 단기 += 2
        else:
            단기 += 8
        단기 = max(0, min(100, int(round(단기))))
        if 단기 >= 65: 단기신호 = "green"; 단기결정 = "단기 매수"
        elif 단기 >= 45: 단기신호 = "yellow"; 단기결정 = "중립"
        else: 단기신호 = "red"; 단기결정 = "단기 매도/관망"

        결과.append({
            "종목": 이름, "통화": 통화, "기호": 기호, "현재가": round(현재, 2),
            "이격200": round(이격200, 1), "RSI": round(rsi, 1),
            "위치52주": round(위치, 0), "mom5": round(mom5, 1),
            "축적점수": 축적, "축적신호": 축적신호, "축적결정": 축적결정,
            "단기점수": 단기, "단기신호": 단기신호, "단기결정": 단기결정,
            "밴드": [
                {"단계": "1차", "가격": round(현재 * 0.97, 2), "설명": "-3% 눌림"},
                {"단계": "2차", "가격": round(현재 * 0.93, 2), "설명": "-7% 조정"},
                {"단계": "3차", "가격": round(현재 * 0.88, 2), "설명": "-12% 조정"},
            ],
            "손절참고": round(현재 * 0.85, 2),
        })
    return {"종목": 결과, "MU30일": round(mu30, 1), "환율5일": round(환율5, 2)}


def 적중판정(신호, 익일등락):
    """마감 신호가 다음 거래일 SOXL 방향을 맞췄는지 채점.
    green=상승 예측, red=하락 예측, yellow=관망(판정 제외)."""
    if 익일등락 is None:
        return None
    if 신호 == "green":
        return "적중" if 익일등락 > 0 else "빗나감"
    if 신호 == "red":
        return "적중" if 익일등락 < 0 else "빗나감"
    return "중립"


def 일지기록(journal_path, 거래일, soxl종가, soxl등락, 점수, now):
    """거래일별 매크로 점수 일지 upsert + 익일결과 자동 채점.
    - 같은 거래일은 1건만 유지(덮어쓰기), 메모는 보존
    - 각 엔트리의 '익일등락'은 바로 다음 거래일 SOXL 등락으로 채워 채점 (다음날 검증)
    """
    try:
        with open(journal_path, encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        data = {"엔트리": []}
    엔트리 = data.get("엔트리", [])

    공통 = {
        "점수": 점수.get("점수"), "신호": 점수.get("신호"), "결정": 점수.get("결정"),
        "SOXL종가": round(soxl종가, 2), "SOXL등락": round(soxl등락, 2),
        "근거": (점수.get("근거") or [])[:3], "감점": (점수.get("감점") or [])[:3],
        "기록시각": now,
    }
    기존 = next((e for e in 엔트리 if e.get("거래일") == 거래일), None)
    if 기존:
        기존.update(공통)
    else:
        새 = {"거래일": 거래일, "익일등락": None, "익일종가": None,
              "적중": None, "메모": ""}
        새.update(공통)
        엔트리.append(새)

    # 날짜순 정렬 후 '다음 거래일' 등락으로 익일결과/적중 재계산
    엔트리.sort(key=lambda e: e.get("거래일", ""))
    for i in range(len(엔트리) - 1):
        cur, nxt = 엔트리[i], 엔트리[i + 1]
        cur["익일등락"] = nxt.get("SOXL등락")
        cur["익일종가"] = nxt.get("SOXL종가")
        cur["적중"] = 적중판정(cur.get("신호"), cur.get("익일등락"))
    if 엔트리:  # 최신 거래일은 아직 익일 결과 없음
        엔트리[-1]["익일등락"] = None
        엔트리[-1]["익일종가"] = None
        엔트리[-1]["적중"] = None

    data["엔트리"] = 엔트리
    data["갱신"] = now
    with open(journal_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return 엔트리


def SKEW분석(가격):
    """CBOE SKEW + VIX 결합으로 꼬리위험 판정 (데스크탑 _soxl_analytics.SKEW분석과 동일 출력 모양).
    PWA renderSKEW가 SKEW/SKEW_변화/위험도/VIX 필드를 기대하므로 raw 가격객체를 그대로 넣으면 안 됨."""
    skew = 가격.get("SKEW")
    vix = 가격.get("VIX")
    if not skew:
        return None
    s = skew["현재가"]
    v = vix["현재가"] if vix else None
    s_변화 = skew.get("등락률", 0)
    if s >= 145:
        위험도, 설명, 경고 = "매우 높음", "꼬리위험 극단 — 블랙스완 가능성 증대", True
    elif s >= 135:
        위험도, 설명, 경고 = "높음", "꼬리위험 누적 — 표면은 평온하지만 주의", True
    elif s >= 125:
        위험도, 설명, 경고 = "주의", "꼬리위험 약간 상승", False
    elif s >= 115:
        위험도, 설명, 경고 = "보통", "정상 범위", False
    else:
        위험도, 설명, 경고 = "낮음", "꼬리위험 안정", False
    if v is not None:
        if v < 18 and s >= 135:
            설명 += " · VIX 낮은데 SKEW 높음 = 위기 직전 시그널 (2008/2020 직전 패턴)"; 경고 = True
        elif v < 18 and s < 125:
            설명 += " · VIX/SKEW 모두 안정 (이상적)"
        elif v >= 25 and s >= 130:
            설명 += " · 양 지표 모두 위험 (조정 가능)"
    return {
        "SKEW": round(s, 1),
        "SKEW_변화": round(s_변화, 2),
        "VIX": round(v, 2) if v else None,
        "위험도": 위험도,
        "설명": 설명,
        "경고": 경고,
    }


def build_data_json(가격, 포지션, 점수):
    이벤트 = {
        "다음FOMC": 다음이벤트(FOMC_2026, "FOMC"),
        "다음CPI": 다음이벤트(CPI_2026, "CPI"),
        "다음ISM_PMI": 다음이벤트(ISM_2026, "ISM PMI"),
        "다음NFP": 다음이벤트(NFP_2026, "비농업고용"),
        "다음신규실업수당": {
            "이름": "신규실업수당",
            "일자": 다음목요일().strftime("%Y-%m-%d"),
            "남은일": (다음목요일() - datetime.now().date()).days,
        },
        "다음TSMC": TSMC매출_다음(),
    }

    # 기존 data.json의 풍부한 분석 필드 보존 (데스크탑 배포가 만든 캘린더/시나리오/섹터/뉴스 등)
    # 클라우드는 점수/SKEW/반도체축적만 계산 → 통째로 덮어쓰면 PWA의 매크로/시나리오/섹터 탭이 비어버림
    기존분석 = {}
    try:
        with open(os.path.join(APP_DIR, 'data.json'), encoding='utf-8') as f:
            기존분석 = (json.load(f).get('분석') or {})
    except Exception:
        기존분석 = {}
    분석 = dict(기존분석)
    분석.update({
        "점수": 점수,
        "SKEW": SKEW분석(가격),
        "반도체축적": 반도체축적분석(),
    })

    data = {
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M") + " UTC",
        "updated_iso": datetime.now().isoformat(),
        "포지션": 포지션,
        "시장": {
            "환율": 가격["환율"], "VIX": 가격["VIX"], "필반": 가격["필반"],
            "NVDA": 가격["NVDA"], "SOXL": 가격["SOXL"], "SOXX": 가격["SOXX"],
            "하이닉스": 가격["하이닉스"], "삼성전자": 가격.get("삼성전자"),
        },
        "금리": {
            "10년물": 가격.get("10년물"), "단기금리": 가격.get("단기금리"),
            "DXY": 가격.get("DXY"), "장단기차": None,
            "역전": False, "경고": [],
        },
        "이벤트": 이벤트,
        "분석": 분석,
    }
    if 가격.get("10년물") and 가격.get("단기금리"):
        data["금리"]["장단기차"] = round(가격["10년물"]["현재가"] - 가격["단기금리"]["현재가"], 3)

    with open(os.path.join(APP_DIR, 'data.json'), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  data.json 생성 ({os.path.getsize(os.path.join(APP_DIR, 'data.json'))} bytes)")
    return data


def main():
    오늘 = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
    한국시간 = (datetime.utcnow() + timedelta(hours=9)).strftime("%Y-%m-%d %H:%M KST")
    print("=" * 60)
    print(f"  SOXL Monitor (Cloud) - {오늘}")
    print(f"  한국시간: {한국시간}")
    print("=" * 60)

    # 환경변수 진단
    print("\n[0/5] 환경변수 진단")
    print(f"  TELEGRAM_BOT_TOKEN: {'설정됨 (' + str(len(BOT_TOKEN)) + '자)' if BOT_TOKEN else '*** 비어있음 ***'}")
    print(f"  TELEGRAM_CHAT_ID: {'설정됨 (' + CHAT_ID + ')' if CHAT_ID else '*** 비어있음 ***'}")
    print(f"  POSITION_JSON 길이: {len(POSITION_JSON_STR)}자")
    print(f"  포지션 종목 수: {len(POSITION.get('포지션', {}))}")
    for 종목, info in POSITION.get('포지션', {}).items():
        활성표시 = "활성" if info.get('활성') else "비활성"
        print(f"    - {종목}: {활성표시}, 수량 {info.get('수량', 0)}")
    print(f"  FORCE_BRIEFING: {FORCE_BRIEFING}")

    if not BOT_TOKEN or not CHAT_ID:
        print("\n*** 텔레그램 토큰 또는 채팅ID 누락. GitHub Secrets 확인 필요 ***")
        print("    Settings → Secrets and variables → Actions 에서 등록")
        # 종료하지 않고 계속 (data.json은 생성)

    print("\n[1/5] 가격 수집")
    가격 = 가격수집()
    가격 = 직전값폴백(가격)  # 수집 실패 종목은 직전 정상값 유지 (null 커밋 → 앱 크래시 방지)

    print("\n[2/5] 포지션 손익 계산")
    포지션 = 포지션손익(가격)
    print(f"  총 투자금: {포지션['총투자금']:,}원")
    print(f"  총 평가손익: {포지션['총평가손익_KRW']:+,.0f}원 ({포지션['총손익률']:+.2f}%)")

    print("\n[3/5] 매크로 분석")
    이벤트 = {
        "다음FOMC": 다음이벤트(FOMC_2026, "FOMC"),
        "다음CPI": 다음이벤트(CPI_2026, "CPI"),
    }
    점수 = 분석실행(가격, 이벤트)
    print(f"  점수: {점수['점수']}/100 ({점수['신호']}, {점수['결정']})")

    print("\n[4/5] 데이터 생성")
    data = build_data_json(가격, 포지션, 점수)

    # 매크로 점수 검증 일지 — 마감 후 브리핑 시점만 기록 (장중 부분봉 오염 방지)
    utc_hour = datetime.utcnow().hour
    soxl = 가격.get("SOXL")
    if (utc_hour in (20, 21) or FORCE_BRIEFING) and soxl:
        거래일 = soxl.get("일자") or datetime.now().strftime("%Y-%m-%d")
        kst = (datetime.utcnow() + timedelta(hours=9)).strftime("%Y-%m-%d %H:%M")
        엔트리 = 일지기록(os.path.join(APP_DIR, 'journal.json'),
                       거래일, soxl["현재가"], soxl["등락률"], 점수, kst)
        print(f"  일지 기록: {거래일} 점수 {점수['점수']}({점수['신호']}), 누적 {len(엔트리)}일")

    print("\n[5/5] 알림 발송")
    # 수동 실행 시 무조건 진단 메시지 + 브리핑
    if FORCE_BRIEFING:
        print("  수동 실행 → 강제 진단 메시지 발송")
        진단 = (
            f"✅ <b>GitHub Actions 연결 진단</b>\n"
            f"{한국시간}\n\n"
            f"환경변수 상태:\n"
            f"• 봇토큰: {'OK' if BOT_TOKEN else '누락'}\n"
            f"• 채팅ID: {'OK' if CHAT_ID else '누락'}\n"
            f"• 포지션: {len(POSITION.get('포지션', {}))}개 종목\n"
            f"• 총투자금: {포지션['총투자금']:,}원\n\n"
            f"이 메시지가 보이면 텔레그램 연결은 정상.\n"
            f"매일 한국 07:00에 정기 브리핑 자동 발송됩니다."
        )
        텔레그램(진단)
        time.sleep(1)

    알림체크(data, 점수, 포지션)
    print("  완료")


if __name__ == "__main__":
    main()
