"""성공/실패 사례 원인 조사: SEC EDGAR 공시(8-K/6-K 보도자료 제목, 424B/S-1/S-3 등) + Google News RSS(날짜 범위) 헤드라인 수집.
실제 출처만 기록, 못 찾으면 '원인 불명'. 출력: data/sa_evidence.json"""
import sys, os, json, time, re, html, random
from pathlib import Path
import pandas as pd, numpy as np, requests, xml.etree.ElementTree as ET
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from core import db, sources as src
OUT = ROOT / "data/sa_evidence.json"
E = pd.read_pickle(ROOT / "data/sa_events.pkl"); A = pd.read_pickle(ROOT / "data/sa_alerts.pkl")
first = A.sort_values("asof").groupby("event").first()
E = E.join(first[["peak_date", "upday", "prob"]])
succ = E[E.first_hit == 1]; fail = E[E.first_hit == 0]
rs = random.Random(7)
s_top = succ.sort_values("maxup", ascending=False).head(30); s_rnd = succ.drop(s_top.index).sample(15, random_state=7)
f_big = fail.sort_values("minlo").head(25); f_rnd = fail.drop(f_big.index).sample(15, random_state=7)
cases = pd.concat([s_top.assign(group="success", pick="top"), s_rnd.assign(group="success", pick="random"),
                   f_big.assign(group="fail", pick="worst"), f_rnd.assign(group="fail", pick="random")])
names = dict(db.q("SELECT ticker, name FROM universe").values)
cik = src.cik_map()
ev = json.loads(OUT.read_text()) if OUT.exists() else {}

def sec(url):
    time.sleep(0.15); return requests.get(url, headers={"User-Agent": src.SEC_UA}, timeout=30)

def pr_title(c, acc):
    """8-K/6-K 의 EX-99 보도자료 첫 제목줄"""
    base = f"https://www.sec.gov/Archives/edgar/data/{c}/{acc.replace('-', '')}"
    try:
        items = sec(base + "/index.json").json()["directory"]["item"]
    except Exception: return None, base
    docs = [i["name"] for i in items if i["name"].lower().endswith((".htm", ".html", ".txt")) and "index" not in i["name"].lower()]
    ex = [d for d in docs if re.search(r"ex[-_]?99|exhibit99|ex99", d, re.I)] or docs[:1]
    if not ex: return None, base
    try:
        t = sec(base + "/" + ex[0]).text
    except Exception: return None, base + "/" + ex[0]
    t = re.sub(r"(?is)<(script|style|title|head).*?</\1>", " ", t)
    t = re.sub(r"(?i)<(br|/p|/div|/tr|/td|/h\d|/li)[^>]*>", "\n", t); t = html.unescape(re.sub(r"<[^>]+>", "", t))
    lines = [re.sub(r"\s+", " ", l).strip() for l in t.split("\n")]
    lines = [l for l in lines if 25 <= len(l) <= 260 and not re.match(r"(?i)^(exhibit|ex-?99|press release|for immediate release|news release)", l)]
    return (lines[0] if lines else None), base + "/" + ex[0]

def gnews(q, a, b):
    url = f"https://news.google.com/rss/search?q={requests.utils.quote(q)}+after:{a}+before:{b}&hl=en-US&gl=US&ceid=US:en"
    time.sleep(0.6)
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20); root = ET.fromstring(r.content)
    except Exception as e: return []
    out = []
    for it in root.iter("item"):
        out.append(dict(title=it.findtext("title"), link=it.findtext("link"), date=it.findtext("pubDate"), source=(it.find("source").text if it.find("source") is not None else "")))
    return out[:15]

for eid, r in cases.iterrows():
    key = f'{r.ticker}|{str(r["first"])[:10]}'
    if key in ev and ev[key].get("done"): continue
    t = r.ticker; d0 = pd.Timestamp(r["first"])
    d1 = pd.Timestamp(r.peak_date) if r.group == "success" and pd.notna(r.peak_date) else d0 + pd.Timedelta(days=8)
    a, b = (d0 - pd.Timedelta(days=4)).date(), (d1 + pd.Timedelta(days=2)).date()
    fil = db.q("SELECT form, filed, accession, items FROM filings WHERE ticker=? AND filed>=? AND filed<=? ORDER BY filed", (t, str(d0 - pd.Timedelta(days=30))[:10], str(b)))
    c = cik.get(t)
    frows = []
    for _, f in fil.iterrows():
        fd = pd.Timestamp(f.filed)
        row = dict(form=f.form, filed=f.filed, items=f["items"], url=(f"https://www.sec.gov/Archives/edgar/data/{c}/{f.accession.replace('-', '')}/" if c else None),
                   in_window=bool(pd.Timestamp(a) <= fd <= pd.Timestamp(b)))
        if row["in_window"] and c and f.form in ("8-K", "6-K", "8-K/A", "6-K/A"):
            row["title"], row["doc"] = pr_title(c, f.accession)
        frows.append(row)
    nm = names.get(t, "") or ""
    short = re.sub(r"(?i)[,.]?\s+(inc|corp|corporation|ltd|limited|holdings?|plc|co|company|group|n\.?v|s\.?a|ag|technologies|therapeutics)\.?\b.*$", "", nm).strip()
    news = gnews(f'"{t}"', a, b)
    if short and len(short) > 3: news += [n for n in gnews(f'"{short}"', a, b) if n["link"] not in {x["link"] for x in news}]
    ev[key] = dict(ticker=t, name=nm, first=str(d0)[:10], peak=str(r.peak_date)[:10] if pd.notna(r.peak_date) else None, window=[str(a), str(b)],
                   group=r.group, pick=r.pick, maxup=float(r.maxup), minlo=float(r.minlo), n_alerts=int(r.n_alerts), filings=frows, news=news[:20], done=True)
    OUT.write_text(json.dumps(ev, ensure_ascii=False, indent=1))
    print(key, r.group, len(frows), len(news), flush=True)
print("cases", len(ev))
