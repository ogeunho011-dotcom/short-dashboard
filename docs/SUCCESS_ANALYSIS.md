# 성공·실패 사례 원인 분석 + 최종 적중률 (2026-10-28 12:23 KST)

> **투자 권유 아님.** 과거 무료 데이터(가격: yfinance, 공시: SEC EDGAR, 뉴스: Google News RSS) 기반 연구이며, 확률·적중률은 모두 **추정치**입니다. 미래를 보장하지 않습니다.

## 0. 한 줄 요약 (초보자용)

- **최종 적중률(표본외, 상위 5% 경보, '5거래일 안에 +30%')**: 현재 채택 모델 **22.5%** (95% CI 20.8%~24.2%, n=2,221, 기본율 8.0%, lift 2.81배, AUC 0.679).
- 사례 분석을 반영한 실험 모델: **24.4%** (95% CI 22.5%~26.3%, n=1,986, lift 3.05배, AUC 0.677). 차이 +1.9%p 이지만 95% CI -0.6~+4.4%p 로 **0을 포함 → 통계적으로 유의하지 않음**. AUC 는 오히려 소폭 하락 → **앱 기본 모델은 바꾸지 않음(미채택)**.
- 즉 경보 4~5개 중 약 1개만 5일 안에 +30%를 찍습니다. 같은 종목 연속 경보를 한 '이벤트'로 묶으면 첫 경보 기준 22.6%, 이벤트 중 한 번이라도 적중 28.6% (755개 이벤트).
- 매매 기대값(청산 규칙은 이전 폴드로만 선택, 비용 0.6% 차감): 이전 -0.83% (CI -2.08%~0.54%) → 실험 -0.14% (CI -1.22%~0.97%). **둘 다 0 이하 또는 0 포함 → 검증된 수익 규칙 없음.**
- 성공 원인 1위는 **원인 불명(뉴스·공시 없음)**, 그다음 계약·M&A, 역분할 직후 저유통, 실적, AI/우주 테마 피벗. 실패 원인 1위는 **유상증자·희석**(원인 불명과 동률), 그다음 'PR 펌프 후 소멸', 역분할 덤프.
- 가장 확실한 '미리 보이는' 실패 신호: **최근 30일 안에 424B(공모 확정) 공시** → 경보 적중률 13.8% (나머지 24.7%의 약 절반).

## 1. 방법

- 대상: 기존 5폴드 워크포워드의 **표본외** 상위 5% 경보 2,224건 → 같은 종목 7일 이내 경보를 묶어 755개 이벤트.
- 성공 표본 45개 = 첫 경보가 5일 내 +30% 적중한 이벤트 중 **상승률 상위 30개 + 무작위 15개**. 실패 표본 40개 = 첫 경보가 실패한 이벤트 중 **10일 최저가 하위 25개(손절 맞은 큰 손실) + 무작위 15개**.
- 각 사례마다 경보일-30일~고점(실패는 +8일)+2일 구간의 SEC 공시(8-K/6-K 항목 코드·EX-99 제목, 424B, S-1/F-1/S-3/F-3, EFFECT, DEF 14A)와 Google News 헤드라인을 수집해 **사람이 읽고 분류**. 근거가 없으면 '원인 불명'. 지어내지 않음.
- 뉴스 매칭이 애매한 일반 단어 티커(IVF, CRE, RCT 등)는 회사명/주가 문맥이 있는 기사만 인정.
- **데이터 오류 발견**: QH 2026-04-15 '+3,686%' 는 DB 가격의 미조정 역분할 점프(4/27 0.12→3.60). 실제 상승이 아니므로 재학습에서 아티팩트 구간 행을 제외함.

## 2. 성공 원인 카테고리 (n=45)

| 카테고리 | 건수 | 비율 |
|---|---|---|
| 원인 불명 | 15 | 33.3% |
| 계약·제휴·M&A | 9 | 20.0% |
| 역분할 직후 저유통 | 5 | 11.1% |
| 실적·흑자전환 | 4 | 8.9% |
| 테마 피벗(AI·우주·크립토) | 4 | 8.9% |
| 기타 회사 발표 | 2 | 4.4% |
| FDA·임상 | 2 | 4.4% |
| 데이터 오류 | 1 | 2.2% |
| 재무구조 개선(희석 해소) | 1 | 2.2% |
| 사업 진척 | 1 | 2.2% |
| 공매도 이슈·스퀴즈 | 1 | 2.2% |

## 3. 실패 원인 카테고리 (n=40)

| 카테고리 | 건수 | 비율 |
|---|---|---|
| 원인 불명 | 11 | 27.5% |
| 유상증자·희석 | 11 | 27.5% |
| 펌프 후 소멸(PR) | 9 | 22.5% |
| 역분할 덤프 | 4 | 10.0% |
| 펌프 후 소멸(무소식) | 2 | 5.0% |
| 상장·존속 위험 | 2 | 5.0% |
| 임상·파트너 실망 | 1 | 2.5% |

### 해석

- 원인이 확인된 성공 29건 중 근거(기사/공시) 날짜가 경보일 **당일 이전**인 것은 13건, **경보 이후**는 16건. → 상당수 재료는 경보 시점에 아직 공개되지 않았음(거래량·가격이 먼저 움직임). 따라서 '재료 자체'를 미리 특징으로 쓰기는 어렵습니다.
- 성공과 실패 양쪽에 'PR(계약·AI·임상) 급등'이 있음: 같은 PR 이라도 **직후 공모(424B)·재판매 등록(EFFECT)·역분할 발표**가 붙으면 실패 쪽으로 감. (예: GRI 임상 PR→4일 뒤 424B5, BCTX 급등 당일 $30M 공모, CIRC 계약 PR→다음날 424B3)
- 역분할은 양면적: 역분할 **직후(유통주식 감소)** 는 급등(TNON, ISPC, WHLR 9월), 역분할 **발표 시점** 은 덤프(HUBC, EZGO, PMAX 4월).
- '원인 불명' 이 성공 33%, 실패 28% → 초소형주 급등의 상당 부분은 공개 재료 없이 수급(저유통·모멘텀 트레이더)으로 발생.

## 4. 미리 볼 수 있는 신호 비교 (경보 시점 종가까지의 정보만, 미래 정보 없음)

### 4-1. 전체 표본외 경보 2,217건 (아티팩트 제외) — 통계적으로 의미 있는 비교

| 경보 시점 특징 | 해당 경보 수 | 적중률 | 나머지 적중률 | 배수 |
|---|---|---|---|---|
| 424B(공모) 30일 이내 | 455 | 13.8% (11.0%~17.3%) | 24.7% | 0.56 |
| 공모 완료(s_offering_done) | 364 | 14.0% (10.8%~18.0%) | 24.1% | 0.58 |
| S-1/S-3/F-1/F-3 등록 30일 이내 | 404 | 17.1% (13.7%~21.1%) | 23.7% | 0.72 |
| RVOL < 1.5 | 1059 | 20.3% (18.0%~22.8%) | 24.4% | 0.83 |
| 5일 수익률 +50% 이상 | 304 | 38.2% (32.9%~43.7%) | 20.0% | 1.91 |
| 직전5일 중 +40% 일봉 있음 | 295 | 33.6% (28.4%~39.1%) | 20.8% | 1.62 |
| 당일 +50% 이상 | 114 | 36.0% (27.7%~45.1%) | 21.7% | 1.66 |
| RVOL ≥ 5 | 624 | 26.8% (23.4%~30.4%) | 20.8% | 1.29 |
| 8-K/6-K 2일 이내(신선한 재료) | 775 | 22.5% (19.7%~25.5%) | 22.5% | 1.00 |
| 위임장(DEF/PRE 14A) 60일 이내(역분할 투표 가능) | 385 | 22.1% (18.2%~26.5%) | 22.5% | 0.98 |
| 반복 경보(4번째 이후) | 863 | 21.1% (18.5%~23.9%) | 23.3% | 0.90 |

### 4-2. 조사 표본(성공 44 vs 실패 40)에서의 보유 비율

| 신호 | 성공 사례 | 실패 사례 |
|---|---|---|
| 저유통 | 73% | 62% |
| 과거급등주 | 82% | 78% |
| SSR | 39% | 50% |
| 갭유지 | 16% | 20% |
| 공모완료 | 7% | 32% |
| 424B≤30일 | 9% | 42% |
| 증권신고서≤30일 | 16% | 18% |
| 5일+50% | 14% | 20% |
| 직전5일 +40%봉 | 5% | 8% |
| 당일+20% | 27% | 28% |
| RVOL≥5 | 66% | 52% |
| RVOL<1.5 | 23% | 25% |
| 8-K/6-K≤2일 | 45% | 30% |
| 위임장≤60일 | 23% | 18% |

- **핵심 구분 신호**: ① 최근 424B/공모 완료(실패 42% vs 성공 9%; 전체 경보에서 적중률 0.56배) ② 강한 거래량(RVOL≥5: 성공 66% vs 실패 52%; 전체 1.29배) ③ 이미 강하게 오른 상태(5일 +50%, 당일 +50%)는 적중률을 **높이지만** 10일 최저가 중앙값도 -25~-33% 로 깊음 → '변동성이 크다'는 뜻이지 안전하다는 뜻이 아님.
- 표본에서 성공 쪽이 많았던 '8-K 2일 이내'는 전체 경보에서는 차이가 없음(1.00배) → 일반화되지 않는 표본 착시.

