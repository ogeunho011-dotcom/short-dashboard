"""🌙 종가 베팅 조건 검증 → model/closebet_study.json
일봉(DB 전 종목, 2024~, 가격 $0.05~15, 20일 거래대금 ≥ $100K): 종가 매수 → 다음날 시가 갭·고가·종가·매도 계획 수익.
임계값 조합은 앞 60% 기간(시간 구간 0~2)에서만 고르고, 뒤 40%(3~4)로 표본외 확인. 비용 왕복 0.5% 차감.
분봉(Yahoo 5분봉, 최근 약 60일, 거래대금 상위 ~390종목): 마감 60분 체결강도(틱 규칙 추정)·다음날 프리장 결과. 표본이 짧아 참고용.
주의: 일봉 검증은 '당일 종가'를 15:45 무렵 가격의 대용으로 씀 (마지막 15분 움직임만큼 낙관적일 수 있음)."""
import sys, json, sqlite3, pickle, itertools; from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
import numpy as np, pandas as pd
from core import closebet as CB

OVER = [("rsi2", "<=", 10), ("rsi2", "<=", 5), ("rsi14", "<=", 30), ("ma5", "<=", -0.05), ("ma5", "<=", -0.10), ("ma20", "<=", -0.20),
        ("dd20", "<=", -0.30), ("dd20", "<=", -0.50), ("stoch", "<=", 20), ("down_n", ">=", 3)]
STR = [None, ("str_day", ">=", 100), ("str_day", ">=", 150), ("str_day", ">=", 200), ("str_day", ">=", 300)]
EXTRA = [None, ("volx", ">=", 1.5), ("volx", ">=", 3), ("chg1", "<=", -0.05), ("chg1", ">=", 0.0), ("hold", ">=", 0.9)]
PLANS = {"open": None, "tp5_sl8": (0.05, 0.08), "tp10_sl10": (0.10, 0.10), "tp3_sl5": (0.03, 0.05)}

def m_of(D, c):
    if c is None: return np.ones(len(D), bool)
    k, op, th = c; v = D[k].values
    return (v <= th) if op == "<=" else (v >= th)

def stats(D, m, plan="tp5_sl8"):
    s = D[m]
    if not len(s): return dict(n=0)
    r = s["open_r"] if plan == "open" else s[plan]
    return dict(n=int(len(s)), win=round(float((r > 0).mean()), 4), mean=round(float(r.mean()), 4), med=round(float(r.median()), 4),
                gap_med=round(float(s.gap.median()), 4), gap_pos=round(float((s.gap > 0).mean()), 4),
                hi5=round(float((s.hi1 >= 0.05).mean()), 4), hi10=round(float((s.hi1 >= 0.10).mean()), 4), c1_med=round(float(s.c1.median()), 4),
                days=int(s.date.nunique()))

