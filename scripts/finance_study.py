"""🏦 자금줄·세력 구조: 스냅샷(model/financiers.json) + 사건 검증(model/finance_study.json).
입력: data/finance_raw.pkl (scripts/finance_build.py), data/finance_yf.pkl (scripts/finance_yf.py, 분할 조정 일봉+분할), data/shortdash.sqlite.
검증은 룩어헤드 없음: 공시는 접수일 '다음 날'부터(filed < t), EFFECT 도 다음 날부터, 역분할은 분할일 당일부터(장 시작 전 공지),
매물대는 t 종가까지 60일. 결과 = t 종가 대비 5/20거래일 안 고가 +30% 터치, 5/20일 뒤 종가 수익률, 앱 성공 라벨(5폴드 표본외).
사용: python scripts/finance_study.py [--snap-only]"""
import sys, json, pickle, datetime as dt; from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / "scripts")); sys.path.insert(0, str(ROOT))
import numpy as np, pandas as pd, sqlite3
from core import finance as FZ

raw = pickle.load(open(ROOT / "data/finance_raw.pkl", "rb"))
YF = pickle.load(open(ROOT / "data/finance_yf.pkl", "rb"))

def rs_of(t):
    g = YF.get(t)
    if g is None or "split" not in g: return []
    s = g["split"]; s = s[(s > 0) & (s < 1)]
    return [(pd.Timestamp(d), float(r)) for d, r in s.items()]

# ---------------------------------------------------------------- 티커별 사실 모으기
FIN = {k: v for k, v in raw["fin"].items() if not v.get("dropped")}
by_t = {}
for k, rec in FIN.items():
    for cik, e in rec["issuers"].items():
        T = by_t.setdefault(e["ticker"], {"fin": [], "regs": [], "cik": cik})
        T["fin"].append(dict(k=k, first=e["first"], last=e["last"], n=e["n"], conv=e.get("conv_first"), eloc=e.get("eloc_first"),
                             dates=e.get("dates", []), conv_dates=e.get("conv_dates", []), eloc_dates=e.get("eloc_dates", [])))
for r in raw["regs"]:
    T = by_t.setdefault(r["ticker"], {"fin": [], "regs": [], "cik": r["cik"]})
    q = {k: r.get(k) for k in ("filed", "effect", "file_num", "withdrawn", "forms", "exchange")}
    # 본문 문서(첫 접수분의 S-1/F-1 본문 우선) — 앱에서 등록 주식 수·할인율 읽기용
    docs = sorted(r.get("docs") or [], key=lambda x: (not any(w in x.split(":")[1].lower() for w in ("s-1", "f-1", "s-3", "f-3", "s1", "f1", "s3", "f3")), x))
    q["doc"] = docs[0] if docs else None
    T["regs"].append(q)
for t, T in by_t.items():
    # 같은 파일번호 중복(문구별 검색) 합치기
    m = {}
    for r in T["regs"]:
        k = r["file_num"] or r["filed"]
        if k in m:
            if r["filed"] < m[k]["filed"]: m[k]["doc"] = r.get("doc") or m[k].get("doc")
            m[k]["filed"] = min(m[k]["filed"], r["filed"]); m[k]["forms"] = sorted(set(m[k]["forms"]) | set(r["forms"]))
        else: m[k] = dict(r, forms=sorted(set(r["forms"])))
    T["regs"] = sorted(m.values(), key=lambda r: r["filed"])
    T["exch"] = next((r.get("exchange") for r in T["regs"] if r.get("exchange")), None)
    T["rs"] = [[str(d.date()), r] for d, r in rs_of(t)]

