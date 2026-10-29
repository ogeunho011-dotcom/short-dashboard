"""⚠️ 참고 경고 4종 과거 사건 모으기 + 시점 기준 검증 → model/events.json, model/events_study.json (공개 SEC 공시·DB 일봉만).
사건(SEC 전문검색 EDGAR FTS, 2023-11 이후):
  rsmeet  역분할 안건 위임장(DEF/PRE 14A) · 외국 기업 6-K 주총 소집 ("reverse stock/share split" + meeting)
  swap    내부자 부채→주식 교환 (set-off / debt conversion / premium to the closing price) — 원문을 받아 core.events.parse_swap 으로
          내부자·교환가가 있는 것만, 교환가 > 직전 종가(DB)인 것만
  delist  나스닥 상폐 결정 통지 (Staff Delisting Determination / delisting determination / determined to delist, 8-K·6-K)
  le10    DB 일봉에서 종가 ≤ $0.10 10거래일 연속이 처음 된 날 (나스닥 종목)
검증(룩어헤드 없음): 진입 = 공시 접수일(또는 신호일) '다음' 거래일 시가 → 5일·20일 뒤 종가 수익률, 20일 최저가, 5일 안 +30% 터치.
비교 기준 = 같은 가격대(<$1, $1~5, $5↑)의 모든 종목·날짜 (같은 계산). 근거 성립(holds) 조건:
  사건 ≥ 30건(종목 ≥ 20) · 20일 수익률 중앙값이 기준보다 5%p 이상 나쁨 · 순위 검정 p < 0.05 · 앞/뒤 절반 기간 모두 같은 방향(−2%p 이하).
성립하면 앱에서 '점수 반영'(🔮 조짐 개수에 더함), 아니면 '참고'만.
한계: DB 일봉은 현재 상장 종목만(상폐된 종목 빠짐 → 상폐 관련 사건 결과가 실제보다 좋게 나옴), 역분할 조정 가격이라 과거 $0.10 연속은 덜 잡힘.
실행: python scripts/events_build.py [--no-fetch | --from-json]  (SEC 초당 ≤ 6회, User-Agent = SEC_USER_AGENT)"""
import os, re, sys, json, time, datetime as dt
from pathlib import Path
import numpy as np, pandas as pd, requests
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import db, events as EV
UA = os.environ.get("SEC_USER_AGENT") or "ShortDash research contact@example.com"
FTS = "https://efts.sec.gov/LATEST/search-index"
START = "2023-11-01"
Q = {
    "rsmeet": [('"reverse stock split" "special meeting"', "DEF 14A,PRE 14A"), ('"reverse stock split" "annual meeting"', "DEF 14A,PRE 14A"),
               ('"reverse share split" "general meeting"', "6-K"), ('"reverse stock split" "special meeting"', "6-K"), ('"share consolidation" "general meeting"', "6-K")],
    "swap": [('"set-off" "premium to the closing price"', "8-K,6-K"), ('"set-off agreement"', "8-K,6-K"), ('"debt conversion" "premium to the closing price"', "8-K,6-K"),
             ('"premium to the closing price" "conversion of" "loan"', "8-K,6-K"), ('"premium to the closing price" "outstanding indebtedness"', "8-K,6-K"),
             ('"premium to the closing price" "in exchange for the cancellation"', "8-K,6-K"), ('"debt-for-equity"', "8-K,6-K"), ('"debt for equity exchange"', "8-K,6-K")],
    "delist": [('"Staff Delisting Determination"', "8-K,6-K"), ('"delisting determination" "request a hearing"', "8-K,6-K"), ('"determined to delist"', "8-K,6-K"),
               ('"delist determination"', "8-K,6-K")],
}
_last = [0.0]
def get(url, params=None, tries=4):
    for i in range(tries):
        w = _last[0] + 1 / 6 - time.time()
        if w > 0: time.sleep(w)
        _last[0] = time.time()
        try:
            r = requests.get(url, params=params, headers={"User-Agent": UA}, timeout=40)
            if r.status_code == 200: return r
        except Exception: pass
        time.sleep(1.5 * (i + 1))
    return None

def fts(q, forms, end):
    out, frm = [], 0
    while frm < 10000:
        r = get(FTS, dict(q=q, forms=forms, dateRange="custom", startdt=START, enddt=end, **({"from": frm} if frm else {})))
        if r is None: break
        j = r.json(); h = j.get("hits", {}).get("hits", [])
        out += h; frm += len(h)
        if not h or frm >= j["hits"]["total"]["value"]: break
    return out

