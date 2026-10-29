"""🔬 SEC 리서치 퀵스캔 — 급등 후보의 공시 구조를 한 화면에 정리 (SEC EDGAR 무료 원문 · XBRL · DB 일봉).

방법(요약, 앱 고유 문구):
- 숫자마다 출처(서류·접수일·링크)와 신뢰도(A~D)를 붙이고, '없음'(공시를 봤는데 해당 없음)과 '확인되지 않음'(데이터를 못 봄)을 구분
- 주식 장부 7칸 (이미 발행 / 지금 바로 발행 가능 / 조건부 / 보상 예약 / 재판매 등록(이미 발행분) / 셸프 남은 금액 / 소진·만료)
  · 재판매 등록 주식은 이미 발행됐거나 워런트 칸에 있으므로 완전희석에 다시 더하지 않음 (중복 금지)
- 완전희석 3단계(기본·현실·최대) · 추가 발행 여유 3단계(정관 한도 기준 원래 여유 · 대기 물량 뺀 여유 · 약정까지 뺀 여유)
- 베이비 셸프(유통 시총 $75M 미만이면 12개월 S-3 발행 한도 = 유통 시총 1/3)
- Rule 144(보고 기업 6개월)·락업 해제 · 내부자·대주주 움직임(질문 형태로만) · 행사가·공모가 + 위 매물대(겹치면 이중 저항)
- 상장 유지 기준(거래소별) · Bull/Base/Bear(가능성 낮음/보통/높음) · 9개 항목 점수(/100, 등급 A~D)와 별도 신뢰도
- 10개 점검 관문 · 핵심 팩트 요약 · 확인 요청(어느 서류에서 확인할지)
점수는 '지금 구조가 얼마나 덜 위험한가'의 참고값이며 앱 종합점수에 넣지 않음 (scripts/sec_study.py 검증 결과는 model/sec_study.json).
규칙·키워드 기반이라 틀릴 수 있음 → 원문 링크를 같이 보여 줌. 투자 권유 아님."""
import re, json, math, time, hashlib, datetime as dt
from pathlib import Path
import numpy as np, pandas as pd
from . import db

ROOT = Path(__file__).resolve().parents[1]
NA = "확인되지 않음"     # 데이터를 못 봄
NONE = "없음"            # 공시를 봤고 해당 없음
LEVELS = ("Critical", "Material", "Context")
LEVEL_KO = {"Critical": "🔴 결정적", "Material": "🟠 중요", "Context": "⚪ 참고"}
BUCKETS = [("out", "이미 발행된 주식"), ("now", "지금 바로 발행 가능 (행사가 ≤ 현재가 워런트 등)"), ("cond", "조건부 (행사가 > 현재가 워런트·전환사채·우선주)"),
           ("resv", "보상 예약 (스톡옵션·RSU)"), ("resale", "재판매 등록 (이미 발행분 — 완전희석에 다시 안 더함)"),
           ("shelf", "셸프·ATM·ELOC 남은 금액 ($)"), ("gone", "소진·만료·철회")]
RULES_ASOF = "2026-10"   # 앱에 저장한 거래소 규정 숫자 기준 시점 — 공식 원문 재확인 필요

# ---------------------------------------------------------------- 공통 도우미
def _f(x):
    try:
        v = float(x)
        return None if math.isnan(v) or math.isinf(v) else v
    except Exception:
        return None

