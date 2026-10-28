"""docs/SUCCESS_ANALYSIS.md + model/success_analysis.json (앱 요약용) 생성"""
import sys, json, math, urllib.parse; from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
import pandas as pd, numpy as np
C = pd.read_pickle(ROOT / "data/sa_cases.pkl"); O = pd.read_pickle(ROOT / "data/sa_compare.pkl")
Mx = json.loads((ROOT / "model/success_analysis_metrics.json").read_text())
E = pd.read_pickle(ROOT / "data/sa_events.pkl")
def P(v, d=1): return "—" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v*100:.{d}f}%"
def gnews(t, d):
    d0 = (pd.Timestamp(d) - pd.Timedelta(days=4)).date(); d1 = (pd.Timestamp(d) + pd.Timedelta(days=10)).date()
    return "https://news.google.com/search?q=" + urllib.parse.quote(f'"{t}" after:{d0} before:{d1}')
C["link2"] = [u if isinstance(u, str) and u else gnews(t, d) for u, t, d in zip(C.link, C.ticker, C.date)]
C["src2"] = [s if isinstance(s, str) and s else "검색 결과 없음 (Google News 검색 링크)" for s in C.src]
SIGN = {"s_low_float": "저유통", "s_runner": "과거급등주", "s_ssr": "SSR", "s_gap_hold": "갭유지", "s_offering_done": "공모완료", "d424_30": "424B≤30일", "reg30": "증권신고서≤30일",
        "mom5": "5일+50%", "prev_spike": "직전5일 +40%봉", "day20": "당일+20%", "rvol5": "RVOL≥5", "rvol_lo": "RVOL<1.5", "k8_2": "8-K/6-K≤2일", "rs60": "위임장≤60일"}
def sigs(r): return ", ".join(v for k, v in SIGN.items() if pd.notna(r.get(k)) and r.get(k) >= 1) or "—"
def cats(g):
    x = C[C.group == g]; vc = x.cat.value_counts(); return [dict(cat=k, n=int(v), pct=float(v / len(x))) for k, v in vc.items()], len(x)
sc, ns = cats("success"); fc, nf = cats("fail")
m = Mx["models"]; ex = Mx["exits"]
b, a, po = m["before"], m["after"], m["pen_only"]
ok = C[(C.group == "success") & ~C.cat.isin(["원인 불명", "데이터 오류"])]
timing = dict(known=int(len(ok)), before_or_same=int((ok.lag <= 0).sum()), after=int((ok.lag > 0).sum()))
keyfe = ["424B(공모) 30일 이내", "공모 완료(s_offering_done)", "S-1/S-3/F-1/F-3 등록 30일 이내", "RVOL < 1.5", "5일 수익률 +50% 이상", "직전5일 중 +40% 일봉 있음", "당일 +50% 이상", "RVOL ≥ 5", "8-K/6-K 2일 이내(신선한 재료)", "위임장(DEF/PRE 14A) 60일 이내(역분할 투표 가능)", "반복 경보(4번째 이후)"]
OK = O.set_index("feature").loc[keyfe].reset_index()
def case_rows(g):
    x = C[C.group == g].sort_values("maxup10" if g == "success" else "minlo10", ascending=(g != "success"))
    return [dict(ticker=r["ticker"], date=r["date"], pick=r["pick"], max5=float(r["maxup10"]), min10=float(r["minlo10"]), cat=r["cat"], cause=r["cause"], link=r["link2"], src=r["src2"], signals=sigs(r)) for r in x.to_dict("records")]