def collect(fetch=True):
    end = dt.date.today().isoformat()
    cik2t = {}
    for t, c in (db.kv_get("sec:cikmap") or {}).items(): cik2t.setdefault(int(c), t)
    have = set(db.q("SELECT DISTINCT ticker FROM prices").ticker)
    E = []
    for kind, qs in Q.items():
        seen = set()
        for q, forms in qs:
            hits = fts(q, forms, end); print(f"  {kind} {q} [{forms}] → {len(hits)}건", flush=True)
            for x in hits:
                s = x["_source"]; acc, fn = x["_id"].split(":", 1)
                tk = None
                for c in s.get("ciks") or []:
                    t = cik2t.get(int(c))
                    if t in have: tk = t; break
                if not tk:
                    for dn in s.get("display_names") or []:
                        m = re.search(r"\(([A-Z][A-Z0-9.\-]{0,6})(?:,|\))", dn)
                        if m and m.group(1) in have: tk = m.group(1); break
                if not tk or (acc, kind) in seen: continue
                seen.add((acc, kind))
                E.append(dict(kind=kind, ticker=tk, filed=s["file_date"], form=s.get("form") or s.get("root_forms", [""])[0], acc=acc, file=fn,
                              cik=int((s.get("ciks") or [0])[0])))
    # swap: 원문 확인 (내부자 · 교환가)
    if fetch:
        from core.filings import _clean
        sw = [e for e in E if e["kind"] == "swap"]
        print(f"  swap 원문 확인 {len(sw)}건...", flush=True)
        for e in sw:
            k = f"fts_swap:{e['acc']}:{e['file']}"
            p = db.kv_get(k)
            if p is None:
                r = get(f"https://www.sec.gov/Archives/edgar/data/{e['cik']}/{e['acc'].replace('-', '')}/{e['file']}")
                p = EV.parse_swap(_clean(r.content[:600_000])) if r is not None else None
                db.kv_set(k, p or {})
            e["swap"] = p or None
    return E

def outcomes(px):
    """종목 일봉 → 날짜별 (다음날 시가 진입) 결과 배열."""
    o, h, l, c = (px[k].values.astype(float) for k in ("open", "high", "low", "close"))
    n = len(c); R = {}
    def fwd(arr, k, fn):
        out = np.full(n, np.nan)
        for i in range(n - 1):
            j = i + 1
            if j + k - 1 < n: out[i] = fn(j, j + k)
        return out
    R["r5"] = fwd(c, 5, lambda j, e: c[e - 1] / o[j] - 1)
    R["r20"] = fwd(c, 20, lambda j, e: c[e - 1] / o[j] - 1)
    R["mdd20"] = fwd(l, 20, lambda j, e: l[j:e].min() / o[j] - 1)
    R["hit30"] = fwd(h, 5, lambda j, e: float(h[j:e].max() / o[j] - 1 >= 0.30))
    R["price"] = c
    return R

def bucket(p): return "<$1" if p < 1 else ("$1~5" if p < 5 else "$5+")

