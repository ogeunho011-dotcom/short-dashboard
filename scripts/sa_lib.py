"""성공/실패 분석 공용: research.py 의 데이터·폴드·모델·시뮬레이터 부분만 실행해 재사용."""
from pathlib import Path
_src = (Path(__file__).with_name("research.py")).read_text(encoding="utf-8")
_cut = _src.index("best = max(MODELS")
_sim0 = _src.index("# ---------------- 청산 규칙 시뮬레이션"); _sim1 = _src.index("before = baseline_before()")
_code = _src[:_cut].replace('MODELS = ["M0_saved", "M1_gated", "M2_logit", "M3_gbm"]', 'MODELS = ["M0_saved", "M1_gated"]') + "\n" + _src[_sim0:_sim1]
exec(compile(_code, "research_prefix", "exec"), globals())
