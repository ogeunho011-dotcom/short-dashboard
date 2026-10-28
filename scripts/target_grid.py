"""적중률 정의 재검토: (A) 고정 목표 그리드, (B) 상황 상대 정의, (C) 셋업 기반(SHFS 스타일, 주 정의).
모두 같은 5폴드 워크포워드 · 표본외 · 룩어헤드 없음. 출력: model/target_grid.json, model/research_defs.json"""
import sys, json, math, time, sqlite3; from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / "scripts"))
import numpy as np, pandas as pd
import sa_lib as L
from sklearn.metrics import roc_auc_score, brier_score_loss
from sklearn.isotonic import IsotonicRegression
df, y0 = L.df, L.y.copy(); N = len(df)
FH, FL, FC = L.FH, L.FL, L.FC
F = pd.read_pickle(ROOT / "data/sa_feat.pkl").drop_duplicates(["ticker", "asof"])
X = df[["ticker", "asof"]].merge(F, on=["ticker", "asof"], how="left"); assert len(X) == N
art = X.art_fwd.fillna(0).values.astype(bool)
for Fd in L.folds:
    for k in ("tr", "fit", "cal", "te"): Fd[k] = Fd[k] & ~art
folds = L.folds; te_all = np.any([Fd["te"] for Fd in folds], 0)
d424 = (X.d_424b <= 30).fillna(False).values
rng = np.random.default_rng(5)

# ---------- 보조 데이터: ATR%, 20일 변동성, IWM, 섹터 ----------
con = sqlite3.connect(ROOT / "data/shortdash.sqlite")
px = pd.read_sql("SELECT ticker,date,open,high,low,close FROM prices WHERE ticker IN (%s)" % ",".join("?" * (df.ticker.nunique() + 1)),
                 con, params=list(df.ticker.unique()) + ["IWM"]); px["date"] = pd.to_datetime(px["date"])
px = px.sort_values(["ticker", "date"])
g = px.groupby("ticker")
pc = g["close"].shift(1)
tr = np.maximum(px.high - px.low, np.maximum((px.high - pc).abs(), (px.low - pc).abs()))
px["atr"] = tr.groupby(px.ticker).transform(lambda s: s.rolling(14, min_periods=10).mean()) / px.close
px["vol20"] = g["close"].pct_change().groupby(px.ticker).transform(lambda s: s.rolling(20, min_periods=15).std())
A = df[["ticker", "asof"]].merge(px[["ticker", "date", "atr", "vol20"]].rename(columns={"date": "asof"}), on=["ticker", "asof"], how="left")
ATR, VOL20 = A.atr.values, A.vol20.values
iwm = px[px.ticker == "IWM"].set_index("date")["close"]
iwm_f = {h: (iwm.shift(-h) / iwm - 1) for h in (3, 5, 10)}
IWM_F = {h: df["asof"].map(iwm_f[h]).values for h in (3, 5, 10)}
IWM20 = df["asof"].map(iwm / iwm.shift(20) - 1).values
info = {k[5:]: json.loads(v) for k, v in con.execute("SELECT k,v FROM kv WHERE k LIKE 'info:%'").fetchall()}
SECT = df.ticker.map(lambda t: (info.get(t) or {}).get("sector") or "Unknown").values

# ---------- 셋업(시점 재구성 숏 차수) ----------
SU = pd.read_pickle(ROOT / "data/setup_all.pkl").drop_duplicates(["ticker", "asof"])
SX = df[["ticker", "asof"]].merge(SU, on=["ticker", "asof"], how="left"); assert len(SX) == N
VALID = SX.valid.fillna(False).values.astype(bool) & (SX.nfut.fillna(0).values >= 10)
Y_SETUP = (VALID & (SX.succ.fillna(0).values == 1)).astype(int)
Y_PH = (VALID & (SX.ph_hit.fillna(0).values == 1)).astype(int)
SRET = SX.ret.values; LEVEL = SX.level.fillna(0).values.astype(int); CP = SX.cp.values

