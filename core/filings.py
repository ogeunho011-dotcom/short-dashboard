"""SEC EDGAR 새 공시 → 호재/악재 판정 (키워드 규칙 · 무료).

흐름: 감시 종목의 submissions JSON(data.sec.gov) → 최근 24시간 안에 접수된 새 공시만 →
  8-K/6-K: 항목(Item) 코드 + 보도자료(EX-99.1) 제목·첫 문단 + 본문 항목 설명을 키워드로 판정
  Form 4: 원문 XML 에서 장내 매수(거래코드 P) 금액
  424B·S-1·S-3·F-1·F-3: 증자 서류 → 악재
판정은 단순 키워드라 틀릴 수 있음 (예: 계약 '해지' 기사를 계약으로 읽는 등). 악재 단어가 하나라도 있으면 호재로 치지 않음.
SEC 접속 규칙: 초당 10회 이하, 연락처가 들어간 User-Agent (sources.SEC_UA)."""
import re, html, time, threading, datetime as dt, concurrent.futures as cf
from zoneinfo import ZoneInfo
from . import sources as src

KST, ET = ZoneInfo("Asia/Seoul"), ZoneInfo("America/New_York")

# ---------------------------------------------------------------- SEC 요청 (초당 8회 이하)
_lock = threading.Lock(); _last = [0.0]
def sec_get(url, timeout=15):
    with _lock:
        w = _last[0] + 0.125 - time.time()
        if w > 0: time.sleep(w)
        _last[0] = time.time()
    return src._sec(url, timeout=timeout)

