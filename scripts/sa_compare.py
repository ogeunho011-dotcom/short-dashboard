"""OOS 경보 전체(2,224건)에서 '움직임 이전' 특징별 적중률 비교 (성공=5일내 +30%)."""
import sys; from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
import pandas as pd, numpy as np, math, json
def wilson(k, n, z=1.96):
    if n == 0: return (0, 0)
    p = k / n; d = 1 + z*z/n; c = p + z*z/(2*n); r = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n)); return ((c-r)/d, (c+r)/d)
A = pd.read_pickle(ROOT / "data/sa_alerts.pkl").merge(pd.read_pickle(ROOT / "data/sa_feat.pkl"), on=["ticker", "asof"], how="left")
ds = pd.read_pickle(ROOT / "data/research_ds.pkl"); ds["asof"] = pd.to_datetime(ds["asof"])
A = A.merge(ds[["ticker", "asof", "s_low_float", "s_runner", "s_ssr", "s_gap_hold", "s_offering_done", "dilution_recent", "s_catalyst", "s_vol"]], on=["ticker", "asof"], how="left")
A = A[A.art_fwd == 0]
A["nth"] = A.sort_values("asof").groupby("event").cumcount() + 1
conds = {
 "첫 경보(이벤트 내 1번째)": A.nth == 1, "반복 경보(4번째 이후)": A.nth >= 4,
 "당일 +20% 이상 이미 상승": A.ret1 >= 0.20, "당일 +50% 이상": A.ret1 >= 0.5, "당일 -5% 이하(눌림)": A.ret1 <= -0.05,
 "직전5일 중 +40% 일봉 있음": A.up_prev5 >= 0.4, "5일 수익률 +50% 이상": A.ret5 >= 0.5,
 "고점 대비 15%+ 밀려 마감(fade)": A.fade >= 0.15, "종가가 일중 상단 25%": A.clv >= 0.75,
 "RVOL ≥ 5": A.rvol >= 5, "RVOL < 1.5": A.rvol < 1.5, "전일 거래량 이미 3배+": A.vol_prev >= 3,
 "424B(공모) 30일 이내": A.d_424b <= 30, "424B 7일 이내": A.d_424b <= 7, "S-1/S-3/F-1/F-3 등록 30일 이내": A.d_reg <= 30,
 "8-K/6-K 2일 이내(신선한 재료)": A.d_8k <= 2, "8-K/6-K 15일+ 없음": A.d_8k >= 15, "위임장(DEF/PRE 14A) 60일 이내(역분할 투표 가능)": A.d_rs <= 60,
 "20일 고점 근처(-10% 이내)": A.dist_hi20 >= -0.10, "60일 고점 대비 -70% 이하": A.dd60 <= -0.70,
 "주가 < $1": A.price < 1, "주가 $1–3": (A.price >= 1) & (A.price < 3), "저유통(s_low_float)": A.s_low_float >= 1,
 "과거 급등주(s_runner)": A.s_runner >= 1, "SSR 발동": A.s_ssr >= 1, "갭 유지(s_gap_hold)": A.s_gap_hold >= 1, "공모 완료(s_offering_done)": A.s_offering_done >= 1,
}
base = A.hit.mean(); out = []
for nm, m in conds.items():
    m = m.fillna(False); k, n = int(A.hit[m].sum()), int(m.sum()); k2, n2 = int(A.hit[~m].sum()), int((~m).sum())
    lo, hi = wilson(k, n)
    out.append(dict(feature=nm, n=n, hit=k / n if n else np.nan, lo=lo, hi=hi, rest=k2 / n2 if n2 else np.nan, d5=float(A.d5[m].mean()) if n else np.nan, minlo=float(A.minlo[m].median()) if n else np.nan))
O = pd.DataFrame(out); O["lift_vs_rest"] = O.hit / O.rest
pd.set_option("display.width", 200); print("alerts", len(A), "base", round(base, 4)); print(O.round(3).to_string())
O.to_pickle(ROOT / "data/sa_compare.pkl")
