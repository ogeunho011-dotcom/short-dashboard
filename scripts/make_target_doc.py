"""model/target_grid.json + research_defs.json + case_cards.json → docs/TARGET_GRID.md (한국어)"""
import json, collections
from pathlib import Path
R = Path(__file__).resolve().parent.parent
g = json.load(open(R/"model/target_grid.json")); D = json.load(open(R/"model/research_defs.json"))
cards = json.load(open(R/"model/case_cards.json"))
P = lambda x: "—" if x is None else f"{x*100:.1f}%"
Ps = lambda x: "—" if x is None else f"{x*100:+.2f}%"
CI = lambda c: f"{c[0]*100:.1f}~{c[1]*100:.1f}%"
CIs = lambda c: f"{c[0]*100:+.2f}~{c[1]*100:+.2f}%"
S = g["setup"]; L = []; w = L.append
w("# 성공 정의 재검토 · 목표 그리드 · 셋업(SHFS형) 분석\n")
w(f"> 생성: {g['created']} · 데이터: 무료 소스(yfinance 일봉, FINRA Reg SHO 일간 공매도 거래량, Nasdaq 공표 SI, SEC EDGAR) · "
  "**투자 조언이 아닙니다.** 모든 수치는 과거 백테스트(워크포워드 5폴드 OOS)이며 미래 수익을 보장하지 않습니다. "
  "'추정' 표기 값은 추정치입니다.\n")
w("## 0. 한 줄 결론 (초보자용)\n")
w("- **적중률이 낮았던 주된 이유는 '조건이 까다로워서'가 맞습니다.** 기존 정의(+30%/5일)는 원래 일어날 확률(기저율)이 약 8%라 경보가 22%를 맞혀도 낮아 보입니다.")
w("- 목표를 쉽게(+10%, 10일) 바꾸면 적중률은 59%까지 올라가지만, **비용(0.6%) 차감 후 기대수익은 거의 0이거나 마이너스**입니다. 적중률 ≠ 수익.")
w(f"- 96개 조합 중 **기대수익 신뢰구간이 0을 확실히 넘는 조합은 없습니다.** 최고 셀도 +{g['grid_best']['trade']['exp']*100:.2f}% (95% CI {CIs(g['grid_best']['trade']['ci'])}).")
w(f"- 새 **셋업 기반(SHFS형) 정의**의 기저율은 {P(S['base_rate'])}. 기존 경보(상위5%)는 {P(S['top5']['hit'])} (리프트 {S['top5']['lift']:.2f}) — 오히려 기저율보다 낮음. "
  f"셋업 라벨로 재학습한 모델은 {P(S['retrained_top5']['hit'])} (리프트 {S['retrained_top5']['lift']:.2f})까지 오르지만 거래 기대수익 {Ps(S['retrained_top5']['trade']['exp'])} (CI {CIs(S['retrained_top5']['trade']['ci'])}, 유의하게 마이너스).")
w("- **권장:** 화면 표시·확률 카드의 기본 정의는 **셋업 기반**(사용자 요청 스타일, 해석이 직관적). 단 '엣지(실력)' 판단은 리프트·기대수익으로만 하세요.\n")
w("## 1. 데이터 · FINRA\n")
w(f"- FINRA Reg SHO 일간 공매도 거래량(CNMSshvol) CDN에서 **720,326행 백필 성공**. 셋업 데이터셋 중 실제 FINRA 비중 {P(S['finra_real_share'])}, Nasdaq 공표 SI로 스케일한 행 {P(S['si_scaled_share'])}.")
w("- 숏 '물량대(트랜치)'·평균단가·손실권 비율은 공매도 거래량과 가격으로 만든 **추정치**입니다(실제 포지션 데이터는 무료로 없음). 대차 수수료(CTB)·대차 가능 수량 이력은 무료 소스가 없어 **사용하지 않고 추정도 하지 않습니다.**")
w(f"- 그리드 데이터: {g['n_rows']:,}행 (OOS 평가 {g['n_test']:,}행, 역분할 미조정 등 아티팩트 {g['artifact_rows']}행 제거).\n")
w("## 2. 헤드라인 — 셋업 기반(SHFS형) 성공 정의\n")
w("**정의(시점 기준, 미래 정보 미사용):** 경보일 종가에서 진입 → 손절 = 가장 가까운 아래 숏 트랜치 하단 아래, "
  "1차 익절 = 재점화 레벨(RL, 위 트랜치 손실권 전환 가격)에서 50% 매도 후 손절을 본전으로, 나머지는 21일 고점(PH) 또는 다음 트랜치 / 10일 종가 청산. "
  "같은 날 손절·목표가 모두 닿으면 **손절 우선**(보수적). **성공 = 손절 전에 RL 도달.** 비용 0.6% 왕복.\n")
