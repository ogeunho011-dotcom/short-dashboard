"""💣 희석·상폐 구조 (참고 표시 전용 — 검증 결과에 따라 점수 반영 여부 결정, model/structure_study.json).
커뮤니티 글(SURG '알 한쪽 걸기', 급등 전 작성) 방식을 무료 데이터로 자동화:
  전환사채 ÷ 시총(오버행) · 공시 간 주식수 증가 · 현금 런웨이 · $0.10(10일 연속 → 상폐 결정) 거리 ·
  베이비 셸프 한도(유통 시총의 1/3) · 다음 10-Q 마감 창 · 호재 공시 반응 약화(PR-fade).
모든 값은 asof 날짜 '이전'에 접수된 공시(filed < asof)와 asof 종가까지만 사용 → 룩어헤드 없음.
없는 값은 None → 화면에 '데이터 없음'."""
import json, functools
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SIGNS = [("overhang", "전환사채 ≥ 시총 50%"), ("shgrow", "공시 간 주식수 +50%↑"), ("runway", "현금 런웨이 6개월 미만"),
         ("near10", "$0.10 상폐선 +50% 이내"), ("baby", "베이비 셸프 한도 < 1년 현금소모"), ("qwin", "10-Q 마감 창 (D-14~D+5)"),
         ("prfade", "호재 공시 반응 약화")]
SIGN_KO = dict(SIGNS)
DUE = [(5, 15), (8, 14), (11, 14), (3, 31)]          # 소형 보고기업 10-Q/10-K 마감 (분기말 +45일, 연말 +90일)

@functools.lru_cache(maxsize=1)
def study():
    try: return json.loads((ROOT / "model/structure_study.json").read_text())
    except Exception: return {}

def _step(dates, filed, vals):
    """filed < date 인 값 중 가장 최근 접수분 (계단 함수). dates·filed: datetime64 정렬 배열."""
    if not len(filed): return np.full(len(dates), np.nan)
    o = np.argsort(filed, kind="stable"); f, v = filed[o], vals[o]
    i = np.searchsorted(f, dates, side="left") - 1
    out = np.where(i >= 0, v[np.clip(i, 0, None)], np.nan)
    return out.astype(float)

def _series(facts, key, maxage=400):
    """facts[key] → (filed, end, start, val) DataFrame."""
    x = pd.DataFrame([r for r in (facts or {}).get(key, []) if r.get("filed") and r.get("val") is not None and r.get("end")])
    if not len(x): return x
    x["filed"] = pd.to_datetime(x["filed"]); x["end"] = pd.to_datetime(x["end"])
    if "start" in x: x["start"] = pd.to_datetime(x["start"], errors="coerce")
    return x.sort_values(["filed", "end"])

def _latest_by_filed(x, dates, value_fn, maxage=400):
    """각 공시 접수 시점에 '알려진 최신 값'(가장 늦은 end, 같은 end 는 합계/최근)을 만들고 계단 함수로."""
    if not len(x): return np.full(len(dates), np.nan)
    fl = np.array(sorted(x["filed"].unique()))
    vals, ends = [], []
    for f in fl:
        k = x[x["filed"] <= f]
        e = k["end"].max(); ends.append(e); vals.append(value_fn(k, e))
    v = _step(dates, fl.astype("datetime64[ns]"), np.array(vals, float))
    e = _step(dates, fl.astype("datetime64[ns]"), np.array([pd.Timestamp(t).value for t in ends], float))
    age = (dates.astype("int64") - e) / 864e11
    return np.where(age <= maxage, v, np.nan)

def months(start, end):
    """기간 개월 수 (181일 → 6개월처럼 분기·반기·연 단위로 반올림, 애매하면 일수/30.44)."""
    m = (pd.Timestamp(end) - pd.Timestamp(start)).days / 30.44
    return max(round(m) if abs(m - round(m)) < 0.25 else m, 1)

