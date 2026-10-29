"""🌙 종가 베팅: 정규장 마감 무렵(약 15:45 ET) 매수 → 다음날 프리장·시가·장중 매도.
조건 = (1) 과매도 정도  (2) 체결강도(추정)  (+ 검증으로 고른 추가 조건). 임계값은 scripts/closebet_study.py 에서
'앞 60% 기간'으로만 고르고 '뒤 40% 기간'으로 확인 (model/closebet_study.json).
체결강도는 틱 데이터가 없어 일봉·분봉으로 만든 추정치: 매수 추정 거래량 ÷ 매도 추정 거래량 × 100 (100% = 균형).
  · 일봉: 종가 위치(CLV) = ((종가-저가) - (고가-종가)) / (고가-저가) → 매수량 = 거래량×(1+CLV)/2
  · 분봉(마감 전 60분): 틱 규칙(직전 봉 종가보다 오르면 매수, 내리면 매도, 같으면 반반)"""
import json, functools
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[1]

@functools.lru_cache(maxsize=1)
def study():
    try: return json.loads((ROOT / "model/closebet_study.json").read_text())
    except Exception: return {}

def rsi(c, n):
    d = pd.Series(c).diff(); up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).fillna(100).values

def strength_clv(o, h, l, c, v):
    rng = h - l
    clv = np.where(rng > 0, ((c - l) - (h - c)) / np.where(rng > 0, rng, 1), 0.0)
    buy, sell = v * (1 + clv) / 2, v * (1 - clv) / 2
    return np.clip(buy / np.maximum(sell, 1e-9) * 100, 0, 999), clv

def strength_tick(bars):
    """bars: 분봉 DataFrame(Close, Volume) → 체결강도(추정)% (틱 규칙)."""
    if bars is None or len(bars) < 3: return None
    c = bars["Close"].astype(float).values; v = bars["Volume"].astype(float).fillna(0).values
    d = np.sign(np.diff(c)); vv = v[1:]
    up = vv[d > 0].sum() + vv[d == 0].sum() / 2; dn = vv[d < 0].sum() + vv[d == 0].sum() / 2
    if up + dn <= 0: return None
    return float(min(up / max(dn, 1e-9) * 100, 999))

def feats(px):
    """px: 일봉(date, open, high, low, close, volume) 정렬. 날짜별 종가 베팅 지표 DataFrame."""
    g = px.sort_values("date").reset_index(drop=True)
    o, h, l, c, v = (g[k].astype(float).values for k in ("open", "high", "low", "close", "volume"))
    F = pd.DataFrame({"date": pd.to_datetime(g["date"]).values, "price": c})
    cs = pd.Series(c)
    F["rsi2"] = rsi(c, 2); F["rsi14"] = rsi(c, 14)
    F["ma5"] = c / cs.rolling(5).mean().values - 1; F["ma20"] = c / cs.rolling(20).mean().values - 1
    F["dd20"] = c / pd.Series(h).rolling(20, min_periods=10).max().values - 1
    dn = (cs.diff() < 0).astype(int).values; st = np.zeros(len(c), int)
    for i in range(1, len(c)): st[i] = st[i - 1] + 1 if dn[i] else 0
    F["down_n"] = st
    lo14, hi14 = pd.Series(l).rolling(14).min().values, pd.Series(h).rolling(14).max().values
    F["stoch"] = np.where(hi14 > lo14, (c - lo14) / np.where(hi14 > lo14, hi14 - lo14, 1) * 100, 50)
    F["str_day"], F["clv"] = strength_clv(o, h, l, c, v)
    F["chg1"] = cs.pct_change().values
    F["volx"] = v / pd.Series(v).shift(1).rolling(20, min_periods=10).mean().values
    F["hold"] = np.where(h > 0, c / h, np.nan)
    F["dv20"] = (cs * pd.Series(v)).rolling(20, min_periods=10).mean().values
    # 다음날 결과 (라벨 전용)
    F["gap"] = np.r_[o[1:] / c[:-1] - 1, np.nan]; F["hi1"] = np.r_[h[1:] / c[:-1] - 1, np.nan]
    F["lo1"] = np.r_[l[1:] / c[:-1] - 1, np.nan]; F["c1"] = np.r_[c[1:] / c[:-1] - 1, np.nan]
    return F

