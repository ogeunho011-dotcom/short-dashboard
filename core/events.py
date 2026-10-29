"""최신 공시로 💣 구조 입력 보정 + 참고 경고 4종 (SEC EDGAR 원문 · 무료).

A. 최신 값 (companyfacts 가 늦을 때):
   - 현금·월 소진: 10-Q/10-K/20-F/6-K 의 XBRL 인스턴스(*_htm.xml) 에서 차원 없는 값 (us-gaap / ifrs-full)
   - 주식 수: 표지 dei 값, 13D/13G·증권신고서 본문 'N shares outstanding as of 날짜', 그 날짜 뒤 발행(부채→주식 교환 등) 합산
B. 참고 경고:
   1 rsmeet  역분할 안건 주총 (DEF/PRE 14A, 외국 기업 6-K) — 주총 날짜
   2 swap    내부자 부채→주식 교환 (set-off / debt conversion) — 교환가 vs 종가, 새 주식 %, 현금 유입 없음
   3 le10    종가 $0.10 이하 10거래일 연속 (나스닥 5810(c)(3)(A)(iii) 즉시 상폐 결정 대상)
   4 delist  나스닥 상폐 결정·청문 진행 (8-K/6-K)
공시 원문 해석은 접수번호별 영구 캐시 (kv fdoc:{acc}), 종목별 모음은 kv fdocs:{t}.
모든 값은 공시 접수일(filed) ≤ 기준일만 씀 (미래 정보 없음). 규칙·정규식 기반이라 틀릴 수 있어 원문 링크를 같이 보여 줌."""
import re, json, datetime as dt
from pathlib import Path
import pandas as pd
from . import db

ROOT = Path(__file__).resolve().parent.parent
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
DATE = rf"(?:{MONTHS})\s+\d{{1,2}},?\s*20\d\d"
KIND_KO = {"rsmeet": "🗳️ 역분할 안건 주총", "swap": "🔁 내부자 부채→주식 교환", "le10": "⛔ $0.10 이하 10일 연속", "delist": "🚪 나스닥 상폐 결정·청문"}
DELIST_KO = {"determination": "상폐 결정 통지 받음", "hearing": "청문(이의 신청) 진행 중", "extension": "청문 패널이 유예 허용",
             "panel_delist": "청문 패널 상폐 결정·거래 정지", "regained": "기준 회복 (해소)"}

def _date(s):
    if not s: return None
    try: return dt.datetime.strptime(re.sub(r"\s+", " ", s.replace(",", ", ")).replace(" ,", ",").replace(",  ", ", ").strip(), "%B %d, %Y").date().isoformat()
    except Exception:
        try: return dt.datetime.strptime(re.sub(r"[,\s]+", " ", s).strip(), "%B %d %Y").date().isoformat()
        except Exception: return None

def _n(s):
    try: return float(str(s).replace(",", ""))
    except Exception: return None

# ---------------------------------------------------------------- 순수 해석기 (단위 테스트 대상)
def parse_instance(xml):
    """XBRL 인스턴스 → {cash:(end,val), opcf:(start,end,val), shares:(date,val)} · 차원(segment) 있는 문맥은 버림."""
    x = xml.decode("utf-8", "ignore") if isinstance(xml, bytes) else xml
    ctx = {}
    for m in re.finditer(r"<(?:xbrli:)?context\b[^>]*\bid=\"([^\"]+)\"[^>]*>(.*?)</(?:xbrli:)?context>", x, re.S):
        body = m.group(2)
        if re.search(r"<(?:xbrli:)?segment|<xbrldi:", body): continue
        i = re.search(r"<(?:xbrli:)?instant>\s*([\d-]{10})", body)
        s = re.search(r"<(?:xbrli:)?startDate>\s*([\d-]{10})", body); e = re.search(r"<(?:xbrli:)?endDate>\s*([\d-]{10})", body)
        ctx[m.group(1)] = (None, i.group(1)) if i else ((s.group(1), e.group(1)) if s and e else None)
    def facts(tags):
        out = []
        for tg in tags:
            for m in re.finditer(rf"<{tg}\b([^>]*)>\s*(-?[\d.]+)\s*</{tg}>", x):
                c = re.search(r"contextRef=\"([^\"]+)\"", m.group(1))
                p = ctx.get(c.group(1)) if c else None
                if p: out.append((p[0], p[1], float(m.group(2))))
        return out
    r = {}
    c = facts(["us-gaap:CashAndCashEquivalentsAtCarryingValue", "ifrs-full:CashAndCashEquivalents", "us-gaap:Cash",
               "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"])
    c = [v for v in c if v[0] is None]
    if c:
        e = max(v[1] for v in c); r["cash"] = (e, next(v[2] for v in c if v[1] == e))
    o = facts(["us-gaap:NetCashProvidedByUsedInOperatingActivities", "ifrs-full:CashFlowsFromUsedInOperatingActivities",
               "us-gaap:NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"])
    o = [v for v in o if v[0]]
    if o:
        e = max(v[1] for v in o); cand = [v for v in o if v[1] == e]
        v = max(cand, key=lambda v: (pd.Timestamp(v[1]) - pd.Timestamp(v[0])).days)   # 같은 끝날이면 가장 긴 기간 (YTD)
        r["opcf"] = v
    s = facts(["dei:EntityCommonStockSharesOutstanding"])
    s = [v for v in s if v[0] is None]
    if s:
        e = max(v[1] for v in s); r["shares"] = (e, sum(v[2] for v in s if v[1] == e))   # 여러 종류 주식은 합산
    return r