def next_due(d):
    d = pd.Timestamp(d); c = []
    for y in (d.year, d.year + 1):
        for m, dd in DUE: c.append(pd.Timestamp(y, m, dd))
    c.sort()
    for x in c:
        if x + pd.Timedelta(days=5) >= d: return x      # NT 10-Q 5일 연장까지 창으로 봄
    return c[-1]

def daily_frame(px, fil=None, facts=None):
    """px: 일봉(date, open, high, low, close, volume) 정렬. 날짜별 구조 지표(DataFrame, index=date)."""
    px = px.sort_values("date").reset_index(drop=True)
    d = pd.to_datetime(px["date"]).values.astype("datetime64[ns]")
    c = px["close"].astype(float).values
    F = pd.DataFrame(index=pd.DatetimeIndex(d)); F["price"] = c
    sh = _series(facts, "shares"); cv = _series(facts, "convertible"); ca = _series(facts, "cash"); op = _series(facts, "opcf")
    F["shares"] = _latest_by_filed(sh, d, lambda k, e: float(k[k["end"] == e]["val"].iloc[-1]))
    def _old(k, e):     # 최신 end 보다 90~240일 이전 시점 주식수 (가장 오래된 쪽)
        o = k[(k["end"] <= e - pd.Timedelta(days=90)) & (k["end"] >= e - pd.Timedelta(days=240))]
        return float(o.sort_values("end")["val"].iloc[0]) if len(o) else np.nan
    F["shares_old"] = _latest_by_filed(sh, d, _old)
    F["conv"] = _latest_by_filed(cv, d, lambda k, e: float(k[k["end"] == e].drop_duplicates("val")["val"].sum()))
    F["cash"] = _latest_by_filed(ca, d, lambda k, e: float(k[k["end"] == e]["val"].iloc[-1]))
    def _burn(k, e):
        q = k[(k["end"] == e) & k["start"].notna()]
        if not len(q): return np.nan
        r = q.iloc[-1]; mo = months(r["start"], r["end"])
        return -float(r["val"]) / mo
    F["burn_m"] = _latest_by_filed(op, d, _burn) if len(op) and "start" in op else np.nan
    F["mcap"] = F["shares"] * F["price"]
    F["overhang"] = F["conv"] / F["mcap"]
    F["shgrow"] = F["shares"] / F["shares_old"] - 1
    F["runway_m"] = np.where(F["burn_m"] > 0, F["cash"] / F["burn_m"], np.nan)
    F["dist10"] = 0.10 / F["price"] - 1
    le = (pd.Series(c) <= 0.10).astype(int)
    F["n_le10"] = le.rolling(10, min_periods=1).sum().values
    F["baby_cap"] = np.where(F["mcap"] < 75e6, F["mcap"] / 3, np.nan)
    F["dd_due"] = [(next_due(x) - pd.Timestamp(x)).days for x in d]
    # 호재성 공시(8-K 7.01/8.01) 다음 거래일까지 반응: 공시일 이후 첫 거래일 t, max(t, t+1 종가) / t-1 종가
    F["pr_n"] = 0; F["pr_first"] = np.nan; F["pr_last"] = np.nan; F["pr_max_prev"] = np.nan
    if fil is not None and len(fil):
        g = fil[(fil["form"].astype(str) == "8-K") & fil["items"].astype(str).str.contains(r"7\.01|8\.01", na=False)].copy()
        g["filed"] = pd.to_datetime(g["filed"])
        ev = []
        for fd in sorted(g["filed"].unique()):
            t = np.searchsorted(d, np.datetime64(fd, "ns"), side="left")
            if t < 1 or t + 1 >= len(d): continue
            r = max(c[t], c[t + 1]) / c[t - 1] - 1
            ev.append((d[t + 1], np.datetime64(fd, "ns"), r))     # t+1 종가 확정 뒤부터 알 수 있음
        if ev:
            kn = np.array([e[0] for e in ev]); fdv = np.array([e[1] for e in ev]); rr = np.array([e[2] for e in ev])
            n, f1, l1, mp = [], [], [], []
            for x in d:
                m = (kn < x) & (fdv >= x - np.timedelta64(150, "D"))
                z = rr[m]
                n.append(len(z)); f1.append(z[0] if len(z) else np.nan); l1.append(z[-1] if len(z) else np.nan)
                mp.append(z[:-1].max() if len(z) > 1 else np.nan)
            F["pr_n"], F["pr_first"], F["pr_last"], F["pr_max_prev"] = n, f1, l1, mp
    return F

