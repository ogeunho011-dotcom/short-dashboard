"""공모 전 펌핑 감지 (SEC EDGAR 원문 · 무료).

- 가격 미정 공모 서류: S-1/F-1(/A) 제출 후 424B1/3/4·MEF(가격 확정)·RW(철회) 없음 → '공모 대기'
  EFFECT(효력 발생)까지 나왔으면 '가격 결정 임박'
- 셸프(S-3/F-3)·ATM: 424B5 본문에 at-the-market 문구
- 나스닥 상장 유지 미달: 8-K Item 3.01 (외국 기업은 6-K 본문) → 기준 종류·회복 기한(본문 날짜, 없으면 통지일+180일 추정)
- $1 규칙: 종가 $1 미만 연속 거래일 → 30일째 통지 예상일
- 공모 규모: 등록 서류의 '최대 공모 금액' 또는 '주식 수 × 가정 가격' (원문 숫자만, 없으면 '데이터 없음')
- 공모가(424B), 워런트 행사가: 원문 'public offering price of $X', 'exercise price of $X'
원문 해석 결과는 접수번호(accession)별로 영구 캐시. 규칙·키워드 기반이라 틀릴 수 있어 원문 링크를 함께 보여 줌."""
import re, datetime as dt
import pandas as pd
from . import db, sources as src
from .filings import sec_get, _clean

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
DATE_RE = rf"((?:{MONTHS})\s+\d{{1,2}},\s*20\d\d)"

def _num(s):
    try: return float(str(s).replace(",", ""))
    except Exception: return None

def submissions(ticker, ttl=3600):
    """최근 공시 목록 (form, filed, acc, primary, items, accepted) — 1시간 캐시."""
    k = f"subm:{ticker}"
    c = db.kv_get(k, ttl)
    if c is not None: return c
    cik = src.cik_map().get(ticker.upper())
    if not cik: return {"cik": None, "rows": []}
    try:
        r = sec_get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json").json()["filings"]["recent"]
        n = min(len(r["form"]), 300)
        rows = [dict(form=r["form"][i], filed=r["filingDate"][i], acc=r["accessionNumber"][i], primary=r["primaryDocument"][i],
                     items=(r.get("items") or [""] * n)[i] or "", accepted=(r.get("acceptanceDateTime") or [""] * n)[i] or "") for i in range(n)]
        try:   # 점수용 filings 표도 같이 갱신
            db.upsert_rows("filings", ["ticker", "form", "filed", "accession", "items"], [(ticker, x["form"], x["filed"], x["acc"], x["items"]) for x in rows])
        except Exception: pass
        out = {"cik": cik, "rows": rows}
        db.kv_set(k, out); return out
    except Exception as e:
        db.set_status("SEC EDGAR", False, repr(e))
        return {"cik": cik, "rows": [], "err": repr(e)}

def doc_url(cik, acc, name=""):
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{name}" if name else \
        f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{acc}-index.htm"

def _text(cik, acc, primary, extra=r"ex-?99|filing.?fees|ex-?107", limit=600_000):
    """본문 + (있으면) 보도자료/수수료 첨부 텍스트."""
    out = []
    try: out.append(_clean(sec_get(doc_url(cik, acc, primary), timeout=30).content[:limit]))
    except Exception: pass
    if extra:
        try:
            j = sec_get(doc_url(cik, acc, "index.json")).json()
            for n in [i["name"] for i in j.get("directory", {}).get("item", [])]:
                if n != primary and re.search(extra, n, re.I) and n.lower().endswith((".htm", ".html", ".txt")):
                    out.append(_clean(sec_get(doc_url(cik, acc, n)).content[:200_000]))
        except Exception: pass
    return " ".join(out)