S_rows, F_rows = case_rows("success"), case_rows("fail")
J = dict(created=Mx["created"], n_success=ns, n_fail=nf, success_cats=sc, fail_cats=fc, timing=timing,
         final=dict(before=dict(prec=b["top5"]["prec"], ci=b["top5"]["ci"], n=b["top5"]["n"], lift=b["top5"]["lift"], auc=b["auc"], base=b["base"], exp=ex["before"]["nested_stats"]["exp"], exp_ci=ex["before"]["nested_stats"]["ci"], trades=ex["before"]["nested_stats"]["n"]),
                    after=dict(prec=a["top5"]["prec"], ci=a["top5"]["ci"], n=a["top5"]["n"], lift=a["top5"]["lift"], auc=a["auc"], base=a["base"], exp=ex["after"]["nested_stats"]["exp"], exp_ci=ex["after"]["nested_stats"]["ci"], trades=ex["after"]["nested_stats"]["n"]),
                    pen_only=dict(prec=po["top5"]["prec"], ci=po["top5"]["ci"], n=po["top5"]["n"], auc=po["auc"]),
                    diff_ci=a["diff_vs_before_ci"], event_first=float(E.first_hit.mean()), event_any=float(E.any_hit.mean()), n_events=int(len(E)), adopted=False),
         features=[dict(f=r.feature, n=int(r.n), hit=float(r.hit), rest=float(r.rest), lift=float(r.lift_vs_rest)) for r in OK.itertuples()],
         success=S_rows, fail=F_rows)
(ROOT / "model/success_analysis.json").write_text(json.dumps(J, ensure_ascii=False, indent=1, default=float), encoding="utf-8")

L = [f"# 성공·실패 사례 원인 분석 + 최종 적중률 ({Mx['created']})", "",
     "> **투자 권유 아님.** 과거 무료 데이터(가격: yfinance, 공시: SEC EDGAR, 뉴스: Google News RSS) 기반 연구이며, 확률·적중률은 모두 **추정치**입니다. 미래를 보장하지 않습니다.", "",
     "## 0. 한 줄 요약 (초보자용)", "",
     f"- **최종 적중률(표본외, 상위 5% 경보, '5거래일 안에 +30%')**: 현재 채택 모델 **{P(b['top5']['prec'])}** (95% CI {P(b['top5']['ci'][0])}~{P(b['top5']['ci'][1])}, n={b['top5']['n']:,}, 기본율 {P(b['base'])}, lift {b['top5']['lift']:.2f}배, AUC {b['auc']:.3f}).",
     f"- 사례 분석을 반영한 실험 모델: **{P(a['top5']['prec'])}** (95% CI {P(a['top5']['ci'][0])}~{P(a['top5']['ci'][1])}, n={a['top5']['n']:,}, lift {a['top5']['lift']:.2f}배, AUC {a['auc']:.3f}). 차이 +{(a['top5']['prec']-b['top5']['prec'])*100:.1f}%p 이지만 95% CI {a['diff_vs_before_ci'][0]*100:+.1f}~{a['diff_vs_before_ci'][1]*100:+.1f}%p 로 **0을 포함 → 통계적으로 유의하지 않음**. AUC 는 오히려 소폭 하락 → **앱 기본 모델은 바꾸지 않음(미채택)**.",
     f"- 즉 경보 4~5개 중 약 1개만 5일 안에 +30%를 찍습니다. 같은 종목 연속 경보를 한 '이벤트'로 묶으면 첫 경보 기준 {P(E.first_hit.mean())}, 이벤트 중 한 번이라도 적중 {P(E.any_hit.mean())} ({len(E)}개 이벤트).",
     f"- 매매 기대값(청산 규칙은 이전 폴드로만 선택, 비용 0.6% 차감): 이전 {P(ex['before']['nested_stats']['exp'],2)} (CI {P(ex['before']['nested_stats']['ci'][0],2)}~{P(ex['before']['nested_stats']['ci'][1],2)}) → 실험 {P(ex['after']['nested_stats']['exp'],2)} (CI {P(ex['after']['nested_stats']['ci'][0],2)}~{P(ex['after']['nested_stats']['ci'][1],2)}). **둘 다 0 이하 또는 0 포함 → 검증된 수익 규칙 없음.**",
     "- 성공 원인 1위는 **원인 불명(뉴스·공시 없음)**, 그다음 계약·M&A, 역분할 직후 저유통, 실적, AI/우주 테마 피벗. 실패 원인 1위는 **유상증자·희석**(원인 불명과 동률), 그다음 'PR 펌프 후 소멸', 역분할 덤프.",
     "- 가장 확실한 '미리 보이는' 실패 신호: **최근 30일 안에 424B(공모 확정) 공시** → 경보 적중률 13.8% (나머지 24.7%의 약 절반).", "",
     "## 1. 방법", "",
     "- 대상: 기존 5폴드 워크포워드의 **표본외** 상위 5% 경보 2,224건 → 같은 종목 7일 이내 경보를 묶어 755개 이벤트.",
     "- 성공 표본 45개 = 첫 경보가 5일 내 +30% 적중한 이벤트 중 **상승률 상위 30개 + 무작위 15개**. 실패 표본 40개 = 첫 경보가 실패한 이벤트 중 **10일 최저가 하위 25개(손절 맞은 큰 손실) + 무작위 15개**.",
     "- 각 사례마다 경보일-30일~고점(실패는 +8일)+2일 구간의 SEC 공시(8-K/6-K 항목 코드·EX-99 제목, 424B, S-1/F-1/S-3/F-3, EFFECT, DEF 14A)와 Google News 헤드라인을 수집해 **사람이 읽고 분류**. 근거가 없으면 '원인 불명'. 지어내지 않음.",
     "- 뉴스 매칭이 애매한 일반 단어 티커(IVF, CRE, RCT 등)는 회사명/주가 문맥이 있는 기사만 인정.",
     "- **데이터 오류 발견**: QH 2026-04-15 '+3,686%' 는 DB 가격의 미조정 역분할 점프(4/27 0.12→3.60). 실제 상승이 아니므로 재학습에서 아티팩트 구간 행을 제외함.", "",
     f"## 2. 성공 원인 카테고리 (n={ns})", "", "| 카테고리 | 건수 | 비율 |", "|---|---|---|"]
