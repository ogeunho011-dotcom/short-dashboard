"""상세 화면 '레벨 맵' · '가격대별 숏 진입 구간(추정)' · '대차비용 변화' · '이벤트 로그' · '숏 커버 경보 레벨' 계산 (순수 함수).

원칙: 실제 숫자(일봉 고/저가, 프리·애프터 고/저가, 이동평균, 갭, SEC 공모가·워런트 행사가, FINRA 공매도 거래량, IBKR 대차)만 씀.
없는 데이터는 None → 화면에 '데이터 없음'. 진입 구간은 일별 공매도 거래량 × 그날 평균가 근사라 '추정'."""
import math, datetime as dt
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd

ET, KST = ZoneInfo("America/New_York"), ZoneInfo("Asia/Seoul")

def _d(x):
    return pd.Timestamp(x).strftime("%m/%d")

def fp(v):
    if v is None: return "데이터 없음"
    v = float(v)
    return f"${v:,.0f}" if v >= 1000 else f"${v:.2f}" if v >= 1 else f"${v:.4f}".rstrip("0").rstrip(".") if v < 0.1 else f"${v:.3f}"

def pct(a, b):
    return (a / b - 1) * 100 if a and b else None

# ---------------------------------------------------------------- 후보 가격 수집
def candidates(px, eh=None, refs=None, price=None, lookback=20):
    """(가격, 설명, 종류, 중요도) 목록."""
    C = []
    if px is None or not len(px): return C
    d = px.sort_values("date").reset_index(drop=True)
    c = d["close"].astype(float)
    for n in (5, 10, 20, 60, 120):
        if len(c) >= n:
            C.append((float(c.tail(n).mean()), f"{n}일선 {fp(c.tail(n).mean())}", "ma", 2 if n >= 60 else 1))
    t = d.tail(lookback)
    for i, r in t.tail(5).iterrows():   # 최근 5거래일 고·저가
        C.append((float(r.high), f"{_d(r.date)} 정규장 고가 {fp(r.high)}", "hi", 2))
        C.append((float(r.low), f"{_d(r.date)} 저가 {fp(r.low)}", "lo", 1))
    if len(t) >= 6:
        h = t.iloc[:-5]
        ih = h["high"].astype(float).idxmax(); il = h["low"].astype(float).idxmin()
        C.append((float(d.loc[ih, "high"]), f"{_d(d.loc[ih, 'date'])} 고점 {fp(d.loc[ih, 'high'])} (최근 {lookback}일)", "hi", 2))
        C.append((float(d.loc[il, "low"]), f"{_d(d.loc[il, 'date'])} 저점 {fp(d.loc[il, 'low'])} (최근 {lookback}일)", "lo", 2))
    if len(d) >= 60:
        w = d.tail(60); ih = w["high"].astype(float).idxmax()
        C.append((float(d.loc[ih, "high"]), f"{_d(d.loc[ih, 'date'])} 60일 최고가 {fp(d.loc[ih, 'high'])}", "hi", 3))
    # 메우지 않은 갭 (최근 lookback 일)
    for i in range(max(1, len(d) - lookback), len(d)):
        ph, pl, lo, hi = float(d.high[i - 1]), float(d.low[i - 1]), float(d.low[i]), float(d.high[i])
        after = d.iloc[i + 1:]
        if lo > ph * 1.02 and (not len(after) or float(after["low"].min()) > ph):
            C.append((ph, f"{_d(d.date[i])} 상승 갭 하단 {fp(ph)} (아직 안 메움)", "gap", 2))
        if hi < pl * 0.98 and (not len(after) or float(after["high"].max()) < pl):
            C.append((pl, f"{_d(d.date[i])} 하락 갭 상단 {fp(pl)} (아직 안 메움)", "gap", 2))
    if eh:
        day = eh.get("day"); dd = pd.Timestamp(day).strftime("%m/%d") if day else ""
        for s, ko in (("pre", "프리장"), ("post", "애프터")):
            x = eh.get(s) or {}
            if x.get("hi"): C.append((float(x["hi"]), f"{dd} {ko} 고가 {fp(x['hi'])}", "eh", 2))
            if x.get("lo") and s == "post": C.append((float(x["lo"]), f"{dd} {ko} 저가 {fp(x['lo'])}", "eh", 1))
        rg = eh.get("regular") or {}
        if rg.get("hi") and day and len(d) and str(pd.Timestamp(d.date.iloc[-1]).date()) != day:
            C.append((float(rg["hi"]), f"{dd} 정규장 고가 {fp(rg['hi'])}", "hi", 2))
    for v, why in (refs or []):
        if v: C.append((float(v), why, "sec", 3))
    if price:
        C = [x for x in C if 0.3 * price <= x[0] <= 3.0 * price]
    return C