# ---------------------------------------------------------------- 같은 자금줄 과거 결과 (분할 조정 yfinance 일봉)
def outcome(g, d, H=60):
    i = int(np.searchsorted(g.index.values, np.datetime64(d), side="left"))
    if i >= len(g) - 20: return None
    ref = g.close.iloc[i]
    if not ref or not np.isfinite(ref): return None
    w = g.iloc[i + 1: i + 1 + H]
    up = float(w.high.max() / ref - 1) * 100; dd = float(w.low.min() / ref - 1) * 100
    return up, dd, int(np.argmax(w.high.values)) + 1

def fin_stats():
    ST = {}; EV = []
    for k, rec in FIN.items():
        out = {"rs": [], "eff": []}
        for cik, e in rec["issuers"].items():
            t = e["ticker"]; g = YF.get(t)
            if g is None or not len(g): continue
            lo, hi = pd.Timestamp(e["first"]) - pd.Timedelta(days=30), pd.Timestamp(e["last"]) + pd.Timedelta(days=365)
            rs = rs_of(t)
            evs = [("rs", d) for d, _ in rs if lo <= d <= hi]
            evs += [("eff", pd.Timestamp(r["effect"])) for r in by_t.get(t, {}).get("regs", []) if r.get("effect") and lo <= pd.Timestamp(r["effect"]) <= hi]
            for typ, d in evs:
                o = outcome(g, d)
                if not o: continue
                rs180 = any(d < x <= d + pd.Timedelta(days=180) for x, _ in rs)
                out[typ].append((o[0], o[1], rs180)); EV.append(dict(fin=k, t=t, ev=typ, d=str(d.date()), up=round(o[0], 1), dd=round(o[1], 1), peak_day=o[2], rs180=rs180))
        st = {}
        for typ, L in out.items():
            if not L: continue
            a = np.array([(u, d) for u, d, _ in L]); st[typ] = dict(n=len(L), up_med=float(np.median(a[:, 0])), up100=float((a[:, 0] >= 100).mean() * 100),
                                                                    dd_med=float(np.median(a[:, 1])), rs180=float(np.mean([r for *_, r in L]) * 100))
        ST[k] = st
    return ST, EV

def snapshot(ST):
    fins = {k: dict(label=v["label"], docs_2024=v["docs_2024"], issuers=len(v["issuers"]),
                    both=sum(1 for e in v["issuers"].values() if e.get("conv_first") and e.get("eloc_first")), stats=ST.get(k, {})) for k, v in FIN.items()}
    tick = {}
    for t, T in by_t.items():
        tick[t] = {"fin": [{x: f[x] for x in ("k", "first", "last", "n", "conv", "eloc")} for f in T["fin"]],
                   "regs": T["regs"][-8:], "rs": T["rs"], "exch": T["exch"], "cik": T.get("cik")}
    drop = {k: v["label"] for k, v in raw["fin"].items() if v.get("dropped")}
    return {"built": raw.get("built"), "source": "SEC EDGAR 전문검색·제출목록, yfinance 분할", "financiers": fins, "dropped": drop, "tickers": tick}

