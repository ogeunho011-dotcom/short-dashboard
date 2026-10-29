"""스크리너 (소형주 급등 패턴 스캔) + 시장 통계."""
import json, re, time, datetime as dt
import numpy as np, pandas as pd
from . import sources as src, db, model

BAD_NAME = re.compile(r"\b(Warrant|Warrants|Right|Rights|Unit|Units|Preferred|Notes?|Depositary Shares? representing|Acquisition Corp\w*|Dep Shr|Capital Trust)\b", re.I)

def universe(p=None):
    """기본: 나스닥·NYSE·NYSE American 상장 초소형~소형 보통주 전부 (시총 < $2B, 주가 $0.05 이상, 장외 제외). 관리 탭에서 조정.
    시총 미상(스크리너에 시총이 없는 신규 상장 등)도 포함."""
    from . import params as P
    p = p or P.load()
    u = db.q("SELECT * FROM universe")
    if len(u) == 0:
        src.fetch_universe(); u = db.q("SELECT * FROM universe")
    if "tier" not in u: u["tier"] = None
    mc = float(p.get("univ_max_mcap_m", 2000)) * 1e6
    u = u[(u.price >= float(p.get("univ_min_price", 0.05))) & (u.price <= float(p.get("univ_max_price", 1000)))
          & (((u.mcap > 0) & (u.mcap <= mc)) | (u.tier == "unknown"))
          & ~u["name"].fillna("").str.contains(BAD_NAME) & u.ticker.str.match(r"^[A-Z]{1,5}$")]
    return u

def quick_rank(tickers, p):
    """가격만으로 1차 선별: 거래량 증가, 응축, 단기 모멘텀."""
    rows = []
    allpx = db.q(f"SELECT * FROM prices WHERE date >= ? ORDER BY ticker, date", ((dt.date.today() - dt.timedelta(days=200)).isoformat(),))
    if len(allpx) == 0: return pd.DataFrame()
    newest = pd.to_datetime(allpx["date"]).max()
    for t, x in allpx[allpx.ticker.isin(tickers)].groupby("ticker"):
        if len(x) < 30: continue
        if pd.Timestamp(x["date"].iloc[-1]) < newest - pd.Timedelta(days=6): continue       # 최근 거래 없음 (정지·상폐)
        c, v = x["close"].values, x["volume"].values.astype(float)
        if int((np.abs(np.diff(c[-11:])) < 1e-9).sum()) >= 5: continue                      # 10일 중 5일 이상 가격 변화 0 → 죽은 종목
        if float(np.median(c[-20:] * v[-20:])) < float(p.get("univ_min_dv_k", 100)) * 1e3 * 0.3: continue   # 중앙값 거래대금도 너무 낮으면 제외
        dv = float((c[-20:] * v[-20:]).mean())
        if dv < float(p.get("univ_min_dv_k", 100)) * 1e3: continue          # 죽은 종목 제외
        if int((v[-20:] == 0).sum()) > int(p.get("univ_max_zero_days", 3)): continue
        vr = model.vol_ratio(v, p)
        base = max(float(np.median(v[-21:-1])), float(v[-21:-1].mean()) * 0.5, float(p.get("vol_base_floor", 20000)))
        v5 = v[-5:].mean() / base
        r5 = c[-1] / c[-6] - 1
        h_ = x["high"].values; o_ = x["open"].values
        brk = c[-1] > h_[-21:-1].max(); gap = o_[-1] / c[-2] - 1 if c[-2] > 0 else 0
        streak = int(all(v[-i] > v[-i - 1] for i in (1, 2, 3)))
        runner = int(np.nansum(h_[-250:] / np.r_[np.nan, c[:-1]][-250:] - 1 >= 0.5))
        q = (min(vr, 6) + min(v5, 4) + (2 if -0.2 < r5 < 0.3 else 0) + (1 if c[-1] < 1 else 0)
             + 1.5 * brk + (1.5 if gap >= 0.08 and c[-1] >= o_[-1] else 0) + streak + min(runner, 3) * 0.5)
        rows.append({"ticker": t, "q": q, "vol_ratio": vr, "dv20": dv, "ret5": r5 * 100, "price": c[-1]})
    return pd.DataFrame(rows).sort_values("q", ascending=False) if rows else pd.DataFrame()

