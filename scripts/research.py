"""정밀 검증: 다중 폴드 워크포워드 + 모델 비교(가중점수/게이트 가중/로지스틱/GBM) + 확률 보정 점검 + 청산 규칙 중첩(nested) 탐색.
입력: data/research_ds.pkl (scripts/research_build.py 로 생성). 출력: model/research.json (+ GBM 이 이기면 model/gbm.pkl), data/research_report.md
주의: 표본은 '현재' 유니버스에서 뽑았으므로 생존 편향이 있음(상폐 종목 누락 → 결과가 실제보다 좋게 나올 수 있음)."""
import sys, json, math, time, itertools, pickle
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from core import model as M, params as P
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score, brier_score_loss, log_loss

rng = np.random.default_rng(7)
TGT, HOLD_LBL, COST, ALLOC = 1.30, 5, 0.006, 0.10
NO_CONF = {"coil", "theme", "low_inst", "low_float"}

def wilson(k, n, z=1.96):
    if n == 0: return (0.0, 0.0)
    ph = k / n; d = 1 + z * z / n; c = ph + z * z / (2 * n); r = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n))
    return ((c - r) / d, (c + r) / d)

def boot_ci(x, B=2000):
    x = np.asarray(x, float)
    if len(x) < 2: return (float("nan"), float("nan"))
    m = rng.choice(x, (B, len(x))).mean(1); return (float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5)))

# ---------------- 데이터 ----------------
df = pd.read_pickle(ROOT / "data/research_ds.pkl")
df["asof"] = pd.to_datetime(df["asof"])
p = P.load()
df = df[(df.price >= 0.05) & (df.price <= float(p.get("univ_max_price", 10)) * 1.5) & (df.dv20 >= float(p.get("univ_min_dv_k", 100)) * 1e3) & (df.zero20 <= 3)]
df = df[df.fh.apply(len) == 10].sort_values(["asof", "ticker"]).reset_index(drop=True)
FH, FL, FO, FC = (np.stack(df[c].values) for c in ("fh", "fl", "fo", "fc"))
df["hit"] = (FH[:, :HOLD_LBL].max(1) >= TGT).astype(int)
SIG = [c for c in df.columns if c.startswith("s_") and df[c].notna().sum() > 100 and df[c].nunique() > 1]
S = df[SIG].astype(float).values
y = df.hit.values
print("rows", len(df), "tickers", df.ticker.nunique(), "days", df["asof"].nunique(), "base", y.mean().round(4), "signals", len(SIG), flush=True)

# 종목별 순번(거래일 근사) — 쿨다운용
df["seq"] = df.groupby("ticker").cumcount()

# ---------------- 폴드 ----------------
dates = np.array(sorted(df["asof"].unique()))
blocks = np.array_split(dates, 6)
EMB = 5
folds = []
for k in range(1, 6):
    tr_dates = np.concatenate(blocks[:k])[:-EMB]
    te = df["asof"].isin(blocks[k]).values
    tr = df["asof"].isin(tr_dates).values
    cut = tr_dates[int(len(tr_dates) * 0.75)]
    fit = tr & (df["asof"] < cut).values
    cal = tr & (df["asof"] >= cut + pd.Timedelta(days=7)).values      # 보정 구간 앞에도 엠바고
    folds.append(dict(k=k, tr=tr, fit=fit, cal=cal, te=te, span=(str(blocks[k][0])[:10], str(blocks[k][-1])[:10])))

# ---------------- 모델 ----------------
def weighted(S, w):
    """앱 score() 와 동일(신호 1.0 상한) + 동점 해소용 미세항(신호 3.0 상한의 1%)"""
    on = ~np.isnan(S); den = (on * w).sum(1)
    num = np.nansum(np.minimum(S, 1.0) * w, 1) + 0.01 * np.nansum(np.minimum(S, 3.0) * w, 1)
    return np.where(den > 0, num / np.maximum(den, 1e-9) * 100, 0.0)

WK = {k: wk for k, wk, _ in M.SIGNALS}
W0 = np.array([float(p.get(WK.get(c[2:], ""), 0) or 0) for c in SIG])
def saved_score(idx):
    sc = weighted(S[idx], W0)
    return sc * np.where(df.dilution_recent.values[idx], 1 - float(p["dilution_penalty"]), 1.0)

