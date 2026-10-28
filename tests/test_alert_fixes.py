"""알림 개선 단위 테스트 (pytest 없이도 실행: python tests/test_alert_fixes.py)."""
import os, sys, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
from zoneinfo import ZoneInfo
from core import live, alerts, filings as F

ET = ZoneInfo("America/New_York")

def _px(rows):
    return pd.DataFrame(rows, columns=["date", "close", "volume"])

def test_ref_close_aeye_premarket_before_today_bars():
    # 10/28 04:07 ET: 1분봉 마지막 날 = 10/27 (오늘 봉 아직 없음). 예전 코드는 10/26 종가 7.42 기준 → +38%
    eh = {"day": "2026-10-27", "reg_close": 10.14, "prev_close": 7.42, "prev_date": "2026-10-26", "last": 10.25}
    px = _px([("2026-10-26", 7.42, 1), ("2026-10-27", 10.14, 1)])
    now = dt.datetime(2026, 10, 28, 4, 7, tzinfo=ET)
    ref, d = live.ref_close(eh, px, now)
    assert abs(ref - 10.14) < 1e-9 and d == "2026-10-27"
    assert abs((10.25 / ref - 1) * 100 - 1.08) < 0.1          # 실제 +1.1%

def test_ref_close_prefers_db_daily_close():
    eh = {"day": "2026-10-28", "prev_close": 9.9, "prev_date": "2026-10-27", "last": 12}
    px = _px([("2026-10-26", 7.42, 1), ("2026-10-27", 10.14, 1)])
    now = dt.datetime(2026, 10, 28, 10, 0, tzinfo=ET)
    assert live.ref_close(eh, px, now)[0] == 10.14

def test_ref_close_db_stale_uses_1m():
    eh = {"day": "2026-10-28", "prev_close": 10.14, "prev_date": "2026-10-27", "last": 12}
    px = _px([("2026-10-26", 7.42, 1)])                         # DB 에 10/27 아직 없음
    now = dt.datetime(2026, 10, 28, 10, 0, tzinfo=ET)
    assert live.ref_close(eh, px, now)[0] == 10.14

def test_grade_levels_rejects_absurd():
    assert alerts.grade_levels(0.80, 5.0, -0.296, None) == (None, None)      # TRUG
    assert alerts.grade_levels(0.079, 25, -25, None) == (None, None)         # CDT
    assert alerts.grade_levels(1.0, 1.3, 0.9, None) == (1.3, 0.9)
    assert alerts.grade_levels(1.0, 3.0, 0.9, 1.5) == (1.5, 0.9)             # 목표 +200% → 다음 저항

def test_post_filter():
    c = dict(alerts.DEFAULTS)
    sig = [("spike", "a"), ("prob", "b"), ("rvol", "c")]
    assert alerts._post_filter(sig, c, "post") == [("prob", "b")]
    assert alerts._post_filter(sig, c, "regular") == sig

def test_prune_keeps_today_counts():
    now = dt.datetime(2026, 10, 28, 12, tzinfo=ET).timestamp()
    st = {"X:any": now - 100, "X:n:20261028": 2, "X:n:20261001": 1, "Y:spike": now - 9 * 86400}
    out = alerts._prune(st, now)
    assert out == {"X:any": now - 100, "X:n:20261028": 2}

def test_insider_min():
    orig = F.form4_buy
    try:
        F.form4_buy = lambda *a: (22000.0, "CEO")             # OWLS 10/28 형
        small = F.judge({"form": "4", "cik": 1, "acc": "x", "primary": "x", "items": "", "title": "", "desc": ""}, insider_min=100000)
        F.form4_buy = lambda *a: (425000.0, "CEO")
        big = F.judge({"form": "4", "cik": 1, "acc": "x", "primary": "x", "items": "", "title": "", "desc": ""}, insider_min=100000)
    finally:
        F.form4_buy = orig
    assert small["polarity"] == "neutral" and big["polarity"] == "pos", (small, big)
    assert "소액" in small.get("label", ""), small

def test_feed_regex():
    s = '<entry><title>8-K - Aeye, Inc. (0001815776) (Filer)</title><updated>2026-10-28T08:01:02-04:00</updated></entry>'
    m = F._FEED_RE.findall(s)
    assert m, "피드 형식 파싱 실패"

def test_buy_zone_sane():
    from core import model
    pp = {"fee_rate": 0.1, "slippage": 0.2}
    # CDT 형: 주가 $0.079, 분할 전 가격이 섞인 매물대 (폭 25, 위 레벨 25)
    meta = {"tranches": [{"lo": 0.07, "hi": 25.0, "name": "A"}], "width": 25.0, "gaps": [], "reignite": 25.0, "hi21": 30.0, "lo21": 0.06}
    bz = model.buy_zone({"price": 0.079}, meta, pp)
    assert 0 < bz["stop"] < 0.079 and bz["stop"] >= 0.079 * 0.45, bz
    assert 0.079 < bz["tp1"] <= 0.079 * 3 and bz["tp1"] < bz["tp2"] <= 0.079 * 3 * 1.15 + 1e-9, bz
    assert isinstance(bz["stop"], float) and bz["capped"]
    # 정상형은 그대로
    meta2 = {"tranches": [{"lo": 0.9, "hi": 1.0, "name": "A"}, {"lo": 1.1, "hi": 1.3, "name": "B"}], "width": 0.05, "gaps": [], "reignite": 1.2, "hi21": 1.5, "lo21": 0.8}
    bz2 = model.buy_zone({"price": 1.0}, meta2, pp)
    assert abs(bz2["stop"] - 0.85) < 1e-9 and bz2["tp1"] == 1.2 and bz2["capped"] == []

if __name__ == "__main__":
    n = 0
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v(); n += 1; print("ok", k)
    print(f"{n}개 통과")
