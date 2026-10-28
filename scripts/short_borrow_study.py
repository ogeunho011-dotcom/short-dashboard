"""공매도 잔고(FINRA 공식, 2023-12~) 를 시점 기준(공표 지연 8영업일)으로 다시 붙여 점수/확률 모델에 넣을 근거가 있는지 검증.
같은 5폴드 워크포워드(표본외)·셋업 라벨(10거래일). 출력: model/short_study.json
대차이자/차입가능 수량은 무료 과거 이력이 없어 검증 불가 → 이 스크립트는 공매도 잔고만 다룸."""
import sys, json, sqlite3, time; from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / "scripts")); sys.path.insert(0, str(ROOT))
import numpy as np, pandas as pd
import sa_lib as L
from sklearn.metrics import roc_auc_score
from sklearn.isotonic import IsotonicRegression
t0 = time.time()
df, N = L.df, len(L.df)
p = L.p
con = sqlite3.connect(ROOT / "data/shortdash.sqlite")

# ---------- 라벨 (target_grid 와 동일한 셋업 정의) ----------
SU = pd.read_pickle(ROOT / "data/setup_all.pkl").drop_duplicates(["ticker", "asof"])
SX = df[["ticker", "asof"]].merge(SU, on=["ticker", "asof"], how="left"); assert len(SX) == N
VALID = SX.valid.fillna(False).values.astype(bool) & (SX.nfut.fillna(0).values >= 10)
Y = (VALID & (SX.succ.fillna(0).values == 1)).astype(int)
FAIL = (VALID & (SX.fail.fillna(0).values == 1)).astype(int)
RET = SX.ret.values
FL = L.FL; DD10 = FL[:, :10].min(1) - 1  # 10일 내 최저 (진입가 대비)

# ---------- 시점 기준 공매도 잔고 ----------
si = pd.read_sql("SELECT ticker, settle_date, si, avg_vol, dtc FROM short_interest", con)
si["settle_date"] = pd.to_datetime(si.settle_date)
si = si.sort_values(["ticker", "settle_date"])
si["prev"] = si.groupby("ticker")["si"].shift(1)
si["prev_settle"] = si.groupby("ticker")["settle_date"].shift(1)
si.loc[(si.settle_date - si.prev_settle).dt.days > 20, "prev"] = np.nan   # 중간 결제일 빠지면 변화율 안 씀
si["pub"] = si.settle_date + pd.offsets.BDay(8)
facts = {k[6:]: json.loads(v) for k, v in con.execute("SELECT k,v FROM kv WHERE k LIKE 'facts:%'").fetchall()}
sh = pd.DataFrame([(t, pd.Timestamp(x["filed"]), float(x["val"])) for t, f in facts.items() for x in (f or {}).get("shares", [])
                   if x.get("filed") and x.get("val")], columns=["ticker", "filed", "shares"]).sort_values("filed")
base = df[["ticker", "asof"]].reset_index().sort_values("asof")
m = pd.merge_asof(base, si.sort_values("pub")[["ticker", "pub", "si", "prev", "dtc"]], left_on="asof", right_on="pub", by="ticker", direction="backward",
                  tolerance=pd.Timedelta(days=45))
m = pd.merge_asof(m.sort_values("asof"), sh, left_on="asof", right_on="filed", by="ticker", direction="backward", tolerance=pd.Timedelta(days=400))
m = m.set_index("index").sort_index()
SI_FLOAT = (m.si / m.shares * 100).where(m.shares > 0).values
SI_CHG = ((m.si / m.prev - 1) * 100).values
DTC = m.dtc.values
new = {"si_float": np.minimum(SI_FLOAT / float(p["si_float_pct"]), 1.5),
       "si_change": np.clip(SI_CHG / float(p["si_change_pct"]), 0, 1.5),
       "dtc": np.minimum(DTC / float(p["dtc_days"]), 1.5)}
cov = {k: dict(old=float(df["s_" + k].notna().mean()), new=float(np.isfinite(v).mean())) for k, v in new.items()}
print("coverage", cov, flush=True)