def gated_weights(idx):
    yy = y[idx]; base = yy.mean(); out = {}
    w = np.zeros(len(SIG))
    for j, c in enumerate(SIG):
        on = S[idx, j] >= 1
        n = int(on.sum()); k = int(yy[on].sum()) if n else 0
        lift = (k / n) / base if n and base else 0
        lo = wilson(k, n)[0]
        if n < 25 or lift < 1: w[j] = 0
        else: w[j] = min(lift, 3.0) * (1.0 if lo > base else 0.5)
        out[c[2:]] = dict(n=n, hit=k / n if n else None, lift=lift, lo=lo, w=float(w[j]))
    return w, out

def Xmat(idx):
    X = np.nan_to_num(np.minimum(S[idx], 3.0), nan=0.0)
    miss = np.isnan(S[idx]).astype(float)
    ex = np.c_[np.log(df.price.values[idx]), np.log1p(df.dv20.values[idx]), df.dilution_recent.values[idx].astype(float), df.regime.values[idx].astype(float)]
    return np.c_[X, miss, ex]

class Std:
    def fit(self, X): self.m = X.mean(0); self.s = X.std(0) + 1e-9; return self
    def __call__(self, X): return (X - self.m) / self.s

def fit_predict(name, fit, cal, te):
    """fit 구간에서 학습 → cal 구간에서 isotonic 보정 → te 확률. 반환 (p_cal, p_te, raw_te, artefact)"""
    if name == "M0_saved":
        fit = fit  # 학습 없음 (저장 가중치)
        r_cal, r_te = saved_score(cal), saved_score(te); art = None
    elif name == "M1_gated":
        w, info = gated_weights(fit); r_cal, r_te = weighted(S[cal], w), weighted(S[te], w); art = (w, info)
    elif name == "M2_logit":
        sd = Std().fit(Xmat(fit)); m = LogisticRegression(C=0.05, max_iter=3000).fit(sd(Xmat(fit)), y[fit])
        r_cal, r_te = m.predict_proba(sd(Xmat(cal)))[:, 1], m.predict_proba(sd(Xmat(te)))[:, 1]; art = (sd, m)
    else:
        m = HistGradientBoostingClassifier(max_iter=250, learning_rate=0.04, max_leaf_nodes=15, min_samples_leaf=150, l2_regularization=1.0, random_state=0)
        m.fit(Xmat(fit), y[fit]); r_cal, r_te = m.predict_proba(Xmat(cal))[:, 1], m.predict_proba(Xmat(te))[:, 1]; art = m
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.001, y_max=0.999).fit(r_cal, y[cal])
    return iso.predict(r_cal), iso.predict(r_te), r_te, art, iso, r_cal

MODELS = ["M0_saved", "M1_gated", "M2_logit", "M3_gbm"]
oof = {m: np.full(len(df), np.nan) for m in MODELS}
oraw = {m: np.full(len(df), np.nan) for m in MODELS}   # 선택(상위 q%)은 원점수 기준 — isotonic 계단의 동점 문제 회피
thr = {m: {} for m in MODELS}          # (fold, q) -> 확률 임계 (보정 구간 예측의 상위 q 분위)
fold_rows = []
for F in folds:
    for m in MODELS:
        pc, pt, rt, art, iso, rc = fit_predict(m, F["fit"], F["cal"], F["te"])
        oof[m][F["te"]] = pt; oraw[m][F["te"]] = rt
        for q in (0.02, 0.05, 0.10, 0.20): thr[m][(F["k"], q)] = float(np.quantile(rc, 1 - q))
        yt = y[F["te"]]
        fold_rows.append(dict(model=m, fold=F["k"], n=int(F["te"].sum()), base=float(yt.mean()),
                              auc=float(roc_auc_score(yt, pt)) if yt.min() != yt.max() else None, brier=float(brier_score_loss(yt, pt))))
    print("fold", F["k"], F["span"], "train", int(F["tr"].sum()), "test", int(F["te"].sum()), flush=True)