def signs_from_row(r):
    """한 날짜 행 → {sign_key: bool or None(데이터 없음)}."""
    nn = lambda v: v is not None and not (isinstance(v, float) and np.isnan(v))
    s = {}
    s["overhang"] = (r["overhang"] >= 0.5) if nn(r.get("overhang")) else None
    s["shgrow"] = (r["shgrow"] >= 0.5) if nn(r.get("shgrow")) else None
    s["runway"] = (r["runway_m"] < 6) if nn(r.get("runway_m")) else None
    s["near10"] = bool(nn(r.get("price")) and r["price"] <= 0.15)
    b = r.get("baby_cap"); bm = r.get("burn_m")
    s["baby"] = (b < bm * 12) if nn(b) and nn(bm) and bm > 0 else (False if nn(b) or nn(r.get("mcap")) else None)
    s["qwin"] = (-5 <= r["dd_due"] <= 14) if nn(r.get("dd_due")) else None
    s["prfade"] = bool(r.get("pr_n", 0) >= 3 and nn(r.get("pr_last")) and nn(r.get("pr_max_prev")) and r["pr_last"] < r["pr_max_prev"] * 0.5)
    return s

def _apply_latest(r, sg, lt, facts, asof, price):
    """companyfacts 보다 새 공시 값(events.latest)이 있으면 현금·월 소모·주식 수를 덮어씀. 출처·기준일을 r 에 남김."""
    nn = lambda v: v is not None and not (isinstance(v, float) and np.isnan(v))
    def fend(key):
        x = _series(facts, key)
        x = x[x["filed"] < asof] if len(x) else x
        return x["end"].max() if len(x) else None
    fe = fend("cash"); r["cash_end"] = str(fe.date()) if fe is not None and nn(r.get("cash")) else None; r["cash_src"] = "XBRL"
    c = lt.get("cash")
    if c and (fe is None or pd.Timestamp(c[0]) > fe):
        r["cash"], r["cash_end"], r["cash_src"] = float(c[1]), c[0], c[2]
    oe = fend("opcf"); r["burn_end"] = str(oe.date()) if oe is not None and nn(r.get("burn_m")) else None; r["burn_src"] = "XBRL"
    o = lt.get("opcf")
    if o and (oe is None or pd.Timestamp(o[1]) > oe):
        mo = months(o[0], o[1])
        r["burn_m"], r["burn_end"], r["burn_src"], r["burn_period"] = -float(o[2]) / mo, o[1], o[3], f"{o[0]}~{o[1]}"
    if nn(r.get("cash")) and nn(r.get("burn_m")):
        r["runway_m"] = r["cash"] / r["burn_m"] if r["burn_m"] > 0 else np.nan
        sg["runway"] = bool(r["runway_m"] < 6) if nn(r["runway_m"]) else False   # 소모 없음(현금 유입) → 런웨이 문제 아님
    sh = lt.get("shares")
    if sh and price and pd.Timestamp(sh["date"]) >= asof - pd.Timedelta(days=45):
        r["shares_pre"] = r.get("shares"); r["shares_pre_src"] = r.get("shares_src")
        r["shares"] = float(sh["n"]); r["shares_src"] = "공시"; r["shares_note"] = sh
        r["mcap"] = r["shares"] * price
        if nn(r.get("conv")): r["overhang"] = r["conv"] / r["mcap"]
        sg["overhang"] = (r["overhang"] >= 0.5) if nn(r.get("overhang")) else None
        r["baby_cap"] = r["mcap"] / 3 if r["mcap"] < 75e6 else None
        if nn(r.get("shares_old")) and r["shares_old"] > 0:
            r["shgrow"] = r["shares"] / r["shares_old"] - 1; sg["shgrow"] = bool(r["shgrow"] >= 0.5)

