"""🌙 종가 베팅 — '하루에 크게 빠진 종목' 검증 → model/closebet_drop.json
python scripts/closebet_drop_study.py [DB경로]   (기본: data/shortdash.sqlite)

일봉(DB 전 종목, 2024~, $0.05~15, 20일 거래대금 ≥ $100K): 당일 종가 매수(15:45 가격 대용) → 다음날.
  · 하락 기준: 전날 종가 대비(chg1) −10/−15/−20/−30%, 시가 대비·장중 고가 대비 하락도 같이.
  · 추가 조건(최대 2개): 거래량·체결강도(일봉 추정)·과매도·종가 위치·직전 상승폭.
  · 고르는 법: 앞 60%(구간 0~2)에서만 '3개 구간 중 가장 나쁜 구간 평균'이 최대인 규칙(미리 정함) → 뒤 40%(3~4)로 확인.
    걷기 검증: 구간 0..k-1 로 고르고 구간 k 로 확인(k=3,4). 비용 왕복 0.5% (참고로 1.0%도).
  · 하락 위험: 다음날 시가 < 매수가 비율, 다음날 저가 −10%/−20% 이하 비율, 최악 사례.
  · 반등 vs 추가 하락을 가르는 것: 공시(유상증자·역분할·상장폐지 통지, 공시 자료 있는 종목만), 종가 위치, 체결강도,
    거래량, 거래대금(규모 대용), 직전 상승폭 — 앞 기간에서 고르고 뒤 기간에서 확인.
5분봉(Yahoo, 최근 약 60일, 거래대금 상위 ~390종목): 실제 15:45 가격으로 하락률·마감 30/60분 체결강도(15:45 이전 봉만),
  다음날 프리장 손절선(−3/−5/−8/−10/−15%) 비교. 표본이 짧아 참고용."""
import sys, os, json, sqlite3, pickle, itertools
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
import numpy as np, pandas as pd
from core import closebet as CB

COST = 0.005
DROPS = [("chg1", "<=", -0.10), ("chg1", "<=", -0.15), ("chg1", "<=", -0.20), ("chg1", "<=", -0.30)]
EXTRA = [None, ("volx", ">=", 1.5), ("volx", ">=", 3), ("str_day", ">=", 100), ("str_day", ">=", 150), ("rsi2", "<=", 10), ("dd20", "<=", -0.3),
         ("from_hi", ">=", -0.05), ("from_hi", "<=", -0.15), ("from_open", "<=", -0.10), ("from_open", ">=", 0.0), ("run20", ">=", 0.3), ("run20", "<=", 0.0),
         ("down_n", ">=", 2), ("dv20", ">=", 1e6), ("clv", "<=", -0.5), ("clv", "<=", 0.0)]
# 공시 여부(nofile)는 공시 자료가 있는 일부 종목(약 470개)만 판정 가능 → 조합에서 빼고 '가르는 요인' 표에서만 봄
PLANS = {"open": None, "tp5_sl8": (0.05, 0.08), "tp10_sl10": (0.10, 0.10), "tp3_sl5": (0.03, 0.05)}
OFFER = {"424B5", "424B4", "424B3", "424B1", "424B2", "424B7", "S-1", "S-1/A", "F-1", "F-1/A", "S-3", "S-3/A", "F-3", "EFFECT"}

def m_of(D, c):
    if c is None: return np.ones(len(D), bool)
    k, op, th = c; v = D[k].values.astype(float)
    return (v <= th) if op == "<=" else (v >= th)

def R4(x): return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), 4)

def stats(s, plan="open"):
    if not len(s): return dict(n=0)
    r = s["open_r"] if plan == "open" else s[plan]
    return dict(n=int(len(s)), days=int(s.date.nunique()), win=R4((r > 0).mean()), mean=R4(r.mean()), med=R4(r.median()),
                mean_cost1=R4(r.mean() - 0.005),
                open_below=R4((s.gap < 0).mean()), lo10=R4((s.lo1 <= -0.10).mean()), lo20=R4((s.lo1 <= -0.20).mean()),
                q05=R4(r.quantile(0.05)), worst=R4(r.min()), hi5=R4((s.hi1 >= 0.05).mean()), c1_med=R4(s.c1.median()))