def cluster(C, tol):
    """가까운 가격(tol 비율 이내)을 한 구간으로."""
    C = sorted(C, key=lambda x: x[0]); out = []
    for x in C:
        if out and x[0] <= out[-1]["hi"] * (1 + tol) and x[0] <= out[-1]["lo"] * (1 + 2.5 * tol):
            z = out[-1]; z["hi"] = max(z["hi"], x[0]); z["items"].append(x); z["w"] += x[3]
        else:
            out.append({"lo": x[0], "hi": x[0], "items": [x], "w": x[3]})
    for z in out:
        z["items"].sort(key=lambda x: -x[3]); z["mid"] = (z["lo"] + z["hi"]) / 2
    return out

def _why(z, n=2):
    seen, w = set(), []
    for it in z["items"]:
        if it[1] in seen: continue
        seen.add(it[1]); w.append(it[1])
        if len(w) >= n: break
    return " · ".join(w)

def level_map(px, eh=None, price=None, refs=None, fee=None, avail=None):
    """반환 {zones:[{key,name,lo,hi,pct_lo,pct_hi,why,tag}], summary:{res,res_pct,sup,sup_pct,rr,target,target_pct}, trigger}"""
    if px is None or len(px) < 5: return None
    price = float(price or px["close"].iloc[-1])
    atr = float((px["high"] - px["low"]).tail(14).mean() or price * 0.05)
    tol = min(max(0.012, 0.25 * atr / price), 0.04)
    C = candidates(px, eh, refs, price)
    near = 0.004
    above = cluster([x for x in C if x[0] > price * (1 + near)], tol)
    below = cluster([x for x in C if x[0] < price * (1 - near)], tol)[::-1]
    inside = cluster([x for x in C if price * (1 - near) <= x[0] <= price * (1 + near)], tol)
    zones = []
    def add(key, name, lo, hi, why, tag=None):
        zones.append(dict(key=key, name=name, lo=lo, hi=hi, pct_lo=pct(lo, price) if lo else None, pct_hi=pct(hi, price) if hi else None, why=why, tag=tag))
    a1 = above[0] if above else None
    a2 = next((z for z in above[1:] if z["w"] >= 3 and z["lo"] >= (a1["hi"] if a1 else price) * 1.03), None) or \
        next((z for z in above[1:] if z["lo"] >= (a1["hi"] if a1 else price) * 1.03), above[1] if len(above) > 1 else None)
    b1 = below[0] if below else None
    b2 = next((z for z in below[1:] if z["hi"] <= (b1["lo"] if b1 else price) * 0.985), below[1] if len(below) > 1 else None)
    b3 = next((z for z in below if b2 and z["hi"] < b2["lo"] * 0.97), None)
    tight = (avail is not None and avail <= 1e4) or (fee is not None and fee >= 50)
    if a2:
        top = max((it for z in above for it in z["items"] if it[2] in ("hi", "eh")), key=lambda it: it[0], default=None)
        extra = f" (위로 {top[1]}까지 찍은 적 있음)" if top and top[0] > a2["hi"] * 1.05 else ""
        add("top", "상단 위험 구간", a2["lo"], None, f"{_why(a2)}{extra} — 여기서는 차익 매물이 몰리기 쉬워 되돌림 위험이 큼", "과열")
    if a1:
        hi = a2["lo"] if a2 else None
        add("break", "돌파 확인 구간", a1["lo"], hi, f"{_why(a1)} 위로 올라서면" + (" 빌릴 주식이 없는 숏이 손절(커버)에 몰릴 수 있는 구간" if tight else " 추가 매수가 붙기 쉬운 구간"), "재점화")
    lo_now = b1["hi"] if b1 else None; hi_now = a1["lo"] if a1 else None
    w_now = " · ".join(filter(None, [_why(z, 1) for z in inside])) or ""
    edge = [x for x in [(f"아래 {_why(b1, 1)}" if b1 else None), (f"위 {_why(a1, 1)}" if a1 else None)] if x]
    add("now", "현재 관찰 구간", lo_now, hi_now, (w_now + " — " if w_now else "") + " / ".join(edge) + " 사이에서 방향을 정하는 중", None)
    if b1:
        lo = b1["lo"] if b1["hi"] - b1["lo"] > price * 0.01 else b1["lo"] - 0.25 * atr
        add("s1", "1차 지지", lo, b1["hi"], f"{_why(b1)} 가 모인 가격대", None)
    if b2:
        add("s2", "2차 지지", b2["lo"], b2["hi"], f"{_why(b2)} 가 모인 가격대", None)
    if b2 or b1:
        base = b2 or b1; nxt = b3
        add("down", "하방 위험 구간", None, base["lo"],
            f"{fp(base['lo'])} 아래로는 " + (f"{_why(nxt, 1)}까지 받쳐 줄 가격이 드물어 빠르게 밀릴 수 있음" if nxt else "최근 기록된 지지 가격이 없음"), "이탈")
    res = a1["lo"] if a1 else None
    sup = zones[[z["key"] for z in zones].index("s1")]["lo"] if b1 else None
    tgt = next((z["lo"] for z in above if z["lo"] >= price * 1.05), res)
    rr = (tgt - price) / (price - sup) if tgt and sup and price > sup else None
    return {"zones": zones, "price": price, "atr": atr,
            "summary": dict(res=res, res_pct=pct(res, price), res_why=_why(a1, 1) if a1 else None, sup=sup, sup_pct=pct(sup, price),
                            target=tgt, target_pct=pct(tgt, price), rr=rr),
            "trigger": (tg := _trigger(above, a1, price)),
            "next_res": _next_res(above, tg, a2)}