# ---------------------------------------------------------------- 키워드 규칙
# (정규식, 한국어 이름, 강도 5=매우 강함 4=보통)
POS = [
    (r"\bFDA\b[^.]{0,80}?\b(approv|clear|grant)(?!\w*[- ]+(phase|trial|study|clinical|IND|protocol))|\b(approv|clear)\w*[^.]{0,60}\bby the (U\.S\. )?(FDA|Food and Drug)|510\(k\)[^.]{0,40}clearance|\bDe Novo\b[^.]{0,40}(grant|authoriz)", "FDA 승인·허가", 5),
    (r"Breakthrough (Therapy|Device) Designation|Fast Track Designation|Orphan Drug Designation|Rare Pediatric Disease Designation|RMAT designation|PRIME designation", "FDA 특별 지정(혁신·신속·희귀)", 5),
    (r"\b(IND|CTA)\b[^.]{0,40}\b(clear|approv|accept)", "임상 시험 승인(IND)", 4),
    (r"\bCE Mark\b|\b(EMA|CHMP|NMPA|PMDA|Health Canada)\b[^.]{0,60}(approv|positive opinion)", "해외 규제 승인", 4),
    (r"met (its|the|all)( \w+)? primary (efficacy )?endpoint|positive (topline|top-line|interim|final|phase|pivotal)[^.]{0,30}(data|results)|statistically significant (improvement|reduction|benefit)", "임상 성공(주요 목표 달성)", 5),
    (r"\b(to be acquired|agreed to be acquired|will be acquired)\b|definitive (merger )?agreement (to be acquired|under which [^.]{0,80} will acquire)|\$[\d.]+ per share in cash|tender offer to acquire all", "피인수·합병(주당 가격 제시)", 5),
    (r"\b(award(ed|s)?|wins?|won|secur(es|ed))\b[^.]{0,60}\b(contract|order|tender|grant)\b|\bpurchase orders?\b|\bselected by\b|\bmulti-year (contract|agreement|deal)\b", "계약·수주", 4),
    (r"\b(strategic )?(partnership|collaboration|co-development|joint venture)\b[^.]{0,40}\b(with|agreement)\b|\blicens(e|ing) agreement\b|\bexclusive licen", "제휴·라이선스", 4),
    (r"\b(share|stock) (repurchase|buyback)|\bbuyback program\b", "자사주 매입", 4),
    (r"\bregain(ed|s)? compliance\b", "상장 유지 기준 회복", 4),
    (r"\buplist|approved (for listing|to list) on (the )?(Nasdaq|NYSE)", "상위 시장 상장", 4),
    (r"\brecord (first|second|third|fourth|q[1-4])?[- ]?(quarter|quarterly|annual|year)?[^.]{0,20}(results|revenue|sales)|\brais(es|ed|ing) (its )?(full[- ]year |annual )?(revenue )?guidance|\bfirst (ever )?profitable quarter", "실적 호조·가이던스 상향", 4),
]
NEG = [
    (r"\b(public|registered direct|underwritten|best[- ]efforts) offering\b|\bprivate placement\b|\bsecurities purchase agreement\b|\bplacement agent\b|\bat[- ]the[- ]market\b|\bATM (program|offering|facility)\b|\bequity line\b|\bwarrants?\b[^.]{0,80}\b(reduced exercise price|inducement)|\binducement letter\b|\bpre-funded warrants?\b|\bstandby equity purchase\b|\bconvertible (note|debenture)s?\b", "증자·희석(공모·사모·워런트)", 0),
    (r"\breverse (stock )?split\b|\bshare consolidation\b", "역분할", 0),
    (r"\b(deficiency|delist\w*|not in compliance|non-?compliance|failed to (comply|satisfy))\b", "상장 유지 기준 미달·상폐 위험", 0),
    (r"\bgoing concern\b", "계속기업 불확실성", 0),
    (r"\b(did not|failed to|does not) (meet|achieve)[^.]{0,30}(endpoint|primary)|\bdiscontinu\w+ (the |its )?(development|trial|study|program)|\bclinical hold\b|\bComplete Response Letter\b|\bCRL\b", "임상 실패·FDA 거절", 0),
    (r"\bbankruptcy\b|\bChapter 11\b|\bwind[- ]down\b|\bliquidation\b", "파산·청산", 0),
    (r"\bterminat\w+ (the |its |of the )?(merger|agreement|contract|collaboration|partnership|license)", "계약·합병 해지", 0),
    (r"\b(auditor|independent registered public accounting firm)\b[^.]{0,60}\b(resign|dismiss)|\bnon-reliance\b|\brestatement of\b|\brestate (its|the|our) (previously|financial)", "감사인 변경·재무제표 정정", 0),
]
ITEM_NEG = {"1.02": "중요 계약 해지", "1.03": "파산", "2.04": "채무 가속", "2.06": "자산 손상", "3.01": "상장 유지 기준 미달 통지",
            "3.02": "미등록 주식 발행(사모)", "3.03": "주주 권리 변경(역분할 등)", "4.01": "감사인 변경", "4.02": "재무제표 신뢰 불가"}
ITEM_KO = {"1.01": "중요 계약", "2.01": "인수·매각 완료", "2.02": "실적", "5.02": "임원 변경", "5.07": "주총 결과", "7.01": "IR 자료", "8.01": "기타 중요 사항", "9.01": "첨부"}
NEG_FORMS = re.compile(r"^(424B\d?|S-1|S-1/A|S-3|S-3/A|S-3ASR|F-1|F-1/A|F-3|F-3/A|F-3ASR)$")

def _clean(raw):
    t = raw.decode("utf-8", "ignore") if isinstance(raw, bytes) else raw
    t = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", t)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    t = html.unescape(t).replace("\xa0", " ")
    return re.sub(r"\s+", " ", t).strip()

def _cut(t):
    m = re.search(r"(Forward[- ]Looking Statements|Safe Harbor|About [A-Z][\w&.,\- ]{2,40}\b(Inc|Corp|Ltd|plc|Therapeutics|Holdings)?)", t)
    return t[: m.start()] if m and m.start() > 200 else t