L += [f"| {c['cat']} | {c['n']} | {P(c['pct'])} |" for c in sc]
L += ["", f"## 3. 실패 원인 카테고리 (n={nf})", "", "| 카테고리 | 건수 | 비율 |", "|---|---|---|"] + [f"| {c['cat']} | {c['n']} | {P(c['pct'])} |" for c in fc]
L += ["", "### 해석", "",
      f"- 원인이 확인된 성공 {timing['known']}건 중 근거(기사/공시) 날짜가 경보일 **당일 이전**인 것은 {timing['before_or_same']}건, **경보 이후**는 {timing['after']}건. → 상당수 재료는 경보 시점에 아직 공개되지 않았음(거래량·가격이 먼저 움직임). 따라서 '재료 자체'를 미리 특징으로 쓰기는 어렵습니다.",
      "- 성공과 실패 양쪽에 'PR(계약·AI·임상) 급등'이 있음: 같은 PR 이라도 **직후 공모(424B)·재판매 등록(EFFECT)·역분할 발표**가 붙으면 실패 쪽으로 감. (예: GRI 임상 PR→4일 뒤 424B5, BCTX 급등 당일 $30M 공모, CIRC 계약 PR→다음날 424B3)",
      "- 역분할은 양면적: 역분할 **직후(유통주식 감소)** 는 급등(TNON, ISPC, WHLR 9월), 역분할 **발표 시점** 은 덤프(HUBC, EZGO, PMAX 4월).",
      "- '원인 불명' 이 성공 33%, 실패 28% → 초소형주 급등의 상당 부분은 공개 재료 없이 수급(저유통·모멘텀 트레이더)으로 발생.", "",
      "## 4. 미리 볼 수 있는 신호 비교 (경보 시점 종가까지의 정보만, 미래 정보 없음)", "",
      "### 4-1. 전체 표본외 경보 2,217건 (아티팩트 제외) — 통계적으로 의미 있는 비교", "",
      "| 경보 시점 특징 | 해당 경보 수 | 적중률 | 나머지 적중률 | 배수 |", "|---|---|---|---|---|"]
