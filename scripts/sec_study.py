"""🔬 SEC 퀵스캔 점수(core.secscan.score) 시점 기준 이벤트 스터디 → model/sec_study.json (DB 공시 목록·XBRL·일봉만, 네트워크 없음).
표본: 유니버스(초소형~소형) 종목 × 2024-01 이후 10거래일마다 한 번. 그 날 '종가까지' 접수된 공시·XBRL 값만으로 pit() → score(F, None)
(원문 해석 없이 — 앱 퀵스캔은 원문 항목이 더해지므로 이 검증은 공시 목록·XBRL 부분만 검증한 것).
결과: 다음 거래일 시가 진입 → 5일 안 +30% 터치, 5일·20일 수익률, 20일 최저가. 비교 기준 = 같은 가격대(<$1, $1~5, $5↑) 전체 표본(가격대 비중 맞춤).
근거 성립: 표본 ≥ 30 · 종목 ≥ 20 · 20일 수익률 중앙값 차이 ≤ −5%p (위험 등급) · 순위 검정 p < 0.05 · 앞/뒤 절반 같은 방향.
성립해도 앱 점수에는 넣지 않고 참고 표시만 (점수 반영은 별도 결정).
한계: 현재 상장 종목만(상폐 빠짐 → 위험 등급 결과가 실제보다 좋게 나옴) · 역분할 조정 가격 · XBRL 누락 종목은 '확인되지 않음' 점수.
실행: python scripts/sec_study.py [--step 10] [--max 0]"""
import sys, json, time, argparse
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import db, secscan as SS
sys.path.insert(0, str(ROOT / "scripts"))
from events_build import outcomes, bucket

START = "2024-01-01"

def samples(step=10, max_t=0):
    U = db.q("SELECT ticker FROM universe WHERE tier IN ('micro','nano','small')").ticker.tolist()
    if max_t: U = U[:max_t]
    out, t0 = [], time.time()
    for n, t in enumerate(U):
        px = db.q("SELECT date, open, high, low, close, volume FROM prices WHERE ticker=? ORDER BY date", (t,))
        if len(px) < 80: continue
        px["date"] = pd.to_datetime(px["date"]); px = px[(px.close > 0) & (px.open > 0)].reset_index(drop=True)
        fr = db.q("SELECT form, filed, items, accession acc FROM filings WHERE ticker=? ORDER BY filed DESC", (t,))
        if not len(fr): continue
        rows = fr.to_dict("records")
        fx = SS.from_basic(db.kv_get(f"facts:{t}") or {})
        R = outcomes(px)
        idx = [i for i in range(60, len(px) - 21, step) if px.date.iloc[i] >= pd.Timestamp(START)]
        for i in idx:
            a = str(px.date.iloc[i].date())
            if np.isnan(R["r20"][i]): continue
            F = SS.pit(rows, fx, px.iloc[: i + 1], a)
            if not F.get("price"): continue
            S = SS.score(F, None)
            out.append(dict(t=t, d=a, total=S["total"], grade=S["grade"], b=bucket(F["price"]), r5=R["r5"][i], r20=R["r20"][i], hit30=R["hit30"][i],
                            mdd20=R["mdd20"][i], **{x["k"]: x["pts"] for x in S["items"]}))
        if n % 200 == 0: print(f"{n}/{len(U)} {len(out)} samples {time.time() - t0:.0f}s", flush=True)
    return pd.DataFrame(out)

