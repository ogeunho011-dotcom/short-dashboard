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

_F4 = """<ownershipDocument><reportingOwner><reportingOwnerId><rptOwnerName>{who}</rptOwnerName></reportingOwnerId></reportingOwner>
<nonDerivativeTable>{rows}</nonDerivativeTable><derivativeTable><derivativeTransaction><transactionCoding><transactionCode>P</transactionCode></transactionCoding>
<transactionAmounts><transactionShares><value>5502402</value></transactionShares><transactionPricePerShare><value>3149.47</value></transactionPricePerShare></transactionAmounts>
</derivativeTransaction></derivativeTable></ownershipDocument>"""
def _f4row(code, sh, pr):
    return (f"<nonDerivativeTransaction><transactionCoding><transactionCode>{code}</transactionCode></transactionCoding><transactionAmounts>"
            f"<transactionShares><value>{sh}</value></transactionShares><transactionPricePerShare><value>{pr}</value></transactionPricePerShare></transactionAmounts>"
            f"<postTransactionAmounts><sharesOwnedFollowingTransaction><value>99999999</value></sharesOwnedFollowingTransaction></postTransactionAmounts></nonDerivativeTransaction>")

def test_form4_lona_bad_price_rejected():
    # LONA 10/28 신고 (0002126186-26-000002): 워런트 행사 3,149,470주를 P 로, 주당 칸에 총 행사대금 $3,149.47 → 예전 $9,919,161,281
    ref = {"lo": 4.55, "hi": 5.75, "close": 4.96, "mcap": 46071932.0}
    xml = _F4.format(who="Portman David J.", rows=_f4row("P", "3149470", "3149.47")).encode()
    assert F.form4_parse(xml, None)["total"] > 9.9e9                       # 시세 기준이 없으면 막을 수 없던 값
    o = F.form4_parse(xml, ref)
    assert o["total"] == 0 and o["rejected"] and "시세" in o["rejected"][0]

def test_form4_normal_and_sanity():
    ref = {"lo": 2.85, "hi": 3.89, "close": 3.0, "mcap": 121.5e6}           # NVA 10/28 형: 6,780주 × $2.95
    rows = _f4row("P", "6780.0000", "2.9500") + _f4row("S", "1000", "3.0") + _f4row("P", "", "3.0") + _f4row("P", "500", "")
    o = F.form4_parse(_F4.format(who="X", rows=rows).encode(), ref)
    assert abs(o["total"] - 20001) < 1 and o["rows"] == 1 and len(o["rejected"]) == 2   # 매도·가격/수량 빈 줄 제외, 파생 표·보유 수량 무시
    big = _f4row("P", "50000000", "3.0")                                    # 상장 주식 수(약 4,050만) 초과
    assert F.form4_parse(_F4.format(who="X", rows=big).encode(), ref)["total"] == 0
    over = _f4row("P", "30000000", "3.8") + _f4row("P", "10000000", "3.8")   # 합계 $1.52억 > 시총
    assert F.form4_parse(_F4.format(who="X", rows=over).encode(), ref)["total"] == 0