te_all = np.any([F["te"] for F in folds], 0)
summ = {}
for m in MODELS:
    pt, yt = oof[m][te_all], y[te_all]
    base_tr = y[folds[0]["tr"]].mean()
    bs = brier_score_loss(yt, pt); bs0 = brier_score_loss(yt, np.full(len(yt), yt.mean()))
    row = dict(auc=float(roc_auc_score(yt, pt)), brier=float(bs), brier_skill=float(1 - bs / bs0), logloss=float(log_loss(yt, np.clip(pt, 1e-3, 1 - 1e-3))))
    for q in (0.05, 0.10):
        sel = np.zeros(len(df), bool)
        for F in folds: sel |= F["te"] & (oraw[m] >= thr[m][(F["k"], q)])
        k, n = int(y[sel].sum()), int(sel.sum())
        row[f"top{int(q*100)}"] = dict(n=n, prec=k / n if n else None, ci=wilson(k, n), lift=(k / n) / yt.mean() if n else None)
    # 보정 10분위
    dec = pd.qcut(pd.Series(pt).rank(method="first"), 10, labels=False)
    row["calib"] = [dict(pred=float(pt[dec == i].mean()), obs=float(yt[dec == i].mean()), n=int((dec == i).sum())) for i in range(10)]
    row["ece"] = float(sum(abs(c["pred"] - c["obs"]) * c["n"] for c in row["calib"]) / len(yt))
    summ[m] = row
    print(m, {k: (round(v, 4) if isinstance(v, float) else v) for k, v in row.items() if k not in ("calib",)}, flush=True)

best = max(MODELS, key=lambda m: (round(summ[m]["auc"], 3), summ[m]["brier_skill"]))
print("BEST", best, flush=True)

# ---------------- 청산 규칙 시뮬레이션 ----------------
def simulate(idx, entry, stop, tp, partial, trail, hold):
    n = len(idx)
    fo, fh, fl, fc = FO[idx], FH[idx], FL[idx], FC[idx]
    e = np.ones(n) if entry == "close" else fo[:, 0]
    stp = np.full(n, 1 - stop); pos = np.ones(n); real = np.zeros(n); hh = np.ones(n); tpd = np.zeros(n, bool)
    for j in range(hold):
        o, h, l, c = fo[:, j] / e, fh[:, j] / e, fl[:, j] / e, fc[:, j] / e
        act = pos > 0
        gap = act & (o <= stp); real[gap] += pos[gap] * (o[gap] - 1); pos[gap] = 0
        hit = act & ~gap & (l <= stp); real[hit] += pos[hit] * (stp[hit] - 1); pos[hit] = 0
        if tp is not None:
            t = (pos > 0) & ~tpd & (h >= 1 + tp)
            px_ = np.where(o >= 1 + tp, o, 1 + tp)
            frac = np.where(partial, 0.5, 1.0) * pos
            real[t] += frac[t] * (px_[t] - 1); pos[t] -= frac[t]; tpd |= t
            if partial: stp[t] = np.maximum(stp[t], 1.0)
        hh = np.maximum(hh, h)
        if trail: stp = np.where(pos > 0, np.maximum(stp, hh * (1 - trail)), stp)
        if j == hold - 1:
            a = pos > 0; real[a] += pos[a] * (c[a] - 1); pos[a] = 0
    return real - COST

def cooldown(sel_idx, hold):
    """같은 종목 보유 중 중복 진입 금지"""
    if len(sel_idx) == 0: return sel_idx
    sub = df.loc[sel_idx, ["ticker", "seq"]].sort_values(["ticker", "seq"])
    keep, last_t, last_s = [], None, -10 ** 9
    for i, t, s in zip(sub.index.values, sub.ticker.values, sub.seq.values):
        if t != last_t: last_t, last_s = t, -10 ** 9
        if s >= last_s + hold + (1 if True else 0): keep.append(i); last_s = s
    return np.array(sorted(keep, key=lambda i: df["asof"].values[i]))

def stats(r, idx):
    r = np.asarray(r, float)
    if len(r) == 0: return dict(n=0)
    order = np.argsort(df["asof"].values[idx], kind="stable"); eq = np.cumprod(1 + ALLOC * r[order])
    mdd = float((eq / np.maximum.accumulate(eq) - 1).min())
    return dict(n=int(len(r)), exp=float(r.mean()), ci=boot_ci(r), win=float((r > 0).mean()), mdd=mdd, total=float(eq[-1] - 1))

