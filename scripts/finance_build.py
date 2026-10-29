"""🏦 자금줄·세력 구조 스냅샷 만들기 → model/financiers.json (공개 SEC 공시만, 비밀값 없음).
1) 희석성 자금줄(전환사채·ELOC 자주 쓰는 투자자) 이름을 SEC 전문검색(EDGAR FTS)으로 찾아 '종목 × 자금줄 × 수단(전환사채/ELOC)' 표.
   이름 목록은 후보 → 2024년 이후 실제 공시 문서 수 ≥ 10 인 이름만 남김 (지어내지 않음).
2) ELOC(주식매수약정) 재판매 등록(S-1/F-1/S-3/F-3 + 정정) 접수일과 같은 파일번호(333-…)의 EFFECT(효력) 날짜.
3) 역분할 날짜(yfinance) + 같은 자금줄 종목의 사건 뒤 결과(최대 상승·최대 하락·추가 역분할) — scripts/finance_study.py 가 계산.
실행: python scripts/finance_build.py  (SEC 초당 ≤ 6회, User-Agent = SEC_USER_AGENT)"""
import os, re, sys, json, time, threading, datetime as dt, pickle
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import requests
ROOT = Path(__file__).resolve().parents[1]
UA = os.environ.get("SEC_USER_AGENT") or "ShortDash research contact@example.com"
FTS = "https://efts.sec.gov/LATEST/search-index"
START = "2023-01-01"
# EDGAR FTS 의 forms= 는 "/A" 가 섞이면 결과가 틀어짐 → 기본 검색은 필터 없이, 펀드 보고서 양식만 뒤에서 제외. 등록서류는 양식별로 따로.
FORMS = None
SKIP_FORMS = {"N-PX", "N-PORT", "N-PORT/A", "NPORT-P", "N-CSR", "N-CSRS", "13F-HR", "485BPOS", "497", "N-2", "N-2/A", "497K"}
REG_FORMS = ["S-1", "S-1/A", "F-1", "F-1/A", "S-3", "S-3/A", "F-3", "F-3/A"]
# (키, 화면 이름, 검색 문구들) — 후보. 실제 문서 수로 걸러짐.
CANDIDATES = [
    ("target", "Target Capital 1", ['"Target Capital 1"']),
    ("yorkville", "Yorkville (YA II PN)", ['"YA II PN"']),
    ("streeterville", "Streeterville Capital", ['"Streeterville Capital"']),
    ("alumni", "Alumni Capital", ['"Alumni Capital"']),
    ("lincolnpark", "Lincoln Park Capital", ['"Lincoln Park Capital Fund"']),
    ("whitelion", "White Lion Capital", ['"White Lion Capital"']),
    ("arena", "Arena Investors", ['"Arena Investors"', '"Arena Business Solutions"']),
    ("hudsonbay", "Hudson Bay", ['"Hudson Bay Master Fund"']),
    ("ionic", "Ionic Ventures", ['"Ionic Ventures"']),
    ("armistice", "Armistice Capital", ['"Armistice Capital Master Fund"']),
    ("3i", "3i, LP", ['"3i, LP"']),
    ("masthill", "Mast Hill Fund", ['"Mast Hill Fund"']),
    ("diagonal", "1800 Diagonal Lending", ['"1800 Diagonal Lending"']),
    ("lind", "Lind Global", ['"Lind Global"']),
    ("helena", "Helena Global", ['"Helena Global Investment"']),
    ("ghs", "GHS Investments", ['"GHS Investments"']),
    ("keystone", "Keystone Capital Partners", ['"Keystone Capital Partners"']),
    ("clearthink", "ClearThink Capital", ['"ClearThink Capital"']),
    ("tumim", "Tumim Stone Capital", ['"Tumim Stone Capital"']),
    ("briley", "B. Riley Principal Capital", ['"B. Riley Principal Capital"']),
    ("squaregate", "Square Gate Capital", ['"Square Gate Capital"']),
    ("jjastor", "J.J. Astor", ['"J.J. Astor"']),
    ("esousa", "Esousa", ['"Esousa Holdings"']),
    ("triton", "Triton Funds", ['"Triton Funds"']),
    ("sabby", "Sabby", ['"Sabby Volatility Warrant Master Fund"']),
    ("anson", "Anson Funds", ['"Anson Investments Master Fund"']),
    ("intracoastal", "Intracoastal Capital", ['"Intracoastal Capital"']),
    ("iroquois", "Iroquois", ['"Iroquois Master Fund"']),
    ("alto", "Alto Opportunity", ['"Alto Opportunity Master Fund"']),
    ("atw", "ATW Opportunities", ['"ATW Opportunities Master Fund"']),
    ("l1", "L1 Capital", ['"L1 Capital Global Opportunities"']),
    ("bigger", "Bigger Capital", ['"Bigger Capital Fund"']),
    ("district2", "District 2 Capital", ['"District 2 Capital"']),
    ("hightrail", "High Trail", ['"High Trail Investments"']),
    ("cavalry", "Cavalry Fund", ['"Cavalry Fund I"']),
    ("leonite", "Leonite Capital", ['"Leonite Capital"']),
    ("firstfire", "FirstFire Global", ['"FirstFire Global"']),
    ("generatingalpha", "Generating Alpha", ['"Generating Alpha"']),
    ("sevenknots", "Seven Knots", ['"Seven Knots"']),
    ("avondale", "Avondale Capital", ['"Avondale Capital"']),
    ("atlas", "Atlas Sciences", ['"Atlas Sciences"']),
]
CONV = ['"convertible promissory note"', '"convertible note"', '"convertible debenture"']
ELOC = ['"equity purchase agreement"', '"common stock purchase agreement"', '"equity line"']