def plan_ret(F, tp, sl, cost=0.005):
    """다음날 매도 계획 수익: 시가가 목표 이상이면 시가 매도, 시가가 손절 이하면 시가 매도, 장중 손절 먼저 닿았다고 가정(보수적) → 목표 → 아니면 종가."""
    gap, hi, lo, c1 = F["gap"].values, F["hi1"].values, F["lo1"].values, F["c1"].values
    r = np.where(gap >= tp, gap, np.where(gap <= -sl, gap, np.where(lo <= -sl, -sl, np.where(hi >= tp, tp, c1))))
    return r - cost

def check(row, rule):
    """rule: {'over': [(키, 연산, 값)...], 'str': (키, 값), 'extra': [...]} → [(이름, 맞음?, 값 문자열)]."""
    out = []
    for k, op, th in rule.get("conds", []):
        v = row.get(k)
        if v is None or (isinstance(v, float) and np.isnan(v)): out.append((k, None, "데이터 없음")); continue
        ok = v <= th if op == "<=" else v >= th
        out.append((k, bool(ok), v))
    return out

LABEL = {"rsi2": "RSI(2)", "rsi14": "RSI(14)", "ma5": "5일선 이격", "ma20": "20일선 이격", "dd20": "20일 고점 대비", "down_n": "연속 하락일",
         "stoch": "스토캐스틱(14)", "str_day": "체결강도(일봉 추정)", "str_60": "체결강도(마감 60분 추정)", "volx": "거래량(20일 평균 대비)",
         "chg1": "당일 등락", "hold": "종가/고가", "clv": "종가 위치"}

def fmtv(k, v):
    if v is None or (isinstance(v, float) and np.isnan(v)): return "데이터 없음"
    if k in ("ma5", "ma20", "dd20", "chg1"): return f"{v * 100:+.1f}%"
    if k in ("str_day", "str_60"): return f"{v:.0f}%"
    if k == "volx": return f"{v:.1f}배"
    if k == "hold": return f"{v * 100:.0f}%"
    if k == "down_n": return f"{int(v)}일"
    if k == "clv": return f"{v:+.2f}"
    return f"{v:.0f}"

# ---------------------------------------------------------------- 오늘 후보 (앱 화면용)
STR_TH = 100      # 마감 60분 체결강도(추정) 기준: 매수 추정량 ≥ 매도 추정량 (분봉 59일 검증, 참고)

def rule():
    """검증으로 고른 규칙(과매도·추가 조건) + 체결강도 조건. 반환 [(키, 연산, 값, 검증됨?)]."""
    b = (study().get("best") or {})
    conds = [tuple(c) + (True,) for c in (b.get("conds") or [("down_n", ">=", 3), ("volx", ">=", 3)])]
    if not any(c[0].startswith("str") for c in conds): conds.append(("str_60", ">=", STR_TH, False))
    return conds

def cond_name(c):
    k, op, th = c[:3]
    if k in ("ma5", "ma20", "dd20", "chg1"): t = f"{th * 100:+.0f}%"
    elif k == "hold": t = f"{th * 100:.0f}%"
    elif k == "volx": t = f"{th:g}배"
    elif k.startswith("str"): t = f"{th:g}%"
    elif k == "down_n": t = f"{th}일"
    else: t = f"{th:g}"
    return f"{LABEL.get(k, k)} {'≤' if op == '<=' else '≥'} {t}"

def evaluate(row, conds=None):
    conds = conds or rule(); res = []
    for c in conds:
        k, op, th, tested = c
        v = row.get(k)
        if v is None or (isinstance(v, float) and np.isnan(v)): res.append(dict(key=k, name=cond_name(c), ok=None, val="데이터 없음", tested=tested)); continue
        ok = v <= th if op == "<=" else v >= th
        res.append(dict(key=k, name=cond_name(c), ok=bool(ok), val=fmtv(k, v), tested=tested))
    return res

def oversold_score(r):
    """과매도 깊이 0~100 (표시·정렬용): RSI(2), 20일 고점 대비, 5일선 이격, 스토캐스틱, 연속 하락을 평균."""
    parts = []
    if r.get("rsi2") is not None: parts.append(max(0, 30 - r["rsi2"]) / 30)
    if r.get("dd20") is not None: parts.append(min(1, max(0, -r["dd20"]) / 0.6))
    if r.get("ma5") is not None: parts.append(min(1, max(0, -r["ma5"]) / 0.2))
    if r.get("stoch") is not None: parts.append(max(0, 30 - r["stoch"]) / 30)
    if r.get("down_n") is not None: parts.append(min(1, r["down_n"] / 5))
    return round(100 * float(np.mean(parts)), 0) if parts else None

