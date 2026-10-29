"""🔮 조짐 보이는 종목: 🧬 성공 패턴(6가지) 3개 이상 또는 💣 희석·상폐 구조 신호(7가지) 2개 이상인 종목을 따로 모아 보여줌.
둘 다 과거 검증에서 '5일 안 +30% 터치'는 잦지만 5일 뒤 종가·앱 성공 기준은 좋지 않아 점수 미반영(참고)."""
import datetime as dt
import numpy as np, pandas as pd
from . import db, pattern as PT, structure as ST

def _one(t, mcap=None, since=None):
    px = db.q("SELECT date, open, high, low, close, volume FROM prices WHERE ticker=? AND date>=? ORDER BY date", (t, since))
    if len(px) < 15: return None
    px["date"] = pd.to_datetime(px["date"])
    fil = db.q("SELECT form, filed, items FROM filings WHERE ticker=?", (t,))
    facts = db.kv_get(f"facts:{t}") or {}
    pm = PT.match(px, None, None, fil, mcap=mcap or None)
    sm = ST.compute(px, fil, facts)
    if not pm and not sm: return None
    pn = pm["n"] if pm else 0; sn = sm["n"] if sm else 0
    return dict(ticker=t, price=float(px.close.iloc[-1]), chg1=float(px.close.iloc[-1] / px.close.iloc[-2] - 1), asof=str(px.date.iloc[-1].date()),
                pm=pm, sm=sm, pat_n=pn, st_n=sn, total=(pn if pn >= 3 else 0) + sn, keep=pn >= 3 or sn >= 2)

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