def _next_res(above, tg, a2):
    """트리거 다음 저항 = 트리거보다 2% 이상 위의 첫 묶음."""
    if tg:
        z = next((z for z in above if z["lo"] >= tg[0] * 1.02), None)
        if z: return (z["lo"], _why(z, 2))
        return None
    return (a2["lo"], _why(a2, 2)) if a2 else None

def _trigger(above, a1, price):
    """숏 커버 트리거 = 위쪽에서 가장 가까운 '실제 거래 가격' 레벨(당일·시간외 고가, 갭, 공모가·워런트) — 이동평균은 제외. 없으면 가장 가까운 저항."""
    for z in above:
        for it in z["items"]:
            if it[2] in ("eh", "hi", "gap", "sec") and it[0] <= price * 1.6:
                return (it[0], it[1])
    return (a1["lo"], _why(a1, 1)) if a1 else None

# ---------------------------------------------------------------- 가격대별 숏 진입 구간 (추정)
def entry_zones(px, sv, price, offer=None, days=20):
    """일별 FINRA 공매도 거래량 × 그날 평균가((고+저+종)/3) → 가까운 날끼리 가격대로 묶음."""
    if sv is None or not len(sv) or px is None or not len(px): return None
    d = px.sort_values("date").tail(days).copy(); d["date"] = pd.to_datetime(d["date"])
    s = sv.copy(); s["date"] = pd.to_datetime(s["date"])
    m = d.merge(s[["date", "short_vol", "total_vol"]], on="date", how="left")
    have = m["short_vol"].notna()
    if have.sum() < 3: return None
    m = m[have].copy()
    m["typ"] = (m["high"] + m["low"] + m["close"]) / 3
    rows = m.sort_values("typ").to_dict("records")
    bands = []
    for r in rows:
        if bands and r["typ"] <= bands[-1]["tmax"] * 1.06 and r["typ"] <= bands[-1]["days"][0]["typ"] * 1.15:
            b = bands[-1]; b["days"].append(r); b["tmax"] = r["typ"]
        else: bands.append({"days": [r], "tmax": r["typ"]})
    tot = float(m["short_vol"].sum()) or 1
    out = []
    last_date = m["date"].max()
    for b in bands:
        ds = sorted(b["days"], key=lambda r: r["date"])
        sv_ = sum(r["short_vol"] for r in ds)
        vw = sum(r["typ"] * r["short_vol"] for r in ds) / sv_ if sv_ else None
        if len(ds) == 1:
            r = ds[0]; lo, hi = (r["low"] + r["typ"]) / 2, (r["high"] + r["typ"]) / 2
        else:
            lo, hi = min(r["typ"] for r in ds), max(r["typ"] for r in ds)
        pl = (vw / price - 1) * 100 if vw else None     # 숏 입장 손익 (+ 수익)
        # 이후 그 구간 위에서 거래된 양 (커버 진행 추정)
        first = ds[0]["date"]
        later = d[d["date"] > ds[-1]["date"]]
        above_vol = float(later.loc[later["low"] > hi, "volume"].sum()) if len(later) else 0
        if pl is not None and pl <= -25 and above_vol >= 2 * sv_: tag = "커버 진행 추정"
        elif pl is not None and pl < -2:
            tag = "돌파 완료" if len(later) and float(later["close"].iloc[0]) < lo <= price and ds[-1]["date"] >= last_date - pd.Timedelta(days=7) else "숏 손실권"
        elif pl is not None and pl > 2: tag = "숏 수익권"
        else: tag = "현재가 부근"
        dd = ", ".join(_d(r["date"]) for r in ds[-4:]) + (f" 외 {len(ds) - 4}일" if len(ds) > 4 else "")
        out.append(dict(lo=lo, hi=hi, vwap=vw, pl=pl, tag=tag, share=sv_ / tot * 100, short_vol=sv_, days=dd, n=len(ds),
                        ratio=sum(r["short_vol"] for r in ds) / max(sum(r["total_vol"] or 0 for r in ds), 1) * 100))
    out.sort(key=lambda x: -x["lo"])
    loss = sum(x["share"] for x in out if x["pl"] is not None and x["pl"] < 0)
    allv = sum(r["short_vol"] for r in rows); avg = sum(r["typ"] * r["short_vol"] for r in rows) / allv if allv else None
    o = None
    if offer and offer.get("price"):
        o = dict(price=offer["price"], gain=(price / offer["price"] - 1) * 100, date=offer.get("date"), form=offer.get("form"), url=offer.get("url"))
    return {"bands": out, "loss_share": loss, "avg": avg, "avg_pl": (avg / price - 1) * 100 if avg else None, "offer": o,
            "from": str(m["date"].min().date()), "to": str(m["date"].max().date()), "n_days": int(len(m))}

