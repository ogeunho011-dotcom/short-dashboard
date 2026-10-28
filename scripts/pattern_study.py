"""'급락 후 반등' 성공 패턴(커뮤니티 성공 사례 공통점) 시점 기준 검증.
A) 앱 표본(research_ds, 5폴드 표본외, 셋업 10거래일 성공 라벨 = 앱의 환경 상대 성공 정의)
B) 넓은 표본(DB 전 종목 일봉 2023-10~, 앱 유니버스 조건, 라벨 = 5거래일 안 고가 +30% / 5일 뒤 종가 수익)
모든 특징은 asof 종가까지의 데이터만 사용 (룩어헤드 없음). 출력: model/pattern_study.json"""
import sys, json, sqlite3; from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / "scripts")); sys.path.insert(0, str(ROOT))
import numpy as np, pandas as pd

TRAITS = {  # 키: (설명, 함수는 아래 feats)
    "sub1": "주가 $1 미만",
    "tiny": "시총 $10M 미만",
    "dd50": "20일 고점 대비 -50% 이상 하락",
    "crash30": "최근 10일 안에 하루 -30% 이상 폭락",
    "distress": "최근 역분할·상장유지 미달(3.01)·증자(424B) 중 하나",
    "volx": "최근 3일 거래량이 20일 평균의 3배 이상",
}

def price_feats(g):
    """g: 한 종목 일봉(date 정렬). 각 날짜 종가 기준 특징."""
    c, h, v = g["close"], g["high"], g["volume"]
    o = pd.DataFrame({"date": g["date"].values, "price": c.values})
    o["dd20"] = (c / h.rolling(20, min_periods=10).max() - 1).values
    r1 = c.pct_change()
    o["worst10"] = r1.rolling(10, min_periods=5).min().values
    va = v.shift(3).rolling(20, min_periods=10).mean()
    o["volx3"] = (v.rolling(3).mean() / va.replace(0, np.nan)).values
    o["ma5"] = (c / c.rolling(5).mean() - 1).values
    o["dv20"] = (c * v).rolling(20, min_periods=10).mean().values
    o["fh5"] = (h[::-1].rolling(5, min_periods=1).max()[::-1].shift(-1) / c - 1).values   # 미래 5일 고가 (라벨 전용)
    o["fc5"] = (c.shift(-5) / c - 1).values
    o["nf"] = (pd.Series(np.arange(len(c))[::-1], index=c.index)).values
    return o

def trait_mask(F, mcap=None, distress=None):
    m = {"sub1": F["price"].values < 1, "dd50": F["dd20"].values <= -0.5, "crash30": F["worst10"].values <= -0.3,
         "volx": F["volx3"].values >= 3}
    m["tiny"] = (mcap < 10e6) if mcap is not None else np.zeros(len(F), bool)
    m["distress"] = distress if distress is not None else np.zeros(len(F), bool)
    return m

