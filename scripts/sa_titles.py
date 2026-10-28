"""제목이 비었거나 파일명인 8-K/6-K 를 다시 읽어 보도자료 제목/본문 첫 줄 추출 (sa_evidence.json 갱신)"""
import sys, json, re, html, time; from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
import requests
from core import sources as src
OUT = ROOT / "data/sa_evidence.json"; ev = json.loads(OUT.read_text())
BOIL = re.compile(r"(?i)(united states|securities and exchange|washington|form (8-k|6-k)|current report|pursuant to|commission file|incorporation|i\.r\.s|employer|address of|registrant|check the appropriate|emerging growth|indicate by check|^exhibit|^ex-?99|press release|for immediate release|news release|\.htm|^\d{4}-\d{2}-\d{2}|^date of report|telephone|zip code|former name|trading symbol|title of each class|name of each exchange|^none$|^n/a$|signature|^table of contents|^item \d|^\(?[a-z]\)?$|xbrl|us-gaap|cover page|^\d+$|report of foreign private issuer|^yes|^no |^\W+$)")
def sec(u): time.sleep(0.12); return requests.get(u, headers={"User-Agent": src.SEC_UA}, timeout=30)
def text_lines(u):
    t = sec(u).text
    t = re.sub(r"(?is)<(script|style|title|head|ix:header).*?</\1>", " ", t)
    t = re.sub(r"(?i)<(br|/p|/div|/tr|/td|/h\d|/li)[^>]*>", "\n", t); t = html.unescape(re.sub(r"<[^>]+>", "", t))
    out = []
    for l in t.split("\n"):
        l = re.sub(r"\s+", " ", l).strip()
        if 15 <= len(l) <= 300 and not BOIL.search(l): out.append(l)
    return out
n = 0
for k, v in ev.items():
    for f in v["filings"]:
        if not (f["in_window"] and f["form"] in ("8-K", "6-K", "8-K/A", "6-K/A") and f.get("url")): continue
        tt = f.get("title") or ""
        if tt and not re.search(r"\.txt|\.htm|us-gaap|^\S+$", tt) and len(tt) > 30 and f.get("lead"): continue
        try:
            items = sec(f["url"] + "index.json").json()["directory"]["item"]
        except Exception as e: print("idx fail", k, e); continue
        docs = [i["name"] for i in items if re.search(r"\.html?$", i["name"], re.I) and "index" not in i["name"].lower()]
        ex = [d for d in docs if re.search(r"ex[-_]?99|exhibit[-_]?99|ex99|dex99", d, re.I)]
        main = [d for d in docs if d not in ex and not re.search(r"ex[-_]?\d", d, re.I)]
        best = None
        for d in (ex[:1] + main[:1]):
            try: L = text_lines(f["url"] + d)
            except Exception: continue
            if L: best = (d, L); break
        if best:
            f["doc"] = f["url"] + best[0]; f["title"] = best[1][0][:250]; f["lead"] = " | ".join(best[1][1:4])[:500]; n += 1
            print(k, f["form"], f["filed"], "::", f["title"][:120])
    OUT.write_text(json.dumps(ev, ensure_ascii=False, indent=1))
print("updated", n)
