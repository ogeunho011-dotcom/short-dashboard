"""🔬 SEC 퀵스캔 단위 테스트 (가짜 데이터 · 네트워크 없음). python -m pytest tests/test_secscan.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd
from core import secscan as SS

def _px(n=80, p=0.5, start="2026-06-01"):
    d = pd.bdate_range(start, periods=n)
    return pd.DataFrame(dict(date=d, open=p, high=p * 1.05, low=p * 0.95, close=p, volume=1e6))

def _fx(shares=10e6, cash=2e6, filed="2026-05-10"):
    s = lambda v: [dict(val=v, end="2026-03-31", filed=filed, form="10-Q", acc="0000000000-26-000001")]
    return dict(shares=s(shares), cash=s(cash), equity=s(-1e6))

ROWS = [dict(form="8-K", filed="2026-09-01", items="3.01,9.01"), dict(form="424B5", filed="2026-08-20", items=""),
        dict(form="S-3", filed="2026-01-05", items=""), dict(form="10-Q", filed="2026-08-10", items=""),
        dict(form="8-K", filed="2026-12-01", items="1.01")]   # 미래 공시 — 안 보여야 함

def test_pit_no_lookahead():
    px = _px()
    F = SS.pit(ROWS, _fx(), px, "2026-09-10")
    assert F["n_rows"] == 4 and F["i101_90"] == 0          # 2026-12-01 공시는 제외
    assert F["def301"] == ["2026-09-01"] and F["n424b5_365"] == 1 and F["shelf_n"] == 1
    assert F["price"] == 0.5 and F["mcap"] == 10e6 * 0.5
    assert F["below1"] >= 30
    # 기준일보다 뒤의 가격은 쓰지 않음
    px2 = px.copy(); px2.loc[px2.date > "2026-09-10", "close"] = 99
    assert SS.pit(ROWS, _fx(), px2, "2026-09-10")["price"] == 0.5

def test_score_range_and_grade():
    F = SS.pit(ROWS, _fx(), _px(), "2026-09-10")
    S = SS.score(F, None)
    assert len(S["items"]) == 9 and sum(x["max"] for x in S["items"]) == 100
    assert 0 <= S["total"] <= 100 and S["grade"] in "ABCD"
    k = {x["k"]: x for x in S["items"]}
    assert "상장 유지 미달 통지" in k["balance"]["why"] and "자본 잠식" in k["balance"]["why"]
    assert "ATM/셸프" in k["dilution"]["why"]
    # 원문 해석(D)이 있으면 그 값을 씀
    S2 = SS.score(F, dict(cat="A", atm_active=False))
    assert {x["k"]: x for x in S2["items"]}["catalyst"]["pts"] == 15

def test_score_missing_is_not_zero_evidence():
    F = SS.pit([], {}, None, "2026-09-10")
    S = SS.score(F, None)
    assert {x["k"]: x for x in S["items"]}["evidence"]["pts"] == 0 and S["grade"] == "D"

def test_listing_nasdaq_and_notices():
    F = SS.pit(ROWS, _fx(), _px(), "2026-09-10")
    docs = [dict(form="8-K", filed="2026-09-01", items="3.01", url="u1", d=dict(def_kind="최소 주가 $1", deadline="2027-02-28")),
            dict(form="8-K", filed="2026-09-02", items="8.01", url="u2", d=dict(def_kind="정기 보고서 지연")),   # 3.01 아님 → 무시
            dict(form="424B5", filed="2026-08-20", items="", url="u3", d=dict(def_kind="최소 주가 $1"))]       # 투자설명서 → 무시
    L = SS.listing("Nasdaq", F, docs)
    ntc = [r for r in L["rules"] if r["state"] == "미달 통지"]
    assert len(ntc) == 1 and "2027-02-28" in ntc[0]["val"]
    assert L["rules"][0]["state"] == "미달"                  # $1 미만 30일+
    # 회복 공시가 있으면 상태 바뀜
    L2 = SS.listing("Nasdaq", F, docs + [dict(form="6-K", filed="2026-09-05", items="", url="u4", d=dict(regained=True))])
    assert any(r["state"] == "통지 후 회복 공시 있음" for r in L2["rules"])
    # 기한이 접수일보다 앞이면 표시 안 함
    L3 = SS.listing("Nasdaq", F, [dict(docs[0], d=dict(def_kind="최소 주가 $1", deadline="2025-01-01"))])
    assert "기한 확인되지 않음" in [r for r in L3["rules"] if r["state"] == "미달 통지"][0]["val"]

def test_listing_otc_unknown():
    F = SS.pit(ROWS[1:], _fx(), _px(), "2026-09-10")      # 3.01 공시 없음
    L = SS.listing("OTC", F, [])
    assert L["rules"][0]["state"] == SS.NA and L["bad"] == 0
    # 3.01 공시가 목록에만 있으면(원문 없음) 통지로 표시
    L2 = SS.listing("OTC", SS.pit(ROWS, _fx(), _px(), "2026-09-10"), [])
    assert L2["bad"] == 1 and "원문 내용 확인되지 않음" in L2["rules"][-1]["val"]

def test_diff():
    a = dict(ts="2026-10-01T09:00", score=dict(total=37, grade="D"), F=dict(price=1.0, cash=1e6), find=[dict(txt="x", lv="Material")])
    b = dict(ts="2026-10-02T09:00", score=dict(total=41, grade="D"), F=dict(price=1.001, cash=1e6), find=[dict(txt="y", lv="Critical")])
    D = SS.diff(b, a)
    labs = [x[0] for x in D["changes"]]
    assert "점수" in labs and "등급" not in labs and "종가" not in labs     # 0.5% 이하 변화는 무시
    assert [x["txt"] for x in D["new"]] == ["y"] and [x["txt"] for x in D["gone"]] == ["x"]
    assert SS.diff(b, None) is None

def _S():
    return dict(ticker="TEST", ts="2026-10-29T09:00", ident=dict(name="Test Co"), asof=dict(filing="2026-09-01", periodic="2026-08-10"),
                F=dict(px_date="2026-10-28"), score=dict(total=40, grade="D", conf="B", items=[dict(label="근거", pts=5, max=10, why="5/10")]),
                exposure="높음", facts=["사실 1"], find=[dict(lv="Critical", txt="위험", src=dict(form="8-K", filed="2026-09-01"))],
                ledger={}, fd=dict(basic=1e6, practical=None, max=None, missing=["워런트"]), head=dict(ok=False), baby=None, inst=[],
                resist=dict(strikes=[], vp={}), cal=[], listing=dict(tier="Nasdaq", rules=[]), scen=[dict(name="Bull", like="낮음", trigger="a", target="b", invalid="c")],
                exits=["출구"], motive=dict(questions=["질문?"]), gates=[dict(n=1, name="관문", state="부분")], ask=["미확인 (2026-09-01 8-K)"])

def test_copy_text():
    t = SS.copy_text(_S(), "https://example.com/?p=sec&t=TEST")
    assert t.startswith("🔬 TEST") and "📌 핵심 팩트 요약" in t and "❓ 확인 요청" in t
    assert "🔴 결정적 위험 [8-K 2026-09-01]" in t and "확인되지 않음" in t
    assert t.rstrip().endswith("투자 권유 아님")
    for w in ("매수하세요", "매도하세요", "사라", "팔아라"): assert w not in t

def test_js_sanitizes_numpy():
    o = SS._js(dict(a=np.int64(3), b=np.float64(1.5), c=[np.nan]))
    import json; json.dumps(o)
    assert o["a"] == 3 and o["b"] == 1.5

if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"): f(); print("ok", k)
