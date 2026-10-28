"""사례 분석 결과를 특징·감점으로 바꿔 같은 5폴드 워크포워드 재실행.
- 데이터 정리: 미조정 역분할 아티팩트 행 제외 (art_fwd)
- 추가 신호(가점 후보): 5일 +50%, 직전5일 +40% 일봉, 당일 +20%, RVOL≥5  → 기존과 같은 '게이트'(학습 구간 n≥25, lift≥1)를 통과해야만 가중치 받음
- 감점 후보(실패 특성): 424B 30일 이내, S-1/S-3/F-1/F-3 등록 30일 이내, RVOL<1.5
  → 각 폴드의 '학습 구간 상위 10% 후보' 안에서만 적중률 비율을 추정, n≥30 이고 Wilson 상한이 나머지 적중률보다 낮을 때만 배수(0.3~1) 적용
- 청산 규칙: 기존과 동일한 1,512개 GRID 중첩 탐색(이전 폴드로만 선택)
출력: model/success_analysis_metrics.json"""
import sys, json, math, time; from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / "scripts"))
import numpy as np, pandas as pd
import sa_lib as L
from sklearn.metrics import roc_auc_score
df, y = L.df, L.y
F = pd.read_pickle(ROOT / "data/sa_feat.pkl").drop_duplicates(["ticker", "asof"])
X = df[["ticker", "asof"]].merge(F, on=["ticker", "asof"], how="left"); assert len(X) == len(df)
art = X.art_fwd.fillna(0).values.astype(bool)
print("artifact rows", art.sum(), "hits among them", y[art].sum())
for Fd in L.folds:
    for k in ("tr", "fit", "cal", "te"): Fd[k] = Fd[k] & ~art
te_all = np.any([Fd["te"] for Fd in L.folds], 0)
S0, SIG0 = L.S.copy(), list(L.SIG)
NEW = {"s_mom5": X.ret5 >= 0.5, "s_prev_spike": X.up_prev5 >= 0.4, "s_day_up20": X.ret1 >= 0.20, "s_rvol5": X.rvol >= 5}
PEN = {"424B 30일 이내": (X.d_424b <= 30).values, "증권신고서(S-1/S-3/F-1/F-3) 30일 이내": (X.d_reg <= 30).values, "RVOL < 1.5": (X.rvol < 1.5).values}
S1 = np.c_[S0, np.column_stack([v.fillna(False).astype(float).values for v in NEW.values()])]; SIG1 = SIG0 + list(NEW)