def wil(k, n): return [float(x) for x in L.wilson(k, n)] if n else [None, None]
ev = np.any([F["te"] for F in L.folds], 0) & VALID
def bucket(x, edges, labels):
    out = []
    for lo, hi, lab in zip(edges[:-1], edges[1:], labels):
        s = ev & (x >= lo) & (x < hi)
        n = int(s.sum()); k = int(Y[s].sum())
        out.append(dict(b=lab, n=n, hit=k / n if n else None, ci=wil(k, n), fail=float(FAIL[s].mean()) if n else None,
                        ret=float(np.nanmean(RET[s])) if n else None, dd10=float(np.nanmedian(DD10[s])) if n else None))
    s = ev & ~np.isfinite(x); n = int(s.sum())
    out.append(dict(b="없음", n=n, hit=float(Y[s].mean()) if n else None, fail=float(FAIL[s].mean()) if n else None))
    return out
UNI = {"base": float(Y[ev].mean()),
       "si_float": bucket(SI_FLOAT, [0, 5, 10, 15, 20, 30, 1e9], ["<5%", "5-10%", "10-15%", "15-20%", "20-30%", "30%+"]),
       "si_change": bucket(SI_CHG, [-1e9, -20, -5, 5, 20, 50, 1e9], ["≤-20%", "-20~-5%", "±5%", "+5~20%", "+20~50%", "+50%+"]),
       "dtc": bucket(DTC, [0, 1, 2, 3, 5, 10, 1e9], ["<1일", "1-2", "2-3", "3-5", "5-10", "10일+"])}
for k in ("si_float", "si_change", "dtc"):
    print(k, [(b["b"], b["n"], round(b["hit"] or 0, 3), round(b["fail"] or 0, 3)) for b in UNI[k]], flush=True)

# ---------- 모델 재학습 비교: 기존 SI 열 vs FINRA 재구성 열 ----------
y0 = L.y.copy()
def run(Smat, mask=VALID, tag=""):
    L.y = Y; S0 = L.S; L.S = Smat
    oraw = np.full(N, np.nan); oof = np.full(N, np.nan); folds = []; W = []
    for F in L.folds:
        fit, cal, te = F["fit"] & mask, F["cal"] & mask, F["te"]
        w, info = L.gated_weights(fit); W.append(w)
        rc, rt = L.weighted(Smat[cal], w), L.weighted(Smat[te], w)
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0.001, y_max=0.999).fit(rc, Y[cal])
        oraw[te] = rt; oof[te] = iso.predict(rt)
        thr = np.quantile(rc, 0.95); e = te & mask
        sel = e & (rt_full := np.full(N, -1.0)).astype(bool)  # placeholder
        rtf = np.full(N, -1e9); rtf[te] = rt; s5 = e & (rtf >= thr)
        folds.append(dict(k=F["k"], auc=float(roc_auc_score(Y[e], oof[e])), n5=int(s5.sum()), prec5=float(Y[s5].mean()) if s5.any() else None))
    L.S = S0; L.y = y0
    e = ev
    top = np.zeros(N, bool)
    for F, fd in zip(L.folds, folds): pass
    # 상위 5% (폴드별 보정구간 임계) 합산
    s5 = np.zeros(N, bool)
    for F in L.folds:
        L.y = Y; L.S = Smat; w, _ = L.gated_weights(F["fit"] & mask); rc = L.weighted(Smat[F["cal"] & mask], w); L.S = S0; L.y = y0
        s5 |= F["te"] & mask & (oraw >= np.quantile(rc, 0.95))
    k, n = int(Y[s5].sum()), int(s5.sum())
    wmean = {c[2:]: float(np.mean([w_[j] for w_ in W])) for j, c in enumerate(L.SIG) if c[2:] in ("si_float", "si_change", "dtc")}
    r = dict(auc=float(roc_auc_score(Y[e], oof[e])), top5=dict(n=n, prec=k / n, ci=wil(k, n), fail=float(FAIL[s5].mean()), ret=float(np.nanmean(RET[s5]))),
             folds=folds, w_si=wmean)
    print(tag, round(r["auc"], 4), round(r["top5"]["prec"], 4), n, wmean, flush=True)
    return r, oraw
S_old = L.S.copy()
S_new = L.S.copy()
for k, v in new.items():
    if "s_" + k in L.SIG: S_new[:, L.SIG.index("s_" + k)] = v
S_none = L.S.copy()
for k in new:
    if "s_" + k in L.SIG: S_none[:, L.SIG.index("s_" + k)] = np.nan
