"""추천 매수가: 종목별 가격 레벨(이동평균선·VWAP·숏 평균 진입가·직전 돌파·저가)을 후보로 만들고,
백테스트(scripts/buy_price.py → model/buy_price.json)에서 측정한 '다음 거래일 체결 확률'과 '체결 후 결과'로 고른다.
숫자는 모두 백테스트 JSON 에서 읽는다 (없으면 '근거 부족'으로 표시)."""
import json, math
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[1]
STATS_PATH = ROOT / "model" / "buy_price.json"
LEVEL_KO = {"ma5": "5일선", "ma10": "10일선", "ma20": "20일선", "ma60": "60일선",
            "vwap5": "최근 5일 VWAP(거래량 가중 평균가)", "short5": "최근 5일 숏 평균 진입가(추정)",
            "brk20": "직전 20일 고점(돌파 후 지지)", "low0": "오늘(신호일) 저가", "atr": "변동폭(ATR) 기준 눌림"}
MIN_GAP = 0.005      # 현재가보다 최소 0.5% 아래만 후보
MAX_ATR = 3.0        # ATR 3배보다 깊으면 후보 제외

_stats = None
def stats():
    global _stats
    if _stats is None:
        try: _stats = json.loads(STATS_PATH.read_text(encoding="utf-8"))
        except Exception: _stats = {}
    return _stats

def atr14(px):
    if len(px) < 15: return None
    h, l, c = px["high"].values.astype(float), px["low"].values.astype(float), px["close"].values.astype(float)
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    return float(np.mean(tr[-14:]))

def levels(px, sv=None):
    """px: asof 까지(포함) 일봉 (date, open, high, low, close, volume). 반환 {종류: 가격}. 미래 정보 없음."""
    out = {}
    if px is None or len(px) < 5: return out
    c = px["close"].astype(float)
    for n in (5, 10, 20, 60):
        if len(c) >= n: out[f"ma{n}"] = float(c.tail(n).mean())
    tail = px.tail(5)
    tp = (tail["high"] + tail["low"] + tail["close"]).astype(float) / 3
    if "volume" in tail and tail["volume"].fillna(0).sum() > 0:
        out["vwap5"] = float((tp * tail["volume"].fillna(0)).sum() / tail["volume"].fillna(0).sum())
    if sv is not None and len(sv):
        s = sv[sv["date"].isin(tail["date"])].merge(tail[["date", "high", "low", "close"]], on="date")
        if len(s) >= 3 and s["short_vol"].fillna(0).sum() > 0:
            tps = (s["high"] + s["low"] + s["close"]) / 3
            out["short5"] = float((tps * s["short_vol"].fillna(0)).sum() / s["short_vol"].fillna(0).sum())
    if len(px) >= 24:
        out["brk20"] = float(px["high"].iloc[-23:-3].max())      # 최근 3일 제외한 직전 20일 고점
    out["low0"] = float(px["low"].iloc[-1])
    return out

def fill_prob(k_atr, S=None, days=1):
    """백테스트에서 측정한 'k×ATR 아래 지정가가 days 거래일 안에 체결된 비율' (구간 선형 보간)."""
    S = S or stats(); g = S.get("grid") or []
    if not g: return None
    ks = [r["k"] for r in g]; ps = [r[f"fill{days}"] for r in g]
    return float(np.interp(k_atr, ks, ps))

def depth_for_prob(pmin, S=None):
    S = S or stats(); g = S.get("grid") or []
    ok = [r["k"] for r in g if r["fill1"] >= pmin]
    return max(ok) if ok else None

