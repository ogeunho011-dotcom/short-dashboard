"""커뮤니티 성공 사례(트레이더 자기 보고) 급등 직전 상태를 시점 기준(룩어헤드 없음)으로 재구성.
입력: DB(가격·공시·SI·FINRA), /workspace/patt/intra5m.pkl(선택, 이동 시작 세션 판정용)
출력: model/pattern_cases.json"""
import sys, json, re, pickle
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
import numpy as np, pandas as pd
from core import model as M, params as P, db
p = P.load()
REG = M.regime_series()
# (티커, 토스 이름, 이동 시작일(ET), 트레이더 설명)
CASES = [
    ("PFSA", "프로퓨사", "2026-10-22", "리딩 전 초반 진입 기준 2배"),
    ("SHFS", "SHF 홀딩스", "2026-10-21", "약 100원대 → 700원"),
    ("FGL", "파운더 그룹", "2026-10-26", "2,000원 초중반 → +50% (숏커버 이벤트)"),
    ("BRAI", "브레인", "2026-10-27", "4,000원 초중반 → 고점 7,000원"),
    ("FLWS", "1 800 플라워스닷컴", "2026-10-22", "진행 중"),
    ("POM", "팜닥터", "2026-10-21", "+100%"),
    ("SURG", "서지페이스", "2026-10-22", "+20% 이상 진행 중"),
    ("LABT", "레이크우드-아메덱스", "2026-10-23", "+50% (1차)"),
    ("LABT", "레이크우드-아메덱스", "2026-10-28", "+50% (2차)"),
    ("DVLT", "데이터발트 AI", "2026-10-28", "+50%"),
    ("YFOR", "YY포스", "2026-10-21", "+50% (1차)"),
    ("YFOR", "YY포스", "2026-10-23", "+50% (2차)"),
    ("INLF", "인리프", "2026-10-22", "+50% (10-19 -88% 폭락 다음 반등)"),
    ("SNAL", "스네일", "2026-10-21", "진행 중"),
]
try: INTRA = pickle.load(open("/workspace/patt/intra5m.pkl", "rb"))
except Exception: INTRA = {}

def sma_pos(c, n): return float(c.iloc[-1] / c.tail(n).mean() - 1) * 100 if len(c) >= n else None

def pre_state(t, E):
    b = M.Bundle(t, REG); E = pd.Timestamp(E)
    px = b.px[b.px["date"] < E]
    asof = px["date"].iloc[-1]
    f = M.features(b, asof, p) or {}
    s = M.score(f, p) if f else {}
    c, h, l, v = px["close"], px["high"], px["low"], px["volume"]
    r = dict(ticker=t, event=str(E.date()), asof=str(asof.date()), price=float(c.iloc[-1]))
    sh, look = b.shares_asof(asof)
    r["shares_m"] = sh / 1e6 if sh else None; r["shares_lookahead"] = look
    r["mcap_m"] = sh * r["price"] / 1e6 if sh else None
    r["float_m"] = f.get("float_m")
    r["dv20_k"] = float((c * v).tail(20).mean() / 1e3)
    r["ma"] = {n: sma_pos(c, n) for n in (5, 20, 60, 120)}
    r["dd_hi20"] = float(c.iloc[-1] / h.tail(20).max() - 1) * 100
    r["dd_hi60"] = float(c.iloc[-1] / h.tail(60).max() - 1) * 100
    r["ret5"] = float(c.iloc[-1] / c.iloc[-6] - 1) * 100
    r["ret20"] = float(c.iloc[-1] / c.iloc[-21] - 1) * 100
    d1 = c.pct_change() * 100
    r["worst_day10"] = float(d1.tail(10).min()); r["worst_day20"] = float(d1.tail(20).min())
    r["best_day60"] = float(d1.tail(60).max())
    r["vol_dry3"] = float(v.tail(3).mean() / max(v.tail(23).head(20).mean(), 1))
    r["vol_ratio"] = f.get("vol_ratio")
    r["si_float"] = f.get("si_float"); r["dtc"] = f.get("dtc"); r["si_chg"] = f.get("si_chg")
    r["sv_ratio"] = f.get("sv_ratio"); r["fee"] = f.get("fee"); r["avail"] = f.get("avail")
    r["dilution_recent"] = f.get("dilution_recent"); r["reg_pending"] = f.get("reg_pending"); r["def301"] = f.get("def301")
    r["rs_recent"] = f.get("rs_recent"); r["below1"] = r["price"] < 1
    fil = b.fil[(b.fil["filed"] <= asof + pd.Timedelta(days=1)) & (b.fil["filed"] >= asof - pd.Timedelta(days=60))] if len(b.fil) else b.fil
    r["filings60"] = [f"{str(x.filed)[:10]} {x.form}{(' ' + x.items) if isinstance(x.items, str) and x.items else ''}" for x in fil.sort_values("filed").itertuples()][-12:]
    r["forms60"] = sorted(set(fil["form"])) if len(fil) else []
    r["industry"] = (b.info or {}).get("industry"); r["country"] = (b.info or {}).get("country")
    r["score"] = s.get("score"); r["level"] = s.get("level"); r["prob"] = s.get("rprob"); r["flagged"] = s.get("flagged")
    r["on"] = s.get("on")
    r["in_universe"] = bool(p["univ_min_price"] <= r["price"] <= p["univ_max_price"] * 1.5 and r["dv20_k"] >= p["univ_min_dv_k"])
    # 이동 시작 세션 (5분봉, ET)
    x = INTRA.get(t)
    if x is not None and len(x):
        x = x.tz_convert("America/New_York")
        w = x[(x.index.date >= (asof + pd.Timedelta(days=1)).date())]
        trig = w[w["High"] >= r["price"] * 1.2]
        if len(trig):
            ts = trig.index[0]; hm = ts.hour * 60 + ts.minute
            r["move_start"] = ts.strftime("%m-%d %H:%M ET"); r["move_session"] = "프리" if hm < 570 else ("정규" if hm < 960 else "애프터")
            if hm >= 960 and ts.date() == asof.date(): r["move_session"] = "애프터(전날)"
        w5 = w[w.index.date <= (E + pd.Timedelta(days=7)).date()]
        r["max_up_5d"] = float(w5["High"].max() / r["price"] - 1) * 100 if len(w5) else None
        # 전날 애프터 움직임
        ah = x[(x.index.date == asof.date()) & ((x.index.hour * 60 + x.index.minute) >= 960)]
        r["prev_ah_max"] = float(ah["High"].max() / r["price"] - 1) * 100 if len(ah) else None
    return r

if __name__ == "__main__":
    rows = []
    for t, nm, E, desc in CASES:
        try:
            r = pre_state(t, E); r["name_ko"] = nm; r["desc"] = desc; rows.append(r)
            print(t, E, {k: (round(v, 2) if isinstance(v, float) else v) for k, v in r.items() if k not in ("filings60",)}, flush=True)
            print("   ", r["filings60"][-6:])
        except Exception as e:
            import traceback; traceback.print_exc()
    json.dump(rows, open(ROOT / "model/pattern_cases.json", "w"), ensure_ascii=False, indent=1, default=lambda o: None if o is None else (bool(o) if isinstance(o, np.bool_) else float(o)))
