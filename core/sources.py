"""무료 데이터 소스 수집기. 각 소스는 실패해도 앱이 동작하도록 예외를 삼키고 상태를 기록한다."""
import io, re, json, time, zipfile, datetime as dt, ftplib, os
import requests
import pandas as pd
from . import db

UA_BROWSER = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
SEC_UA = os.environ.get("SEC_USER_AGENT", "ShortDash personal research contact@example.com")
S = requests.Session()
S.headers.update({"User-Agent": UA_BROWSER})

def _get(url, headers=None, timeout=20, **kw):
    return S.get(url, headers=headers or {}, timeout=timeout, **kw)

# ---------------- 가격 (yfinance) ----------------
def fetch_prices(ticker, period="2y"):
    import yfinance as yf
    try:
        h = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=False, actions=False)
        if h is None or h.empty:
            db.set_status("yfinance", False, f"{ticker}: 빈 응답"); return 0
        h = h.dropna(subset=["Close"])
        df = pd.DataFrame({"ticker": ticker, "date": [d.strftime("%Y-%m-%d") for d in h.index],
                           "open": h["Open"].values, "high": h["High"].values, "low": h["Low"].values,
                           "close": h["Close"].values, "volume": h["Volume"].values})
        n = db.upsert_df("prices", df, ["ticker", "date", "open", "high", "low", "close", "volume"])
        db.set_status("yfinance", True, f"{ticker} {n}일")
        return n
    except Exception as e:
        db.set_status("yfinance", False, repr(e)); return 0

def get_prices(ticker):
    df = db.q("SELECT * FROM prices WHERE ticker=? ORDER BY date", (ticker,))
    if len(df): df["date"] = pd.to_datetime(df["date"])
    return df