def compute(px, fil=None, facts=None, info=None, mcap=None, latest=None):
    """상세 카드·스캔용 최신 상태. 반환 dict 또는 None.
    mcap: 현재 시총(스캔·시세). XBRL 주식수는 마지막 10-Q 기준이라 그 뒤 증자·전환이 빠짐 →
    현재 시총/시세 주식수가 있으면 최신 값(시총·전환사채 비율·베이비 셸프 한도)은 그걸로 계산.
    latest: core.events.latest() — companyfacts 보다 새 공시(6-K/10-Q XBRL 인스턴스, 13D·신고서 주식 수, 그 뒤 발행)."""
    if px is None or len(px) < 15: return None
    try: F = daily_frame(px.tail(260), fil, facts)
    except Exception: return None
    r = F.iloc[-1].to_dict(); sg = signs_from_row(r)
    info = info or {}
    nn = lambda v: v is not None and not (isinstance(v, float) and np.isnan(v))
    price = r.get("price")
    cur = None
    for k in ("sharesOutstanding", "impliedSharesOutstanding"):
        v = info.get(k)
        if v and float(v) > 0: cur = float(v); break
    if cur is None and price:
        m = mcap if mcap else info.get("marketCap")
        if m and float(m) > 0: cur = float(m) / price
    r["shares_xbrl"] = r.get("shares"); r["shares_src"] = "XBRL"
    if cur and price and (not nn(r.get("shares")) or cur > r["shares"] * 1.05):
        r["shares"] = cur; r["mcap"] = cur * price; r["shares_src"] = "시세"
        if nn(r.get("conv")): r["overhang"] = r["conv"] / r["mcap"]
        r["baby_cap"] = r["mcap"] / 3 if r["mcap"] < 75e6 else None
        sg["overhang"] = (r["overhang"] >= 0.5) if nn(r.get("overhang")) else None
        if nn(r.get("shares_old")) and r["shares_old"] > 0:      # 10-Q 이후 증자분까지 반영한 주식수 증가
            r["shgrow"] = cur / r["shares_old"] - 1; sg["shgrow"] = bool(r["shgrow"] >= 0.5)
    if latest:
        try: _apply_latest(r, sg, latest, facts, F.index[-1], price)
        except Exception: pass
    # 유통주식(info) 이 있으면 베이비 셸프 한도는 유통 시총 기준 (발행주식보다 클 수 없음)
    fs = info.get("floatShares")
    if fs and price:
        fsv = min(float(fs), r["shares"]) if nn(r.get("shares")) else float(fs)
        fu = fsv * price; r["float_usd"] = fu
        r["baby_cap"] = fu / 3 if fu < 75e6 else None
    bm = r.get("burn_m"); b = r.get("baby_cap")
    if nn(b) and nn(bm) and bm > 0: sg["baby"] = bool(b < bm * 12)
    elif nn(r.get("mcap")) and r["mcap"] >= 75e6: sg["baby"] = False
    due = next_due(F.index[-1])
    pr = []
    if fil is not None and len(fil):
        g = fil[(fil["form"].astype(str) == "8-K") & fil["items"].astype(str).str.contains(r"7\.01|8\.01", na=False)]
        d = F.index.values; c = F["price"].values
        for fd in sorted(pd.to_datetime(g["filed"]).unique())[-6:]:
            t = np.searchsorted(d, np.datetime64(fd, "ns"), side="left")
            if 1 <= t < len(d) - 1: pr.append((str(pd.Timestamp(fd).date()), round((max(c[t], c[t + 1]) / c[t - 1] - 1) * 100, 1)))
    on = [k for k, _ in SIGNS if sg.get(k)]
    return dict(v=r, signs=sg, on=on, n=len(on), m=len(SIGNS), due=str(due.date()), pr=pr, asof=str(F.index[-1].date()))