# ---------------------------------------------------------------- 일별 신호 (DB 유니버스)
def daily(t, g):
    T = by_t.get(t) or {}
    rs = rs_of(t)
    g = FZ.adjust_px(g, rs)
    d = pd.to_datetime(g.date).values
    n = len(g); c, h, l, v = (g[x].values.astype(float) for x in ("close", "high", "low", "volume"))
    tp = (h + l + c) / 3
    W = 60; above = np.full(n, np.nan)
    if n >= W:
        from numpy.lib.stride_tricks import sliding_window_view as sw
        TP, V = sw(tp, W), sw(v, W)
        cc = c[W - 1:][:, None]
        with np.errstate(invalid="ignore", divide="ignore"):
            above[W - 1:] = np.nansum(V * (TP > cc), 1) / np.nansum(V, 1) * 100
    def recent(dates, days):     # dates < t 이고 t-days 이내
        if not dates: return np.zeros(n, bool)
        x = np.array(sorted(pd.to_datetime(dates).values))
        i = np.searchsorted(x, d, side="left") - 1          # x[i] < d
        ok = i >= 0
        last = np.where(ok, x[np.clip(i, 0, None)], np.datetime64("NaT"))
        return ok & ((d - last) <= np.timedelta64(days, "D"))
    fin = np.zeros(n, bool); both = np.zeros(n, bool)
    for f in T.get("fin", []):
        fin |= recent(f["dates"], 365)
        if f["conv_dates"] and f["eloc_dates"]:
            cf, ef = np.datetime64(min(f["conv_dates"])), np.datetime64(min(f["eloc_dates"]))
            both |= (d > cf) & (d > ef) & recent(f["dates"], 365)
    pend = np.zeros(n, bool); eff30 = np.zeros(n, bool)
    for r in T.get("regs", []):
        fd = np.datetime64(r["filed"]); ed = np.datetime64(r["effect"]) if r.get("effect") else None
        wd = np.datetime64(r["withdrawn"]) if r.get("withdrawn") else None
        p = (d > fd) & ((d - fd) <= np.timedelta64(180, "D"))
        if ed is not None: p &= d <= ed
        if wd is not None: p &= d <= wd
        pend |= p
        if ed is not None: eff30 |= (d > ed) & ((d - ed) <= np.timedelta64(30, "D"))
    rsd = np.array(sorted(x.to_datetime64() for x, _ in rs)) if rs else np.array([], "datetime64[ns]")
    rs90 = np.zeros(n, bool); rsm = np.zeros(n, bool)
    if len(rsd):
        j = np.searchsorted(rsd, d, side="right")      # rs ≤ t
        last = np.where(j > 0, rsd[np.clip(j - 1, 0, None)], np.datetime64("NaT"))
        rs90 = (j > 0) & ((d - last) <= np.timedelta64(90, "D"))
        j2 = np.searchsorted(rsd, d - np.timedelta64(730, "D"), side="right")
        rsm = (j - j2) >= 2
    fh = lambda k: pd.Series(h[::-1]).rolling(k, min_periods=1).max()[::-1].shift(-1).values / c - 1
    return pd.DataFrame(dict(ticker=t, date=d, price=c, dv20=pd.Series(c * v).rolling(20, min_periods=10).mean().values,
                             above=above, fin=fin, both=both, pending=pend, eff30=eff30, rs90=rs90, rsmulti=rsm, oh=above >= 70,
                             fh5=fh(5), fh20=fh(20), fc5=pd.Series(c).shift(-5).values / c - 1, fc20=pd.Series(c).shift(-20).values / c - 1,
                             n_fwd=np.arange(n)[::-1]))

def study():
    con = sqlite3.connect(ROOT / "data/shortdash.sqlite")
    px = pd.read_sql("SELECT ticker, date, open, high, low, close, volume FROM prices WHERE date >= '2023-06-01'", con)
    fr = []
    for i, (t, g) in enumerate(px.groupby("ticker")):
        if len(g) < 80: continue
        try: fr.append(daily(t, g.sort_values("date").reset_index(drop=True)))
        except Exception as e: print("skip", t, e)
        if i % 300 == 0: print(i, t, flush=True)
    F = pd.concat(fr, ignore_index=True); F.to_pickle(ROOT / "data/finance_frames.pkl")
    return F

