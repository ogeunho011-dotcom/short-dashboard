"""🔮 조짐 보이는 종목: 🧬 성공 패턴(6가지) 3개 이상 또는 💣 희석·상폐 구조 신호(7가지) 2개 이상
(또는 🏦 자금줄·세력 구조 신호 5개 이상)인 종목을 따로 모아 보여줌.
둘 다 과거 검증에서 '5일 안 +30% 터치'는 잦지만 5일 뒤 종가·앱 성공 기준은 좋지 않아 점수 미반영(참고)."""
import datetime as dt
import numpy as np, pandas as pd
from . import db, pattern as PT, structure as ST, finance as FZ, events as EV

def _one(t, mcap=None, since=None):
    px = db.q("SELECT date, open, high, low, close, volume FROM prices WHERE ticker=? AND date>=? ORDER BY date", (t, since))
    if len(px) < 15: return None
    px["date"] = pd.to_datetime(px["date"])
    fil = db.q("SELECT form, filed, items FROM filings WHERE ticker=?", (t,))
    facts = db.kv_get(f"facts:{t}") or {}
    pm = PT.match(px, None, None, fil, mcap=mcap or None)
    try: lt, ew = EV.for_ticker(t, px)          # 캐시된 최신 공시 해석만 (원문은 매일 작업에서 받음)
    except Exception: lt, ew = None, []
    sm = ST.compute(px, fil, facts, mcap=mcap or None, latest=lt)
    try: fz = FZ.compute(t, px, db.kv_get(f"info:{t}") or {}, facts)
    except Exception: fz = None
    if not pm and not sm and not fz and not ew: return None
    pn = pm["n"] if pm else 0; sn = sm["n"] if sm else 0; fn = fz["n"] if fz else 0
    wn = sum(1 for w in ew if w.get("scored"))     # 과거 검증에서 근거가 성립한 경고만 개수에 더함
    return dict(ticker=t, price=float(px.close.iloc[-1]), chg1=float(px.close.iloc[-1] / px.close.iloc[-2] - 1), asof=str(px.date.iloc[-1].date()),
                pm=pm, sm=sm, fz=fz, ew=ew, pat_n=pn, st_n=sn, fz_n=fn, ew_n=wn,
                total=(pn if pn >= 3 else 0) + sn + (fn if fn >= 5 else 0) + wn, keep=pn >= 3 or sn >= 2 or fn >= 5 or wn >= 1)

def build(df):
    """df: 최근 스캔 결과(ticker, mcap ...). 반환: 조짐 종목 리스트(신호 많은 순)."""
    if df is None or not len(df): return []
    since = (dt.date.today() - dt.timedelta(days=420)).isoformat()
    out = []
    mc = df.set_index("ticker")["mcap"].to_dict() if "mcap" in df else {}
    for t in df.ticker.unique():
        try: r = _one(t, mc.get(t), since)
        except Exception: r = None
        if r and r["keep"]: out.append(r)
    out.sort(key=lambda r: (r["total"], r["pat_n"], -r["price"]), reverse=True)
    return out

def signs_list(r):
    """[(아이콘, 이름, 값)] — 켜진 것만."""
    L = []
    if r["pm"]:
        for it in r["pm"]["hits"]:
            if it["on"]: L.append(("🧬", it["label"], it["val"]))
    if r["sm"]:
        vals = ST.values(r["sm"])
        for k, lab in ST.SIGNS:
            if r["sm"]["signs"].get(k): L.append(("💣", lab, vals.get(k) or "데이터 없음"))
    if r.get("fz"):
        vals = FZ.values(r["fz"])
        for k, lab in FZ.SIGNS:
            if r["fz"]["signs"].get(k): L.append(("🏦", lab, vals.get(k) or "데이터 없음"))
    for w in r.get("ew") or []:
        L.append(("⚠️", EV.KIND_KO.get(w["kind"], w["kind"]) + (" [점수 반영]" if w.get("scored") else " [참고]"), w["text"]))
    return L

def missing(r):
    """데이터 없음인 구조 신호 이름."""
    if not r["sm"]: return [lab for _, lab in ST.SIGNS]
    return [lab for k, lab in ST.SIGNS if r["sm"]["signs"].get(k) is None]

def copy_text(r, link=""):
    L = [f"🔮 {r['ticker']} 조짐 {r['total']}개 (참고, 점수 미반영) · ${r['price']:.4g} ({r['chg1'] * 100:+.1f}%) · {r['asof']} 종가"]
    for ic, lab, val in signs_list(r): L.append(f"{ic} {lab}: {val}")
    ms = missing(r)
    if ms: L.append("데이터 없음: " + ", ".join(ms))
    L.append("과거 검증: +30% 짧게 튀는 일은 잦지만 5일 뒤 종가는 보통 하락 → 터지면 짧게 익절")
    if link: L.append(f"🔗 {link}")
    L.append("※ 숏 레이더 추정치 · 투자 권유 아님")
    return "\n".join(L)

def build_full(tickers=None, mcap=None, days_fresh=6):
    """유니버스 전체(가격이 있는 모든 종목)로 조짐 계산 → kv 'omen_full' 에 저장 (매일 업데이트에서 1회, 앱은 읽기만).
    종목별 DB 조회 2번 + 패턴·구조 계산이라 수천 종목도 몇 분 안. 반환: (조짐 종목 수, 검사 종목 수)."""
    import time as _t
    t0 = _t.time()
    since = (dt.date.today() - dt.timedelta(days=420)).isoformat()
    L = db.q("SELECT ticker, MAX(date) d, COUNT(*) n FROM prices GROUP BY ticker")
    if not len(L): return 0, 0
    top = pd.Timestamp(L.d.max())
    L = L[(pd.to_datetime(L.d) >= top - pd.Timedelta(days=days_fresh)) & (L.n >= 15)]
    tk = [t for t in L.ticker if tickers is None or t in set(tickers)]
    if mcap is None:
        u = db.q("SELECT ticker, mcap FROM universe"); mcap = dict(zip(u.ticker, u.mcap))
    out = []
    for t in tk:
        try: r = _one(t, mcap.get(t) or None, since)
        except Exception: r = None
        if r and r["keep"]: out.append(r)
    out.sort(key=lambda r: (r["total"], r["pat_n"], -r["price"]), reverse=True)
    meta = dict(ts=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), checked=len(tk), n=len(out), secs=round(_t.time() - t0))
    db.kv_set("omen_full", {"meta": meta, "rows": out})
    return len(out), len(tk)

def load_full(max_age_h=60):
    """매일 업데이트가 저장한 전체 유니버스 조짐 목록 (없거나 오래되면 None)."""
    return db.kv_get("omen_full", max_age_h * 3600)
