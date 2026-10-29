"""💣 희석·상폐 구조 신호(SURG 글 방식) 시점 기준 검증 → model/structure_study.json
A) 앱 표본(research_ds, 5폴드 표본외, 앱 성공 라벨)  B) 넓은 표본(재무 XBRL 있는 전 종목 일봉 2024~, 라벨 = 5일 안 +30% 터치 / 5일 뒤 종가)
특징은 core/structure.daily_frame (filed < asof 공시, asof 종가까지) — 룩어헤드 없음."""
import sys, json, sqlite3; from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / "scripts")); sys.path.insert(0, str(ROOT))
import numpy as np, pandas as pd
from core import structure as S, db

def frames(tickers, px, fil):
    out = []
    for i, t in enumerate(tickers):
        g = px[px.ticker == t].sort_values("date")
        if len(g) < 40: continue
        fa = db.kv_get(f"facts:{t}") or {}
        try: F = S.daily_frame(g, fil[fil.ticker == t], fa)
        except Exception as e: print("skip", t, e); continue
        c, h = g.close.values, g.high.values
        F["fh5"] = (pd.Series(h[::-1]).rolling(5, min_periods=1).max()[::-1].shift(-1).values / c - 1)
        F["fc5"] = pd.Series(c).shift(-5).values / c - 1
        F["dv20"] = (g.close * g.volume).rolling(20, min_periods=10).mean().values
        F["has_facts"] = bool(fa)
        F["ticker"] = t; out.append(F.reset_index(names="date"))
        if i % 100 == 0: print(i, t, flush=True)
    return pd.concat(out, ignore_index=True)

def signs(F):
    R = {}
    for k, _ in S.SIGNS:
        R[k] = np.zeros(len(F), bool); R[k + "_na"] = np.zeros(len(F), bool)
    for i, r in enumerate(F[["price", "overhang", "shgrow", "runway_m", "baby_cap", "burn_m", "mcap", "dd_due", "pr_n", "pr_last", "pr_max_prev"]].to_dict("records")):
        sg = S.signs_from_row(r)
        for k, v in sg.items():
            if v is None: R[k + "_na"][i] = True
            else: R[k][i] = bool(v)
    return R

if __name__ == "__main__":
    con = sqlite3.connect(ROOT / "data/shortdash.sqlite")
    px = pd.read_sql("SELECT ticker, date, open, high, low, close, volume FROM prices WHERE date >= '2023-06-01'", con); px["date"] = pd.to_datetime(px.date)
    fil = pd.read_sql("SELECT ticker, form, filed, items FROM filings", con); fil["filed"] = pd.to_datetime(fil.filed)
    fk = {k[6:] for (k,) in con.execute("SELECT k FROM kv WHERE k LIKE 'facts:%'")}
    import sa_lib as L
    tick = sorted(fk & set(px.ticker.unique()) | set(L.df.ticker.unique()))
    fp = ROOT / "data/structure_frames.pkl"
    if fp.exists() and "--rebuild" not in sys.argv: F = pd.read_pickle(fp)
    else: F = frames(tick, px, fil); F.to_pickle(fp)
    out = {"signs": dict(S.SIGNS)}
    # ---------- B
    B = F[(F.price >= 0.05) & (F.price <= 15) & (F.dv20 >= 100e3) & F.fh5.notna() & F.fc5.notna() & (F.date >= "2024-01-01") & F.has_facts].reset_index(drop=True)
    SB = signs(B); B["hit30"] = (B.fh5 >= 0.3).astype(int)
    cuts = np.quantile(B.date.astype("int64"), [0, .2, .4, .6, .8, 1]); seg = np.clip(np.searchsorted(cuts, B.date.astype("int64"), side="right") - 1, 0, 4)
    def brow(m):
        s = B[m]; return dict(n=int(len(s)), hit30=round(float(s.hit30.mean()), 4) if len(s) else None, fc5_med=round(float(s.fc5.median()), 4) if len(s) else None)
    def bf(m): return [[int((m & (seg == j)).sum()), round(float(B.hit30[m & (seg == j)].mean()), 3) if (m & (seg == j)).sum() else None, round(float(B.hit30[~m & (seg == j)].mean()), 3)] for j in range(5)]
    BB = {"base": brow(np.ones(len(B), bool)), "signs": {}, "count": {}}
    K = sum(SB[k].astype(int) for k, _ in S.SIGNS); B["k"] = K
    for k, lab in S.SIGNS:
        BB["signs"][k] = dict(name=lab, on=brow(SB[k]), off=brow(~SB[k] & ~SB[k + "_na"]), na=int(SB[k + "_na"].sum()), folds=bf(SB[k]))
        print("B", k, BB["signs"][k])
    for n in range(8): BB["count"][str(n)] = brow(K == n)
    for th in (2, 3, 4): BB["count"][f">={th}"] = dict(**brow(K >= th), folds=bf(K >= th))
    print("B base", BB["base"]); print(BB["count"])
    out["B"] = BB
    # ---------- A
    df, N = L.df, len(L.df)
    SU = pd.read_pickle(ROOT / "data/setup_all.pkl").drop_duplicates(["ticker", "asof"])
    SX = df[["ticker", "asof"]].merge(SU, on=["ticker", "asof"], how="left")
    VALID = SX.valid.fillna(False).values.astype(bool) & (SX.nfut.fillna(0).values >= 10)
    Y = (VALID & (SX.succ.fillna(0).values == 1)).astype(int); FAIL = (VALID & (SX.fail.fillna(0).values == 1)).astype(int)
    A_ = df[["ticker", "asof"]].assign(date=pd.to_datetime(df["asof"])).merge(F, on=["ticker", "date"], how="left")
    SA = signs(A_.fillna({"pr_n": 0}))
    ev = np.any([f["te"] for f in L.folds], 0) & VALID
    def arow(m):
        s = ev & m; n = int(s.sum()); k = int(Y[s].sum())
        return dict(n=n, hit=round(k / n, 4) if n else None, ci=[round(float(x), 3) for x in L.wilson(k, n)] if n else None, fail=round(float(FAIL[s].mean()), 4) if n else None)
    def af(m): return [[int((f["te"] & VALID & m).sum()), round(float(Y[f["te"] & VALID & m].mean()), 3) if (f["te"] & VALID & m).sum() else None,
                        round(float(Y[f["te"] & VALID & ~m].mean()), 3)] for f in L.folds]
    KA = sum(SA[k].astype(int) for k, _ in S.SIGNS)
    AA = {"base": arow(np.ones(N, bool)), "signs": {}, "count": {}}
    for k, lab in S.SIGNS:
        AA["signs"][k] = dict(name=lab, on=arow(SA[k]), na=int((ev & SA[k + "_na"]).sum()), folds=af(SA[k])); print("A", k, AA["signs"][k])
    for th in (1, 2, 3, 4): AA["count"][f">={th}"] = dict(**arow(KA >= th), folds=af(KA >= th))
    print("A base", AA["base"], AA["count"])
    out["A"] = AA
    json.dump(out, open(ROOT / "model/structure_study.json", "w"), ensure_ascii=False, indent=1, default=float)