def choose_deepest(price, atr, lv, stop, S=None, pmin=0.4):
    """(비교용·채택 안 함) 체결확률 >= pmin 인 후보 중 가장 깊은 레벨. 표본외에서 -5% 지정가보다 나쁘지 않았지만 낫지도 않았음."""
    S = S or stats()
    if not price or not atr or atr <= 0: return None
    floor = (stop or 0) * 1.02
    cands = []
    for k, v in lv.items():
        if not v or v >= price * (1 - MIN_GAP) or v <= floor: continue
        d = (price - v) / atr
        if d > MAX_ATR: continue
        pf = fill_prob(d, S)
        if pf is None: continue
        cands.append(dict(kind=k, price=float(v), k_atr=float(d), fill=pf))
    ok = [c for c in cands if c["fill"] >= pmin]
    if ok:
        best = min(ok, key=lambda c: c["price"])
    else:
        kd = depth_for_prob(pmin, S)
        if kd is None: return None
        v = price - kd * atr
        if v <= floor: return None
        best = dict(kind="atr", price=float(v), k_atr=float(kd), fill=fill_prob(kd, S))
    best["confluence"] = [c["kind"] for c in cands if c is not best and abs(c["price"] - best["price"]) <= 0.25 * atr]
    best["cands"] = sorted(cands, key=lambda c: -c["price"])
    return best

SNAP_ATR = 0.3       # -5% 가격에서 ATR 0.3배 이내에 '검증된 레벨'이 있으면 그 레벨로 맞춤 (scripts/buy_price.py snap 0.3)
PULL = 0.05          # 기본 규칙: 기준가(신호일 종가) -5% 지정가, 다음 거래일 1일 유효
MA_KEYS = ("ma5", "ma10", "ma20", "ma60")

def _lv_stat(S, k):
    d = (S.get("levels_detail") or {}).get(k) or {}
    return d.get("f2_5") or d.get("all") or (S.get("levels") or {}).get(k) or {}

def _pf(v): return f"{v * 100:+.1f}%"
def _ci(c): return f"{c[0] * 100:+.1f}~{c[1] * 100:+.1f}%"

def choose(price, atr, lv, stop, S=None):
    """백테스트로 고른 규칙(표본외 폴드 2~5 검증):
    기본 = 기준가 × 0.95 지정가. 그 가격에서 ATR 0.3배 이내에 '과거 폴드에서 체결 후 기대값이 +였던 레벨'
    (S['snap_live_types'], 현재 20일선·60일선·숏 평균가)이 있으면 가장 가까운 그 레벨로 맞춘다.
    -5% 가격이 손절선 ×1.01 이하이면 추천하지 않음(백테스트도 미매매 처리)."""
    S = S or stats()
    if not price or not atr or atr <= 0: return None
    base = price * (1 - PULL)
    if stop and base <= stop * 1.01:
        return {"kind": None, "price": None, "base": base, "reason": "stop"}
    ok = S.get("snap_live_types") or []
    c = sorted((abs(lv[k] - base), k) for k in ok if lv.get(k) and abs(lv[k] - base) <= SNAP_ATR * atr and lv[k] > (stop or 0) * 1.01)
    if c:
        k = c[0][1]; best = dict(kind=k, price=float(lv[k]))
    else:
        best = dict(kind="pct5", price=float(base))
    best["base"] = base; best["k_atr"] = (price - best["price"]) / atr
    best["confluence"] = [k for k, v in lv.items() if v and k != best["kind"] and abs(v - best["price"]) <= 0.25 * atr]
    return best