# ---------------------------------------------------------------- 대차비용 변화
def borrow_table(bor, n=12):
    """bor: ts(UTC naive), available, fee → 최근 n행 (최신 위). 급변 표시."""
    if bor is None or not len(bor): return None
    b = bor.sort_values("ts").copy()
    b = b[(b["fee"].diff().fillna(1) != 0) | (b["available"].diff().fillna(1) != 0)]   # 변화 있는 행만
    rows = []
    prev = None
    for r in b.to_dict("records"):
        ts = pd.Timestamp(r["ts"]).tz_localize("UTC")
        fee, av = float(r["fee"]) if r["fee"] is not None else None, float(r["available"]) if r["available"] is not None else None
        jump = []
        if prev is not None:
            pf, pa = prev
            if fee is not None and pf is not None and (fee - pf >= 20 or (pf > 0 and fee / pf >= 1.5 and fee - pf >= 3)): jump.append("이자 급등")
            if fee is not None and pf is not None and (pf - fee >= 20 or (fee > 0 and pf / fee >= 1.5 and pf - fee >= 3)): jump.append("이자 급락")
            if av is not None and pa is not None and av <= 0 < pa: jump.append("차입 0")
            elif av is not None and pa is not None and pa > 0 and av < pa * 0.5: jump.append("수량 급감")
            elif av is not None and pa is not None and pa <= 0 < av: jump.append("수량 재공급")
        rows.append(dict(et=ts.tz_convert(ET).strftime("%m/%d %H:%M"), kst=ts.tz_convert(KST).strftime("%m/%d %H:%M"), fee=fee, avail=av, jump=jump, ts=ts))
        prev = (fee, av)
    return rows[::-1][:n]

