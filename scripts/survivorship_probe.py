"""생존 편향 점검: 2025-03-03 FINRA CNMS 파일에는 있었는데 2026-10-26 파일에는 없는 종목(=상폐·합병·티커변경)을
yfinance 로 받아볼 수 있는지, 받아지면 그 기간 수익률이 어땠는지 확인. 출력 model/survivorship_probe.json"""
import sys, json, time, re, warnings, sqlite3
warnings.filterwarnings("ignore")
import pandas as pd, numpy as np, yfinance as yf
sys.path.insert(0, ".")
a = pd.read_csv("/tmp/finra_20250303.csv"); b = pd.read_csv("/tmp/finra_20261026.csv")
a = a[a.Symbol.notna() & a.Market.astype(str).str.contains("Q")]   # Market 에 Q(나스닥 TRF) 포함 행만
a = a[a.Symbol.astype(str).str.fullmatch(r"[A-Z]{1,4}")]           # 보통주형 1~4글자 (워런트·유닛 제외)
gone = sorted(set(a.Symbol) - set(b.Symbol.dropna()))
con = sqlite3.connect("data/shortdash.sqlite")
uni = set(r[0] for r in con.execute("select ticker from universe"))
print("2025-03 symbols", len(a), "gone", len(gone), flush=True)
# 표본 200개(무작위 고정 시드) · 종목별 개별 요청 · 요청 제한(429)이면 기다렸다 재시도 → "데이터 없음"과 "막힘"을 구분
import random
random.seed(7); samp = sorted(random.sample(gone, min(200, len(gone))))
rows = []; n_rl = 0; errs = {}
for t in samp:
    g = pd.DataFrame(); err = None
    for a_ in range(5):
        try:
            g = yf.Ticker(t).history(start="2025-03-01", end="2026-10-28", interval="1d", auto_adjust=True, raise_errors=True); err = None; break
        except Exception as e:
            err = type(e).__name__
            if "RateLimit" in err: n_rl += 1; time.sleep(30 * (a_ + 1)); continue
            break
    errs[err] = errs.get(err, 0) + 1
    g = g.dropna(subset=["Close"]) if len(g) else g
    rows.append(dict(ticker=t, err=err, n=int(len(g)), first=str(g.index[0].date()) if len(g) else None, last=str(g.index[-1].date()) if len(g) else None,
                     p0=float(g.Close.iloc[0]) if len(g) else None, p1=float(g.Close.iloc[-1]) if len(g) else None))
    time.sleep(0.7)
print("errors", errs, flush=True)
R = pd.DataFrame(rows); got = R[R.n > 20].copy()
got["ret"] = got.p1 / got.p0 - 1
small = got[got.p0 < 10]
out = dict(sample=len(samp), errors=errs, rate_limit_retries=n_rl, created=time.strftime("%Y-%m-%d %H:%M KST"), n_q_symbols_2025_03=int(len(a)), n_gone=len(gone), n_yf_any=int((R.n > 0).sum()), n_yf_20d=int(len(got)),
           coverage=float(len(got) / max(len(samp), 1)),
           median_ret_got=float(got.ret.median()) if len(got) else None, share_down50=float((got.ret < -0.5).mean()) if len(got) else None,
           n_under10=int(len(small)), median_ret_under10=float(small.ret.median()) if len(small) else None,
           sample_got=got.sort_values("ret").head(15)[["ticker", "first", "last", "p0", "p1", "ret"]].to_dict("records"),
           sample_missing=list(R[R.n == 0].ticker.head(30)))
json.dump(out, open("model/survivorship_probe.json", "w"), ensure_ascii=False, indent=1, default=str)
print({k: v for k, v in out.items() if not k.startswith("sample")})
