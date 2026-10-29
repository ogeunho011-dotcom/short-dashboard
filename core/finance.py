"""🏦 자금줄·세력 구조 (참고 표시 전용 — 점수 미반영, 검증 결과 model/finance_study.json).
커뮤니티 글 방식('같은 자금줄이 전환사채+ELOC 를 같이 쥔 소형주는 극단적으로 펌핑/덤핑')을 무료 데이터로 자동화:
  ① 자금줄 추적: SEC 전문검색으로 찾은 희석성 투자자(전환사채·ELOC 자주 쓰는 곳) × 종목 × 수단 (scripts/finance_build.py 스냅샷)
  ② ELOC 재판매 등록(S-1/F-1/S-3/F-3) 접수일 + 같은 파일번호 EFFECT(효력) 날짜 → '효력 대기 / 효력 직후'
  ③ 역분할 횟수·날짜 (yfinance 분할 기록)   ④ 매물대: 최근 60/120일 거래량 중 현재가 위에서 거래된 비율 + 가장 가까운 큰 매물대
  ⑤ 같은 자금줄 다른 종목의 과거 결과(역분할·EFFECT 뒤 60거래일 최대 상승/최대 하락, 180일 안 추가 역분할)
  ⑥ 워런트 오버행(XBRL 워런트 ÷ 주식수)
없는 값은 None → 화면에 '데이터 없음'. 스냅샷은 공개 공시만 담음(비밀값 없음)."""
import json, functools, datetime as dt
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SNAP_PATH = "data/finance/financiers.json"         # alert-data 브랜치 (주간 갱신) → 없으면 model/financiers.json
SIGNS = [("fin", "희석성 자금줄 공시 (최근 1년)"), ("both", "같은 자금줄이 전환사채+ELOC 동시"),
         ("pending", "ELOC 재판매 등록 효력 대기"), ("eff30", "ELOC 등록 효력 30일 이내"),
         ("rs90", "역분할 90일 이내"), ("rsmulti", "역분할 2년 내 2회↑"), ("oh", "위 매물대 ≥ 60일 거래량 70%")]
SIGN_KO = dict(SIGNS)

@functools.lru_cache(maxsize=1)
def _model_file():
    try: return json.loads((ROOT / "model/financiers.json").read_text())
    except Exception: return {}

def snapshot():
    try:
        from . import alerts as AL
        r = AL.remote_get(SNAP_PATH, ttl=6 * 3600)
        if r and r.get("tickers"): return r
    except Exception: pass
    return _model_file()

@functools.lru_cache(maxsize=1)
def study():
    try: return json.loads((ROOT / "model/finance_study.json").read_text())
    except Exception: return {}

# ---------------------------------------------------------------- 가격 정리·매물대
def reverse_splits(info=None, snap_rs=None):
    """[(날짜 Timestamp, 비율<1)] — yfinance 분할 기록 + 스냅샷. 비율 0.1667 = 1:6 역분할."""
    out = {}
    for d, r in ((info or {}).get("splits") or []):
        try:
            if 0 < float(r) < 1: out[pd.Timestamp(d[:10])] = float(r)
        except Exception: pass
    for d, r in (snap_rs or []):
        out.setdefault(pd.Timestamp(d[:10]), float(r))
    return sorted(out.items())

def adjust_px(px, rs):
    """DB 일봉에 역분할이 미조정으로 남아 있으면(분할일 시가/전날 종가 ≈ 1/비율) 분할 전 가격을 맞춰 연속 시계열로."""
    if px is None or not len(px) or not rs: return px
    g = px.sort_values("date").reset_index(drop=True).copy()
    d = pd.to_datetime(g["date"]).values
    for day, r in rs:
        i = int(np.searchsorted(d, np.datetime64(day), side="left"))
        if i <= 0 or i >= len(g): continue
        j = min(i + 2, len(g) - 1)
        prev = g.close.iloc[i - 1]
        if not prev or not np.isfinite(prev): continue
        best = max(range(i, j + 1), key=lambda k: abs(np.log(max(g.open.iloc[k] or prev, 1e-9) / g.close.iloc[k - 1])))
        jump = (g.open.iloc[best] or prev) / g.close.iloc[best - 1]
        if abs(np.log(jump) - np.log(1 / r)) < abs(np.log(jump)) and abs(np.log(jump)) > np.log(1.8):
            for c in ("open", "high", "low", "close"):
                if c in g: g.loc[: best - 1, c] = g.loc[: best - 1, c] / r
            if "volume" in g: g.loc[: best - 1, "volume"] = g.loc[: best - 1, "volume"] * r
    return g