def evaluate(F):
    out = {"signs": dict(FZ.SIGNS)}
    B = F[(F.price >= 0.05) & (F.price <= 15) & (F.dv20 >= 100e3) & (F.date >= "2024-01-01") & (F.n_fwd >= 20) & F.fh5.notna()].reset_index(drop=True)
    for k in ("5", "20"): B[f"hit{k}"] = (B[f"fh{k}"] >= 0.3).astype(int)
    cuts = np.quantile(B.date.astype("int64"), [0, .2, .4, .6, .8, 1]); seg = np.clip(np.searchsorted(cuts, B.date.astype("int64"), side="right") - 1, 0, 4)
    def row(m):
        s = B[m]
        if not len(s): return dict(n=0)
        return dict(n=int(len(s)), tickers=int(s.ticker.nunique()), hit5=round(float(s.hit5.mean()), 4), hit20=round(float(s.hit20.mean()), 4),
                    fc5_med=round(float(s.fc5.median()), 4), fc20_med=round(float(s.fc20.median()), 4),
                    fc20_mean=round(float(s.fc20.clip(-1, 3).mean()), 4))
    def folds(m):
        r = []
        for j in range(5):
            on, off = m & (seg == j), ~m & (seg == j)
            r.append(dict(n=int(on.sum()), hit5=round(float(B.hit5[on].mean()), 3) if on.sum() else None, base5=round(float(B.hit5[off].mean()), 3),
                          fc5=round(float(B.fc5[on].median()), 3) if on.sum() else None, base_fc5=round(float(B.fc5[off].median()), 3)))
        return r
    BB = {"base": row(np.ones(len(B), bool)), "signs": {}}
    for k, lab in FZ.SIGNS:
        m = B[k].values.astype(bool); fo = folds(m)
        up = sum(1 for x in fo if x["hit5"] is not None and x["n"] >= 30 and x["hit5"] > x["base5"])
        fcup = sum(1 for x in fo if x["fc5"] is not None and x["n"] >= 30 and x["fc5"] > x["base_fc5"])
        BB["signs"][k] = dict(name=lab, on=row(m), off=row(~m), folds=fo, hit5_up_folds=up, fc5_up_folds=fcup)
        print("B", k, BB["signs"][k]["on"], "off", BB["signs"][k]["off"]["hit5"], "up", up, "fcup", fcup, flush=True)
    # 조합: 효력 직후 + 위 매물대 / 자금줄 + 역분할
    for nm, m in (("eff30_oh", B.eff30 & B.oh), ("fin_rs90", B.fin & B.rs90), ("both_any", B.both), ("pending_oh", B.pending & B.oh), ("oh_low", B.above <= 20)):
        BB["signs"][nm] = dict(name=nm, on=row(m.values), folds=folds(m.values)); print("B", nm, BB["signs"][nm]["on"])
    out["B"] = BB
    # ---------- A: 앱 표본·성공 라벨 (5폴드 표본외)
    try:
        import sa_lib as L
        df, N = L.df, len(L.df)
        SU = pd.read_pickle(ROOT / "data/setup_all.pkl").drop_duplicates(["ticker", "asof"])
        SX = df[["ticker", "asof"]].merge(SU, on=["ticker", "asof"], how="left")
        VALID = SX.valid.fillna(False).values.astype(bool) & (SX.nfut.fillna(0).values >= 10)
        Y = (VALID & (SX.succ.fillna(0).values == 1)).astype(int)
        A_ = df[["ticker", "asof"]].assign(date=pd.to_datetime(df["asof"])).merge(F, on=["ticker", "date"], how="left")
        ev = np.any([f["te"] for f in L.folds], 0) & VALID
        def arow(m):
            s = ev & m; n = int(s.sum()); k = int(Y[s].sum())
            return dict(n=n, hit=round(k / n, 4) if n else None, ci=[round(float(x), 3) for x in L.wilson(k, n)] if n else None)
        def af(m): return [[int((f["te"] & VALID & m).sum()), round(float(Y[f["te"] & VALID & m].mean()), 3) if (f["te"] & VALID & m).sum() else None,
                            round(float(Y[f["te"] & VALID & ~m].mean()), 3)] for f in L.folds]
        AA = {"base": arow(np.ones(N, bool)), "covered": int((ev & A_.price.notna().values).sum()), "signs": {}}
        for k, lab in FZ.SIGNS:
            m = A_[k].fillna(False).values.astype(bool)
            AA["signs"][k] = dict(name=lab, on=arow(m), folds=af(m)); print("A", k, AA["signs"][k], flush=True)
        out["A"] = AA
    except Exception as e:
        out["A"] = {"error": repr(e)}; print("A err", e)
    # 점수 반영 규칙: 넓은 표본 5구간 중 ≥4 에서 hit5·fc5 둘 다 기준보다 좋고, 앱 표본 성공률 신뢰구간 하한 > 기준
    sc = {}
    for k, _ in FZ.SIGNS:
        b = BB["signs"][k]; a = (out.get("A") or {}).get("signs", {}).get(k, {}).get("on") or {}
        base = (out.get("A") or {}).get("base", {}).get("hit")
        sc[k] = bool(b["hit5_up_folds"] >= 4 and b["fc5_up_folds"] >= 4 and a.get("ci") and base is not None and a["ci"][0] > base)
    out["scored"] = sc
    out["note_ko"] = note_ko(out)
    return out