def classify_text(text):
    pos, neg = [], []
    for rx, name, w in POS:
        if re.search(rx, text, re.I): pos.append((name, w))
    for rx, name, _ in NEG:
        for m in re.finditer(rx, text, re.I):
            # '기준 회복' 문장 안의 deficiency 는 악재로 치지 않음
            if name.startswith("상장 유지") and re.search(r"regain(ed|s)? compliance", text[max(0, m.start() - 300): m.end() + 300], re.I): continue
            neg.append(name); break
    return pos, neg

# ---------------------------------------------------------------- 문서 받기
def _docs(cik, acc, primary):
    """8-K/6-K: (보도자료 앞부분, 본문 항목 설명) 텍스트."""
    base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}"
    ex, body, head = "", "", ""
    try:
        j = sec_get(f"{base}/index.json").json()
        names = [i["name"] for i in j.get("directory", {}).get("item", [])]
        exs = [n for n in names if re.search(r"ex-?99|exhibit-?99|dex99", n, re.I) and n.lower().endswith((".htm", ".html", ".txt"))]
        exs.sort(key=lambda n: (not re.search(r"99[._\-d]?0?1(?!\d)", n, re.I), n))
        if exs:
            ex = _clean(sec_get(f"{base}/{exs[0]}").content)
    except Exception:
        pass
    try:
        if primary:
            body = _clean(sec_get(f"{base}/{primary}").content)
            m = re.search(r"Item\s*\d\.\d{2}", body)
            if m: body = body[m.start():]
            else:
                m2 = re.search(r"Form 40-F\W{0,6}", body)
                body = body[m2.end():] if m2 else body[-4000:]
            body = _cut(body)[:3000]
    except Exception:
        pass
    if ex:
        head = _cut(ex)[:1500]
    return head, body

MON = r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},\s*20\d\d"
def headline(head):
    """보도자료 제목 추정: 'Exhibit 99.1' 머리말 뒤 ~ 날짜·통신사 표시 앞 (최대 160자)."""
    h = head
    ms = list(re.finditer(r"Exhibit\s*99\.?\d*", h[:500], re.I))
    if ms: h = h[ms[-1].end():]
    h = re.sub(r"^.{0,40}?Form 40-F\W{0,6}", "", h).strip(" \u200b")
    h = re.sub(r"^(INFORMATION CONTAINED IN THIS (CURRENT )?(REPORT ON )?FORM 6-K( REPORT)?|Information contained in this (Current )?Report on Form 6-K)\s*", "", h, flags=re.I)
    m = re.search(r"\b[A-Z][A-Z.'\- ]{2,30},\s*[A-Za-z.\s]{0,24}[,\s\u2014\u2013\-]+" + MON + r"|\(GLOBE NEWSWIRE\)|\(BUSINESS WIRE\)|/PRNewswire/|\(ACCESS ?Newswire\)|\(Newsfile", h)
    if m and 15 < m.start() < 600: return h[: m.start()].strip(" -\u2013\u2014\u200b")[:160]
    h = re.sub(r"^(Press Release|PRESS RELEASE|FOR IMMEDIATE RELEASE)\s*", "", h).strip()
    return h[:160].strip()

def form4_buy(cik, acc, primary):
    """Form 4 장내 매수(P) 금액 $. 없으면 0."""
    import xml.etree.ElementTree as X
    try:
        doc = primary.split("/")[-1]
        r = sec_get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{doc}")
        root = X.fromstring(r.content)
        who = root.findtext(".//reportingOwner/reportingOwnerId/rptOwnerName") or ""
        tot = 0.0
        for tr in root.iter("nonDerivativeTransaction"):
            if tr.findtext(".//transactionCoding/transactionCode") != "P": continue
            sh = float(tr.findtext(".//transactionAmounts/transactionShares/value") or 0)
            pr = float(tr.findtext(".//transactionAmounts/transactionPricePerShare/value") or 0)
            tot += sh * pr
        return tot, who
    except Exception:
        return 0.0, ""