if __name__ == "__main__":
    con = sqlite3.connect(ROOT / "data/shortdash.sqlite")
    px = pd.read_sql("SELECT ticker, date, open, high, low, close, volume FROM prices WHERE date >= '2023-09-01'", con); px["date"] = pd.to_datetime(px.date)
    fp = ROOT / "data/closebet_frames.pkl"
    if fp.exists() and "--rebuild" not in sys.argv: D = pd.read_pickle(fp)
    else:
        rows = []
        for t, g in px.groupby("ticker"):
            if len(g) < 40: continue
            F = CB.feats(g); F["ticker"] = t; rows.append(F)
        D = pd.concat(rows, ignore_index=True); D.to_pickle(fp)
    D = D[(D.date >= "2024-01-01") & (D.price >= 0.05) & (D.price <= 15) & (D.dv20 >= 100e3) & D.gap.notna() & D.hi1.notna()].reset_index(drop=True)
    D = D[(D.gap.abs() < 3) & (D.hi1 < 5)].reset_index(drop=True)     # 분할·오류 제거
    D["open_r"] = D.gap - 0.005
    for k, v in PLANS.items():
        if v: D[k] = CB.plan_ret(D, *v)
    cuts = np.quantile(D.date.astype("int64"), [0, .2, .4, .6, .8, 1]); D["seg"] = np.clip(np.searchsorted(cuts, D.date.astype("int64"), side="right") - 1, 0, 4)
    TR, TE = D.seg.values <= 2, D.seg.values >= 3
    out = {"n_rows": int(len(D)), "period": [str(D.date.min().date()), str(D.date.max().date())],
           "seg_start": [str(pd.Timestamp(int(x)).date()) for x in cuts[:5]], "base": {}, "single": {}, "grid": []}
    for pl in PLANS: out["base"][pl] = {"train": stats(D, TR, pl), "test": stats(D, TE, pl)}
    print("base", out["base"])
    for c in OVER + [x for x in STR if x] + [x for x in EXTRA if x]:
        m = m_of(D, c); key = f"{c[0]}{c[1]}{c[2]}"
        out["single"][key] = {"train": stats(D, TR & m), "test": stats(D, TE & m), "folds": [stats(D, (D.seg.values == j) & m)["mean"] if (m & (D.seg.values == j)).sum() else None for j in range(5)]}
    res = []
    for o, s_, e in itertools.product(OVER, STR, EXTRA):
        m = m_of(D, o) & m_of(D, s_) & m_of(D, e)
        for pl in PLANS:
            tr = stats(D, TR & m, pl)
            if tr["n"] < 300: continue
            fo = [stats(D, (D.seg.values == j) & m, pl) for j in range(5)]
            res.append(dict(conds=[c for c in (o, s_, e) if c], plan=pl, train=tr, folds=[f.get("mean") for f in fo], fold_n=[f.get("n") for f in fo],
                            train_min=min(f.get("mean", -9) if f.get("n", 0) >= 50 else -9 for f in fo[:3]), _m=m))
    def fin(r):
        r = dict(r); m = r.pop("_m"); r["test"] = stats(D, TE & m, r["plan"]); return r
    # 선택 기준 1 (처음 정한 것): 앞 60% 평균 수익 최대  /  기준 2: 앞 60%의 3개 구간 중 '가장 나쁜 구간' 수익 최대 (구간마다 버티는 규칙)
    by_mean = sorted(res, key=lambda r: r["train"]["mean"], reverse=True)[:15]
    by_min = sorted(res, key=lambda r: r["train_min"], reverse=True)[:15]
    out["grid"] = [fin(r) for r in by_mean]; out["grid_robust"] = [fin(r) for r in by_min]
    for nm, G in (("평균", out["grid"]), ("최악구간", out["grid_robust"])):
        for r in G[:10]: print(nm, r["conds"], r["plan"], r["train"]["n"], r["train"]["mean"], r["train_min"], "| test", r["test"].get("n"), r["test"].get("mean"), r["test"].get("win"), r["test"].get("gap_pos"), r["folds"])
    out["best_by_mean"] = out["grid"][0] if out["grid"] else None
    out["best_robust"] = out["grid_robust"][0] if out["grid_robust"] else None
    # 걷기 검증: 구간 0..k-1 로 평균 최대 규칙을 골라 구간 k 에서 확인 (k = 3, 4)
    wf = []
    for k in (3, 4):
        def pooled(r):
            ns = [r["fold_n"][j] or 0 for j in range(k)]
            if sum(ns) < 300: return -9
            return sum((r["folds"][j] or 0) * ns[j] for j in range(k)) / sum(ns)
        r = max(res, key=pooled)
        wf.append(dict(test_seg=k, conds=r["conds"], plan=r["plan"], pick_mean=round(pooled(r), 4), test_mean=r["folds"][k], test_n=r["fold_n"][k]))
    out["walk_forward"] = wf; print("walk-forward", wf)
    # 화면에 쓰는 규칙: 두 선택 기준 모두 2위였고 5구간 모두 플러스인 규칙 (표본외 성적을 본 뒤 고른 것이라 '사후 선택' 표시)
    CH = [("down_n", ">=", 3), ("volx", ">=", 3)]
    ch = next(fin(r) for r in res if r["conds"] == CH and r["plan"] == "open")
    ch["post_hoc"] = True
    best = out["best"] = ch
    out["n_combos"] = len(res)
    # 과매도 × 체결강도 표 (표본외)
    tab = {}
    for o in OVER:
        for s_ in STR:
            m = m_of(D, o) & m_of(D, s_)
            tab[f"{o[0]}{o[1]}{o[2]}|{s_[0] + s_[1] + str(s_[2]) if s_ else '없음'}"] = {"train": stats(D, TR & m), "test": stats(D, TE & m)}
    out["over_x_str"] = tab
    # ---------- 분봉 (마감 60분 체결강도, 다음날 프리장)
    try:
        I = pickle.load(open("/workspace/surg/i5m_all.pkl", "rb"))
        rec = []
        for t, x in I.items():
            x = x.copy(); x.index = pd.DatetimeIndex(x.index).tz_convert("America/New_York")
            x = x.dropna(subset=["Close"]); x["d"] = x.index.date; x["hm"] = x.index.hour * 60 + x.index.minute
            days = sorted(x.d.unique())
            for i, d in enumerate(days[:-1]):
                a = x[x.d == d]; reg = a[(a.hm >= 570) & (a.hm < 960)]
                if len(reg) < 40: continue
                last60 = reg[reg.hm >= 900]; pre_close = reg[reg.hm < 945]
                c_ref = float(pre_close.Close.iloc[-1]) if len(pre_close) else None      # 15:45 가격
                c_close = float(reg.Close.iloc[-1])
                n = x[x.d == days[i + 1]]; pm = n[n.hm < 570]; nr = n[(n.hm >= 570) & (n.hm < 960)]
                if not len(nr) or not c_ref: continue
                dv = float((reg.Close * reg.Volume).sum())
                rec.append(dict(ticker=t, date=pd.Timestamp(d), p1545=c_ref, close=c_close, str_60=CB.strength_tick(last60), str_dayt=CB.strength_tick(reg),
                                dv=dv, pm_hi=float(pm.High.max()) / c_ref - 1 if len(pm) else np.nan, pm_last=float(pm.Close.iloc[-1]) / c_ref - 1 if len(pm) else np.nan,
                                open1=float(nr.Open.iloc[0]) / c_ref - 1, hi1=float(nr.High.max()) / c_ref - 1, c1=float(nr.Close.iloc[-1]) / c_ref - 1))
        R = pd.DataFrame(rec); R = R[(R.p1545 >= 0.05) & (R.p1545 <= 15) & (R.dv >= 100e3)]
        # 일봉 과매도 지표 붙이기 (그날 종가 기준 — 15:45 대용)
        R = R.merge(D[["ticker", "date", "rsi2", "rsi14", "ma5", "ma20", "dd20", "stoch", "down_n", "str_day", "volx", "chg1", "hold"]], on=["ticker", "date"], how="left")
        def ist(m):
            s = R[m]
            if not len(s): return dict(n=0)
            return dict(n=int(len(s)), days=int(s.date.nunique()), pm_hi3=round(float((s.pm_hi >= 0.03).mean()), 4), pm_hi_med=round(float(s.pm_hi.median()), 4),
                        open_pos=round(float((s.open1 > 0).mean()), 4), open_med=round(float(s.open1.median()), 4), hi5=round(float((s.hi1 >= 0.05).mean()), 4),
                        c1_med=round(float(s.c1.median()), 4),
                        # 계획: 프리장에 +3% 지정가 매도(닿으면 +3%), 안 닿으면 시가 매도. 왕복 비용 0.5%
                        pm3_open=round(float((np.where(s.pm_hi >= 0.03, 0.03, s.open1) - 0.005).mean()), 4),
                        pm3_open_win=round(float(((np.where(s.pm_hi >= 0.03, 0.03, s.open1) - 0.005) > 0).mean()), 4),
                        open_mean=round(float((s.open1 - 0.005).mean()), 4))
        J = {"base": ist(np.ones(len(R), bool)), "period": [str(R.date.min().date()), str(R.date.max().date())]}
        for th in (100, 150, 200): J[f"str_60>={th}"] = ist(R.str_60.values >= th); J[f"str_60<{th}"] = ist(R.str_60.values < th)
        if best:
            mb = np.ones(len(R), bool)
            for c in best["conds"]:
                if c[0] in R: mb &= m_of(R.fillna({c[0]: np.nan}), c)
            J["best"] = ist(mb); J["best&str_60>=100"] = ist(mb & (R.str_60.values >= 100)); J["best&str_60>=150"] = ist(mb & (R.str_60.values >= 150)); J["best&str_60<100"] = ist(mb & (R.str_60.values < 100))
        mo = (R.dd20.values <= -0.3) | (R.rsi2.values <= 10)
        J["oversold"] = ist(mo); J["oversold&str_60>=150"] = ist(mo & (R.str_60.values >= 150)); J["oversold&str_60<100"] = ist(mo & (R.str_60.values < 100))
        J["corr_str60_open"] = round(float(R[["str_60", "open1"]].corr().iloc[0, 1]), 4)
        out["intraday"] = J; print("intraday", J)
    except Exception as e:
        out["intraday"] = {"error": repr(e)}; print("intraday err", e)
    json.dump(out, open(ROOT / "model/closebet_study.json", "w"), ensure_ascii=False, indent=1, default=float)
