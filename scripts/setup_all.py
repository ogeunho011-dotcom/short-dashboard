"""데이터셋 전체 행(티커×날짜)에 대해 시점 재구성 숏 차수 셋업 + 셋업 기반 라벨 계산 → data/setup_all.pkl"""
import sys, time
sys.path.insert(0, "scripts"); sys.path.insert(0, ".")
import pandas as pd, numpy as np
from multiprocessing import Pool
def work(args):
    import setup_lib as S
    t, dates = args; out = []
    for d in dates:
        try:
            o = S.setup_at(t, d, H=10)
            if o:
                r = o[0]; m = o[2]
                r["tranches"] = [(x["name"], round(x["lo"], 4), round(x["hi"], 4), round(x["rem"]), round(x["ratio"], 3), x["tag"], x["side"], round(x["age"], 1)) for x in m["tranches"]]
                r["hi21"] = m["hi21"]; r["lo21"] = m["lo21"]; r["total_rem"] = m["total_rem"]; r["scaled_si"] = m["scaled_to_si"]
                out.append(r)
        except Exception as e:
            pass
    return out
if __name__ == "__main__":
    df = pd.read_pickle("data/research_ds.pkl")[["ticker", "asof", "price", "dv20", "zero20", "fh"]]
    df = df[(df.price >= 0.05) & (df.dv20 >= 1e5) & (df.zero20 <= 3) & (df.fh.apply(len) == 10)]
    jobs = [(t, list(g["asof"])) for t, g in df.groupby("ticker")]
    print(len(df), "rows", len(jobs), "tickers", flush=True)
    t0 = time.time(); rows = []
    with Pool(6) as pool:
        for i, r in enumerate(pool.imap_unordered(work, jobs)):
            rows += r
            if i % 20 == 0: print(i, len(rows), round(time.time() - t0), flush=True)
    out = pd.DataFrame(rows); out.to_pickle("data/setup_all.pkl"); print("saved", len(out), round(time.time() - t0))