def wil(k, n): return L.wilson(k, n) if n else [None, None]
def boot(x): return L.boot_ci(np.asarray(x, float)) if len(x) > 1 else [None, None]

# ---------- 채택 모델(M1_gated, 원 라벨) 표본외 원점수 + q=1% 임계 재계산 ----------
QS = (0.01, 0.02, 0.05, 0.10)
def run_def(yv, mask=None):
    """M1_gated 를 라벨 yv 로 재학습·보정. mask=학습/평가에 쓸 행(셋업 무효 행 제외 등)."""
    mask = np.ones(N, bool) if mask is None else mask
    L.y = yv
    oraw = np.full(N, np.nan); oof = np.full(N, np.nan); thr = {}; W = []
    for Fd in folds:
        fit, cal, te = Fd["fit"] & mask, Fd["cal"] & mask, Fd["te"]
        w, _ = L.gated_weights(fit)
        rc, rt = L.weighted(L.S[cal], w), L.weighted(L.S[te], w)
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0.001, y_max=0.999).fit(rc, yv[cal])
        oraw[te] = rt; oof[te] = iso.predict(rt); W.append(w)
        for q in QS: thr[(Fd["k"], q)] = float(np.quantile(rc, 1 - q))
    L.y = y0
    ev = te_all & mask
    res = dict(base=float(yv[ev].mean()), n_test=int(ev.sum()), auc=float(roc_auc_score(yv[ev], oof[ev])),
               brier=float(brier_score_loss(yv[ev], oof[ev])))
    for q in (0.05,):
        s = sel_mask(oraw, thr, q) & mask; k, n = int(yv[s].sum()), int(s.sum())
        res["top5"] = dict(n=n, prec=k / n, ci=wil(k, n), lift=(k / n) / res["base"])
    return oraw, thr, oof, res

def sel_mask(oraw, thr, q, excl=None):
    s = np.zeros(N, bool)
    for Fd in folds: s |= Fd["te"] & (oraw >= thr[(Fd["k"], q)])
    if excl is not None: s &= ~excl
    return s

t0 = time.time()
ORAW, THR, OOF, R_ORIG = run_def(y0.astype(int))
print("M1 orig", R_ORIG, round(time.time() - t0), flush=True)

STOPS = (0.05, 0.07, 0.10, 0.15)
def nested_trades(sel, hold, tp, stops=STOPS, tp_arr=False):
    """폴드 k 의 손절폭은 폴드 1..k-1 거래로만 선택 → 폴드 2~5 표본외 거래"""
    per = {}
    for Fd in folds:
        idx = L.cooldown(np.where(sel & Fd["te"])[0], hold)
        per[Fd["k"]] = {s_: (idx, L.simulate(idx, "close", s_, (tp[idx] if tp_arr else tp), False, None, hold) if len(idx) else np.array([])) for s_ in stops}
    R, I, chosen = [], [], []
    for k in range(2, 6):
        best = max(stops, key=lambda s_: np.mean(np.concatenate([per[j][s_][1] for j in range(1, k)]) if sum(len(per[j][s_][1]) for j in range(1, k)) else -9))
        idx, r = per[k][best]; R.append(r); I.append(idx); chosen.append(best)
    r = np.concatenate(R) if R else np.array([]); idx = np.concatenate(I).astype(int) if I else np.array([], int)
    st = L.stats(r, idx) if len(r) else dict(n=0)
    st["stops"] = chosen
    return st

def cell(yv, sel, base_mask=None):
    bm = te_all if base_mask is None else te_all & base_mask
    base = float(yv[bm].mean()); k, n = int(yv[sel].sum()), int(sel.sum())
    return dict(base=base, n=n, hit=k / n if n else None, ci=wil(k, n), lift=(k / n) / base if n and base else None)

OUT = {"created": time.strftime("%Y-%m-%d %H:%M KST"), "n_rows": int(N), "n_test": int(te_all.sum()), "artifact_rows": int(art.sum())}