def study(E):
    from scipy.stats import mannwhitneyu
    P = db.q("SELECT ticker, date, open, high, low, close FROM prices WHERE date >= '2023-10-01' ORDER BY ticker, date")
    P = P[(P.open > 0) & (P.close > 0)]
    ex = dict(db.q("SELECT ticker, exchange FROM universe").values.tolist())
    base = {b: {k: [] for k in ("r5", "r20", "mdd20", "hit30")} for b in ("<$1", "$1~5", "$5+")}
    ev_rows = []
    byk = {}
    for e in E: byk.setdefault(e["ticker"], []).append(e)
    rng = np.random.default_rng(7)
    for t, g in P.groupby("ticker", sort=False):
        g = g.reset_index(drop=True)
        if len(g) < 30: continue
        R = outcomes(g); d = g.date.values
        # 기준: 종목당 날짜 10% 표본
        idx = np.where(~np.isnan(R["r20"]))[0]
        if len(idx):
            for i in rng.choice(idx, max(1, len(idx) // 10), replace=False):
                b = bucket(R["price"][i])
                for k in base[b]: base[b][k].append(R[k][i])
        evs = list(byk.get(t, []))
        # le10: 나스닥, 10거래일 연속 종가 ≤ $0.10 이 처음 된 날 (60일 안 재발은 같은 사건)
        if str(ex.get(t, "")).upper().startswith("NASDAQ"):
            st = 0; last = None
            for i, v in enumerate(g.close.values):
                st = st + 1 if v <= 0.10 else 0
                if st == 10 and (last is None or i - last > 60): evs.append(dict(kind="le10", ticker=t, filed=d[i], acc=None)); last = i
        for e in evs:
            if e["kind"] == "swap":
                s = e.get("swap") or {}
                if not (s.get("insider") and s.get("price")): continue
            i = int(np.searchsorted(d, e["filed"], side="right")) - 1     # 접수일 당일(또는 직전) 거래일 → 진입은 다음날 시가
            if e["kind"] == "le10": i = int(np.searchsorted(d, e["filed"], side="left"))
            if i < 1 or i >= len(g) or np.isnan(R["r20"][i]): continue
            if e["kind"] == "swap":
                pre = g.close.values[i - 1] if d[i] == e["filed"] else g.close.values[i]   # 접수일 전 종가
                if not s["price"] > pre: continue
                e["prem"] = s["price"] / pre - 1
            ev_rows.append(dict(kind=e["kind"], ticker=t, date=str(d[i]), bucket=bucket(R["price"][i]), **{k: float(R[k][i]) for k in ("r5", "r20", "mdd20", "hit30")}))
    EVd = pd.DataFrame(ev_rows)
    out = {"built": dt.datetime.now().isoformat(timespec="seconds"), "start": START, "rule": "같은 종목 45일 안은 한 사건 · 다음 거래일 시가 진입 · 20일 중앙값 기준보다 −5%p↓ · p<0.05 · 앞뒤 절반 모두 −2%p↓ · n≥30·종목≥20",
           "base": {b: dict(n=len(v["r20"]), **{k: float(np.nanmedian(v[k])) if k != "hit30" else float(np.nanmean(v[k])) for k in v}) for b, v in base.items()}, "kinds": {}}
    for kind in ("rsmeet", "swap", "le10", "delist"):
        x = EVd[EVd.kind == kind].sort_values("date") if len(EVd) else EVd
        if len(x):   # 같은 종목 45일 안 재공시(PRE→DEF 14A, 8-K→보도자료 6-K 등)는 한 사건
            keep, last = [], {}
            for i, r in x.iterrows():
                p0 = last.get(r.ticker)
                if p0 is None or (pd.Timestamp(r.date) - p0).days > 45: keep.append(i); last[r.ticker] = pd.Timestamp(r.date)
            x = x.loc[keep]
        if not len(x): out["kinds"][kind] = dict(n=0, holds=False, why="사건 없음"); continue
        # 가격대 가중 기준 (사건의 가격대 구성대로)
        w = x.bucket.value_counts(normalize=True)
        bmed = {k: float(sum(w.get(b, 0) * out["base"][b][k] for b in w.index)) for k in ("r5", "r20", "mdd20", "hit30")}
        ref = np.concatenate([np.array(base[b]["r20"])[rng.choice(len(base[b]["r20"]), int(4000 * w[b]))] for b in w.index if len(base[b]["r20"])])
        p = float(mannwhitneyu(x.r20.values, ref, alternative="less").pvalue) if len(x) >= 5 else None
        xs = x.sort_values("date"); h = len(xs) // 2
        d1 = float(xs.r20.iloc[:h].median() - bmed["r20"]) if h else None; d2 = float(xs.r20.iloc[h:].median() - bmed["r20"]) if h else None
        md = float(x.r20.median())
        holds = bool(len(x) >= 30 and x.ticker.nunique() >= 20 and md - bmed["r20"] <= -0.05 and p is not None and p < 0.05 and d1 is not None and d1 <= -0.02 and d2 <= -0.02)
        out["kinds"][kind] = dict(n=int(len(x)), tickers=int(x.ticker.nunique()), r5_med=float(x.r5.median()), r20_med=md, mdd20_med=float(x.mdd20.median()),
                                  hit30=float(x.hit30.mean()), r20_share_neg=float((x.r20 < 0).mean()), base=bmed, diff_r20=md - bmed["r20"], p=p,
                                  half1=d1, half2=d2, holds=holds)
    return out, EVd

def main():
    fetch = "--no-fetch" not in sys.argv
    db.init(); t0 = time.time()
    if "--from-json" in sys.argv: E = json.load(open(ROOT / "model/events.json"))["events"]   # 사건 목록 재사용, 검증만 다시
    else: E = collect(fetch)
    print(f"사건 {len(E)}건 ({ {k: sum(1 for e in E if e['kind'] == k) for k in Q} }) · {time.time() - t0:.0f}s", flush=True)
    json.dump({"built": dt.datetime.now().isoformat(timespec="seconds"), "events": E}, open(ROOT / "model/events.json", "w"), ensure_ascii=False, default=str)
    S, EVd = study(E)
    json.dump(S, open(ROOT / "model/events_study.json", "w"), ensure_ascii=False, indent=1, default=float)
    for k, v in S["kinds"].items(): print(k, json.dumps(v, ensure_ascii=False, default=float))
    print(f"완료 {time.time() - t0:.0f}s")

if __name__ == "__main__":
    main()