def test_adapt_cold_keeps_under_target():
    import importlib.util
    spec = importlib.util.spec_from_file_location("ar", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "alerts_run.py"))
    ar = importlib.util.module_from_spec(spec); spec.loader.exec_module(ar)
    ad = {"n": 1100, "pos": 0, "per": None, "other": None, "last": None, "prev_n": None}
    # 느린 러너: 2,101종목 받는 데 150초, 그 밖 30초 → 회차 180초 → 줄여야 함
    n1 = ar.adapt_cold(180, 150, 2101, 1001, 2300, 120, ad)
    assert n1 < 1100 and n1 >= 550
    n = n1
    for _ in range(8):                                                     # 같은 속도로 몇 회차 → 목표 근처로 수렴
        fetch = 150 / 2101 * (1001 + n); n = ar.adapt_cold(fetch + 30, fetch, 1001 + n, 1001, 2300, 120, ad)
    assert 150 / 2101 * (1001 + n) + 30 <= 121, n
    # 빠른 러너: 여유 있으면 늘리되 2배 넘게 한 번에 늘리지 않음, 나머지 전체 수 넘지 않음
    ad2 = {"n": 300, "pos": 0, "per": None, "other": None, "last": None, "prev_n": None}
    assert ar.adapt_cold(30, 10, 1300, 1000, 2300, 120, ad2) == 600
    assert ar.adapt_cold(30, 10, 1600, 1000, 700, 120, ad2) == 700
    # 핵심+핫만으로도 넘으면 최소 조각(COLD_MIN)으로
    ad3 = {"n": 100, "pos": 0, "per": None, "other": None, "last": None, "prev_n": None}
    assert ar.adapt_cold(200, 180, 1100, 1000, 2300, 120, ad3) == ar.COLD_MIN

# ---------------------------------------------------------------- 💣 최신 공시 값 · ⚠️ 참고 경고 4종
_XBRL = """<xbrl><xbrli:context id="c1"><xbrli:entity/><xbrli:period><xbrli:instant>2026-06-30</xbrli:instant></xbrli:period></xbrli:context>
<xbrli:context id="c0"><xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period></xbrli:context>
<xbrli:context id="d6"><xbrli:period><xbrli:startDate>2026-01-01</xbrli:startDate><xbrli:endDate>2026-06-30</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="d3"><xbrli:period><xbrli:startDate>2026-04-01</xbrli:startDate><xbrli:endDate>2026-06-30</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="seg"><xbrli:entity><xbrli:segment><xbrldi:explicitMember>x</xbrldi:explicitMember></xbrli:segment></xbrli:entity><xbrli:period><xbrli:instant>2026-09-30</xbrli:instant></xbrli:period></xbrli:context>
<ifrs-full:CashAndCashEquivalents contextRef="c1" decimals="0">770000</ifrs-full:CashAndCashEquivalents>
<ifrs-full:CashAndCashEquivalents contextRef="c0" decimals="0">480000</ifrs-full:CashAndCashEquivalents>
<ifrs-full:CashAndCashEquivalents contextRef="seg" decimals="0">999</ifrs-full:CashAndCashEquivalents>
<ifrs-full:CashFlowsFromUsedInOperatingActivities contextRef="d6">-8207239</ifrs-full:CashFlowsFromUsedInOperatingActivities>
<ifrs-full:CashFlowsFromUsedInOperatingActivities contextRef="d3">-3000000</ifrs-full:CashFlowsFromUsedInOperatingActivities></xbrl>"""
_SWAP = ("RedCloud Holdings plc (Nasdaq: RCT) today announced that it has entered into subscription agreements and set-off agreements with Company insiders "
         "pursuant to which the Company agreed to issue and sell 31.7 million of its unregistered ordinary shares in a private placement at a price per share of $0.25, "
         "representing a premium of approximately 281% to the closing price of the Company’s ordinary shares on October 27, 2026, for an aggregate subscription price of $7,925,000. "
         "The aggregate subscription price will be paid to the Company by offsetting financial liabilities of the Company owed to such Company insiders.")

