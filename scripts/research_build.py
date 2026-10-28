"""연구용 데이터셋 생성 (개발용, 앱 실행에는 필요 없음).
유니버스에서 무작위 N종목 → 매 거래일(step=1) 특징/신호 + 이후 10거래일 가격 경로 저장.
출력: data/research_ds.pkl  (커밋 안 함)
"""
import os, sys, time, random, pickle, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from core import db, sources as src, model, params as P, scan

N = int(os.environ.get("RS_N", 220)); STEP = int(os.environ.get("RS_STEP", 1)); DAYS = int(os.environ.get("RS_DAYS", 460))
OUT = os.path.join(os.path.dirname(db.DB_PATH), "research_ds.pkl")
FWD = 10

def prefetch(t):
    try:
        src.fetch_short_interest(t); src.fetch_filings(t); src.fetch_companyfacts(t); src.fetch_info(t)
    except Exception as e:
        print("prefetch", t, e)

def work(t):
    p = P.load(); reg = model.regime_series()
    b = model.Bundle(t, reg)
    if len(b.px) < 120: return []
    px = b.px.reset_index(drop=True)
    end = pd.Timestamp.today() - pd.Timedelta(days=16); start = pd.Timestamp.today() - pd.Timedelta(days=DAYS)
    idx = [i for i, d in enumerate(px["date"]) if start <= d <= end][::STEP]
    O, H, L, C, V = (px[k].values.astype(float) for k in ("open", "high", "low", "close", "volume"))
    rows = []
    for i in idx:
        if i + FWD >= len(px) or C[i] <= 0: continue
        d = px["date"].iloc[i]
        try:
            f = model.features(b, d, p)
        except Exception:
            continue
        if f is None: continue
        s = model.signals(f, p)
        dv20 = float((C[max(0, i - 19):i + 1] * V[max(0, i - 19):i + 1]).mean())
        zero20 = int((V[max(0, i - 19):i + 1] == 0).sum())
        c0 = C[i]
        rows.append({"ticker": t, "asof": d, "price": c0, "dv20": dv20, "zero20": zero20, "dilution_recent": bool(f.get("dilution_recent")),
                     "regime": f.get("regime", 1), **{f"s_{k}": (None if v is None else float(v)) for k, v in s.items()},
                     "fo": O[i + 1:i + 1 + FWD] / c0, "fh": H[i + 1:i + 1 + FWD] / c0, "fl": L[i + 1:i + 1 + FWD] / c0, "fc": C[i + 1:i + 1 + FWD] / c0})
    return rows

if __name__ == "__main__":
    t0 = time.time(); p = P.load()
    u = scan.universe(p)
    cnt = db.q("SELECT ticker, COUNT(*) n FROM prices GROUP BY ticker")
    pool = sorted(set(u.ticker))
    random.seed(7); sample = random.sample(pool, min(N, len(pool)))
    have = dict(zip(cnt.ticker, cnt.n))
    need = [t for t in sample if have.get(t, 0) < 380]
    print("universe", len(pool), "sample", len(sample), "need 2y prices", len(need), flush=True)
    if need: src.bulk_prices(need, period="2y")
    with ThreadPoolExecutor(4) as ex: list(ex.map(prefetch, sample))
    print("prefetch done", round(time.time() - t0), flush=True)
    rows = []
    with ProcessPoolExecutor(7) as ex:
        for k, r in enumerate(ex.map(work, sample, chunksize=2)):
            rows += r
            if k % 20 == 0: print("tick", k, len(rows), round(time.time() - t0), flush=True)
    df = pd.DataFrame(rows)
    pickle.dump(df, open(OUT, "wb"))
    print("done rows", len(df), "tickers", df.ticker.nunique() if len(df) else 0, "sec", round(time.time() - t0), flush=True)
