"""모델 파라미터 기본값 (UI '관리' 탭에서 조정 → settings 테이블에 저장)."""
from . import db

DEFAULTS = {
    # 유니버스 (초소형주 기본)
    "univ_max_mcap_m": 2000.0,  # 시가총액 상한 ($M) — 초소형~소형주 전부 (< $2B)
    "univ_max_price": 1000.0,   # 주가 상한 ($) — 사실상 끔 (시총으로만 거름)
    "univ_min_price": 0.05,     # 주가 하한 ($, $1 미만 포함)
    "univ_min_dv_k": 100.0,     # 20일 평균 거래대금 하한 ($k) — 죽은 종목 제외
    "univ_max_zero_days": 3,    # 최근 20일 중 거래량 0인 날 허용 수
    "vol_base_floor": 20000,    # 거래량 배수 계산 시 기준 거래량 하한(주) — 극단 배수 방지
    "scan_top_k": 200,          # 정밀 분석 종목 수
    "univ_max_float_m": 50.0,   # 유통주식 상한 (백만주, 0=끄기) — 정밀 분석 후 적용
    "low_float_m": 20.0,        # '소형 유통' 기준 (백만주)
    "float_rot_x": 1.0,         # 유통주식 회전 기준 (당일 거래량 ÷ 유통주식)
    "dtc_days": 5.0,            # 숏 커버 일수 기준
    "low_inst_pct": 5.0,        # 기관 보유 낮음 기준 (%)
    "w_low_float": 1.0, "w_float_rot": 1.0, "w_dtc": 0.7, "w_gap_hold": 1.0, "w_breakout": 1.0, "w_squeeze_break": 1.0,
    "w_vol_streak": 0.7, "w_close_high": 0.7, "w_ssr": 0.5, "w_runner": 0.7, "w_halt_hist": 0.7, "w_catalyst": 0.7,
    "w_insider_buy": 0.5, "w_earnings_soon": 0.3, "w_offering_done": 0.5, "w_rs_lowfloat": 0.5, "w_round_reclaim": 0.5,
    "w_theme": 0.3, "w_low_inst": 0.3,
    "w_pm_gap": 0.5, "w_ah_move": 0.5, "w_vwap_reclaim": 0.5, "w_options_calls": 0.3, "w_sympathy": 0.5,
    # 예측 목표
    "horizon_days": 5,          # N일 이내
    "target_pct": 30.0,         # +X% 급등 (고가 기준)
    "stop_pct": 15.0,           # 백테스트 손절 %
    "success_def": "setup",     # 확률 카드 성공 정의 (model/research_defs.json 키, 'legacy'=기존 +30%/5일)
    # 신호 임계값
    "vol_mult": 3.0,            # 거래량 급증 배수 (20일 중앙값 대비)
    "sv_z": 1.5,                # 공매도 비율 z-score
    "si_float_pct": 15.0,       # 유통주식 대비 숏 %
    "si_change_pct": 20.0,      # 직전 공표 대비 숏 잔고 증가 %
    "loss_side_pct": 50.0,      # 손실권 숏 비중 %
    "reignite_near": 0.85,      # 재점화 레벨 도달률
    "fee_pct": 30.0,            # CTB 연 %
    "avail_low": 50000,         # 차입 가능 수량 하한
    "bbw_pctile": 20.0,         # 볼린저 폭 하위 백분위 (응축)
    # 가중치
    "w_vol": 1.0, "w_sv": 1.0, "w_si_float": 1.0, "w_si_change": 1.0, "w_loss_side": 1.5,
    "w_reignite": 1.0, "w_borrow": 1.0, "w_fee": 1.0, "w_ftd": 0.7, "w_threshold": 0.7, "w_coil": 0.5,
    # 판정
    "flag_score": 45.0,         # 경보 점수 기준
    "min_confluence": 3,        # 최소 동시 신호 수
    "regime_adj": 10.0,         # 약세장에서 기준 점수 가산
    "dilution_penalty": 0.25,   # 최근 증자 공시 시 점수 감산 비율
    # 진입 구간 맵
    "map_lookback": 90,
    "band_width": 0.0,          # 0 = 자동
    "default_short_ratio": 0.45,# FINRA 미수집 시 일 거래량 중 공매도 비율 가정
    "retention": 0.08,          # 일 공매도 거래 중 익일 잔존 비율(SI 없을 때)
    "base_cover": 0.01,         # 일일 기본 커버율
    "squeeze_cover": 0.06,      # 손실권 진입 시 추가 커버율
    # 확률 보정
    "min_samples": 30,
    "calib_bins": 5,
    # 매수 구간 / 비용
    "fee_rate": 0.1,            # 편도 수수료 %
    "slippage": 0.5,            # 편도 슬리피지 %
}

