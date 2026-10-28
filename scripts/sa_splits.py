"""DB 가격의 '미조정 역분할' 점프 탐지 → yfinance splits 로 확인. 출력 data/sa_splits.pkl (ticker, date, ratio, confirmed)"""
import sys; from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
import pandas as pd, numpy as np, yfinance as yf, time
from core import db
P = db.q("select ticker,date,open,close,volume from prices order by ticker,date")
P["pc"] = P.groupby("ticker").close.shift(1)
P["r"] = P.open / P.pc
g = P.groupby("ticker").volume
P["vb"] = g.transform(lambda v: v.shift(1).rolling(5, min_periods=2).mean())
P["va"] = g.transform(lambda v: v[::-1].rolling(5, min_periods=2).mean()[::-1])
cand = P[((P.r >= 2.5) & (P.va <= 0.5 * P.vb)) | ((P.r <= 0.4) & (P.va >= 2 * P.vb))].copy()
print("candidates", len(cand), cand.ticker.nunique())
out = []
for t, grp in cand.groupby("ticker"):
    try: sp = yf.Ticker(t).splits
    except Exception: sp = pd.Series(dtype=float)
    sp.index = pd.to_datetime(sp.index).tz_localize(None).normalize() if len(sp) else sp.index
    for _, r in grp.iterrows():
        d = pd.Timestamp(r.date); near = sp[(sp.index >= d - pd.Timedelta(days=5)) & (sp.index <= d + pd.Timedelta(days=5))] if len(sp) else []
        out.append(dict(ticker=t, date=r.date, jump=float(r.r), confirmed=len(near) > 0, yf_ratio=float(near.iloc[0]) if len(near) else None))
    time.sleep(0.2)
O = pd.DataFrame(out); O.to_pickle(ROOT / "data/sa_splits.pkl")
print(O.confirmed.value_counts()); print(O.head(20))