# ---------------------------------------------------------------- 이벤트 로그 (번호 타임라인)
FORM_KO = {"S-1": "증권신고서(S-1)", "S-1/A": "증권신고서 수정(S-1/A)", "F-1": "증권신고서(F-1)", "F-1/A": "증권신고서 수정(F-1/A)", "EFFECT": "신고서 효력 발생(EFFECT)",
           "424B4": "공모가 확정(424B4)", "424B5": "증자 설명서(424B5)", "424B3": "설명서(424B3)", "S-3": "셸프 등록(S-3)", "F-3": "셸프 등록(F-3)", "8-K": "주요 공시(8-K)", "6-K": "외국 기업 공시(6-K)",
           "10-Q": "분기 보고서", "10-K": "연간 보고서", "20-F": "연간 보고서(20-F)", "RW": "신고서 철회(RW)", "FWP": "투자 설명 자료(FWP)"}

def event_timeline(px, fil=None, bor_rows=None, news=None, eh=None, trigger=None, price=None, days=10, cik=None, judged=None):
    """[(정렬키, 날짜표시, 종류, 문장, 링크)] — 최근 days 일."""
    E = []
    if px is None or not len(px): return E
    d = px.sort_values("date").reset_index(drop=True)
    since = pd.Timestamp(d["date"].iloc[-1]) - pd.Timedelta(days=days)
    for i in range(max(1, len(d) - days), len(d)):
        r, p = d.iloc[i], d.iloc[i - 1]
        ch = (r.close / p.close - 1) * 100 if p.close else 0
        up = (r.high / r.open - 1) * 100 if r.open else 0
        hp = (r.high / p.close - 1) * 100 if p.close else 0
        if abs(ch) >= 15 or up >= 25 or hp >= 30:
            t = f"시가 {fp(r.open)} → 고가 {fp(r.high)}" + (f"(전일 종가 대비 {hp:+.0f}%)" if hp >= 30 else "") + f", 종가 {fp(r.close)} ({ch:+.1f}%)"
            if r.volume and len(d) > 20:
                mv = float(d.volume.iloc[max(0, i - 20):i].median() or 0)
                if mv > 0: t += f", 거래량 평소의 {r.volume / mv:.0f}배"
            E.append((pd.Timestamp(r.date) + pd.Timedelta(hours=16), _d(r.date), "가격", t, None))
    if fil is not None and len(fil):
        f = fil[fil["filed"] >= since]
        for r in f.itertuples():
            fm = str(r.form)
            if fm in ("4", "3", "3/A", "4/A", "SC 13G", "SC 13G/A") or fm.startswith("DEF"): continue
            ko = FORM_KO.get(fm, fm)
            it = str(getattr(r, "items", "") or "")
            if "3.01" in it: ko += " — 상장 유지 기준 미달 통지(3.01)"
            elif "1.01" in it and fm.startswith("8-K"): ko += " — 중요 계약(1.01)"
            elif "2.02" in it: ko += " — 실적"
            j = (judged or {}).get(getattr(r, "accession", ""))
            if j: ko += f" · {j}"
            url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{str(r.accession).replace('-', '')}/{r.accession}-index.htm" if cik and getattr(r, "accession", None) else None
            E.append((pd.Timestamp(r.filed) + pd.Timedelta(hours=8), _d(r.filed), "공시", ko, url))
    for n in (news or [])[:20]:
        try:
            ts = pd.Timestamp(n.get("ts") or n.get("time") or n.get("published") or n.get("date"))
            if ts.tzinfo is not None: ts = ts.tz_convert(ET).tz_localize(None)
            if ts < since: continue
            E.append((ts, ts.strftime("%m/%d"), "뉴스", str(n.get("title"))[:90], n.get("link") or n.get("url")))
        except Exception: continue
    for r in (bor_rows or []):
        if r["jump"]:
            t = r["ts"].tz_convert(ET).tz_localize(None)
            if t < since: continue
            E.append((t, r["et"][:5], "대차", f"{' · '.join(r['jump'])}: 대차이자 {r['fee']:.0f}% · 빌릴 주식 {r['avail']:,.0f}주 (ET {r['et'][6:]})", None))
    if eh and eh.get("day"):
        dd = pd.Timestamp(eh["day"])
        for s, ko, hh in (("pre", "프리장", 9), ("post", "애프터", 20)):
            x = eh.get(s) or {}
            if x.get("hi") and x.get("lo") and eh.get("prev_close" if s == "pre" else "reg_close"):
                base = eh["prev_close"] if s == "pre" else eh["reg_close"]
                mv = (x["hi"] / base - 1) * 100
                if abs(mv) >= 8 or abs(x["lo"] / base - 1) * 100 >= 8:
                    E.append((dd + pd.Timedelta(hours=hh), dd.strftime("%m/%d"), "시간외", f"{ko} 저 {fp(x['lo'])} · 고 {fp(x['hi'])} (기준 {fp(base)} 대비 고가 {mv:+.0f}%)", None))
    E.sort(key=lambda x: x[0])
    if trigger and price:
        tp, tw = trigger
        E.append((pd.Timestamp.max, "지금", "트리거", f"현재 {fp(price)}, 트리거 {fp(tp)} ({tw}) " + ("돌파 — 유지되는지 확인" if price >= tp else f"까지 {pct(tp, price):+.1f}% — 재시험 대기"), None))
    return E[-12:]