_lock = threading.Lock(); _last = [0.0]
def _get(params, tries=5):
    for i in range(tries):
        with _lock:
            w = _last[0] + 1 / 6 - time.time()
            if w > 0: time.sleep(w)
            _last[0] = time.time()
        try:
            r = requests.get(FTS if params is not None and not isinstance(params, str) else params,
                             params=params if not isinstance(params, str) else None,
                             headers={"User-Agent": UA}, timeout=40)
            if r.status_code == 200: return r.json()
        except Exception: pass
        time.sleep(1.5 * (i + 1))
    return None

def _ticker(dn):
    # 'Name  (TICK, TICKW)  (CIK 000…)' → TICK
    # 회사 이름 안 괄호('SMX (Security Matters) Public Ltd Co  (SMX, SMXWW)  (CIK …)') 대비: 두 칸 띄운 괄호 중 CIK 아닌 마지막 것
    g = [x for x in re.findall(r"\s\s\(([^()]*)\)", dn) if not x.strip().upper().startswith("CIK")]
    if not g: return None
    t = g[-1].split(",")[0].strip().upper()
    return t if t and t.replace("-", "").replace(".", "").isalnum() and len(t) <= 6 else None

def search_all(q, forms=FORMS, start=START, end=None, cap=9800):
    """문서 단위 전체 결과 (100건씩). 10,000건 넘으면 기간을 반으로 나눠 다시."""
    end = end or dt.date.today().isoformat()
    p = {"q": q, "dateRange": "custom", "startdt": start, "enddt": end, "from": 0}
    if forms: p["forms"] = forms
    j = _get(p)
    if not j: return None
    tot = j["hits"]["total"]["value"]
    if tot >= cap and start < end:
        a, b = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
        mid = a + (b - a) / 2
        if mid <= a: return None
        x = search_all(q, forms, start, mid.isoformat()); y = search_all(q, forms, (mid + dt.timedelta(days=1)).isoformat(), end)
        return None if x is None or y is None else x + y
    out = [h for h in j["hits"]["hits"]]
    for f in range(100, tot, 100):
        p["from"] = f; jj = _get(p)
        if not jj: return None
        out += jj["hits"]["hits"]
    return [{"id": h["_id"], "date": h["_source"].get("file_date"), "form": h["_source"].get("form") or h["_source"].get("file_type"),
             "ciks": h["_source"].get("ciks") or [], "names": h["_source"].get("display_names") or [],
             "file_num": h["_source"].get("file_num") or []} for h in out]

def count(q, start="2024-01-01"):
    j = _get({"q": q, "dateRange": "custom", "startdt": start, "enddt": dt.date.today().isoformat()})
    return j["hits"]["total"]["value"] if j else 0

def by_cik(hits):
    """문서 목록 → {cik: {ticker,name,first,last,n,forms}} (티커 없는 펀드·개인은 버림)."""
    d = {}
    for h in hits or []:
        if h["form"] in SKIP_FORMS: continue
        for c, n in zip(h["ciks"], h["names"]):
            t = _ticker(n)
            if not t: continue
            e = d.setdefault(c.lstrip("0"), {"ticker": t, "name": n.split("  (")[0].strip(), "first": h["date"], "last": h["date"], "n": 0, "forms": {}})
            e["n"] += 1; e["first"] = min(e["first"], h["date"]); e["last"] = max(e["last"], h["date"])
            e["forms"][h["form"]] = e["forms"].get(h["form"], 0) + 1
            e.setdefault("dates", set()).add(h["date"])
    for e in d.values(): e["dates"] = sorted(e["dates"])
    return d

