# -*- coding: utf-8 -*-
"""
SOXL <-> SOXS 스위칭 규칙기반 액션 엔진
================================================
빛날빈님 매매 스타일 전용:
  - SOXL(불) <-> SOXS(베어) 데일리 스위칭
  - 정보 기반 확률 계산 후 진입, 레버리지라 1~2일 보유 후 매도

핵심 철학:
  1~2일 방향 예측은 거의 동전던지기다. 진짜 엣지는
  (a) 횡보장(레짐) 거르기  (b) 칼같은 청산  (c) 신호 강할 때만 베팅.
  => 시스템의 가장 중요한 출력은 "오늘은 쉬어(관망)"일 수 있다.

출력: 매 실행마다 단 하나의 액션
  ENTER_SOXL / ENTER_SOXS / HOLD / EXIT / STAY_FLAT

설정(빛날빈님 확정):
  운용자금 1,000만원 / 손절 -5% / 익절 +10% / 시간손절 D+2
"""
import sys
import os
import json
import math
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding='utf-8')

import yfinance as yf
import pandas as pd
import numpy as np


# ===================== 설정 =====================
운용자금원화 = 10_000_000      # 스위칭 운용 자금
손절률 = -5.0                  # % (ETF 기준)
익절률 = 10.0                  # %
진입임계 = 40                  # |방향점수| 이 값 이상이어야 진입
풀베팅임계 = 60                # 이 값 이상이면 풀베팅, 사이면 절반
시간손절_거래일 = 2            # D+2 종가에 무조건 청산
반전청산임계 = 25              # 보유 반대방향 점수가 이 값 넘으면 신호반전 청산

포지션파일 = r"C:\Users\SAMSUNG\Dropbox\주식투자\스위칭포지션.json"


# ===================== 이벤트 블랙아웃 캘린더 (2026) =====================
# 임박 이벤트엔 신규진입 회피 (휩쏘/갭 리스크). 근사일자 — 확정 발표시 갱신.
FOMC_2026 = ["2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
             "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09"]
CPI_2026 = ["2026-01-13", "2026-02-11", "2026-03-11", "2026-04-10",
            "2026-05-12", "2026-06-10", "2026-07-14", "2026-08-12",
            "2026-09-11", "2026-10-13", "2026-11-12", "2026-12-10"]
NVDA실적_2026 = ["2026-02-25", "2026-05-27", "2026-08-26", "2026-11-18"]
# 트리플위칭 (선물옵션 동시만기, 3·6·9·12월 셋째 금요일)
트리플위칭_2026 = ["2026-03-20", "2026-06-19", "2026-09-18", "2026-12-18"]


def _남은일(일자리스트, 오늘):
    """가장 가까운 미래(또는 오늘) 이벤트까지 남은 일수. 없으면 None."""
    후보 = []
    for s in 일자리스트:
        d = datetime.strptime(s, "%Y-%m-%d").date()
        if d >= 오늘:
            후보.append((d - 오늘).days)
    return min(후보) if 후보 else None


def 블랙아웃판정(오늘=None):
    """오늘 신규진입을 피해야 하는 이벤트가 있나? (사유 리스트 반환)"""
    if 오늘 is None:
        오늘 = datetime.now().date()
    사유 = []
    f = _남은일(FOMC_2026, 오늘)
    c = _남은일(CPI_2026, 오늘)
    n = _남은일(NVDA실적_2026, 오늘)
    if f is not None and f <= 3:
        사유.append(f"FOMC D-{f}" if f else "FOMC 당일")
    if c is not None and c <= 3:
        사유.append(f"CPI D-{c}" if c else "CPI 당일")
    if n is not None and n <= 1:
        사유.append(f"NVDA실적 D-{n}" if n else "NVDA실적 당일")
    if 오늘.strftime("%Y-%m-%d") in 트리플위칭_2026:
        사유.append("트리플위칭(동시만기)")
    return 사유


# ===================== 지표 계산 =====================
def _RSI(종가, 기간=14):
    delta = 종가.diff()
    gain = delta.where(delta > 0, 0).rolling(기간).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(기간).mean()
    rs = gain / loss.replace(0, 1e-9)
    return 100 - (100 / (1 + rs))