SH_PAT = [
    rf"([\d,]{{7,}})\s+(?:issued and )?(?:outstanding )?(?:ordinary shares|common shares|shares of (?:our |the Company[’']s |the Issuer[’']s )?(?:Class A )?(?:common stock|ordinary shares)|shares)[^.\d]{{0,60}}?(?:issued and )?outstanding,?\s+(?:as of|on|at)\s+({DATE})",
    rf"(?:As of|On)\s+({DATE}),?\s+(?:there were|the (?:Company|Issuer|registrant) had|we had)\s+([\d,]{{7,}})\s+(?:ordinary shares|common shares|shares)",
]
def parse_shares_out(text):
    """'85,956,495 ordinary shares outstanding as of October 27, 2026' → [(85956495.0, '2026-10-27')]"""
    out = []
    for k, p in enumerate(SH_PAT):
        for m in re.finditer(p, text, re.I):
            n, d = (m.group(1), m.group(2)) if k == 0 else (m.group(2), m.group(1))
            n, d = _n(n), _date(d)
            if n and d and 1e5 <= n <= 5e10: out.append((n, d))
    return sorted(set(out), key=lambda v: v[1])

SWAP_RE = r"set-?off agreement|\bset-?off\b|offsetting (?:the )?(?:financial )?liabilit|debt conversion|debt[- ]for[- ]equity|in exchange for the (?:cancellation|extinguishment|satisfaction|conversion)|conver(?:t|ted|sion of) (?:the |certain )?(?:outstanding )?(?:shareholder |related[- ]party )?(?:loans?|indebtedness|advances|notes? payable)\b"
INSIDER_RE = r"\binsiders?\b|\bdirectors?\b|\bofficers?\b|chief executive|chairman|largest shareholder|principal shareholder|majority shareholder|\baffiliate|founder|related part"
def parse_swap(text):
    """내부자 부채→주식 교환 · {shares, price, premium, close_date, insider, cash_in:False} 또는 None."""
    if not re.search(SWAP_RE, text, re.I): return None
    w = re.search(SWAP_RE, text, re.I).start()
    win = text[max(0, w - 2500): w + 2500]
    sh = None
    m = re.search(r"(\d+(?:\.\d+)?)\s+million\s+(?:of (?:its|our|the Company[’']s) )?(?:unregistered |newly issued |restricted )?(?:ordinary shares|common shares|shares)", win, re.I)
    if m: sh = float(m.group(1)) * 1e6
    else:
        m = re.search(r"([\d,]{6,})\s+(?:unregistered |newly issued |restricted )?(?:ordinary shares|common shares|shares of (?:the Company[’']s )?common stock|shares)", win, re.I)
        if m: sh = _n(m.group(1))
    pr = None
    m = re.search(r"(?:subscription|conversion|exchange|issue|purchase|offering)? ?price (?:per share )?of (?:US)?\$\s?([\d.]+)|at (?:a price of )?(?:US)?\$\s?([\d.]+) per (?:ordinary )?share|price per share of (?:US)?\$\s?([\d.]+)", win, re.I)
    if m: pr = _n(next(g for g in m.groups() if g))
    pm = re.search(r"premium of (?:approximately |about )?([\d.]+)\s?%", win, re.I)
    cd = re.search(rf"closing (?:bid )?price[^.]{{0,80}}?on ({DATE})", win, re.I)
    if not (sh or pr): return None
    return dict(shares=sh, price=pr, premium=_n(pm.group(1)) if pm else None, close_date=_date(cd.group(1)) if cd else None,
                insider=bool(re.search(INSIDER_RE, win, re.I)), cash_in=False)