def worst_cases(s, k=5):
    s = s.sort_values("gap").head(k)
    return [dict(ticker=r.ticker, date=str(r.date.date()), chg1=R4(r.chg1), gap=R4(r.gap), lo1=R4(r.lo1), c1=R4(r.c1)) for r in s.itertuples()]

def main(dbp):
    con = sqlite3.connect(dbp)
    fp = ROOT / "data/closebet_frames.pkl"
    if fp.exists() and "--rebuild" not in sys.argv: D = pd.read_pickle(fp)
    else:
        px = pd.read_sql("SELECT ticker, date, open, high, low, close, volume FROM prices WHERE date >= '2023-09-01'", con); px["date"] = pd.to_datetime(px.date)
        D = pd.concat([CB.feats(g).assign(ticker=t) for t, g in px.groupby("ticker") if len(g) >= 40], ignore_index=True); D.to_pickle(fp)
    D = D[(D.date >= "2024-01-01") & (D.price >= 0.05) & (D.price <= 15) & (D.dv20 >= 100e3) & D.gap.notna() & D.hi1.notna()]
    D = D[(D.gap.abs() < 3) & (D.hi1 < 5) & (D.chg1 > -0.95)].reset_index(drop=True)
    # 공시 (공시 자료가 있는 종목만): 당일 또는 전날(장 마감 후) 제출 → 하락 원인 후보
    F = pd.read_sql("SELECT ticker, form, filed, items FROM filings WHERE filed >= '2023-12-01'", con)
    cov = set(F.ticker); F["filed"] = pd.to_datetime(F.filed)
    F["off"] = F.form.isin(OFFER) | F["items"].fillna("").str.contains("3.02")
    F["rs"] = F["items"].fillna("").str.contains("5.03") | F["items"].fillna("").str.contains("3.03")
    F["dl"] = F["items"].fillna("").str.contains("3.01")
    ev = []
    for lag in (0, 1, 2, 3):   # 제출일 = d, d-1(장 마감 후), 주말 건너 d-3 까지
        x = F.copy(); x["date"] = x.filed + pd.Timedelta(days=lag); ev.append(x)
    E = pd.concat(ev).groupby(["ticker", "date"])[["off", "rs", "dl"]].max().reset_index()
    D = D.merge(E, on=["ticker", "date"], how="left")
    D["cov"] = D.ticker.isin(cov)
    for k in ("off", "rs", "dl"): D[k] = D[k].fillna(False).astype(bool)
    D["nofile"] = np.where(D["cov"], (~(D.off | D.rs | D.dl)).astype(float), np.nan)
    D["open_r"] = D.gap - COST
    for k, v in PLANS.items():
        if v: D[k] = CB.plan_ret(D, *v, cost=COST)
    cuts = np.quantile(D.date.astype("int64"), [0, .2, .4, .6, .8, 1])
    D["seg"] = np.clip(np.searchsorted(cuts, D.date.astype("int64"), side="right") - 1, 0, 4)
    TR, TE = D.seg.values <= 2, D.seg.values >= 3
    out = {"n_rows": int(len(D)), "period": [str(D.date.min().date()), str(D.date.max().date())], "cost": COST,
           "seg_start": [str(D[D.seg == j].date.min().date()) for j in range(5)]}
    out["base"] = {"train": stats(D[TR]), "test": stats(D[TE])}
    # 옛 규칙 (연속 하락 3일 + 거래량 3배, 시가 매도)
    mo = m_of(D, ("down_n", ">=", 3)) & m_of(D, ("volx", ">=", 3))
    out["old_rule"] = {"conds": [["down_n", ">=", 3], ["volx", ">=", 3]], "plan": "open", "train": stats(D[TR & mo]), "test": stats(D[TE & mo]),
                       "folds": [stats(D[(D.seg.values == j) & mo]).get("mean") for j in range(5)]}
    # 하락 기준만 (추가 조건 없음)
    out["drop_only"] = {}
    for dr in DROPS + [("from_open", "<=", -0.10), ("from_open", "<=", -0.15), ("from_hi", "<=", -0.15), ("from_hi", "<=", -0.25)]:
        m = m_of(D, dr)
        out["drop_only"][f"{dr[0]}{dr[1]}{dr[2]}"] = {pl: {"train": stats(D[TR & m], pl), "test": stats(D[TE & m], pl)} for pl in PLANS} | {
            "folds": [stats(D[(D.seg.values == j) & m]).get("mean") for j in range(5)], "worst": worst_cases(D[TE & m])}
    # 조합 그리드
    res = []
    pairs = [(a, b) for a, b in itertools.combinations(EXTRA, 2) if a is not None and b is not None and a[0] != b[0]] + [(e, None) for e in EXTRA]
    for dr in DROPS:
        md = m_of(D, dr)
        for e1, e2 in pairs:
            m = md & m_of(D, e1) & m_of(D, e2)
            if (m & TR).sum() < 150: continue
            for pl in PLANS:
                fo = [stats(D[(D.seg.values == j) & m], pl) for j in range(5)]
                tr = stats(D[TR & m], pl)
                res.append(dict(conds=[c for c in (dr, e1, e2) if c], plan=pl, train=tr, folds=[f.get("mean") for f in fo], fold_n=[f.get("n", 0) for f in fo],
                                train_min=min((f.get("mean") if f.get("n", 0) >= 30 else -9) for f in fo[:3]), _m=m))
    def fin(r):
        r = dict(r); m = r.pop("_m"); r["test"] = stats(D[TE & m], r["plan"]); r["worst"] = worst_cases(D[TE & m]); return r
    by_min = sorted(res, key=lambda r: (r["train_min"], r["train"]["mean"]), reverse=True)
    by_mean = sorted(res, key=lambda r: r["train"]["mean"], reverse=True)
    out["n_combos"] = len(res)
    out["grid_robust"] = [fin(r) for r in by_min[:15]]; out["grid_mean"] = [fin(r) for r in by_mean[:10]]
    out["best"] = out["grid_robust"][0] if res else None   # 미리 정한 기준: 앞 기간 최악 구간 최대
    wf = []
    for k in (3, 4):
        def pooled_min(r):
            fs = [(r["folds"][j], r["fold_n"][j]) for j in range(k)]
            return min((f if n >= 30 else -9) for f, n in fs)
        r = max(res, key=lambda r: (pooled_min(r), sum((r["folds"][j] or 0) * r["fold_n"][j] for j in range(k))))
        wf.append(dict(test_seg=k, conds=r["conds"], plan=r["plan"], pick_min=R4(pooled_min(r)), test_mean=r["folds"][k], test_n=r["fold_n"][k]))
    out["walk_forward"] = wf
    # 하락 기준별(−10%↓ 전체) 반등/추가 하락 가르는 요인 — 앞/뒤 기간 따로
    B = D[m_of(D, ("chg1", "<=", -0.10))].copy()
    B["clv_b"] = pd.cut(B.clv, [-1.01, -0.5, 0, 0.5, 1.01], labels=["저가 근처", "아래쪽", "위쪽", "고가 근처"])
    B["volx_b"] = pd.cut(B.volx, [0, 1.5, 3, 6, 1e9], labels=["<1.5배", "1.5~3배", "3~6배", "6배↑"])
    B["dv_b"] = pd.cut(B.dv20, [0, 3e5, 1e6, 5e6, 1e12], labels=["<30만$", "30만~100만$", "100만~500만$", "500만$↑"])
    B["run_b"] = pd.cut(B.run20, [-10, 0, 0.3, 1, 1e9], labels=["하락 중", "0~30%", "30~100%", "100%↑"])
    B["drop_b"] = pd.cut(B.chg1, [-1, -0.3, -0.2, -0.15, -0.10001], labels=["−30%↓", "−20~30%", "−15~20%", "−10~15%"])
    B["file_b"] = np.where(~B["cov"], "공시자료 없음", np.where(B.off, "증자 관련 공시", np.where(B.rs, "역분할 공시", np.where(B.dl, "상장 유지 통지", "공시 없음"))))
    seps = {}
    for col in ("drop_b", "clv_b", "volx_b", "dv_b", "run_b", "file_b"):
        rows = []
        for v, g in B.groupby(col, observed=True):
            a, b = g[g.seg <= 2], g[g.seg >= 3]
            rows.append(dict(v=str(v), train=stats(a), test=stats(b)))
        seps[col] = rows
    out["separators"] = seps
    # 카드용: 하락폭 × 종가 위치 칸별 다음날 추가 하락 확률 (전체 기간, 칸 표본 수 같이)
    cell = {}
    for (a, b), g in B.groupby(["drop_b", "clv_b"], observed=True):
        cell[f"{a}|{b}"] = dict(n=int(len(g)), open_below=R4((g.gap < 0).mean()), lo10=R4((g.lo1 <= -0.10).mean()), lo20=R4((g.lo1 <= -0.20).mean()),
                                mean=R4(g.open_r.mean()))
    out["cells"] = cell
    out["sep_n"] = int(len(B))
    # ---------- 5분봉: 실제 15:45 가격
    try:
        I = pickle.load(open(os.environ.get("I5M", "/workspace/surg/i5m_all.pkl"), "rb"))
        pxd = pd.read_sql("SELECT ticker, date, close, volume FROM prices WHERE date >= '2026-06-01'", con); pxd["date"] = pd.to_datetime(pxd.date)
        pxd = pxd.sort_values(["ticker", "date"]); pxd["pc"] = pxd.groupby("ticker").close.shift(1)
        pxd["v20"] = pxd.groupby("ticker").volume.transform(lambda s: s.shift(1).rolling(20, min_periods=10).mean())
        PC = {(r.ticker, r.date): (r.pc, r.v20) for r in pxd.itertuples()}
        rec = []
        for t, x in I.items():
            x = x.dropna(subset=["Close"]).copy(); x.index = pd.DatetimeIndex(x.index).tz_convert("America/New_York")
            x["d"] = x.index.date; x["hm"] = x.index.hour * 60 + x.index.minute
            days = sorted(x.d.unique())
            for i, d in enumerate(days[:-1]):
                a = x[x.d == d]; reg = a[(a.hm >= 570) & (a.hm < 945)]
                if len(reg) < 40: continue
                pc, v20 = PC.get((t, pd.Timestamp(d)), (np.nan, np.nan))
                if not pc or np.isnan(pc): continue
                p = float(reg.Close.iloc[-1])
                n = x[x.d == days[i + 1]]; pm = n[n.hm < 570]; nr = n[(n.hm >= 570) & (n.hm < 960)]
                if not len(nr): continue
                rec.append(dict(ticker=t, date=pd.Timestamp(d), p=p, chg=p / pc - 1, from_open=p / float(reg.Open.iloc[0]) - 1, from_hi=p / float(reg.High.max()) - 1,
                                str60=CB.strength_tick(reg[reg.hm >= 885]), str30=CB.strength_tick(reg[reg.hm >= 915]),
                                volx=float(reg.Volume.sum()) / v20 if v20 and v20 > 0 else np.nan, dv=float((reg.Close * reg.Volume).sum()),
                                clv=(2 * p - float(reg.Low.min()) - float(reg.High.max())) / max(float(reg.High.max() - reg.Low.min()), 1e-9),
                                pm_lo=list((pm.Low / p - 1).values), pm_hi=float(pm.High.max()) / p - 1 if len(pm) else np.nan,
                                open1=float(nr.Open.iloc[0]) / p - 1, lo1=float(min(nr.Low.min(), pm.Low.min() if len(pm) else 9e9)) / p - 1,
                                hi1=float(nr.High.max()) / p - 1, c1=float(nr.Close.iloc[-1]) / p - 1))
        R = pd.DataFrame(rec); R = R[(R.p >= 0.05) & (R.p <= 15) & (R.dv >= 100e3) & (R.open1.abs() < 3)]
        def stop_ret(r, X, tp=None):
            for lo in r.pm_lo:      # 프리장: 손절선 닿으면 그 값에서 매도(추가 미끄러짐 0.5%)
                if X is not None and lo <= -X: return -X - 0.005
            if tp is not None and r.pm_hi >= tp: return tp
            return r.open1           # 아니면 시가 매도 (시가가 손절선 아래여도 시가에 팔림)
        def ist(s):
            if not len(s): return dict(n=0)
            o = dict(n=int(len(s)), days=int(s.date.nunique()), open_mean=R4((s.open1 - COST).mean()), win=R4(((s.open1 - COST) > 0).mean()),
                     open_below=R4((s.open1 < 0).mean()), lo10=R4((s.lo1 <= -0.10).mean()), lo20=R4((s.lo1 <= -0.20).mean()),
                     worst=R4((s.open1 - COST).min()), q05=R4((s.open1 - COST).quantile(0.05)))
            for X in (0.03, 0.05, 0.08, 0.10, 0.15):
                o[f"stop{int(X * 100)}"] = R4(np.mean([stop_ret(r, X) for r in s.itertuples()]) - COST)
                o[f"stop{int(X * 100)}_hit"] = R4(np.mean([any(lo <= -X for lo in r.pm_lo) for r in s.itertuples()]))
                o[f"stop{int(X * 100)}_worst"] = R4(min(stop_ret(r, X) for r in s.itertuples()) - COST)
            o["pm3_stop8"] = R4(np.mean([stop_ret(r, 0.08, 0.03) for r in s.itertuples()]) - COST)
            return o
        J = {"period": [str(R.date.min().date()), str(R.date.max().date())], "base": ist(R)}
        for th in (-0.10, -0.15, -0.20, -0.30):
            m = R.chg <= th; J[f"chg<={th}"] = ist(R[m])
            J[f"chg<={th}&str60>=100"] = ist(R[m & (R.str60 >= 100)]); J[f"chg<={th}&str60<100"] = ist(R[m & (R.str60 < 100)])
            J[f"chg<={th}&str30>=100"] = ist(R[m & (R.str30 >= 100)]); J[f"chg<={th}&clv>=0"] = ist(R[m & (R.clv >= 0)]); J[f"chg<={th}&clv<0"] = ist(R[m & (R.clv < 0)])
            J[f"chg<={th}&volx>=3"] = ist(R[m & (R.volx >= 3)])
        if out["best"]:
            mb = np.ones(len(R), bool)
            for k, op, th in out["best"]["conds"]:
                kk = {"chg1": "chg", "str_day": "str60"}.get(k, k)
                if kk in R: v = R[kk].values.astype(float); mb &= (v <= th) if op == "<=" else (v >= th)
            J["best_approx"] = ist(R[mb])
        out["intraday"] = J
    except Exception as e:
        out["intraday"] = {"error": repr(e)}
    json.dump(out, open(ROOT / "model/closebet_drop.json", "w"), ensure_ascii=False, indent=1, default=float)
    return out

if __name__ == "__main__":
    dbp = next((a for a in sys.argv[1:] if not a.startswith("--")), os.environ.get("SHORTDASH_DB", str(ROOT / "data/shortdash.sqlite")))
    o = main(dbp)
    print("base", o["base"]); print("old", o["old_rule"])
    for k, v in o["drop_only"].items(): print("drop", k, "train", v["open"]["train"], "\n   test", v["open"]["test"], v["folds"])
    for r in o["grid_robust"][:10]: print("robust", r["conds"], r["plan"], r["train"]["n"], r["train"]["mean"], r["train_min"], r["folds"], "| test", r["test"])
    print("seg", o["seg_start"]); print("best_approx", o["intraday"].get("best_approx")); print("cells", o["cells"])
    print("wf", o["walk_forward"])
    for c, rows in o["separators"].items():
        for r in rows: print("sep", c, r["v"], "tr", r["train"].get("n"), r["train"].get("mean"), r["train"].get("open_below"), "| te", r["test"].get("n"), r["test"].get("mean"), r["test"].get("open_below"), r["test"].get("lo20"))
    print(json.dumps(o["intraday"], ensure_ascii=False)[:6000])