def _ADX(고, 저, 종, 기간=14):
    """Wilder ADX — 추세 강도. 낮으면(<20) 횡보 = 레버리지 학살장."""
    up = 고.diff()
    down = -저.diff()
    plus_dm = ((up > down) & (up > 0)) * up
    minus_dm = ((down > up) & (down > 0)) * down
    tr1 = 고 - 저
    tr2 = (고 - 종.shift()).abs()
    tr3 = (저 - 종.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/기간, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1/기간, adjust=False).mean() / atr.replace(0, 1e-9))
    minus_di = 100 * (minus_dm.ewm(alpha=1/기간, adjust=False).mean() / atr.replace(0, 1e-9))
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-9)
    return dx.ewm(alpha=1/기간, adjust=False).mean()


def 지표수집():
    """SMH(반도체 기초)·NQ=F(야간선물)·VIX 지표 + SOXL/SOXS 현재가."""
    out = {}

    # --- SMH: 방향 지표의 핵심 (1배 ETF라 레버리지 노이즈 없음) ---
    for _시도 in range(3):
        try:
            h = yf.Ticker("SMH").history(period="6mo")
            if len(h) >= 30:
                break
        except Exception:
            h = None
    if h is None or len(h) < 30:
        return None

    종 = h['Close']; 고 = h['High']; 저 = h['Low']
    ema10 = 종.ewm(span=10, adjust=False).mean()
    ema20 = 종.ewm(span=20, adjust=False).mean()
    ema12 = 종.ewm(span=12, adjust=False).mean()
    ema26 = 종.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    시그널 = macd.ewm(span=9, adjust=False).mean()
    hist = macd - 시그널
    rsi5 = _RSI(종, 5)
    adx = _ADX(고, 저, 종, 14)

    종가 = float(종.iloc[-1])
    out["SMH"] = {
        "종가": 종가,
        "EMA10": float(ema10.iloc[-1]),
        "EMA20": float(ema20.iloc[-1]),
        "RSI5": float(rsi5.iloc[-1]),
        "MACD_hist": float(hist.iloc[-1]),
        "MACD_hist_전": float(hist.iloc[-2]),
        "ADX": float(adx.iloc[-1]),
        "수익2일": (종가 - float(종.iloc[-3])) / float(종.iloc[-3]) * 100 if len(종) >= 3 else 0,
        "수익1일": (종가 - float(종.iloc[-2])) / float(종.iloc[-2]) * 100 if len(종) >= 2 else 0,
    }

    # --- NQ=F: 야간 나스닥 선물 (반도체 익일 방향 선행) ---
    try:
        nq = yf.Ticker("NQ=F").history(period="5d")['Close'].dropna()
        out["NQ"] = (float(nq.iloc[-1]) - float(nq.iloc[-2])) / float(nq.iloc[-2]) * 100 if len(nq) >= 2 else 0
    except Exception:
        out["NQ"] = None

    # --- VIX ---
    try:
        v = yf.Ticker("^VIX").history(period="5d")['Close'].dropna()
        out["VIX"] = float(v.iloc[-1])
        out["VIX_변화"] = float(v.iloc[-1]) - float(v.iloc[-2]) if len(v) >= 2 else 0
    except Exception:
        out["VIX"] = None; out["VIX_변화"] = 0

    # --- SOXL / SOXS 현재가 (진입/청산·사이징용) ---
    for 종목 in ("SOXL", "SOXS"):
        try:
            p = yf.Ticker(종목).history(period="2d")['Close'].dropna()
            out[종목] = float(p.iloc[-1])
        except Exception:
            out[종목] = None

    # --- 환율 (원화 사이징용) ---
    try:
        krw = yf.Ticker("KRW=X").history(period="5d")['Close'].dropna()
        out["환율"] = float(krw.iloc[-1])
    except Exception:
        out["환율"] = 1380.0

    return out