# ---------------------------------------------------------------- 숏 커버 경보 레벨
def cover_alert(f, lm, ez, bor_rows, price, rvol=None):
    """5개 조건 체크리스트 → 레벨 = 충족 수 (1~5). 데이터 없는 조건은 '데이터 없음'으로 미충족 처리."""
    C = []
    av, fee = f.get("avail"), f.get("fee")
    if av is None: C.append(("빌릴 주식 고갈 (차입 가능 0)", None, "IBKR 대차 목록에 없음 — 데이터 없음"))
    else: C.append(("빌릴 주식 고갈 (차입 가능 0)", av <= 0, f"차입 가능 {av:,.0f}주" + (" — 새 숏이 들어오기 어려움" if av <= 0 else "")))
    if fee is None: C.append(("대차이자 높음 또는 상승", None, "데이터 없음"))
    else:
        old = None
        if bor_rows and len(bor_rows) > 1:
            old = bor_rows[-1]["fee"]
        ch = f.get("fee_chg")
        rising = (ch is not None and ch >= 10) or (old is not None and fee - old >= 10)
        C.append(("대차이자 높음 또는 상승", bool(fee >= 50 or rising), f"연 {fee:.0f}%" + (f" (최근 기록 대비 {fee - old:+.0f}%p)" if old is not None and abs(fee - old) >= 1 else "") +
                  (f" (5일 전 대비 {ch:+.0f}%p)" if ch is not None and abs(ch) >= 1 else "")))
    if not ez: C.append(("주가가 숏 평균 진입가 위", None, "FINRA 공매도 거래량 데이터 없음"))
    else:
        ok = ez["avg"] is not None and price > ez["avg"]
        C.append(("주가가 숏 평균 진입가 위", bool(ok), f"최근 {ez['n_days']}거래일 숏 평균 진입 추정 {fp(ez['avg'])} · 손실권 비중 {ez['loss_share']:.0f}%"))
    if rvol is None: C.append(("거래량 급증", None, "데이터 없음"))
    else: C.append(("거래량 급증", rvol >= 3, f"평소(20일 중앙값)의 {rvol:.1f}배"))
    tg = lm.get("trigger") if lm else None
    if not tg: C.append(("트리거 근접 (3% 이내 또는 돌파)", None, "위쪽 저항 레벨 없음"))
    else:
        reach = price / tg[0] * 100
        C.append(("트리거 근접 (3% 이내 또는 돌파)", reach >= 97, f"트리거 {fp(tg[0])} ({tg[1]}) 도달률 {reach:.1f}%"))
    met = sum(1 for c in C if c[1]); unk = sum(1 for c in C if c[1] is None)
    return {"level": max(1, met), "met": met, "unknown": unk, "checks": C,
            "trigger": tg, "reach": (price / tg[0] * 100) if tg else None, "next_res": lm.get("next_res") if lm else None}