RS_RE = r"reverse (?:stock |share )?split|share consolidation|consolidation of (?:the Company[’']s |our )?(?:ordinary )?shares"
def parse_rsmeet(text, filed=None):
    """역분할 안건 주총 · {date, ratio} 또는 None. 주총 날짜는 접수일 이후 첫 날짜."""
    if not re.search(RS_RE, text, re.I): return None
    dates = []
    for m in re.finditer(rf"(annual|special|extraordinary)(?: and special)?(?: general)? meeting(?: of (?:the )?(?:stock|share)holders)?[^.]{{0,200}}?({DATE})", text[:200_000], re.I):
        d = _date(m.group(2))
        if d and (not filed or d >= filed): dates.append((d, m.group(1).lower()))
    if not dates: return None
    d, kind = sorted(dates)[0]
    rt = None
    m = re.search(r"1[- ]for[- ](\d+)[^.]{0,60}?(?:to|and) 1[- ]for[- ](\d+)", text, re.I) or re.search(r"1[- ]for[- ](\d+)", text, re.I)
    if m: rt = "1:" + "~".join(m.groups())
    return dict(date=d, kind=kind, ratio=rt)

def parse_delist(text):
    """상폐 결정·청문 상태 · {status, hearing} 또는 None."""
    if not re.search(r"Nasdaq|NYSE", text): return None
    st = None
    if re.search(r"Panel (?:has |had )?(?:determined|decided) to (?:delist|suspend)|(?:will|to) file (?:a )?Form 25|(?:trading|shares) (?:in the Company[’']s (?:ordinary shares|common stock|securities) )?(?:will be|was|were|has been) suspended (?:effective|on|at the opening)", text, re.I): st = "panel_delist"
    elif re.search(r"Panel (?:has |had )?granted|granted (?:the Company )?(?:an? )?(?:exception|extension)", text, re.I): st = "extension"
    elif re.search(r"request(?:ed|s)? (?:a|an oral|a written) hearing|request for (?:a|an oral) hearing|hearing (?:request|before the Panel|is scheduled|has been scheduled|was held)|appealed the (?:Staff[’']s )?(?:Delisting )?Determination", text, re.I): st = "hearing"
    elif re.search(r"Staff Delisting Determination|delist(?:ing)? determination|Determination Letter|determined (?:that the Company[’']s securities would be|to delist)|will be delisted", text, re.I): st = "determination"
    elif re.search(r"\b(?:has |had )?regained compliance", text, re.I) and re.search(r"Panel|hearing|delist", text, re.I): st = "regained"
    if not st: return None
    h = re.search(rf"hearing[^.]{{0,80}}?(?:is |has been )?(?:scheduled (?:for|on)|to be held on|will be held on) ({DATE})", text, re.I)
    return dict(status=st, hearing=_date(h.group(1)) if h else None)

def le10_streak(px):
    """마지막 날 기준 종가 ≤ $0.10 연속 거래일 수."""
    if px is None or not len(px): return 0
    c = px["close"].values[::-1]; n = 0
    for v in c:
        if v == v and v <= 0.10: n += 1
        else: break
    return n