def volume_profile(px, n=60, price=None, bins=24):
    """최근 n거래일: 현재가 위에서 거래된 거래량 비율(%) + 가장 가까운 큰 매물대(가격대·비중)."""
    if px is None or len(px) < max(10, n // 3): return None
    g = px.sort_values("date").tail(n)
    tp = ((g.high + g.low + g.close) / 3).values.astype(float); v = g.volume.values.astype(float)
    ok = np.isfinite(tp) & np.isfinite(v) & (tp > 0)
    tp, v = tp[ok], v[ok]
    if not len(tp) or v.sum() <= 0: return None
    p = float(price or g.close.dropna().iloc[-1])
    above = float(v[tp > p].sum() / v.sum() * 100)
    lo, hi = np.log(tp.min()), np.log(tp.max())
    zone = None
    if hi > lo and tp.max() > p:
        e = np.linspace(lo, hi, bins + 1); idx = np.clip(np.searchsorted(e, np.log(tp), side="right") - 1, 0, bins - 1)
        share = np.bincount(idx, weights=v, minlength=bins) / v.sum()
        mids = np.exp((e[:-1] + e[1:]) / 2)
        cand = [k for k in range(bins) if np.exp(e[k + 1]) > p * 1.02 and share[k] >= max(0.08, 1.5 / bins)]
        if cand:
            k = min(cand, key=lambda k: mids[k])
            zone = {"lo": float(max(np.exp(e[k]), p)), "hi": float(np.exp(e[k + 1])), "share": float(share[k] * 100), "pct": float(max(0.0, (np.exp(e[k]) / p - 1) * 100)), "pct_hi": float((np.exp(e[k + 1]) / p - 1) * 100)}
    return {"n": int(len(tp)), "above": above, "zone": zone}

# ---------------------------------------------------------------- ELOC 등록서류 본문: 재판매 등록 주식 수·매수 가격 할인 (앱에서 1건만, 30일 캐시)
import re
_NUM = r"([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,})"
def parse_terms(t):
    out = {}
    m = re.search(r"relates to the (?:offer and )?(?:re)?sale[^.]{0,300}?up to (?:an aggregate of )?" + _NUM, t, re.I) \
        or re.search(r"(?:resale|offer and sale)[^.]{0,200}?up to (?:an aggregate of )?" + _NUM + r" (?:shares|ordinary shares|Class A|of our)", t, re.I)
    if m: out["shares"] = float(m.group(1).replace(",", ""))
    p = sorted({float(x) for x in re.findall(r"\b([89]\d(?:\.\d+)?)% of the (?:lowest|average) (?:daily |applicable |intraday )*(?:VWAP|volume[- ]weighted|traded price|closing (?:sale )?price|sale price)", t, re.I)})
    if p: out["pct"] = p
    m = re.search(r"(?:purchase|sell)[^.]{0,120}?up to (?:an aggregate (?:of )?)?\$\s?([0-9][0-9.,]*)\s?(million|billion)?", t, re.I)
    if m:
        v = float(m.group(1).replace(",", "").rstrip(".")); u = (m.group(2) or "").lower()
        out["commit"] = v * (1e6 if u == "million" else 1e9 if u == "billion" else 1)
    return out

def eloc_terms(cik, doc):
    """doc = 'adsh:파일명'. 반환 {'shares': 등록 주식 수, 'pct': 매수가 = 시장가의 몇 %, 'commit': 약정 한도 $} — 못 읽으면 None 값."""
    if not cik or not doc or ":" not in doc: return None
    from . import db, sources as src
    k = f"eloc_terms:{doc}"
    c = db.kv_get(k, 30 * 86400)
    if c is not None: return c or None
    adsh, fn = doc.split(":", 1)
    out = {}
    try:
        r = src._sec(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{adsh.replace('-', '')}/{fn}", timeout=20)
        if r.status_code == 200:
            import html as _h
            t = re.sub(r"<[^>]+>", " ", r.text[:800000]); t = re.sub(r"\s+", " ", _h.unescape(t))
            out.update(parse_terms(t))
    except Exception:
        return None
    db.kv_set(k, out)
    return out or None

# ---------------------------------------------------------------- 메인
def _d(s): return pd.Timestamp(s) if s else None

def compute(ticker, px=None, info=None, facts=None, asof=None, snap=None, fetch_docs=False):
    snap = snap if snap is not None else snapshot()
    T = (snap.get("tickers") or {}).get((ticker or "").upper()) or {}
    FN = snap.get("financiers") or {}
    asof = pd.Timestamp(asof) if asof is not None else (pd.Timestamp(px["date"].max()) if px is not None and len(px) else pd.Timestamp(dt.date.today()))
    out = {"ticker": ticker, "asof": str(asof.date()), "built": snap.get("built"), "has_snap": bool(snap.get("tickers"))}
    # ① 자금줄
    fins = []
    for f in T.get("fin") or []:
        if not f.get("first") or _d(f["first"]) >= asof: continue
        meta = FN.get(f["k"]) or {}
        fins.append(dict(k=f["k"], label=meta.get("label", f["k"]), first=f["first"], last=f.get("last"), n=f.get("n"),
                         conv=f.get("conv"), eloc=f.get("eloc"), stats=meta.get("stats")))
    fins.sort(key=lambda f: f.get("last") or "", reverse=True)
    out["fin"] = fins
    recent = [f for f in fins if f.get("last") and (asof - _d(f["last"])).days <= 365]
    both = [f for f in fins if f.get("conv") and f.get("eloc")]
    # ② ELOC 등록
    regs = sorted([r for r in T.get("regs") or [] if r.get("filed") and _d(r["filed"]) < asof], key=lambda r: r["filed"])
    for r in regs:
        e = r.get("effect")
        r["eff_known"] = e if e and _d(e) <= asof else None
        r["wd"] = r.get("withdrawn") if r.get("withdrawn") and _d(r["withdrawn"]) <= asof else None
    out["regs"] = regs[-6:]
    pend = [r for r in regs if not r["eff_known"] and not r["wd"] and (asof - _d(r["filed"])).days <= 180]
    effs = sorted(r["eff_known"] for r in regs if r["eff_known"])
    out["pending"] = pend[-1] if pend else None
    out["last_eff"] = effs[-1] if effs else None
    out["eff_days"] = int((asof - _d(effs[-1])).days) if effs else None
    # ③ 역분할
    rs = [(d, r) for d, r in reverse_splits(info, T.get("rs")) if d <= asof]
    out["rs"] = [[str(d.date()), r] for d, r in rs]
    out["rs_n2y"] = sum(1 for d, _ in rs if (asof - d).days <= 730)
    out["rs_days"] = int((asof - rs[-1][0]).days) if rs else None
    # ④ 매물대
    vp60 = vp120 = None
    if px is not None and len(px):
        g = adjust_px(px[pd.to_datetime(px["date"]) <= asof], rs)
        vp60, vp120 = volume_profile(g, 60), volume_profile(g, 120)
    out["vp60"], out["vp120"] = vp60, vp120
    # ⑥ 워런트 오버행 (XBRL, asof 이전 접수분)
    out["warr"] = None
    try:
        W = [x for x in (facts or {}).get("warrants", []) if x.get("filed") and x.get("val") and _d(x["filed"]) < asof]
        S = [x for x in (facts or {}).get("shares", []) if x.get("filed") and x.get("val") and _d(x["filed"]) < asof]
        if W and S:
            w = max(W, key=lambda x: (x["end"] or "", x["filed"])); s = max(S, key=lambda x: (x["end"] or "", x["filed"]))
            if (asof - _d(w["end"])).days <= 400 and s["val"] > 0:
                out["warr"] = {"w": float(w["val"]), "sh": float(s["val"]), "pct": float(w["val"] / s["val"] * 100), "end": w["end"]}
    except Exception: pass
    out["exch"] = T.get("exch")
    out["terms"] = None
    if fetch_docs and regs:
        try:
            r = (pend or regs)[-1]
            tm = eloc_terms(T.get("cik"), r.get("doc"))
            if tm:
                sh = (info or {}).get("sharesOutstanding")
                if tm.get("shares") and sh: tm = dict(tm, pct_out=tm["shares"] / sh * 100)
                out["terms"] = dict(tm, filed=r["filed"])
        except Exception: pass
    sg = {"fin": bool(recent) if out["has_snap"] else None, "both": bool(both) if out["has_snap"] else None,
          "pending": bool(pend) if out["has_snap"] else None,
          "eff30": (out["eff_days"] is not None and out["eff_days"] <= 30) if out["has_snap"] else None,
          "rs90": out["rs_days"] is not None and out["rs_days"] <= 90, "rsmulti": out["rs_n2y"] >= 2,
          "oh": (vp60["above"] >= 70) if vp60 else None}
    out["signs"] = sg; out["on"] = [k for k, _ in SIGNS if sg.get(k)]
    out["n"] = len(out["on"]); out["m"] = len(SIGNS)
    return out

# ---------------------------------------------------------------- 표시용
def _pct(v): return "데이터 없음" if v is None else f"{v:.0f}%"

def _ratio(r):
    try: return f"1:{round(1 / r):g}" if r < 1 else f"{r:g}:1"
    except Exception: return "?"

def values(F):
    """신호별 설명 문장 (데이터 없음은 None)."""
    v = {}
    if F["fin"]:
        v["fin"] = " · ".join(f"{f['label']} (공시 {f['first']}~{f['last']})" for f in F["fin"][:3])
    elif F["has_snap"]: v["fin"] = "추적 중인 자금줄 이름이 공시에 없음"
    bt = [f for f in F["fin"] if f.get("conv") and f.get("eloc")]
    if bt: v["both"] = " · ".join(f"{f['label']}: 전환사채 {f['conv']} · ELOC {f['eloc']} 첫 언급" for f in bt[:2])
    elif F["has_snap"]: v["both"] = "전환사채+ELOC 를 같이 쥔 자금줄 없음"
    if F["pending"]:
        p = F["pending"]; v["pending"] = f"{'/'.join(sorted(set(p.get('forms') or [])))} {p['filed']} 접수 · 파일 {p.get('file_num') or '?'} · 아직 EFFECT 없음"
    elif F["has_snap"]: v["pending"] = "대기 중인 ELOC 등록 없음" if not F["regs"] else f"최근 ELOC 등록 {F['regs'][-1]['filed']} (효력 {F['regs'][-1].get('eff_known') or '없음/철회'})"
    if F["last_eff"]: v["eff30"] = f"마지막 ELOC 등록 효력 {F['last_eff']} ({F['eff_days']}일 전)"
    elif F["has_snap"]: v["eff30"] = "ELOC 등록 효력 기록 없음"
    v["rs90"] = f"마지막 역분할 {F['rs'][-1][0]} ({_ratio(F['rs'][-1][1])}, {F['rs_days']}일 전)" if F["rs"] else "역분할 기록 없음"
    v["rsmulti"] = (f"2년 내 {F['rs_n2y']}회 · 전체 " + ", ".join(f"{d} {_ratio(r)}" for d, r in F["rs"][-5:])) if F["rs"] else "역분할 기록 없음"
    if F["vp60"]:
        z = F["vp60"]["zone"]
        v["oh"] = (f"60일 {F['vp60']['above']:.0f}% · 120일 {_pct((F['vp120'] or {}).get('above'))} 가 현재가 위에서 거래"
                   + (f" · 가장 가까운 큰 매물대 ${z['lo']:.4g}~${z['hi']:.4g} (+{z['pct']:.0f}~{z.get('pct_hi', z['pct']):.0f}%, 거래량 {z['share']:.0f}%)" if z else " · 위쪽 큰 매물대 없음"))
    return v

def analog_text(F):
    """같은 자금줄 다른 종목 과거 결과 한 줄씩."""
    L = []
    for f in F["fin"][:3]:
        s = f.get("stats") or {}
        for ev, nm in (("eff", "ELOC 효력 뒤"), ("rs", "역분할 뒤")):
            x = s.get(ev)
            if x and x.get("n"):
                L.append(f"{f['label']} · {nm} {x['n']}건: 60거래일 최대 상승 중앙 +{x['up_med']:.0f}% (+100%↑ {x['up100']:.0f}%) · "
                         f"최대 하락 중앙 {x['dd_med']:.0f}% · 180일 안 추가 역분할 {x['rs180']:.0f}%")
    return L

def line(F):
    if not F: return None
    on = [SIGN_KO[k] for k in F["on"]]
    s = f"🏦 자금줄·세력 구조 {F['n']}/{F['m']} (참고, 점수 미반영)" + (f": {', '.join(on)}" if on else "")
    if F["fin"]: s += f" · 자금줄 {', '.join(f['label'] for f in F['fin'][:2])}"
    if F["pending"]: s += f" · ELOC 등록 {F['pending']['filed']} 효력 대기"
    tm = F.get("terms") or {}
    if tm.get("shares"): s += f" · 재판매 등록 {tm['shares']:,.0f}주" + (f"(주식수의 {tm['pct_out']:.0f}%)" if tm.get("pct_out") else "")
    if F["vp60"]: s += f" · 위 매물대 {F['vp60']['above']:.0f}%"
    return s
