"""yfinance 일봉(분할 조정) + 분할 기록 묶음 받기 → data/finance_yf.pkl {ticker: DataFrame(date,open,high,low,close,volume,split)}
사용: python scripts/finance_yf.py [추가 티커 파일]  (이미 받은 티커는 건너뜀)"""
import sys, pickle, warnings; from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
import pandas as pd, yfinance as yf, sqlite3, logging
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
P = ROOT / "data/finance_yf.pkl"
have = pickle.load(open(P, "rb")) if P.exists() else {}
if len(sys.argv) > 1: want = [t.strip() for t in open(sys.argv[1]) if t.strip()]
else: want = [r[0] for r in sqlite3.connect(ROOT / "data/shortdash.sqlite").execute("select distinct ticker from prices")]
todo = [t for t in want if t not in have]
print("todo", len(todo), flush=True)
for i in range(0, len(todo), 100):
    ch = todo[i:i + 100]
    try: d = yf.download(ch, start="2022-06-01", actions=True, auto_adjust=False, group_by="ticker", threads=True, progress=False)
    except Exception as e: print("err", e); continue
    for t in ch:
        try: g = d[t] if isinstance(d.columns, pd.MultiIndex) else d
        except KeyError: have[t] = None; continue
        g = g.dropna(subset=["Close"]) if "Close" in g else g.iloc[0:0]
        if not len(g): have[t] = None; continue
        g = g.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume", "Stock Splits": "split"})
        g.index = pd.to_datetime(g.index).tz_localize(None)
        have[t] = g[["open", "high", "low", "close", "volume"] + (["split"] if "split" in g else [])].astype(float)
    pickle.dump(have, open(P, "wb")); print(i + len(ch), flush=True)
print("ok", sum(v is not None for v in have.values()))