w(f"- 유효 셋업 비율 {P(S['valid_share'])} (RL > 가격×1.005 이고 손절 < 가격×0.995).")
w("\n| 구간 | n | 적중률 (95% CI) | 리프트 | PH 재시험 | 거래 기대수익 (CI) | 승률 | MDD | 필요상승 중앙 | 위험 중앙 |")
w("|---|---|---|---|---|---|---|---|---|---|")
for k in ["top1","top2","top5","top5_ex424","top10","retrained_top5"]:
    x = S[k]; t = x["trade"]
    w(f"| {x['name']} | {x['n']:,} | {P(x['hit'])} ({CI(x['ci'])}) | {x['lift']:.2f} | {P(x['ph']['hit'])} | {Ps(t['exp'])} ({CIs(t['ci'])}) | {P(t['win'])} | {P(t.get('mdd'))} | {P(x['need_med'])} | {P(x['risk_med'])} |")
tb = S["top5"]["trade_base"]
w(f"| 기저(전체 셋업) | — | {P(S['base_rate'])} | 1.00 | {P(S['top5']['ph']['base'])} | {Ps(tb['exp'])} ({CIs(tb['ci'])}) | {P(tb['win'])} | — | {P(S['top5']['need_med_base'])} | {P(S['top5']['risk_med_base'])} |")
w("\n**해석:** 기존 급등(M1) 경보는 RL에서 멀리 떨어진(필요상승 중앙 ~29%) 종목을 고르기 때문에 셋업 기준 적중률이 기저보다 낮습니다. "
  "셋업 라벨로 재학습하면 RL에 가까운 종목(필요상승 중앙 ~5%)을 고르게 되어 적중률은 55%대로 오르지만, 이익 폭이 작고 손실 폭이 커서 기대수익은 마이너스입니다.\n")
for key, title in [("by_level","경보 레벨별"),("by_cp","커버 압력 지수 구간별"),("by_regime","시장 국면(IWM 20일)별")]:
    w(f"### {title}\n")
    w("| 구간 | 전체 n | 전체 적중률 (CI) | 전체 PH | 전체 기대수익 (CI) | 경보 n | 경보 적중률 | 경보 기대수익 (CI) |")
    w("|---|---|---|---|---|---|---|---|")
    for b in S[key]:
        w(f"| {b['bucket']} | {b['n_all']:,} | {P(b['hit_all'])} ({CI(b['ci_all'])}) | {P(b.get('ph_all'))} | {Ps(b['exp_all'])} ({CIs(b['exp_all_ci'])}) | {b['n_alert']:,} | {P(b['hit_alert']) if b['n_alert'] else '—'} | {Ps(b['exp_alert']) if b.get('exp_alert') is not None else '—'} ({CIs(b['exp_alert_ci']) if b.get('exp_alert_ci') else '—'}) |")
    w("")
w("> 커버 압력 지수는 'RL까지의 근접도'를 일부 포함하므로 구간별 적중률 상승은 **부분적으로 기계적**입니다(가까우면 당연히 더 잘 닿음). 기대수익은 대부분 구간에서 마이너스입니다.\n")
w("## 3. 고정 목표 그리드 (96칸)\n")
w("행 = 목표 수익률 × 기간, 열 = 모델 상위 분위. 각 칸: **적중률 (95% CI) / 기저율 / 리프트 / 비용 후 기대수익 (CI) / 승률 / MDD**. "
  "손절폭은 학습 폴드에서만 선택(중첩 선택, 테스트 폴드 미사용).\n")