if __name__ == "__main__":
    import sa_lib as L
    from core import model as M
    con = sqlite3.connect(ROOT / "data/shortdash.sqlite")
    out = {"traits": TRAITS}
    # ---------------- A) 앱 표본
    df, N = L.df, len(L.df)
    SU = pd.read_pickle(ROOT / "data/setup_all.pkl").drop_duplicates(["ticker", "asof"])
    SX = df[["ticker", "asof"]].merge(SU, on=["ticker", "asof"], how="left")
    VALID = SX.valid.fillna(False).values.astype(bool) & (SX.nfut.fillna(0).values >= 10)
    Y = (VALID & (SX.succ.fillna(0).values == 1)).astype(int); FAIL = (VALID & (SX.fail.fillna(0).values == 1)).astype(int); RET = SX.ret.values
    ev = np.any([F["te"] for F in L.folds], 0) & VALID
    tk = df["ticker"].values; asof = pd.to_datetime(df["asof"]).values
    px = pd.read_sql("SELECT ticker, date, open, high, low, close, volume FROM prices", con); px["date"] = pd.to_datetime(px.date)
    fil = pd.read_sql("SELECT ticker, form, filed, items FROM filings", con); fil["filed"] = pd.to_datetime(fil.filed)
    FA = pd.DataFrame(index=range(N), columns=["price", "dd20", "worst10", "volx3", "ma5"], dtype=float)
    mcap = np.full(N, np.nan); dis = np.zeros(N, bool)
    REG = M.regime_series()
    for t in np.unique(tk):
        idx = np.where(tk == t)[0]
        g = px[px.ticker == t].sort_values("date")
        if len(g) < 25: continue
        pf = price_feats(g.reset_index(drop=True)).set_index("date")
        a = pd.DatetimeIndex(asof[idx])
        sub = pf.reindex(a)
        for col in FA.columns: FA.loc[idx, col] = sub[col].values
        try:
            b = M.Bundle(t, REG)
            sp = [pd.Timestamp(d) for d, r in (b.info.get("splits") or []) if r and r < 1]
        except Exception: b, sp = None, []
        G = fil[fil.ticker == t].sort_values("filed")
        for j, i in enumerate(idx):
            A = pd.Timestamp(asof[i])
            if b is not None:
                try:
                    sh, look = b.shares_asof(A)
                    if sh and not look: mcap[i] = sh * sub["price"].iloc[j]
                except Exception: pass
            rs = any(A - pd.Timedelta(days=120) <= d <= A for d in sp)
            st = M.reg_status(G[G.filed < A], A) if len(G) else {"def301": False, "atm": False}
            off = len(G[(G.filed < A) & (G.filed >= A - pd.Timedelta(days=30)) & G.form.str.match(r"^424B", na=False)]) > 0
            dis[i] = rs or st["def301"] or off
    TM = trait_mask(FA, mcap, dis)
    K = sum(TM[k].astype(int) for k in TRAITS)
    def wil(k, n): return [round(float(x), 3) for x in L.wilson(k, n)] if n else [None, None]
    def row(mask, name):
        s = ev & mask; n = int(s.sum()); k = int(Y[s].sum())
        return dict(name=name, n=n, hit=round(k / n, 4) if n else None, ci=wil(k, n), fail=round(float(FAIL[s].mean()), 4) if n else None,
                    ret=round(float(np.nanmean(RET[s])), 4) if n else None)
    def folds(mask):
        r = []
        for F in L.folds:
            m = F["te"] & VALID; a, b2 = m & mask, m & ~mask
            r.append([int(a.sum()), round(float(Y[a].mean()), 3) if a.sum() else None, round(float(Y[b2].mean()), 3) if b2.sum() else None])
        return r
    A = {"base": row(np.ones(N, bool), "전체"), "traits": {}, "count": {}}
    for k, lab in TRAITS.items():
        A["traits"][k] = dict(on=row(TM[k], lab), off=row(~TM[k], "아님"), folds=folds(TM[k]))
    for n in range(7):
        A["count"][n] = row(K == n, f"{n}/6 일치")
    for th in (3, 4, 5):
        A["count"][f">={th}"] = dict(**row(K >= th, f"{th}개 이상"), folds=folds(K >= th))
    # 핵심 조합: 급락(dd50 & crash30) + 소형(sub1|tiny)
    core_m = TM["dd50"] & TM["crash30"]
    A["combo_crash"] = dict(**row(core_m, "20일 -50% + 하루 -30% 폭락"), folds=folds(core_m))
    A["combo_crash_ma5"] = dict(**row(core_m & (FA["ma5"].values > 0), "급락 + 5일선 위 회복"), folds=folds(core_m & (FA["ma5"].values > 0)))
    out["A"] = A
    print("A base", A["base"])
    for k, v in A["traits"].items(): print(k, v["on"], "| off", v["off"]["hit"], v["folds"])
    for k, v in A["count"].items(): print("cnt", k, v)
    print(A["combo_crash"]); print(A["combo_crash_ma5"])
    # ---------------- B) 넓은 표본 (가격 특징만)
    rows = []
    for t, g in px.groupby("ticker"):
        g = g.sort_values("date").reset_index(drop=True)
        if len(g) < 40: continue
        pf = price_feats(g); pf["ticker"] = t; rows.append(pf)
    B = pd.concat(rows, ignore_index=True)
    B = B[(B.price >= 0.05) & (B.price <= 15) & (B.dv20 >= 100e3) & (B.nf >= 5) & B.fh5.notna()]
    B = B[B.date >= "2024-01-01"]
    B["yr"] = B.date.dt.to_period("Q").astype(str)
    TB = trait_mask(B)
    B["k4"] = sum(TB[k].astype(int) for k in ("sub1", "dd50", "crash30", "volx"))
    B["hit30"] = (B.fh5 >= 0.30).astype(int)
    def brow(m, name):
        s = B[m]; return dict(name=name, n=int(len(s)), hit30=round(float(s.hit30.mean()), 4) if len(s) else None,
                              fc5_med=round(float(s.fc5.median()), 4) if len(s) else None, fc5_mean=round(float(s.fc5.clip(-1, 3).mean()), 4) if len(s) else None)
    # 5개 시간 구간 (분위로 나눔)
    cuts = np.quantile(B.date.astype("int64"), [0, .2, .4, .6, .8, 1])
    seg = np.clip(np.searchsorted(cuts, B.date.astype("int64"), side="right") - 1, 0, 4)
    def bfold(m): return [[int((m & (seg == j)).sum()), round(float(B.hit30[m & (seg == j)].mean()), 3) if (m & (seg == j)).sum() else None,
                           round(float(B.hit30[(~m) & (seg == j)].mean()), 3)] for j in range(5)]
    BB = {"base": brow(np.ones(len(B), bool), "전체"), "traits": {}, "count": {}}
    for k in ("sub1", "dd50", "crash30", "volx"):
        BB["traits"][k] = dict(on=brow(TB[k], TRAITS[k]), folds=bfold(TB[k]))
    for n in range(5): BB["count"][n] = brow(B.k4.values == n, f"{n}/4")
    cm = TB["dd50"] & TB["crash30"]
    BB["combo_crash"] = dict(**brow(cm, "급락 조합"), folds=bfold(cm))
    BB["combo_crash_sub1"] = dict(**brow(cm & TB["sub1"], "급락 + $1 미만"), folds=bfold(cm & TB["sub1"]))
    BB["combo_crash_ma5"] = dict(**brow(cm & (B.ma5.values > 0), "급락 + 5일선 회복"), folds=bfold(cm & (B.ma5.values > 0)))
    out["B"] = BB
    print("B base", BB["base"])
    for k, v in BB["traits"].items(): print(k, v)
    for k, v in BB["count"].items(): print("cnt", k, v)
    for k in ("combo_crash", "combo_crash_sub1", "combo_crash_ma5"): print(k, BB[k])
    json.dump(out, open(ROOT / "model/pattern_study.json", "w"), ensure_ascii=False, indent=1, default=float)
