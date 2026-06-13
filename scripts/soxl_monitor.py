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
        try:
            t = yf.Ticker(티커)
            hist = t.history(period="3mo")
            현재가 = float(hist['Close'].iloc[-1])
            전일가 = float(hist['Close'].iloc[-2]) if len(hist) >= 2 else 현재가
            등락 = ((현재가 - 전일가) / 전일가) * 100
            spark = [round(float(x), 4) for x in hist['Close'].tail(60).tolist()]
            결과[이름] = {
                "현재가": round(현재가, 4), "전일가": round(전일가, 4),
                "등락률": round(등락, 2), "스파크라인": spark, "티커": 티커,
            }
            print(f"  [{이름:8}] {현재가:>12,.2f}  ({등락:+.2f}%)")
        except Exception as e:
            결과[이름] = None
            print(f"  [{이름}] 실패: {e}")
    return 결과


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
    """간소화된 매크로 점수 계산"""
    점수 = 0
    근거 = []
    감점 = []

    # 금리
    t10 = 가격.get("10년물")
    if t10:
        수준 = t10["현재가"]
        bp = (t10["현재가"] - t10["전일가"]) * 100
        if 수준 < 4.0: 점수 += 15; 근거.append(f"10년물 {수준:.2f}% (낮음)")
        elif 수준 < 4.5: 점수 += 11; 근거.append(f"10년물 {수준:.2f}% (보통)")
        elif 수준 < 4.8: 점수 += 5; 감점.append(f"10년물 {수준:.2f}% (높음)")
        if bp >= 10: 점수 -= 5; 감점.append(f"10년물 +{bp:.0f}bp 급등")
        elif bp <= -10: 점수 += 5; 근거.append(f"10년물 {bp:.0f}bp 급락")

    # VIX
    vix = 가격.get("VIX")
    if vix:
        v = vix["현재가"]
        if v < 15: 점수 += 10; 근거.append(f"VIX {v:.1f} (안정)")
        elif v < 20: 점수 += 7
        elif v < 25: 점수 += 3; 감점.append(f"VIX {v:.1f} (주의)")

    # DXY
    dxy = 가격.get("DXY")
    if dxy:
        d = dxy["현재가"]
        if d < 100: 점수 += 15; 근거.append(f"DXY {d:.1f} (약달러)")
        elif d < 103: 점수 += 10
        elif d < 105: 점수 += 5; 감점.append(f"DXY {d:.1f} (강달러)")
        if dxy["등락률"] >= 0.5:
            점수 -= 3; 감점.append(f"DXY +{dxy['등락률']:.2f}% 급등")

    # 모멘텀
    sox = 가격.get("필반")
    if sox:
        sp = sox.get("스파크라인", [])
        if len(sp) >= 5:
            m = (sp[-1] - sp[-5]) / sp[-5] * 100
            if m >= 3: 점수 += 10; 근거.append(f"반도체 5일 +{m:.1f}%")
            elif m >= 0: 점수 += 7
            elif m >= -3: 점수 += 3
            else: 감점.append(f"반도체 5일 {m:.1f}%")

    # 이벤트
    fomc = 이벤트.get("다음FOMC")
    cpi = 이벤트.get("다음CPI")
    가까움 = None
    if fomc and cpi:
        가까움 = fomc if fomc["남은일"] <= cpi["남은일"] else cpi
    elif fomc: 가까움 = fomc
    elif cpi: 가까움 = cpi
    if 가까움:
        남 = 가까움["남은일"]
        if 남 > 7: 점수 += 10
        elif 남 > 3: 점수 += 5; 감점.append(f"{가까움['이름']} D-{남}일")
        else: 감점.append(f"{가까움['이름']} D-{남}일 (임박)")

    # HYG + BTC (위험선호)
    hyg = 가격.get("HYG")
    btc = 가격.get("BTC")
    if hyg and btc:
        h5 = (hyg["스파크라인"][-1] - hyg["스파크라인"][-5]) / hyg["스파크라인"][-5] * 100 if len(hyg.get("스파크라인",[])) >= 5 else 0
        b5 = (btc["스파크라인"][-1] - btc["스파크라인"][-5]) / btc["스파크라인"][-5] * 100 if len(btc.get("스파크라인",[])) >= 5 else 0
        if h5 >= 0.5 and b5 >= 3:
            점수 += 10; 근거.append(f"HYG/BTC 동반 강세")
        elif h5 >= 0 and b5 >= 0:
            점수 += 6
        else:
            점수 += 2

    # TLT + MOVE (유동성)
    tlt = 가격.get("TLT")
    move = 가격.get("MOVE")
    if tlt:
        sp = tlt.get("스파크라인", [])
        t5 = (sp[-1] - sp[-5]) / sp[-5] * 100 if len(sp) >= 5 else 0
        if t5 >= 1: 점수 += 5; 근거.append(f"TLT 5일 +{t5:.1f}%")
        elif t5 >= -1: 점수 += 3
    if move:
        m = move["현재가"]
        if m < 80: 점수 += 5; 근거.append(f"MOVE {m:.0f} (안정)")
        elif m < 100: 점수 += 3
        elif m < 120: 점수 += 1
        else: 감점.append(f"MOVE {m:.0f} (불안)")

    # SKEW
    skew = 가격.get("SKEW")
    if skew:
        s = skew["현재가"]
        v = vix["현재가"] if vix else 999
        if s >= 145:
            점수 -= 10; 감점.append(f"SKEW {s:.0f} 극단 (블랙스완 경고)")
        elif s >= 135:
            점수 -= 5; 감점.append(f"SKEW {s:.0f} 높음 (꼬리위험)")
        if v < 18 and s >= 135:
            점수 -= 3; 감점.append("VIX 낮고 SKEW 높음 = 위기 직전 패턴")

    점수 = max(0, min(100, int(round(점수))))
    if 점수 >= 70: 신호 = "green"; 결정 = "진입 유리"
    elif 점수 >= 45: 신호 = "yellow"; 결정 = "관망 권고"
    else: 신호 = "red"; 결정 = "신규 진입 회피"

    return {
        "점수": 점수, "신호": 신호, "결정": 결정,
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

    # 5. 정기 브리핑 (UTC 22시=한국 07시 또는 수동 실행 시)
    # GitHub Actions는 UTC 시간으로 작동
    utc_hour = datetime.utcnow().hour
    아침브리핑타이밍 = utc_hour in (21, 22, 23) or FORCE_BRIEFING
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
            f"<b>매크로 점수: {점수['점수']}/100</b> ({점수['결정']})\n\n"
            f"<b>총 평가손익: {손익부호}{총손익:,.0f}원</b> ({총퍼센트:+.2f}%)\n"
            + "\n".join(포지션라인) + "\n\n"
            f"<b>호재</b>\n• " + "\n• ".join(점수['근거']) if 점수['근거'] else "호재: 없음"
        )
        브리핑 += (
            f"\n\n<b>위험</b>\n• " + "\n• ".join(점수['감점']) if 점수['감점'] else "\n\n위험: 없음"
        )
        알림목록.insert(0, 브리핑)

    # 발송
    발송수 = 0
    for msg in 알림목록:
        if 텔레그램(msg):
            발송수 += 1
            time.sleep(0.5)  # 텔레그램 rate limit 방지
    print(f"  텔레그램 {발송수}건 발송")


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
        "분석": {
            "점수": 점수,
            "SKEW": 가격.get("SKEW"),
        },
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