grid = g["grid"]
for ex in [False, True]:
    w(f"### {'424B 공모 30일 내 제외' if ex else '전체 (424B 포함)'}\n")
    w("| 목표/기간 | 기저율 | 상위1% | 상위2% | 상위5% | 상위10% |"); w("|---|---|---|---|---|---|")
    for tg in [0.1,0.15,0.2,0.3]:
        for h in [3,5,10]:
            cells = {c["q"]: c for c in grid if c["excl424"]==ex and abs(c["target"]-tg)<1e-9 and c["h"]==h}
            if not cells: continue
            base = next(iter(cells.values()))["base"]
            row = [f"+{int(tg*100)}% / {h}일", P(base)]
            for q in [0.01,0.02,0.05,0.1]:
                c = cells.get(q)
                if not c: row.append("—"); continue
                t = c["trade"]
                row.append(f"{P(c['hit'])} ({CI(c['ci'])})<br>리프트 {c['lift']:.2f}<br>기대 {Ps(t['exp'])} ({CIs(t['ci'])})<br>승률 {P(t['win'])} · MDD {P(t['mdd'])}")
            w("| " + " | ".join(row) + " |")
    w("")
b = g["grid_best"]; t = b["trade"]
w("### 최고 칸 (비용 후 기대수익 기준)\n")
w(f"- **상위{int(b['q']*100)}% · {'424B 제외' if b['excl424'] else '전체'} · +{int(b['target']*100)}% / {b['h']}일**: 적중률 {P(b['hit'])}, 리프트 {b['lift']:.2f}, "
  f"기대수익 {Ps(t['exp'])} (95% CI {CIs(t['ci'])}), 거래 {t['n']:,}건, 승률 {P(t['win'])}, MDD {P(t['mdd'])}.")
w(f"- **CI가 0을 배제하는가? {'예' if b['ci_excludes_zero'] else '아니오'}.** {b['n_cells']}칸을 시험했으므로 다중검정 효과로 최고 칸은 운이 섞여 과대평가됐을 가능성이 큽니다. 실전 엣지로 보기 어렵습니다.\n")
w("## 4. 맥락 상대 정의 (상위5% 경보)\n")
C = g["context"]
names = {"atr2":"ATR 2배 상승","atr3":"ATR 3배","atr4":"ATR 4배","vol20_3":"20일 변동성 3σ","beat_iwm":"IWM 대비 초과(5일)","beat_iwm10":"IWM 대비 +10%p","beat_peer":"섹터 동종 대비 초과","beat_peer10":"동종 대비 +10%p"}
w("| 정의 | 기저율 | 적중률 (CI) | 리프트 | 기대수익 (CI) | 승률 |"); w("|---|---|---|---|---|---|")
for k, nm in names.items():
    x = C.get(k)
    if not x: continue
    t = x.get("trade") or {}
    w(f"| {nm} | {P(x['base'])} | {P(x['hit'])} ({CI(x['ci'])}) | {x['lift']:.2f} | {Ps(t.get('exp')) if t else '—'} ({CIs(t['ci']) if t else '—'}) | {P(t.get('win')) if t else '—'} |")
w(f"\n- 섹터 {C.get('sector_n')}개, 섹터 미상 {P(C.get('unknown_sector_share'))}. 섹터 라벨은 현재 기준(경미한 미래 정보).")
w("- 국면별(강세/약세: IWM 20일 수익률 ≥0/<0):")
for k, arr in C["regime"].items():
    w(f"  - {k}: " + " · ".join(f"{a['bucket']} {P(a['hit'])} (기저 {P(a['base'])}, 리프트 {a['lift']:.2f}, n={a['n']})" for a in arr))
w("")
w("## 5. 정의별 재학습 확률 모델 (관리 탭에서 선택)\n")
w("| 정의 | 기저율 | OOS AUC | Brier | 상위5% 정밀도 (CI) | 리프트 |"); w("|---|---|---|---|---|---|")
for k, d in D["defs"].items():
    o = d["oos"]; t5 = o["top5"]
    star = " ⭐권장" if k == D.get("recommended") else ""
    w(f"| {d['label']}{star} | {P(o['base'])} | {o['auc']:.3f} | {o['brier']:.3f} | {P(t5['prec'])} ({CI(t5['ci'])}) | {t5['lift']:.2f} |")