def cover_story(ca, f):
    """경보 한 줄 해설."""
    m = {c[0]: c[1] for c in ca["checks"]}
    parts = []
    if m.get("빌릴 주식 고갈 (차입 가능 0)"): parts.append("새로 빌릴 주식 없음")
    if m.get("대차이자 높음 또는 상승"): parts.append("대차이자 비쌈·상승")
    if m.get("주가가 숏 평균 진입가 위"): parts.append("최근 숏 대부분 손실권")
    if m.get("거래량 급증"): parts.append("거래량 급증")
    s = ("지금: " + " · ".join(parts) + ". ") if parts else "지금 충족된 조건이 없습니다. "
    tg = ca.get("trigger")
    if tg:
        s += f"트리거 {fp(tg[0])}({tg[1]}) " + ("위에서 버티면 숏 커버(되사기)가 몰릴 수 있습니다." if (ca["reach"] or 0) >= 100 else "를 넘으면 숏 커버가 붙을 수 있습니다.")
    if ca["unknown"]: s += f" (조건 {ca['unknown']}개는 데이터 없음 → 미충족 처리)"
    return s.strip()


# ---------------------------------------------------------------- 한 번에 묶기 (앱용)
def radar(x, fetch_docs=True):
    """live.snapshot 결과 → 레벨 맵·진입 구간·대차 표·이벤트 로그·커버 경보·공모 감지. 실패한 부분은 None (화면은 '데이터 없음')."""
    from . import offering, sources as src
    t, b, f, eh = x["ticker"], x["b"], x["f"], x.get("eh") or {}
    price = eh.get("last") or f["price"]
    R = {"price": price, "err": []}
    try: R["off"] = offering.detect(t, px=b.px, dil=x.get("dil"), delist=x.get("delist"), fetch_docs=fetch_docs)
    except Exception as e: R["off"] = None; R["err"].append(f"공시: {e}")
    off = R["off"] or {}
    try: R["lm"] = level_map(b.px, eh, price, off.get("levels"), f.get("fee"), f.get("avail"))
    except Exception as e: R["lm"] = None; R["err"].append(f"레벨: {e}")
    try: R["ez"] = entry_zones(b.px, b.sv, price, off.get("offer"))
    except Exception as e: R["ez"] = None; R["err"].append(f"진입: {e}")
    try: R["br"] = borrow_table(b.bor)
    except Exception as e: R["br"] = None; R["err"].append(f"대차: {e}")
    try:
        fil = src.get_filings(t)
        news = src.fetch_news(t)
        R["ev"] = event_timeline(b.px, fil, R["br"], news, eh, (R["lm"] or {}).get("trigger"), price, cik=off.get("cik"))
    except Exception as e: R["ev"] = []; R["err"].append(f"이벤트: {e}")
    try:
        from . import pattern as PT
        R["pat"] = PT.match(b.px, f, getattr(b, "info", None), getattr(b, "fil", None))
    except Exception as e: R["pat"] = None; R["err"].append(f"패턴: {e}")
    try:
        R["ca"] = cover_alert(f, R["lm"], R["ez"], R["br"], price, f.get("vol_ratio"))
        R["story"] = cover_story(R["ca"], f)
    except Exception as e: R["ca"] = None; R["story"] = ""; R["err"].append(f"경보: {e}")
    return R