def split_bars(b, minutes=60):
    """분봉 → (정규장 전체, 마지막 minutes 분)."""
    idx = b.index.tz_convert("America/New_York") if b.index.tz is not None else b.index
    hm = np.asarray(idx.hour * 60 + idx.minute)
    reg = b[(hm >= 570) & (hm < 960)]; hr = hm[(hm >= 570) & (hm < 960)]
    if not len(reg): return reg, reg
    return reg, reg[hr >= hr.max() - minutes + 1]

def candidates(daily, bars=None, conds=None):
    """daily: {ticker: 일봉 DataFrame(오늘 막대 포함)}, bars: {ticker: 오늘 분봉(Close, Volume, index=ET)}.
    반환 (qualify, near): 조건 전부 맞는 종목 / 하나만 빠진 종목. 각 항목 dict(ticker, row, checks, met, score)."""
    conds = conds or rule(); Q, N = [], []
    for t, g in daily.items():
        try:
            F = feats(g)
            if not len(F): continue
            r = F.iloc[-1].to_dict()
        except Exception: continue
        if not (0.05 <= (r.get("price") or 0) <= 15) or not (r.get("dv20") or 0) >= 100e3: continue
        b = (bars or {}).get(t)
        r["str_60"] = None
        if b is not None and len(b):
            reg, last = split_bars(b)
            r["str_60"] = strength_tick(last); r["str_dayt"] = strength_tick(reg)
            r["bar_ts"] = str(reg.index[-1])[:16] if len(reg) else None
        ch = evaluate(r, conds); met = sum(1 for c in ch if c["ok"]); miss = len(ch) - met
        item = dict(ticker=t, row=r, checks=ch, met=met, m=len(ch), over=oversold_score(r),
                    score=met * 100 + (oversold_score(r) or 0) + min((r.get("str_60") or 0), 300) / 10)
        if miss == 0: Q.append(item)
        elif miss == 1: N.append(item)
    Q.sort(key=lambda x: x["score"], reverse=True); N.sort(key=lambda x: x["score"], reverse=True)
    return Q, N

def stats_lines():
    """규칙별 과거 성적 (화면 표시용)."""
    S = study(); b = S.get("best") or {}; L = []
    if not b: return L
    te, tr = b.get("test") or {}, b.get("train") or {}
    L.append(dict(name=" + ".join(cond_name(c) for c in b["conds"]) + " (일봉, 다음날 시가 매도" + (", 사후 선택" if b.get("post_hoc") else "") + ")", tested=True,
                  train=tr, test=te, folds=b.get("folds")))
    J = S.get("intraday") or {}
    for k, nm in (("best", "위 규칙 (분봉 표본, 15:45 가격 기준)"), ("best&str_60>=100", "위 규칙 + 마감 60분 체결강도 ≥100%"), ("best&str_60<100", "위 규칙 + 체결강도 <100% (비교)"),
                  ("oversold&str_60>=150", "과매도(20일 고점 -30%↓ 또는 RSI(2)≤10) + 체결강도 ≥150%"), ("oversold&str_60<100", "과매도 + 체결강도 <100% (비교)"),
                  ("str_60>=150", "체결강도 ≥150% 만 (전체)"), ("str_60<100", "체결강도 <100% (전체, 비교)"), ("base", "아무 조건 없음 (전체 평균)")):
        if J.get(k): L.append(dict(name=nm, tested=False, intra=J[k]))
    return L

def copy_text(it, plan, link=""):
    r = it["row"]
    L = [f"🌙 {it['ticker']} 종가 베팅 후보 · ${r['price']:.4g} ({(r.get('chg1') or 0) * 100:+.1f}%) · 조건 {it['met']}/{it['m']}"]
    for c in it["checks"]: L.append(f"{'✅' if c['ok'] else ('❔' if c['ok'] is None else '❌')} {c['name']}: {c['val']}" + ("" if c["tested"] else " (참고)"))
    L.append(f"과매도 점수 {it['over']:.0f}/100 · 체결강도(추정) 마감 60분 {fmtv('str_60', r.get('str_60'))} · 일봉 {fmtv('str_day', r.get('str_day'))}")
    L += plan
    if link: L.append(f"🔗 {link}")
    L.append("※ 1분봉으로 추정한 체결강도 · 과거 검증 수치는 보장 아님 · 투자 권유 아님")
    return "\n".join(L)