def note_ko(o):
    """카드에 보여줄 한 줄 요약 (숫자는 이 파일의 검증 결과에서만)."""
    B = o["B"]; b0 = B["base"]; A = o.get("A") or {}
    def p(x): return f"{x * 100:.0f}%" if x is not None else "데이터 없음"
    bits = []
    for k in ("pending", "eff30", "rs90", "oh"):
        s = B["signs"][k]; a = (A.get("signs") or {}).get(k, {}).get("on") or {}
        bits.append(f"{s['name']}: 5일 +30% 터치 {p(s['on']['hit5'])}(나머지 {p(s['off']['hit5'])}, {s['hit5_up_folds']}/5구간 우위) · "
                    f"5일 종가 중앙 {s['on']['fc5_med'] * 100:+.1f}%(나머지 {s['off']['fc5_med'] * 100:+.1f}%) · 앱 성공률 {p(a.get('hit'))}(전체 {p((A.get('base') or {}).get('hit'))})")
    n_sc = sum(o["scored"].values())
    head = (f"2024년~ 미래 안 보는 이벤트 검증({b0['n']:,}종목·일): 이 신호들은 급등 '터치'는 잦게 하지만 종가는 더 빠지고 앱 성공 기준은 낮춤 → "
            + ("점수 미반영(참고)" if not n_sc else f"{n_sc}개만 점수 반영"))
    return head + " | " + " | ".join(bits)

def timing():
    """ELOC 등록 접수 → EFFECT 걸린 날 (전체 등록)."""
    d = [(pd.Timestamp(r["effect"]) - pd.Timestamp(r["filed"])).days for T in by_t.values() for r in T["regs"] if r.get("effect")]
    nn = sum(1 for T in by_t.values() for r in T["regs"])
    return dict(n=nn, n_eff=len(d), med=float(np.median(d)) if d else None, p25=float(np.percentile(d, 25)) if d else None, p75=float(np.percentile(d, 75)) if d else None)

if __name__ == "__main__":
    ST, EV = fin_stats()
    snap = snapshot(ST)
    json.dump(snap, open(ROOT / "model/financiers.json", "w"), ensure_ascii=False, separators=(",", ":"))
    print("snapshot tickers", len(snap["tickers"]), "financiers", len(snap["financiers"]))
    if "--snap-only" in sys.argv: sys.exit()
    fp = ROOT / "data/finance_frames.pkl"
    F = pd.read_pickle(fp) if fp.exists() and "--rebuild" not in sys.argv else study()
    res = evaluate(F)
    res["timing"] = timing(); res["analog_events"] = len(EV)
    res["analog_by_fin"] = {k: v for k, v in ST.items() if v}
    res["built"] = dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    json.dump(res, open(ROOT / "model/finance_study.json", "w"), ensure_ascii=False, indent=1, default=float)
    pd.DataFrame(EV).to_csv(ROOT / "data/finance_analog_events.csv", index=False)
    print(json.dumps(res["scored"]), res["timing"])