GRID = []
for entry, stop, tp, partial, trail, hold, q in itertools.product(["close", "open"], [0.07, 0.10, 0.15], [0.15, 0.20, 0.30, None], [False, True], [None, 0.10, 0.15], [3, 5, 10], [0.02, 0.05, 0.10, 0.20]):
    if tp is None and partial: continue
    GRID.append(dict(entry=entry, stop=stop, tp=tp, partial=partial, trail=trail, hold=hold, q=q))
print("grid", len(GRID), flush=True)

def fold_trades(m, k, cfg, cache):
    key = (m, k, cfg["q"], cfg["hold"])
    if key not in cache:
        F = folds[k - 1]
        sel = np.where(F["te"] & (oraw[m] >= thr[m][(k, cfg["q"])]))[0]
        cache[key] = cooldown(sel, cfg["hold"])
    idx = cache[key]
    return idx, (simulate(idx, cfg["entry"], cfg["stop"], cfg["tp"], cfg["partial"], cfg["trail"], cfg["hold"]) if len(idx) else np.array([]))

def run_exit_search(m):
    cache = {}; res = {}  # (gi, fold) -> returns
    t0 = time.time()
    for gi, cfg in enumerate(GRID):
        for k in range(1, 6):
            idx, r = fold_trades(m, k, cfg, cache); res[(gi, k)] = (idx, r)
    print("sim done", m, round(time.time() - t0), "s", flush=True)
    def crit(gi, ks):
        r = np.concatenate([res[(gi, k)][1] for k in ks]); 
        if len(r) < 30: return -9, len(r)
        return r.mean() - r.std(ddof=1) / math.sqrt(len(r)), len(r)    # 평균 - 1SE (과최적화 완화)
    nested = []
    for k in range(2, 6):
        gi = max(range(len(GRID)), key=lambda g: crit(g, range(1, k))[0])
        idx, r = res[(gi, k)]
        nested.append(dict(fold=k, cfg=GRID[gi], train_crit=crit(gi, range(1, k)), idx=idx, r=r))
    nr = np.concatenate([x["r"] for x in nested]); ni = np.concatenate([x["idx"] for x in nested]).astype(int)
    final_gi = max(range(len(GRID)), key=lambda g: crit(g, range(1, 6))[0])
    allr = {gi: np.concatenate([res[(gi, k)][1] for k in range(1, 6)]) for gi in range(len(GRID))}
    alli = {gi: np.concatenate([res[(gi, k)][0] for k in range(1, 6)]).astype(int) for gi in range(len(GRID))}
    top = sorted(range(len(GRID)), key=lambda g: -crit(g, range(1, 6))[0])[:10]
    # 견고성: 폴드별 기대값이 모두 양수인 규칙 수 / 최소 폴드 기대값 최대 규칙
    pf = {g: [float(res[(g, k)][1].mean()) if len(res[(g, k)][1]) >= 15 else -9 for k in range(1, 6)] for g in range(len(GRID))}
    n_all_pos = sum(all(v > 0 for v in pf[g]) for g in pf); n_4pos = sum(sum(v > 0 for v in pf[g]) >= 4 for g in pf)
    gmin = max(pf, key=lambda g: min(pf[g]))
    print("ROBUST", m, "all5>0:", n_all_pos, ">=4/5>0:", n_4pos, "of", len(GRID), "maximin", GRID[gmin], [round(v, 4) for v in pf[gmin]], flush=True)
    return dict(nested=nested, nested_stats=stats(nr, ni), final=GRID[final_gi], final_stats=stats(allr[final_gi], alli[final_gi]),
                top=[dict(cfg=GRID[g], **stats(allr[g], alli[g])) for g in top], res=res,
                robust=dict(all5=n_all_pos, four5=n_4pos, grid=len(GRID), maximin=GRID[gmin], maximin_folds=pf[gmin]))