## 5. 특징·감점 반영 후 같은 5폴드 워크포워드 재실행

- 가점 후보 4개(5일+50%, 직전5일 +40%봉, 당일+20%, RVOL≥5)는 기존과 같은 게이트(학습 구간 n≥25·lift≥1)를 통과할 때만 가중치. 감점 후보 3개(424B≤30일, 증권신고서≤30일, RVOL<1.5)는 **각 폴드의 학습 구간 상위 10% 후보 안에서만** 비율을 추정하고 Wilson 상한이 나머지보다 낮을 때만 0.3~1 배수 적용. 임계값·청산 규칙도 학습 폴드에서만 선택.
- 아티팩트 제외 행: 12개 (데이터셋 기준).

| 지표 (표본외, 상위 5%) | 이전 (게이트 가중) | 감점만 추가 | 신호+감점 (실험) |
|---|---|---|---|
| 적중률 (95% CI) | 22.5% (20.8%~24.2%) | 22.5% (20.7%~24.3%) | 24.4% (22.5%~26.3%) |
| 경보 수 n | 2,221 | 2,057 | 1,986 |
| 기본율 | 8.0% | 8.0% | 8.0% |
| lift | 2.81 | 2.81 | 3.05 |
| AUC | 0.679 | 0.670 | 0.677 |
| 상위 10% 적중률 | 19.6% | 18.4% | 19.9% |
| 이전 대비 상위5% 차이 95% CI | — | -2.6~+2.5%p | -0.6~+4.4%p |
| 폴드별 상위5% 적중률 | 19% / 24% / 21% / 26% / 22% | — | 18% / 27% / 24% / 28% / 23% |
| 중첩 청산 기대값/거래 (CI, 거래수) | -0.83% (-2.08%~0.54%, 1172) | — | -0.14% (-1.22%~0.97%, 1515) |
| 중첩 청산 승률 / MDD(10% 배분) | 29.3% / -81.0% | — | 32.9% / -59.0% |

### 정직한 결론

- 실패 특성 **감점만** 넣으면 상위 5% 적중률은 그대로(22.5%), AUC 는 하락. 424B 효과는 폴드 3 이후에야 학습 구간에서 유의해져 초기 폴드에는 적용되지 않았음.
- 신호+감점 실험 모델은 상위 5% 적중률 +1.9%p, 5폴드 중 4개에서 개선됐지만 **CI 가 0을 포함 → 우연일 수 있음**. AUC 소폭 하락, 기대값도 여전히 0 근처 음수.
- 그래서 **앱의 점수 모델은 바꾸지 않았고**, 이 결과는 '참고용 연구'로만 앱(타임머신 탭)에 표시. 대신 '최근 30일 424B 공모'는 경보를 볼 때 직접 확인할 주의 사항으로 안내.
- 생존 편향: 표본은 현재 상장 종목에서 추출 → 상장폐지된 실패 사례 누락, 실제는 더 나쁠 수 있음. 분류는 1인 수작업이며 뉴스 검색 누락 가능.

## 6. 성공 사례표 (n=45)

