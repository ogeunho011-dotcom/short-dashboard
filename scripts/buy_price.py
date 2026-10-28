"""추천 매수가 근거 백테스트 (룩어헤드 없음).
- 신호: entry_timing 과 동일 (셋업 재학습 상위 5% + 유효 + 10일 쿨다운, 912건, 5폴드 워크포워드)
- 레벨: 신호일 종가까지의 데이터로 5/10/20/60일선, 5일 VWAP, 5일 숏 평균 진입가(추정), 직전 20일 고점, 신호일 저가
- 각 레벨에 지정가 → 다음 거래일(1일)/3일 안 체결 여부, 체결 후 entry_timing 과 같은 청산 규칙(손절 우선·50% 익절·본전·비용 0.6%)
- 깊이 곡선: ATR 의 k배 아래 지정가의 체결률 + 결과 (k=0.1~3.0)
- 추천 규칙(core.buyprice.choose: 체결확률 >= pmin 인 가장 깊은 레벨) 을 중첩 표본외로 평가: 폴드 k 는 폴드 1..k-1 로 만든 곡선·pmin 사용
출력: model/buy_price.json"""
import sys, json, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
src_ = (ROOT / "scripts/entry_timing.py").read_text(encoding="utf-8")
exec(compile(src_[:src_.index("t0 = time.time()")], "entry_timing_prefix", "exec"), globals())
from core import buyprice as BP, db as DB

tick = sorted(set(df.ticker.values[IDX]))

import sqlite3
con = sqlite3.connect(ROOT / "data/shortdash.sqlite")
PXV = pd.read_sql("SELECT ticker,date,open,high,low,close,volume FROM prices WHERE ticker IN (%s)" % ",".join("?" * len(tick)), con, params=tick)
SVV = pd.read_sql("SELECT ticker,date,short_vol FROM short_vol WHERE ticker IN (%s)" % ",".join("?" * len(tick)), con, params=tick)
for d_ in (PXV, SVV): d_["date"] = pd.to_datetime(d_["date"])
PXG = {t: g.sort_values("date").reset_index(drop=True) for t, g in PXV.groupby("ticker")}
SVG = {t: g.sort_values("date").reset_index(drop=True) for t, g in SVV.groupby("ticker")}

def sim_limit(i, lim, D):
    wv = window(i)
    if wv is None: return None
    d0, o, h, l, c = wv
    price, rl, stop, ph = float(SX.price.values[i]), float(SX.rl.values[i]), float(SX.stop.values[i]), float(SX.ph.values[i])
    for j in range(D):
        if h[j] >= rl and l[j] > lim: return dict(filled=0, ret=0.0, hit=0)
        if l[j] <= lim:
            e = min(o[j], lim); r, hit, _ = manage(o, h, l, c, j, e, rl, stop, ph); return dict(filled=1, ret=r, hit=hit)
    return dict(filled=0, ret=0.0, hit=0)

KS = [round(0.1 * x, 1) for x in range(1, 31)]
INFO = {}
t0 = time.time()
for i in IDX:
    wv = window(i)
    if wv is None: continue
    t = df.ticker.values[i]; d = pd.Timestamp(df["asof"].values[i])
    g = PXG.get(t)
    if g is None: continue
    hist = g[g.date <= d]
    if len(hist) < 25: continue
    atr = BP.atr14(hist)
    if not atr: continue
    sv = SVG.get(t); sv = sv[sv.date <= d] if sv is not None else None
    lv = BP.levels(hist, sv)
    price, stop = float(SX.price.values[i]), float(SX.stop.values[i])
    _, o, h, l, c = wv
    grid = {}
    for k in KS:
        lim = price - k * atr
        r = dict(t1=int(l[0] <= lim), t3=int(l[:3].min() <= lim))
        if lim > stop * 1.01: r["sim"] = sim_limit(i, lim, 1)
        grid[k] = r
    lvr = {}
    for kd, v in lv.items():
        if not v or v >= price * (1 - BP.MIN_GAP) or v <= stop * 1.02 or (price - v) / atr > BP.MAX_ATR: continue
        lvr[kd] = dict(price=v, k=(price - v) / atr, s1=sim_limit(i, v, 1), s3=sim_limit(i, v, 3))
    INFO[i] = dict(atr=atr, lv=lv, grid=grid, lvr=lvr, price=price, stop=stop)
print("prepared", len(INFO), "of", len(IDX), round(time.time() - t0), "s", flush=True)
CLOSE = {i: run_rule(i, ("close",)) for i in INFO}
PULL5 = {i: run_rule(i, ("pull", 0.05, 1)) for i in INFO}