def financier_table(raw):
    out = {}
    for key, label, phrases in CANDIDATES:
        if key in raw.get("fin", {}): out[key] = raw["fin"][key]; continue
        n = sum(count(p) for p in phrases)
        rec = {"label": label, "phrases": phrases, "docs_2024": n}
        if n < 10:
            rec["dropped"] = True; out[key] = rec; print("drop", label, n, flush=True); continue
        base = []; conv = []; eloc = []
        for p in phrases:
            base += search_all(p) or []
            for c in CONV: conv += search_all(f"{p} {c}") or []
            for e in ELOC: eloc += search_all(f"{p} {e}") or []
        B, C, E = by_cik(base), by_cik(conv), by_cik(eloc)
        for cik, e in B.items():
            e["conv_first"] = C.get(cik, {}).get("first"); e["conv_last"] = C.get(cik, {}).get("last")
            e["eloc_first"] = E.get(cik, {}).get("first"); e["eloc_last"] = E.get(cik, {}).get("last")
            e["conv_dates"] = C.get(cik, {}).get("dates", []); e["eloc_dates"] = E.get(cik, {}).get("dates", [])
        rec["issuers"] = B
        out[key] = rec; raw.setdefault("fin", {})[key] = rec
        print(label, n, "issuers", len(B), flush=True)
        pickle.dump(raw, open(ROOT / "data/finance_raw.pkl", "wb"))
    return out

def eloc_regs(raw):
    if "regs" in raw: return raw["regs"]
    hits = []
    for e in ['"equity purchase agreement"', '"common stock purchase agreement"', '"equity line of credit"', '"standby equity purchase"']:
        for f in REG_FORMS: hits += search_all(e, forms=f) or []
        print("reg", e, len(hits), flush=True)
    regs = {}
    for h in hits:
        for c, n in zip(h["ciks"], h["names"]):
            t = _ticker(n)
            if not t: continue
            for fn in h["file_num"] or [None]:
                if fn and not fn.startswith("333-"): continue
                k = (c.lstrip("0"), fn or h["id"])
                r = regs.setdefault(k, {"cik": c.lstrip("0"), "ticker": t, "file_num": fn, "filed": h["date"], "forms": [], "docs": []})
                r["filed"] = min(r["filed"], h["date"]); r["forms"].append(h["form"])
                if h["id"] not in r["docs"]: r["docs"].append(h["id"])
    raw["regs"] = list(regs.values()); pickle.dump(raw, open(ROOT / "data/finance_raw.pkl", "wb"))
    return raw["regs"]

def submissions(cik):
    j = _get(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json")
    if not j: return None
    rows = []
    def add(r):
        for i in range(len(r.get("form", []))):
            rows.append((r["form"][i], r["filingDate"][i], r.get("fileNumber", [""] * 99999)[i], r["accessionNumber"][i]))
    add(j["filings"]["recent"])
    for f in j["filings"].get("files", []):
        if f.get("filingTo", "9999") >= START:
            jj = _get(f"https://data.sec.gov/submissions/{f['name']}")
            if jj: add(jj)
    return {"tickers": j.get("tickers", []), "exchanges": j.get("exchanges", []), "rows": rows}

def effects(raw):
    ciks = sorted({r["cik"] for r in raw["regs"]})
    S = raw.setdefault("subm", {})
    todo = [c for c in ciks if c not in S]
    with ThreadPoolExecutor(4) as ex:
        for c, s in zip(todo, ex.map(submissions, todo)):
            if s: S[c] = s
    pickle.dump(raw, open(ROOT / "data/finance_raw.pkl", "wb"))
    for r in raw["regs"]:
        s = S.get(r["cik"])
        if not s or not r["file_num"]: r["effect"] = None; continue
        eff = sorted(d for f, d, fn, a in s["rows"] if f == "EFFECT" and fn == r["file_num"] and d >= r["filed"])
        r["effect"] = eff[0] if eff else None
        r["exchange"] = (s.get("exchanges") or [None])[0]
        wd = [d for f, d, fn, a in s["rows"] if f == "RW" and fn == r["file_num"]]
        r["withdrawn"] = min(wd) if wd else None
    return raw["regs"]

if __name__ == "__main__":
    p = ROOT / "data/finance_raw.pkl"
    raw = pickle.load(open(p, "rb")) if p.exists() and "--fresh" not in sys.argv else {}
    financier_table(raw)
    eloc_regs(raw)
    effects(raw)
    raw["built"] = dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    pickle.dump(raw, open(p, "wb"))
    tk = sorted({e["ticker"] for v in raw["fin"].values() for e in (v.get("issuers") or {}).values()} | {r["ticker"] for r in raw["regs"]})
    (ROOT / "data/finance_tickers.txt").write_text("\n".join(tk))
    print("done", len(raw["regs"]), "regs", len(tk), "tickers")