def exclusion_flags(b: model.Bundle, news=None):
    now = pd.Timestamp.today()
    fil = b.fil
    dil = bool(len(fil) and len(fil[(fil.filed >= now - pd.Timedelta(days=90)) & fil.form.str.match(r"^(S-1|S-3|F-1|F-3|424B)")]))
    rs = bool(any(pd.Timestamp(d) >= now - pd.Timedelta(days=365) and r < 1 for d, r in (b.info.get("splits") or [])))
    rs = rs or bool(len(fil) and len(fil[(fil.filed >= now - pd.Timedelta(days=180)) & (fil.form == "8-K") & fil["items"].str.contains("5.03", na=False) & fil["items"].str.contains("3.03", na=False)]))
    law = bool(news and any(re.search(r"lawsuit|class action|securities fraud|investigation|subpoena", it.get("title", ""), re.I) for it in news[:20]))
    return {"dilution": dil, "reverse_split": rs, "lawsuit": law}

def _analyze(t, u, reg, p, hot=None, keep=None, bars=None):
        try:
            src.fetch_short_interest(t); src.fetch_filings(t); src.fetch_companyfacts(t)
            info = src.fetch_info(t)
            b = model.Bundle(t, reg)
            fresh = False
            if bars and t in bars: b.px, fresh = src.merge_today(b.px, bars[t])   # Yahoo 일봉 지연 보정
            f = model.features(b, b.px["date"].iloc[-1], p)
            if f is None: return None
            from . import live as _lv
            if _lv.session_now()[0] != "closed": f["_live"] = True
            f.update(model.live_feats(info or {}, None, hot))
            mf = float(p.get("univ_max_float_m", 0) or 0)
            if mf and f.get("float_m") is not None and f["float_m"] > mf: return None
            if keep is not None: keep[t] = f
            if not (float(p.get("univ_min_price", 0)) <= f["price"] <= float(p.get("univ_max_price", 1e9)) * 1.5): return None  # 최신 종가 기준 재확인
            s = model.score(f, p)
            news = src.fetch_news(t)
            ex = exclusion_flags(b, news)
            meta = f.get("_meta", {})
            up = (meta["reignite"] / f["price"] - 1) * 100 if meta.get("reignite") else None
            status = "가능" if s["flagged"] else ("대기" if s["score"] >= p["flag_score"] - 10 else "관망")
            dil = model.dilution(b)
            try:
                from . import pattern as PT
                pm = PT.match(b.px, f, getattr(b, "info", None), getattr(b, "fil", None)); pl = PT.line(pm) or ""
            except Exception: pm, pl = None, ""
            try:
                from . import structure as ST
                sm = ST.compute(b.px, getattr(b, "fil", None), getattr(b, "facts", None), info); sl = ST.line(sm) or ""
            except Exception: sm, sl = None, ""
            return {"ticker": t, "name": (u.set_index("ticker").name.get(t) or "")[:40], "price": f["price"], "chg1": f["chg1"],
                         "score": s["score"], "level": s["level"], "conf": s["confluence"], "flagged": s["flagged"], "status": status,
                         "upside": up, "loss_pct": f.get("loss_pct"), "si_float": f.get("si_float"), "vol_ratio": f.get("vol_ratio"),
                         "runway": dil.get("runway_m"), "dil_score": dil["score"], **ex, "on": ",".join(s["on"]),
                    "mcap": float(u.set_index("ticker").mcap.get(t) or 0), "float_m": f.get("float_m"), "industry": (info or {}).get("industry"),
                    "dtc": f.get("dtc"), "summary": model.plain_summary(f), "fresh_1m": fresh,
                    "last_date": str(b.px["date"].iloc[-1].date()),
                    "pat_n": pm["n"] if pm else None, "pat_on": ",".join(x["label"] for x in pm["hits"] if x["on"]) if pm else "",
                    "pat_line": pl, "st_n": sm["n"] if sm else None, "st_on": ",".join(sm["on"]) if sm else "", "st_line": sl}
        except Exception as e:
            db.set_status("스캔", False, f"{t}: {e!r}"[:200]); return None