def agg(rows):
    """rows: list of dict(filled, ret, hit) (미체결 ret 0)"""
    rows = [r for r in rows if r is not None]
    if not rows: return dict(n_sig=0)
    sig = np.array([r["ret"] for r in rows]); fil = np.array([r["filled"] for r in rows]).astype(bool)
    tr = sig[fil]; hits = np.array([r["hit"] for r in rows])[fil]
    return dict(n_sig=len(rows), fill=float(fil.mean()), n_trade=int(fil.sum()),
                exp_trade=float(tr.mean()) if len(tr) else None, ci_trade=boot(tr) if len(tr) > 1 else None,
                exp_signal=float(sig.mean()), ci_signal=boot(sig) if len(sig) > 1 else None,
                hit=float(hits.mean()) if len(hits) else None, hit_ci=wil(int(hits.sum()), int(len(hits))) if len(hits) else None)

def build_grid(ks_folds):
    out = []
    ids = [i for i in INFO if FOLD[i] in ks_folds]
    for k in KS:
        t1 = np.mean([INFO[i]["grid"][k]["t1"] for i in ids]); t3 = np.mean([INFO[i]["grid"][k]["t3"] for i in ids])
        sims = [INFO[i]["grid"][k]["sim"] for i in ids if "sim" in INFO[i]["grid"][k]]
        a = agg(sims)
        out.append(dict(k=k, n_sig=len(ids), fill1=float(t1), fill3=float(t3), n_fill=a.get("n_trade", 0), exp_trade=a.get("exp_trade"),
                        ci_trade=a.get("ci_trade"), hit=a.get("hit")))
    return out

ALLF = {1, 2, 3, 4, 5}; OOS = {2, 3, 4, 5}
OUT = {"created": time.strftime("%Y-%m-%d %H:%M KST"), "n_signals": len(INFO), "cost": COST, "H": H,
       "note": "지정가 = 일봉 저가가 닿으면 체결(낙관적). 체결 당일은 손절만 인정. 미체결 신호 수익 0.",
       "grid": build_grid(ALLF)}
LV = {}
for kd in ["ma5", "ma10", "ma20", "ma60", "vwap5", "short5", "brk20", "low0"]:
    for tag, fs in (("all", ALLF), ("f2_5", OOS)):
        ids = [i for i in INFO if FOLD[i] in fs and kd in INFO[i]["lvr"]]
        a1 = agg([INFO[i]["lvr"][kd]["s1"] for i in ids]); a3 = agg([INFO[i]["lvr"][kd]["s3"] for i in ids])
        same = agg([CLOSE[i] for i in ids])
        n_all = sum(1 for i in INFO if FOLD[i] in fs)
        rec = dict(a1, eligible_share=len(ids) / n_all if n_all else None, depth_pct_med=float(np.median([1 - INFO[i]["lvr"][kd]["price"] / INFO[i]["price"] for i in ids])) if ids else None,
                   k_atr_med=float(np.median([INFO[i]["lvr"][kd]["k"] for i in ids])) if ids else None,
                   d3=a3, close_same=dict(exp_trade=same.get("exp_trade"), ci_trade=same.get("ci_trade"), hit=same.get("hit")))
        LV.setdefault(kd, {})[tag] = rec
OUT["levels_detail"] = LV
OUT["levels"] = {k: dict(v["all"], name=BP.LEVEL_KO[k]) for k, v in LV.items()}   # 앱 표시용 (전체 폴드)
OUT["baseline"] = agg(list(CLOSE.values())); OUT["baseline_f2_5"] = agg([CLOSE[i] for i in INFO if FOLD[i] in OOS])
OUT["pull5_f2_5"] = agg([PULL5[i] for i in INFO if FOLD[i] in OOS])

def apply_rule(i, S, pmin):
    x = INFO[i]
    b = BP.choose_deepest(x["price"], x["atr"], x["lv"], x["stop"], S, pmin)
    if not b: return None, None
    if b["kind"] != "atr" and b["kind"] in x["lvr"]: return x["lvr"][b["kind"]]["s1"], b["kind"]
    return sim_limit(i, b["price"], 1), b["kind"]

PMINS = [0.3, 0.4, 0.5, 0.6]
fixed = {}
for pm in PMINS:
    S = {"grid": OUT["grid"]}
    rr = {i: apply_rule(i, S, pm) for i in INFO}
    fixed[pm] = rr
nested, chosen, kinds = [], [], {}
for k in range(2, 6):
    prev = set(range(1, k)); S = {"grid": build_grid(prev)}
    def val(pm):
        v = [apply_rule(i, S, pm)[0] for i in INFO if FOLD[i] in prev]
        return np.mean([r["ret"] if r else 0.0 for r in v])
    pm = max(PMINS, key=val); chosen.append(pm)
    for i in INFO:
        if FOLD[i] == k:
            r, kd = apply_rule(i, S, pm)
            nested.append(r if r else dict(filled=0, ret=0.0, hit=0)); kinds[kd] = kinds.get(kd, 0) + 1