# ---------------------------------------------------------------- 공시 원문 읽기 (접수번호별 영구 캐시)
PERIODIC = {"10-Q", "10-K", "10-Q/A", "10-K/A", "20-F", "20-F/A", "40-F", "10-KT"}
EVENT = {"8-K", "8-K/A", "6-K", "6-K/A", "DEF 14A", "PRE 14A", "DEFA14A", "DEFR14A", "DEF 14C", "PRE 14C"}
HOLD = {"SCHEDULE 13D", "SCHEDULE 13D/A", "SCHEDULE 13G", "SCHEDULE 13G/A", "SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A"}
REG = {"424B3", "424B4", "424B5", "424B1", "S-1", "S-1/A", "F-1", "F-1/A", "S-3", "F-3", "POS AM"}
DOC_FORMS = PERIODIC | EVENT | HOLD | REG

def _fetch(cik, acc, form, primary=""):
    from .filings import sec_get, _clean
    base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/"
    names = []
    try: names = [i["name"] for i in sec_get(base + "index.json").json().get("directory", {}).get("item", [])]
    except Exception: pass
    d = dict(acc=acc, form=form, ok=bool(names))
    inst = [n for n in names if re.search(r"_htm\.xml$", n, re.I)] or \
           [n for n in names if re.search(r"\d{8}\.xml$", n) and not re.search(r"_(cal|def|lab|pre)\.xml$", n)]
    if inst and (form in PERIODIC or form.startswith("6-K")):
        try: d["xbrl"] = parse_instance(sec_get(base + inst[0], timeout=40).content)
        except Exception: pass
    if form in PERIODIC: return d   # 정기 보고서 본문은 크고 표지 주식 수는 dei 에 있음
    docs = [primary] if primary else []
    docs += [n for n in names if re.search(r"ex-?99|dex99", n, re.I) and n.lower().endswith((".htm", ".html", ".txt")) and n != primary]
    if form in HOLD and "primary_doc.xml" in names and "primary_doc.xml" not in docs: docs.insert(0, "primary_doc.xml")
    txt = []
    for n in docs[:3]:
        try: txt.append(_clean(sec_get(base + n, timeout=30).content[: 1_500_000 if form in REG or "14A" in form else 600_000]))
        except Exception: pass
    t = " ".join(txt)
    d["ok"] = d["ok"] and bool(t)
    d["shares_out"] = parse_shares_out(t)[-3:]
    if form in EVENT:
        d["swap"] = parse_swap(t)
        if "14" in form or form.startswith("6-K"): d["rsmeet"] = parse_rsmeet(t, None)
        if form.startswith(("8-K", "6-K")): d["delist"] = parse_delist(t)
    return d

def scan(ticker, days=150, max_new=12, fetch=True, ttl=6 * 3600):
    """최근 공시 원문 해석 모음 (새 공시만 원문을 받음). fetch=False 면 캐시만."""
    k = f"fdocs:{ticker}"
    c = db.kv_get(k, ttl)
    if (c is not None and not c.get("partial")) or not fetch: return c or db.kv_get(k) or {"docs": []}
    from . import offering as OF
    sub = OF.submissions(ticker)
    cik = sub.get("cik")
    if not cik: return {"docs": []}
    cut = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    rows = [r for r in sub.get("rows", []) if r["filed"] >= cut and r["form"] in DOC_FORMS][:30]
    out, new = [], 0
    for r in rows:
        d = db.kv_get(f"fdoc:{r['acc']}")
        if d is None and new < max_new:
            d = _fetch(cik, r["acc"], r["form"], r.get("primary") or ""); new += 1
            if d.get("ok"): db.kv_set(f"fdoc:{r['acc']}", d)
        if d: out.append({**d, "filed": r["filed"], "form": r["form"], "items": r.get("items", ""),
                          "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{r['acc'].replace('-', '')}/{r['acc']}-index.htm"})
    res = {"cik": cik, "docs": out, "ts": dt.datetime.now().isoformat(timespec="seconds"), "partial": new >= max_new}
    db.kv_set(k, res)
    return res

def refresh(tickers, budget_s=600, max_new=8):
    """일일 작업용: 여러 종목 공시 원문 갱신 (시간 예산 안에서)."""
    import time
    t0, n = time.time(), 0
    for t in tickers:
        if time.time() - t0 > budget_s: break
        try: scan(t, max_new=max_new, ttl=12 * 3600); n += 1
        except Exception: pass
    return n, len(tickers), round(time.time() - t0)

