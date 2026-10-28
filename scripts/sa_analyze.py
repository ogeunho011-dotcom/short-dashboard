"""사례표 + 카테고리 집계 + 사전신호 비교. 출력 data/sa_cases.pkl, model/sa_summary_part.json"""
import sys, json, re; from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
import pandas as pd, numpy as np
from sa_cases import SUCC, FAIL
ev = json.loads((ROOT / "data/sa_evidence.json").read_text())
A = pd.read_pickle(ROOT / "data/sa_alerts.pkl"); F = pd.read_pickle(ROOT / "data/sa_feat.pkl")
ds = pd.read_pickle(ROOT / "data/research_ds.pkl"); ds["asof"] = pd.to_datetime(ds["asof"])
sig = ["s_low_float", "s_runner", "s_ssr", "s_gap_hold", "s_vol", "s_offering_done", "s_catalyst", "s_reignite", "s_close_high", "dilution_recent"]
A = A.merge(F, on=["ticker", "asof"], how="left").merge(ds[["ticker", "asof"] + [c for c in sig if c in ds]], on=["ticker", "asof"], how="left")
first = A.sort_values("asof").groupby("event").first()
def link(v, kws):
    for kw in kws:
        for n in v["news"]:
            if kw.lower() in (n["title"] or "").lower(): return n["link"], n["title"][:110]
        for f in v["filings"]:
            if kw.lower() in ((f.get("title") or "") + " " + f["form"] + " " + (f.get("items") or "")).lower() and (f["in_window"] or kw.upper().startswith(("424", "S-", "F-"))):
                return f.get("doc") or f["url"], f'SEC {f["form"]} {f["filed"]}' + (f' — {f["title"][:80]}' if f.get("title") and not re.search(r"(?i)exchange|securities act|document", f["title"]) else "")
    return None, None
rows = []
for key, v in ev.items():
    cat, why, kws = (SUCC.get(key) or FAIL.get(key))
    t, d = key.split("|"); fr = first[(first.ticker == t) & (first["asof"] == pd.Timestamp(d))].iloc[0]
    u, src_t = link(v, kws)
    rows.append(dict(key=key, ticker=t, date=d, group=v["group"], pick=v["pick"], cat=cat, cause=why, link=u, src=src_t,
                     max5=float(fr.maxup5) if "maxup5" in fr else np.nan, maxup10=float(fr.maxup), minlo10=float(fr.minlo), d5=float(fr.d5), n_alerts=v["n_alerts"],
                     **{c: (float(fr[c]) if pd.notna(fr[c]) else np.nan) for c in ["price", "ret1", "ret5", "gap", "clv", "fade", "dist_hi20", "rvol", "vol_prev", "up_prev5", "dd60", "d_424b", "d_reg", "d_8k", "d_rs", "prob"] + [c for c in sig if c in fr]}))
C = pd.DataFrame(rows); C.to_pickle(ROOT / "data/sa_cases.pkl")
for g in ("success", "fail"):
    x = C[C.group == g]; vc = x.cat.value_counts()
    print(g, len(x)); print(pd.DataFrame({"n": vc, "%": (vc / len(x) * 100).round(1)}))
print("missing link", C.link.isna().sum(), C[C.link.isna()].key.tolist())

# ---- 근거 시점(경보일 대비) + 사전 특징 비교 ----
def src_date(key, u):
    v = ev[key]
    for n in v["news"]:
        if n["link"] == u: return n.get("date")
    for f in v["filings"]:
        if (f.get("doc") or f["url"]) == u: return f["filed"]
    return None
C["src_date"] = [src_date(k, u) if u else None for k, u in zip(C.key, C.link)]
def _lag(s, d):
    try:
        t = pd.to_datetime(s, utc=True, format="mixed")
        return np.nan if pd.isna(t) else (t.tz_localize(None).normalize() - pd.Timestamp(d)).days
    except Exception: return np.nan
C["lag"] = [_lag(s, d) if s else np.nan for s, d in zip(C.src_date, C.date)]
C["d424_30"] = C.d_424b <= 30; C["reg30"] = C.d_reg <= 30; C["mom5"] = C.ret5 >= 0.5; C["prev_spike"] = C.up_prev5 >= 0.4
C["day20"] = C.ret1 >= 0.2; C["rvol5"] = C.rvol >= 5; C["rvol_lo"] = C.rvol < 1.5; C["k8_2"] = C.d_8k <= 2; C["rs60"] = C.d_rs <= 60
FEATS = ["d424_30", "reg30", "mom5", "prev_spike", "day20", "rvol5", "rvol_lo", "k8_2", "rs60", "s_low_float", "s_runner", "s_ssr", "s_gap_hold", "s_offering_done"]
G = C[C.cat != "데이터 오류"]
cmp_ = G.groupby("group")[FEATS].apply(lambda x: (x.fillna(0) >= 1).mean()).T
print(cmp_.round(2))
print(G.groupby("cat")[["d424_30", "mom5", "prev_spike", "rvol5", "k8_2"]].apply(lambda x: (x.fillna(0) >= 1).mean()).round(2).assign(n=G.cat.value_counts()))
print("lag (success, known):", G[(G.group == "success") & G.lag.notna() & (G.cat != "원인 불명")].lag.describe())
C.to_pickle(ROOT / "data/sa_cases.pkl")