def _parse(t):
    """원문에서 숫자 추출 (없으면 None)."""
    o = {}
    m = re.search(r"(?:proposed\s+)?maximum\s+aggregate\s+offering\s+price[^$]{0,200}?\$\s?([\d,]{5,}(?:\.\d+)?)", t, re.I)
    if m: o["max_amount"] = _num(m.group(1))
    m = re.search(r"(?:we are|the company is)\s+offering\s+(?:up to\s+)?([\d,]{5,})\s+(?:shares|ordinary shares|class a|units|american depositary)", t, re.I)
    if m: o["shares_offered"] = _num(m.group(1))
    m = re.search(r"assumed\s+(?:public\s+)?offering\s+price\s+of\s+\$\s?([\d.]+)", t, re.I) or \
        re.search(r"assumed\s+combined\s+public\s+offering\s+price\s+of\s+\$\s?([\d.]+)", t, re.I)
    if m: o["assumed_price"] = _num(m.group(1).rstrip("."))
    m = re.search(r"(?:combined\s+)?(?:public\s+)?offering\s+price\s+(?:of|is)\s+\$\s?(\d+(?:\.\d+)?)", t[:150_000], re.I)
    if m:
        v = _num(m.group(1)); win = t[max(0, m.start() - 250): m.end() + 120]
        k = re.search(r"(?:per|each)\s+(two|three|four|five)\s+shares", win, re.I)
        if k and v:
            n = {"two": 2, "three": 3, "four": 4, "five": 5}[k.group(1).lower()]; v = v / n; o["offer_note"] = f"주식 {n}주+워런트 묶음 ${m.group(1)} → 주당 환산"
        o["offer_price"] = round(v, 4) if v else None
    m = re.search(r"public\s+offering\s+price\s*\$\s?[\d.]+\s*\$\s?([\d,]{6,})", t[:150_000], re.I)
    if m: o["gross"] = _num(m.group(1))
    ex = []
    for m in re.finditer(r"exercise\s+price\s+(?:of|equal\s+to)\s+\$\s?([\d.]+)\s+per", t, re.I):
        v = _num(m.group(1).rstrip("."))
        if v and v > 0.0001 and v not in ex: ex.append(v)
        if len(ex) >= 4: break
    if ex: o["warrant_ex"] = ex
    o["best_efforts"] = bool(re.search(r"best[- ]efforts", t[:200_000], re.I))
    o["atm"] = bool(re.search(r"at[- ]the[- ]market|sales agreement|equity distribution agreement", t[:5000], re.I))
    m = re.search(r"Registration (?:Statement )?No\.?\s*(333-\d+)", t[:5000], re.I)
    if m: o["reg_no"] = m.group(1)
    neg = re.search(r"deficien|not in compliance|non-?compliance|below the minimum|did not (meet|satisfy|comply)|fail(ed|s)? to (meet|satisfy|comply)", t[:60000], re.I)
    if re.search(r"(has|had)\s+regained\s+compliance|confirm\w*[^.]{0,60}regain\w*\s+compliance", t[:60000], re.I) and not neg:
        o["regained"] = True
    if neg and re.search(r"Nasdaq|NYSE|listing", t[:60000], re.I):
        kind = ("최소 주가 $1" if re.search(r"bid price", t, re.I) else
                "시가총액(MVLS)" if re.search(r"market value of listed securities|MVLS", t, re.I) else
                "자기자본" if re.search(r"stockholders.{0,3} equity", t, re.I) else
                "유통주식 시가(MVPHS)" if re.search(r"publicly held shares", t, re.I) else
                "정기 보고서 지연" if re.search(r"periodic (report|filing)|10-K|10-Q|20-F", t, re.I) else "기타")
        o["def_kind"] = kind
        m = re.search(rf"(?:until|through|by|on or before|expir\w+ on|ending on)\s+{DATE_RE}", t, re.I)
        if m:
            try: o["deadline"] = str(dt.datetime.strptime(re.sub(r"\s+", " ", m.group(1).replace(",", ", ")).replace(" ,", ",").replace(",  ", ", "), "%B %d, %Y").date())
            except Exception: pass
    return o

def parsed(cik, row):
    """접수번호별 영구 캐시."""
    k = f"offdoc4:{row['acc']}"
    c = db.kv_get(k)
    if c is not None: return c
    t = _text(cik, row["acc"], row["primary"])
    o = _parse(t) if t else {}
    o["ok"] = bool(t)
    if t: db.kv_set(k, o)
    return o

def _ago(d, today):
    return (today - pd.Timestamp(d)).days