def baseline_before(m="M0_saved"):
    """이전 기본값: 저장 가중치 점수 ≥ flag_score(+국면) & 합류 ≥ min_confluence, 종가 진입, 손절 15%, 목표 30%, 5일 보유"""
    sc = saved_score(np.arange(len(df)))
    conf = np.sum([(S[:, j] >= 1) for j, c in enumerate(SIG) if c[2:] not in NO_CONF], 0)
    rg = df.regime.values.astype(float); ra = float(p["regime_adj"])
    adj = np.where(rg < 0, ra, np.where(rg == 0, ra / 2, 0))
    fl = (sc >= float(p["flag_score"]) + adj) & (conf >= int(p.get("min_confluence", 2)))
    sel = np.where(te_all & fl)[0]; k, n = int(y[sel].sum()), len(sel)
    idx = cooldown(sel, 5); r = simulate(idx, "close", 0.15, 0.30, False, None, 5)
    te25 = np.any([F["te"] for F in folds[1:]], 0)
    sel2 = np.where(te25 & fl)[0]; idx2 = cooldown(sel2, 5); r2 = simulate(idx2, "close", 0.15, 0.30, False, None, 5)
    return dict(flags=n, prec=k / n if n else None, ci=wilson(k, n), recall=k / max(int(y[te_all].sum()), 1), trade=stats(r, idx), trade_f25=stats(r2, idx2))

before = baseline_before()
print("BEFORE", {k: v for k, v in before.items()}, flush=True)
ex_best = run_exit_search(best)
ex_m0 = run_exit_search("M0_saved") if best != "M0_saved" else ex_best
for nm, ex in (("best", ex_best), ("M0", ex_m0)):
    print("NESTED", nm, ex["nested_stats"], [ (x["fold"], x["cfg"]) for x in ex["nested"]], flush=True)
    print("FINAL", nm, ex["final"], ex["final_stats"], flush=True)

# ---------------- 최종 모델 (전체 데이터: 앞 80% 학습, 뒤 20% 보정) ----------------
cut = dates[int(len(dates) * 0.8)]
fit_all = (df["asof"] < cut).values; cal_all = (df["asof"] >= cut + pd.Timedelta(days=7)).values
pc, _, _, art, iso, rc = fit_predict(best, fit_all, cal_all, cal_all)
fx = ex_best["final"]
FLAG_Q = 0.05   # 경보 임계: 분류 성능(상위 5% 정밀도)으로 정함 — 청산 규칙 탐색과 분리
q_thr = float(np.quantile(rc, 1 - FLAG_Q))
out = dict(created=time.strftime("%Y-%m-%d %H:%M KST"), model=best, signals=[c[2:] for c in SIG], target=dict(gain=TGT - 1, days=HOLD_LBL),
           n_rows=int(len(df)), n_tickers=int(df.ticker.nunique()), span=[str(dates[0])[:10], str(dates[-1])[:10]], base_rate=float(y.mean()),
           folds=[dict(k=F["k"], test=F["span"], n_train=int(F["tr"].sum()), n_test=int(F["te"].sum())) for F in folds],
           compare={m: {k: v for k, v in summ[m].items()} for m in MODELS}, fold_rows=fold_rows,
           iso=dict(x=[float(v) for v in iso.X_thresholds_], y=[float(v) for v in iso.y_thresholds_]),
           threshold=dict(q=FLAG_Q, raw=q_thr, prob=float(iso.predict([q_thr])[0])),
           before=before,
           exit=dict(final=fx, final_stats=ex_best["final_stats"], nested_stats=ex_best["nested_stats"],
                     nested=[dict(fold=x["fold"], cfg=x["cfg"], **stats(x["r"], x["idx"])) for x in ex_best["nested"]],
                     top=ex_best["top"], robust=ex_best["robust"], m0_robust=ex_m0["robust"], m0_nested=ex_m0["nested_stats"], m0_final=ex_m0["final"], m0_final_stats=ex_m0["final_stats"]),
           survivorship_note="표본은 현재 상장 유니버스에서 추출 → 상폐 종목 누락(생존 편향). 결과가 실제보다 낙관적일 수 있음.")
out["exit"]["positive_oos"] = bool(ex_best["nested_stats"].get("n", 0) >= 30 and ex_best["nested_stats"]["exp"] > 0)
if best == "M1_gated":
    w, info = art; out["weights"] = {c[2:]: float(w[j]) for j, c in enumerate(SIG)}; out["gate"] = info
