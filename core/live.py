"""실시간(지연 가능) 분석: yfinance 1분봉(prepost=True) → 오늘 봉 합성 → 점수/확률/레벨 재계산 + 라이브 트리거.
무료 데이터라 수 분 지연될 수 있음."""
import datetime as dt, json, time
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
from . import sources as src, db, model, buyprice

ET, KST = ZoneInfo("America/New_York"), ZoneInfo("Asia/Seoul")

def session_now(now=None):
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(ET)
    if now.weekday() >= 5: return "closed", now
    m = now.hour * 60 + now.minute
    if 4 * 60 <= m < 9 * 60 + 30: return "pre", now
    if 9 * 60 + 30 <= m < 16 * 60: return "regular", now
    if 16 * 60 <= m < 20 * 60: return "post", now
    return "closed", now

SESSION_KO = {"pre": "프리마켓", "regular": "정규장", "post": "애프터마켓", "closed": "장 마감"}

_MEM = {}   # 일괄 시세(batch_intraday)로 받은 1분봉: {ticker: (받은 시각, DataFrame)}

def _norm(h):
    h = h.tz_convert(ET) if h.index.tz is not None else h.tz_localize(ET)
    return pd.DataFrame({"ts": h.index, "open": h["Open"].values, "high": h["High"].values, "low": h["Low"].values,
                         "close": h["Close"].values, "volume": h["Volume"].values}).dropna(subset=["close"]).reset_index(drop=True)

def batch_intraday(tickers, period="5d", chunk=200):
    """여러 종목 1분봉(prepost)을 한 번에 받아 메모리 캐시에 넣음 (yfinance 일괄 다운로드, 156종목 약 4초).
    반환: {ticker: DataFrame} (빈 응답 종목은 빠짐)."""
    import yfinance as yf
    out, now = {}, time.time()
    tk = list(dict.fromkeys(t.upper() for t in tickers if t))
    for i in range(0, len(tk), chunk):
        ch = tk[i:i + chunk]
        try:
            d = yf.download(ch, period=period, interval="1m", prepost=True, group_by="ticker", threads=True,
                            progress=False, auto_adjust=False)
        except Exception:
            continue
        if d is None or len(d) == 0: continue
        for t in ch:
            try:
                h = d[t] if isinstance(d.columns, pd.MultiIndex) else d
                h = h.dropna(subset=["Close"])
                if len(h): out[t] = _norm(h)
            except Exception:
                pass
    for t, df in out.items(): _MEM[t] = (now, df)
    db.set_status("yfinance 1분봉(일괄)", bool(out), f"{len(out)}/{len(tk)}종목")
    return out

def intraday(ticker, ttl=50):
    m = _MEM.get(ticker)
    if m is not None and time.time() - m[0] < max(ttl, 150): return m[1]
    k = f"live1m:{ticker}"
    c = db.kv_get(k, ttl)
    if c is not None:
        df = pd.DataFrame(c)
        if len(df): df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(ET)
        return df
    h = src.fetch_intraday(ticker, period="5d", interval="1m")
    if h is None or len(h) == 0:
        db.set_status("yfinance 1분봉", False, f"{ticker} 빈 응답"); return pd.DataFrame()
    df = _norm(h)
    db.kv_set(k, df.assign(ts=df["ts"].astype(str)).to_dict("records"))
    db.set_status("yfinance 1분봉", True, f"{ticker} {len(df)}봉 (prepost)")
    return df

def _sess(ts):
    m = ts.hour * 60 + ts.minute
    return "pre" if m < 570 else ("regular" if m < 960 else "post")

def intraday_vwap(df):
    """오늘 정규장 1분봉 VWAP (참고용 · 1분봉 과거 데이터가 짧아 백테스트 불가)."""
    try:
        if df is None or len(df) == 0: return None
        d = df.assign(d=df["ts"].dt.date, s=df["ts"].apply(_sess))
        t = d[(d.d == d["d"].max()) & (d.s == "regular")]
        v = t["volume"].fillna(0)
        if len(t) < 5 or v.sum() <= 0: return None
        return float((((t["high"] + t["low"] + t["close"]) / 3) * v).sum() / v.sum())
    except Exception:
        return None

def ext_hours(df):
    """오늘(가장 최근 거래일) 프리/정규/애프터 고저 및 직전 정규장 종가."""
    if len(df) == 0: return {}
    df = df.assign(d=df["ts"].dt.date, s=df["ts"].apply(_sess))
    days = sorted(df["d"].unique()); last = days[-1]
    today = df[df.d == last]; out = {"day": str(last)}
    for s in ("pre", "regular", "post"):
        x = today[today.s == s]
        if len(x): out[s] = {"hi": float(x.high.max()), "lo": float(x.low.min()), "last": float(x.close.iloc[-1]), "vol": float(x.volume.sum())}
    reg_today = today[today.s == "regular"]
    prev_reg = None
    for d in reversed(days[:-1]):
        x = df[(df.d == d) & (df.s == "regular")]
        if len(x): prev_reg = float(x.close.iloc[-1]); out["prev_date"] = str(d); break
    out["prev_close"] = prev_reg
    out["reg_close"] = float(reg_today.close.iloc[-1]) if len(reg_today) and _sess(df.ts.iloc[-1]) != "regular" else None
    out["last"] = float(df.close.iloc[-1]); out["last_ts"] = df.ts.iloc[-1]
    # 프리마켓 갭 & 거래량
    if "pre" in out and prev_reg: out["pre_gap"] = (out["pre"]["last"] / prev_reg - 1) * 100
    return out