w("\n- AUC는 짧은 기간·큰 목표(+30%/3일 0.717)가 가장 높습니다 = **순위 매기기 능력(엣지)은 드문 큰 급등에서 가장 뚜렷**합니다. 반면 정밀도(적중률)는 쉬운 목표가 높습니다.")
w("- 확률은 정의마다 따로 학습 후 등방 회귀(isotonic)로 보정합니다. '확률(추정)'은 과거 빈도 기반 추정치입니다.\n")
w("## 6. 권장 정의\n")
w("1. **기본(표시·확률 카드): 셋업 기반(SHFS형)** — '숏 손실권 → 재점화 레벨 → 21일 고점 재시험'의 흐름으로 설명 가능하고, 손절·익절 규칙이 정의에 내장돼 있음. 단, 적중률 55%(재학습)는 RL 근처 종목 선택 효과이며 기대수익은 마이너스.")
w("2. **엣지 확인용 보조 지표:** ATR 3~4배 또는 +30%/5일의 **리프트**(1.8~2.8). '기저율 대비 몇 배 잘 고르나'가 실력의 정직한 척도입니다.")
w("3. 어떤 정의도 비용 후 **양(+)의 기대수익이 통계적으로 검증되지 않았습니다.** 매매 신호로 쓰지 마세요.\n")
w("## 7. 과거 사례 카드 85건 (타임머신 탭)\n")
cnt = collections.Counter((c["group"], c["result"]) for c in cards)
w("| 그룹 | 결과 | 건수 |"); w("|---|---|---|")
for (gr, r), n in sorted(cnt.items()): w(f"| {'성공 사례' if gr=='success' else '실패 사례'} | {r} | {n} |")
w("\n- 각 카드: 시점 기준 숏 트랜치(추정), 손실권 비율(추정), 커버 압력 지수, 재점화 레벨, 21일 고점, 손절선, 한국어 서술, 이벤트 로그(공시·뉴스 링크), 사후 결과.")
w("- 과거 사례는 CTB/대차 이력이 없어 'N/A — 추정하지 않음'으로 표시. '⚠️데이터오류'로 표시된 사례는 역분할 미조정 등으로 가격이 왜곡된 경우이며 목록 끝에 배치됩니다.\n")
w("## 8. 앱 사용법\n")
w("- **관리 → 🎯 성공 정의 · 확률 카드**: 정의를 고르고 저장하면 홈/종목의 확률 카드가 그 정의로 재학습·보정된 모델을 사용합니다(⭐ = 권장). '기존(legacy)'을 고르면 이전 +30%/5일 모델.")
w("- **타임머신 → 🗂️ 과거 사례 카드**: 성공/실패 그룹과 결과로 필터, 사례별 4장 카드 + 사후 결과.")
w("- 재생성: `python scripts/target_grid.py` → `python scripts/case_narratives.py` → `python scripts/make_target_doc.py`.\n")
w("## 9. 한계\n")
for s in ["데이터셋의 과거 신호 일부는 추정 공매도 거래량으로 계산(지도/카드는 실제 FINRA 사용).",
          "숏 트랜치·평균단가·손실권 %는 추정. FINRA 공매도 거래량 ≠ 공매도 잔고.",
          "생존 편향(상장폐지 종목 누락 가능), 섹터 라벨은 현재 기준.",
          "대차 수수료·대차 가능 수량 이력 없음 → 숏 스퀴즈 강도 과소/과대평가 가능.",
          "일봉 기준 — 장중 순서 불명 시 손절 우선 가정(보수적).",
          f"그리드 {b['n_cells']}칸 동시 시험 → 최고값은 다중검정으로 과대평가.",
          "**투자 조언이 아닙니다. 본인 판단과 책임으로 사용하세요.**"]:
    w(f"- {s}")
(R/"docs/TARGET_GRID.md").write_text("\n".join(L), encoding="utf-8")
print("ok", len(L))