# ===================== 방향 점수 (-100 SOXS ~ +100 SOXL) =====================
def 방향점수(지표):
    """양수=SOXL(불) 유리, 음수=SOXS(베어) 유리. 합계 ±100."""
    s = 지표["SMH"]
    점수 = 0.0
    근거 = []

    # 1. 추세 (±30) — 종가 vs EMA10/EMA20
    종가, e10, e20 = s["종가"], s["EMA10"], s["EMA20"]
    if 종가 > e10 > e20:
        점수 += 30; 근거.append("SMH 정배열(종가>EMA10>EMA20) 강세")
    elif 종가 > e10 and 종가 > e20:
        점수 += 18; 근거.append("SMH EMA 위 상승")
    elif 종가 > e20:
        점수 += 6
    elif 종가 < e10 < e20:
        점수 -= 30; 근거.append("SMH 역배열(종가<EMA10<EMA20) 약세")
    elif 종가 < e10 and 종가 < e20:
        점수 -= 18; 근거.append("SMH EMA 아래 하락")
    else:
        점수 -= 6

    # 2. 단기 모멘텀 (±25) — 2일 수익 + RSI5
    m2 = s["수익2일"]; rsi5 = s["RSI5"]
    mo = 0
    if m2 >= 2: mo += 15
    elif m2 >= 0.5: mo += 9
    elif m2 <= -2: mo -= 15
    elif m2 <= -0.5: mo -= 9
    if rsi5 >= 70: mo += 10      # 단기 강모멘텀 (추종, 역발상 감점 안 함)
    elif rsi5 >= 55: mo += 6
    elif rsi5 <= 30: mo -= 10
    elif rsi5 <= 45: mo -= 6
    점수 += max(-25, min(25, mo))
    근거.append(f"SMH 2일 {m2:+.1f}% / RSI5 {rsi5:.0f}")

    # 3. 야간 선물 (±20) — NQ=F
    nq = 지표.get("NQ")
    if nq is not None:
        if nq >= 0.6: 점수 += 20; 근거.append(f"나스닥선물 {nq:+.1f}% (강세 갭업)")
        elif nq >= 0.1: 점수 += 12
        elif nq <= -0.6: 점수 -= 20; 근거.append(f"나스닥선물 {nq:+.1f}% (약세 갭다운)")
        elif nq <= -0.1: 점수 -= 12

    # 4. 변동성 (±15) — VIX 레벨·방향. 오를수록 SOXS 편향
    vix = 지표.get("VIX"); dv = 지표.get("VIX_변화", 0)
    if vix is not None:
        v점 = 0
        if vix < 16: v점 += 9
        elif vix < 20: v점 += 4
        elif vix < 26: v점 -= 4
        else: v점 -= 9
        if dv <= -1: v점 += 6
        elif dv >= 1: v점 -= 6
        점수 += max(-15, min(15, v점))
        근거.append(f"VIX {vix:.1f} ({dv:+.1f})")

    # 5. MACD (±10) — 히스토그램 부호·기울기
    h, hp = s["MACD_hist"], s["MACD_hist_전"]
    if h > 0 and h >= hp: 점수 += 10
    elif h > 0: 점수 += 5
    elif h < 0 and h <= hp: 점수 -= 10
    elif h < 0: 점수 -= 5

    점수 = int(round(max(-100, min(100, 점수))))
    return {"점수": 점수, "근거": 근거}


# ===================== 레짐 필터 (칠 날 / 쉴 날) =====================
def 레짐판정(지표, 오늘=None):
    """추세장이면 매매, 횡보/고변동/이벤트면 관망. (가능, 사유)"""
    s = 지표["SMH"]
    adx = s["ADX"]
    vix = 지표.get("VIX"); dv = 지표.get("VIX_변화", 0)
    사유 = []

    if adx < 20:
        사유.append(f"ADX {adx:.0f}<20 (추세 없음=횡보, 레버리지 감쇠 위험)")
    if vix is not None and vix > 28 and dv > 0:
        사유.append(f"VIX {vix:.0f} 상승 (휩쏘 위험)")
    블 = 블랙아웃판정(오늘)
    if 블:
        사유.append("이벤트 임박: " + ", ".join(블))

    return (len(사유) == 0, 사유, round(adx, 0))