def test_events_parsers():
    from core import events as EV
    x = EV.parse_instance(_XBRL)
    assert x["cash"] == ("2026-06-30", 770000.0)                                # 차원 있는 값(999)·이전 기간 무시
    assert x["opcf"] == ("2026-01-01", "2026-06-30", -8207239.0)                # 같은 끝날 → 가장 긴 기간
    s = EV.parse_swap(_SWAP)
    assert s["shares"] == 31.7e6 and s["price"] == 0.25 and s["insider"] and s["close_date"] == "2026-10-27" and s["cash_in"] is False
    assert EV.parse_swap("The Company sold shares for cash in a registered direct offering.") is None
    t = "the Issuer had 85,956,495 ordinary shares outstanding as of October 27, 2026. 86,091,495 shares including options to purchase 135,000 shares outstanding as of October 27, 2026"
    assert (85956495.0, "2026-10-27") in EV.parse_shares_out(t)
    assert EV.parse_shares_out("As of August 1, 2026, there were 12,345,678 shares of common stock") == [(12345678.0, "2026-08-01")]
    assert EV.parse_delist("On October 13, 2026 the Company received a Determination Letter from Nasdaq. The Company requested a hearing before the Panel, "
                           "which stayed the suspension of trading. The hearing is scheduled for November 20, 2026.") == {"status": "hearing", "hearing": "2026-11-20"}
    assert EV.parse_delist("The Company received a deficiency notice from Nasdaq regarding the minimum bid price.") is None
    assert EV.parse_delist("Nasdaq notified the Company that it has regained compliance and the Panel closed the matter.")["status"] == "regained"
    m = EV.parse_rsmeet("PROPOSAL 2: approve a reverse stock split at a ratio of 1-for-5 to 1-for-50. The special meeting of stockholders will be held on December 3, 2026.", "2026-10-20")
    assert m["date"] == "2026-12-03" and m["ratio"] == "1:5~50"
    px = pd.DataFrame({"close": [0.2] * 5 + [0.09] * 10})
    assert EV.le10_streak(px) == 10 and EV.le10_streak(pd.DataFrame({"close": [0.09] * 3 + [0.11]})) == 0

def test_events_latest_and_warnings():
    from core import events as EV, structure as ST
    fd = {"docs": [
        {"form": "6-K", "filed": "2026-09-30", "url": "u1", "xbrl": EV.parse_instance(_XBRL)},
        {"form": "SCHEDULE 13D/A", "filed": "2026-10-27", "url": "u2", "shares_out": [(85956495.0, "2026-10-27")]},
        {"form": "6-K", "filed": "2026-10-28", "url": "u3", "swap": EV.parse_swap(_SWAP)},
        {"form": "6-K", "filed": "2026-10-15", "url": "u4", "delist": {"status": "hearing", "hearing": None}},
        {"form": "6-K", "filed": "2026-10-29", "url": "u5", "swap": EV.parse_swap(_SWAP)},   # 같은 거래 재공시 → 한 번만
    ]}
    lt = EV.latest(fd, "2026-10-29")
    assert lt["cash"][:2] == ("2026-06-30", 770000.0)
    assert abs(lt["shares"]["n"] - 117656495) < 1 and len(lt["shares"]["adds"]) == 1
    assert abs(-lt["opcf"][2] / ST.months(lt["opcf"][0], lt["opcf"][1]) - 8207239 / 6) < 1           # 6개월 → 월 $1.37M
    assert "shares" not in EV.latest(fd, "2026-10-26") or EV.latest(fd, "2026-10-26")["shares"]["n"] != lt["shares"]["n"]   # 접수 전 공시는 안 씀
    d = pd.bdate_range("2026-10-01", "2026-10-28")
    px = pd.DataFrame({"date": d, "close": [0.2] * (len(d) - 10) + [0.066] * 10})
    W = EV.warnings("RCT", px, fd, exchange="NASDAQ", asof="2026-10-28")
    k = {w["kind"]: w for w in W}
    assert set(k) == {"swap", "le10", "delist"}
    assert "$0.066" in k["swap"]["text"] and "+279%" in k["swap"]["text"] and "+37%" in k["swap"]["text"] and "현금 유입 없음" in k["swap"]["text"]
    assert "10거래일" in k["le10"]["text"]
    assert not any(w["kind"] == "le10" for w in EV.warnings("X", px, {}, exchange="NYSE American", asof="2026-10-28"))
    assert EV.warnings("X", px, {"docs": [dict(fd["docs"][3], delist={"status": "regained", "hearing": None})]}, exchange="NYSE", asof="2026-10-28") == []

if __name__ == "__main__":
    n = 0
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v(); n += 1; print("ok", k)
    print(f"{n}개 통과")