def ref_close(eh, px=None, now=None):
    """등락률 기준 종가 (전일 정규장 종가). 1분봉만 믿으면 틀릴 수 있어(예: 오늘 봉이 아직 없을 때 '어제 급등'을 오늘 등락으로 계산 → AEYE +40%)
    일봉 DB 로 교차 확인. 반환: (기준 종가, 기준 날짜 문자열) — 모르면 (None, None).
    규칙: 오늘(ET) 날짜 직전 거래일의 일봉 종가가 있으면 그것을 우선, 없으면 1분봉의 직전 정규장 종가.
    1분봉 마지막 날이 오늘이 아니면(오늘 체결 없음) 그날 자신의 정규장 종가 기준 → 시간외 등락만 표시."""
    eh = eh or {}
    today = (now or dt.datetime.now(ET)).astimezone(ET).strftime("%Y-%m-%d")
    day = str(eh.get("day") or "")
    daily = None
    try:
        if px is not None and len(px):
            d = pd.to_datetime(px["date"]).dt.strftime("%Y-%m-%d")
            ref_day = day if day and day < today else today
            m = px[(d < ref_day).values]
            if day and day < today:      # 오늘 체결이 아직 없음 → 그날 정규장 종가가 기준
                same = px[(d == day).values]
                if eh.get("reg_close"): return float(eh["reg_close"]), day
                if len(same): return float(same["close"].iloc[-1]), day
            if len(m): daily = (float(m["close"].iloc[-1]), str(pd.Timestamp(m["date"].iloc[-1]).date()))
    except Exception:
        daily = None
    if day and day < today and eh.get("reg_close"): return float(eh["reg_close"]), day
    mp = (eh.get("prev_close"), eh.get("prev_date"))
    if daily and (not mp[0] or not mp[1] or daily[1] >= str(mp[1])): return daily
    return mp if mp[0] else (None, None)

def today_bar(df):
    """최근 거래일 정규장(없으면 프리) 1분봉 → 일봉 합성."""
    if len(df) == 0: return None
    d = df["ts"].dt.date; last = d.max(); x = df[d == last]
    reg = x[x["ts"].apply(_sess) == "regular"]
    y = reg if len(reg) else x
    return {"date": pd.Timestamp(last), "open": float(y.open.iloc[0]), "high": float(y.high.max()), "low": float(y.low.min()),
            "close": float(x.close.iloc[-1]), "volume": float(y.volume.sum())}

def triggers(ticker, df, f, meta, prev_state):
    """라이브 트리거: 재점화 돌파, 거래량 급증, 거래정지 의심, 차입 가용 급감."""
    out = []
    sess, now = session_now()
    if len(df) == 0: return out
    last = float(df.close.iloc[-1])
    rl = meta.get("reignite") if meta else None
    if rl and last > rl and (prev_state.get("last") is None or prev_state.get("last") <= rl or not prev_state.get("above_rl")):
        out.append(("reignite", f"재점화 레벨 ${rl:.3f} 돌파 (현재 ${last:.3f})"))
    d = df[df["ts"].dt.date == df["ts"].dt.date.max()]
    if len(d) > 30:
        v5 = d.volume.tail(5).sum(); base = d.volume.iloc[:-5].median() * 5
        if base > 0 and v5 > 5 * base:
            out.append(("volume", f"5분 거래량 {v5 / 1e3:,.0f}k (당일 평균 {v5 / base:.1f}배)"))
        if len(d) > 5:
            c5 = d.close.tail(6)
            ch = (c5.iloc[-1] / c5.iloc[0] - 1) * 100
            if abs(ch) >= 10: out.append(("move", f"5분 {ch:+.1f}% 급변"))
    age_min = (now - df["ts"].iloc[-1]).total_seconds() / 60
    if sess == "regular" and 5 <= age_min < 120 and f.get("dollar_vol20", 0) > 2e5:
        out.append(("halt", f"{age_min:.0f}분째 체결 없음 — 거래정지(LULD/뉴스) 의심 (무료데이터 지연일 수도 있음)"))
    if f.get("avail") is not None and prev_state.get("avail") and f["avail"] < prev_state["avail"] * 0.5:
        out.append(("borrow", f"빌릴 수 있는 주식 {prev_state['avail']:,.0f} → {f['avail']:,.0f}주 급감"))
    return out