R = {}
R["old"], o_old = run(S_old, tag="기존(SI 457종목, 1년)")
R["finra"], o_new = run(S_new, tag="FINRA 재구성(1,941종목, 2023-12~)")
R["no_si"], _ = run(S_none, tag="SI 빼고")

# ---------- 조건부: 모델 상위 20% 안에서 SI 가 추가로 구분하나 (양방향) ----------
COND = []
q80 = np.nanquantile(o_new[ev], 0.8)
hi = ev & (o_new >= q80)
for lab, s in [("상위20% 전체", hi), ("+ 유통대비 숏 20%+", hi & (SI_FLOAT >= 20)), ("+ 유통대비 숏 <5%", hi & (SI_FLOAT < 5)),
               ("+ 숏 증가 20%+", hi & (SI_CHG >= 20)), ("+ 숏 감소 20%+", hi & (SI_CHG <= -20)),
               ("+ 커버일수 5일+", hi & (DTC >= 5)), ("+ 유통대비 30%+ & 숏 감소", hi & (SI_FLOAT >= 30) & (SI_CHG < -5))]:
    n = int(s.sum()); k = int(Y[s].sum())
    COND.append(dict(b=lab, n=n, hit=k / n if n else None, ci=wil(k, n), fail=float(FAIL[s].mean()) if n else None, dd10=float(np.nanmedian(DD10[s])) if n else None))
print("cond", [(c["b"], c["n"], round(c["hit"] or 0, 3), round(c["fail"] or 0, 3)) for c in COND], flush=True)
out = dict(created=time.strftime("%Y-%m-%d %H:%M"), rows=int(ev.sum()), coverage=cov, univariate=UNI, models=R, conditional=COND,
           note="공표일 = 결제일+8영업일 이후에만 사용. 주식수는 그 시점까지 제출된 SEC 공시 기준(없으면 결측). 대차이자/차입가능 수량은 무료 과거 이력 없음 → 미검증.")
(ROOT / "model/short_study.json").write_text(json.dumps(out, ensure_ascii=False, default=float), encoding="utf-8")
print("saved", round(time.time() - t0), flush=True)

# ---------- 보정 규칙 검증: 종합점수(원점수)에서 과밀/숏 이탈 감점이 표본외 상위 선정을 개선하나 ----------
# 규칙은 학습구간(fit)에서만 방향 확인 후, 같은 폴드 test 로 평가.
L.y = Y; L.S = S_new
RULES = {"crowd30": lambda: np.nan_to_num(SI_FLOAT) >= 30, "drop20": lambda: np.nan_to_num(SI_CHG) <= -20,
         "crowd30_or_drop20": lambda: (np.nan_to_num(SI_FLOAT) >= 30) | (np.nan_to_num(SI_CHG) <= -20)}
ADJ = {}
for rn, rf in RULES.items():
    flag = rf()
    for pen in (0, 3, 5, 8):
        s5 = np.zeros(N, bool); per = []; fitdir = []
        for F in L.folds:
            w, _ = L.gated_weights(F["fit"] & VALID)
            fm = F["fit"] & VALID; fitdir.append(float(Y[fm & flag].mean() - Y[fm & ~flag].mean()) if (fm & flag).any() else None)
            rc = L.weighted(S_new[F["cal"] & VALID], w) - pen * flag[F["cal"] & VALID]
            rt = L.weighted(S_new[F["te"]], w) - pen * flag[F["te"]]
            full = np.full(N, -1e9); full[F["te"]] = rt
            sel = F["te"] & VALID & (full >= np.quantile(rc, 0.95)); s5 |= sel
            per.append(round(float(Y[sel].mean()), 4) if sel.any() else None)
        k, n = int(Y[s5].sum()), int(s5.sum())
        ADJ[f"{rn}_{pen}"] = dict(n=n, prec=k / n, ci=wil(k, n), fail=float(FAIL[s5].mean()), folds=per, fit_diff=fitdir, flagged_share=float(flag[ev].mean()))
        print(rn, pen, n, round(k / n, 4), round(float(FAIL[s5].mean()), 4), per, [None if v is None else round(v, 3) for v in fitdir], flush=True)
L.S = S_old; L.y = y0
out["score_adj"] = ADJ
(ROOT / "model/short_study.json").write_text(json.dumps(out, ensure_ascii=False, default=float), encoding="utf-8")