elif best == "M0_saved":
    out["weights"] = {c[2:]: float(W0[j]) for j, c in enumerate(SIG)}
elif best == "M2_logit":
    sd, m = art; out["logit"] = dict(mean=sd.m.tolist(), std=sd.s.tolist(), coef=m.coef_[0].tolist(), intercept=float(m.intercept_[0]))
else:
    pickle.dump(art, open(ROOT / "model/gbm.pkl", "wb"))
json.dump(out, open(ROOT / "model/research.json", "w"), ensure_ascii=False, indent=1, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o))
print("saved model/research.json", flush=True)

# ---------------- 보고서 (docs/RESEARCH.md) ----------------
def P_(v, d=1): return "N/A" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v * 100:.{d}f}%"
def cfg_txt(c):
    return (f'{"종가" if c["entry"] == "close" else "다음날 시가"} 진입 · 손절 -{c["stop"]*100:.0f}% · ' + (f'익절 +{c["tp"]*100:.0f}%' + (" (절반 익절 후 본전 손절)" if c["partial"] else "") if c["tp"] else "익절 없음")
            + (f' · 추적손절 {c["trail"]*100:.0f}%' if c["trail"] else "") + f' · 최대 {c["hold"]}일 보유 · 점수 상위 {c["q"]*100:.0f}%')
def st_txt(s_): return f'{s_["n"]}건 · 기대값 {P_(s_["exp"], 2)} (95% CI {P_(s_["ci"][0], 2)} ~ {P_(s_["ci"][1], 2)}) · 승률 {P_(s_["win"])} · MDD {P_(s_["mdd"])}' if s_.get("n") else "거래 없음"
L = [f"# 정밀 검증 보고서 ({out['created']})", "",
     f"- 표본: {out['n_tickers']}종목 × 매 거래일, {out['span'][0]} ~ {out['span'][1]}, {out['n_rows']:,}행 (시점 기준 유동성 필터 적용 후)",
     f"- 정답 정의: 신호일 종가 대비 {HOLD_LBL}거래일 안에 고가 +{(TGT-1)*100:.0f}% 도달. 기본율 {P_(out['base_rate'])}",
     "- 방식: 확장형 워크포워드 5폴드 (날짜 블록 6개, 학습/검증 사이 5거래일 엠바고). 각 폴드에서 학습 75% 로 적합 → 뒤 25% 로 isotonic 확률 보정 → 다음 블록에서 평가",
     f"- 비용: 왕복 {COST*100:.1f}% 차감, 같은 종목 보유 중 재진입 금지, MDD 는 거래당 자본 {ALLOC*100:.0f}% 순차 투입 기준",
     "- **생존 편향 주의**: 표본은 현재 상장 종목에서 뽑았음 → 상폐 종목이 빠져 결과가 실제보다 좋게 나올 수 있음", "",
     "## 1. 모델 비교 (표본외, 5폴드 합산)", "", "| 모델 | AUC | Brier | Brier skill | 보정오차(ECE) | 상위5% 적중률 (95% CI) | 상위10% 적중률 |", "|---|---|---|---|---|---|---|"]
NM = {"M0_saved": "기존 가중 점수", "M1_gated": "게이트 가중(표본≥25·lift≥1)", "M2_logit": "로지스틱 회귀", "M3_gbm": "GBM(HistGB)"}
for m in MODELS:
    c = summ[m]; t5, t10 = c["top5"], c["top10"]
    L.append(f'| {NM[m]}{" **(채택)**" if m == best else ""} | {c["auc"]:.3f} | {c["brier"]:.4f} | {c["brier_skill"]:+.3f} | {c["ece"]*100:.1f}%p | {P_(t5["prec"])} ({P_(t5["ci"][0])}~{P_(t5["ci"][1])}), n={t5["n"]} | {P_(t10["prec"])}, n={t10["n"]} |')