def fetch_info(ticker, ttl=6 * 3600):
    k = f"info:{ticker}"
    c = db.kv_get(k, ttl)
    if c is not None: return c
    import yfinance as yf
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        keep = ["longName", "shortName", "regularMarketPrice", "regularMarketPreviousClose", "regularMarketChangePercent",
                "preMarketPrice", "preMarketChangePercent", "postMarketPrice", "postMarketChangePercent", "regularMarketDayHigh",
                "regularMarketDayLow", "floatShares", "sharesOutstanding", "sharesShort", "shortPercentOfFloat",
                "sharesShortPriorMonth", "dateShortInterest", "bid", "ask", "bidSize", "askSize", "averageVolume10days",
                "averageVolume", "marketCap", "sector", "industry", "firstTradeDateMilliseconds", "totalCash", "exchange",
                "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "heldPercentInsiders", "heldPercentInstitutions", "currency"]
        d = {x: info.get(x) for x in keep}
        try:
            cal = t.calendar
            if isinstance(cal, dict) and cal.get("Earnings Date"):
                d["earnings_dates"] = [str(x) for x in cal.get("Earnings Date")]
        except Exception:
            pass
        try:
            sp = t.splits
            d["splits"] = [[i.strftime("%Y-%m-%d"), float(v)] for i, v in sp.items()] if sp is not None else []
        except Exception:
            d["splits"] = []
        db.kv_set(k, d)
        return d
    except Exception as e:
        db.set_status("yfinance_info", False, repr(e)); return {}

def fetch_intraday(ticker, period="5d", interval="5m"):
    import yfinance as yf
    try:
        h = yf.Ticker(ticker).history(period=period, interval=interval, prepost=True)
        return h
    except Exception:
        return pd.DataFrame()

# ---------------- FINRA Reg SHO 일별 공매도 거래량 ----------------
FINRA_URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{d}.txt"

def fetch_finra_day(day: dt.date, tickers=None):
    ds = day.strftime("%Y%m%d")
    try:
        r = _get(FINRA_URL.format(d=ds), allow_redirects=False, timeout=30)
        if r.status_code in (301, 302, 307, 403):
            # CDN 이 클라우드 서버(GitHub Actions 등) IP 를 막는 경우 → FINRA 공개 API 로 같은 데이터 받기
            n = fetch_finra_day_api(day, tickers)
            if n is not None: return n
        if r.status_code != 200 or not r.text.startswith("Date|"):
            msg = f"HTTP {r.status_code} (WAF/차단 또는 휴장일)"
            db.exec_("INSERT OR REPLACE INTO finra_days VALUES(?,?,?)", (ds, "blocked" if r.status_code in (301, 302, 307, 403) else "missing", time.time()))
            db.set_status("FINRA RegSHO", False, msg)
            return -1 if r.status_code in (301, 302, 307, 403) else 0
        df = pd.read_csv(io.StringIO(r.text), sep="|")
        df = df[df["Date"].astype(str).str.fullmatch(r"\d{8}")]
        if tickers is not None:
            df = df[df["Symbol"].isin(set(tickers))]
        out = pd.DataFrame({"ticker": df["Symbol"], "date": pd.to_datetime(df["Date"].astype(str)).dt.strftime("%Y-%m-%d"),
                            "short_vol": df["ShortVolume"], "short_exempt": df["ShortExemptVolume"], "total_vol": df["TotalVolume"]})
        n = db.upsert_df("short_vol", out, ["ticker", "date", "short_vol", "short_exempt", "total_vol"])
        db.exec_("INSERT OR REPLACE INTO finra_days VALUES(?,?,?)", (ds, "ok", time.time()))
        db.set_status("FINRA RegSHO", True, f"{ds} {n}행")
        return n
    except Exception as e:
        db.set_status("FINRA RegSHO", False, repr(e)); return -1

FINRA_API = "https://api.finra.org/data/group/otcMarket/name/regShoDaily"

def fetch_finra_day_api(day: dt.date, tickers=None):
    """FINRA 공개 API(인증 불필요). 거래보고소(NQTRF·NYTRF·NCTRF)별 행을 합치면 CNMSshvol 파일과 같은 값
    (2026-10-27 SOUN·TDIC·NN·AEYE·AAPL 로 일치 확인). ORF(장외 종목)는 CNMS 파일에 없으므로 제외.
    성공 시 행 수, 그날 자료가 없으면 0, API 도 실패하면 None."""
    ds = day.strftime("%Y%m%d"); iso = day.strftime("%Y-%m-%d")
    try:
        rows, off = [], 0
        while True:
            r = requests.post(FINRA_API, json={"limit": 5000, "offset": off, "compareFilters": [
                {"compareType": "equal", "fieldName": "tradeReportDate", "fieldValue": iso}]},
                headers={"Accept": "application/json", "User-Agent": UA_BROWSER}, timeout=60)
            if r.status_code == 204: break
            if r.status_code != 200: return None
            j = r.json(); rows += j; off += 5000
            if len(j) < 5000: break
        if not rows:
            db.exec_("INSERT OR REPLACE INTO finra_days VALUES(?,?,?)", (ds, "missing", time.time()))
            db.set_status("FINRA RegSHO", False, f"{ds} 자료 없음 (휴장일?)"); return 0
        a = pd.DataFrame(rows)
        a = a[a["marketCode"] != "O"]
        g = a.groupby("securitiesInformationProcessorSymbolIdentifier")[["shortParQuantity", "shortExemptParQuantity", "totalParQuantity"]].sum().reset_index()
        if tickers is not None: g = g[g["securitiesInformationProcessorSymbolIdentifier"].isin(set(tickers))]
        out = pd.DataFrame({"ticker": g["securitiesInformationProcessorSymbolIdentifier"], "date": iso,
                            "short_vol": g["shortParQuantity"], "short_exempt": g["shortExemptParQuantity"], "total_vol": g["totalParQuantity"]})
        n = db.upsert_df("short_vol", out, ["ticker", "date", "short_vol", "short_exempt", "total_vol"])
        db.exec_("INSERT OR REPLACE INTO finra_days VALUES(?,?,?)", (ds, "ok", time.time()))
        db.set_status("FINRA RegSHO", True, f"{ds} {n}행 (API)")
        return n
    except Exception:
        return None

def import_finra_file(path_or_buf, tickers=None):
    """차단된 환경용: 브라우저로 받은 CNMSshvol 파일을 수동 업로드."""
    df = pd.read_csv(path_or_buf, sep="|")
    df = df[df["Date"].astype(str).str.fullmatch(r"\d{8}")]
    if tickers is not None: df = df[df["Symbol"].isin(set(tickers))]
    out = pd.DataFrame({"ticker": df["Symbol"], "date": pd.to_datetime(df["Date"].astype(str)).dt.strftime("%Y-%m-%d"),
                        "short_vol": df["ShortVolume"], "short_exempt": df["ShortExemptVolume"], "total_vol": df["TotalVolume"]})
    return db.upsert_df("short_vol", out, ["ticker", "date", "short_vol", "short_exempt", "total_vol"])

def update_finra(days_back=60, tickers=None):
    today = dt.date.today()
    have = set(db.q("SELECT date FROM finra_days WHERE status='ok'")["date"])
    got = 0; blocked = 0
    for i in range(1, days_back + 1):
        d = today - dt.timedelta(days=i)
        if d.weekday() >= 5 or d.strftime("%Y%m%d") in have: continue
        n = fetch_finra_day(d, tickers)
        if n < 0:
            blocked += 1
            if blocked >= 3: break   # 차단 환경이면 빨리 포기
        else:
            got += max(n, 0)
    return got, blocked

def get_short_vol(ticker):
    df = db.q("SELECT * FROM short_vol WHERE ticker=? ORDER BY date", (ticker,))
    if len(df): df["date"] = pd.to_datetime(df["date"])
    return df

# ---------------- 공매도 잔고(Short Interest, 월 2회) : Nasdaq API + FINRA 공식 API ----------------
def _num(x):
    try:
        v = str(x).replace(",", "").strip()
        return float(v) if v and v.upper() not in ("N/A", "NA", "NONE", "-") else None
    except Exception:
        return None

def fetch_short_interest(ticker, ttl=12 * 3600):
    if ttl and db.kv_get(f"si_ok:{ticker}", ttl): return -1   # 캐시 (월 2회 공표라 12시간 캐시)
    try:
        r = _get(f"https://api.nasdaq.com/api/quote/{ticker}/short-interest?assetClass=stocks", headers={"Accept": "application/json"})
        d = r.json().get("data") or {}
        rows = (d.get("shortInterestTable") or {}).get("rows") or []
        recs = []
        for x in rows:
            si = _num(x.get("interest"))
            if si is None: continue                     # 'N/A' 행은 건너뜀
            recs.append((ticker, pd.to_datetime(x["settlementDate"]).strftime("%Y-%m-%d"), si,
                         _num(x.get("avgDailyShareVolume")) or 0.0, _num(x.get("daysToCover")) or 0.0))
        db.upsert_rows("short_interest", ["ticker", "settle_date", "si", "avg_vol", "dtc"], recs)
        db.set_status("Nasdaq Short Interest", True, f"{ticker} {len(recs)}건"); db.kv_set(f"si_ok:{ticker}", 1)
        return len(recs)
    except Exception as e:
        db.set_status("Nasdaq Short Interest", False, repr(e)); return 0

FINRA_SI = "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest"

def finra_si_dates(probe="AAPL"):
    """FINRA 공매도 잔고 결제일 목록 (공식 무료 API, 로그인 불필요)."""
    r = S.post(FINRA_SI, json={"limit": 5000, "fields": ["settlementDate"],
                               "compareFilters": [{"compareType": "EQUAL", "fieldName": "symbolCode", "fieldValue": probe}]},
               headers={"Accept": "application/json"}, timeout=40)
    r.raise_for_status()
    return sorted({x["settlementDate"] for x in r.json()})

def fetch_finra_si_date(settle, tickers=None):
    """결제일 하루치 나스닥 전 종목 공매도 잔고 → short_interest 표. tickers 를 주면 그 종목만 저장."""
    out, off = [], 0
    while True:
        r = S.post(FINRA_SI, json={"limit": 5000, "offset": off,
                                   "fields": ["symbolCode", "settlementDate", "currentShortPositionQuantity", "averageDailyVolumeQuantity", "daysToCoverQuantity"],
                                   "compareFilters": [{"compareType": "EQUAL", "fieldName": "settlementDate", "fieldValue": settle}],
                                   "domainFilters": [{"fieldName": "marketClassCode", "values": ["NNM", "SC", "NYSE", "AMEX", "ARCA", "BZX", "TXSE"]}]},
                   headers={"Accept": "application/json"}, timeout=60)
        r.raise_for_status()
        rows = r.json() if r.text.strip() else []
        out += rows
        if len(rows) < 5000: break
        off += 5000
    keep = set(tickers) if tickers is not None else None
    recs = [(x["symbolCode"], x["settlementDate"], float(x["currentShortPositionQuantity"] or 0), float(x.get("averageDailyVolumeQuantity") or 0),
             float(x.get("daysToCoverQuantity") or 0)) for x in out
            if x.get("symbolCode") and x.get("currentShortPositionQuantity") is not None and (keep is None or x["symbolCode"] in keep)]
    db.upsert_rows("short_interest", ["ticker", "settle_date", "si", "avg_vol", "dtc"], recs)
    return len(recs)

def update_finra_si(n_dates=4, since=None, tickers=None):
    """최근 n_dates 개 결제일(또는 since 이후 전부)의 FINRA 공매도 잔고. 이미 받은 날짜는 건너뜀(최근 2개는 정정 대비 다시 받음)."""
    try:
        ds = finra_si_dates()
        done = set(db.kv_get("finra_si_dates") or [])
        if not since and not done: since = "2023-12-01"   # 첫 실행: 백테스트용 과거분 한 번에 채움 (~2분)
        ds = [d for d in ds if d >= since] if since else ds[-n_dates:]
        if tickers is None:
            u = db.q("SELECT DISTINCT ticker FROM prices")
            tickers = set(u.ticker) if len(u) else None
        n = 0
        for d in ds:
            if d in done and d not in ds[-2:]: continue
            n += fetch_finra_si_date(d, tickers); done.add(d)
        db.kv_set("finra_si_dates", sorted(done))
        db.set_status("FINRA Short Interest", True, f"결제일 {ds[-1] if ds else '-'} · {n}건")
        return n
    except Exception as e:
        db.set_status("FINRA Short Interest", False, repr(e)[:200]); return 0

def get_short_interest(ticker):
    df = db.q("SELECT * FROM short_interest WHERE ticker=? ORDER BY settle_date", (ticker,))
    if len(df):
        df["settle_date"] = pd.to_datetime(df["settle_date"])
        # 공표일 = 결제일 + 약 8영업일 (FINRA 공표 일정). 백테스트 시 이 날짜 이후에만 사용 (룩어헤드 방지)
        df["publish_date"] = df["settle_date"] + pd.offsets.BDay(8)
    return df

# ---------------- 차입 가능 수량 / 대차이자(CTB) : IBKR 공개 FTP ----------------
# IBKR 이 무료 공개하는 usa.txt (ftp2.interactivebrokers.com, 사용자 shortstock, 비번 없음, 하루 중 수시 갱신).
# iBorrowDesk 는 JSON API 가 유료로 바뀌어 쓰지 않음. 과거 이력은 무료로 없음 → 오늘부터 직접 쌓음.
IBKR_HOSTS = ("ftp2.interactivebrokers.com", "ftp3.interactivebrokers.com")
_IBKR = {"ts": 0, "d": {}, "asof": None}

def fetch_ibkr_ftp(max_age=900):
    """전 종목 {ticker: (가용 주식수, 연 수수료 %)}. 실패하면 빈 dict. 15분 메모리 캐시."""
    if _IBKR["d"] and time.time() - _IBKR["ts"] < max_age: return _IBKR["d"]
    if db.kv_get("ibkr_down", 1800): return {}
    err = None
    for host in IBKR_HOSTS:
        try:
            f = ftplib.FTP(host, timeout=20); f.login("shortstock", "")
            buf = io.BytesIO(); f.retrbinary("RETR usa.txt", buf.write); f.quit()
            d, asof = {}, None
            for line in buf.getvalue().decode("latin1").splitlines():
                p = line.split("|")
                if line.startswith("#BOF") and len(p) >= 3:
                    try:   # 파일 작성 시각 (미국 동부) → UTC
                        from zoneinfo import ZoneInfo
                        t = dt.datetime.strptime(p[1] + " " + p[2], "%Y.%m.%d %H:%M:%S").replace(tzinfo=ZoneInfo("America/New_York"))
                        asof = t.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M")
                    except Exception: pass
                    continue
                if len(p) > 7 and p[0] and not p[0].startswith("#") and p[1] == "USD":
                    try:
                        av = p[7].strip()
                        avail = 1e7 if av.startswith(">") else float(av or 0)
                        d[p[0]] = (avail, float(p[6] or 0))   # (가용 수량, 연 수수료 %) — 빈 수수료 = 사실상 0
                    except Exception:
                        pass
            if len(d) < 1000: raise ValueError(f"행 수 이상 {len(d)}")
            _IBKR.update(ts=time.time(), d=d, asof=asof or dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M"))
            db.set_status("IBKR 대차(FTP)", True, f"{len(d)}종목 · {asof} UTC")
            return d
        except Exception as e:
            err = e
    db.set_status("IBKR 대차(FTP)", False, repr(err)[:200]); db.kv_set("ibkr_down", 1)
    return {}

def store_borrow(tickers=None):
    """IBKR 스냅샷을 borrow 표에 누적. 같은 날 직전 값과 같으면 건너뜀(하루 1행은 항상 남김). 반환: 저장 행 수."""
    d = fetch_ibkr_ftp()
    if not d: return 0
    ts = _IBKR["asof"]
    keys = [t for t in (tickers if tickers is not None else d.keys()) if t in d]
    last = db.q("SELECT b.ticker, b.ts, b.available, b.fee FROM borrow b JOIN (SELECT ticker, MAX(ts) m FROM borrow WHERE source='ibkr' GROUP BY ticker) x "
                "ON b.ticker=x.ticker AND b.ts=x.m WHERE b.source='ibkr'")
    L = {r.ticker: (r.ts, r.available, r.fee) for r in last.itertuples()}
    recs = []
    for t in keys:
        av, fee = d[t]; o = L.get(t)
        if o:
            if o[0] >= ts: continue
            same = abs((o[1] or 0) - av) < 1 and abs((o[2] or 0) - fee) < 1e-6
            new_day = o[0][:10] != ts[:10]
            if same and not new_day: continue
        recs.append((t, ts, av, fee, "ibkr"))
    return db.upsert_rows("borrow", ["ticker", "ts", "available", "fee", "source"], recs)

def borrow_csv(tickers=None):
    """현재 IBKR 스냅샷을 CSV 문자열로 (알림 기록 브랜치에 올려 앱이 장중에도 최신 값을 보게)."""
    d = fetch_ibkr_ftp()
    if not d: return None
    keys = [t for t in (tickers if tickers is not None else d.keys()) if t in d]
    return "ticker,ts,available,fee\n" + "".join(f"{t},{_IBKR['asof']},{d[t][0]:.0f},{d[t][1]:.4f}\n" for t in sorted(keys))

BORROW_RAW = "https://raw.githubusercontent.com/{repo}/alert-data/data/borrow/{name}"

def import_borrow_csv(text):
    rows = []
    for line in (text or "").splitlines()[1:]:
        p = line.split(",")
        if len(p) == 4:
            try: rows.append((p[0], p[1], float(p[2]), float(p[3]), "ibkr"))
            except ValueError: pass
    return db.upsert_rows("borrow", ["ticker", "ts", "available", "fee", "source"], rows)

def borrow_publish(folder, tickers=None):
    """(알림 작업) 최신 스냅샷 latest.csv + 바뀐 종목만 월별 이력 hist-YYYY-MM.csv 에 추가. 반환: (전체, 추가 행)."""
    text = borrow_csv(tickers)
    if not text: return 0, 0
    os.makedirs(folder, exist_ok=True)
    lp = os.path.join(folder, "latest.csv")
    old = {}
    if os.path.exists(lp):
        for line in open(lp, encoding="utf-8").read().splitlines()[1:]:
            q = line.split(",")
            if len(q) == 4: old[q[0]] = q
    rows = text.splitlines()[1:]
    if rows and old and next(iter(old.values()))[1] == rows[0].split(",")[1]: return len(rows), 0   # IBKR 파일 시각 그대로 → 변화 없음
    ch = [r for r in rows if (lambda q: q[0] not in old or old[q[0]][2:] != q[2:] or old[q[0]][1][:10] != q[1][:10])(r.split(","))]
    open(lp, "w", encoding="utf-8").write(text)
    if ch:
        hp = os.path.join(folder, dt.datetime.utcnow().strftime("hist-%Y-%m.csv"))
        new = not os.path.exists(hp)
        with open(hp, "a", encoding="utf-8") as fh:
            if new: fh.write("ticker,ts,available,fee\n")
            fh.write("\n".join(ch) + "\n")
    return len(rows), len(ch)

def sync_borrow_remote(repo=None, ttl=600, months=1):
    """(앱/daily) 알림 작업이 올린 최신 대차 스냅샷 + 이번 달 장중 이력을 받아 DB 에 합침. 공개 저장소라 토큰 불필요."""
    repo = repo or os.environ.get("GITHUB_REPOSITORY") or os.environ.get("GH_REPO") or "ogeunho011-dotcom/short-dashboard"
    if ttl and db.kv_get("borrow_sync", ttl) is not None: return -1
    n = 0
    now = dt.datetime.utcnow().replace(day=1)
    mons = [(now - dt.timedelta(days=28 * i)).strftime("hist-%Y-%m.csv") for i in range(months)]
    for name in ["latest.csv"] + list(dict.fromkeys(mons)):
        try:
            r = _get(BORROW_RAW.format(repo=repo, name=name), timeout=20)
            if r.status_code == 200: n += import_borrow_csv(r.text)
        except Exception:
            pass
    db.kv_set("borrow_sync", n)
    return n

def ftp_allowed():
    """FTP 는 GitHub 서버에서만 열림(이 상자·Streamlit 은 막힘 확인). 그 외에는 원격 스냅샷을 받음."""
    return bool(os.environ.get("GITHUB_ACTIONS") or os.environ.get("SHORTDASH_IBKR_FTP"))

def fetch_borrow(ticker):
    """한 종목 대차 정보 갱신 — GitHub 서버면 IBKR 파일, 아니면 알림 작업이 올린 스냅샷."""
    return store_borrow([ticker]) if ftp_allowed() else sync_borrow_remote()

def get_borrow(ticker):
    df = db.q("SELECT * FROM borrow WHERE ticker=? ORDER BY ts", (ticker,))
    if len(df): df["ts"] = pd.to_datetime(df["ts"], errors="coerce", utc=True).dt.tz_localize(None)
    return df.dropna(subset=["ts"]) if len(df) else df

# ---------------- 유니버스: Nasdaq 스크리너 ----------------
def fetch_universe(caps="small|micro|nano"):
    try:
        r = _get(f"https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=5000&exchange=nasdaq&marketcap={caps}",
                 headers={"Accept": "application/json"}, timeout=40)
        rows = r.json()["data"]["table"]["rows"]
        today = dt.date.today().isoformat()
        recs = []
        for x in rows:
            try:
                recs.append((x["symbol"].strip(), x["name"], float((x.get("marketCap") or "0").replace(",", "") or 0),
                             float((x.get("lastsale") or "$0").replace("$", "").replace(",", "") or 0),
                             float((x.get("pctchange") or "0").replace("%", "") or 0), today))
            except Exception:
                pass
        db.upsert_rows("universe", ["ticker", "name", "mcap", "price", "pct", "updated"], recs)
        db.set_status("Nasdaq Screener", True, f"{len(recs)}종목")
        return len(recs)
    except Exception as e:
        db.set_status("Nasdaq Screener", False, repr(e)); return 0

# ---------------- Reg SHO Threshold list (Nasdaq Trader) ----------------
def fetch_threshold(day: dt.date):
    ds = day.strftime("%Y%m%d")
    try:
        r = _get(f"https://www.nasdaqtrader.com/dynamic/symdir/regsho/nasdaqth{ds}.txt", timeout=20)
        if not r.text.startswith("Symbol|"):
            db.exec_("INSERT OR REPLACE INTO threshold_days VALUES(?,?)", (ds, "missing")); return 0
        recs = []
        for line in r.text.splitlines()[1:]:
            p = line.split("|")
            if len(p) > 3 and p[3] == "Y": recs.append((p[0], day.isoformat()))
        db.upsert_rows("threshold", ["ticker", "date"], recs)
        db.exec_("INSERT OR REPLACE INTO threshold_days VALUES(?,?)", (ds, "ok"))
        db.set_status("Nasdaq RegSHO Threshold", True, f"{ds} {len(recs)}종목")
        return len(recs)
    except Exception as e:
        db.set_status("Nasdaq RegSHO Threshold", False, repr(e)); return 0

def update_threshold(days_back=30):
    have = set(db.q("SELECT date FROM threshold_days")["date"])
    for i in range(0, days_back):
        d = dt.date.today() - dt.timedelta(days=i)
        if d.weekday() < 5 and d.strftime("%Y%m%d") not in have: fetch_threshold(d)

# ---------------- SEC: FTD, 공시, XBRL ----------------
def _sec(url, timeout=30):
    return requests.get(url, headers={"User-Agent": SEC_UA, "Accept-Encoding": "gzip, deflate"}, timeout=timeout)

def update_ftd(months_back=4, tickers=None):
    today = dt.date.today(); names = []
    for m in range(months_back, -1, -1):
        y, mo = today.year, today.month - m
        while mo <= 0: mo += 12; y -= 1
        for half in "ab": names.append(f"cnsfails{y}{mo:02d}{half}")
    have = set(db.q("SELECT name FROM ftd_files")["name"])
    tick = set(tickers) if tickers else None
    for n in names:
        if n in have: continue
        try:
            r = _sec(f"https://www.sec.gov/files/data/fails-deliver-data/{n}.zip", timeout=60)
            if r.status_code != 200: continue
            z = zipfile.ZipFile(io.BytesIO(r.content)); txt = z.read(z.namelist()[0]).decode("latin1")
            recs = []
            for line in txt.splitlines()[1:]:
                p = line.split("|")
                if len(p) < 6 or not p[0].isdigit(): continue
                if tick and p[2] not in tick: continue
                try: recs.append((p[2], f"{p[0][:4]}-{p[0][4:6]}-{p[0][6:]}", float(p[3] or 0), float(p[5] or 0) if p[5].strip() not in ("", ".") else None))
                except Exception: pass
            db.upsert_rows("ftd", ["ticker", "date", "qty", "price"], recs)
            db.exec_("INSERT OR REPLACE INTO ftd_files VALUES(?,?)", (n, time.time()))
            db.set_status("SEC FTD", True, f"{n} {len(recs)}행")
        except Exception as e:
            db.set_status("SEC FTD", False, repr(e))

def get_ftd(ticker):
    df = db.q("SELECT * FROM ftd WHERE ticker=? ORDER BY date", (ticker,))
    if len(df):
        df["date"] = pd.to_datetime(df["date"])
        df["publish_date"] = df["date"] + pd.Timedelta(days=21)  # SEC는 반월 후 약 2주 뒤 공개 → 룩어헤드 방지용 보수적 지연
    return df

def cik_map():
    c = db.kv_get("sec:cikmap", ttl=7 * 86400)
    if c: return c
    try:
        j = _sec("https://www.sec.gov/files/company_tickers.json").json()
        m = {v["ticker"].upper(): int(v["cik_str"]) for v in j.values()}
        db.kv_set("sec:cikmap", m); return m
    except Exception as e:
        db.set_status("SEC EDGAR", False, repr(e)); return {}

def fetch_filings(ticker, ttl=12 * 3600):
    if ttl and db.kv_get(f"fil_ok:{ticker}", ttl): return -1
    cik = cik_map().get(ticker.upper())
    if not cik: return 0
    try:
        j = _sec(f"https://data.sec.gov/submissions/CIK{cik:010d}.json").json()
        rec = j["filings"]["recent"]
        recs = [(ticker, rec["form"][i], rec["filingDate"][i], rec["accessionNumber"][i], rec.get("items", [""] * 9999)[i] or "")
                for i in range(len(rec["form"]))]
        db.upsert_rows("filings", ["ticker", "form", "filed", "accession", "items"], recs)
        db.set_status("SEC EDGAR", True, f"{ticker} {len(recs)}건"); db.kv_set(f"fil_ok:{ticker}", 1)
        return len(recs)
    except Exception as e:
        db.set_status("SEC EDGAR", False, repr(e)); return 0

def get_filings(ticker):
    df = db.q("SELECT * FROM filings WHERE ticker=? ORDER BY filed DESC", (ticker,))
    if len(df): df["filed"] = pd.to_datetime(df["filed"])
    return df

def fetch_companyfacts(ticker, ttl=86400):
    k = f"facts:{ticker}"
    c = db.kv_get(k, ttl)
    if c is not None: return c
    cik = cik_map().get(ticker.upper())
    if not cik: return {}
    try:
        j = _sec(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json", timeout=40).json()
        f = j.get("facts", {})
        g = f.get("us-gaap", {}); dei = f.get("dei", {})
        def series(ns, tag, unit):
            return [{"end": x.get("end"), "start": x.get("start"), "val": x.get("val"), "filed": x.get("filed"), "form": x.get("form")}
                    for x in ns.get(tag, {}).get("units", {}).get(unit, [])]
        out = {"shares": series(dei, "EntityCommonStockSharesOutstanding", "shares") + series(g, "CommonStockSharesOutstanding", "shares"),
               "public_float": series(dei, "EntityPublicFloat", "USD"),
               "cash": series(g, "CashAndCashEquivalentsAtCarryingValue", "USD") or series(g, "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "USD"),
               "opcf": series(g, "NetCashProvidedByUsedInOperatingActivities", "USD"),
               "warrants": series(g, "ClassOfWarrantOrRightOutstanding", "shares"),
               "convertible": series(g, "ConvertibleNotesPayableCurrent", "USD") + series(g, "ConvertibleDebtNoncurrent", "USD")}
        db.kv_set(k, out)
        return out
    except Exception as e:
        db.set_status("SEC XBRL", False, repr(e)); return {}

# ---------------- 뉴스 RSS / 소셜 / 환율 / 텔레그램 ----------------
def fetch_news(ticker, ttl=1800):
    k = f"news:{ticker}"
    c = db.kv_get(k, ttl)
    if c is not None: return c
    items = []
    try:
        import xml.etree.ElementTree as ET
        r = _get(f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US")
        root = ET.fromstring(r.content)
        for it in root.iter("item"):
            items.append({"title": (it.findtext("title") or "").strip(), "link": it.findtext("link"), "date": it.findtext("pubDate")})
        db.set_status("Yahoo RSS", True, f"{ticker} {len(items)}건")
    except Exception as e:
        db.set_status("Yahoo RSS", False, repr(e))
    db.kv_set(k, items)
    return items

def fetch_reddit_buzz(ticker, ttl=3600):
    k = f"reddit:{ticker}"
    c = db.kv_get(k, ttl)
    if c is not None: return c
    out = None
    try:
        r = requests.get(f"https://www.reddit.com/search.json?q=%24{ticker}&sort=new&limit=100&t=week",
                         headers={"User-Agent": "shortdash/0.1 personal"}, timeout=10)
        posts = r.json()["data"]["children"]
        now = time.time()
        d1 = sum(1 for p in posts if now - p["data"]["created_utc"] < 86400)
        out = {"week": len(posts), "day": d1}
        db.set_status("Reddit JSON", True, f"{ticker} {len(posts)}")
    except Exception as e:
        db.set_status("Reddit JSON", False, repr(e)[:150])
    try:
        r = requests.get(f"https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json", headers={"User-Agent": UA_BROWSER}, timeout=10)
        if r.status_code == 200:
            msgs = r.json().get("messages", [])
            out = (out or {}) | {"stocktwits": len(msgs)}
            db.set_status("StockTwits", True, f"{ticker}")
        else:
            db.set_status("StockTwits", False, f"HTTP {r.status_code}")
    except Exception as e:
        db.set_status("StockTwits", False, repr(e)[:150])
    db.kv_set(k, out)
    return out

def fetch_usdkrw(ttl=6 * 3600):
    c = db.kv_get("fx:usdkrw", ttl)
    if c: return c
    try:
        v = float(requests.get("https://open.er-api.com/v6/latest/USD", timeout=10).json()["rates"]["KRW"])
        db.kv_set("fx:usdkrw", v); db.set_status("환율(open.er-api)", True, f"{v:.1f}")
        return v
    except Exception as e:
        db.set_status("환율(open.er-api)", False, repr(e)); return db.kv_get("fx:usdkrw") or 1400.0

def fetch_options(ticker, ttl=3600):
    k = f"opt:{ticker}"
    c = db.kv_get(k, ttl)
    if c is not None: return c
    import yfinance as yf
    out = {}
    try:
        t = yf.Ticker(ticker)
        exps = t.options
        if exps:
            ch = t.option_chain(exps[0])
            calls, puts = ch.calls, ch.puts
            out = {"expiry": exps[0], "call_vol": float(calls["volume"].fillna(0).sum()), "put_vol": float(puts["volume"].fillna(0).sum()),
                   "call_oi": float(calls["openInterest"].fillna(0).sum()), "put_oi": float(puts["openInterest"].fillna(0).sum()),
                   "calls": calls[["strike", "volume", "openInterest", "impliedVolatility"]].fillna(0).to_dict("records")}
    except Exception as e:
        out = {"error": repr(e)[:100]}
    db.kv_set(k, out)
    return out

def send_telegram(text):
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not tok or not chat: return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", data={"chat_id": chat, "text": text[:4000]}, timeout=15)
        return r.ok
    except Exception:
        return False

def refresh_ticker(ticker, full=True):
    """한 종목의 모든 데이터를 새로 받아 캐시."""
    ticker = ticker.upper().strip()
    fetch_prices(ticker)
    fetch_short_interest(ticker)
    if full:
        fetch_borrow(ticker)
        fetch_filings(ticker)
        fetch_companyfacts(ticker)
    return ticker

# ---------------- 대량 가격 (스크리너용) ----------------
def bulk_prices(tickers, period="1y", chunk=80):
    """yfinance 일괄 다운로드 → prices 테이블. 반환: 저장된 종목 수"""
    import yfinance as yf
    ok = 0
    for i in range(0, len(tickers), chunk):
        part = tickers[i:i + chunk]
        try:
            h = yf.download(part, period=period, interval="1d", auto_adjust=False, group_by="ticker", threads=True, progress=False)
        except Exception as e:
            db.set_status("yfinance bulk", False, repr(e)); continue
        for t in part:
            try:
                x = h[t] if len(part) > 1 else h
                x = x.dropna(subset=["Close"])
                if len(x) == 0: continue
                df = pd.DataFrame({"ticker": t, "date": [d.strftime("%Y-%m-%d") for d in x.index], "open": x["Open"].values,
                                   "high": x["High"].values, "low": x["Low"].values, "close": x["Close"].values, "volume": x["Volume"].values})
                db.upsert_df("prices", df, ["ticker", "date", "open", "high", "low", "close", "volume"]); ok += 1
            except Exception:
                pass
    db.set_status("yfinance bulk", ok > 0, f"{ok}/{len(tickers)} 종목")
    return ok

def bulk_today_bars(tickers, chunk=100):
    """최신 세션 1분봉(정규장)을 일괄로 받아 종목별 당일 OHLCV 로 합침. Yahoo 일봉이 늦게 갱신될 때 보정용.
    반환: {ticker: {date, open, high, low, close, volume, ts}}"""
    import yfinance as yf
    out = {}
    for i in range(0, len(tickers), chunk):
        part = list(tickers[i:i + chunk])
        try:
            h = yf.download(part, period="1d", interval="1m", prepost=False, auto_adjust=False, group_by="ticker", threads=True, progress=False)
        except Exception as e:
            db.set_status("yfinance 1분봉", False, repr(e)); continue
        if h is None or h.empty: continue
        for t in part:
            try:
                x = (h[t] if len(part) > 1 else h).dropna(subset=["Close"])
                if len(x) == 0: continue
                ts = x.index[-1].tz_convert("America/New_York") if x.index.tz is not None else x.index[-1]
                x = x[[ix.date() == ts.date() for ix in (x.index.tz_convert("America/New_York") if x.index.tz is not None else x.index)]]
                out[t] = {"date": pd.Timestamp(ts.date()), "open": float(x["Open"].iloc[0]), "high": float(x["High"].max()), "low": float(x["Low"].min()),
                          "close": float(x["Close"].iloc[-1]), "volume": float(x["Volume"].sum()), "ts": str(ts)}
            except Exception:
                pass
    db.set_status("yfinance 1분봉", bool(out), f"{len(out)}/{len(tickers)} 종목 최신 1분봉")
    return out

def merge_today(px, bar, intraday_open=None):
    """일봉 DataFrame 에 최신 1분봉 합본을 반영: 1분봉 날짜가 더 새로우면 행 추가.
    같은 날짜면 장중(정규장 진행 중)일 때만 고가/저가/종가/거래량 갱신 — 장 마감 후에는 공식 종가(일봉)를 우선."""
    if intraday_open is None:
        from .live import session_now
        intraday_open = session_now()[0] == "regular"
    if bar is None or px is None or len(px) == 0: return px, False
    last = px["date"].iloc[-1]
    if bar["date"] > last:
        row = {"ticker": px["ticker"].iloc[-1], **{k: bar[k] for k in ("date", "open", "high", "low", "close", "volume")}}
        return pd.concat([px, pd.DataFrame([row])], ignore_index=True), True
    if bar["date"] == last and intraday_open:
        px = px.copy(); i = px.index[-1]
        px.loc[i, "high"] = max(float(px.loc[i, "high"]), bar["high"]); px.loc[i, "low"] = min(float(px.loc[i, "low"]), bar["low"])
        px.loc[i, "close"] = bar["close"]; px.loc[i, "volume"] = max(float(px.loc[i, "volume"]), bar["volume"])
        return px, True
    return px, False

# ---------------- 내부자 매매 (Form 4) ----------------
def insider_trades(ticker, max_docs=8, ttl=86400):
    """최근 Form 4 원문 XML 파싱 → 매수(P)/매도(S) 수량. SEC 무료."""
    k = f"form4:{ticker}"
    c = db.kv_get(k, ttl)
    if c is not None: return c
    import xml.etree.ElementTree as ET
    out = []
    cik = cik_map().get(ticker.upper())
    if not cik: return out
    try:
        j = _sec(f"https://data.sec.gov/submissions/CIK{cik:010d}.json").json()["filings"]["recent"]
        idx = [i for i, f in enumerate(j["form"]) if f == "4"][:max_docs]
        for i in idx:
            acc = j["accessionNumber"][i].replace("-", ""); doc = j["primaryDocument"][i].split("/")[-1]
            try:
                x = _sec(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}", timeout=15).content
                root = ET.fromstring(x)
                who = root.findtext(".//reportingOwner/reportingOwnerId/rptOwnerName") or ""
                for tr in root.iter("nonDerivativeTransaction"):
                    code = tr.findtext(".//transactionCoding/transactionCode")
                    sh = float(tr.findtext(".//transactionAmounts/transactionShares/value") or 0)
                    pr = tr.findtext(".//transactionAmounts/transactionPricePerShare/value")
                    out.append({"filed": j["filingDate"][i], "who": who, "code": code, "shares": sh, "price": float(pr) if pr else None})
            except Exception:
                continue
            time.sleep(0.15)
        db.set_status("SEC Form 4", True, f"{ticker} {len(out)}건")
    except Exception as e:
        db.set_status("SEC Form 4", False, repr(e))
    db.kv_set(k, out)
    return out

# ---------------- 옵션 콜 거래량 (yfinance, 무료·지연) ----------------
def options_calls(ticker, ttl=1800):
    """가장 가까운 만기 콜옵션 거래량 ÷ 미결제약정. 초소형주는 옵션이 없는 경우가 많음 → None."""
    k = f"optc:{ticker}"
    c = db.kv_get(k, ttl)
    if c is not None: return c.get("v")
    v = None
    try:
        import yfinance as yf
        tk = yf.Ticker(ticker); ex = tk.options
        if ex:
            ch = tk.option_chain(ex[0]).calls
            vol, oi = float(ch["volume"].fillna(0).sum()), float(ch["openInterest"].fillna(0).sum())
            if vol > 0: v = vol / max(oi, 1)
    except Exception:
        v = None
    db.kv_set(k, {"v": v})
    return v