# ---------- (A) 고정 목표 그리드 ----------
grid = []
for q in QS:
    for ex in (False, True):
        sel0 = sel_mask(ORAW, THR, q, d424 if ex else None)
        for t in (0.10, 0.15, 0.20, 0.30):
            for h in (3, 5, 10):
                yv = (FH[:, :h].max(1) >= 1 + t).astype(int)
                c = cell(yv, sel0); c.update(q=q, excl424=ex, target=t, h=h)
                c["trade"] = nested_trades(sel0, h, t)
                grid.append(c)
    print("grid q", q, round(time.time() - t0), flush=True)
OUT["grid"] = grid
best = max([g_ for g_ in grid if g_["trade"].get("n", 0) >= 30], key=lambda g_: g_["trade"]["exp"])
OUT["grid_best"] = dict(q=best["q"], excl424=best["excl424"], target=best["target"], h=best["h"], trade=best["trade"], hit=best["hit"], lift=best["lift"],
                        ci_excludes_zero=bool(best["trade"]["ci"][0] > 0 or best["trade"]["ci"][1] < 0), n_cells=len(grid))
print("best cell", OUT["grid_best"], flush=True)

# ---------- (C) 셋업 기반 (주 정의) ----------
SEL5 = sel_mask(ORAW, THR, 0.05)
def setup_block(sel, name):
    s = sel & VALID; base_m = te_all & VALID
    c = cell(Y_SETUP, s, VALID); c["ph"] = cell(Y_PH, s, VALID)
    idx = L.cooldown(np.where(s)[0], 10); r = SRET[idx]; r = r[~np.isnan(r)]
    c["trade"] = L.stats(r, idx[~np.isnan(SRET[idx])]) if len(r) else dict(n=0)
    c["need_med"] = float(np.nanmedian(SX.need.values[s])); c["risk_med"] = float(np.nanmedian(SX.risk.values[s]))
    c["need_med_base"] = float(np.nanmedian(SX.need.values[base_m])); c["risk_med_base"] = float(np.nanmedian(SX.risk.values[base_m]))
    c["invalid_share"] = float(1 - (sel & VALID).sum() / max(sel.sum(), 1))
    # 기준선: 아무 날이나 같은 규칙으로 진입한 기대값
    bi = L.cooldown(np.where(base_m)[0], 10); br = SRET[bi]; br = br[~np.isnan(br)]
    c["trade_base"] = dict(n=int(len(br)), exp=float(br.mean()), ci=boot(br), win=float((br > 0).mean()))
    c["name"] = name
    return c
SETUP = {"top5": setup_block(SEL5, "M1 상위5%"), "top5_ex424": setup_block(sel_mask(ORAW, THR, 0.05, d424), "M1 상위5% · 424B 30일 제외"),
         "top1": setup_block(sel_mask(ORAW, THR, 0.01), "M1 상위1%"), "top2": setup_block(sel_mask(ORAW, THR, 0.02), "M1 상위2%"),
         "top10": setup_block(sel_mask(ORAW, THR, 0.10), "M1 상위10%")}
# 경보 레벨(앱 점수 1~5) · 커버 압력 구간별 — 전체 표본외 행 기준과 M1 상위5% 기준
def breakdown(key_arr, buckets, sel):
    rows = []
    for name, m in buckets:
        allm = te_all & VALID & m; s = sel & VALID & m
        k, n = int(Y_SETUP[s].sum()), int(s.sum()); kb, nb = int(Y_SETUP[allm].sum()), int(allm.sum())
        idx = L.cooldown(np.where(allm)[0], 10); r = SRET[idx]; r = r[~np.isnan(r)]
        idx2 = L.cooldown(np.where(s)[0], 10); r2 = SRET[idx2]; r2 = r2[~np.isnan(r2)]
        rows.append(dict(bucket=name, n_all=nb, hit_all=kb / nb if nb else None, ci_all=wil(kb, nb), exp_all=float(r.mean()) if len(r) else None, exp_all_ci=boot(r),
                         n_alert=n, hit_alert=k / n if n else None, ci_alert=wil(k, n), exp_alert=float(r2.mean()) if len(r2) else None, exp_alert_ci=boot(r2), n_trades_alert=int(len(r2)),
                         ph_all=float(Y_PH[allm].mean()) if nb else None))
    return rows