L += [f"| {r.feature} | {int(r.n)} | {P(r.hit)} ({P(r.lo)}~{P(r.hi)}) | {P(r.rest)} | {r.lift_vs_rest:.2f} |" for r in OK.itertuples()]
cm = C[C.cat != "데이터 오류"].groupby("group")[list(SIGN)].apply(lambda x: (x.fillna(0) >= 1).mean()).T
L += ["", "### 4-2. 조사 표본(성공 44 vs 실패 40)에서의 보유 비율", "", "| 신호 | 성공 사례 | 실패 사례 |", "|---|---|---|"]
L += [f"| {SIGN[k]} | {P(cm.loc[k,'success'],0)} | {P(cm.loc[k,'fail'],0)} |" for k in SIGN]
L += ["", "- **핵심 구분 신호**: ① 최근 424B/공모 완료(실패 42% vs 성공 9%; 전체 경보에서 적중률 0.56배) ② 강한 거래량(RVOL≥5: 성공 66% vs 실패 52%; 전체 1.29배) ③ 이미 강하게 오른 상태(5일 +50%, 당일 +50%)는 적중률을 **높이지만** 10일 최저가 중앙값도 -25~-33% 로 깊음 → '변동성이 크다'는 뜻이지 안전하다는 뜻이 아님.",
      "- 표본에서 성공 쪽이 많았던 '8-K 2일 이내'는 전체 경보에서는 차이가 없음(1.00배) → 일반화되지 않는 표본 착시.", "",
      "## 5. 특징·감점 반영 후 같은 5폴드 워크포워드 재실행", "",
      "- 가점 후보 4개(5일+50%, 직전5일 +40%봉, 당일+20%, RVOL≥5)는 기존과 같은 게이트(학습 구간 n≥25·lift≥1)를 통과할 때만 가중치. 감점 후보 3개(424B≤30일, 증권신고서≤30일, RVOL<1.5)는 **각 폴드의 학습 구간 상위 10% 후보 안에서만** 비율을 추정하고 Wilson 상한이 나머지보다 낮을 때만 0.3~1 배수 적용. 임계값·청산 규칙도 학습 폴드에서만 선택.",
      f"- 아티팩트 제외 행: {Mx['artifact_rows']}개 (데이터셋 기준).", "",
      "| 지표 (표본외, 상위 5%) | 이전 (게이트 가중) | 감점만 추가 | 신호+감점 (실험) |", "|---|---|---|---|",
      f"| 적중률 (95% CI) | {P(b['top5']['prec'])} ({P(b['top5']['ci'][0])}~{P(b['top5']['ci'][1])}) | {P(po['top5']['prec'])} ({P(po['top5']['ci'][0])}~{P(po['top5']['ci'][1])}) | {P(a['top5']['prec'])} ({P(a['top5']['ci'][0])}~{P(a['top5']['ci'][1])}) |",
      f"| 경보 수 n | {b['top5']['n']:,} | {po['top5']['n']:,} | {a['top5']['n']:,} |",
      f"| 기본율 | {P(b['base'])} | {P(po['base'])} | {P(a['base'])} |",
      f"| lift | {b['top5']['lift']:.2f} | {po['top5']['lift']:.2f} | {a['top5']['lift']:.2f} |",
      f"| AUC | {b['auc']:.3f} | {po['auc']:.3f} | {a['auc']:.3f} |",
      f"| 상위 10% 적중률 | {P(b['top10']['prec'])} | {P(po['top10']['prec'])} | {P(a['top10']['prec'])} |",
      f"| 이전 대비 상위5% 차이 95% CI | — | {po['diff_vs_before_ci'][0]*100:+.1f}~{po['diff_vs_before_ci'][1]*100:+.1f}%p | {a['diff_vs_before_ci'][0]*100:+.1f}~{a['diff_vs_before_ci'][1]*100:+.1f}%p |",
      f"| 폴드별 상위5% 적중률 | {' / '.join(P(f['prec'],0) for f in b['fold_top5'])} | — | {' / '.join(P(f['prec'],0) for f in a['fold_top5'])} |",
      f"| 중첩 청산 기대값/거래 (CI, 거래수) | {P(ex['before']['nested_stats']['exp'],2)} ({P(ex['before']['nested_stats']['ci'][0],2)}~{P(ex['before']['nested_stats']['ci'][1],2)}, {ex['before']['nested_stats']['n']}) | — | {P(ex['after']['nested_stats']['exp'],2)} ({P(ex['after']['nested_stats']['ci'][0],2)}~{P(ex['after']['nested_stats']['ci'][1],2)}, {ex['after']['nested_stats']['n']}) |",
      f"| 중첩 청산 승률 / MDD(10% 배분) | {P(ex['before']['nested_stats']['win'])} / {P(ex['before']['nested_stats']['mdd'])} | — | {P(ex['after']['nested_stats']['win'])} / {P(ex['after']['nested_stats']['mdd'])} |", "",
      "### 정직한 결론", "",
      "- 실패 특성 **감점만** 넣으면 상위 5% 적중률은 그대로(22.5%), AUC 는 하락. 424B 효과는 폴드 3 이후에야 학습 구간에서 유의해져 초기 폴드에는 적용되지 않았음.",
      "- 신호+감점 실험 모델은 상위 5% 적중률 +1.9%p, 5폴드 중 4개에서 개선됐지만 **CI 가 0을 포함 → 우연일 수 있음**. AUC 소폭 하락, 기대값도 여전히 0 근처 음수.",
      "- 그래서 **앱의 점수 모델은 바꾸지 않았고**, 이 결과는 '참고용 연구'로만 앱(타임머신 탭)에 표시. 대신 '최근 30일 424B 공모'는 경보를 볼 때 직접 확인할 주의 사항으로 안내.",
      "- 생존 편향: 표본은 현재 상장 종목에서 추출 → 상장폐지된 실패 사례 누락, 실제는 더 나쁠 수 있음. 분류는 1인 수작업이며 뉴스 검색 누락 가능.", ""]