# ===================== 포지션 상태 =====================
def 포지션읽기():
    # 클라우드(GitHub Actions)는 env(SWITCH_POSITION_JSON)로 주입, 데스크탑은 Dropbox 파일
    env = os.environ.get("SWITCH_POSITION_JSON", "").strip()
    if env:
        try:
            return json.loads(env)
        except Exception:
            pass
    if os.path.exists(포지션파일):
        try:
            with open(포지션파일, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"보유": None, "진입가": 0, "진입일": "", "수량": 0,
            "투자금원화": 0, "환율": 1380}


def _거래일수(진입일문, 오늘=None):
    """진입일~오늘 평일 수(주말 제외 근사). 같은날=0."""
    if not 진입일문:
        return 0
    if 오늘 is None:
        오늘 = datetime.now().date()
    try:
        d0 = datetime.strptime(진입일문, "%Y-%m-%d").date()
    except Exception:
        return 0
    n = 0; cur = d0
    while cur < 오늘:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            n += 1
    return n


# ===================== 액션 결정 =====================
def 액션결정(지표, 방향, 레짐, 포지션, 오늘=None):
    dir점 = 방향["점수"]
    가능, 레짐사유, adx = 레짐
    보유 = 포지션.get("보유")

    # ----- 1) 포지션 보유 중이면 청산 규칙 먼저 (심장) -----
    if 보유 in ("SOXL", "SOXS"):
        현재가 = 지표.get(보유)
        진입가 = 포지션.get("진입가", 0)
        # 표시값(소수1자리)과 판정 기준을 일치시켜 경계 혼란 방지
        손익 = round((현재가 - 진입가) / 진입가 * 100, 1) if (현재가 and 진입가) else 0
        보유일 = _거래일수(포지션.get("진입일", ""), 오늘)

        청산사유 = None
        if 손익 <= 손절률:
            청산사유 = f"손절 {손익:+.1f}% (<= {손절률}%)"
        elif 손익 >= 익절률:
            청산사유 = f"익절 {손익:+.1f}% (>= +{익절률}%)"
        elif 보유일 >= 시간손절_거래일:
            청산사유 = f"시간손절 D+{보유일} (>= D+{시간손절_거래일})"
        else:
            # 신호 반전: 보유 반대방향 점수가 임계 넘음
            반대점 = -dir점 if 보유 == "SOXL" else dir점
            if 반대점 >= 반전청산임계:
                청산사유 = f"신호반전 (방향점수 {dir점:+d}, {보유} 불리)"

        if 청산사유:
            return {
                "액션": "EXIT", "종목": 보유, "손익": round(손익, 1),
                "보유일": 보유일, "현재가": 현재가, "진입가": 진입가,
                "한줄": f"{보유} 청산 -> {청산사유}",
                "사유": [청산사유],
            }
        return {
            "액션": "HOLD", "종목": 보유, "손익": round(손익, 1),
            "보유일": 보유일, "현재가": 현재가, "진입가": 진입가,
            "방향점수": dir점,
            "한줄": f"{보유} 홀드 (손익 {손익:+.1f}%, D+{보유일}, 청산조건 미도달)",
            "사유": [f"손절·익절·시간·반전 모두 미도달 (방향점수 {dir점:+d})"],
        }

    # ----- 2) 무포지션: 진입 여부 -----
    if not 가능:
        return {
            "액션": "STAY_FLAT", "종목": None,
            "한줄": "관망 (레짐 부적합) — " + " / ".join(레짐사유),
            "사유": 레짐사유,
        }

    if abs(dir점) < 진입임계:
        return {
            "액션": "STAY_FLAT", "종목": None,
            "한줄": f"관망 (방향점수 {dir점:+d}, |{진입임계}| 미만 = 엣지 약함)",
            "사유": [f"방향점수 {dir점:+d} 진입임계 {진입임계} 미달", f"ADX {adx:.0f} 추세장"],
        }

    # 진입!
    종목 = "SOXL" if dir점 > 0 else "SOXS"
    현재가 = 지표.get(종목)
    환율 = 지표.get("환율", 1380)
    풀 = abs(dir점) >= 풀베팅임계
    투입원화 = 운용자금원화 if 풀 else 운용자금원화 // 2
    수량 = 0; 손절가 = 익절가 = None
    if 현재가 and 환율:
        수량 = int(투입원화 / (현재가 * 환율))
        손절가 = round(현재가 * (1 + 손절률 / 100), 2)
        익절가 = round(현재가 * (1 + 익절률 / 100), 2)

    return {
        "액션": "ENTER_" + 종목, "종목": 종목,
        "방향점수": dir점, "현재가": 현재가, "수량": 수량,
        "투입원화": 투입원화, "베팅": "풀" if 풀 else "절반",
        "손절가": 손절가, "익절가": 익절가, "환율": round(환율, 1),
        "한줄": f"{종목} 진입 (점수 {dir점:+d}, {'풀' if 풀 else '절반'}베팅)",
        "사유": 방향["근거"][:4],
    }