PRICE_LOG = {}

def refresh_universe_prices(tick, full_days=7):
    """유니버스 일봉 갱신 (종목이 4천 가까이 돼도 가볍게):
    새 종목(DB 에 없거나 60일 미만) → 2년치 · 주 1회 전체 → 1년치 · 그 외 날 → 1개월치 + 액면 병합 감지 시 그 종목만 2년치 다시.
    6시간 안에 같은 목록이면 건너뜀."""
    t0 = time.time()
    last = db.kv_get("bulk_done", 6 * 3600)
    if last and not (set(tick) - set(last)): PRICE_LOG.update(mode="건너뜀(6시간 내)"); return
    have = db.q("SELECT ticker, COUNT(*) n FROM prices GROUP BY ticker")
    n_of = dict(zip(have.ticker, have.n))
    new = [t for t in tick if n_of.get(t, 0) < 60]
    old = [t for t in tick if n_of.get(t, 0) >= 60]
    lf = db.kv_get("bulk_full_ts")
    full = not lf or time.time() - float(lf) > full_days * 86400
    got_new = src.bulk_prices(new, "2y") if new else 0
    got_old = src.bulk_prices(old, "1y" if full else "1mo", split_check=not full) if old else 0
    if full and old: db.kv_set("bulk_full_ts", time.time())
    db.kv_set("bulk_done", tick)
    PRICE_LOG.clear(); PRICE_LOG.update(mode="주간 전체(1년)" if full else "매일(1개월)", new=len(new), got_new=got_new, old=len(old), got_old=got_old,
                                        resplit=len(src.YF_LOG.get("resplit") or []), secs=round(time.time() - t0))