def detect(ticker, px=None, dil=None, delist=None, today=None, fetch_docs=True):
    """반환 dict: tags[], items[] (title, why, url, date), penalty 설명, est(공모 규모), prices(워런트·공모가 레벨용)."""
    today = pd.Timestamp(today or dt.date.today())
    sub = submissions(ticker)
    cik, rows = sub.get("cik"), sub.get("rows") or []
    out = {"tags": [], "items": [], "levels": [], "est": None, "status": None, "source_ok": bool(rows), "cik": cik}
    if not rows:
        out["items"].append(dict(title="SEC 공시", why="데이터 없음 (SEC 목록을 못 받음)" if cik else "데이터 없음 (SEC 등록 번호 없음)", url=None, date=None))
        return out
    df = pd.DataFrame(rows); df["filed"] = pd.to_datetime(df["filed"])
    st = __import__("core.model", fromlist=["reg_status"]).reg_status(df.rename(columns={}), today + pd.Timedelta(days=1))
    # 1) 가격 미정 공모 서류
    reg = df[df["form"].str.match(r"^(S-1|F-1)(/A)?$")]
    if st["pending"]:
        r0 = reg.iloc[0]
        ser = reg[reg["filed"] >= st["reg_first"]]
        ds = ", ".join(pd.Timestamp(x).strftime("%m/%d") for x in ser["filed"].iloc[:4][::-1])
        o = parsed(cik, r0) if fetch_docs else {}
        if o.get("max_amount"): out["est"] = dict(amount=o["max_amount"], how="등록 서류의 최대 공모 금액", src=r0["form"])
        elif o.get("shares_offered") and o.get("assumed_price"):
            out["est"] = dict(amount=o["shares_offered"] * o["assumed_price"], how=f"{o['shares_offered'] / 1e4:,.0f}만 주 × 가정가 ${o['assumed_price']}", src=r0["form"])
        why = f"{r0['form'].split('/')[0]} 계열 서류 {len(ser)}건 제출({ds}) — 아직 가격 확정 서류(424B) 없음."
        why += " 효력 발생(EFFECT)까지 나와 가격 결정이 임박했을 수 있음." if st["effect"] else " 가격이 정해지면 새 주식이 시장에 풀림."
        if o.get("best_efforts"): why += " 주관사 책임 없는 방식(best efforts)."
        out["items"].append(dict(title="공모 대기 (가격 미정)" if not st["effect"] else "공모 가격 결정 임박", why=why, url=doc_url(cik, r0["acc"]), date=str(r0["filed"].date())))
        out["tags"].append("공모 전 펌핑 주의"); out["status"] = "pending"
        for v in (o.get("warrant_ex") or [])[:2]: out["levels"].append((v, f"워런트 행사가 ${v:g} ({r0['form']} {r0['filed']:%m/%d})"))
        if o.get("assumed_price"): out["levels"].append((o["assumed_price"], f"가정 공모가 ${o['assumed_price']:g} ({r0['form']} {r0['filed']:%m/%d})"))
    # 2) 최근 가격 확정 공모(424B) → 공급 기준선 (S-1/F-1 대기 직후 424B면 그 공모의 가격 확정)
    pr = df[df["form"].str.match(r"^424B\d$") & (df["filed"] >= today - pd.Timedelta(days=200))]
    out["priced"] = None
    if len(pr) and fetch_docs:
        for _, r1 in pr.head(3).iterrows():
            o = parsed(cik, r1)
            if not o.get("offer_price") or o.get("atm"): continue
            after_reg = bool(len(reg)) and 0 <= (r1["filed"] - reg["filed"].max()).days <= 30
            out["offer"] = dict(price=o["offer_price"], date=str(r1["filed"].date()), form=r1["form"], url=doc_url(cik, r1["acc"]), gross=o.get("gross"), note=o.get("offer_note"))
            out["levels"].append((o["offer_price"], f"공모가 ${o['offer_price']:g} ({r1['form']} {r1['filed']:%m/%d})"))
            for v in (o.get("warrant_ex") or [])[:2]:
                if all(abs(v - x[0]) > 1e-9 for x in out["levels"]): out["levels"].append((v, f"워런트 행사가 ${v:g} ({r1['form']} {r1['filed']:%m/%d})"))
            if _ago(r1["filed"], today) <= 30:
                g = f", 총 ${o['gross'] / 1e6:.1f}M" if o.get("gross") else ""
                out["items"].append(dict(title="공모 가격 확정" + (" (S-1/F-1 공모)" if after_reg else ""),
                                         why=f"{r1['filed']:%m/%d} {r1['form']} — 공모가 ${o['offer_price']:g}{g}" + (f" ({o['offer_note']})" if o.get("offer_note") else "") +
                                             (f", 워런트 행사가 ${o['warrant_ex'][0]:g}" if o.get("warrant_ex") else "") + ". 새 주식이 풀려 공모가 근처가 매도 기준선이 되기 쉬움.",
                                         url=doc_url(cik, r1["acc"]), date=str(r1["filed"].date())))
                out["tags"].append("공모 직후"); out["priced"] = str(r1["filed"].date())
            break
    # 3) 셸프·ATM
    b5 = df[df["form"].str.match(r"^424B5$") & (df["filed"] >= today - pd.Timedelta(days=120))]
    if out.get("offer") and len(b5): b5 = b5[b5["filed"].astype(str).str[:10] != out["offer"]["date"]]
    shelf = df[df["form"].str.match(r"^(S-3|F-3)(ASR)?$") & (df["filed"] >= today - pd.Timedelta(days=3 * 365))]
    if len(b5):
        r2 = b5.iloc[0]; o = parsed(cik, r2) if fetch_docs else {}
        kind = "ATM(시장가 수시 매도)" if o.get("atm") else "셸프 증자(424B5)"
        out["items"].append(dict(title=f"{kind} 사용", why=f"{r2['filed']:%m/%d} 424B5 제출 — 주가가 오르면 회사가 수시로 주식을 팔 수 있음.", url=doc_url(cik, r2["acc"]), date=str(r2["filed"].date())))
        out["tags"].append("ATM·셸프")
        for v in (o.get("warrant_ex") or [])[:2]:
            if all(abs(v - x[0]) > 1e-9 for x in out["levels"]): out["levels"].append((v, f"워런트 행사가 ${v:g} (424B5 {r2['filed']:%m/%d})"))
    elif len(shelf):
        r2 = shelf.iloc[0]
        out["items"].append(dict(title="셸프 등록 보유", why=f"{r2['filed']:%m/%d} {r2['form']} — 필요할 때 바로 증자할 수 있는 한도가 있음 (잔여 한도는 원문 확인).", url=doc_url(cik, r2["acc"]), date=str(r2["filed"].date())))
    # 4) 상장 유지 미달
    dk = df[(df["form"].str.startswith("8-K") & df["items"].astype(str).str.contains(r"\b3\.01\b")) & (df["filed"] >= today - pd.Timedelta(days=365))]
    if len(dk):
        r3 = dk.iloc[0]; o = parsed(cik, r3) if fetch_docs else {}
        if not o.get("regained"):
            dl = o.get("deadline") or str((r3["filed"] + pd.Timedelta(days=180)).date())
            est = "" if o.get("deadline") else " (본문 날짜 못 찾음 → 통지+180일 추정)"
            left = (pd.Timestamp(dl) - today).days
            out["items"].append(dict(title=f"나스닥 상장 유지 미달 통지 — {o.get('def_kind') or '기준 원문 확인'}",
                                     why=f"8-K 3.01 ({r3['filed']:%Y-%m-%d}) · 회복 기한 {dl}{est}" + (f" · D-{left}" if left >= 0 else " · 기한 지남"),
                                     url=doc_url(cik, r3["acc"]), date=str(r3["filed"].date())))
            out["tags"].append("상장 유지 미달")
            out["deadline"] = dl
    elif fetch_docs:   # 외국 기업: 6-K 본문으로 통지 확인 (최근 120일 · 최대 4건)
        for _, r3 in df[(df["form"] == "6-K") & (df["filed"] >= today - pd.Timedelta(days=120))].head(4).iterrows():
            o = parsed(cik, r3)
            if o.get("def_kind") and not o.get("regained"):
                dl = o.get("deadline") or str((r3["filed"] + pd.Timedelta(days=180)).date())
                est = "" if o.get("deadline") else " (본문 날짜 못 찾음 → 통지+180일 추정)"
                left = (pd.Timestamp(dl) - today).days
                out["items"].append(dict(title=f"상장 유지 미달 통지(6-K) — {o['def_kind']}", why=f"6-K ({r3['filed']:%Y-%m-%d}) · 회복 기한 {dl}{est}" + (f" · D-{left}" if left >= 0 else " · 기한 지남"),
                                         url=doc_url(cik, r3["acc"]), date=str(r3["filed"].date())))
                out["tags"].append("상장 유지 미달"); out["deadline"] = dl
                break
    # 5) $1 규칙
    if delist and delist.get("days_below_1"):
        n = int(delist["days_below_1"])
        if n < 30:
            out["items"].append(dict(title="$1 미만 30거래일 규칙", why=f"종가 $1 미만 {n}거래일째 — 30거래일이면 나스닥 통지 (약 {30 - n}거래일 남음, 규칙 기반 추정)", url=None, date=None))
        else:
            out["items"].append(dict(title="$1 미만 30거래일 도달", why=f"종가 $1 미만 {n}거래일 — 통지 대상 (공시 여부는 위 항목 참고)", url=None, date=None))
        out["tags"].append("$1 미만")
    # 6) 현금 소진
    if dil and dil.get("runway_m") is not None:
        rm = float(dil["runway_m"])
        out["runway_m"] = rm
        if rm < 12:
            out["items"].append(dict(title="현금 소진 추정", why=f"최근 재무제표 기준 현금으로 약 {rm:.1f}개월 버팀 (XBRL 현금 ÷ 영업 현금 유출) — 짧을수록 증자 압박", url=None, date=None))
            if rm < 6: out["tags"].append("현금 부족")
    if not out["items"]:
        out["items"].append(dict(title="공모·상장 유지 위험 공시", why="최근 해당 공시 없음 (S-1/F-1 대기·424B5·8-K 3.01 없음)", url=None, date=None))
    return out