L += ["", "## 2. 확률 보정 점검 (채택 모델, 10분위)", "", "| 분위 | 예측 평균 | 실제 적중 | n |", "|---|---|---|---|"]
for i, c in enumerate(summ[best]["calib"], 1): L.append(f'| {i} | {P_(c["pred"])} | {P_(c["obs"])} | {c["n"]} |')
L += ["", "## 3. 신호 게이트 (최종 학습 구간)", "", "| 신호 | 켜진 횟수 | 적중률 | lift | Wilson 하한 | 가중치 |", "|---|---|---|---|---|---|"]
if best == "M1_gated":
    for k, v in sorted(out["gate"].items(), key=lambda kv: -kv[1]["w"]):
        L.append(f'| {M.SIG_NAME.get(k, k)} | {v["n"]} | {P_(v["hit"])} | {v["lift"]:.2f} | {P_(v["lo"])} | {v["w"]:.2f}{" (제외)" if v["w"] == 0 else (" (절반)" if v["lo"] <= out["base_rate"] else "")} |')
b0 = before
L += ["", "## 4. 이전 vs 이후", "", "| 항목 | 이전 (저장 가중치 + 고정 규칙) | 이후 (게이트 가중 + 보정) |", "|---|---|---|",
      f'| AUC | {summ["M0_saved"]["auc"]:.3f} | {summ[best]["auc"]:.3f} |',
      f'| Brier skill | {summ["M0_saved"]["brier_skill"]:+.3f} | {summ[best]["brier_skill"]:+.3f} |',
      f'| 경보 적중률 | {P_(b0["prec"])} (n={b0["flags"]}, 기존 경보 조건) | {P_(summ[best]["top5"]["prec"])} (n={summ[best]["top5"]["n"]}, 상위 5%) |',
      f'| 매매 결과 (손절15/익절30/5일, 폴드2~5) | {st_txt(b0["trade_f25"])} | — |',
      f'| 매매 결과 (중첩 탐색 청산 규칙, 폴드2~5) | {st_txt(ex_m0["nested_stats"])} | {st_txt(ex_best["nested_stats"])} |',
      "", "## 5. 청산 규칙 탐색 (학습 폴드에서만 선택 → 다음 폴드 평가)", "",
      f'- 탐색 공간 {len(GRID)}개: 진입(종가/다음날 시가) × 손절(7/10/15%) × 익절(15/20/30%/없음) × 절반 익절 × 추적손절(없음/10/15%) × 보유(3/5/10일) × 상위(2/5/10/20%)',
      "- 선택 기준: 이전 폴드들의 표본외 거래(≥30건) 기대값 − 1 표준오차 (과최적화 완화)", ""]
for x in ex_best["nested"]: L.append(f'- 폴드 {x["fold"]}: {cfg_txt(x["cfg"])} → {st_txt(stats(x["r"], x["idx"]))}')
rb = ex_best["robust"]
L += ["", f'- **중첩 표본외 합계: {st_txt(ex_best["nested_stats"])}**',
      f'- 견고성: {rb["grid"]}개 규칙 중 5개 폴드 모두 기대값 양수인 규칙 {rb["all5"]}개, 4/5 폴드 양수 {rb["four5"]}개',
      f'- 전체 폴드에서 가장 나았던 규칙(사후 선택이라 낙관적): {cfg_txt(out["exit"]["final"])} → {st_txt(out["exit"]["final_stats"])}', "",
      "### 결론", ""]
if out["exit"]["positive_oos"]:
    L.append(f'- 중첩 표본외 기대값이 양수 → 앱 기본 청산 규칙으로 채택: {cfg_txt(out["exit"]["final"])}')
else:
    L.append("- **중첩 표본외 기대값이 양수가 아님 → '검증된 수익 규칙'은 없다.** 앱은 손절/익절을 '참고(미검증)'로만 표시하고 기본값을 바꾸지 않았다.")
    L.append("- 모델은 '오를 가능성이 높은 종목'을 고르는 능력(AUC·적중률)은 개선됐지만, 급등 후 되돌림이 커서 단순 규칙으로는 비용 차감 후 이익이 남지 않았다.")
L += ["", "> 투자 권유가 아님. 모든 확률·가격 수준은 과거 무료 데이터 기반 추정치이며 미래를 보장하지 않음."]
(ROOT / "docs").mkdir(exist_ok=True); (ROOT / "docs/RESEARCH.md").write_text("\n".join(L), encoding="utf-8")
print("saved docs/RESEARCH.md", flush=True)