def run_scan(p, top_k=None, refresh_prices=True, progress=None, workers=6):
    """1) 유니버스 전체 일봉 일괄 다운로드(캐시) → 2) 가격 기반 1차 순위 → 3) 상위 top_k 정밀 분석 (병렬, SI/공시 12h·재무 24h 캐시)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    top_k = int(top_k or p.get("scan_top_k", 150))
    u = universe(p)
    tick = list(u.ticker)
    if refresh_prices: refresh_universe_prices(tick)
    qr = quick_rank(tick, p)
    if len(qr) == 0: return pd.DataFrame()
    cand = list(qr.ticker.head(top_k))
    reg = model.regime_series()
    rows, keep = [], {}
    try: bars = src.bulk_today_bars(cand)
    except Exception: bars = {}
    with ThreadPoolExecutor(workers) as ex_:
        futs = {ex_.submit(_analyze, t, u, reg, p, None, keep, bars): t for t in cand}
        for i, fu in enumerate(as_completed(futs)):
            r = fu.result()
            if r: rows.append(r)
            if progress: progress((i + 1) / len(cand), futs[fu])
    # 업종 동조: 오늘 +20% 이상 급등한 대장주가 있는 업종의 다른 종목 → 재채점 (라이브 전용 조건)
    lead = {}
    for r in rows:
        if r.get("industry") and r["chg1"] >= 20 and r["chg1"] > lead.get(r["industry"], (None, 0))[1]: lead[r["industry"]] = (r["ticker"], r["chg1"])
    for r in rows:
        ld = lead.get(r.get("industry"))
        f = keep.get(r["ticker"])
        if f is None: continue
        f["sympathy"] = bool(ld and ld[0] != r["ticker"])
        s2 = model.score(f, p)
        r.update({"score": s2["score"], "level": s2["level"], "conf": s2["confluence"], "flagged": s2["flagged"], "on": ",".join(s2["on"]),
                  "status": "가능" if s2["flagged"] else ("대기" if s2["score"] >= p["flag_score"] - 10 else "관망"),
                  "sympathy_of": ld[0] if f["sympathy"] else None})
    df = pd.DataFrame(rows)
    db.kv_set("hot_industries", [{"industry": k, "leader": v[0], "chg": v[1]} for k, v in lead.items()])
    ts = db.now_kst()
    try:   # 이전 스캔 기억 → 스캐너 탭 '신규·해제' 계산용
        old, om = last_scan()
        if len(old):
            db.kv_set("screen_prev", {"ts": (om or {}).get("ts"), "tickers": list(old.ticker), "flagged": list(old[old.flagged.astype(bool)].ticker)})
    except Exception: pass
    db.exec_("DELETE FROM scans WHERE kind='screen'")
    db.upsert_rows("scans", ["ts", "kind", "ticker", "data"], [(ts, "screen", r["ticker"], json.dumps(r, default=float)) for r in rows])
    db.kv_set("last_scan", {"ts": ts, "universe": len(u), "ranked": len(qr), "scored": len(df)})
    db.set_status("스캔", True, f"{len(u)}종목 중 {len(df)}종목 정밀분석")
    return df

def last_scan():
    x = db.q("SELECT ts, data FROM scans WHERE kind='screen'")
    if len(x) == 0: return pd.DataFrame(), None
    return pd.DataFrame([json.loads(d) for d in x["data"]]), db.kv_get("last_scan")

def gainer_continuation(jump=30.0, days=250):
    """전일 +jump% 급등주의 다음날 성과 (DB 내 전 종목)."""
    px = db.q("SELECT ticker,date,open,high,low,close,volume FROM prices WHERE date >= ? ORDER BY ticker,date",
              ((dt.date.today() - dt.timedelta(days=days * 1.5)).isoformat(),))
    rec = []
    for t, x in px.groupby("ticker"):
        c, o, h = x.close.values, x.open.values, x.high.values
        for i in range(1, len(x) - 1):
            g = (c[i] / c[i - 1] - 1) * 100
            if g >= jump and c[i - 1] * x.volume.values[i] > 5e5:
                rec.append({"ticker": t, "date": x.date.values[i], "gain": g, "next_open": (o[i + 1] / c[i] - 1) * 100,
                            "next_high": (h[i + 1] / c[i] - 1) * 100, "next_close": (c[i + 1] / c[i] - 1) * 100})
    return pd.DataFrame(rec)

def premarket_stats(ticker):
    """최근 5일 1분봉으로 프리마켓 갭 vs 정규장 고가 (무료 1분봉은 최근 ~7일만 제공)."""
    from . import live
    df = live.intraday(ticker)
    if len(df) == 0: return pd.DataFrame()
    df = df.assign(d=df.ts.dt.date, s=df.ts.apply(live._sess))
    out = []; prev = None
    for d, x in df.groupby("d"):
        pre, reg = x[x.s == "pre"], x[x.s == "regular"]
        if prev and len(reg):
            out.append({"date": str(d), "pre_gap": (pre.close.iloc[-1] / prev - 1) * 100 if len(pre) else None, "pre_vol": float(pre.volume.sum()),
                        "reg_high": (reg.high.max() / prev - 1) * 100, "reg_close": (reg.close.iloc[-1] / prev - 1) * 100})
        if len(reg): prev = float(reg.close.iloc[-1])
    return pd.DataFrame(out)

def hot_runner_corr(ticker, n=10):
    g = gainer_continuation(30, 30)
    if len(g) == 0: return None
    hot = list(g.sort_values("date").ticker.unique()[-n:])
    px = db.q("SELECT ticker,date,close FROM prices WHERE date >= ?", ((dt.date.today() - dt.timedelta(days=45)).isoformat(),))
    pv = px.pivot_table(index="date", columns="ticker", values="close").pct_change()
    if ticker not in pv: return None
    cs = {h: float(pv[ticker].corr(pv[h])) for h in hot if h in pv and h != ticker}
    return {"hot": hot, "corr": cs, "avg": float(np.nanmean(list(cs.values()))) if cs else None}