def tbl(rows, g):
    hd = "| # | 티커 | 첫 경보일 | 선정 | 5일 최고 | 10일 최저 | 카테고리 | 원인 | 근거 | 경보 시점 신호 |"
    out = [hd, "|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        out.append(f"| {i} | {r['ticker']} | {r['date']} | {'상위' if r['pick'] in ('top','worst') else '무작위'} | {P(r['max5'],0)} | {P(r['min10'],0)} | {r['cat']} | {r['cause']} | [{r['src'].replace('|','/')}]({r['link']}) | {r['signals']} |")
    return out
L += [f"## 6. 성공 사례표 (n={ns})", ""] + tbl(S_rows, "s") + ["", f"## 7. 실패 사례표 (n={nf})", ""] + tbl(F_rows, "f")
L += ["", "## 8. 재현", "", "```", "python scripts/sa_events.py      # 경보→이벤트", "python scripts/sa_research.py    # SEC·뉴스 근거 수집 → data/sa_evidence.json", "python scripts/sa_titles.py      # 8-K/6-K 제목 보강",
      "python scripts/sa_splits.py      # 미조정 역분할 탐지", "python scripts/sa_features.py    # 경보 시점 특징", "python scripts/sa_analyze.py     # 분류표(scripts/sa_cases.py) 결합", "python scripts/sa_compare.py     # 전체 경보 특징 비교",
      "python scripts/sa_rerun.py       # 5폴드 재실행", "python scripts/sa_report.py      # 이 문서 + model/success_analysis.json", "```", "", "> 투자 권유가 아님. 모든 수치는 과거 데이터 기반 추정치입니다."]
(ROOT / "docs/SUCCESS_ANALYSIS.md").write_text("\n".join(L), encoding="utf-8"); print("ok", len(L))