def compare(x, base, all_):
    from scipy.stats import mannwhitneyu
    if len(x) < 5: return None
    w = x.b.value_counts(normalize=True)
    exp = lambda col, f: float(sum(w.get(k, 0) * f(base[k][col]) for k in w.index))
    o = dict(n=int(len(x)), tickers=int(x.t.nunique()),
             hit30=float(x.hit30.mean()), hit30_base=exp("hit30", np.mean),
             r5_med=float(x.r5.median()), r5_base=exp("r5", np.median),
             r20_med=float(x.r20.median()), r20_base=exp("r20", np.median),
             mdd20_med=float(x.mdd20.median()))
    o["hit30_diff"] = o["hit30"] - o["hit30_base"]; o["r20_diff"] = o["r20_med"] - o["r20_base"]; o["r5_diff"] = o["r5_med"] - o["r5_base"]
    rest = all_.drop(x.index)
    try: o["p_r20_less"] = float(mannwhitneyu(x.r20, rest.r20, alternative="less").pvalue)
    except Exception: o["p_r20_less"] = None
    try: o["p_hit_greater"] = float(mannwhitneyu(x.hit30, rest.hit30, alternative="greater").pvalue)
    except Exception: o["p_hit_greater"] = None
    return o

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--step", type=int, default=10); ap.add_argument("--max", type=int, default=0)
    a = ap.parse_args()
    t0 = time.time()
    df = samples(a.step, a.max)
    print("samples", len(df), "tickers", df.t.nunique(), f"{time.time() - t0:.0f}s")
    base = {k: g for k, g in df.groupby("b")}
    mid = df.d.sort_values().iloc[len(df) // 2]
    res = dict(meta=dict(ts=time.strftime("%Y-%m-%d %H:%M"), n=int(len(df)), tickers=int(df.t.nunique()), start=START, step=a.step, mid=mid,
                         base=dict(hit30=float(df.hit30.mean()), r5_med=float(df.r5.median()), r20_med=float(df.r20.median()))), groups={})
    df["q"] = pd.qcut(df.total.rank(method="first"), 5, labels=["Q1(낮음)", "Q2", "Q3", "Q4", "Q5(높음)"])
    for col, key in (("grade", "등급"), ("q", "점수 5분위")):
        for k, x in df.groupby(col, observed=True):
            o = compare(x, base, df)
            if not o: continue
            h1, h2 = compare(x[x.d < mid], base, df), compare(x[x.d >= mid], base, df)
            o["half1_r20_diff"] = h1 and h1["r20_diff"]; o["half2_r20_diff"] = h2 and h2["r20_diff"]
            o["half1_hit_diff"] = h1 and h1["hit30_diff"]; o["half2_hit_diff"] = h2 and h2["hit30_diff"]
            o["risk_holds"] = bool(o["n"] >= 30 and o["tickers"] >= 20 and o["r20_diff"] <= -0.05 and (o["p_r20_less"] or 1) < 0.05
                                   and (o["half1_r20_diff"] or 0) <= -0.02 and (o["half2_r20_diff"] or 0) <= -0.02)
            o["surge_holds"] = bool(o["n"] >= 30 and o["tickers"] >= 20 and o["hit30_diff"] >= 0.05 and (o["p_hit_greater"] or 1) < 0.05
                                    and (o["half1_hit_diff"] or 0) >= 0.02 and (o["half2_hit_diff"] or 0) >= 0.02)
            res["groups"][f"{key}:{k}"] = o
    items = {}
    for k in ("evidence", "clarity", "dilution", "balance", "catalyst", "market", "motive", "pricemap", "downside"):
        lo = df[df[k] <= df[k].quantile(0.2)]
        if len(lo) >= 30 and len(lo) < len(df):
            c = compare(lo, base, df); items[k] = dict(n=c["n"], r20_diff=c["r20_diff"], hit30_diff=c["hit30_diff"])
    res["items_low20"] = items
    G = res["groups"]
    risk = [k for k, v in G.items() if v["risk_holds"]]; surge = [k for k, v in G.items() if v["surge_holds"]]
    gd = G.get("등급:D") or {}
    res["verdict"] = (f"2024-01 이후 {res['meta']['n']:,}개 표본({res['meta']['tickers']:,}종목) 시점 기준 검증 — "
                      + (f"D등급 5일 +30% 터치 {gd.get('hit30', 0) * 100:.1f}% (기준 {gd.get('hit30_base', 0) * 100:.1f}%), 20일 수익률 중앙값 {gd.get('r20_med', 0) * 100:+.1f}% (기준 {gd.get('r20_base', 0) * 100:+.1f}%) · " if gd else "")
                      + ("위험 구분 근거 성립: " + ", ".join(risk) if risk else "위험 구분 근거 불충분")
                      + " · " + ("급등 예측 근거 성립: " + ", ".join(surge) if surge else "급등 예측 근거 없음")
                      + (f" · 점수 하위 20%는 +30% 터치가 오히려 높고(변동성 큼) 20일 수익률이 나쁨({q1['r20_diff'] * 100:+.1f}%p), 상위 20%는 조용함(터치 {q5['hit30'] * 100:.1f}%)"
                         if (q1 := G.get("점수 5분위:Q1(낮음)")) and (q5 := G.get("점수 5분위:Q5(높음)")) else "")
                      + " → 앱 점수 미반영, 참고용 (급등 신호 아님: 구조 위험 정리용)")
    (ROOT / "model").mkdir(exist_ok=True)
    (ROOT / "model/sec_study.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))
    print(res["verdict"])
    for k, v in G.items():
        print(f"{k:14s} n={v['n']:6d} t={v['tickers']:5d} hit30 {v['hit30'] * 100:5.1f}% vs {v['hit30_base'] * 100:5.1f}% | r5 {v['r5_med'] * 100:+5.1f}% vs {v['r5_base'] * 100:+5.1f}% | "
              f"r20 {v['r20_med'] * 100:+5.1f}% vs {v['r20_base'] * 100:+5.1f}% p={v['p_r20_less'] if v['p_r20_less'] is None else round(v['p_r20_less'], 4)} halves {v['half1_r20_diff']} {v['half2_r20_diff']} risk={v['risk_holds']} surge={v['surge_holds']}")
    print("items(low 20%)", json.dumps(items, default=float))

if __name__ == "__main__": main()