def _js(o):
    """kv 저장용: numpy·Timestamp → 기본 타입."""
    if isinstance(o, dict): return {str(k): _js(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [_js(v) for v in o]
    if isinstance(o, (np.bool_, bool)): return bool(o)
    if isinstance(o, (np.integer,)): return int(o)
    if isinstance(o, (np.floating, float)): return _f(o)
    if isinstance(o, (pd.Timestamp, dt.date, dt.datetime)): return str(o)[:19]
    return o

def _d(s):
    try: return pd.Timestamp(str(s)[:10])
    except Exception: return None

def usd(v):
    v = _f(v)
    if v is None: return NA
    a = abs(v)
    if a >= 1e9: return f"${v / 1e9:.2f}B"
    if a >= 1e6: return f"${v / 1e6:.2f}M"
    if a >= 1e3: return f"${v / 1e3:.0f}K"
    return f"${v:,.0f}"

def shs(v):
    v = _f(v)
    if v is None: return NA
    if abs(v) >= 1e6: return f"{v / 1e6:.2f}M주"
    if abs(v) >= 1e3: return f"{v / 1e3:.0f}K주"
    return f"{v:,.0f}주"

def pxs(v):
    v = _f(v)
    if v is None: return NA
    return (f"${v:.4f}".rstrip("0").rstrip(".")) if v < 1 else f"${v:,.2f}"

def _num(s):
    try: return float(str(s).replace(",", ""))
    except Exception: return None

def _money(m, unit=None):
    v = _num(m)
    if v is None: return None
    u = (unit or "").lower()
    if u.startswith("million"): v *= 1e6
    elif u.startswith("billion"): v *= 1e9
    return v

# ---------------------------------------------------------------- 1. 데이터 받기 (캐시)
def subm(t, ttl=6 * 3600, fetch=True):
    """SEC submissions: 회사 정보 + 최근 공시(파일 번호 포함). kv secsub:{t}."""
    t = t.upper(); k = f"secsub:{t}"
    c = db.kv_get(k, ttl)
    if c is not None or not fetch: return c or db.kv_get(k)
    from . import sources as src
    from .filings import sec_get
    cik = src.cik_map().get(t)
    if not cik: return {"cik": None, "rows": [], "meta": {}, "err": "SEC 등록 번호(CIK) 없음"}
    try:
        j = sec_get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", timeout=30).json()
    except Exception as e:
        return db.kv_get(k) or {"cik": cik, "rows": [], "meta": {}, "err": repr(e)[:120]}
    r = j.get("filings", {}).get("recent", {})
    n = len(r.get("form", []))
    cut = (dt.date.today() - dt.timedelta(days=4 * 365)).isoformat()
    g = lambda key, i: ((r.get(key) or [""] * n)[i] or "")
    rows = [dict(form=g("form", i), filed=g("filingDate", i), acc=g("accessionNumber", i), primary=g("primaryDocument", i), items=g("items", i),
                 fn=g("fileNumber", i), report=g("reportDate", i), desc=g("primaryDocDescription", i)) for i in range(n) if g("filingDate", i) >= cut]
    ad = (j.get("addresses") or {}).get("business") or {}
    meta = dict(name=j.get("name"), entityType=j.get("entityType"), sic=j.get("sic"), sicDesc=j.get("sicDescription"),
                category=re.sub(r"<br>", " · ", j.get("category") or "").strip(" ·"), fye=j.get("fiscalYearEnd"),
                state=j.get("stateOfIncorporation"), stateDesc=j.get("stateOfIncorporationDescription"), exchanges=j.get("exchanges") or [],
                tickers=j.get("tickers") or [], hq=ad.get("stateOrCountryDescription"), foreign=bool(ad.get("isForeignLocation")),
                former=[x.get("name") for x in (j.get("formerNames") or [])][:3])
    out = {"cik": cik, "rows": rows, "meta": meta, "ts": dt.datetime.now().isoformat(timespec="seconds")}
    db.kv_set(k, out)
    return out

FX = {   # 이름: [(네임스페이스, 태그, 단위)] — 앞에서부터 있는 것 사용
    "shares": [("dei", "EntityCommonStockSharesOutstanding", "shares"), ("us-gaap", "CommonStockSharesOutstanding", "shares")],
    "authorized": [("us-gaap", "CommonStockSharesAuthorized", "shares")],
    "float": [("dei", "EntityPublicFloat", "USD")],
    "cash": [("us-gaap", "CashAndCashEquivalentsAtCarryingValue", "USD"), ("us-gaap", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "USD"),
             ("ifrs-full", "CashAndCashEquivalents", "USD")],
    "restricted": [("us-gaap", "RestrictedCashCurrent", "USD"), ("us-gaap", "RestrictedCash", "USD")],
    "opcf": [("us-gaap", "NetCashProvidedByUsedInOperatingActivities", "USD"), ("ifrs-full", "CashFlowsFromUsedInOperatingActivities", "USD")],
    "equity": [("us-gaap", "StockholdersEquity", "USD"), ("us-gaap", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "USD"),
               ("ifrs-full", "Equity", "USD")],
    "ni": [("us-gaap", "NetIncomeLoss", "USD"), ("us-gaap", "ProfitLoss", "USD"), ("ifrs-full", "ProfitLoss", "USD")],
    "revenue": [("us-gaap", "Revenues", "USD"), ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax", "USD"), ("ifrs-full", "Revenue", "USD")],
    "debt_cur": [("us-gaap", "DebtCurrent", "USD"), ("us-gaap", "LongTermDebtCurrent", "USD"), ("us-gaap", "NotesPayableCurrent", "USD")],
    "convertible": [("us-gaap", "ConvertibleNotesPayableCurrent", "USD"), ("us-gaap", "ConvertibleDebtNoncurrent", "USD"), ("us-gaap", "ConvertibleNotesPayable", "USD"),
                    ("us-gaap", "ConvertibleDebtCurrent", "USD")],
    "conv_px": [("us-gaap", "DebtInstrumentConvertibleConversionPrice1", "USD/shares")],
    "warrants": [("us-gaap", "ClassOfWarrantOrRightOutstanding", "shares")],
    "warr_ex": [("us-gaap", "ClassOfWarrantOrRightExercisePriceOfWarrantsOrRights1", "USD/shares"), ("us-gaap", "ClassOfWarrantOrRightExercisePriceOfWarrantsOrRights", "USD/shares")],
    "options": [("us-gaap", "ShareBasedCompensationArrangementByShareBasedPaymentAwardOptionsOutstandingNumber", "shares")],
    "opt_px": [("us-gaap", "ShareBasedCompensationArrangementByShareBasedPaymentAwardOptionsOutstandingWeightedAverageExercisePrice", "USD/shares")],
    "rsu": [("us-gaap", "ShareBasedCompensationArrangementByShareBasedPaymentAwardEquityInstrumentsOtherThanOptionsNonvestedNumber", "shares")],
    "pref_out": [("us-gaap", "PreferredStockSharesOutstanding", "shares")],
    "antidil": [("us-gaap", "AntidilutiveSecuritiesExcludedFromComputationOfEarningsPerShareAmount", "shares")],
}

def facts_ext(t, ttl=7 * 86400, fetch=True):
    """XBRL companyfacts 확장 태그 (최근 5년) — kv secfx:{t}. 못 받으면 기존 facts:{t} 로 일부만."""
    t = t.upper(); k = f"secfx:{t}"
    c = db.kv_get(k, ttl)
    if c is not None: return c
    if not fetch:
        old = db.kv_get(k)
        return old if old is not None else from_basic(db.kv_get(f"facts:{t}") or {})
    from . import sources as src
    from .filings import sec_get
    cik = src.cik_map().get(t)
    if not cik: return {}
    try:
        j = sec_get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json", timeout=45).json()
    except Exception:
        return db.kv_get(k) or from_basic(db.kv_get(f"facts:{t}") or {})
    f = j.get("facts", {})
    cut = (dt.date.today() - dt.timedelta(days=5 * 365)).isoformat()
    out = {"_tags": {}}
    for name, cands in FX.items():
        ser = []
        for ns, tag, unit in cands:
            xs = (f.get(ns, {}).get(tag, {}).get("units", {}) or {}).get(unit, [])
            ser = [{"end": x.get("end"), "start": x.get("start"), "val": x.get("val"), "filed": x.get("filed"), "form": x.get("form"),
                    "accn": x.get("accn")} for x in xs if (x.get("end") or "9") >= cut]
            if ser: out["_tags"][name] = tag; break
        out[name] = ser
    db.kv_set(k, out)
    return out

def from_basic(f):
    """기존 facts:{t}(shares·cash·opcf·warrants·convertible·public_float) → 확장 형식."""
    o = {n: [] for n in FX}
    for a, b in (("shares", "shares"), ("cash", "cash"), ("opcf", "opcf"), ("warrants", "warrants"), ("convertible", "convertible"), ("float", "public_float")):
        o[a] = list(f.get(b) or [])
    o["_tags"] = {"_basic": True}
    return o

def pick(ser, asof, kind="inst", maxage=500):
    """접수일 ≤ asof 인 값 중 기간 끝이 가장 최근인 것. kind: inst(시점) · dur(기간, 가장 긴)."""
    a = str(asof)[:10]
    xs = [x for x in ser or [] if x.get("filed") and x["filed"] <= a and x.get("val") is not None and x.get("end")]
    xs = [x for x in xs if not x.get("start")] if kind == "inst" else [x for x in xs if x.get("start")]
    if not xs: return None
    e = max(x["end"] for x in xs)
    if maxage and (_d(a) - _d(e)).days > maxage: return None
    c = [x for x in xs if x["end"] == e]
    if kind != "inst": c = [max(c, key=lambda x: ((_d(x["end"]) - _d(x["start"])).days, x["filed"]))]
    x = max(c, key=lambda x: x["filed"])
    return dict(x, months=((_d(x["end"]) - _d(x["start"])).days / 30.4) if x.get("start") else None)

def fy_losses(ser, asof, n=5):
    """최근 회계연도 순이익 목록 (최신 먼저)."""
    a = str(asof)[:10]
    xs = [x for x in ser or [] if x.get("filed") and x["filed"] <= a and x.get("start") and x.get("val") is not None
          and 330 <= (_d(x["end"]) - _d(x["start"])).days <= 400]
    by = {}
    for x in sorted(xs, key=lambda x: x["filed"]): by[x["end"]] = x
    return [by[e] for e in sorted(by, reverse=True)[:n]]

# ---------------------------------------------------------------- 2. 원문 해석 (접수번호별 영구 캐시)
RX = {
    "atm": r"at[- ]the[- ]market (?:offering|issuance|sales?)|equity distribution agreement|open market sale agreement",
    "eloc": r"committed equity (?:facility|financing)|equity line of credit|\bELOC\b|equity purchase (?:agreement|facility)",
    "resale": r"selling (?:stock|share)holders?|resale (?:by|of)",
    "resale_only": r"will not receive any (?:of the )?proceeds from the (?:sale|resale)",
    "lowvwap": r"lowest (?:daily |single[- ]day )?(?:VWAP|volume[- ]weighted average price|closing (?:bid )?price|trading price)",
    "ratchet": r"full[- ]ratchet|price[- ]protection|price[- ]based anti-?dilution",
    "reset": r"\breset\b[^.]{0,60}(?:exercise|conversion) price|(?:exercise|conversion) price[^.]{0,60}\breset\b",
    "mfn": r"most[- ]favou?red[- ]nation",
    "altcash": r"alternat(?:e|ive) cashless",
    "cap1999": r"19\.99\s?%|exchange cap|Rule 5635",
    "default": r"event of default[^.]{0,80}(?:120|125|130|150)\s?%",
}
CAT = [   # 촉매 법적 강도 (원문 기준) — A 구속력 · B 확정 절차 · C 근거 약함
    ("A", r"FDA (?:has )?approv|approval (?:from|by) the (?:U\.S\. )?(?:FDA|Food and Drug)|definitive (?:merger|acquisition|business combination) agreement|agreement and plan of merger|tender offer|completion of (?:the )?(?:merger|acquisition)"),
    ("B", r"PDUFA|accepted for (?:filing|review)|stockholders? approved|shareholders? approved|debt (?:restructuring|exchange) agreement"),
    ("C", r"letter of intent|non-?binding|memorandum of understanding|\bMOU\b|(?<!previous )(?<!prior )(?<!all )term sheet|strategic alternatives|exploring (?:a )?potential (?:sale|merger)"),
]

def _parse_more(t):
    o = {}
    head = t[:250_000]
    for k, p in RX.items():
        o[k] = bool(re.search(p, head, re.I))
    m = re.search(r"aggregate (?:gross )?(?:offering|sales) price of up to \$\s?([\d,.]+)\s*(million|billion)?", head, re.I) or \
        re.search(r"having an aggregate offering price of (?:up to )?\$\s?([\d,.]+)\s*(million|billion)?", head, re.I)
    if m: o["atm_amt"] = _money(m.group(1), m.group(2))
    m = re.search(r"(?:purchase|buy)\s+(?:from (?:us|the Company)\s+)?(?:up to\s+)?(?:an aggregate of\s+)?\$\s?([\d,.]+)\s*(million|billion)?\s+(?:of|in)\s+(?:our |the Company.s )?(?:shares|common stock|ordinary shares)", head, re.I)
    if m: o["commit"] = _money(m.group(1), m.group(2))
    m = re.search(r"(?:up to|an aggregate of|offering)\s+([\d,]{5,})\s+(?:shares|ordinary shares)[^.]{0,220}selling (?:stock|share)holder", head, re.I)
    if m: o["resale_sh"] = _num(m.group(1))
    m = re.search(r"conversion price (?:of|equal to|is)\s+\$\s?(\d+(?:\.\d+)?)", head, re.I)
    if m: o["conv_px"] = _num(m.group(1))
    w = [_num(x) for x in re.findall(r"warrants? to purchase (?:up to )?(?:an aggregate of )?([\d,]{5,}) (?:shares|ordinary shares)", head, re.I)]
    w = [x for x in w if x]
    if w: o["warr_sh"] = max(w)
    m = re.search(r"lock-?up[^.]{0,200}?(\d{2,3})\s*(?:-|\s)?days|(\d{2,3})\s*(?:-|\s)?days?[^.]{0,120}lock-?up", head, re.I)
    if m:
        v = int(m.group(1) or m.group(2))
        if 30 <= v <= 400: o["lockup_d"] = v
    o["withdraw"] = bool(re.search(r"requests? (?:the )?withdrawal|consent to the withdrawal", t[:20000], re.I))
    ch = t[:60_000]   # 촉매는 본문 앞부분만 (첨부 경력 소개 등 잡음 제외)
    for g, p in CAT:
        m = re.search(p, ch, re.I)
        if m:
            o["cat"] = g; o["cat_hit"] = re.sub(r"\s+", " ", ch[max(0, m.start() - 60): m.end() + 60]).strip()[:170]; break
    return o

def doc(cik, row, fetch=True):
    """원문 1건 해석: offering._parse (공모가·워런트 행사가·최대 금액·상장 미달) + 추가 규칙. kv secdoc:{acc}."""
    k = f"secdoc:{row['acc']}"
    c = db.kv_get(k)
    if c is not None or not fetch: return c
    from . import offering as OF
    t = OF._text(cik, row["acc"], row.get("primary") or "", extra=r"ex-?99|ex-?10|ex-?4|filing.?fees|ex-?107")
    if not t: return None
    o = OF._parse(t); o.update(_parse_more(t)); o["ok"] = True; o["len"] = len(t)
    if o.get("eloc") or o.get("resale"):
        try:
            from . import finance as FZ
            tm = FZ.parse_terms(t) or {}
            if tm.get("shares") and not o.get("resale_sh"): o["resale_sh"] = tm["shares"]
            if tm.get("commit") and not o.get("commit"): o["commit"] = tm["commit"]
            if tm.get("pct"): o["eloc_pct"] = tm["pct"]
        except Exception: pass
    o = _js(o)
    db.kv_set(k, o)
    return o

REG_BASE = {"S-1", "F-1", "S-3", "F-3", "S-1/A", "F-1/A", "S-3/A", "F-3/A", "S-3ASR", "F-3ASR", "POS AM"}
PROS = {"424B1", "424B2", "424B3", "424B4", "424B5", "424B7"}

def doc_plan(rows, today=None, max_n=30):
    """원문을 받을 공시 고르기: 최근 셸프·신고서(3년, 파일 번호별 최신), 투자설명서(18개월), 주요 8-K/6-K(120일), 철회(RW)."""
    today = pd.Timestamp(today or dt.date.today())
    c3, c18, c4 = [(today - pd.Timedelta(days=d)).strftime("%Y-%m-%d") for d in (1100, 550, 120)]
    P, seen = [], set()
    for r in rows:   # 최신 먼저
        f = r["form"]
        if f in REG_BASE and r["filed"] >= c3:
            key = (r.get("fn") or r["acc"])
            if key in seen: continue
            seen.add(key); P.append(r)
    P = P[:8]
    c12 = (today - pd.Timedelta(days=365)).strftime("%Y-%m-%d")
    P += [r for r in rows if r["form"] == "8-K" and "3.01" in (r.get("items") or "") and r["filed"] >= c12][:4]   # 상장 유지 통지 (1년)
    P += [r for r in rows if r["form"] in PROS and r["filed"] >= c18][:10]
    P += [r for r in rows if r["form"] in ("8-K", "6-K") and r["filed"] >= c4
          and r not in P and (r["form"] == "6-K" or re.search(r"1\.01|2\.01|3\.01|3\.02|7\.01|8\.01|2\.03", r.get("items") or ""))][:10]
    P += [r for r in rows if r["form"] == "RW" and r["filed"] >= c3][:3]
    return P[:max_n]

# ---------------------------------------------------------------- 3. 시점 기준 특징 (백테스트와 같은 함수)
def _streak(c, f):
    n = 0
    for v in reversed(c):
        if f(v): n += 1
        else: break
    return n

def pit(rows, fx, px, asof, info=None, mcap=None):
    """공시 목록(form, filed, items) + XBRL + 일봉 → 특징 dict. asof 접수분·asof 종가까지만 씀 (진입은 다음날 시가)."""
    a = str(asof)[:10]; A = pd.Timestamp(a)
    R = [r for r in rows if (r.get("filed") or "9") <= a]
    days = lambda r: (A - pd.Timestamp(r["filed"])).days
    F = {"asof": a}
    g = px[px["date"] <= A] if px is not None and len(px) else None
    if g is not None and len(g) >= 5:
        c = g["close"].values.astype(float); v = g["volume"].values.astype(float)
        F["price"] = float(c[-1]); F["px_date"] = str(pd.Timestamp(g["date"].iloc[-1]).date())
        F["dv20"] = float(np.median((c * v)[-20:])); F["vol20"] = float(np.mean(v[-20:]))
        F["lo20"] = float(g["low"].values[-20:].min()); F["hi60"] = float(g["high"].values[-60:].max())
        F["below1"] = _streak(c, lambda x: x < 1); F["le10"] = _streak(c, lambda x: x <= 0.10)
        F["max60"] = float(c[-60:].max()); F["avg30"] = float(c[-30:].mean())
        F["chg20"] = float(c[-1] / c[-21] - 1) if len(c) > 21 else None
    else:
        F["price"] = None; F["px_date"] = None
    P = F["price"]
    s = pick(fx.get("shares"), a, maxage=500); F["shares"] = _f(s["val"]) if s else None; F["shares_src"] = s
    s1 = pick(fx.get("shares"), (A - pd.Timedelta(days=365)).strftime("%Y-%m-%d"), maxage=500)
    F["shgrow"] = (F["shares"] / s1["val"] - 1) if (s1 and F["shares"] and s1["val"]) else None
    for k in ("authorized", "cash", "restricted", "equity", "debt_cur", "convertible", "warrants", "warr_ex", "options", "opt_px", "rsu", "pref_out", "antidil", "conv_px", "float"):
        x = pick(fx.get(k), a, maxage=550 if k != "float" else 420)
        F[k] = _f(x["val"]) if x else None; F[k + "_src"] = x
    o = pick(fx.get("opcf"), a, kind="dur", maxage=500)
    F["burn_m"] = (-o["val"] / o["months"]) if (o and o["val"] is not None and o["val"] < 0 and o.get("months")) else (0.0 if o else None)
    F["opcf_src"] = o
    F["runway_m"] = (F["cash"] / F["burn_m"]) if (F["cash"] is not None and F["burn_m"]) else (99.0 if (F["cash"] is not None and F["burn_m"] == 0) else None)
    fl = fy_losses(fx.get("ni"), a); F["ni_fy"] = [_f(x["val"]) for x in fl]; F["ni_src"] = fl[0] if fl else None
    F["mcap"] = (F["shares"] * P) if (F["shares"] and P) else (_f(mcap) if mcap else None)
    fs = _f((info or {}).get("floatShares"))
    if fs and P and F.get("max60"):
        F["float_usd"] = min(fs, F["shares"] or fs) * F["max60"]; F["float_src"] = "시세 유통주식 × 60일 최고 종가"
    elif F["float"]:
        F["float_usd"] = F["float"]; F["float_src"] = "10-K 표지 유통 시총"
    else:
        F["float_usd"] = None; F["float_src"] = None
    cnt = lambda pat, d, field="form": [r for r in R if days(r) <= d and re.search(pat, r.get(field) or "")]
    F["n424_30"] = len(cnt(r"^424B[1-57]$", 30)); F["n424_365"] = len(cnt(r"^424B[1-57]$", 365))
    F["n424b5_365"] = len(cnt(r"^424B5$", 365))
    shelf = [r for r in R if r["form"] in ("S-3", "F-3", "S-3ASR", "F-3ASR") and days(r) <= 1095]
    F["shelf_n"] = len(shelf); F["shelf_last"] = shelf[0]["filed"] if shelf else None
    pend = None   # 가격 미정 신고서(S-1/F-1) — 뒤에 424B1/B4/B3·RW 가 없으면 대기
    for r in R:
        if r["form"] in ("S-1", "F-1", "S-1/A", "F-1/A") and days(r) <= 180:
            later = [x for x in R if x["filed"] >= r["filed"] and x["form"] in ("424B1", "424B4", "RW", "424B3")]
            if not later: pend = r
            break
    F["s1_pending"] = pend["filed"] if pend else None
    F["eff_30"] = len(cnt(r"^EFFECT$", 30))
    F["def301"] = [r["filed"] for r in cnt(r"3\.01", 365, "items")]
    F["nt_365"] = len(cnt(r"^NT ", 365)); F["i402"] = len(cnt(r"4\.02", 365, "items")); F["i401"] = len(cnt(r"4\.01", 365, "items"))
    F["f4_90"] = len(cnt(r"^4$", 90)); F["f144_90"] = [r["filed"] for r in cnt(r"^144$", 90)]
    F["d13_365"] = [r["filed"] for r in cnt(r"13D", 365)]; F["g13_365"] = len(cnt(r"13G", 365))
    F["i302"] = [r["filed"] for r in cnt(r"3\.02", 365, "items")]
    F["pr_90"] = len(cnt(r"7\.01|8\.01", 90, "items")); F["i101_90"] = len(cnt(r"1\.01", 90, "items")); F["i201_90"] = len(cnt(r"2\.01", 90, "items"))
    F["proxy_90"] = len(cnt(r"^(DEF|PRE) 14[AC]$", 90))
    per = [r for r in R if r["form"] in ("10-Q", "10-K", "20-F", "40-F", "10-K/A", "10-Q/A", "20-F/A")]
    F["per_last"] = per[0]["filed"] if per else None; F["per_form"] = per[0]["form"] if per else None
    fpi = any(r["form"] in ("20-F", "6-K", "40-F") for r in R if days(r) <= 730)
    F["fpi"] = fpi
    F["per_late"] = (days(per[0]) > (400 if fpi else 140)) if per else None
    F["n_rows"] = len(R)
    return F

# ---------------------------------------------------------------- 4. 점수 (9항목 /100 — 높을수록 구조 위험이 덜함)
def _cl(v, lo, hi): return max(lo, min(hi, v))

def score(F, D=None):
    """F: pit() 특징, D: 원문 해석 요약(없으면 None — 백테스트도 같은 함수). 반환 dict(items, total, grade)."""
    D = D or {}
    it = []
    keys = ["price", "shares", "cash", "burn_m", "equity", "authorized", "warrants", "per_last", "mcap", "float_usd"]
    ok = sum(1 for k in keys if F.get(k) is not None)
    it.append(("evidence", "근거 품질 (핵심 숫자 확인 비율)", 10, round(10 * ok / len(keys)), f"{ok}/{len(keys)}개 확인"))
    s, why = 10, []
    if F.get("per_late"): s -= 4; why.append("정기 보고서 늦음")
    if F.get("nt_365"): s -= 2; why.append(f"지연 통지(NT) {F['nt_365']}건")
    if F.get("i402"): s -= 4; why.append("재무제표 신뢰 철회(4.02)")
    if F.get("i401"): s -= 2; why.append("감사인 변경(4.01)")
    if F.get("per_last") is None: s -= 4; why.append("정기 보고서 없음")
    it.append(("clarity", "공시 명확성", 10, _cl(s, 0, 10), ", ".join(why) or "문제 없음"))
    s, why = 20, []
    fdr = D.get("fd_ratio")
    if fdr is None and F.get("shares"):
        extra = sum(F.get(k) or 0 for k in ("warrants", "options", "rsu"))
        fdr = 1 + extra / F["shares"] if extra else None
    if fdr is not None:
        if fdr >= 2: s -= 8; why.append(f"완전희석 {fdr:.1f}배")
        elif fdr >= 1.5: s -= 5; why.append(f"완전희석 {fdr:.1f}배")
        elif fdr >= 1.2: s -= 2; why.append(f"완전희석 {fdr:.2f}배")
    if F.get("s1_pending"): s -= 4; why.append("가격 미정 공모 신고서 대기")
    if F.get("n424_30"): s -= 3; why.append(f"최근 30일 투자설명서 {F['n424_30']}건")
    if D.get("atm_active") or (D.get("atm_active") is None and F.get("n424b5_365", 0) >= 1 and F.get("shelf_n")): s -= 3; why.append("ATM/셸프 발행 흔적")
    if D.get("eloc_active"): s -= 3; why.append("ELOC")
    if D.get("toxic"): s -= 4; why.append("위험 조항(" + ", ".join(D["toxic"][:2]) + ")")
    sg = F.get("shgrow")
    if sg is not None and sg >= 0.5: s -= 3; why.append(f"1년 주식수 {sg * 100:+.0f}%")
    it.append(("dilution", "희석·오버행 위험", 20, _cl(s, 0, 20), ", ".join(why) or "큰 희석 요인 확인 안 됨"))
    rw = F.get("runway_m")
    s = 3 if rw is None else (10 if rw >= 24 else 7 if rw >= 12 else 4 if rw >= 6 else 1)
    why = ["런웨이 " + ("확인되지 않음" if rw is None else ("소모 없음" if rw >= 99 else f"{rw:.0f}개월"))]
    if F.get("equity") is not None and F["equity"] < 0: s -= 2; why.append("자본 잠식")
    if F.get("def301"): s -= 3; why.append("상장 유지 미달 통지")
    it.append(("balance", "재무·현금 런웨이", 10, _cl(s, 0, 10), ", ".join(why)))
    cg = D.get("cat")
    if cg is None: cg = "C" if (F.get("i101_90") or F.get("i201_90")) else None
    s = {"A": 15, "B": 11, "C": 6}.get(cg, 2)
    it.append(("catalyst", "촉매 법적 강도", 15, s, f"{cg}급" if cg else "확인된 구속력 있는 촉매 없음 (D급)"))
    dv = F.get("dv20")
    s = 1 if dv is None else (10 if dv >= 5e6 else 7 if dv >= 1e6 else 4 if dv >= 2e5 else 1)
    why = [f"20일 거래대금 중앙값 {usd(dv)}"]
    if (D.get("vp_above") or 0) >= 70: s -= 2; why.append(f"위 매물대 {D['vp_above']:.0f}%")
    it.append(("market", "시장 구조·유동성", 10, _cl(s, 0, 10), ", ".join(why)))
    s, why = 5, []
    if D.get("ins_buy"): s += 3; why.append(f"내부자 장내 매수 {D['ins_buy']}건")
    if D.get("ins_sell"): s -= 2; why.append(f"내부자 매도 {D['ins_sell']}건")
    if len(F.get("f144_90") or []) >= 2: s -= 1; why.append(f"144 매도 예고 {len(F['f144_90'])}건")
    if F.get("d13_365"): s += 1; why.append("13D(경영 참여 목적) 신고")
    if F.get("proxy_90") and F.get("price") is not None and F["price"] < 1: s -= 2; why.append("$1 미만 + 주총 안건 (역분할 가능성)")
    it.append(("motive", "내부자·대주주 동기", 10, _cl(s, 0, 10), ", ".join(why) or "뚜렷한 움직임 확인 안 됨"))
    s = 2 + (3 if D.get("strikes") else 0) + (3 if D.get("vp_zone") else 0) + (2 if F.get("lo20") else 0)
    it.append(("pricemap", "가격 지도·무효화 조건 명확성", 10, _cl(s, 0, 10), "행사가·공모가 " + ("있음" if D.get("strikes") else "확인 안 됨") + " · 매물대 " + ("있음" if D.get("vp_zone") else "확인 안 됨")))
    m = F.get("mcap"); c = F.get("cash")
    if m and c is not None:
        r = c / m; s = 5 if r >= 1 else 3 if r >= 0.5 else 2 if r >= 0.2 else 0; w = f"현금/시총 {r:.2f}"
    else: s, w = 1, "현금 또는 시총 확인되지 않음"
    it.append(("downside", "하방 쿠션 (현금/시총)", 5, s, w))
    total = int(sum(x[3] for x in it))
    grade = "A" if total >= 85 else "B" if total >= 70 else "C" if total >= 55 else "D"
    return dict(items=[dict(k=a, label=b, max=c, pts=int(d), why=e) for a, b, c, d, e in it], total=total, grade=grade)

# ---------------------------------------------------------------- 5. 전체 퀵스캔
def _src(form, filed, url=None): return dict(form=form, filed=filed, url=url)

def _url(cik, acc): return f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{acc}-index.htm"

def _xsrc(x, cik):
    if not x: return None
    acc = x.get("accn")
    u = _url(cik, acc) if (acc and cik) else (f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}" if cik else None)
    return _src(f"{x.get('form') or 'XBRL'} (기준 {x.get('end')})", x.get("filed"), u)

def _conf_x(x, asof):
    if not x: return "D"
    age = (_d(asof) - _d(x.get("filed"))).days
    return "A" if age <= 120 else "B" if age <= 400 else "C"

JURIS = {"DE": "델라웨어", "NV": "네바다", "WY": "와이오밍", "E9": "케이맨 제도", "D8": "영국령 버진아일랜드", "D0": "버뮤다", "L3": "이스라엘", "A0": "캐나다(앨버타)",
         "A1": "캐나다(BC)", "A6": "캐나다(온타리오)", "A8": "캐나다(퀘벡)", "F4": "중국", "K3": "홍콩", "U0": "싱가포르", "X0": "영국", "C3": "호주", "FL": "플로리다", "CO": "콜로라도", "NY": "뉴욕"}
JURIS_NOTE = {"NV": "네바다 설립: 이사회가 주총 없이 역분할·수권주식 조정을 할 수 있는 범위가 넓은 편 (정관 확인 필요)",
              "WY": "와이오밍 설립: 이사회 권한이 넓은 편 (정관 확인 필요)",
              "DE": "델라웨어 설립: 수권주식 증가·역분할에 보통 주주 승인 필요"}

def build(t, fetch=True, budget_docs=24, asof=None, save=True):
    """티커 1개 퀵스캔 → 스냅샷 dict (kv secsnap:{t} 에 저장, 이전 스냅샷과 비교용)."""
    from . import structure as ST, finance as FZ, events as EV, sources as src
    t = t.upper().strip()
    T0 = time.time()
    S = {"ticker": t, "ts": dt.datetime.now().isoformat(timespec="seconds"), "v": 1}
    sub = subm(t, fetch=fetch) or {"cik": None, "rows": [], "meta": {}}
    cik, rows, meta = sub.get("cik"), sub.get("rows") or [], sub.get("meta") or {}
    S["err"] = sub.get("err")
    px = db.q("SELECT date, open, high, low, close, volume FROM prices WHERE ticker=? AND date>=? ORDER BY date",
              (t, (dt.date.today() - dt.timedelta(days=420)).isoformat()))
    if fetch and len(px) < 20:
        try:
            src.fetch_prices(t, "1y")
            px = db.q("SELECT date, open, high, low, close, volume FROM prices WHERE ticker=? AND date>=? ORDER BY date",
                      (t, (dt.date.today() - dt.timedelta(days=420)).isoformat()))
        except Exception: pass
    if len(px):
        px["date"] = pd.to_datetime(px["date"]); px = px[px.close > 0].reset_index(drop=True)
    info = db.kv_get(f"info:{t}") or {}
    if fetch and not info:
        try: info = src.fetch_info(t) or {}
        except Exception: info = {}
    uni = db.q("SELECT name, exchange, mcap FROM universe WHERE ticker=?", (t,))
    uname = uni.name.iloc[0] if len(uni) else None
    exch = (uni.exchange.iloc[0] if len(uni) else None) or ((meta.get("exchanges") or [None])[0])
    fx = (facts_ext(t, fetch=fetch) if cik else {}) or {}
    asof = asof or (str(px.date.iloc[-1].date()) if len(px) else dt.date.today().isoformat())
    F = pit(rows, fx, px if len(px) else None, asof, info=info, mcap=(uni.mcap.iloc[0] if len(uni) else None))
    P = F.get("price")
    # --- 원문
    docs, nnew = [], 0
    for r in doc_plan(rows):
        d = db.kv_get(f"secdoc:{r['acc']}")
        if d is None and fetch and cik and nnew < budget_docs:
            try: d = doc(cik, r); nnew += 1
            except Exception: d = None
        docs.append(dict(r, d=d, url=_url(cik, r["acc"]) if cik else None))
    S["docs_seen"] = sum(1 for x in docs if x["d"]); S["docs_planned"] = len(docs); S["docs_new"] = nnew
    try: fd = EV.scan(t, fetch=fetch, max_new=6) if cik else None
    except Exception: fd = None
    lt = EV.latest(fd, asof) if fd else {}
    # --- 1) 신원
    name = meta.get("name") or uname or info.get("longName") or info.get("shortName")
    adr = bool(re.search(r"american depositary|\bADS\b|\bADR\b", f"{uname or ''} {info.get('longName') or ''} {info.get('quoteType') or ''}", re.I))
    itype = "ADR(예탁증서)" if adr else ("외국 기업(FPI · 20-F/6-K)" if F.get("fpi") else ("보통주 (미국 보고 기업)" if rows else NA))
    st_ = (meta.get("state") or "").strip()
    S["ident"] = dict(name=name, cik=cik, exchange=exch or NA, type=itype, juris=JURIS.get(st_, meta.get("stateDesc") or (st_ or NA)), juris_note=JURIS_NOTE.get(st_),
                      sic=meta.get("sicDesc"), category=meta.get("category") or NA, former=meta.get("former") or [], fye=meta.get("fye"), hq=meta.get("hq"))
    S["asof"] = dict(price=F.get("px_date") or NA, filing=(rows[0]["filed"] if rows else NA), periodic=f"{F.get('per_form') or ''} {F.get('per_last') or NA}".strip(),
                     built=S["ts"], sec_list=sub.get("ts"))
    # --- 2) 증거 장부
    EVL = []
    def E(key, label, val, num=None, src_=None, conf="C", state="ok", note=None):
        EVL.append(dict(k=key, label=label, val=val, num=_f(num), src=src_, conf=conf if state == "ok" else "D", state=state, note=note))
    out_n, out_src, out_conf = F.get("shares"), _xsrc(F.get("shares_src"), cik), _conf_x(F.get("shares_src"), asof)
    lsh = (lt or {}).get("shares")
    if lsh and lsh.get("n") and (not F.get("shares_src") or str(lsh.get("date")) > str(F["shares_src"].get("end"))):
        out_n = float(lsh["n"]); out_src = _src(f"{lsh.get('src')} (기준 {lsh.get('date')})", lsh.get("date"), lsh.get("url")); out_conf = "A"
    if out_n is None and info.get("sharesOutstanding"):
        out_n = float(info["sharesOutstanding"]); out_src = _src("시세 정보(야후)", F.get("px_date")); out_conf = "C"
    if out_n and P and out_n != F.get("shares"):
        F["shares"] = out_n; F["mcap"] = out_n * P
    E("out", "이미 발행된 주식", shs(out_n), out_n, out_src, out_conf, "ok" if out_n else "unk")
    warr, wex = F.get("warrants"), F.get("warr_ex")
    dw = [x for x in docs if x["d"] and x["form"] in PROS | REG_BASE]
    doc_ex = sorted({e for x in dw for e in (x["d"].get("warrant_ex") or []) if e})
    doc_wsh = max([x["d"].get("warr_sh") or 0 for x in dw] or [0]) or None
    wsrc_, wconf = _xsrc(F.get("warrants_src"), cik), _conf_x(F.get("warrants_src"), asof)
    if warr is None and doc_wsh:
        warr = doc_wsh; w0 = next(x for x in dw if (x["d"].get("warr_sh") or 0) == doc_wsh)
        wsrc_ = _src(f"{w0['form']} (발행 시점 수량 — 이후 행사분 미반영)", w0["filed"], w0["url"]); wconf = "C"
    ex_list = sorted({x for x in ([wex] if wex else []) + doc_ex if x})
    itm = otm = None; wl = NA
    if warr is not None and P:
        if not warr: itm = otm = 0.0; wl = NONE
        elif ex_list:
            if max(ex_list) <= P: itm, otm = warr, 0.0; wl = "행사가 ≤ 현재가 → 지금 행사 가능(ITM)"
            elif min(ex_list) > P: itm, otm = 0.0, warr; wl = "행사가 > 현재가 → 잠재 물량(OTM)"
            else: wl = "행사가가 여러 개 (일부만 ITM) — 종류별 수량 확인되지 않음 → 조건부로 봄"; itm, otm = 0.0, warr
        else:
            wl = "행사가 확인되지 않음 → 조건부로 봄"; itm, otm = 0.0, warr
    E("warr", "워런트 잔량", shs(warr) if warr is not None else NA, warr, wsrc_, wconf, "ok" if warr is not None else "unk",
      note=wl + (f" · 행사가 {', '.join(pxs(x) for x in ex_list[:4])}" if ex_list else ""))
    opts, rsu = F.get("options"), F.get("rsu")
    E("opt", "스톡옵션 잔량", shs(opts), opts, _xsrc(F.get("options_src"), cik), _conf_x(F.get("options_src"), asof), "ok" if opts is not None else "unk",
      note=f"가중평균 행사가 {pxs(F.get('opt_px'))}" if F.get("opt_px") else None)
    E("rsu", "RSU(미확정 주식 보상)", shs(rsu), rsu, _xsrc(F.get("rsu_src"), cik), _conf_x(F.get("rsu_src"), asof), "ok" if rsu is not None else "unk")
    conv = F.get("convertible")
    cpx = F.get("conv_px") or next((x["d"].get("conv_px") for x in docs if x["d"] and x["d"].get("conv_px")), None)
    conv_sh = (conv / cpx) if (conv and cpx) else None
    E("conv", "전환사채 잔액", usd(conv), conv, _xsrc(F.get("convertible_src"), cik), _conf_x(F.get("convertible_src"), asof), "ok" if conv is not None else "unk",
      note=((f"전환가 {pxs(cpx)} → 약 {shs(conv_sh)}" if conv_sh else "전환가 확인되지 않음 → 주식 수 환산 불가") if conv else None))
    pref = F.get("pref_out")
    E("pref", "우선주 잔량", shs(pref), pref, _xsrc(F.get("pref_out_src"), cik), _conf_x(F.get("pref_out_src"), asof), "ok" if pref is not None else "unk",
      note="전환 비율 확인되지 않음" if pref else None)
    auth = F.get("authorized")
    E("auth", "정관상 발행 한도(수권주식)", shs(auth), auth, _xsrc(F.get("authorized_src"), cik), _conf_x(F.get("authorized_src"), asof), "ok" if auth else "unk")
    # --- 발행 수단 (원문)
    inst = []
    effs = [r for r in rows if r["form"] == "EFFECT"]
    def eff_of(r):
        e = [x for x in effs if x["filed"] >= r["filed"] and r.get("fn") and x.get("fn") == r.get("fn")]
        return e[-1]["filed"] if e else None
    def rw_of(r):
        return any(x["form"] == "RW" and x["filed"] >= r["filed"] and r.get("fn") and x.get("fn") == r.get("fn") for x in rows)
    used_12, used_src = 0.0, []
    for x in docs:
        d = x["d"]
        if x["form"] in ("424B5", "424B4", "424B1") and d and (_d(asof) - _d(x["filed"])).days <= 365 and not d.get("atm"):
            g = d.get("gross") or (((d.get("offer_price") or 0) * (d.get("shares_offered") or 0)) or None)
            if g: used_12 += g; used_src.append(f"{x['form']} {x['filed']} {usd(g)}")
    shelf_cap, resale_sh, gone = 0.0, 0.0, []
    for x in docs:
        d, f = x["d"], x["form"]
        if f in REG_BASE:
            age = (_d(asof) - _d(x["filed"])).days
            eff = x["filed"] if f.endswith("ASR") else eff_of(x)
            wd = rw_of(x) or bool(d and d.get("withdraw"))
            kind = "셸프" if f.startswith(("S-3", "F-3")) else "공모/재판매 신고서"
            if d and d.get("eloc"): kind = "ELOC 재판매 등록"
            elif d and d.get("resale_only") and not d.get("max_amount"): kind = "재판매 등록"
            amt = (d or {}).get("max_amount")
            state = "철회" if wd else ("만료(3년 경과)" if (kind == "셸프" and age > 1095) else (f"효력 {eff}" if eff else "효력 대기"))
            item = dict(kind=kind, form=f, filed=x["filed"], fn=x.get("fn"), url=x["url"], amt=amt, eff=eff, state=state,
                        label=f"{kind}: {state}" + (f" · 등록 한도 {usd(amt)}" if amt else "") + ("" if d else " · 원문 못 읽음"),
                        resale_sh=(d or {}).get("resale_sh"), commit=(d or {}).get("commit"), parsed=bool(d))
            if wd or "만료" in state: gone.append(item)
            else:
                if kind == "셸프" and amt: shelf_cap = max(shelf_cap, amt)
                if "재판매" in kind and item["resale_sh"]: resale_sh += item["resale_sh"]
                if kind == "ELOC 재판매 등록" and item.get("resale_sh"): item["label"] += f" · 재판매 {shs(item['resale_sh'])}"
            inst.append(item)
        elif f in PROS and d:
            if d.get("atm"):
                inst.append(dict(kind="ATM(시장가 분할 매도)", form=f, filed=x["filed"], fn=x.get("fn"), url=x["url"], amt=d.get("atm_amt"), state="사용 가능(셸프 효력 전제)",
                                 label=f"ATM 한도 {usd(d.get('atm_amt'))} · 사용액은 이후 10-Q 확인", parsed=True))
            elif d.get("resale_only") and not d.get("offer_price") and not d.get("atm"):
                if d.get("resale_sh"): resale_sh += d["resale_sh"]
                inst.append(dict(kind="재판매 투자설명서", form=f, filed=x["filed"], url=x["url"], resale_sh=d.get("resale_sh"), state="등록됨",
                                 label=f"재판매 {shs(d.get('resale_sh'))}", parsed=True))
            elif d.get("offer_price") or d.get("gross"):
                inst.append(dict(kind="가격 확정 공모", form=f, filed=x["filed"], url=x["url"], amt=d.get("gross"), px=d.get("offer_price"), state="완료",
                                 label=f"공모가 {pxs(d.get('offer_price'))} · 총액 {usd(d.get('gross'))}" + (" · 베스트 에포트" if d.get("best_efforts") else ""),
                                 parsed=True, lockup=d.get("lockup_d")))
        elif f in ("8-K", "6-K") and d and d.get("eloc"):
            inst.append(dict(kind="ELOC 계약", form=f, filed=x["filed"], url=x["url"], amt=d.get("commit"), state="계약 공시", label=f"ELOC 약정 {usd(d.get('commit'))}", parsed=True))
    atm = [i for i in inst if i["kind"].startswith("ATM")]
    eloc = [i for i in inst if "ELOC" in i["kind"] and i.get("state") != "철회"]
    atm_rem = (atm[0].get("amt") or 0) if atm else 0      # 최근 ATM 한도 (사용액 차감 전 = 최대치)
    eloc_rem = max([(i.get("amt") or i.get("commit") or 0) for i in eloc] or [0])
    toxic_map = {"lowvwap": "최저 VWAP·최저가 기준 전환/행사", "ratchet": "가격 하향 조정(래칫·가격 보호)", "reset": "행사·전환가 리셋", "mfn": "최혜 조건(MFN)",
                 "altcash": "대체 무상 행사(alternate cashless)", "default": "부도 시 120%↑ 상환"}
    toxic, toxic_src = [], {}
    for x in docs:
        d = x["d"]
        if not d or (_d(asof) - _d(x["filed"])).days > 550: continue
        for k, lab in toxic_map.items():
            if d.get(k) and lab not in toxic: toxic.append(lab); toxic_src[lab] = _src(x["form"], x["filed"], x["url"])
    cap1999 = next((x for x in docs if x["d"] and x["d"].get("cap1999")), None)
    # --- 장부 7칸 (중복 금지: 재판매 칸은 완전희석에서 제외)
    cv_now = (conv_sh or 0) if (cpx and P and cpx <= P) else 0
    cv_cond = (conv_sh or 0) if (cpx and P and cpx > P) else 0
    B = {"out": dict(sh=out_n, items=[shs(out_n)], src=out_src)}
    B["now"] = dict(sh=(itm + cv_now) if itm is not None else None,
                    items=[x for x in [f"ITM 워런트 {shs(itm)}" if itm else None, f"ITM 전환사채 {shs(cv_now)}" if cv_now else None] if x] or ([NONE] if itm == 0 else [NA]))
    B["cond"] = dict(sh=((otm or 0) + cv_cond) if (otm is not None or cv_cond) else None,
                     items=[x for x in [f"OTM·행사가 미확인 워런트 {shs(otm)}" if otm else None, f"전환사채 {usd(conv)} (전환가 {pxs(cpx)})" if conv else None,
                                        f"우선주 {shs(pref)} (전환 비율 {NA})" if pref else None] if x] or ([NONE] if otm == 0 else [NA]))
    B["resv"] = dict(sh=((opts or 0) + (rsu or 0)) if (opts is not None or rsu is not None) else None, items=[f"옵션 {shs(opts)}", f"RSU {shs(rsu)}"])
    B["resale"] = dict(sh=resale_sh or None, items=[f"{i['kind']} {i['form']} {i['filed']} {shs(i.get('resale_sh'))}" for i in inst if "재판매" in i["kind"]][:4] or
                       [NONE if S["docs_seen"] else NA], note="이미 발행됐거나 워런트 칸에 있는 주식 → 완전희석에 다시 안 더함")
    B["shelf"] = dict(usd=(max(shelf_cap, atm_rem) + eloc_rem) or None, items=[x for x in [f"셸프 등록 {usd(shelf_cap)}" if shelf_cap else None,
                      f"ATM 한도 {usd(atm_rem)} (셸프 안)" if atm_rem else None, f"ELOC 약정 {usd(eloc_rem)}" if eloc_rem else None] if x] or [NONE if S["docs_seen"] else NA])
    B["gone"] = dict(items=[f"{g['form']} {g['filed']} {g['state']}" for g in gone][:5] or [NONE if S["docs_seen"] else NA])
    S["ledger"] = B
    # --- 완전희석 · 베이비 셸프
    room_usd = (max(shelf_cap, atm_rem) + eloc_rem) or None
    fus = F.get("float_usd"); baby = None
    if fus is not None:
        if fus < 75e6:
            cap = fus / 3; left = max(0.0, cap - used_12)
            baby = dict(on=True, float_usd=fus, cap=cap, used=used_12, left=left, src=F.get("float_src"), used_src=used_src)
            if room_usd is not None: room_usd = min(max(shelf_cap, atm_rem), left) + eloc_rem   # ELOC 재판매 등록은 셸프 한도 밖
        else: baby = dict(on=False, float_usd=fus, src=F.get("float_src"))
    shelf_sh = (room_usd / P) if (room_usd and P) else None
    missing = [n for n, ok in (("발행 주식", out_n is not None), ("워런트", warr is not None), ("옵션·RSU", opts is not None or rsu is not None),
                               ("전환사채 전환가", not conv or bool(conv_sh))) if not ok]
    basic = out_n
    prac = (basic + (itm or 0) + (rsu or 0) + cv_now) if basic else None
    mx = (basic + (warr or 0) + (opts or 0) + (rsu or 0) + (conv_sh or 0) + (shelf_sh or 0)) if basic else None
    S["fd"] = dict(basic=basic, practical=prac, max=mx, ratio=(mx / basic) if (mx and basic) else None, shelf_sh=shelf_sh, room_usd=room_usd, missing=missing,
                   note="현실 = 기본 + ITM 워런트 + RSU + ITM 전환 · 최대 = 기본 + 워런트 전부 + 옵션 + RSU + 전환(전환가 확인분) + 셸프·ATM·ELOC 남은 금액 ÷ 현재가 (재판매 등록분 제외)")
    if auth and out_n:
        raw = auth - out_n; ovh = raw - (warr or 0) - (opts or 0) - (rsu or 0) - (conv_sh or 0)
        S["head"] = dict(auth=auth, raw=raw, overhang=ovh, free=ovh - (shelf_sh or 0), ok=True)
    else: S["head"] = dict(auth=auth, ok=False)
    S["baby"] = baby
    # --- Rule 144 · 락업
    unlock = []
    for d302 in F.get("i302") or []:
        mo = 12 if F.get("per_late") else 6
        unlock.append(dict(date=(_d(d302) + pd.DateOffset(months=mo)).strftime("%Y-%m-%d"),
                           what=f"사모 발행(8-K 3.02, {d302}) 주식 Rule 144 매도 가능 추정 ({'보고 지연 → 12개월' if mo == 12 else '보고 기업 6개월'})", src=_src("8-K 3.02", d302)))
    for i in inst:
        if i.get("lockup"):
            unlock.append(dict(date=(_d(i["filed"]) + pd.Timedelta(days=int(i["lockup"]))).strftime("%Y-%m-%d"),
                               what=f"공모({i['form']} {i['filed']}) 락업 {i['lockup']}일 해제 추정", src=_src(i["form"], i["filed"], i.get("url"))))
    aff_lim = max(0.01 * out_n, (F.get("vol20") or 0) * 5) if out_n else None
    S["r144"] = dict(f144=F.get("f144_90") or [], unlock=sorted(unlock, key=lambda x: x["date"]), aff_limit=aff_lim,
                     note="내부자(계열사) 3개월 매도 한도 ≈ 발행 주식 1% 와 최근 4주 주간 평균 거래량 중 큰 값 (추정)")
    # --- 내부자·대주주 (질문으로만)
    f4 = db.kv_get(f"form4:{t}")
    if f4 is None and fetch and cik:
        try: f4 = src.insider_trades(t)
        except Exception: f4 = None
    cut90 = (_d(asof) - pd.Timedelta(days=90)).strftime("%Y-%m-%d")
    buys = [x for x in (f4 or []) if x.get("code") == "P" and not x.get("bad") and str(x.get("filed", "")) >= cut90]
    sells = [x for x in (f4 or []) if x.get("code") == "S" and str(x.get("filed", "")) >= cut90]
    Q = []
    if sells: Q.append(f"내부자 매도 {len(sells)}건(90일) — 미리 정한 매도 계획(10b5-1)인지, 세금용인지, 자금 조달 직전인지? (Form 4 각주)")
    if buys: Q.append(f"내부자 장내 매수 {len(buys)}건 — 매수가({', '.join(pxs(b.get('price')) for b in buys[:3])})보다 지금 가격이 높은가 낮은가?")
    if F.get("f144_90"): Q.append(f"Form 144(매도 예고) {len(F['f144_90'])}건 — 누가, 얼마나 팔 예정인가?")
    if F.get("d13_365"): Q.append(f"13D(경영 참여 목적) {len(F['d13_365'])}건 — 지분 확대·경영 개입 의도는?")
    if F.get("g13_365"): Q.append(f"13G(단순 투자) {F['g13_365']}건 — 공모 참여 투자자 지분 신고인가? (워런트 포함 4.99·9.99% 상한 흔함)")
    if F.get("proxy_90"): Q.append("최근 주총 위임장 — 역분할·수권주식 증가·19.99% 초과 발행 승인 안건이 있는가?")
    if F.get("i302"): Q.append("최근 사모 발행(3.02) — 누구에게 얼마에 팔았고, 언제부터 시장에 팔 수 있는가?")
    S["motive"] = dict(buys=len(buys), sells=len(sells), f4_90=F.get("f4_90"), f144=len(F.get("f144_90") or []), d13=len(F.get("d13_365") or []), g13=F.get("g13_365"),
                       questions=Q, form4_ok=f4 is not None)
    # --- 가격 저항 (행사가·공모가·전환가 + 위 매물대)
    strikes = [dict(px=e, what="워런트 행사가") for e in ex_list]
    strikes += [dict(px=i["px"], what=f"공모가 ({i['form']} {i['filed']})") for i in inst if i.get("px")]
    if cpx: strikes.append(dict(px=cpx, what="전환가"))
    if P: strikes = [s_ for s_ in strikes if 0.3 * P <= s_["px"] <= 5 * P]
    try: vp = FZ.volume_profile(px, 60) if len(px) >= 20 else None
    except Exception: vp = None
    z = (vp or {}).get("zone")
    for s_ in strikes:
        s_["above"] = bool(P and s_["px"] > P)
        s_["double"] = bool(z and z["lo"] * 0.92 <= s_["px"] <= z["hi"] * 1.08)
    S["resist"] = dict(strikes=sorted(strikes, key=lambda x: x["px"]), vp=vp, lo20=F.get("lo20"), hi60=F.get("hi60"),
                       double=[s_ for s_ in strikes if s_["double"] and s_["above"]])
    S["listing"] = listing(exch, F, docs)
    # --- 일정
    cal = []
    try:
        if not F.get("fpi"): cal.append(dict(date=str(ST.next_due(pd.Timestamp(asof)).date()), what="다음 10-Q/10-K 마감 추정 (소형 보고 기업 기준)", kind="filing"))
    except Exception: pass
    cal += [dict(date=u["date"], what=u["what"], kind="supply") for u in S["r144"]["unlock"]]
    for x in docs:
        d = x["d"] or {}
        if d.get("deadline"): cal.append(dict(date=str(d["deadline"])[:10], what=f"상장 유지 회복 기한 ({d.get('def_kind') or '기준'} · {x['form']} {x['filed']})", kind="listing"))
    for w in (fd or {}).get("docs", []):
        m = w.get("rsmeet") or {}
        if m.get("date"): cal.append(dict(date=str(m["date"])[:10], what=f"역분할 안건 주총 ({w['form']} {w['filed']})", kind="meeting"))
    for i in inst:
        if i["kind"] == "셸프" and str(i.get("state", "")).startswith("효력"):
            cal.append(dict(date=(_d(i["filed"]) + pd.Timedelta(days=1095)).strftime("%Y-%m-%d"), what=f"셸프({i['form']} {i['filed']}) 3년 만료", kind="supply"))
        if "재판매" in i["kind"] and i.get("state") == "효력 대기":
            cal.append(dict(date=i["filed"], what=f"{i['kind']} 효력 대기 ({i['form']} {i['filed']} 접수) — 효력 나면 매도 물량", kind="supply"))
    if F.get("s1_pending"): cal.append(dict(date=F["s1_pending"], what="가격 미정 공모 신고서 접수 — 가격 확정·효력 대기", kind="supply"))
    if P and F.get("below1"):
        n = F["below1"]
        cal.append(dict(date=(_d(asof) + pd.offsets.BDay(max(0, 30 - n))).strftime("%Y-%m-%d"),
                        what=(f"$1 미만 {n}거래일째 → 30거래일째 (나스닥 통지 예상일)" if n < 30 else f"$1 미만 {n}거래일 (30일 넘음 — 통지·유예 기간 확인)"), kind="listing"))
    lo = (_d(asof) - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    S["cal"] = sorted([c for c in cal if c["date"] >= lo or c["kind"] == "supply" and "대기" in c["what"]], key=lambda c: c["date"])[:12]
    # --- 점수
    cats = [(x["d"].get("cat"), x) for x in docs if x["d"] and x["d"].get("cat") and x["form"] in ("8-K", "6-K") and (_d(asof) - _d(x["filed"])).days <= 90]
    best = min(c[0] for c in cats) if cats else None
    Dg = dict(fd_ratio=S["fd"]["ratio"], atm_active=(bool(atm) if S["docs_seen"] else None), eloc_active=(bool(eloc) if S["docs_seen"] else None), toxic=toxic, cat=best,
              ins_buy=len(buys), ins_sell=len(sells), strikes=bool(strikes), vp_zone=bool(z), vp_above=(vp or {}).get("above"))
    S["cat"] = [dict(g=g, form=x["form"], filed=x["filed"], url=x["url"], hit=x["d"].get("cat_hit")) for g, x in sorted(cats, key=lambda c: (c[0], c[1]["filed"]))][:4]
    sc = score(F, Dg)
    # --- 증거 장부 나머지
    E("cash", "현금", usd(F.get("cash")), F.get("cash"), _xsrc(F.get("cash_src"), cik), _conf_x(F.get("cash_src"), asof), "ok" if F.get("cash") is not None else "unk")
    lc = (lt or {}).get("cash")
    if lc and F.get("cash_src") and str(lc[0]) > str(F["cash_src"].get("end")):
        E("cash_new", "현금 (더 최근 공시)", usd(lc[1]), lc[1], _src(f"{lc[2]} (기준 {lc[0]})", lc[0], lc[3] if len(lc) > 3 else None), "A")
    E("burn", "월 현금 소모 (영업현금흐름)", usd(F.get("burn_m")), F.get("burn_m"), _xsrc(F.get("opcf_src"), cik), _conf_x(F.get("opcf_src"), asof), "ok" if F.get("burn_m") is not None else "unk")
    rwm = F.get("runway_m")
    E("runway", "현금 런웨이", (f"{rwm:.1f}개월" if rwm is not None and rwm < 99 else ("소모 없음" if rwm else NA)), rwm, _src("계산: 현금 ÷ 월 소모", asof), "C", "ok" if rwm is not None else "unk")
    E("restricted", "제한 현금", usd(F.get("restricted")), F.get("restricted"), _xsrc(F.get("restricted_src"), cik), _conf_x(F.get("restricted_src"), asof), "ok" if F.get("restricted") is not None else "unk")
    E("debt", "단기 부채", usd(F.get("debt_cur")), F.get("debt_cur"), _xsrc(F.get("debt_cur_src"), cik), _conf_x(F.get("debt_cur_src"), asof), "ok" if F.get("debt_cur") is not None else "unk")
    E("equity", "자기자본", usd(F.get("equity")), F.get("equity"), _xsrc(F.get("equity_src"), cik), _conf_x(F.get("equity_src"), asof), "ok" if F.get("equity") is not None else "unk")
    E("mcap", "시가총액", usd(F.get("mcap")), F.get("mcap"), _src("계산: 발행 주식 × 종가", F.get("px_date")), "C", "ok" if F.get("mcap") else "unk")
    E("float", "유통 시총 (베이비 셸프 기준)", usd(fus), fus, _src(F.get("float_src") or NA, F.get("px_date")), "C" if str(F.get("float_src") or "").startswith("시세") else "B", "ok" if fus else "unk")
    cov = sum(1 for e in EVL if e["state"] == "ok") / max(1, len(EVL))
    fresh = bool(F.get("per_last")) and (_d(asof) - _d(F["per_last"])).days <= 120
    sc["conf"] = "A" if (cov >= 0.8 and fresh and S["docs_seen"] >= 3) else "B" if cov >= 0.6 else "C" if cov >= 0.4 else "D"
    sc["cov"] = cov
    S["score"] = sc; S["ev"] = EVL; S["inst"] = inst[:14]; S["F"] = {k: v for k, v in F.items() if not k.endswith("_src")}
    S["toxic"] = [dict(lab=x, src=toxic_src.get(x)) for x in toxic]
    S["cap1999"] = _src(cap1999["form"], cap1999["filed"], cap1999["url"]) if cap1999 else None
    S["scen"], S["exposure"], S["exits"] = scenarios(S, F, P)
    S["gates"] = gates(S, F)
    S["find"] = findings(S, F)
    S["facts"] = facts_summary(S, F)
    S["ask"] = asks(S, F, docs)
    S["secs"] = round(time.time() - T0, 1)
    S = _js(S)
    if save: save_snap(S)
    return S

def listing(exch, F, docs):
    """거래소별 상장 유지 점검 (앱에 저장한 규정 숫자 · 공식 원문 재확인 필요)."""
    e = str(exch or "").upper(); P = F.get("price"); L = []
    def add(rule, state, val, note=None): L.append(dict(rule=rule, state=state, val=val, note=note))
    eq, m, ni = F.get("equity"), F.get("mcap"), (F.get("ni_fy") or [None])[0]
    if e.startswith("NASDAQ"):
        tier = "Nasdaq (등급 확인되지 않음 → Capital Market 최소 기준으로 봄)"
        n = F.get("below1") or 0
        add("최소 주가 $1 (30거래일 연속 미만 → 통지, 180일 회복 기간 · 조건 충족 시 180일 추가 · 1년 내 역분할 이력 있으면 유예 없음)",
            "미달" if n >= 30 else ("주의" if n else "충족"), f"$1 미만 {n}거래일 연속")
        add("$0.10 이하 10거래일 연속 → 바로 상폐 결정", "미달" if (F.get("le10") or 0) >= 10 else ("주의" if F.get("le10") else "충족"), f"{F.get('le10') or 0}거래일")
        known = eq is not None or m is not None
        okk = (eq is not None and eq >= 2.5e6) or (m is not None and m >= 35e6) or (ni is not None and ni >= 5e5)
        add("자기자본 $2.5M · 상장 시총 $35M · 최근 연 순이익 $0.5M 중 하나 이상", ("충족" if okk else "미달 가능") if known else NA,
            f"자기자본 {usd(eq)} · 시총 {usd(m)} · 연 순이익 {usd(ni)}")
        fu = F.get("float_usd")
        add("유통주식 시가 $1M 이상", NA if fu is None else ("충족" if fu >= 1e6 else "미달 가능"), usd(fu))
    elif e == "NYSE":
        tier = "NYSE"
        add("평균 시총 $50M 미만이면서 자기자본 $50M 미만 → 미달", NA if m is None else ("미달 가능" if (m < 50e6 and (eq is None or eq < 50e6)) else "충족"), f"시총 {usd(m)} · 자기자본 {usd(eq)}")
        add("평균 시총 $15M 미만 → 바로 상폐 절차", NA if m is None else ("미달" if m < 15e6 else "충족"), usd(m))
        add("30거래일 평균 종가 $1 미만 → 통지 (6개월 회복)", NA if F.get("avg30") is None else ("미달" if F["avg30"] < 1 else "충족"), pxs(F.get("avg30")))
    elif "AMERICAN" in e or e in ("AMEX", "NYSEAMERICAN", "NYSE MKT"):
        tier = "NYSE American"
        losses = [x for x in (F.get("ni_fy") or []) if x is not None]
        ln = lambda k: sum(1 for x in losses[:k] if x < 0)
        need = None
        if eq is not None:
            if eq < 6e6 and len(losses) >= 5 and ln(5) == 5: need = "$6M (최근 5년 연속 손실)"
            elif eq < 4e6 and ln(4) >= 3: need = "$4M (최근 4년 중 3년 손실)"
            elif eq < 2e6 and ln(3) >= 2: need = "$2M (최근 3년 중 2년 손실)"
        ex = m is not None and m >= 50e6
        add("자기자본 기준 $2M/$4M/$6M (손실 연수별) — 시총 $50M 이상 등 조건 충족 시 면제 가능",
            NA if eq is None else ("충족" if not need else ("면제 가능" if ex else "미달 가능")), f"자기자본 {usd(eq)} · 손실 {ln(5)}/{len(losses)}년 · 시총 {usd(m)}", need)
        add("저가 기준: 거래소 재량 (고정 숫자 없음 · 낮은 가격이 이어지면 역분할 요구 · 새 최소가 규정 제안은 확정 여부 확인 필요)", "주의" if (P or 9) < 0.5 else "참고", pxs(P))
    elif e:
        tier = e
        add("OTC 등: 거래소 상장 유지 기준 없음 (OTCQX/QB/Pink 등급 데이터 없음)", NA, e)
    else: tier = NA
    for x in docs:
        d = x["d"] or {}
        if (_d(F["asof"]) - _d(x["filed"])).days > 365: continue
        # 통지는 8-K 3.01 · 6-K 원문만 (투자설명서·셸프의 위험 요인 문구는 과거 통지 재인용이라 제외)
        if not (x["form"].startswith("6-K") or (x["form"].startswith("8-K") and "3.01" in str(x.get("items") or ""))): continue
        if d.get("def_kind") and any(r["state"] == "미달 통지" and r["rule"].endswith(d["def_kind"]) for r in L): continue
        if d.get("def_kind"):
            add(f"거래소 미달 통지: {d['def_kind']}", "미달 통지", f"{x['form']} {x['filed']}" + (f" · 회복 기한 {d['deadline']}" if d.get("deadline") and str(d["deadline"]) > x["filed"] else " · 기한 확인되지 않음"), x["url"])
        elif d.get("regained"):
            add("기준 회복 공시", "회복", f"{x['form']} {x['filed']}", x["url"])
    if F.get("def301") and not any(r["state"] == "미달 통지" for r in L):
        add("8-K 3.01 (상장 유지 미달·이전) 공시", "미달 통지", ", ".join(F["def301"][:3]) + " · 원문 내용 확인되지 않음")
    if any(r["state"] == "회복" for r in L):
        for r in L:
            if r["state"] == "미달 통지": r["state"] = "통지 후 회복 공시 있음"
    return dict(tier=tier, rules=L, bad=sum(1 for r in L if r["state"] in ("미달", "미달 통지", "미달 가능")), asof_rules=RULES_ASOF)

def scenarios(S, F, P):
    sup = [x for x in S["resist"]["strikes"] if x["above"]]
    z = (S["resist"].get("vp") or {}).get("zone")
    r1 = sup[0]["px"] if sup else (z["lo"] if z else F.get("hi60"))
    sup_on = bool(S["fd"].get("room_usd")) or bool(F.get("s1_pending")) or bool(F.get("n424_30"))
    weak = (F.get("runway_m") is not None and F["runway_m"] < 6) or S["listing"]["bad"] > 0
    cat = next((x["pts"] for x in S["score"]["items"] if x["k"] == "catalyst"), 0) >= 11
    bull = dict(name="Bull", like="보통" if (cat and not sup_on) else "낮음",
                trigger=(f"원문 근거 촉매({S['cat'][0]['g']}급) 이어짐 + 새 발행 공시 없음" if S["cat"] else "새 구속력 있는 촉매(계약·승인) 공시 + 거래량 동반 돌파"),
                target=f"첫 저항 {pxs(r1)}" if r1 else "저항 확인되지 않음", invalid="새 증자·ATM 사용 공시 또는 20일 저점 이탈")
    base = dict(name="Base", like="낮음" if weak else "보통", trigger="공시 공백 · 거래량 감소",
                target=(f"{pxs(F.get('lo20'))} ~ {pxs(r1)} 박스" if F.get("lo20") and r1 else "범위 확인되지 않음"), invalid="박스 위·아래 이탈")
    bt = [x for x in ["셸프·ATM·ELOC 물량" if S["fd"].get("room_usd") else None, "가격 미정 공모 대기" if F.get("s1_pending") else None,
                      "런웨이 6개월 미만" if F.get("runway_m") is not None and F["runway_m"] < 6 else None, "상장 유지 미달" if S["listing"]["bad"] else None] if x]
    bear = dict(name="Bear", like="높음" if (sup_on or weak) else "보통", trigger=", ".join(bt) or "급등 뒤 이익 실현 · 공시 공백",
                target=f"20일 저점 {pxs(F.get('lo20'))} 아래" if F.get("lo20") else NA, invalid="구속력 있는 촉매 + 물량 소진 공시")
    g = S["score"]["grade"]
    dil = next((x["pts"] for x in S["score"]["items"] if x["k"] == "dilution"), 20)
    expo = "극단" if (((P or 9) < 1 and S["listing"]["bad"]) or (dil <= 6 and weak)) else ("높음" if g == "D" else "보통" if g == "C" else "낮음")
    if (F.get("dv20") or 0) < 2e5 and expo in ("낮음", "보통"): expo = "높음"
    ex = ["EXIT1 모멘텀 소진: 거래량 줄며 고점 못 넘을 때"]
    if S["fd"].get("room_usd") or F.get("n424_30"): ex.append("EXIT2 희석·대주주 매도: 투자설명서(424B)·ATM 사용·재판매 등록 효력 공시")
    if S["cat"]: ex.append("EXIT3 촉매 실패: 계약 해지·승인 거절·일정 연기")
    if any(i["kind"].startswith("ATM") for i in S["inst"]): ex.append("ATM: 급등일 거래량 급증 = 회사가 시장에 팔 수 있는 구간")
    if any("ELOC" in i["kind"] for i in S["inst"]): ex.append("ELOC: 재판매 등록 효력 직후 매도 물량")
    if S["resist"]["strikes"]: ex.append("워런트: 행사가 위에서 행사·매도 물량 (" + ", ".join(pxs(x["px"]) for x in S["resist"]["strikes"][:3]) + ")")
    return [bull, base, bear], expo, ex

def gates(S, F):
    G = []
    def g(n, name, st, why): G.append(dict(n=n, name=name, state=st, why=why))
    idn = S["ident"]
    g(1, "신원 (회사·CIK·거래소·증권 종류)", "통과" if idn["cik"] and idn["exchange"] != NA and idn["type"] != NA else "부분", f"CIK {idn['cik'] or NA} · {idn['exchange']} · {idn['type']}")
    g(2, "기준 시점 (가격·공시 기준일)", "통과" if F.get("px_date") and S["asof"]["filing"] != NA else "부분", f"가격 {F.get('px_date') or NA} · 최근 공시 {S['asof']['filing']}")
    act = [i for i in S["inst"] if i["kind"] in ("셸프", "ELOC 재판매 등록", "재판매 등록", "공모/재판매 신고서") and i["state"] != "철회" and "만료" not in i["state"]]
    linked = [i for i in act if i.get("eff")]
    g(3, "계보 (계약 → 등록 → 효력 → 투자설명서)", ("해당 없음" if not act else "통과" if len(linked) == len(act) else "부분"),
      f"활성 등록 {len(act)}건 중 효력 연결 {len(linked)}건" if act else "활성 등록 서류 없음 (최근 3년 원문 기준)")
    g(4, "중복 금지 (재판매 등록분을 완전희석에 다시 안 더함)", "통과", "재판매 칸은 완전희석 계산에서 제외")
    g(5, "발행 가능 물량과 매도 가능 물량 분리", "통과", "발행 칸(지금·조건부·셸프)과 매도 칸(재판매 등록·144·락업)을 따로 표시")
    have = [k for k in ("cash", "burn_m", "debt_cur", "restricted") if F.get(k) is not None]
    g(6, "현금 현실 (제한 현금·부채·소모)", "통과" if len(have) == 4 else "부분", f"확인 {len(have)}/4 (현금·소모·단기 부채·제한 현금)")
    g(7, "법적 강도 (보도자료 말고 원문 계약)", "통과" if S["cat"] else "부분", "촉매 원문 근거 " + (f"{S['cat'][0]['form']} {S['cat'][0]['filed']}" if S["cat"] else NA))
    g(8, "규정 최신성", "부분", f"규정 숫자는 {RULES_ASOF} 기준 앱 저장값 — 거래소·SEC 공식 원문 재확인 필요")
    nu = sum(1 for e in S["ev"] if e["state"] == "unk")
    g(9, "불확실성 (없음 vs 확인되지 않음)", "통과", f"확인되지 않음 {nu}개 → 확인 요청에 어느 서류인지 표시")
    g(10, "결정 유용성 (결정적·중요 먼저, 잡음 제거)", "통과", "발견 사항 결정적 → 중요 → 참고 순 정렬")
    return G

def findings(S, F):
    L = []
    def add(lv, txt, src_=None): L.append(dict(lv=lv, txt=txt, src=src_))
    for r in S["listing"]["rules"]:
        u = r.get("note") if str(r.get("note") or "").startswith("http") else None
        if r["state"] in ("미달", "미달 통지"): add("Critical", f"상장 유지: {r['rule']} — {r['val']}", dict(url=u) if u else None)
        elif r["state"] == "미달 가능": add("Material", f"상장 유지 미달 가능: {r['rule']} — {r['val']}")
    for x in S["toxic"]: add("Critical", f"위험 조항 문구 발견: {x['lab']}", x.get("src"))
    rw = F.get("runway_m")
    if rw is not None and rw < 6: add("Critical", f"현금 런웨이 약 {rw:.1f}개월 (6개월 미만 → 자금 조달 압박)")
    elif rw is not None and rw < 12: add("Material", f"현금 런웨이 약 {rw:.1f}개월")
    if F.get("s1_pending"): add("Critical", f"가격 미정 공모 신고서 대기 ({F['s1_pending']} 접수) — 가격 확정되면 대량 신주")
    m, ru = F.get("mcap"), S["fd"].get("room_usd")
    if ru and m: add("Critical" if ru >= 0.2 * m else "Material", f"셸프·ATM·ELOC 남은 발행 여력 {usd(ru)} = 시총의 {ru / m * 100:.0f}%")
    lg = S["ledger"]; bs = S["fd"].get("basic")
    if lg["now"].get("sh") and bs:
        r = lg["now"]["sh"] / bs
        add("Critical" if r >= 0.2 else "Material", f"지금 바로 행사 가능한 워런트 등 {shs(lg['now']['sh'])} (발행 주식의 {r * 100:.0f}%)")
    if lg["cond"].get("sh") and bs: add("Material", f"조건부 잠재 물량 {shs(lg['cond']['sh'])} (발행 주식의 {lg['cond']['sh'] / bs * 100:.0f}%)")
    fr = S["fd"].get("ratio")
    if fr and fr >= 1.5: add("Material", f"최대 완전희석 {fr:.2f}배")
    if F.get("n424_30"): add("Material", f"최근 30일 투자설명서(424B) {F['n424_30']}건")
    b = S.get("baby") or {}
    if b.get("on"): add("Material", f"베이비 셸프 적용: 유통 시총 {usd(b['float_usd'])} → 12개월 한도 {usd(b['cap'])} · 사용 {usd(b['used'])} · 남음 {usd(b['left'])}")
    A = _d(F["asof"])
    for u in S["r144"]["unlock"]:
        if A - pd.Timedelta(days=7) <= _d(u["date"]) <= A + pd.Timedelta(days=60): add("Material", f"{u['date']} {u['what']}", u.get("src"))
    if S["r144"]["f144"]: add("Material", f"Form 144 매도 예고 {len(S['r144']['f144'])}건 (90일 · 최근 {S['r144']['f144'][0]})")
    if S["motive"]["sells"]: add("Material", f"내부자 매도 {S['motive']['sells']}건 (90일 · Form 4)")
    for d in S["resist"]["double"][:2]: add("Material", f"이중 저항 {pxs(d['px'])}: {d['what']} + 위 매물대 겹침")
    if F.get("shgrow") is not None and F["shgrow"] >= 0.5: add("Material", f"1년 새 주식 수 {F['shgrow'] * 100:+.0f}%")
    if S["cap1999"]: add("Context", "19.99% 발행 한도(나스닥 5635) 문구 — 넘기려면 주주 승인 필요", S["cap1999"])
    for c in S["cat"][:2]: add("Context", f"촉매 {c['g']}급 원문 문구 ({c['form']} {c['filed']}): {c.get('hit') or ''}"[:220], _src(c["form"], c["filed"], c["url"]))
    if S["motive"]["buys"]: add("Context", f"내부자 장내 매수 {S['motive']['buys']}건 (90일)")
    if S["ident"].get("juris_note"): add("Context", S["ident"]["juris_note"])
    vp = S["resist"].get("vp") or {}
    if vp.get("above") is not None: add("Context", f"최근 60일 거래량의 {vp['above']:.0f}%가 현재가 위에서 거래됨 (위 매물대)")
    order = {k: i for i, k in enumerate(LEVELS)}
    L = list({x["txt"]: x for x in L}.values())
    return sorted(L, key=lambda x: order[x["lv"]])

def facts_summary(S, F):
    sc, fd, idn = S["score"], S["fd"], S["ident"]
    rw = F.get("runway_m")
    return [f"{idn['name'] or S['ticker']} · {idn['exchange']} · {idn['type']} · 설립지 {idn['juris']}",
            f"종가 {pxs(F.get('price'))} ({F.get('px_date') or NA}) · 시총 {usd(F.get('mcap'))} · 20일 거래대금 중앙값 {usd(F.get('dv20'))}",
            f"발행 주식 {shs(fd.get('basic'))} → 현실 완전희석 {shs(fd.get('practical'))} → 최대 {shs(fd.get('max'))}" + (f" ({fd['ratio']:.2f}배)" if fd.get("ratio") else ""),
            f"현금 {usd(F.get('cash'))} · 월 소모 {usd(F.get('burn_m'))} · 런웨이 " + (f"{rw:.1f}개월" if rw is not None and rw < 99 else ("소모 없음" if rw else NA)),
            "셸프·ATM·ELOC 남은 여력 " + (usd(fd["room_usd"]) if fd.get("room_usd") else (NONE if S["docs_seen"] else NA)),
            f"상장 유지 미달·가능 {S['listing']['bad']}건 · 위험 조항 문구 {len(S['toxic'])}개",
            f"점수 {sc['total']}/100 · 등급 {sc['grade']} · 신뢰도 {sc['conf']} · 노출 위험 {S['exposure']} (참고용)"]

def asks(S, F, docs):
    """확인 요청: 결론을 바꿀 수 있는 미확인 항목만, 어느 서류에서 볼지 콕 집어 '미확인 (날짜 서류)' 형식."""
    per = f"{F.get('per_form') or '10-Q'} {F.get('per_last') or ''}".strip()
    A, unk = [], {e["k"] for e in S["ev"] if e["state"] == "unk"}
    wnote = next((e.get("note") or "" for e in S["ev"] if e["k"] == "warr"), "")
    if "out" in unk: A.append(f"발행 주식 수 — 미확인 ({per} 표지)")
    if "warr" in unk: A.append(f"워런트 잔량·행사가 — 미확인 ({per} 자본 주석)")
    elif "행사가" in wnote and NA in wnote: A.append(f"워런트 종류별 행사가 — 미확인 ({per} 자본 주석)")
    if "auth" in unk: A.append(f"수권주식 한도 — 미확인 ({per} 대차대조표)")
    if F.get("convertible") and not (F.get("conv_px") or any((x["d"] or {}).get("conv_px") for x in docs)):
        A.append(f"전환사채 전환가·조정 조항 — 미확인 ({per} 부채 주석 · 원계약 8-K 1.01 첨부)")
    a = next((i for i in S["inst"] if i["kind"].startswith("ATM")), None)
    if a: A.append(f"ATM 사용액·남은 한도 — 미확인 ({a['form']} {a['filed']} 이후 10-Q 'at-the-market' 문단)")
    p = next((i for i in S["inst"] if i["kind"] in ("셸프", "재판매 등록", "ELOC 재판매 등록", "공모/재판매 신고서") and i["state"] == "효력 대기"), None)
    if p: A.append(f"{p['kind']} 효력 여부 — 미확인 ({p['form']} {p['filed']} · EFFECT 공지)")
    if {"cash", "burn"} & unk: A.append(f"현금·영업현금흐름 — 미확인 ({per} 현금흐름표)")
    if str(S["listing"]["tier"]).startswith("Nasdaq") and F.get("below1"): A.append("나스닥 등급(Capital/Global)·최근 1년 역분할 이력 — 미확인 (8-K 3.01 원문 · 거래소 공지)")
    if not S["motive"]["form4_ok"]: A.append("내부자 거래 — 미확인 (최근 Form 4)")
    if S["docs_planned"] > S["docs_seen"]: A.append(f"원문 {S['docs_planned'] - S['docs_seen']}건 아직 못 읽음 — 다시 실행하면 이어서 읽음")
    return A[:10]

# ---------------------------------------------------------------- 6. 저장·비교·목록
DIFF_KEYS = [("score.total", "점수"), ("score.grade", "등급"), ("score.conf", "신뢰도"), ("fd.basic", "발행 주식"), ("fd.max", "최대 완전희석"),
             ("fd.room_usd", "셸프·ATM·ELOC 여력"), ("F.cash", "현금"), ("F.runway_m", "런웨이(개월)"), ("listing.bad", "상장 유지 미달·가능"),
             ("exposure", "노출 위험"), ("F.price", "종가")]

def _get(S, path):
    o = S
    for p in path.split("."):
        o = o.get(p) if isinstance(o, dict) else None
    return o

def _sig(S): return hashlib.md5(json.dumps([_get(S, k) for k, _ in DIFF_KEYS] + sorted(x["txt"] for x in S.get("find") or []), default=str).encode()).hexdigest()

def save_snap(S):
    """cur = 이번 결과, prev = 값이 달랐던(또는 다른 날짜의) 직전 결과."""
    k = f"secsnap:{S['ticker']}"
    old = db.kv_get(k) or {}
    cur, prev = old.get("cur"), old.get("prev")
    if cur and (_sig(cur) != _sig(S) or str(cur.get("ts", ""))[:10] < S["ts"][:10]): prev = cur
    db.kv_set(k, {"cur": S, "prev": prev})

def load_snap(t, max_age_h=None):
    return db.kv_get(f"secsnap:{t.upper()}", max_age_h * 3600 if max_age_h else None) or {}

def diff(cur, prev):
    """이전 스냅샷 대비 바뀐 값 [(이름, 이전, 지금)] + 새로 생긴/사라진 발견 사항."""
    if not cur or not prev: return None
    D = []
    for k, lab in DIFF_KEYS:
        a, b = _get(prev, k), _get(cur, k)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
            if abs(a - b) <= max(1e-9, abs(a) * 0.005): continue
        elif a == b: continue
        D.append((lab, a, b))
    pt = {x["txt"] for x in prev.get("find") or []}; ct = {x["txt"] for x in cur.get("find") or []}
    return dict(changes=D, new=[x for x in cur.get("find") or [] if x["txt"] not in pt], gone=[x for x in prev.get("find") or [] if x["txt"] not in ct],
                prev_ts=prev.get("ts"))

def fmt_val(lab, v):
    if v is None: return NA
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if lab in ("발행 주식", "최대 완전희석"): return shs(v)
        if lab in ("셸프·ATM·ELOC 여력", "현금"): return usd(v)
        if lab == "종가": return pxs(v)
        if lab == "런웨이(개월)": return "소모 없음" if v >= 99 else f"{v:.1f}"
        return f"{v:g}"
    return str(v)

def summary_row(S):
    F = S.get("F") or {}; sc = S.get("score") or {}; fd = S.get("fd") or {}
    fi = S.get("find") or []
    return dict(ticker=S["ticker"], name=(S.get("ident") or {}).get("name"), price=F.get("price"), px_date=F.get("px_date"), total=sc.get("total"),
                grade=sc.get("grade"), conf=sc.get("conf"), fd_ratio=fd.get("ratio"), room=fd.get("room_usd"), mcap=F.get("mcap"), runway=F.get("runway_m"),
                crit=sum(1 for x in fi if x["lv"] == "Critical"), mat=sum(1 for x in fi if x["lv"] == "Material"),
                listing=(S.get("listing") or {}).get("bad"), exposure=S.get("exposure"), exch=(S.get("ident") or {}).get("exchange"), ts=S.get("ts"),
                top=fi[0]["txt"] if fi else None)

def candidates(limit=60, alerts=None):
    """급등 후보: 🔮 조짐 상위 → 오늘 스캔 상위 → 최근 알림 보낸 종목 (중복 제거)."""
    from . import omen as OM, scan as SC
    out = []
    try:
        rows = (OM.load_full(96) or {}).get("rows") or []
        out += [r["ticker"] for r in sorted(rows, key=lambda r: -(r.get("total") or 0))[:30]]
    except Exception: pass
    try:
        df, _ = SC.last_scan()
        if len(df) and "score" in df: out += df.sort_values("score", ascending=False).ticker.head(20).tolist()
    except Exception: pass
    try:
        if alerts is None:
            from . import alerts as AL
            alerts = AL.fetch_remote_log(ttl=600) or []
        cut = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3)).strftime("%Y-%m-%dT%H:%M")
        out += [str(r["ticker"]).upper() for r in reversed(alerts) if r.get("sent") and not r.get("dry") and r.get("ticker") and str(r.get("ts_utc") or "") >= cut][:20]
    except Exception: pass
    return list(dict.fromkeys(t for t in out if t))[:limit]

def refresh(tickers=None, budget_s=420, docs_per=10):
    """매일 작업: 후보 종목 퀵스캔 (시간 예산 안에서) → kv sec_list."""
    t0 = time.time()
    tk = tickers if tickers is not None else candidates()
    rows, done = [], 0
    for t in tk:
        if time.time() - t0 > budget_s: break
        try:
            rows.append(summary_row(build(t, fetch=True, budget_docs=docs_per))); done += 1
        except Exception as e:
            rows.append(dict(ticker=t, err=repr(e)[:120]))
    meta = dict(ts=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), n=done, tried=len(tk), secs=round(time.time() - t0))
    db.kv_set("sec_list", _js({"meta": meta, "rows": rows}))
    return meta

def load_list(max_age_h=96):
    """매일 계산 목록 + 앱에서 직접 돌린 스냅샷 합치기 (티커별 최신)."""
    L = db.kv_get("sec_list", max_age_h * 3600) or {}
    by = {r["ticker"]: r for r in L.get("rows") or [] if not r.get("err")}
    try:
        x = db.q("SELECT v FROM kv WHERE k LIKE 'secsnap:%' AND ts >= ?", (time.time() - max_age_h * 3600,))
        for v in x.v:
            S = (json.loads(v) or {}).get("cur")
            if S and (S["ticker"] not in by or str(S.get("ts")) > str(by[S["ticker"]].get("ts"))): by[S["ticker"]] = summary_row(S)
    except Exception: pass
    return L.get("meta"), list(by.values())

def study():
    try: return json.loads((ROOT / "model/sec_study.json").read_text())
    except Exception: return {}

# ---------------------------------------------------------------- 7. 복사 글
def copy_text(S, link=""):
    F = S.get("F") or {}; sc = S["score"]; idn = S["ident"]
    L = [f"🔬 {S['ticker']} SEC 퀵스캔 · {idn.get('name') or ''}".strip(" ·"),
         f"기준: 종가 {F.get('px_date') or NA} · 최근 공시 {S['asof']['filing']} · 정기 보고서 {S['asof']['periodic']} · 작성 {S['ts'][:16].replace('T', ' ')} (한국시간)",
         f"점수 {sc['total']}/100 · 등급 {sc['grade']} · 신뢰도 {sc['conf']} · 노출 위험 {S['exposure']} (참고용, 앱 점수 미반영)", "", "📌 핵심 팩트 요약"]
    L += [f"- {x}" for x in S["facts"]]
    if S["find"]:
        L += ["", "🧭 발견 사항 (결정적 → 중요 → 참고)"]
        for x in S["find"][:14]:
            s_ = x.get("src") or {}
            tag = " ".join(v for v in (s_.get("form"), s_.get("filed")) if v)
            L.append(f"- {LEVEL_KO[x['lv']]} {x['txt']}" + (f" [{tag}]" if tag else ""))
    L += ["", "📒 주식 장부 (7칸)"]
    for k, lab in BUCKETS:
        b = S["ledger"].get(k) or {}
        v = shs(b["sh"]) if b.get("sh") else (usd(b["usd"]) if b.get("usd") else (", ".join(b.get("items") or []) or NA))
        L.append(f"- {lab}: {v}")
    fd = S["fd"]
    L.append(f"- 완전희석: 기본 {shs(fd.get('basic'))} · 현실 {shs(fd.get('practical'))} · 최대 {shs(fd.get('max'))}" + (f" (빠진 항목: {', '.join(fd['missing'])})" if fd.get("missing") else ""))
    h = S["head"]
    L.append(f"- 추가 발행 여유: 원래 {shs(h.get('raw'))} · 대기 물량 뺀 {shs(h.get('overhang'))} · 약정까지 뺀 {shs(h.get('free'))}" if h.get("ok") else f"- 추가 발행 여유: 수권주식 {NA}")
    b = S.get("baby")
    if b: L.append(f"- 베이비 셸프: {'적용' if b.get('on') else '미적용'} (유통 시총 {usd(b.get('float_usd'))})" + (f" · 12개월 한도 {usd(b['cap'])} · 남음 {usd(b['left'])}" if b.get("on") else ""))
    if S["inst"]: L += ["", "🧾 발행 수단"] + [f"- {i['label']} ({i['form']} {i['filed']})" for i in S["inst"][:8]]
    rs = S["resist"]
    z = (rs.get("vp") or {}).get("zone")
    if rs["strikes"] or z:
        L += ["", "🧱 가격 저항"] + [f"- {pxs(x['px'])} {x['what']}" + (" · 이중 저항" if x["double"] and x["above"] else "") for x in rs["strikes"][:5]]
        if z: L.append(f"- 위 매물대 {pxs(z['lo'])}~{pxs(z['hi'])} (60일 거래량 {z['share']:.0f}%)")
    if S["cal"]: L += ["", "📅 일정"] + [f"- {c['date']} {c['what']}" for c in S["cal"][:8]]
    lr = [r for r in S["listing"]["rules"] if r["state"] not in ("충족", "참고")]
    L += ["", f"🏛️ 상장 유지 ({S['listing']['tier']})"] + ([f"- {r['state']}: {r['rule']} — {r['val']}" for r in lr[:5]] or ["- 확인된 미달 없음"])
    L += ["", "🎲 시나리오 (가능성: 낮음/보통/높음)"] + [f"- {s_['name']} [{s_['like']}] {s_['trigger']} → {s_['target']} · 무효화: {s_['invalid']}" for s_ in S["scen"]]
    L += ["", "🚪 출구 경로"] + [f"- {x}" for x in S["exits"]]
    if S["motive"]["questions"]: L += ["", "🕵️ 내부자·대주주 (질문)"] + [f"- {q}" for q in S["motive"]["questions"]]
    L += ["", "🧮 점수 항목"] + [f"- {x['label']} {x['pts']}/{x['max']} · {x['why']}" for x in sc["items"]]
    L += ["", "🚦 점검 관문"] + [f"- {g['n']}. {g['name']}: {g['state']}" for g in S["gates"]]
    if S["ask"]: L += ["", "❓ 확인 요청"] + [f"- {a}" for a in S["ask"]]
    if link: L += ["", f"🔗 {link}"]
    L.append("※ 숏 레이더 SEC 공시 자동 정리 · 키워드 해석이라 틀릴 수 있음 (원문 확인) · 투자 권유 아님")
    return "\n".join(L)