def fmt(v, kind):
    if v is None or (isinstance(v, float) and np.isnan(v)): return "데이터 없음"
    if kind == "x": return f"{v:.2f}배"
    if kind == "pct": return f"{v * 100:+.0f}%"
    if kind == "m": return f"{v:.1f}개월"
    if kind == "usd": return f"${v / 1e6:.2f}M"
    return str(v)

def _sh(v):
    return "데이터 없음" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v / 1e6:.1f}M주"

def _asof(v, k):
    e = v.get(f"{k}_end")
    if not e: return ""
    src = v.get(f"{k}_src") or "XBRL"
    return f"({e} 기준{', ' + src if src != 'XBRL' else ''})"

def _sh_note(v):
    n = v.get("shares_note") or {}
    adds = " + ".join(f"{a[0][5:]} {a[2]} {a[1] / 1e6:.1f}M" for a in n.get("adds") or [])
    src = f"{n.get('src')} {n.get('date')} {n.get('base', 0) / 1e6:.2f}M" + (f" + {adds}" if adds else "")
    pre = f" (시세 {_sh(v.get('shares_pre'))})" if v.get("shares_pre_src") == "시세" else ""
    return f"주식수 {_sh(v.get('shares_old'))}(XBRL) → 10-Q {_sh(v.get('shares_xbrl'))} → 현재 약 {_sh(v.get('shares'))}(공시: {src}){pre} ({fmt(v.get('shgrow'), 'pct')})"

def values(st):
    """사람이 읽는 핵심 숫자 (키 → 문자열)."""
    v = st["v"]
    pr = " → ".join(f"{p[1]:+.0f}%" for p in st.get("pr") or []) or "데이터 없음"
    return {"overhang": f"전환사채 {fmt(v.get('conv'), 'usd')} ÷ 시총 {fmt(v.get('mcap'), 'usd')} = {fmt(v.get('overhang'), 'x')}",
            "shgrow": (_sh_note(v) if v.get('shares_src') == '공시' else
                       f"주식수 {_sh(v.get('shares_old'))}(XBRL) → 10-Q {_sh(v.get('shares_xbrl'))} → 현재 약 {_sh(v.get('shares'))}(시세) ({fmt(v.get('shgrow'), 'pct')})" if v.get('shares_src') == '시세'
                       else f"주식수 {_sh(v.get('shares_old'))} → {_sh(v.get('shares'))} ({fmt(v.get('shgrow'), 'pct')})"),
            "runway": f"현금 {fmt(v.get('cash'), 'usd')}{_asof(v, 'cash')} · 월 소모 {fmt(v.get('burn_m'), 'usd')}{_asof(v, 'burn')} → {fmt(v.get('runway_m'), 'm')}",
            "near10": f"$0.10까지 {fmt(v.get('dist10'), 'pct')} · 최근 10일 중 $0.10 이하 종가 {int(v.get('n_le10') or 0)}일 (10일 연속이면 상폐 결정)",
            "baby": f"베이비 셸프 한도({'유통 시총' if v.get('float_usd') else '시총'} 1/3) {fmt(v.get('baby_cap'), 'usd')} vs 1년 소모 {fmt((v.get('burn_m') or np.nan) * 12, 'usd')}",
            "qwin": f"다음 10-Q/10-K 마감 {st['due']} (D{-int(v['dd_due']):+d})" if v.get("dd_due") is not None else "데이터 없음",
            "prfade": f"최근 호재 공시 반응(8-K 7.01/8.01): {pr}"}

def line(st):
    if not st: return None
    on = [SIGN_KO[k] for k in st["on"]]
    return f"💣 희석·상폐 구조 {st['n']}/{st['m']} (참고, 점수 미반영)" + (f": {', '.join(on)}" if on else "")