base_setup = float(Y_SETUP[te_all & VALID].mean())
SETUP["by_level"] = breakdown(LEVEL, [(f"레벨 {i}", LEVEL == i) for i in range(1, 6)], SEL5)
SETUP["by_cp"] = breakdown(CP, [("0–25", CP < 25), ("25–50", (CP >= 25) & (CP < 50)), ("50–75", (CP >= 50) & (CP < 75)), ("75–100", CP >= 75)], SEL5)
SETUP["by_regime"] = breakdown(IWM20, [("IWM 20일 ≥0 (강세)", IWM20 >= 0), ("IWM 20일 <0 (약세)", IWM20 < 0)], SEL5)
SETUP["base_rate"] = base_setup; SETUP["valid_share"] = float(VALID[te_all].mean())
est = SX.est_days.values; md = SX.map_days.values
SETUP["finra_real_share"] = float(np.nansum(md[te_all] - est[te_all]) / np.nansum(md[te_all]))
SETUP["si_scaled_share"] = float(SX.scaled_si.fillna(False).astype(bool).values[te_all].mean())
# 셋업 라벨로 재학습한 모델
OR_S, TH_S, OF_S, R_S = run_def(Y_SETUP, VALID)
SETUP["retrained"] = R_S
SETUP["retrained_top5"] = setup_block(sel_mask(OR_S, TH_S, 0.05) & VALID, "셋업 라벨 재학습 상위5%")
# 레벨 × 셋업 결합 규칙: 셋업 무효/레벨 등 단순 규칙 효과
print("SETUP", {k: (v if not isinstance(v, list) else len(v)) for k, v in SETUP.items() if k not in ("by_level", "by_cp", "by_regime")}, flush=True)
OUT["setup"] = SETUP

# ---------- (B) 상황 상대 정의 ----------
CTX = {}
h = 5
mx5 = FH[:, :h].max(1) - 1; r5 = FC[:, h - 1] - 1
okA = ~np.isnan(ATR)
for k in (2, 3, 4):
    yv = (okA & (mx5 >= k * np.nan_to_num(ATR, nan=9))).astype(int)
    c = cell(yv, SEL5 & okA, okA); c["trade"] = nested_trades(SEL5 & okA, h, np.nan_to_num(k * ATR, nan=9), tp_arr=True)
    c["tp_med"] = float(np.nanmedian(k * ATR[SEL5 & okA])); CTX[f"atr{k}"] = c
okV = ~np.isnan(VOL20)
yv = (okV & (mx5 >= 3 * np.nan_to_num(VOL20, nan=9))).astype(int)
c = cell(yv, SEL5 & okV, okV); c["trade"] = nested_trades(SEL5 & okV, h, np.nan_to_num(3 * VOL20, nan=9), tp_arr=True); c["tp_med"] = float(np.nanmedian(3 * VOL20[SEL5 & okV])); CTX["vol20_3"] = c
okI = ~np.isnan(IWM_F[h])
ex_iwm = r5 - np.nan_to_num(IWM_F[h])
peer = pd.Series(r5).groupby([df["asof"].values, SECT]).transform("median").values
for nm, yv in (("beat_iwm", okI & (ex_iwm > 0)), ("beat_iwm10", okI & (ex_iwm >= 0.10)), ("beat_peer", r5 - peer > 0), ("beat_peer10", r5 - peer >= 0.10)):
    yv = yv.astype(int); c = cell(yv, SEL5 & okI, okI); c["trade"] = nested_trades(SEL5, h, None); CTX[nm] = c
CTX["sector_n"] = int(len(set(SECT))); CTX["unknown_sector_share"] = float((SECT == "Unknown").mean())
# (d) 국면별: 고정(+30%/5일), ATR×3, 셋업
REG = {}
for nm, yv, m_ in (("fixed30_5", (FH[:, :5].max(1) >= 1.3).astype(int), np.ones(N, bool)), ("atr3", (okA & (mx5 >= 3 * np.nan_to_num(ATR, nan=9))).astype(int), okA),
                   ("setup", Y_SETUP, VALID)):
    REG[nm] = []
    for bn, bm in (("강세(IWM 20일 ≥0)", IWM20 >= 0), ("약세(IWM 20일 <0)", IWM20 < 0)):
        c = cell(yv, SEL5 & bm & m_, bm & m_); c["bucket"] = bn; REG[nm].append(c)