# ---------------------------------------------------------------- 판정
def judge(f):
    """f: dict(ticker, cik, form, acc, items, primary, accepted) → 판정 dict 추가."""
    form, items = f["form"], [i for i in (f.get("items") or "").split(",") if i]
    out = dict(f, polarity="neutral", label="", cats=[], negs=[], strength=0, headline="")
    if NEG_FORMS.match(form):
        out.update(polarity="neg", label="증자 서류(" + form + ")", negs=["증자 서류"]); return out
    if form == "4":
        amt, who = form4_buy(f["cik"], f["acc"], f["primary"])
        if amt >= 10000:
            out.update(polarity="pos", label=f"내부자 장내 매수 ${amt:,.0f}", cats=["내부자 장내 매수"], strength=4, headline=who)
        return out
    if form not in ("8-K", "6-K", "8-K/A"):
        return out
    head, body = _docs(f["cik"], f["acc"], f["primary"])
    hl = headline(head) if head else ""
    text = (head + " " + body)
    pos, neg = classify_text(text)
    src_pos = head or (body if form == "6-K" else "")
    pos = classify_text(src_pos)[0] if src_pos else []
    if body and form != "6-K":   # 8-K 법률 문구에서는 강한 호재만 인정 (예: 원료 '공급 계약'을 수주로 오판 방지)
        pos += [p for p in classify_text(body)[0] if p[1] >= 5 and p not in pos]
    neg += [f"{ITEM_NEG[i]}(항목 {i})" for i in items if i in ITEM_NEG
            and not (i == "3.01" and re.search(r"regain(ed|s)? compliance", text, re.I))]
    out["headline"] = hl or (headline(body) if body else "")
    out["negs"] = list(dict.fromkeys(neg))
    if neg:
        out.update(polarity="neg", label=out["negs"][0])
    elif pos:
        out.update(polarity="pos", cats=[n for n, _ in pos], strength=max(w for _, w in pos), label=" · ".join(n for n, _ in pos[:2]))
    else:
        out["label"] = " · ".join(ITEM_KO.get(i, i) for i in items if i != "9.01") or "일반 공시"
    return out

# ---------------------------------------------------------------- 새 공시 찾기
def recent(tickers, hours=24, workers=4):
    """감시 종목의 최근 hours 시간 안 접수 공시 [(dict)] (판정 전)."""
    cm = src.cik_map()
    cut = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    def one(t):
        cik = cm.get(t.upper())
        if not cik: return []
        try:
            r = sec_get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
            if r.status_code != 200: return [("ERR", r.status_code)]
            rec = r.json()["filings"]["recent"]
        except Exception as e:
            return [("ERR", type(e).__name__)]
        out = []
        for i in range(min(40, len(rec["form"]))):
            a = rec.get("acceptanceDateTime", [""])[i] if rec.get("acceptanceDateTime") else ""
            try: at = dt.datetime.fromisoformat(a.replace("Z", "+00:00"))
            except Exception: continue
            if at < cut: continue
            out.append({"ticker": t, "cik": cik, "form": rec["form"][i], "acc": rec["accessionNumber"][i], "items": rec.get("items", [""] * 999)[i] or "",
                        "primary": rec.get("primaryDocument", [""] * 999)[i] or "", "accepted": at.isoformat(), "filed": rec["filingDate"][i]})
        return out
    res, errs = [], []
    with cf.ThreadPoolExecutor(workers) as ex:
        for lst in ex.map(one, tickers):
            for x in lst:
                (errs if isinstance(x, tuple) else res).append(x)
    return res, errs

def kst_str(iso):
    try: return dt.datetime.fromisoformat(iso).astimezone(KST).strftime("%m/%d %H:%M")
    except Exception: return ""

def sec_url(f):
    return f"https://www.sec.gov/Archives/edgar/data/{f['cik']}/{f['acc'].replace('-', '')}/{f['acc']}-index.htm"