# ---------------------------------------------------------------- A. 최신 값
def latest(fd, asof=None):
    """공시 모음 → {cash:(end,val,src), opcf:(start,end,val,src), shares:{n, date, base, adds, src}} · 접수일 ≤ asof 만."""
    asof = str(asof or dt.date.today())[:10]
    docs = [d for d in (fd or {}).get("docs", []) if d.get("filed", "9") <= asof]
    r = {}
    for d in docs:
        x = d.get("xbrl") or {}
        tag = f"{d['form']} {d['filed']}"
        if x.get("cash") and (not r.get("cash") or x["cash"][0] > r["cash"][0]): r["cash"] = (*x["cash"], tag, d.get("url"))
        if x.get("opcf") and (not r.get("opcf") or x["opcf"][1] > r["opcf"][1]): r["opcf"] = (*x["opcf"], tag, d.get("url"))
    cand = []
    for d in docs:
        x = d.get("xbrl") or {}
        if x.get("shares"): cand.append((x["shares"][0], x["shares"][1], f"{d['form']} 표지", d.get("url")))
        for n, dd in d.get("shares_out") or []:
            if dd <= d["filed"]: cand.append((dd, n, d["form"], d.get("url")))
    if cand:
        base = max(cand, key=lambda v: (v[0], v[1]))
        adds = []
        seen = set()
        for d in sorted(docs, key=lambda d: d["filed"]):
            s = d.get("swap")
            if s and s.get("shares") and s.get("price") and d["filed"] >= base[0] and (s.get("close_date") or d["filed"]) >= base[0]:
                key = (s["shares"], s.get("price"))
                if key in seen: continue   # 같은 거래를 6-K·보도자료가 두 번 공시
                seen.add(key); adds.append((d["filed"], s["shares"], "부채→주식 교환"))
        r["shares"] = dict(n=base[1] + sum(a[1] for a in adds), date=base[0], base=base[1], adds=adds, src=base[2], url=base[3])
    return r

# ---------------------------------------------------------------- B. 경고
def warnings(t, px=None, fd=None, exchange=None, asof=None, close_before=None):
    """참고 경고 목록 [{kind, text, date, url, scored}] · 데이터 없으면 빈 목록."""
    if px is not None and len(px) and "date" in px.columns:
        px = px.set_index(pd.to_datetime(px["date"])).sort_index()
    asof = str(asof or (px.index[-1].date() if px is not None and len(px) else dt.date.today()))[:10]
    W = []
    docs = [d for d in (fd or {}).get("docs", []) if d.get("filed", "9") <= asof]
    ev = study_flags()
    # 1 역분할 주총
    rm = [d for d in docs if d.get("rsmeet") and d["rsmeet"]["date"] >= asof]
    if rm:
        d = max(rm, key=lambda d: d["filed"]); m = d["rsmeet"]
        W.append(dict(kind="rsmeet", date=m["date"], url=d.get("url"), scored=ev.get("rsmeet", False),
                      text=f"{KIND_KO['rsmeet']} {m['date']} ({d['form']} {d['filed']}{', 비율 ' + m['ratio'] if m.get('ratio') else ''}) — 주총 뒤 역분할·증자가 잦음"))
    # 2 부채→주식 교환
    sw = [d for d in docs if d.get("swap") and d["swap"].get("insider") and d["filed"] >= (pd.Timestamp(asof) - pd.Timedelta(days=60)).strftime("%Y-%m-%d")]
    if sw:
        d = max(sw, key=lambda d: d["filed"]); s = d["swap"]
        cl = None
        if px is not None and len(px):
            ref = s.get("close_date") or d["filed"]
            p0 = px[px.index.strftime("%Y-%m-%d") <= ref] if s.get("close_date") else px[px.index.strftime("%Y-%m-%d") < ref]
            if len(p0): cl = float(p0["close"].iloc[-1])
        prem = (s["price"] / cl - 1) * 100 if s.get("price") and cl else s.get("premium")
        lat = latest(fd, asof).get("shares") or {}
        base = lat.get("base")
        pct = s["shares"] / base * 100 if s.get("shares") and base else None
        bits = [f"교환가 ${s['price']:.4g}" if s.get("price") else "교환가 데이터 없음",
                f"직전 종가 ${cl:.4g}" if cl else "직전 종가 데이터 없음",
                f"{'+' if (prem or 0) >= 0 else ''}{prem:.0f}%" if prem is not None else "",
                f"새 주식 {s['shares'] / 1e6:.1f}M주 (기존 대비 +{pct:.0f}%)" if pct else (f"새 주식 {s['shares'] / 1e6:.1f}M주" if s.get("shares") else "")]
        W.append(dict(kind="swap", date=d["filed"], url=d.get("url"), scored=ev.get("swap", False),
                      text=f"{KIND_KO['swap']} {d['filed']}: " + " · ".join(b for b in bits if b) + " — 현금 유입 없음 (빚을 주식으로 갚음)"))
    # 3 $0.10 이하 10일 연속
    nst = le10_streak(px[px.index.strftime("%Y-%m-%d") <= asof] if px is not None and len(px) else px)
    if nst >= 10 and (exchange or "").upper().startswith("NASDAQ"):
        W.append(dict(kind="le10", date=asof, url=None, scored=ev.get("le10", False),
                      text=f"{KIND_KO['le10']}: {nst}거래일 연속 종가 ≤ $0.10 — 나스닥 규정상 유예 없이 상폐 결정 통지 대상 (종가 기준 추정, 공식 기준은 매수 호가)"))
    elif 7 <= nst < 10 and (exchange or "").upper().startswith("NASDAQ"):
        W.append(dict(kind="le10", date=asof, url=None, scored=False, text=f"⛔ $0.10 이하 {nst}거래일 연속 — 10일 되면 나스닥 즉시 상폐 결정 대상"))
    # 4 상폐 결정·청문
    dl = [d for d in docs if d.get("delist") and d["filed"] >= (pd.Timestamp(asof) - pd.Timedelta(days=180)).strftime("%Y-%m-%d")]
    if dl:
        d = max(dl, key=lambda d: d["filed"]); s = d["delist"]
        if s["status"] != "regained":
            W.append(dict(kind="delist", date=d["filed"], url=d.get("url"), scored=ev.get("delist", False),
                          text=f"{KIND_KO['delist']}: {DELIST_KO[s['status']]} ({d['form']} {d['filed']}{', 청문 ' + s['hearing'] if s.get('hearing') else ''})"))
    return W