CTX["regime"] = REG
OUT["context"] = CTX
print("CTX done", round(time.time() - t0), flush=True)

# ---------- 정의별 재학습 표본외 성능 + 최종 모델 저장 ----------
DEFS = {"setup": dict(label="셋업 기반(재점화 도달 > 최신 차수 하단 이탈 먼저) · 10거래일", y=Y_SETUP, mask=VALID, h=10, target=None, kind="setup")}
for t in (0.10, 0.15, 0.20, 0.30):
    for hh in (3, 5, 10):
        DEFS[f"fixed_{int(t*100)}_{hh}"] = dict(label=f"고정 {hh}거래일 내 고가 +{int(t*100)}%", y=(FH[:, :hh].max(1) >= 1 + t).astype(int), mask=np.ones(N, bool), h=hh, target=t * 100, kind="fixed")
for k in (2, 3, 4):
    DEFS[f"atr{k}"] = dict(label=f"변동성 조정: 5거래일 최대상승 ≥ {k}×ATR14%", y=(okA & (mx5 >= k * np.nan_to_num(ATR, nan=9))).astype(int), mask=okA, h=5, target=None, kind="atr", k=k)
DEFS["beat_iwm10"] = dict(label="시장 대비: 5거래일 수익률이 IWM보다 +10%p 이상", y=(okI & (ex_iwm >= 0.10)).astype(int), mask=okI, h=5, target=None, kind="excess")
DEFS["beat_peer10"] = dict(label="섹터 대비: 5거래일 수익률이 같은 섹터 표본 중앙값보다 +10%p 이상", y=(r5 - peer >= 0.10).astype(int), mask=np.ones(N, bool), h=5, target=None, kind="excess")
dates = np.array(sorted(df["asof"].unique())); cut = dates[int(len(dates) * 0.8)]
fit_all = (df["asof"] < cut).values & ~art; cal_all = (df["asof"] >= cut + pd.Timedelta(days=7)).values & ~art
RD = {"created": OUT["created"], "recommended": "setup", "signals": [c[2:] for c in L.SIG], "defs": {}}
for key, D in DEFS.items():
    yv, m_ = D["y"], D["mask"]
    _, _, _, res = run_def(yv, m_) if key != "setup" else (None, None, None, R_S)
    L.y = yv
    w, gate = L.gated_weights(fit_all & m_)
    L.y = y0
    rc = L.weighted(L.S[cal_all & m_], w)
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.001, y_max=0.999).fit(rc, yv[cal_all & m_])
    xs = np.unique(np.quantile(rc, np.linspace(0, 1, 120)))
    rq = float(np.quantile(rc, 0.95))
    RD["defs"][key] = dict(label=D["label"], kind=D["kind"], horizon_days=D["h"], target_pct=D["target"], k=D.get("k"),
                           weights={c[2:]: float(w[j]) for j, c in enumerate(L.SIG)}, iso=dict(x=[float(v) for v in xs], y=[float(v) for v in iso.predict(xs)]),
                           threshold=dict(q=0.05, raw=rq, prob=float(iso.predict([rq])[0])), oos=res, base_rate=res["base"])
    print("def", key, {k_: res[k_] for k_ in ("base", "auc")}, res["top5"]["prec"], flush=True)
OUT["defs_oos"] = {k: v["oos"] for k, v in RD["defs"].items()}
(ROOT / "model/research_defs.json").write_text(json.dumps(RD, ensure_ascii=False, default=float), encoding="utf-8")
(ROOT / "model/target_grid.json").write_text(json.dumps(OUT, ensure_ascii=False, default=lambda o: o.item() if hasattr(o, "item") else str(o)), encoding="utf-8")
print("saved", round(time.time() - t0))
