"""사례 분석에서 나온 '움직임 이전' 특징 (look-ahead 없음: asof 당일 종가까지, filed<=asof 공시만).
출력 data/sa_feat.pkl (ticker, asof + 특징), 그리고 가격 미조정 역분할(아티팩트) 플래그."""
import sys; from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
import pandas as pd, numpy as np
from core import db
ds = pd.read_pickle(ROOT / "data/research_ds.pkl")[["ticker", "asof"]].copy(); ds["asof"] = pd.to_datetime(ds["asof"])
T = sorted(ds.ticker.unique())
P = db.q(f"select ticker,date,open,high,low,close,volume from prices where ticker in ({','.join('?'*len(T))}) order by ticker,date", tuple(T))
P["date"] = pd.to_datetime(P.date)
out = []
for t, g in P.groupby("ticker"):
    g = g.reset_index(drop=True); c = g.close; pc = c.shift(1)
    f = pd.DataFrame({"ticker": t, "asof": g.date})
    f["ret1"] = c / pc - 1; f["ret5"] = c / c.shift(5) - 1; f["ret20"] = c / c.shift(20) - 1
    f["gap"] = g.open / pc - 1
    f["clv"] = ((c - g.low) / (g.high - g.low).replace(0, np.nan)).fillna(0.5)
    f["fade"] = (g.high / c - 1)                                  # 당일 고점 대비 밀린 정도
    f["dist_hi20"] = c / g.high.shift(1).rolling(20, min_periods=5).max() - 1
    f["rvol"] = g.volume / g.volume.shift(1).rolling(20, min_periods=5).mean()
    f["vol_prev"] = g.volume.shift(1) / g.volume.shift(2).rolling(20, min_periods=5).mean()   # 전일 이미 터졌는지
    f["up_prev5"] = (c / pc - 1).shift(1).rolling(5, min_periods=1).max()                    # 직전 5일 최대 일간상승
    f["dd60"] = c / g.high.rolling(60, min_periods=10).max() - 1                           # 60일 고점대비 하락폭
    r = c / pc
    f["artifact"] = ((g.open / pc >= 2.5) & (g.volume.shift(-1).rolling(1).mean().fillna(g.volume) < 9e18)).astype(int) * 0  # placeholder
    out.append(f)
F = pd.concat(out)
# 공시 기반 (filed <= asof)
fl = db.q(f"select ticker,form,filed from filings where ticker in ({','.join('?'*len(T))})", tuple(T)); fl["filed"] = pd.to_datetime(fl.filed, errors="coerce")
def last_before(forms, col, prefix=False):
    s = fl[fl.form.str.startswith(forms) if prefix else fl.form.isin(forms)][["ticker", "filed"]].sort_values("filed")
    s = s.rename(columns={"filed": col}); s["_k"] = s[col]
    m = pd.merge_asof(F.sort_values("asof"), s.sort_values("_k"), left_on="asof", right_on="_k", by="ticker", direction="backward")
    return (m.set_index(["ticker", "asof"])[col])
F = F.sort_values("asof")
for nm, forms, pre in [("d_424b", ("424B",), True), ("d_reg", ["S-1", "S-1/A", "F-1", "F-1/A", "S-3", "F-3", "S-3/A", "F-3/A"], False),
                       ("d_8k", ["8-K", "6-K"], False), ("d_rs", ["DEF 14A", "PRE 14A"], False), ("d_effect", ["EFFECT"], False)]:
    lb = last_before(tuple(forms) if pre else forms, "x", pre)
    F = F.set_index(["ticker", "asof"]); F[nm] = (F.index.get_level_values(1) - lb.reindex(F.index).values).days if False else (F.index.get_level_values(1) - pd.DatetimeIndex(lb.reindex(F.index).values)).days
    F = F.reset_index()
# 아티팩트: 미조정 역분할 점프 (sa_splits)
O = pd.read_pickle(ROOT / "data/sa_splits.pkl"); O["date"] = pd.to_datetime(O.date); art = O[(O.jump >= 2.5) | O.confirmed]
F["art_fwd"] = 0
for _, a in art.iterrows():
    m = (F.ticker == a.ticker) & (F["asof"] < a.date) & (F["asof"] >= a.date - pd.Timedelta(days=15)); F.loc[m, "art_fwd"] = 1
    m = (F.ticker == a.ticker) & (F["asof"] >= a.date) & (F["asof"] <= a.date + pd.Timedelta(days=30)); F.loc[m, "art_fwd"] = 1   # 과거창 오염
F = F.drop(columns=["artifact"])
F = ds.merge(F, on=["ticker", "asof"], how="left")
F.to_pickle(ROOT / "data/sa_feat.pkl"); print(F.describe().T[["count", "mean", "50%"]]); print("art rows", F.art_fwd.sum())