| # | 티커 | 첫 경보일 | 선정 | 5일 최고 | 10일 최저 | 카테고리 | 원인 | 근거 | 경보 시점 신호 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | HCWB | 2026-05-14 | 상위 | 1084% | 181% | 실적·흑자전환 | 1분기 실적(순이익 흑자) + HCW11-040 전임상 결과 발표 후 시간외 +122% | [HCW Biologics (HCWB) Stock Is Trending Overnight — Here's Why It Moved Over 122% In After-Hours Session - Benz](https://news.google.com/rss/articles/CBMi6gFBVV95cUxObXUxejdSeHZId0RmVHpTcTJBUnAyT2RMUVB4S3RlYkg2b01KTlJOa3pqa25JT3MtV1JldWJPX0VGZ1ZuNkNwMWNEUEd6NWQ3RmJfTlR5cUhEaWNyMVV0MV9jdDB6SDBMV3VPZmpiVEViQkdOVXBuQmJ3OHBvVTR3S2ctMzNoVlUtWmtSVlBKajRoXzRzZXBhdTBtWldiTjZiaGI5N1F3OV9Zc0RnOG1wclBycTgxZUVQX3J5bV8tYjJuanNoVVBaSjNvYWxmUU1VV2NnUkNmc1N5Zmk3LWRkcWxsaFJiTWxJNnc?oc=5) | 저유통, 과거급등주, 증권신고서≤30일, RVOL≥5, 8-K/6-K≤2일, 위임장≤60일 |
| 2 | AZIO | 2026-01-06 | 상위 | 754% | -21% | 계약·제휴·M&A | EVTV 와 합병 추진 + 동남아 정부 GPU 주문($107M) 보도 | [AZIO AI Lands $107 Million Southeast Asia Government GPU Order - Pulse 2.0](https://news.google.com/rss/articles/CBMiiAFBVV95cUxQbWNTZk84LXBaVi0zYlRwUzdwMVhoeVlveWEzV1VDS1o0Z00yN1MxRzdmMTRNbE9LSkhaTGVnYnFVOUlyX2pLMW0wUDFpYzY5bW12VE9OeS05ZVNieElDYW5aSXAyWFBPVkt6WWcwOGd2UmtTMXY0UkVBXzVSSXhJRVBLVlJjSll60gGOAUFVX3lxTE40MUJPVy1kTEtyZlRiOEVnSlhtS0k5UGhieVNqaUVyTHNkLTBWZHVFMUpGRjNVeGg2WDdLYVEwWmQ3aWZkX1kzbm5NZkczaU5NLTVtV2tKWVhZV3hDTTFRWXpNeHNHbnNOYlo1M1hYX01LWEY4U2VZVF9DZHRGT3pCWFUwMnhhZHMtdHhMZmc?oc=5) | 저유통, 갭유지, 당일+20%, RVOL≥5, 위임장≤60일 |
| 3 | IVF | 2026-01-16 | 상위 | 464% | 49% | 기타 회사 발표 | 확장 전략 발표 보도(Benzinga 'trending'); 뚜렷한 계약·실적 없음 | [Why INVO Fertility (IVF) Stock Is Trending Overnight - Benzinga](https://news.google.com/rss/articles/CBMiqwFBVV95cUxPa3JCUTd5R1laU1BTQzl2b2c5U0xCNXpwemQ4cHMtU1ZrdGNsTjFZUVF3TUY4czE0Vnc0eE1qRDZSQ1dQM3ZvOGg4ajFXMWthUDhJcGlsdjdjRnNrNGVKN29VU0Z0ZnB5SEZBX2hHS1p3b2Mybl9YU21oVGYxVG1MNDA0aklNTGlFUWluc0NhX2ZWZWw3SC1MWHpMRGlBcjQyRWJyVXZ1RHdqaTA?oc=5) | 저유통, 과거급등주, 공모완료, 424B≤30일, 증권신고서≤30일, RVOL≥5, 위임장≤60일 |
| 4 | ASTC | 2026-05-27 | 상위 | 399% | 21% | 테마 피벗(AI·우주·크립토) | 이사회 승인 '달 자원·인프라' 신사업 발표 + NASA 달 탐사 테마(MNTS·RKTO 동반 급등) | [Astrotech jumps 154% after unveiling board-approved lunar resource and infrastructure initiative / ASTC Stock ](https://news.google.com/rss/articles/CBMiywFBVV95cUxOVF9CZDJXbzE5RlhyTlF1LWxnaUZfc0szZXZCbEs4Tkd3ZUJ1RDh2R0ZhNFdJQTVFRmUyTWJzcGN6TTR6WHpKSW92dnVjV2hCanBMeUtVa0tLRTlpSVFrYlpjXy1BTkJscTJRT09ZbzVKd2VSRGdUUG44NERCaTJYNlhxMlY2VWNxNE9UUk5UMUlSLUlRN2lkVkNqWGVNcU94aUVET25Xak9seHRpTjQtUFdXcC1JNERMemtRQUVvRFd4d3gzX3Y1eU1XTQ?oc=5) | 저유통, 과거급등주, 갭유지, 5일+50%, 당일+20%, RVOL≥5 |
| 5 | TNON | 2026-09-09 | 상위 | 344% | 55% | 재무구조 개선(희석 해소) | 전환사채 조기상환 발표 → '희석 부담 해소' 해석으로 +75% | [Tenon Medical Announces Early Repayment of Its Convertible Notes - Yahoo Finance](https://news.google.com/rss/articles/CBMiogFBVV95cUxPazNBakNOMVRIY3RjVklZTDV5ZUhVU0lGVkhNaVMtbFcyc2pSRlRzZWlGR1VwVDQ4WTVEZEM4ZHlWRUJTLWd5eVJEM1AxTHd6WGJ6d3ZSdWEtSWo3SmpYWnZvWjdUUzFHSHdnaDNKc0FoNlFXYWd1SVlCajJiRHhsOUI5UUZtbXdsOVFaaEtTajd5VGQ1R1ZlclZSdndxM0lnTlE?oc=5) | 저유통, 과거급등주, SSR, 424B≤30일, 증권신고서≤30일, 8-K/6-K≤2일 |
| 6 | FGI | 2026-08-12 | 상위 | 321% | 49% | 실적·흑자전환 | 2분기 실적 서프라이즈(마진 개선, EPS 예상 상회) | [FGI Industries Ltd. (FGI) Beats Q2 Earnings Estimates - Yahoo Finance](https://news.google.com/rss/articles/CBMimAFBVV95cUxPQmI3RnRZcU5CWkV3YXR2eHExRHIyVGtBclBSRmx5bzZqQjNDRGpoaVlFamNiZFl5ZzFQSmNsNEQ2MFBmeG93RDFSVWotUzVxUWtsSzBGWGkyYUZ3bVdOOTJWcUp1dlFkemoxYXllNng3UmVMbW11WmxuRE5CeVFNRk4xRVloMWtiZTJkLWw4V2o1Mkd1UDVndw?oc=5) | 저유통, 과거급등주, RVOL≥5, 8-K/6-K≤2일 |
| 7 | TCRT | 2026-10-12 | 상위 | 319% | 44% | 계약·제휴·M&A | Velaris 인수 + $350M 사모 조달 발표(직전 상장폐지 통지) | [TCRT Stock Explodes After Velaris Deal And $350M Raise - StocksToTrade](https://news.google.com/rss/articles/CBMigwFBVV95cUxOSmxZdHpEYnFHWWxFdDVrVmdqN2tBY2tqVE9PWms1eHBlWENfQ0FneFc3aUp2NERya205LU5ISUQ4QVNMVDV0aEd4eXdNQjYxaEJSTnBqVEN6cF9XMXE0SHhuaFIyTG9Ka255UTA0cTZrWDJzekoxUm5JMjJwZTE4bFNRUQ?oc=5) | 저유통, 공모완료, 424B≤30일, 당일+20%, RVOL<1.5 |
| 8 | GITS | 2026-01-21 | 상위 | 317% | -10% | 계약·제휴·M&A | ATEEZ 주제가 글로벌 배급권 계약(8-K 1.01), 별도 뉴스 없음 | [SEC 8-K 2026-01-26 — Interactive Technologies, Inc. Announces Agreement with ATEEZ for Animated Featu](https://www.sec.gov/Archives/edgar/data/1911545/000149315226003585/ex99-1.htm) | 저유통, 과거급등주, 5일+50%, 당일+20%, RVOL≥5 |
| 9 | AXNX | 2025-12-30 | 상위 | 313% | -7% | 원인 불명 | 6-K 1건(내용 미상), 관련 뉴스 없음 | [SEC 6-K 2025-12-29](https://www.sec.gov/Archives/edgar/data/1998560/000121390025125791/ea0271100-6k_mint.htm) | 과거급등주, SSR, RVOL<1.5, 8-K/6-K≤2일 |
| 10 | MYSE | 2026-04-15 | 상위 | 301% | 106% | 테마 피벗(AI·우주·크립토) | 'Myseum.AI' 로 사명 변경(AI 리브랜딩) + 저유통 모멘텀 | [Myseum Rebrands as Myseum.AI to Align with Full Suite of Technology and Social Media Platforms - Yahoo Finance](https://news.google.com/rss/articles/CBMiogFBVV95cUxOeE1JOGJrbTFLRXJ5VmJtY2FDVkExNkoyR1lyWW85MUdhdDNZVEFtLW9FX1ptYmxuRldueHh5UW9jamVISTREZzVPRDd0TjQ5STkyUHN1ajlPR2o3VXpwdjdVSDVUZGl5aXBPRjZkNGJSVHVZQjVBemhzNnV2MG42OFNUc1pCdFA3cG5jTXZMTmx1bkZYSlRoaU82MXBEcXBxQXc?oc=5) | 저유통, RVOL≥5, 8-K/6-K≤2일 |
| 11 | CLRO | 2026-08-05 | 상위 | 283% | 47% | 계약·제휴·M&A | Cortigent 합병 주주승인(8-K 5.07) + 적은 주식수 부각 | [ClearOne Cancels 437,500 First Finance Warrants at $5.00 Amid Cortigent Merger Process - TradingView](https://news.google.com/rss/articles/CBMi4AFBVV95cUxPQUdDVVlUZ3B4Z3RwSDMxc0JmaHFLTkNDV0FmbndiU0pKRmNHNTlIdWhIWlExaUJDRkRLRFZpMEhDLTRRNkFFTFFNVXItTGJjWi10UkgxbXlHS1paR1dKTFdhVFFkUHItQjU4YzhRZjY1T3lkOGo3ZzNpUXhTeHYtR3gzN1JJR3ZqeUtJRmFjSjZEcjFGTHFHd0p4ZFNBYkJCUloyejhSVzhwZnRNeGxTVG5kRnhZT2ZCX2FYZVdmQzFkVGtkN1hib0pYLVZXemkyMDF2Q3lKRmVKQWs5ZE1wdg?oc=5) | 저유통, 과거급등주, RVOL≥5, 8-K/6-K≤2일 |
| 12 | PIII | 2026-05-14 | 상위 | 269% | 25% | 실적·흑자전환 | 1분기 실적 예상 상회(턴어라운드) + 부채 출자전환 | [PIII Stock Soars As Earnings Beat Signals Turnaround - StocksToTrade](https://news.google.com/rss/articles/CBMigAFBVV95cUxQbkwwMmh0SEV3N3p0WW1TY285bVFiSnplbHF4UUs2TFpfZzZsdTVYQ3RjQl93VFZUZG5wVjl4VTM4MXhHUVNIb0ltSFJrWXhRZ2ZZVDk2MWFiMExaSjU1emNPLUFSTGZZaWl6X0JaSDFnVnFGMFlZT1pOSFJHZTQ3cA?oc=5) | 저유통, RVOL≥5, 8-K/6-K≤2일, 위임장≤60일 |
| 13 | INHD | 2026-04-07 | 상위 | 249% | -55% | 테마 피벗(AI·우주·크립토) | AI 전략계획 공식 발표 당일 +180% | [SEC 8-K 2026-04-08 — Holdings Inc. Officially Launches Artificial Intelligence Strategic Plan](https://www.sec.gov/Archives/edgar/data/1961847/000149315226015714/ex99-1.htm) | 저유통, 과거급등주, SSR, RVOL≥5, 위임장≤60일 |
| 14 | BYAH | 2026-06-11 | 상위 | 247% | 14% | 테마 피벗(AI·우주·크립토) | AI 영양사 제휴 발표(같은 날 $2M 공모 발표도 있음) | [Park Ha Biological Launches AI Nutritionist Through Strategic Partnership to Expand AI-Powered Skincare Ecosys](https://news.google.com/rss/articles/CBMirgFBVV95cUxQSjNFejhvTmFrNDFlRGNzaUtncnVhQk9wY2dYLXN3YS04OW9OOUZLdWZwMVFwUE16WVhHb3Q3cVVJWEhCenVmekVRaVhocThoeFZFN3BrTUY4Q0dxSlNPZm1ORVU1Y1dqV0YzQXZ3N1ZvY1FIRmdRVnpDM0hQRWdSN3NoY09nVVdtWThJWVlUZmFrOWtGVkJsQ2gzcVQtWjllVlN4aC14YVhjandpWFE?oc=5) | 과거급등주, SSR, 증권신고서≤30일, 직전5일 +40%봉, RVOL≥5 |
| 15 | SKYQ | 2026-03-31 | 상위 | 224% | -8% | 원인 불명 | 8-K(3.01 상장유지 통지)·10-K 외 뉴스 없음 | [SEC 8-K 2026-03-30](https://www.sec.gov/Archives/edgar/data/1812447/000109690626000405/R1.htm) | 저유통, 과거급등주, SSR, RVOL<1.5, 8-K/6-K≤2일 |
| 16 | XHLD | 2025-10-27 | 상위 | 221% | 4% | 원인 불명 | 8-K(1.01 계약) 1건, 내용·뉴스 미확인 | [SEC 8-K 2025-10-27](https://www.sec.gov/Archives/edgar/data/2030954/000149315225019786/form8-k.htm) | 과거급등주, RVOL≥5, 8-K/6-K≤2일 |
| 17 | BRLS | 2026-02-06 | 상위 | 220% | 4% | 원인 불명 | 8-K(2.04 채무 가속 사유) — 오히려 악재 공시, 상승 원인 뉴스 없음 | [SEC 8-K 2026-02-06](https://www.sec.gov/Archives/edgar/data/1852973/000121390026013285/ea0275816-8k_borealis.htm) | 과거급등주, SSR, RVOL<1.5, 8-K/6-K≤2일 |
| 18 | GCTK | 2026-07-29 | 상위 | 216% | 18% | FDA·임상 | LT-100 FDA Type C 미팅 결과 발표 후 시간외 +70% | [GlucoTrack (GCTK) Stock Surges Over 70% After Hours: Why is it Moving? - Benzinga](https://news.google.com/rss/articles/CBMivwFBVV95cUxQTk5kaVFkYmF5M1QxbUNzZkxLNnhiOWRvMUIxRDR3SnRlNzF3VDkwQUJGSXhYUW9icms4bEFLM1dyMUhLUlhrLXh2Y0ZhQXl4aXFEcmc3MmcyTE8wSndrbmhvYTM5X3F2R2FwQWN4S1lyQjFfQVUtY1V6dnZhUF82MWQ4VGt6b2ZkUWo2TFVWeGVjNnh4MGRIU3NtcHNqc2s4aGtYaDhLR0o5bFBYc0N3VThjVURZWnR3MzlHc0Y2MA?oc=5) | 저유통, 과거급등주, 8-K/6-K≤2일, 위임장≤60일 |
| 19 | SHPH | 2026-01-12 | 상위 | 210% | -7% | 원인 불명 | 8-K(5.02 임원 변경)만, 의미있는 뉴스 없음 | [SEC 8-K 2026-01-12](https://www.sec.gov/Archives/edgar/data/1757499/000149315226001861/form8-k.htm) | 저유통, 과거급등주, RVOL<1.5, 8-K/6-K≤2일 |
| 20 | BEAT | 2025-12-10 | 상위 | 158% | -7% | FDA·임상 | FDA 허가(clearance) 보도 후 랠리 | [HeartBeam (BEAT) Stock News Today: FDA Clearance Ignites Rally, Analysts Lift Targets, and What Investors Are ](https://news.google.com/rss/articles/CBMi5gFBVV95cUxQbUFrSG40a3lodXlQTzNkSVJyTVhOSWNWQnVBUzQ1dHJTWGpSeWxuOWxubmVjUDdlSVJfNUl6SHdoaW1xaG4yRFZCb0daZE56OG96RGltc2VkcHI0MnBBTVoydXZMVThPWDFLOFBoUHVoVEROUXB3MWN5Z0d3Y29MR18tcFJxa0N6am14cmFkb0o0UlZjbzJpZWQtYW9nOERVcXhnUENlQzR1eENSNVNTcmtsZjFDRWlZYWRaZnpKZ3JPWXU4Y1lrRnRUbF9HVG1VRG8xWmlFLTBNWGVLRlJ3Y1VUcEJUQQ?oc=5) | 갭유지, 5일+50%, 당일+20%, RVOL≥5 |
| 21 | ZTG | 2026-07-29 | 상위 | 156% | 5% | 원인 불명 | 관련 뉴스·공시 없음 | [SEC 6-K 2026-08-07](https://www.sec.gov/Archives/edgar/data/2011458/000149315226036484/form6-k.htm) | 저유통, 과거급등주, SSR, RVOL≥5 |
| 22 | CLRO | 2026-07-02 | 상위 | 155% | -11% | 계약·제휴·M&A | Cortigent 합병계약 체결 발표 → 당일 +170% | [ClearOne Announces Entry into Merger Agreement with Cortigent, Inc., a Wholly-Owned Subsidiary of Vivani Medic](https://news.google.com/rss/articles/CBMi-wFBVV95cUxNVlU5OVVLaEUxS1BUaThTU1Bib00zaU9oNF9FeXZXc3FvYnRJTldzTlkxODQyRDZRMG9YQ3lEWkhYZmlLUXJiRkxtNmdnN1pSU2VXVWdPcVJXaV9CMk9OUDFPSzYxNUt6OGlpYzd0MzdVRDJ5UklXQWd2RlNjWWFQUGlpanZ6aVEyVzJPYzJITkJOMnBBOWRqWVdqU0dVU1pPOEV4TWtpVVpxUHFFZXhvNTJzbF8tVUZGLUI2a2lldVpRaWVkM2loMG9lTzVmVG1OODJXSmpOa0dpQ0FkUXZGWHRZZERhNUpZR0luNFFOSWtuNHhhZXFQOVlYUQ?oc=5) | 저유통, SSR, 갭유지, 증권신고서≤30일, 5일+50%, 당일+20%, RVOL≥5, 8-K/6-K≤2일 |
| 23 | WHLR | 2026-09-16 | 상위 | 153% | -52% | 역분할 직후 저유통 | 역분할(8-K 3.03/5.03) 직후 유통주식 급감 → 변동성 급등 보도 | [WHLR jumps as reverse split appears to drive outsized move / WHLR Stock News - Quiver Quantitative](https://news.google.com/rss/articles/CBMilgFBVV95cUxPYk85bmpzYUxzOV9sQThvLS16aVVza1NwU05rLVhlVXphcVpQTjRnVkFtRzQxSGgyRDByRjRYQ2ZCUDZ0MkpETk02T3NiVU5xUTUwRWFsZUQ4cmRfejBfRVh1NVNmRDZ6SG50NnhES2t1elNBelZqamVQbnZaZ1dKTGlCR01vWDBNWGZMb3VSblBlalg3dGc?oc=5) | 저유통, 과거급등주, SSR, 공모완료, 424B≤30일, RVOL≥5 |
| 24 | PCSA | 2025-12-15 | 상위 | 150% | -23% | 역분할 직후 저유통 | 8-K 3.03/5.03(정관 변경·주주권 변경, 통상 역분할) — 뉴스 미확인, 추정 | [SEC 8-K 2025-12-15](https://www.sec.gov/Archives/edgar/data/1533743/000149315225027680/form8-k.htm) | 과거급등주, RVOL≥5, 8-K/6-K≤2일 |
| 25 | QH | 2026-04-15 | 상위 | 118% | -67% | 데이터 오류 | 가격 DB 의 미조정 역분할 점프(4/27 시가 0.12→3.60, 거래량 급감). 실제 +3,686% 상승 아님 — 재학습에서 제외 | [SEC F-3 2026-04-14](https://www.sec.gov/Archives/edgar/data/1781193/000121390026043534/) | 저유통, 과거급등주, SSR, 증권신고서≤30일, 5일+50%, 직전5일 +40%봉, 당일+20%, RVOL<1.5, 8-K/6-K≤2일 |
| 26 | SKYQ | 2026-06-22 | 상위 | 118% | -21% | 사업 진척 | 네바다 정유소 생산 단계 진입 발표 | [Sky Quarry enters production phase at Nevada refinery - Hydrocarbon Engineering](https://news.google.com/rss/articles/CBMisAFBVV95cUxOWlloU21IMWpIU2t6RkktYjhtM2tvVGVmWTRUOWZKc0tzVWUtS3BBZlNSRXF6UlBhYXVwemN5V1hINEtRcnI2WE5wbzZhNXZqU0JxZDN5S0dnZ0UzeVg0Mjg4R1J2ZHlMRUtWc3VveVhGaEFKdTZGTEZ6cVZ1VGNTeDAxdHE1T1ZzeEJhd0NBSmoyMkp0MHBoclo0NkVQN3llZ3lNZHh3em5OZFRWWk80dA?oc=5) | 저유통, 과거급등주, 갭유지, 당일+20%, RVOL≥5, 8-K/6-K≤2일 |
| 27 | VIVS | 2026-01-29 | 무작위 | 100% | 32% | 계약·제휴·M&A | 아시아 유통계약 보도 | [VivoSim Labs Shares Surge 82% Amid Key Asia Distribution Deals - StocksToTrade](https://news.google.com/rss/articles/CBMidkFVX3lxTE9oUXV2cXlYZk54TVI4WkFBaE5Gc2poVUlwVEdvbWtTTTFUazVQU0M5VHlGaXlVQ1lEdE5iY1ZrRWdfVVFjMEVZbWgwVVhYX0VId2I5aV9OY0k3NmVkOWhJSGljRGtNaE1GVEtJSWJuODlNZGtTUGc?oc=5) | 저유통, 과거급등주, RVOL≥5 |
| 28 | CRE | 2026-06-10 | 무작위 | 98% | -19% | 원인 불명 | 관련 뉴스·공시 없음 | [검색 결과 없음 (Google News 검색 링크)](https://news.google.com/search?q=%22CRE%22%20after%3A2026-06-06%20before%3A2026-06-20) | 저유통, 과거급등주, SSR, 당일+20%, RVOL<1.5 |
| 29 | BNAI | 2026-01-14 | 상위 | 96% | -18% | 계약·제휴·M&A | AI 라이선싱 계약($2.05M, 아프리카) 발표 | [Brand Engagement Network Secures $2.050 Million AI Licensing Partnership in Africa - PR Newswire](https://news.google.com/rss/articles/CBMi0wFBVV95cUxPTnZFMDNKbjlrSHoyRHhMMnRKc0I1UlFDWnBZbXVuNW1ZeHplb1VIMG9GUXd6LWhzbHp1QWpUOXZYZ0piRlctTzExWXZPQTUwdjFXQng2RjZHb01OZ1lPb0JhVjVtSzVMVkxBUGdwc2hkbzRGOEhKb3V1clJKZnZhQU9SeWlIelY2aFlWdmcybXJZdF9fVGY1ZFE5WHFLbThPUXVnX1BNODR6cDdpOVFOZWwyYmtnY0lEYzdIdWdBaWg3TXhhZUZrMjdTVFNBdlZtdzZJ?oc=5) | 과거급등주, 갭유지, 5일+50%, 당일+20% |
| 30 | DCOY | 2025-11-11 | 무작위 | 77% | -15% | 계약·제휴·M&A | Salarius 와 합병 완료(동시에 424B4 공모) | [SEC 8-K 2025-11-13 — Salarius Pharmaceuticals and Decoy Therapeutics Complete Merger](https://www.sec.gov/Archives/edgar/data/1615219/000161521925000162/a111325decoyandsalariuscom.htm) | 저유통, 과거급등주, SSR, 증권신고서≤30일, RVOL≥5, 위임장≤60일 |
| 31 | QH | 2026-06-12 | 무작위 | 75% | -12% | 원인 불명 | 임시주총 위임장(6-K) 외 없음 | [SEC 6-K 2026-06-11 — FORM OF PROXY CARD FOR EXTRAORDINARY GENERAL MEETING OF SHAREHOLDERS](https://www.sec.gov/Archives/edgar/data/1781193/000121390026067833/ea029393101ex99-1.htm) | 저유통, 과거급등주, 5일+50%, 직전5일 +40%봉, RVOL<1.5, 8-K/6-K≤2일 |
| 32 | LNAI | 2025-10-30 | 무작위 | 63% | -14% | 원인 불명 | 8-K(3.01 상장 기준 미달) 외 뉴스 없음 | [SEC 8-K 2025-10-30](https://www.sec.gov/Archives/edgar/data/1527728/000173112225001446/e6985_8-k.htm) | 과거급등주, SSR, RVOL<1.5, 8-K/6-K≤2일, 위임장≤60일 |
| 33 | TNON | 2026-08-07 | 상위 | 56% | 1% | 역분할 직후 저유통 | 1:35 역분할 발표·시행 직후 급등 | [Tenon Medical, Inc. Announces 1:35 Reverse Stock Split - ACCESS Newswire](https://news.google.com/rss/articles/CBMizwFBVV95cUxQaXI2Y2lPb2ZvMnpQOVF6c1ZweDRpOU9jbDdqZXJES2JiZzFjeFI4b1hwck1iUjUySlFhemxGcTlHamk3aUhaNTB4bjZiRldvRXd2MlIwd2xaM2RZRDFnVXRwajdXVWpZSVdrTVdmMnNNNnBnNWZSNWxmWWpxV0dfYmlwWFlLYjUyUjRkZWh4ZU5EVG9JLUk4cl9nRjdGWEM1WXlYcTBia045ekdnd2gtaVlhanBHczBqQzlWdzdBelkzeDhaRFNyRVhMMW5PZkU?oc=5) | 저유통, 과거급등주, SSR, 위임장≤60일 |
| 34 | DRMA | 2026-08-11 | 무작위 | 50% | 9% | 실적·흑자전환 | 2분기 실적·스킨케어 출시 계획 발표 후 시간외 +35% | [Trending Stocks Today / Dermata Therapeutics Soars 35.18% Post-Market - Moomoo](https://news.google.com/rss/articles/CBMirAFBVV95cUxNSDVrYU5nQmlDN2VpclRPVFcxeS16aDZJQUM0R1AzeEMxbmxoeFh0dFZDb2E2NHo5V09tMVgyZFZnTlJXWTBrYkg3REpDZU4zTUpfbl9fQVRYREJKU1hSZ21PS3hYWXhYR1JoRjZvR2kwNVQ0V1ZxeVIzV2RNQmZ4LVR3N21aVmRKTDctam10VzRobmFVWjZPTXdsdHNHNnI5SURJcGlkN01ZNG8t?oc=5) | 저유통, 과거급등주, RVOL≥5, 8-K/6-K≤2일 |
| 35 | ISPC | 2026-04-28 | 무작위 | 48% | -12% | 역분할 직후 저유통 | 1-for-40 역분할 후 '마이크로 플로트' 급등 | [iSpecimen Announces 1-for-40 Reverse Stock Split - Yahoo Finance](https://news.google.com/rss/articles/CBMingFBVV95cUxOd09Ra19WQW9IWDk3QWs1S3o5Q3F3Tnoxd3dNQlBFOVV3X24yeFdCOEljNXNXSmgwT1daNFJnQnpseUxtb25wbjlXM0Z1dExDTVJhbzZObEhWMWs0dHZzNGNIYnpJMFdGbG9hZFNNdU9qVjBzUVVaaVhpbncySk5mUDc1NzljRWd4aU0tX2JPVUxYRUJESnhpcEc3NVBmQQ?oc=5) | 과거급등주, SSR, RVOL<1.5 |
| 36 | GAUZ | 2026-03-19 | 무작위 | 41% | -15% | 기타 회사 발표 | 이사 선임·나스닥 규정 준수 회복 발표 | [SEC 6-K 2026-03-19 — Gauzy Strengthens Board and Regains Compliance with Nasdaq Listing](https://www.sec.gov/Archives/edgar/data/1781446/000121390026031832/ea028259901ex99-1.htm) | 저유통, 과거급등주, RVOL≥5, 8-K/6-K≤2일 |
| 37 | NXAT | 2026-07-31 | 무작위 | 41% | -20% | 원인 불명 | 기간 중 424B5 공모만 확인, 상승 원인 뉴스 없음 | [SEC 424B5 2026-08-03](https://www.sec.gov/Archives/edgar/data/2000756/000182912626008268/) | 과거급등주, SSR, RVOL≥5 |
| 38 | ZTG | 2026-09-04 | 상위 | 41% | -21% | 계약·제휴·M&A | ZentoAI 인수 계약(AI·빅데이터) 발표 | [Zenta Group Company Limited Announces Agreement to Acquire ZentoAI Intelligent Technology Company Limited - Ya](https://news.google.com/rss/articles/CBMiowFBVV95cUxON1RWS3h3X2JFQV9QMF9CQVFVdmtVeDhpVVB5UWVXUzAzOUR2eV9OYWQ1UzNlVHJidUR5cEczZFM3a040cmxQREhVMXp2Wk1IeVZDbVhFcF9CMjZOYzM0bTRnRE9EMk9IdE95SVVTcXVZV3Z2TzFRWGM1UDUzampYV2RUZVFjLWNfalVoUHBVTnhpQUVzS3lGUjlIVFZvZ0tIZUdn?oc=5) | 저유통, 과거급등주, SSR, RVOL≥5 |
| 39 | SPHL | 2025-11-05 | 무작위 | 38% | -30% | 원인 불명 | 뉴스·공시 없음 | [검색 결과 없음 (Google News 검색 링크)](https://news.google.com/search?q=%22SPHL%22%20after%3A2025-11-01%20before%3A2025-11-15) | 저유통, 과거급등주, 당일+20%, RVOL≥5 |
| 40 | LFS | 2026-01-14 | 무작위 | 36% | -11% | 원인 불명 | 뉴스·공시 없음 | [검색 결과 없음 (Google News 검색 링크)](https://news.google.com/search?q=%22LFS%22%20after%3A2026-01-10%20before%3A2026-01-24) | 저유통, 과거급등주, 당일+20%, RVOL≥5 |
| 41 | IVF | 2025-12-30 | 무작위 | 36% | -8% | 원인 불명 | 공모(424B4) 직후 반등, 원인 뉴스 없음 | [SEC 424B4 2025-12-31](https://www.sec.gov/Archives/edgar/data/1417926/000149315225029789/) | 저유통, 과거급등주, SSR, 증권신고서≤30일, RVOL<1.5, 위임장≤60일 |
| 42 | LNAI | 2026-08-03 | 무작위 | 34% | -11% | 공매도 이슈·스퀴즈 | '불법 무차입 공매도' 소송(10명 피고) 발표 | [Lunai Bioworks (Nasdaq: LNAI) Names 10 Defendants in Naked Short Selling Fraud Suit - Yahoo Finance](https://news.google.com/rss/articles/CBMingFBVV95cUxNWnBOWHdzV2kyRk9TTUV1Slp1SXVMalhyOGJ1OXdRZjVnQmkwLUZtMGJUQVdFeTVaYXZOeEVvREVhT1hxcUFOcVVzYjdhYlBMZWNtVVVKZkZHM1VWczdkaUczd0xtSk5LM3ZFelh3cHdhcDZyV0wyRjFkYUdxYU1FTE1QNXpNZzNqS2VpY1V0RzdkOEVTOGFRMmxmS0JSQQ?oc=5) | 과거급등주, 당일+20%, RVOL≥5 |
| 43 | QTTB | 2025-10-08 | 무작위 | 33% | -8% | 원인 불명 | 뉴스·공시 없음 | [검색 결과 없음 (Google News 검색 링크)](https://news.google.com/search?q=%22QTTB%22%20after%3A2025-10-04%20before%3A2025-10-18) | 저유통, 갭유지, RVOL≥5 |
| 44 | NXTS | 2026-05-26 | 상위 | 31% | -7% | 원인 불명 | 8-K(1.01/2.03 차입계약)만 확인, 관련 뉴스 없음 | [SEC 8-K 2026-05-27](https://www.sec.gov/Archives/edgar/data/1789192/000149315226025397/form8-k.htm) | 저유통 |
| 45 | BGDE | 2025-11-19 | 무작위 | 30% | -27% | 역분할 직후 저유통 | 1-for-20 역분할 발표(Mawson, 8-K) | [SEC 8-K 2025-11-19 — MAWSON INFRASTRUCTURE GROUP INC. ANNOUNCES 1-FOR-20](https://www.sec.gov/Archives/edgar/data/1218683/000121390025112368/ea026625901ex99-1_mawson.htm) | 과거급등주, RVOL≥5, 8-K/6-K≤2일 |

## 7. 실패 사례표 (n=40)

| # | 티커 | 첫 경보일 | 선정 | 5일 최고 | 10일 최저 | 카테고리 | 원인 | 근거 | 경보 시점 신호 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | HUBC | 2026-09-21 | 상위 | -19% | -75% | 역분할 덤프 | 역분할 발표(9/17) 후 -75%, 나스닥 통지 | [SEC 6-K 2026-09-17 — HUB Announces Reverse Share Split](https://www.sec.gov/Archives/edgar/data/1905660/000121390026100960/ea030581201ex99-1.htm) | 과거급등주, SSR, 당일+20%, RVOL≥5 |
| 2 | PRLD | 2025-11-03 | 상위 | -45% | -71% | 임상·파트너 실망 | Incyte 옵션계약 발표와 함께 CMO 사임·SMARCA2 프로그램 중단 → -71% | [Prelude loses CMO, pauses SMARCA2 degraders and bags $60M from Incyte - Fierce Biotech](https://news.google.com/rss/articles/CBMiogFBVV95cUxQS0pfMVZIOEh5Zm8zUkVHRFk1dkx6UUtESW5mV2tjbGg4cTA5QlEyTXdISXlZTFAwejVBTnZvaWEyYWpVR2Z3cWFualN5M2lpbl94T1o1d3ZXNmxNTlR4LWs4SDBYVEV0N3djY2dJUnRKNWYwdWZ2QXRjV2cyZU1nNmxZYmhwWm9HOE5UczJlUVFRanJwUkVpdjAxMDdGaXMyT3c?oc=5) | 5일+50%, 당일+20%, RVOL≥5 |
| 3 | EZGO | 2026-05-07 | 상위 | 0% | -65% | 역분할 덤프 | 1-for-150 역분할 발표(5/15), 직전 424B5(4/8) 공모 | [EZGO Announces 1-for-150 Reverse Share Split Effective May 19, 2026 - Yahoo Finance](https://news.google.com/rss/articles/CBMimAFBVV95cUxPemNwUnJQYjVpSTF1aTg2Ym1oV1JiNl9GNk5aXzNGa2VXQVRnaVRPMFJlS05zMlpNSmVGVXJFLWJReGROYTdQSWZjTXNwQy11ZFBTTjJLZmJPUFJiVlRDVnFLLXBvcDBMS2ZMYTR4RWU0ejVxUlJ6M21GUXBDMTRfbjRaejgzenFOczdPdXpHVXUzZThLZXliSQ?oc=5) | 저유통, 과거급등주, SSR, 공모완료, 424B≤30일, 직전5일 +40%봉, RVOL≥5 |
| 4 | DFNS | 2026-07-10 | 상위 | -9% | -65% | 원인 불명 | 하락 원인 뉴스 없음(직전 S-1/A·424B3 7/1 공모 등록은 있음, 이후 7/27 별도 급등) | [SEC 424B3 2026-07-01](https://www.sec.gov/Archives/edgar/data/1787518/000121390026074046/) | 과거급등주, 공모완료, 424B≤30일, 증권신고서≤30일, RVOL≥5, 8-K/6-K≤2일, 위임장≤60일 |
| 5 | VRXA | 2026-06-17 | 상위 | -10% | -65% | 펌프 후 소멸(PR) | 합병 상장 직후 BIO 2026 PR 로 급등→소멸, '밸류에이션 과다' 분석 | [VERAXA Unveils Cancer Therapy Platform, Sparks Partnering Talks at BIO 2026 - Yahoo Finance](https://news.google.com/rss/articles/CBMioAFBVV95cUxPaXV3XzljOWZncE8wVXRldVdkT0NNcXAxQzhVci04TGtZVFJ0ckRjbXI1UWNTZ1o2bWxhZmZRN056VkMyUl9zWW5fTVFuWkRpcHR6ZUxsc0JraHZpNmwtLW1oaTd6MndwZVE2SHNHMzVTUW5pTm9wLWlBS3NDNlktanpxRHpub3JDQmNqcHlpaEdYU0ZQVkxrQk9CS0RGajk0?oc=5) | 저유통, SSR, 직전5일 +40%봉, RVOL≥5 |
| 6 | BCTX | 2026-01-13 | 상위 | -52% | -62% | 유상증자·희석 | +50% 급등 당일 $30M 공모(424B4/S-1MEF) 가격 결정 → -62% | [SEC 8-K 2026-01-15 — Therapeutics Announces Pricing of $30 million Public Offering](https://www.sec.gov/Archives/edgar/data/1610820/000149315226002430/ex99-1.htm) | 저유통, 과거급등주, 증권신고서≤30일, 5일+50%, 당일+20%, RVOL≥5 |
| 7 | WHLR | 2026-08-28 | 상위 | -16% | -61% | 유상증자·희석 | 우선주→보통주 교환 발행(424B3 연속) 중 프리마켓 +124% 후 하락 | [Trending Stocks Today / Wheeler Real Estate Investment Trust Soars 124.1% Pre-Market - Moomoo](https://news.google.com/rss/articles/CBMirwFBVV95cUxOblVRZ2pIQnBZMjhxNHpKeTVTSEdGR3lfcmM0TWZXR0tQVS1teWNwRWRIQlU5NFkxZV8zeEgwMHg1ME50S2xkWmhNaEJMRTZFUTduZzN3TVNVYjhWanIxWnFzOEZ0OU9KbDlYNmZjR203dm9NcktqQjI4NnpxUTdwM3o5dGVpcm5ldzJQdnpuQXdWTW5NUTcxNDNuZEFLY21abVNldjkwakFMSlFyZWNB?oc=5) | 저유통, 과거급등주, SSR, 424B≤30일, RVOL≥5 |
| 8 | WYHG | 2026-08-06 | 상위 | 29% | -59% | 펌프 후 소멸(PR) | ADS 분리로 +582% 후 급락 | [Wing Yip Food (NASDAQ:WYHG; KOSDAQ:900340) jumps 582% as U.S. ADSs detach from Korean shares - TechStock²](https://news.google.com/rss/articles/CBMiqgFBVV95cUxPS0RfSUlVQ3hVeWRwXzk2U2RoWUdNajF1RWNJUHRDdjNLd0dqRnJ6MUNUNDBvMjNjOGxCVVI1anZPZnhZT0IwdG9zSUFFWGpKWWlKcmxTQkhJd0lpSHpyUU1SenNtUmN4Q1c4al9XandWMDhyZ1JjRlZSRTVXSkE0SWtTZzA5c2Q3SFhwU1FoZUttZHU5NkE5cWh6YnROenJ4T1BhaEZseHFZdw?oc=5) | 과거급등주, 갭유지, 5일+50%, 당일+20%, RVOL≥5, 8-K/6-K≤2일 |
| 9 | CRE | 2026-08-26 | 상위 | -10% | -59% | 펌프 후 소멸(PR) | 상반기 고객수 PR 로 +142% 후 하락 | [Trending Stocks Today / Cre8 Enterprise Soars 142.43% - Moomoo](https://news.google.com/rss/articles/CBMilwFBVV95cUxNbTIzRkFic3R6emJpLXdBeVNlSS0zRlA5aEFRTDhiZ0pwcXRia3dQdzN0MTdtRTFYVVZlMVFtSkxVWE9QMHVPQTd3dWN5aVpzcDFxUS1FU3p4S3FWMHdyTzc5cW4wSWNpbS1ycmZsc19QUFdFYkdxRmU1YW5MX1AzT2hFbGtCT1ZhWF9hNXpVZ3o0c20tUVlF?oc=5) | 저유통, 과거급등주, 갭유지, 5일+50%, 당일+20%, RVOL≥5, 8-K/6-K≤2일 |
| 10 | SXTC | 2026-10-09 | 상위 | -25% | -58% | 유상증자·희석 | $12M 등록직접공모(424B5) 발표 → -88% | [China SXT Pharmaceuticals Inc. (SXTC) Announces $12M Registered Direct Offering - TradingView](https://news.google.com/rss/articles/CBMi0wFBVV95cUxQY3lMcll3THJVVGNkNDFrSzJ6bFI2aXowVVlzZ0Fubm5vYVU2T29iT1RoRUFEWkJBZXNzdFhWalE5dEdJYmxjcXNsNlpfdVBxM2dtVk9GbHpUbEJUcG9DS2MtR0lycDdhNi1qaXF3QUY4U2otUGdPdFJDZWx1LTBQRk4taTA5OEVnckhRLTBqZm9YNDNGd2xlNXl2anpMZE5qaDR0SFQ1dl80Rkx2eGpDWkN2UG5mcnlQT1RpeDJQdGtMUVk4aUFtZXZVa1NPajhiS1NJ?oc=5) | 저유통, 과거급등주, SSR, 424B≤30일, 직전5일 +40%봉, RVOL≥5, 8-K/6-K≤2일 |
| 11 | LNAI | 2026-10-12 | 상위 | -2% | -58% | 상장·존속 위험 | 나스닥 거래정지 요청·감사인 '계속기업 의문'(10-K) | [Lunai Bioworks Inc. Auditor Raises 'Going Concern' Doubt - www.marketscreener.com](https://news.google.com/rss/articles/CBMiqgFBVV95cUxQV21WeU83UGtvaXBkNjl3UEVEWDNNa3dpNGZmcVVmWDVJNFFwMFgzc0VabHJuQ3Vyb19NVzlKRjhjdDFxbHVSc2NrX01XQjVMWndxdlZ2bEVickQ1Z0tnaWVOeE92dFFJNWJRMlQxUm90Z2pHX2FiWERVRUR1YXRyVFBmWER3eE5VZDlQaXYxaDFCQjE4dVpQekcxMjJUcU1aQTU4M0JwODlDdw?oc=5) | 과거급등주, SSR, RVOL<1.5 |
| 12 | WHLR | 2026-10-05 | 상위 | 24% | -58% | 유상증자·희석 | 우선주 교환 신주 발행(424B3·8-K 3.02) 중 하루 -47% | [Why Did Wheeler REIT (NASDAQ:WHLR) Crash 47 Percent in a Day? - kalkine.ca](https://news.google.com/rss/articles/CBMimAFBVV95cUxPTHJ0aTJyU3VqWk9JZFk0X1Rld3VtNVdia2c1VTJ0SEVFSmhXZHdKQnNWcHZNSDN5UGh0bmlNdGpZNmpIeGxpRU5uNEQ0LXRYaENwZ1JFUE44UVhXR25sUjFKUE1sOUxWdWwyZ2NzLTg3V2VJRXNOb3ZZZTU3Vk12c3lNX21PQmFtZVZVSEVYZGd1bU4xZHFsag?oc=5) | 저유통, 과거급등주, SSR, 공모완료, 424B≤30일, RVOL<1.5 |
| 13 | LHAI | 2026-07-01 | 상위 | -20% | -56% | 펌프 후 소멸(PR) | 인수 완료·GPU 금융 PR 로 급등 → 'euphoria fades', 나스닥 미준수 통지 | [LHAI Stock Slides After Mortgage One Deal Euphoria Fades - www.timothysykes.com](https://news.google.com/rss/articles/CBMie0FVX3lxTE82ZDZQdjhBV0VhdmkyclhWaDlJc3JyS283ZFRrUGNlOVhDU3p0em1XRDNkM2cyWEpfM1YtYl9DYXUyMTlSUDVzQjhlMElzcHNXUDlnY213YTM5eFM3clZoUERnc29WTDZCZjVScXdIaHQ3UHRWWEtCZm5BMA?oc=5) | 저유통, 갭유지, 5일+50%, 당일+20%, RVOL≥5, 위임장≤60일 |
| 14 | CLIK | 2026-03-16 | 상위 | 8% | -53% | 펌프 후 소멸(PR) | 실적 성장 PR(3/13) 후 하락, 이후 뉴스 없음 | [SEC 6-K 2026-03-13 — Holdings Limited (NASDAQ: CLIK) Reports Strong Growth in Silver Economy Segment,](https://www.sec.gov/Archives/edgar/data/2020027/000149315226009994/ex99-1.htm) | 과거급등주, SSR, RVOL≥5 |
| 15 | PMAX | 2026-09-24 | 상위 | 13% | -53% | 유상증자·희석 | Remington 지분 인수 PR 후 $2.42M 사모(Form D) 조달 | [Powell Max raises $2.42M in private placement, taps Spartan for M&A advisory - Dealroom](https://news.google.com/rss/articles/CBMirAFBVV95cUxOYTZLNVlpOEtaUGMta0NUOTBIUjRfd2x1MTBNOWxQWkdvaEd5c29PNERSQWdENzhqZ09GQ1pZajF3UDIzOEJoU09YTVB6MFhiSlJMcWNTNVBIdkhYR2h4cEpwWlpiUmdKUDZheXJjQndPbnd6dTJTckcxY21RaFM1cUFUcGl0VGM2Z2I2ZGJTMlZkNUo4ZHpZWVR6Yk5KUXhnTVVCaXJrQnNfR3lz?oc=5) | 저유통, 과거급등주, SSR, 갭유지, 5일+50%, 당일+20%, RVOL≥5 |
| 16 | BGDE | 2026-04-24 | 상위 | 15% | -52% | 상장·존속 위험 | 나스닥 상장폐지 결정 통지(8-K 3.01)·사명 변경 | [SEC 8-K 2026-04-23 — Mawson Infrastructure Group Inc. Becomes Big](https://www.sec.gov/Archives/edgar/data/1218683/000121390026047100/ea028753501ex99-1.htm) | 저유통, 과거급등주, SSR, 당일+20%, RVOL<1.5, 8-K/6-K≤2일 |
| 17 | RCT | 2026-06-24 | 상위 | 2% | -51% | 유상증자·희석 | F-1/F-3 재판매 등록 효력(EFFECT 6/23-24) 직후 하락, 같은 기간 PR 다수 | [SEC EFFECT 2026-06-23](https://www.sec.gov/Archives/edgar/data/2027360/999999999526002090/) | 과거급등주, 424B≤30일, 증권신고서≤30일 |
| 18 | GRI | 2026-01-26 | 상위 | 21% | -51% | 유상증자·희석 | 임상 2a 데이터 PR 직후 S-3·424B5 공모(1/30) | [SEC 424B5 2026-01-09](https://www.sec.gov/Archives/edgar/data/1824293/000182429326000005/) | 저유통, 과거급등주, 공모완료, 424B≤30일, 위임장≤60일 |
| 19 | CIRC | 2026-06-23 | 상위 | 14% | -51% | 유상증자·희석 | 정부계약 PR 후 424B3(6/24) 재판매 등록 → 하락 | [Atlantic International’s Circle8 Secures Minimum $52 Million Government Contract Award - Yahoo Finance](https://news.google.com/rss/articles/CBMisAFBVV95cUxOUXBXSjFzdE9ieGF5NEZ1M3RXU0tQaWg0T0Iwb0FELWVTbThzVFZsMnZVMlVLbmZucmJ6YTBCVUNWNUhibzBadHpRNmRzR2R2YWZVaWY3UVNPcVZuZWZkNnNURWhBd0pmZXFRcTZuTm94dHBtNTBvV3o2d3ExLUhwalA1TG5PRml1MVkyUTc4UUszQlBySlgzN2k1WEhOSnQwRkRKUDB6UEduWS1jRUVVZg?oc=5) | SSR, 갭유지, 공모완료, 424B≤30일, 5일+50%, 당일+20%, RVOL≥5 |
| 20 | AZIO | 2025-12-17 | 상위 | -16% | -51% | 원인 불명 | 관련 뉴스·공시 없음 | [검색 결과 없음 (Google News 검색 링크)](https://news.google.com/search?q=%22AZIO%22%20after%3A2025-12-13%20before%3A2025-12-27) | 저유통, SSR, RVOL<1.5, 위임장≤60일 |
| 21 | HCWB | 2026-03-16 | 상위 | 11% | -50% | 펌프 후 소멸(PR) | CAR-T 연구 결과로 프리마켓 급등 → 직전 424B4(2/19) 공모 물량에 소멸 | [HCWB Stock Soars Pre-Market On Positive Research Results For CAR-T Cell Therapy - Stocktwits](https://news.google.com/rss/articles/CBMiwwFBVV95cUxNOFY1UVBjeU5pZFp5U01ic2M0SkRwbjNoWG9YVE53U0F2Y2lLUXY4Q3cwTTlyOEtXVTlsTzhNT0FNRzB6NFItMUIzN3Y0Q2FTSlZqdVkweS1jakFlcTFWWDIwako5Q3NwNU1WdVNRM0o5SkpMVHhkZ2tEX1BRdThzRVNxcjc2RE56THE1SkQxZGZTZzdUQ1p1WTdmZ0dyRUJ6NWJCSzNEM1hKZGs2Ry1nVVhOeW9GUWIwVVNWTXRBcDFpUVU?oc=5) | 저유통, 과거급등주, SSR, 갭유지, 공모완료, 424B≤30일, 증권신고서≤30일, 5일+50%, 당일+20%, RVOL≥5, 위임장≤60일 |
| 22 | PMAX | 2026-04-08 | 상위 | 30% | -43% | 역분할 덤프 | 1-for-10 주식병합 발표(4/15) + 집단소송 조사 | [SEC 6-K 2026-04-15 — POWELL MAX LIMITED ANNOUNCES 1-FOR-10 SHARE CONSOLIDATION EFFECTIVE](https://www.sec.gov/Archives/edgar/data/2012096/000121390026043772/ea028633101ex99-1.htm) | 저유통, 과거급등주 |
| 23 | NAMI | 2026-06-23 | 무작위 | -5% | -38% | 역분할 덤프 | ADS 비율 변경(실질적 역분할) 발표 | [Jinxin Technology Holding Company Announces Plan to Implement ADS Ratio Change - Yahoo Finance](https://news.google.com/rss/articles/CBMirAFBVV95cUxOZDAzLW1ZVGl0VElDWlNqNVNGNXo3NUJHeExJNEQ1bzVEWkIzWEZCVEpSeWlWU1MtYzZ0b0JEWjhpVmIySlp4enZadHpXX1pDTjZRNmU0N3BMTmJKenhFeEV6cDFUdGJWXzQ3cldiQUo2WXpYRV9MZGQ1bUg2eUQ5UUdWemVsZ0QtTzgyc0VWeTJYNTdtX3h6RklOQ0N2TXBJd1MtTEtMcVd3V09J?oc=5) | 과거급등주, SSR, RVOL≥5, 8-K/6-K≤2일 |
| 24 | SPHL | 2026-09-24 | 무작위 | 1% | -28% | 펌프 후 소멸(PR) | 반기 실적 6-K 후 급등→'whipsaw' | [SPHL Stock Whipsaws After Spike, Traders Eye Key Levels - Timothy Sykes](https://news.google.com/rss/articles/CBMigwFBVV95cUxOc250VXVQY0hQWDNGZkppN21DaVRjLUVOOVRDUGxvaG1XRXhONWdDM3N3S2hoRnk3SEo5UjhrdS1NSmdiYnlrcTV5emZzMWtVOU4zelNLTWVIVGRxV2NMNjlHM3hQeWV4U1o0TnV6SDA4SEdQdXNRaTJLenh5bWZzN0pWRQ?oc=5) | 저유통, 과거급등주, 갭유지, 당일+20%, RVOL≥5, 8-K/6-K≤2일 |
| 25 | CIRC | 2026-06-08 | 무작위 | 18% | -28% | 원인 불명 | 뉴스 없음(424B3 5/27 재판매 등록은 있음) | [SEC 424B3 2026-05-27](https://www.sec.gov/Archives/edgar/data/1605888/000121390026061540/) | SSR, 공모완료, 424B≤30일 |
| 26 | FGI | 2025-10-08 | 무작위 | -1% | -21% | 원인 불명 | 뉴스·공시 없음 | [검색 결과 없음 (Google News 검색 링크)](https://news.google.com/search?q=%22FGI%22%20after%3A2025-10-04%20before%3A2025-10-18) | 저유통, 과거급등주, RVOL<1.5 |
| 27 | PRFX | 2026-05-20 | 상위 | -5% | -20% | 펌프 후 소멸(PR) | F-1·424B3(5/19) 직후 전임상·AI PR 연발, 급등 후 -50% | [SEC 424B3 2026-05-19](https://www.sec.gov/Archives/edgar/data/1801834/000117891326002809/) | 저유통, 과거급등주, 424B≤30일, 증권신고서≤30일, RVOL≥5 |
| 28 | QH | 2025-10-08 | 상위 | 10% | -18% | 펌프 후 소멸(무소식) | 관련 뉴스 없음, 54회 연속 경보 후 -91% | [SEC 6-K 2025-10-14 — RULE 13a-16 OR 15d-16](https://www.sec.gov/Archives/edgar/data/1781193/000110465925099277/tm2528680d1_6k.htm) | 저유통, SSR, RVOL≥5 |
| 29 | MYSE | 2026-02-13 | 무작위 | 7% | -16% | 유상증자·희석 | 424B5(2/6) 공모 직후 주주서한 PR | [SEC 424B5 2026-02-06](https://www.sec.gov/Archives/edgar/data/1648960/000121390026013331/) | 저유통, 과거급등주, 공모완료, 424B≤30일, 8-K/6-K≤2일 |
| 30 | QH | 2026-02-18 | 상위 | 11% | -14% | 펌프 후 소멸(무소식) | 직전 424B5(2/11) 공모 후 무소식 급등→폭락(-93%), 임시주총 소집 | [SEC 424B5 2026-02-11](https://www.sec.gov/Archives/edgar/data/1781193/000121390026014927/) | 저유통, 과거급등주, 공모완료, 424B≤30일, 8-K/6-K≤2일 |
| 31 | NOMA | 2026-01-06 | 무작위 | 22% | -13% | 원인 불명 | 뉴스 없음(직전 424B3 12/9) | [SEC 424B3 2025-12-09](https://www.sec.gov/Archives/edgar/data/1994214/000149315225026888/) | 저유통, SSR, 공모완료, 424B≤30일, RVOL≥5 |
| 32 | IVF | 2025-12-18 | 무작위 | 3% | -12% | 유상증자·희석 | S-1 공모 등록(12/17) 시점, 인수 PR 와 겹침 | [SEC S-1 2025-12-17](https://www.sec.gov/Archives/edgar/data/1417926/000149315225028163/) | 저유통, 과거급등주, SSR, 증권신고서≤30일, RVOL<1.5, 8-K/6-K≤2일, 위임장≤60일 |
| 33 | SKYQ | 2025-10-08 | 무작위 | 3% | -12% | 원인 불명 | 뉴스 없음(424B3 9/25 등록은 있음) | [SEC 424B3 2025-09-25](https://www.sec.gov/Archives/edgar/data/1812447/000109690625001578/) | 저유통, 과거급등주, SSR, 공모완료, 424B≤30일, 증권신고서≤30일, RVOL<1.5, 8-K/6-K≤2일, 위임장≤60일 |
| 34 | RCT | 2026-02-23 | 무작위 | 12% | -12% | 원인 불명 | 관련 뉴스 없음 | [SEC 6-K 2026-02-27](https://www.sec.gov/Archives/edgar/data/2027360/000149315226008374/form6-k.htm) | 과거급등주, RVOL<1.5 |
| 35 | EZGO | 2026-10-05 | 무작위 | 12% | -10% | 원인 불명 | 뉴스·공시 없음 | [검색 결과 없음 (Google News 검색 링크)](https://news.google.com/search?q=%22EZGO%22%20after%3A2026-10-01%20before%3A2026-10-15) | 저유통, 과거급등주, RVOL<1.5 |
| 36 | NXAT | 2026-08-19 | 무작위 | 7% | -8% | 유상증자·희석 | 424B5(8/20) 추가 공모 | [SEC 424B5 2026-08-03](https://www.sec.gov/Archives/edgar/data/2000756/000182912626008268/) | 과거급등주, 공모완료, 424B≤30일, 8-K/6-K≤2일 |
| 37 | MOBX | 2026-06-04 | 무작위 | 11% | -8% | 펌프 후 소멸(PR) | 드론업체 인수 PR 당일 급등 후 매도 | [Is MOBX The Next Big Domestic Defense Play? Inside Mobix Labs’ Move to Acquire U.S. Drone Maker Vision Aerial ](https://news.google.com/rss/articles/CBMimwFBVV95cUxQYzdGOFdWRkowLTlTblQtR184YlZjLTBQc0JScHZWTnJIOTNDV29MQXRiQUhGSEd5aGhXNWJuWmVRSnVYZjRxcnNoMHViS3RZLU0taWwzNXRjQXVlY0F5dnBYUzBKUGh1dE9xaVlDRXlPVkI4d0JQb2JzdjR4VGUyMGtqckZnaHEzem14MkwxUHk5UHIwQTdQSGZTMA?oc=5) | 저유통, 과거급등주, 공모완료, 424B≤30일 |
| 38 | XTLB | 2025-11-10 | 무작위 | 10% | -4% | 원인 불명 | 뉴스·공시 없음 | [검색 결과 없음 (Google News 검색 링크)](https://news.google.com/search?q=%22XTLB%22%20after%3A2025-11-06%20before%3A2025-11-20) | 과거급등주 |
| 39 | ACB | 2026-10-05 | 무작위 | 5% | -4% | 원인 불명 | Curaleaf 적대적 인수 제안 진행 중, 추가 상승 없음(공모 아님) | [Aurora Cannabis Inc. (ACB) Urges Holders to Reject Curaleaf’s Revised Hostile Bid - TradingView](https://news.google.com/rss/articles/CBMi1wFBVV95cUxPenBqaWZnRmpPdGdZbUNRZmdORFdzSURFd3RQQ2RoTXRxY2FjSktvYWsxQlVETTJnR1NQZVpiRUJ5R05RRFU4UUsyckRtMEhBbFBlcUVsSHMwUlRwM1hYdzJOd2Zrck10VXFoZDktVUtVdzl6dFhYSXVFSHhyQlFxemtGUGRhMmV5TGpael93WXQ3UGhYVWotcDVuZTFOSk1ScWpGWWlHNzVjNmphZkk2WlJHdkRMa2tQUXlYaG00NUFQeGVrVVVBZnNqRFJ6cmVfZzNnSGhVcw?oc=5) | 갭유지, RVOL≥5 |
| 40 | RCT | 2025-12-03 | 무작위 | 10% | 1% | 원인 불명 | AI 신사업 기사 외 특이사항 없음 | [RedCloud opens new AI chapter for FMCG markets with Genesis - Business Weekly](https://news.google.com/rss/articles/CBMinwFBVV95cUxQODhvbEpQcnJTdjlrV1Q1OHBXLUNvLUtQOU1fRUNFYkFNTzhzdXhQZndoM0tkWnRLUVVnclZQbWh4dmlBb0lxQVF1QzBfXzFfS1ZQNElQblBaVnRuNzdHYlBzWlBOcjNHT0ZuMzdrc1prN3lzNHZDend0RVltVUxCRTdtMGl4c3JzZ1k1OXZsbmRDd2Nyb21VOV9ab1JKUkk?oc=5) | 과거급등주, SSR, RVOL<1.5 |

## 8. 재현

```
python scripts/sa_events.py      # 경보→이벤트
python scripts/sa_research.py    # SEC·뉴스 근거 수집 → data/sa_evidence.json
python scripts/sa_titles.py      # 8-K/6-K 제목 보강
python scripts/sa_splits.py      # 미조정 역분할 탐지
python scripts/sa_features.py    # 경보 시점 특징
python scripts/sa_analyze.py     # 분류표(scripts/sa_cases.py) 결합
python scripts/sa_compare.py     # 전체 경보 특징 비교
python scripts/sa_rerun.py       # 5폴드 재실행
python scripts/sa_report.py      # 이 문서 + model/success_analysis.json
```

> 투자 권유가 아님. 모든 수치는 과거 데이터 기반 추정치입니다.