def recommend(px, sv, price, stop, p=None, S=None, alert=False, ivwap=None):
    """화면·알림용 추천 매수가 묶음. px/sv 는 현재 시점까지의 데이터(미래 정보 없음)."""
    S = S or stats()
    if not S or px is None or len(px) < 20 or not price: return None
    atr = atr14(px); lv = levels(px, sv)
    best = choose(price, atr, lv, stop, S)
    if not best: return None
    ref = {k: {"price": v, "pct": (v / price - 1) * 100, "name": LEVEL_KO.get(k, k)} for k, v in lv.items() if k in MA_KEYS}
    if ivwap: ref["ivwap"] = {"price": ivwap, "pct": (ivwap / price - 1) * 100, "name": "오늘 장중 VWAP"}
    if best["price"] is None:
        return {"price": None, "reason": "stop", "base": best["base"], "stop": stop, "ref": ref, "atr": atr, "refp": price,
                "evidence": [f"−5% 가격 ${best['base']:.3f}가 손절선 ${stop:.3f}에 너무 가까워(1% 이내) 지정가를 추천하지 않습니다 — 백테스트에서도 이런 경우는 매매하지 않음으로 계산했습니다."],
                "weak": []}
    P5 = S.get("pull5_f2_5") or {}; B0 = S.get("baseline_f2_5") or {}
    sn = ((S.get("snap") or {}).get(str(SNAP_ATR)) or {}).get("f2_5") or {}
    rec = best["price"]; half = 0.15 * atr
    lo, hi = max(rec - half, (stop or 0) * 1.01), min(rec + half, price * (1 - MIN_GAP / 2))
    cost = ((p or {}).get("fee_rate", 0.1) + (p or {}).get("slippage", 0.2)) / 100 if p else 0.003
    be = rec * (1 + cost) / (1 - cost)
    pct = (rec / price - 1) * 100
    kind = best["kind"]; name = "기준가 −5%" if kind == "pct5" else LEVEL_KO.get(kind, kind)
    ev = []
    if kind == "pct5":
        ev.append(f"기준가 ${price:.3f}의 −5% = ${rec:.3f}. 근처(±ATR 0.3배)에 과거 성적이 좋았던 20일선·60일선·숏 평균가가 없어 −5% 그대로 씁니다.")
    else:
        ev.append(f"{name} ${rec:.3f}({pct:+.1f}%)가 −5% 가격 ${best['base']:.3f} 바로 근처라 그 선에 맞췄습니다 — 과거 이 선 터치 매수의 체결 후 평균이 +였던 선입니다.")
    R = sn if sn.get("n_trade") else P5
    if R.get("n_trade") and B0.get("exp_trade") is not None:
        ev.append(f"이 규칙을 과거 경보 {R['n_sig']}건(표본외)에 적용: 다음 날 체결 {R['fill'] * 100:.0f}%, 체결 시 10일 평균 {_pf(R['exp_trade'])}(95% CI {_ci(R['ci_trade'])}) — "
                  f"같은 신호를 종가에 바로 사면 {_pf(B0['exp_trade'])}(CI {_ci(B0['ci_trade'])})로 확실히 손해였습니다.")
    if kind in MA_KEYS or kind == "short5":
        L = _lv_stat(S, kind)
        if L.get("n_trade"):
            ev.append(f"{name} 단독 테스트(그 선이 어디 있든 그 가격에 지정가): 체결 {L['fill'] * 100:.0f}% · {L['n_trade']}건 평균 {_pf(L['exp_trade'])}(CI {_ci(L['ci_trade'])}). 10일선은 {_pf(_lv_stat(S, 'ma10').get('exp_trade', 0))}로 유일하게 확실히 나빴던 선이라 쓰지 않습니다.")
    conf = [LEVEL_KO.get(k, k) for k in best["confluence"] if k in MA_KEYS or k in ("short5", "vwap5", "low0")]
    if conf: ev.append("같은 가격대(±ATR 0.25배)에 " + " · ".join(conf[:3]) + "도 겹쳐 있습니다.")
    weak = ["신뢰구간이 0을 포함 — '종가 추격 매수보다 덜 나빴다'는 건 확실하지만, 이 가격에 사면 돈을 번다는 증명은 아님",
            f"이동평균선끼리 비교하면 차이가 통계적으로 구분되지 않음(20일선 {_pf(_lv_stat(S, 'ma20').get('exp_trade', 0))}, 60일선 {_pf(_lv_stat(S, 'ma60').get('exp_trade', 0))}은 점추정만 좋음)",
            "일봉 저가가 닿으면 체결로 계산(실제 체결은 더 적을 수 있음) · 미체결이면 그날은 매수하지 않는 것"]
    if not alert: weak.append("통계는 경보(상위 5%) 신호 기준 — 경보가 아닌 종목엔 그대로 맞지 않을 수 있음")
    fill = fill_prob(best["k_atr"], S)   # 이 종목의 변동폭(ATR) 대비 깊이로 본 과거 다음 날 체결률
    return {"price": rec, "lo": lo, "hi": hi, "kind": kind, "name": name, "fill": fill, "fill_avg": (sn or P5).get("fill"), "k_atr": best["k_atr"],
            "atr": atr, "stop": stop, "break_even": be, "evidence": ev, "weak": weak, "levels": lv, "ref": ref,
            "pct": pct, "refp": price, "base": best["base"], "snap_stats": sn, "pull5": P5, "base0": B0}