OUT["rule"] = dict(desc="체결확률(다음 거래일) >= pmin 인 후보 레벨 중 가장 깊은 가격, 없으면 ATR 깊이(체결확률≈pmin)",
                   nested=agg(nested), nested_pmin=chosen, nested_kinds=kinds,
                   fixed={str(pm): dict(all=agg([v[0] or dict(filled=0, ret=0.0, hit=0) for v in rr.values()]),
                                         f2_5=agg([v[0] or dict(filled=0, ret=0.0, hit=0) for i, v in rr.items() if FOLD[i] in OOS])) for pm, rr in fixed.items()})
best_all = max(PMINS, key=lambda pm: OUT["rule"]["fixed"][str(pm)]["all"]["exp_signal"])
OUT["rule"]["pmin_live"] = max(set(chosen), key=chosen.count)
OUT["rule"]["pmin_best_all"] = best_all
json.dump(OUT, open(ROOT / "model/buy_price.json", "w"), ensure_ascii=False, indent=1, default=float)
f = lambda v: "None" if v is None else f"{v * 100:+.2f}%"
for k, v in LV.items():
    a = v["f2_5"]; print(f"{k:7s} elig {a['eligible_share'] or 0:.2f} depth {a['depth_pct_med'] or 0:.3f} fill {a.get('fill', 0):.2f} n {a.get('n_trade', 0)} exp_t {f(a.get('exp_trade'))} {a.get('ci_trade')} hit {a.get('hit')} | same-close {f(a['close_same']['exp_trade'])} | d3 exp {f(a['d3'].get('exp_trade'))} fill {a['d3'].get('fill')}")
print("grid", [(g["k"], round(g["fill1"], 2), g["n_fill"], None if g["exp_trade"] is None else round(g["exp_trade"] * 100, 2)) for g in OUT["grid"]][::3])
print("rule nested", OUT["rule"]["nested"], chosen, kinds)
for pm in PMINS: print(pm, OUT["rule"]["fixed"][str(pm)]["f2_5"])
print("base f2_5", OUT["baseline_f2_5"]); print("pull5 f2_5", OUT["pull5_f2_5"])

# ---- 변형 B "스냅": 검증된 기본(종가 -5% 지정가·1일)에서, 이전 폴드에서 체결 후 평균이 양수였던 레벨(표본>=20)이
#      기본가 ±SNAP×ATR 안에 있으면 그 레벨 가격으로 옮김. 폴드 k 의 레벨 선택은 폴드 1..k-1 로만.
def type_ok(prev):
    ok = []
    for kd in ["ma5", "ma10", "ma20", "ma60", "vwap5", "short5", "brk20", "low0"]:
        ids = [i for i in INFO if FOLD[i] in prev and kd in INFO[i]["lvr"]]
        a = agg([INFO[i]["lvr"][kd]["s1"] for i in ids])
        if a.get("n_trade", 0) >= 20 and a["exp_trade"] > 0: ok.append(kd)
    return ok

def snap_rule(i, okt, snap):
    x = INFO[i]; base = x["price"] * 0.95
    if base <= x["stop"] * 1.01: return dict(filled=0, ret=0.0, hit=0), None
    c = [(abs(x["lvr"][k]["price"] - base), k) for k in okt if k in x["lvr"] and abs(x["lvr"][k]["price"] - base) <= snap * x["atr"]]
    if c:
        k = min(c)[1]; return x["lvr"][k]["s1"], k
    return PULL5[i], "pct5"

SNAPS = [0.15, 0.3, 0.5]
snap_out = {}
for snap in SNAPS:
    rows, kinds_s, oks = [], {}, []
    for k in range(2, 6):
        okt = type_ok(set(range(1, k))); oks.append(okt)
        for i in INFO:
            if FOLD[i] == k:
                r, kd = snap_rule(i, okt, snap); rows.append(r); kinds_s[kd] = kinds_s.get(kd, 0) + 1
    snap_out[str(snap)] = dict(f2_5=agg(rows), kinds=kinds_s, ok_types=oks)
    # 같은 신호에서 스냅된 경우만 vs 그 신호의 -5% 기본
    print("snap", snap, snap_out[str(snap)]["f2_5"], kinds_s, oks, flush=True)
OUT["snap"] = snap_out
OUT["snap_live_types"] = type_ok(ALLF)
json.dump(OUT, open(ROOT / "model/buy_price.json", "w"), ensure_ascii=False, indent=1, default=float)
print("live types", OUT["snap_live_types"])
