"""일봉 가정 vs 5분봉 실제 경로 재검증 (최근 ~60일, yfinance 5분봉 한도).
- 대상: entry_timing 과 같은 표본외 신호(상위5% 재학습 · 셋업 유효 · 10일 쿨다운) 중 10일 보유 창 전체가 5분봉 범위에 들어오는 것
- 일봉 규칙(setup_lib.score_path 동일): 같은 날 손절·목표 동시 터치 → 손절 우선 (보수적)
- 5분봉 규칙: 같은 규칙을 5분 단위 시간순으로 적용. 한 5분봉 안에서 동시 터치면 역시 손절 우선. 정규장만(프리/애프터 제외)
- 출력: model/intraday_retest.json"""
import sys, json, time, warnings
warnings.filterwarnings("ignore")
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / "scripts"))
src = (ROOT / "scripts/entry_timing.py").read_text(encoding="utf-8")
exec(compile(src[:src.index("t0 = time.time()")], "entry_timing_prefix", "exec"), globals())
import yfinance as yf

START = pd.Timestamp.today().normalize() - pd.Timedelta(days=58)
cand = []
for i in IDX:
    wv = window(i)
    if wv is None: continue
    t = df.ticker.values[i]; d = pd.Timestamp(df["asof"].values[i]); b = BARS[t]; p0 = DPOS[t][d]
    days = list(b["date"].iloc[p0 + 1: p0 + 1 + H])
    if pd.Timestamp(days[0]) >= START: cand.append((i, t, d, days))
print("cands", len(cand), flush=True)

def daily_path(i):
    return run_rule(i, ("close",))

def m5_path(i, bars, days):
    price, rl, stop, ph = float(SX.price.values[i]), float(SX.rl.values[i]), float(SX.stop.values[i]), float(SX.ph.values[i])
    pos, real, st_, tp1 = 1.0, 0.0, stop, False
    ambig = 0
    for d in days:
        db_ = bars[bars.index.normalize() == pd.Timestamp(d)]
        if not len(db_): return None
        for _, r in db_.iterrows():
            o, h, l = float(r.Open), float(r.High), float(r.Low)
            if l <= st_ and ((not tp1 and h >= rl) or (tp1 and h >= ph)): ambig += 1
            if l <= st_:
                real += pos * (min(o, st_) / price - 1); return dict(ret=real - COST, hit=int(tp1), ambig5=ambig)
            if not tp1 and h >= rl:
                tp1 = True; real += 0.5 * (max(o, rl) / price - 1); pos = 0.5; st_ = price
            if tp1 and h >= ph:
                real += pos * (max(o, ph) / price - 1); return dict(ret=real - COST, hit=1, ambig5=ambig)
        last_c = float(db_.Close.iloc[-1])
    return dict(ret=real + pos * (last_c / price - 1) - COST, hit=int(tp1), ambig5=ambig)

def daily_ambig(i):
    d0, o, h, l, c = window(i)
    rl, stop, ph = float(SX.rl.values[i]), float(SX.stop.values[i]), float(SX.ph.values[i])
    return int(any((l[j] <= stop and h[j] >= rl) for j in range(H)))

rows = []
tick = sorted({t for _, t, _, _ in cand})
data = {}
for k in range(0, len(tick), 20):
    grp = tick[k:k + 20]
    try:
        raw = yf.download(grp, period="60d", interval="5m", prepost=False, group_by="ticker", progress=False, auto_adjust=False, threads=True)
    except Exception as e:
        print("dl err", e); continue
    for t in grp:
        try:
            g = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
            g = g.dropna(subset=["Open"])
            if len(g):
                g.index = g.index.tz_convert("America/New_York").tz_localize(None); data[t] = g
        except Exception: pass
print("5m tickers", len(data), "/", len(tick), flush=True)
for i, t, d, days in cand:
    dd = daily_path(i); g = data.get(t)
    m = m5_path(i, g, days) if g is not None else None
    rows.append(dict(ticker=t, asof=str(d.date()), daily_ret=dd["ret"], daily_hit=dd["hit"], daily_ambig=daily_ambig(i),
                     m5_ret=None if m is None else m["ret"], m5_hit=None if m is None else m["hit"], m5_ambig=None if m is None else m["ambig5"]))
R = pd.DataFrame(rows); ok = R.dropna(subset=["m5_ret"])
out = dict(created=time.strftime("%Y-%m-%d %H:%M KST"), window_start=str(START.date()), n_cand=int(len(R)), n_5m=int(len(ok)),
           daily_exp=float(ok.daily_ret.mean()) if len(ok) else None, m5_exp=float(ok.m5_ret.mean()) if len(ok) else None,
           daily_ci=boot(ok.daily_ret.values) if len(ok) > 1 else None, m5_ci=boot(ok.m5_ret.values) if len(ok) > 1 else None,
           daily_hit=float(ok.daily_hit.mean()) if len(ok) else None, m5_hit=float(ok.m5_hit.mean()) if len(ok) else None,
           daily_hit_ci=wil(int(ok.daily_hit.sum()), len(ok)) if len(ok) else None, m5_hit_ci=wil(int(ok.m5_hit.sum()), len(ok)) if len(ok) else None,
           n_daily_ambiguous=int(ok.daily_ambig.sum()) if len(ok) else 0, n_5m_bar_ambiguous=int((ok.m5_ambig > 0).sum()) if len(ok) else 0,
           n_outcome_changed=int((ok.daily_hit != ok.m5_hit).sum()) if len(ok) else 0,
           mean_abs_diff=float((ok.daily_ret - ok.m5_ret).abs().mean()) if len(ok) else None,
           rows=rows)
json.dump(out, open(ROOT / "model/intraday_retest.json", "w"), ensure_ascii=False, indent=1, default=str)
print({k: v for k, v in out.items() if k != "rows"})
print(ok.to_string())
