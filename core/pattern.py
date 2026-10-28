"""🧬 '급락 후 반등' 성공 패턴 일치 (참고 표시 전용 — 종합점수·확률에는 반영 안 함).
커뮤니티 성공 사례 14건(트레이더 자기 보고)의 급등 직전 공통점 6가지를 지금 종목과 비교.
과거 검증(scripts/pattern_study.py → model/pattern_study.json):
  · 5거래일 안 '+30% 터치' 확률은 크게 오름 (전 종목 일봉 36만 건, 5개 시간 구간 모두 같은 방향)
  · 하지만 5일 뒤 종가는 보통 하락, 앱의 성공 기준(재점화 레벨 도달, 손절 전)은 오히려 낮음
  → 점수 가산 X, '짧게 튀는 자리(단타·분할 익절)' 참고 태그로만 보여줌."""
import json, functools
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TRAITS = [("sub1", "$1 미만"), ("tiny", "시총 $10M 미만"), ("dd50", "20일 고점 대비 -50%↓"),
          ("crash30", "10일 안 하루 -30% 폭락"), ("distress", "역분할·상장유지 미달·증자"), ("volx", "거래량 3배↑")]
PRICE_KEYS = ("sub1", "dd50", "crash30", "volx")

@functools.lru_cache(maxsize=1)
def study():
    try: return json.loads((ROOT / "model/pattern_study.json").read_text())
    except Exception: return {}

def match(px, f=None, info=None, fil=None, mcap=None):
    """px: 일봉(date, high, close, volume) asof 까지. f: model.features 결과(선택). 반환 None 또는 dict."""
    if px is None or len(px) < 15: return None
    f = f or {}
    c = px["close"].astype(float).values; hgh = px["high"].astype(float).values; v = px["volume"].astype(float).values
    price = float(f.get("price") or c[-1])
    hi20 = float(np.nanmax(hgh[-20:])); dd = price / hi20 - 1 if hi20 > 0 else 0
    r1 = c[1:] / np.where(c[:-1] > 0, c[:-1], np.nan) - 1
    worst = float(np.nanmin(r1[-10:])) if len(r1) else 0
    base = v[-23:-3] if len(v) >= 23 else v[:-3]
    vb = float(np.nanmean(base)) if len(base) else 0
    vx = float(np.nanmean(v[-3:]) / vb) if vb > 0 else None
    if mcap is None:
        fm = f.get("float_m")
        mcap = fm * 1e6 * price if fm else None
    dis, why = False, []
    if f.get("rs_recent"): dis = True; why.append("최근 역분할")
    if f.get("def301"): dis = True; why.append("상장유지 미달(3.01)")
    try:
        if fil is not None and len(fil):
            asof = pd.Timestamp(px["date"].iloc[-1])
            q = fil[(pd.to_datetime(fil["filed"]) >= asof - pd.Timedelta(days=30)) & fil["form"].astype(str).str.match(r"^424B")]
            if len(q): dis = True; why.append("30일 내 증자(424B)")
    except Exception: pass
    if not why and f.get("dilution_recent"): dis = True; why.append("최근 희석")
    val = {"sub1": (price < 1, f"${price:.3g}"), "tiny": (bool(mcap and mcap < 10e6), f"${mcap / 1e6:.1f}M" if mcap else "데이터 없음"),
           "dd50": (dd <= -0.5, f"{dd * 100:+.0f}%"), "crash30": (worst <= -0.3, f"최악 {worst * 100:+.0f}%"),
           "distress": (dis, ", ".join(why) or "없음"), "volx": (bool(vx and vx >= 3), f"{vx:.1f}배" if vx else "N/A")}
    hits = [dict(key=k, label=lab, on=bool(val[k][0]), val=val[k][1]) for k, lab in TRAITS]
    n = sum(x["on"] for x in hits); k4 = sum(x["on"] for x in hits if x["key"] in PRICE_KEYS)
    S = study(); B = (S.get("B") or {}); A = (S.get("A") or {})
    cnt = (B.get("count") or {}).get(str(k4)) or {}
    base = (B.get("base") or {})
    return dict(n=n, m=len(TRAITS), k4=k4, hits=hits, spike=cnt.get("hit30"), spike_base=base.get("hit30"),
                fc5_med=cnt.get("fc5_med"), n_hist=cnt.get("n"), app_hit=((A.get("count") or {}).get(">=3") or {}).get("hit"),
                app_base=(A.get("base") or {}).get("hit"))

def tag(pm):
    """카드용 짧은 배지 글 (3개 이상 일치일 때만)."""
    if not pm or pm["n"] < 3: return None
    return f"🧬 성공 패턴 {pm['n']}/{pm['m']} (참고)"

def line(pm):
    """복사 글·카드 한 줄 설명 (평이한 한국어)."""
    if not pm: return None
    on = [x["label"] for x in pm["hits"] if x["on"]]
    s = f"🧬 성공 패턴 일치 {pm['n']}/{pm['m']} (참고, 점수 미반영)" + (f": {', '.join(on)}" if on else "")
    if pm.get("spike") is not None and pm["k4"] >= 2:
        s += f" · 과거 비슷한 자리 5일 안 +30% 터치 {pm['spike'] * 100:.0f}% (평균 {pm['spike_base'] * 100:.0f}%)"
        if pm.get("fc5_med") is not None: s += f", 단 5일 뒤 종가는 보통 {pm['fc5_med'] * 100:+.0f}% → 짧게 익절"
    return s