def warn_text(W, sep=" · "):
    return sep.join(w["text"] + (" [점수 반영]" if w.get("scored") else " [참고]") for w in W)

_SF = {}
def study_flags():
    """model/events_study.json 의 검증 결과 → {kind: True(근거 성립 → 점수 반영)}."""
    if "v" in _SF: return _SF["v"]
    try: j = json.loads((ROOT / "model" / "events_study.json").read_text())
    except Exception: j = {}
    _SF["v"] = {k: bool(v.get("holds")) for k, v in (j.get("kinds") or {}).items()}
    return _SF["v"]

def study_note():
    """검증 결과 한 줄 요약 (화면 각주). 결과 파일이 없으면 그렇다고 표시."""
    try: j = json.loads((ROOT / "model" / "events_study.json").read_text())
    except Exception: return "과거 검증 결과 데이터 없음 → 4종 모두 참고만"
    P = []
    for k in ("rsmeet", "swap", "le10", "delist"):
        v = (j.get("kinds") or {}).get(k) or {}
        if not v.get("n"): P.append(f"{KIND_KO[k]} 사건 없음"); continue
        P.append(f"{KIND_KO[k]} {v['n']}건 20일 중앙값 {v['r20_med'] * 100:+.0f}% (기준 {v['base']['r20'] * 100:+.0f}%) → " + ("점수 반영" if v.get("holds") else "근거 부족, 참고"))
    return "과거 검증(다음날 시가 진입): " + " · ".join(P)

_EX = {}
def exchange(ticker):
    if not _EX:
        try: _EX.update(dict(db.q("SELECT ticker, exchange FROM universe").values.tolist()))
        except Exception: pass
    return _EX.get(ticker)

def for_ticker(t, px, fetch=False):
    """(latest 값, 경고 목록) — 상세 카드(fetch=True)·스캔·🔮·🌙(캐시만)."""
    fd = scan(t, fetch=True) if fetch else cached(t)
    return latest(fd), warnings(t, px, fd, exchange=exchange(t))

def cached(ticker):
    return db.kv_get(f"fdocs:{ticker}") or {"docs": []}
