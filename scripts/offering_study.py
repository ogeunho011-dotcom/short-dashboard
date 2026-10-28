"""공모 전 펌핑(가격 미정 S-1/F-1, 나스닥 상장유지 미달 8-K 3.01, 최근 424B5/ATM) 표시가 성공률을 낮추는지 시점 기준(룩어헤드 없음) 검증.
라벨·평가표본은 short_borrow_study.py 와 동일 (셋업 10거래일 성공, 5폴드 표본외 구간만). 공시는 asof '전날까지' 제출된 것만 사용.
출력: model/offering_study.json"""
import sys, json, sqlite3; from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / "scripts")); sys.path.insert(0, str(ROOT))
import numpy as np, pandas as pd
import sa_lib as L
df, N = L.df, len(L.df)
con = sqlite3.connect(ROOT / "data/shortdash.sqlite")
SU = pd.read_pickle(ROOT / "data/setup_all.pkl").drop_duplicates(["ticker", "asof"])
SX = df[["ticker", "asof"]].merge(SU, on=["ticker", "asof"], how="left"); assert len(SX) == N
VALID = SX.valid.fillna(False).values.astype(bool) & (SX.nfut.fillna(0).values >= 10)
Y = (VALID & (SX.succ.fillna(0).values == 1)).astype(int)
FAIL = (VALID & (SX.fail.fillna(0).values == 1)).astype(int)
RET = SX.ret.values
ev = np.any([F["te"] for F in L.folds], 0) & VALID
fil = pd.read_sql("SELECT ticker, form, filed, items FROM filings", con); fil["filed"] = pd.to_datetime(fil.filed)
covered = set(fil.ticker)
import importlib; M = importlib.import_module("core.model")
asof = pd.to_datetime(df["asof"]).values; tk = df["ticker"].values
flags = {k: np.zeros(N, bool) for k in ("pend", "def301", "atm", "any")}
for t, g in fil.groupby("ticker"):
    idx = np.where(tk == t)[0]
    if not len(idx): continue
    G = g.sort_values("filed")
    for i in idx:
        a = pd.Timestamp(asof[i]); h = G[G.filed < a]
        if not len(h): continue
        st = M.reg_status(h, a)
        flags["pend"][i] = st["pending"]
        flags["def301"][i] = st["def301"]
        flags["atm"][i] = st["atm"]
flags["any"] = flags["pend"] | flags["def301"]
cov = np.isin(tk, list(covered))
def wil(k, n): return [round(float(x), 3) for x in L.wilson(k, n)] if n else [None, None]
def row(mask, name):
    s = ev & mask; n = int(s.sum()); k = int(Y[s].sum())
    return dict(name=name, n=n, hit=round(k / n, 4) if n else None, ci=wil(k, n), fail=round(float(FAIL[s].mean()), 4) if n else None,
                ret=round(float(np.nanmean(RET[s])), 4) if n else None)
# 폴드별 (일관성)
out = {"base_all": row(np.ones(N, bool), "전체"), "base_cov": row(cov, "공시 수집 종목"), "rows": [], "folds": {}}
for k, lab in [("pend", "가격 미정 S-1/F-1 대기"), ("def301", "8-K 3.01 상장유지 미달(180일 내)"), ("atm", "424B5/ATM 60일 내"), ("any", "가격 미정 등록 또는 3.01")]:
    out["rows"].append(row(cov & flags[k], lab + " — 있음")); out["rows"].append(row(cov & ~flags[k], lab + " — 없음"))
    fr = []
    for j, F in enumerate(L.folds):
        m = F["te"] & VALID & cov
        a, b = m & flags[k], m & ~flags[k]
        fr.append(dict(fold=j, n_flag=int(a.sum()), hit_flag=round(float(Y[a].mean()), 3) if a.sum() else None, hit_rest=round(float(Y[b].mean()), 3) if b.sum() else None))
    out["folds"][k] = fr
for r in out["rows"]: print(r)
for k, v in out["folds"].items(): print(k, v)
print(out["base_all"], out["base_cov"])
json.dump(out, open(ROOT / "model/offering_study.json", "w"), ensure_ascii=False, indent=1)