def snapshot(ticker, p, refresh_borrow=True):
    """상세 화면용 전체 계산 (라이브 반영)."""
    ticker = ticker.upper()
    info = src.fetch_info(ticker)
    if refresh_borrow:
        last_b = db.kv_get(f"borrow_try:{ticker}", 300)
        if last_b is None:
            src.fetch_borrow(ticker); db.kv_set(f"borrow_try:{ticker}", 1)
    reg = db.kv_get("regime_cache", 3600)
    regime = model.regime_series()
    b = model.Bundle(ticker, regime)
    df = intraday(ticker)
    tb = today_bar(df)
    live_used = False
    if tb is not None and len(b.px) and tb["date"] > b.px["date"].iloc[-1]:
        b.px = pd.concat([b.px, pd.DataFrame([{"ticker": ticker, **tb}])], ignore_index=True); live_used = True
    elif tb is not None and len(b.px) and tb["date"] == b.px["date"].iloc[-1] and session_now()[0] == "regular":
        i = b.px.index[-1]   # 장중에만 1분봉으로 갱신 (마감 후엔 공식 일봉 종가 우선)
        b.px.loc[i, "high"] = max(float(b.px.loc[i, "high"]), tb["high"]); b.px.loc[i, "low"] = min(float(b.px.loc[i, "low"]), tb["low"])
        b.px.loc[i, "close"] = tb["close"]; b.px.loc[i, "volume"] = max(float(b.px.loc[i, "volume"]), tb["volume"])
        live_used = True
    if len(b.px) < 25: return None
    asof = b.px["date"].iloc[-1]
    f = model.features(b, asof, p)
    if f is None: return None
    eh = ext_hours(df)
    if eh.get("last"): f["live_price"] = eh["last"]
    if session_now()[0] != "closed": f["_live"] = True
    hot = {r.get("industry") for r in (db.kv_get("hot_industries") or [])} if db.kv_get("hot_industries") else None
    f.update(model.live_feats(info or {}, df, hot))
    oc = src.options_calls(ticker)
    if oc is not None: f["call_vol_oi"] = oc
    s = model.score(f, p)
    prob = model.probability(s["score"], p, s=s)
    meta = f.get("_meta", {}); bands = f.get("_bands")
    stk = f"live_state:{ticker}"
    prev = db.kv_get(stk) or {}
    trig = triggers(ticker, df, f, meta, prev)
    db.kv_set(stk, {"last": eh.get("last"), "above_rl": bool(meta and eh.get("last") and eh["last"] > meta.get("reignite", 1e9)),
                    "avail": f.get("avail"), "score": s["score"]})
    now_k = dt.datetime.now(KST).strftime("%H:%M:%S")
    for kind, msg in trig:   # 라이브 이벤트 로그에 누적 (같은 종류는 15분에 1번)
        last = db.q("SELECT ts FROM scans WHERE kind=? AND ticker=? ORDER BY rowid DESC LIMIT 1", (f"live_{kind}", ticker))
        if len(last) and time.time() - float(json.loads(db.q("SELECT data FROM scans WHERE kind=? AND ticker=? ORDER BY rowid DESC LIMIT 1", (f"live_{kind}", ticker))["data"].iloc[0]).get("t", 0)) < 900:
            continue
        db.exec_("INSERT INTO scans(ts,kind,ticker,data) VALUES(?,?,?,?)", (db.now_kst(), f"live_{kind}", ticker, json.dumps({"msg": msg, "t": time.time()})))
    live_log = db.q("SELECT ts, kind, data FROM scans WHERE ticker=? AND kind LIKE 'live_%' ORDER BY rowid DESC LIMIT 8", (ticker,))
    sess, _ = session_now()
    dil = model.dilution(b)
    summary = model.plain_summary(f)
    bz = model.buy_zone(f, meta, p)
    try:
        bp = buyprice.recommend(b.px[b.px["date"] <= asof], b.sv, f["price"], (bz or {}).get("stop"), p,
                                alert=bool(s.get("flagged")), ivwap=intraday_vwap(df))
    except Exception:
        bp = None
    try:
        dd = df[df["ts"].dt.date == df["ts"].dt.date.max()] if len(df) else df
        v5 = float(dd["volume"].tail(5).sum()) if len(dd) else None
    except Exception:
        v5 = None
    return {"ticker": ticker, "ivwap": intraday_vwap(df), "v5": v5, "summary": summary, "info": info, "b": b, "f": f, "s": s, "prob": prob, "meta": meta, "bands": bands, "eh": eh,
            "triggers": trig, "live_log": live_log, "session": sess, "updated_kst": now_k, "live_used": live_used,
            "last_bar_kst": eh["last_ts"].astimezone(KST).strftime("%m/%d %H:%M") if eh.get("last_ts") is not None else None,
            "dil": dil, "delist": model.delisting(b.px), "liq": model.liquidity(f, info),
            "bz": bz, "bp": bp, "events": model.event_log(b, f, meta)}