def run(name, S, SIG, use_pen):
    L.S, L.SIG = S, SIG
    oof = np.full(len(df), np.nan); oraw = np.full(len(df), np.nan); thr = {}; info = []
    for Fd in L.folds:
        w, gi = L.gated_weights(Fd["fit"])
        rf = L.weighted(S[Fd["fit"]], w); mult = np.ones(len(df)); pinfo = {}
        if use_pen:
            fi = np.where(Fd["fit"])[0]; top = fi[rf >= np.quantile(rf, 0.90)]
            for pn, pm in PEN.items():
                on = top[pm[top]]; off = top[~pm[top]]
                k, n = int(y[on].sum()), len(on); r_off = y[off].mean() if len(off) else np.nan
                hi = L.wilson(k, n)[1]; ratio = (k / n) / r_off if n and r_off else 1
                f = float(np.clip(ratio, 0.3, 1.0)) if (n >= 30 and hi < r_off) else 1.0
                pinfo[pn] = dict(n=n, hit=k / n if n else None, rest=float(r_off), factor=f); mult = np.where(pm, mult * f, mult)
        sc = lambda m: L.weighted(S[m], w) * mult[m]
        r_cal, r_te = sc(Fd["cal"]), sc(Fd["te"])
        iso = L.IsotonicRegression(out_of_bounds="clip", y_min=0.001, y_max=0.999).fit(r_cal, y[Fd["cal"]])
        oof[Fd["te"]] = iso.predict(r_te); oraw[Fd["te"]] = r_te
        for q in (0.02, 0.05, 0.10, 0.20): thr[(Fd["k"], q)] = float(np.quantile(r_cal, 1 - q))
        info.append(dict(fold=Fd["k"], weights={c[2:]: float(w[j]) for j, c in enumerate(SIG) if w[j] > 0}, pen=pinfo))
    yt, pt = y[te_all], oof[te_all]
    res = dict(model=name, n_test=int(te_all.sum()), base=float(yt.mean()), auc=float(roc_auc_score(yt, pt)))
    for q in (0.05, 0.10):
        sel = np.zeros(len(df), bool)
        for Fd in L.folds: sel |= Fd["te"] & (oraw >= thr[(Fd["k"], q)])
        k, n = int(y[sel].sum()), int(sel.sum())
        res[f"top{int(q*100)}"] = dict(n=n, k=k, prec=k / n, ci=L.wilson(k, n), lift=(k / n) / yt.mean())
        if q == 0.05:
            res["top5_d5_mean"] = float(np.mean(L.FC[sel, 4] - 1)); res["top5_minlo_med"] = float(np.median(L.FL[sel].min(1) - 1))
            res["_sel5"] = sel
    # fold-level top5 precision (안정성)
    res["fold_top5"] = []
    for Fd in L.folds:
        s = Fd["te"] & (oraw >= thr[(Fd["k"], 0.05)]); res["fold_top5"].append(dict(fold=Fd["k"], n=int(s.sum()), prec=float(y[s].mean()) if s.sum() else None, base=float(y[Fd["te"]].mean())))
    L.oraw[name] = oraw; L.thr[name] = thr; L.oof[name] = oof
    print(name, {k: v for k, v in res.items() if not k.startswith("_") and k != "fold_top5"}, flush=True)
    return res, info

R = {}
R["before"], I0 = run("M1_clean", S0, SIG0, False)          # 이전 모델 (같은 정리된 데이터)
R["pen_only"], I1 = run("M5_pen", S0, SIG0, True)            # 실패 특성 감점만
R["after"], I2 = run("M4_case", S1, SIG1, True)              # 새 신호 + 감점
# 두 모델 상위5% 적중률 차이의 부트스트랩 CI (같은 테스트 기간)
rng = np.random.default_rng(11)
def boot_diff(a, b, B=4000):
    ia, ib = np.where(a)[0], np.where(b)[0]; d = []
    for _ in range(B): d.append(y[rng.choice(ia, len(ia))].mean() - y[rng.choice(ib, len(ib))].mean())
    return [float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))]
for k in ("pen_only", "after"): R[k]["diff_vs_before_ci"] = boot_diff(R[k]["_sel5"], R["before"]["_sel5"])
# 중첩 청산 탐색 (같은 GRID, 이전 폴드로만 선택)
EX = {}
for nm, m in (("before", "M1_clean"), ("after", "M4_case")):
    L.S = S0 if nm == "before" else S1
    ex = L.run_exit_search(m)
    EX[nm] = dict(nested_stats=ex["nested_stats"], nested=[dict(fold=x["fold"], cfg=x["cfg"], **L.stats(x["r"], x["idx"])) for x in ex["nested"]], robust=ex["robust"],
                  final=ex["final"], final_stats=ex["final_stats"])
    print("NESTED", nm, ex["nested_stats"], flush=True)
for k in R: R[k].pop("_sel5", None)
out = dict(created=time.strftime("%Y-%m-%d %H:%M KST"), artifact_rows=int(art.sum()), models=R, exits=EX, fold_info=dict(before=I0, pen_only=I1, after=I2),
           new_signals=list(NEW), penalties=list(PEN))
json.dump(out, open(ROOT / "model/success_analysis_metrics.json", "w"), ensure_ascii=False, indent=1, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o))
print("saved")