# ===================== 카드 출력 =====================
def 액션카드(오늘=None):
    지표 = 지표수집()
    if 지표 is None:
        return {"오류": "지표 수집 실패 (yfinance)"}
    방향 = 방향점수(지표)
    레짐 = 레짐판정(지표, 오늘)
    포지션 = 포지션읽기()
    결정 = 액션결정(지표, 방향, 레짐, 포지션, 오늘)
    return {"지표": 지표, "방향": 방향, "레짐": 레짐, "포지션": 포지션, "결정": 결정}


def 요약(c=None):
    """data.json / PWA / 텔레그램용 컴팩트 dict. 데스크탑·클라우드 동일 출력(단일 엔진)."""
    if c is None:
        c = 액션카드()
    if not c or "오류" in c:
        return None
    결 = c["결정"]; 가능, 사유, adx = c["레짐"]
    out = {
        "점수": c["방향"]["점수"],
        "액션": 결["액션"],
        "종목": 결.get("종목"),
        "한줄": 결.get("한줄", ""),
        "레짐가능": bool(가능),
        "레짐사유": 사유,
        "ADX": int(adx),
        "근거": (결.get("사유") or [])[:4],
        "손절률": 손절률, "익절률": 익절률, "시간손절": 시간손절_거래일,
        "운용자금": 운용자금원화,
        "갱신": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    # 액션별 부가 필드 (있을 때만)
    for k in ("현재가", "손절가", "익절가", "수량", "베팅", "투입원화",
              "손익", "보유일", "진입가", "방향점수"):
        if k in 결:
            out[k] = 결[k]
    return out


def _출력(c):
    if "오류" in c:
        print("[오류]", c["오류"]); return
    결정 = c["결정"]; 방향 = c["방향"]; 레짐 = c["레짐"]; s = c["지표"]["SMH"]
    가능, 레짐사유, adx = 레짐
    print("=" * 52)
    print(f"  SOXL/SOXS 스위칭 액션  ({datetime.now():%Y-%m-%d %H:%M})")
    print("=" * 52)
    print(f"  방향점수 : {방향['점수']:+d}   (-100 SOXS  ~  +100 SOXL)")
    print(f"  레짐     : {'매매 가능(추세장)' if 가능 else '관망(쉴 날)'}   ADX {adx:.0f}")
    if 레짐사유:
        for r in 레짐사유:
            print(f"             - {r}")
    print("-" * 52)
    print(f"  >>> 액션 : {결정['액션']}")
    print(f"      {결정['한줄']}")
    if 결정["액션"].startswith("ENTER"):
        print(f"      현재가 : ${결정['현재가']}  x {결정['수량']}주  ({결정['베팅']}베팅 {결정['투입원화']:,}원)")
        print(f"      손절   : ${결정['손절가']} ({손절률}%)   익절 : ${결정['익절가']} (+{익절률}%)")
        print(f"      시간손절: D+{시간손절_거래일} 종가")
    elif 결정["액션"] in ("HOLD", "EXIT"):
        print(f"      {결정['종목']} ${결정['진입가']} -> ${결정['현재가']}  손익 {결정['손익']:+.1f}%  (D+{결정['보유일']})")
    print("-" * 52)
    print("  근거:")
    for r in 결정.get("사유", []):
        print(f"   - {r}")
    print("=" * 52)


if __name__ == "__main__":
    _출력(액션카드())
