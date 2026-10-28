"""셋업 기반(SHFS 스타일) 성공 정의: 알림 시점까지의 데이터로 숏 차수 구조를 재구성하고,
이후 경로가 '재점화 레벨(최신 차수 상단) 도달'이 '최신 차수 하단(지지) 이탈'보다 먼저인지 채점한다."""
import sys, math
sys.path.insert(0, ".")
import numpy as np, pandas as pd
from core import model, params as P
p = P.load() if hasattr(P, "load") else dict(P.DEFAULTS)
COST = 0.006
_B = {}
REG = None

def bundle(t):
    global REG
    if REG is None: REG = model.regime_series()
    if t not in _B: _B[t] = model.Bundle(t, REG)
    return _B[t]

def setup_at(t, asof, H=10):
    """asof 종가 기준 셋업 + 이후 H거래일 경로 채점. 반환 dict 또는 None."""
    b = bundle(t); asof = pd.Timestamp(asof)
    f = model.features(b, asof, p)
    if not f or "_meta" not in f: return None
    m = f["_meta"]; bz = model.buy_zone(f, m, p)
    if not bz: return None
    s = model.score(f, p)
    price = f["price"]; rl = float(m["reignite"]); stop = float(bz["stop"])
    above = sorted([x["hi"] for x in m["tranches"] if x["hi"] > rl * 1.001])
    ph = float(m["hi21"]) if m["hi21"] > rl * 1.001 else (above[0] if above else float(max(m["hi21"], rl * 1.15)))
    tr = m["tranches"]
    newest = min(tr, key=lambda x: x["age"]) if tr else None
    fut = b.px[b.px["date"] > asof].head(H)
    out = {"ticker": t, "asof": asof, "price": price, "rl": rl, "stop": stop, "ph": ph, "need": rl / price - 1, "risk": stop / price - 1,
           "need_ph": ph / price - 1, "level": int(s["level"]), "score": float(s["score"]), "cp": float(f["cover_pressure"]),
           "loss_pct": float(m["loss_pct"]), "est_days": int(m["est_days"]), "map_days": int(m["days"]), "n_tr": len(tr),
           "newest": newest["name"] if newest else None, "valid": bool(rl > price * 1.005 and stop < price * 0.995), "nfut": len(fut)}
    out.update(score_path(fut, price, rl, stop, ph))
    return out, f, m, bz, s

def score_path(fut, price, rl, stop, ph):
    """보수적 채점: 같은 날 손절·목표 동시 터치면 손절 우선(시가 갭 제외)."""
    res = {"succ": 0, "succ_day": None, "ph_hit": 0, "fail": 0, "fail_day": None, "ret": None}
    if len(fut) == 0: return res
    pos, real, st_ = 1.0, 0.0, stop
    tp1_done = False; done = False
    for i, r in enumerate(fut.itertuples(index=False), 1):
        o, h, l, c = float(r.open), float(r.high), float(r.low), float(r.close)
        # 손절 (갭 하락이면 시가 체결)
        if l <= st_:
            fill = min(o, st_)
            if not tp1_done: res["fail"] = 1; res["fail_day"] = i
            real += pos * (fill / price - 1); pos = 0; done = True; break
        if not tp1_done and h >= rl:
            fill = max(o, rl); tp1_done = True; res["succ"] = 1; res["succ_day"] = i
            real += 0.5 * (fill / price - 1); pos = 0.5; st_ = price  # 본전 스탑
        if tp1_done and h >= ph:
            fill = max(o, ph); res["ph_hit"] = 1
            real += pos * (fill / price - 1); pos = 0; done = True; break
    if not done and pos > 0:
        real += pos * (float(fut["close"].iloc[-1]) / price - 1)
    res["ret"] = real - COST
    res["end_ret"] = float(fut["close"].iloc[-1]) / price - 1
    res["maxup"] = float(fut["high"].max()) / price - 1
    return res