LABELS = {
    "univ_max_mcap_m": "유니버스 시총 상한 ($M)", "univ_max_price": "유니버스 주가 상한 ($)", "univ_min_price": "유니버스 주가 하한 ($)",
    "univ_min_dv_k": "최소 20일 평균 거래대금 ($k)", "univ_max_zero_days": "20일 중 거래량 0일 허용", "vol_base_floor": "거래량 배수 기준 하한(주)",
    "scan_top_k": "정밀 분석 종목 수", "univ_max_float_m": "유통주식 상한 (백만주, 0=끄기)", "low_float_m": "소형 유통 기준 (백만주)",
    "float_rot_x": "유통주식 회전 기준 (배)", "dtc_days": "숏 커버 일수 기준 (일)", "low_inst_pct": "기관 보유 낮음 기준 (%)",
    "w_low_float": "가중치: 소형 유통주식", "w_float_rot": "가중치: 유통주식 회전", "w_dtc": "가중치: 숏 커버 일수", "w_gap_hold": "가중치: 갭상승 유지",
    "w_breakout": "가중치: 신고가 돌파", "w_squeeze_break": "가중치: 응축 후 돌파", "w_vol_streak": "가중치: 거래량 연속 증가", "w_close_high": "가중치: 고가 마감",
    "w_ssr": "가중치: 전일 SSR", "w_runner": "가중치: 과거 급등 이력", "w_halt_hist": "가중치: 급등 정지 이력", "w_catalyst": "가중치: 최근 공시",
    "w_insider_buy": "가중치: 내부자 매수", "w_earnings_soon": "가중치: 실적 임박", "w_offering_done": "가중치: 증자 완료", "w_rs_lowfloat": "가중치: 역분할+소형 유통",
    "w_round_reclaim": "가중치: $1·라운드 회복", "w_theme": "가중치: 핫 테마", "w_low_inst": "가중치: 기관 보유 낮음",
    "w_pm_gap": "가중치: 프리마켓 갭 (라이브)", "w_ah_move": "가중치: 시간외 급등 (라이브)", "w_vwap_reclaim": "가중치: VWAP 회복 (라이브)",
    "w_options_calls": "가중치: 콜옵션 이상 (라이브)", "w_sympathy": "가중치: 업종 동조 (라이브)",
    "horizon_days": "예측 기간 N (거래일)", "target_pct": "급등 기준 +%", "stop_pct": "손절 %", "success_def": "성공 정의 (확률 카드)",
    "vol_mult": "거래량 급증 배수", "sv_z": "공매도비율 z", "si_float_pct": "유통 대비 숏 %", "si_change_pct": "숏 잔고 증가 %",
    "loss_side_pct": "손실권 숏 비중 %", "reignite_near": "재점화 도달률", "fee_pct": "CTB 기준 %", "avail_low": "차입가능 하한(주)",
    "bbw_pctile": "볼린저 응축 백분위", "flag_score": "경보 점수 기준", "min_confluence": "최소 동시 신호 수",
    "regime_adj": "약세장 가산점", "dilution_penalty": "증자 감점 비율", "map_lookback": "맵 기간(일)", "band_width": "밴드 폭($, 0=자동)",
    "default_short_ratio": "공매도비율 가정(FINRA 없음)", "retention": "잔존 비율 가정", "base_cover": "기본 커버율/일",
    "squeeze_cover": "손실권 추가 커버율/일", "min_samples": "확률 최소 표본", "calib_bins": "확률 구간 수",
    "fee_rate": "수수료 % (편도)", "slippage": "슬리피지 % (편도)",
}

def _research_weights():
    """model/research.json(커밋됨)의 검증 가중치 → 새 설치(빈 DB)에서도 같은 모델로 시작"""
    import json
    from pathlib import Path
    fp = Path(__file__).resolve().parents[1] / "model" / "research.json"
    try: return {f"w_{k}": round(float(v), 3) for k, v in json.loads(fp.read_text(encoding="utf-8")).get("weights", {}).items()}
    except Exception: return {}

def load():
    p = dict(DEFAULTS)
    p.update({k: v for k, v in _research_weights().items() if k in DEFAULTS})
    sv = db.get_setting("params", {}) or {}
    if sv and not db.get_setting("univ_v2", False):
        # 1회 이전: 예전 기본값(시총 $300M·주가 $10)을 그대로 저장해 둔 경우 → 새 기본(초소형~소형주 전부, < $2B)으로
        ch = False
        if float(sv.get("univ_max_mcap_m", 300)) == 300.0: sv["univ_max_mcap_m"] = DEFAULTS["univ_max_mcap_m"]; ch = True
        if float(sv.get("univ_max_price", 10)) == 10.0: sv["univ_max_price"] = DEFAULTS["univ_max_price"]; ch = True
        try:
            if ch: db.set_setting("params", sv)
            db.set_setting("univ_v2", True)
        except Exception:
            pass
    p.update(sv)
    return p

def save(p):
    db.set_setting("params", {k: p[k] for k in DEFAULTS if k in p})
