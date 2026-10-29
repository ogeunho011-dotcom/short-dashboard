"""숏 데이터 기반 급등 탐지 모델.
모든 함수는 asof(기준일) 이전/당일 데이터만 사용한다 (컨닝 모드 배제).
무료 데이터 한계로 '진입 가격', '잔존 수량'은 모두 추정치다."""
import math, json, re, datetime as dt
import numpy as np
import pandas as pd
from . import sources as src, db

SIGNALS = [  # key, 가중치 파라미터, 한국어 이름
    ("vol", "w_vol", "거래량 급증"), ("sv", "w_sv", "공매도비율 급등"), ("si_float", "w_si_float", "유통 대비 숏 과다"),
    ("si_change", "w_si_change", "숏 재축적"), ("loss_side", "w_loss_side", "손실권 숏 우세"), ("reignite", "w_reignite", "재점화 레벨 근접"),
    ("borrow", "w_borrow", "차입 가능 고갈"), ("fee", "w_fee", "대차이자 높음"), ("ftd", "w_ftd", "FTD 급증"),
    ("threshold", "w_threshold", "RegSHO Threshold"), ("coil", "w_coil", "변동성 응축"),
    # --- 급등 잠재력 (일봉·공시로 과거 시점 재현 가능 → 타임머신 검증 대상)
    ("low_float", "w_low_float", "소형 유통주식"), ("float_rot", "w_float_rot", "유통주식 회전"), ("dtc", "w_dtc", "숏 커버 일수 높음"),
    ("gap_hold", "w_gap_hold", "갭상승 유지"), ("breakout", "w_breakout", "신고가 돌파"), ("squeeze_break", "w_squeeze_break", "응축 후 돌파"),
    ("vol_streak", "w_vol_streak", "거래량 연속 증가"), ("close_high", "w_close_high", "고가 마감"), ("ssr", "w_ssr", "전일 SSR 발동"),
    ("runner", "w_runner", "과거 급등 이력"), ("halt_hist", "w_halt_hist", "급등 정지 이력(추정)"), ("catalyst", "w_catalyst", "최근 8-K/공시"),
    ("insider_buy", "w_insider_buy", "내부자 매수"), ("earnings_soon", "w_earnings_soon", "실적 발표 임박(추정)"),
    ("offering_done", "w_offering_done", "증자 완료(물량 해소)"), ("rs_lowfloat", "w_rs_lowfloat", "역분할+소형 유통"),
    ("round_reclaim", "w_round_reclaim", "$1·라운드 넘버 회복"), ("theme", "w_theme", "핫 테마 업종"), ("low_inst", "w_low_inst", "기관 보유 낮음"),
    # --- 라이브 전용 (과거 재현 불가 → 검증 안 됨, 가중치 낮게)
    ("pm_gap", "w_pm_gap", "프리마켓 갭·거래량"), ("ah_move", "w_ah_move", "시간외 급등"), ("vwap_reclaim", "w_vwap_reclaim", "VWAP 회복"),
    ("options_calls", "w_options_calls", "콜옵션 이상 거래"), ("sympathy", "w_sympathy", "동종 업종 급등 동조"),
]
LIVE_ONLY = {"pm_gap", "ah_move", "vwap_reclaim", "options_calls", "sympathy"}
HOT_THEME = r"biotech|pharma|drug|biolog|diagnost|medical|genetic|software|semiconductor|artificial|\bai\b|computer|crypto|blockchain|bitcoin|quantum|nuclear|uranium|drone|aerospace|defense|space|electric|battery|solar|cannabis"
SIG_NAME = {k: n for k, _, n in SIGNALS}

# ---------------------------------------------------------------- 데이터 묶음
class Bundle:
    """한 종목의 전체 이력 (한 번만 로드). asof 로 잘라 쓴다."""
    def __init__(self, ticker, regime=None):
        self.t = ticker
        self.px = src.get_prices(ticker)
        self.sv = src.get_short_vol(ticker)
        self.si = src.get_short_interest(ticker)
        self.ftd = src.get_ftd(ticker)
        self.fil = src.get_filings(ticker)
        self.bor = src.get_borrow(ticker)
        th = db.q("SELECT date FROM threshold WHERE ticker=?", (ticker,))
        self.thr = pd.to_datetime(th["date"]) if len(th) else pd.Series([], dtype="datetime64[ns]")
        self.info = db.kv_get(f"info:{ticker}") or {}
        self.facts = db.kv_get(f"facts:{ticker}") or {}
        self.f4 = db.kv_get(f"form4:{ticker}")
        self.regime = regime

    def shares_asof(self, asof):
        """SEC 공시 기준 발행주식수 (공시일 <= asof). 없으면 현재 floatShares (룩어헤드 주의 플래그)."""
        s = [x for x in self.facts.get("shares", []) if x.get("filed") and x.get("val") and pd.Timestamp(x["filed"]) <= asof
             and pd.Timestamp(x["filed"]) >= asof - pd.Timedelta(days=400)]
        if s:
            s.sort(key=lambda x: (x["filed"], x["end"]))
            return float(s[-1]["val"]), False
        fl = self.info.get("floatShares") or self.info.get("sharesOutstanding")
        return (float(fl), True) if fl else (None, True)

def regime_series():
    """QQQ / IWM 추세 → 날짜별 시장 국면 (1 강세, 0 중립, -1 약세)."""
    out = {}
    for t in ("QQQ", "IWM"):
        px = src.get_prices(t)
        if len(px) == 0:
            src.fetch_prices(t, "3y"); px = src.get_prices(t)
        if len(px) == 0: continue
        s = px.set_index("date")["close"]
        ok = (s > s.rolling(50).mean()) & (s.pct_change(20) > 0)
        out[t] = ok.astype(int)
    if not out: return None
    df = pd.DataFrame(out).ffill().fillna(1)
    return (df.sum(axis=1) - 1).clip(-1, 1)   # 둘다 OK=1, 하나=0, 둘다 X=-1

# ---------------------------------------------------------------- 기술 지표
def rsi(s, n=14):
    d = s.diff(); up = d.clip(lower=0).ewm(alpha=1 / n).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1 / n).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))

def technicals(px):
    c = px["close"]; out = {}
    if len(px) < 21: return out
    ma = c.rolling(20).mean(); sd = c.rolling(20).std()
    bbw = (4 * sd / ma)
    out["rsi"] = float(rsi(c).iloc[-1])
    out["bb_pctb"] = float(((c - (ma - 2 * sd)) / (4 * sd)).iloc[-1])
    out["bbw_pctile"] = float((bbw.rank(pct=True).iloc[-1]) * 100) if bbw.notna().sum() > 30 else 50.0
    tp = (px["high"] + px["low"] + px["close"]) / 3
    out["vwap20"] = float((tp * px["volume"]).tail(20).sum() / max(px["volume"].tail(20).sum(), 1))
    rng = (px["high"] - px["low"]).replace(0, np.nan)
    clv = (((px["close"] - px["low"]) - (px["high"] - px["close"])) / rng).fillna(0)
    out["pressure"] = float((clv * px["volume"]).tail(5).sum() / max(px["volume"].tail(5).sum(), 1))  # -1 매도 ~ +1 매수
    return out

# ---------------------------------------------------------------- 진입 구간 맵
def vol_ratio(v, p=None):
    """당일 거래량 ÷ 기준 거래량. 기준 = max(20일 중앙값, 20일 평균×0.5, 하한) → 거래 없던 종목의 극단 배수 방지, 최대 50배."""
    v = np.asarray(v, dtype=float)
    if len(v) < 6: return 0.0
    w = v[-21:-1]
    base = max(float(np.median(w)), float(w.mean()) * 0.5, float((p or {}).get("vol_base_floor", 20000)))
    return float(min(v[-1] / base, 50.0)) if base > 0 else 0.0

def nice_width(lo, hi, price):
    span = max(hi - lo, price * 0.2, 0.01)
    raw = span / 25
    for w in (0.005, 0.01, 0.02, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 25):
        if raw <= w: return w
    return 50.0

def entry_map(b: Bundle, asof, p, si_est=None):
    """일별 공매도 거래량 × 당일 가격대 분포 → 가격 밴드별 숏 유입 추정, 이후 커버(감소) 시뮬레이션.
    반환: bands DataFrame, meta dict"""
    px = b.px[b.px["date"] <= asof].tail(int(p["map_lookback"]))
    if len(px) < 5: return pd.DataFrame(), {}
    sv = b.sv[b.sv["date"] <= asof].set_index("date") if len(b.sv) else pd.DataFrame()
    price = float(px["close"].iloc[-1])
    lo, hi = float(px["low"].min()), float(px["high"].max())
    w = float(p["band_width"]) or nice_width(lo, hi, price)
    edges = np.arange(math.floor(lo / w) * w, hi + w * 1.0001, w)
    if len(edges) > 400:  # 안전장치
        w = (hi - lo) / 300; edges = np.arange(lo, hi + w, w)
    mids = (edges[:-1] + edges[1:]) / 2
    nb = len(mids)
    init = np.zeros(nb); rem = np.zeros(nb); wdate = np.zeros(nb); est_days = 0
    dates = list(px["date"])
    for i, r in enumerate(px.itertuples(index=False)):
        if len(sv) and r.date in sv.index:
            s_v = float(sv.loc[r.date, "short_vol"]) if np.ndim(sv.loc[r.date, "short_vol"]) == 0 else float(sv.loc[r.date, "short_vol"].iloc[-1])
        else:
            s_v = float(r.volume) * float(p["default_short_ratio"]); est_days += 1
        # 커버 (기존 재고 감소): 당일 고가가 밴드 위로 가면 손실권 → 추가 커버
        if i > 0:
            vol_ratio = min(3.0, float(r.volume) / max(float(px["volume"].iloc[max(0, i - 20):i].median() or 1), 1))
            loss = (r.high > edges[1:])  # 밴드 상단 위로 거래됨 → 그 밴드 숏은 손실
            cov = np.where(loss, float(p["base_cover"]) + float(p["squeeze_cover"]) * vol_ratio, float(p["base_cover"]))
            rem *= (1 - np.clip(cov, 0, 0.9))
        # 신규 유입: 당일 가격 범위에 전형가격 중심 분포
        tp = (r.high + r.low + r.close) / 3; sig = max((r.high - r.low) / 4, w / 2)
        wts = np.exp(-0.5 * ((mids - tp) / sig) ** 2) * ((mids >= r.low - w / 2) & (mids <= r.high + w / 2))
        if wts.sum() <= 0:
            wts = np.zeros(nb); wts[np.clip(np.searchsorted(edges, tp) - 1, 0, nb - 1)] = 1
        add = s_v * wts / wts.sum()
        init += add; rem += add; wdate += add * i
    # 스케일: 잔존 합계를 추정 숏 잔고(SI)에 맞춤
    raw_rem = rem.sum()
    if si_est and raw_rem > 0:
        k = si_est / raw_rem
    else:
        k = float(p["retention"])
    init *= k; rem *= k
    avg_idx = np.where(init > 0, wdate * k / np.maximum(init, 1e-9), 0)
    df = pd.DataFrame({"lo": edges[:-1], "hi": edges[1:], "mid": mids, "init": init, "rem": rem})
    df["rem_ratio"] = np.where(df["init"] > 0, df["rem"] / df["init"], 0)
    df["pl_pct"] = (df["mid"] - price) / df["mid"] * 100   # 숏 관점 손익 (+ 수익 / - 손실)
    df["side"] = np.where(df["mid"] > price, "profit", "loss")
    df["age_days"] = len(px) - 1 - avg_idx
    meta = {"price": price, "width": w, "est_days": est_days, "days": len(px), "scaled_to_si": bool(si_est),
            "total_rem": float(rem.sum()), "hi21": float(px["high"].tail(21).max()), "lo21": float(px["low"].tail(21).min()),
            "day_hi": float(px["high"].iloc[-1]), "day_lo": float(px["low"].iloc[-1]), "close": price}
    tot = df["rem"].sum()
    meta["loss_pct"] = float(df.loc[df.side == "loss", "rem"].sum() / tot * 100) if tot > 0 else 0
    meta["profit_pct"] = 100 - meta["loss_pct"] if tot > 0 else 0
    tr = tranches(df, price, meta)
    meta["tranches"] = tr
    meta["reignite"] = reignite_level(tr, price, meta)
    meta["gaps"] = gaps(df, price)
    return df, meta

def tranches(df, price, meta):
    """밴드를 연속된 물량 덩어리(차수)로 묶는다. 1차=가장 오래된 진입."""
    if len(df) == 0: return []
    thr = df["init"].max() * 0.04
    active = df["init"] > thr
    groups, cur = [], []
    for i, a in enumerate(active):
        if a: cur.append(i)
        elif cur: groups.append(cur); cur = []
    if cur: groups.append(cur)
    # 가격 폭이 너무 넓은 덩어리는 가장 얇은 지점(매물 골)에서 분할
    def split(g):
        if len(g) < 4: return [g]
        lo_, hi_ = df.loc[g[0], "lo"], df.loc[g[-1], "hi"]
        if (hi_ - lo_) / max(lo_, 1e-6) <= 0.25: return [g]
        inner = df.loc[g[1:-1], "init"]
        cut = int(inner.idxmin())
        return split([i for i in g if i < cut]) + split([i for i in g if i >= cut])
    groups = [x for g in groups for x in split(g) if x]
    # 너무 잘게 쪼개지면 이웃끼리 병합 (최대 6개)
    while len(groups) > 6:
        sizes = [df.loc[g, "init"].sum() for g in groups]
        j = int(np.argmin(sizes)); k = j - 1 if j > 0 and (j == len(groups) - 1 or sizes[j - 1] < sizes[j + 1]) else j + 1
        a, b_ = sorted([j, k]); groups[a] = list(range(groups[a][0], groups[b_][-1] + 1)); del groups[b_]
    # 큰 덩어리는 가격 중앙에서 다시 분리 (차수 구분 가독성)
    out = []
    for g in groups:
        sub = df.loc[g]
        init, rem = float(sub["init"].sum()), float(sub["rem"].sum())
        age = float((sub["age_days"] * sub["init"]).sum() / max(init, 1e-9))
        ratio = rem / init if init > 0 else 0
        tag = "신규" if age <= 21 and ratio > 0.5 else ("청산" if ratio < 0.10 else ("커버 소진" if ratio < 0.30 else ""))
        out.append({"lo": float(sub["lo"].min()), "hi": float(sub["hi"].max()), "init": init, "rem": rem, "ratio": ratio,
                    "age": age, "tag": tag, "idx": g, "side": "profit" if sub["mid"].mean() > price else ("loss" if sub["hi"].max() < price else "mixed")})
    order = sorted(range(len(out)), key=lambda i: -out[i]["age"])
    for n, i in enumerate(order, 1): out[i]["name"] = f"{n}차 숏"
    total = sum(x["rem"] for x in out) or 1
    for x in out: x["share_pct"] = x["rem"] / total * 100
    return sorted(out, key=lambda x: -x["hi"])

def reignite_level(tr, price, meta):
    """현재가를 포함/바로 위 물량 덩어리의 상단: 돌파 시 해당 차수 전량이 손실권 전환."""
    cands = [x for x in tr if x["hi"] > price and x["rem"] > 0.03 * max(meta["total_rem"], 1)]
    if not cands: return float(meta["hi21"])
    x = min(cands, key=lambda x: x["hi"])
    return float(x["hi"])

def gaps(df, price):
    if len(df) == 0: return []
    thr = df["init"].max() * 0.04
    out, start = [], None
    for i, r in df.iterrows():
        if r["init"] <= thr:
            start = r["lo"] if start is None else start
        elif start is not None:
            out.append((float(start), float(r["lo"]))); start = None
    return [g for g in out if g[1] - g[0] > 0]

# ---------------------------------------------------------------- SI 추정
def si_asof(b: Bundle, asof):
    si = b.si[b.si["publish_date"] <= asof] if len(b.si) else b.si
    if len(si) == 0: return None
    last = si.iloc[-1]; prev = si.iloc[-2] if len(si) > 1 else None
    out = {"si": float(last["si"]), "settle": last["settle_date"], "dtc": float(last["dtc"] or 0),
           "chg_pct": (float(last["si"]) / float(prev["si"]) - 1) * 100 if prev is not None and prev["si"] else 0.0,
           "prev": float(prev["si"]) if prev is not None else None}
    # 결제일 이후 공매도 거래 비율 변화로 현재 잔고 추정 (FINRA 데이터 있을 때만)
    est = out["si"]
    if len(b.sv):
        sv = b.sv[(b.sv["date"] <= asof)]
        after = sv[sv["date"] > last["settle_date"]]; before = sv[(sv["date"] <= last["settle_date"])].tail(10)
        if len(after) >= 2 and len(before) >= 5:
            r_a = after["short_vol"].sum() / max(after["total_vol"].sum(), 1); r_b = before["short_vol"].sum() / max(before["total_vol"].sum(), 1)
            est = out["si"] * (1 + float(np.clip((r_a / max(r_b, 1e-6) - 1) * 0.5, -0.5, 0.5)))
    out["est"] = est
    return out

# ---------------------------------------------------------------- 특징량 & 점수
def features(b: Bundle, asof, p, with_map=True):
    asof = pd.Timestamp(asof)
    px = b.px[b.px["date"] <= asof]
    if len(px) < 25: return None
    c = px["close"]; v = px["volume"]
    f = {"date": asof.strftime("%Y-%m-%d"), "price": float(c.iloc[-1]), "chg1": float(c.pct_change().iloc[-1] * 100),
         "ret5": float((c.iloc[-1] / c.iloc[-6] - 1) * 100) if len(c) > 6 else 0}
    f["vol_ratio"] = vol_ratio(v, p)
    f["dollar_vol20"] = float((c * v).tail(20).mean())
    f.update(technicals(px))
    # FINRA 공매도 비율
    sv = b.sv[b.sv["date"] <= asof] if len(b.sv) else b.sv
    f["has_finra"] = bool(len(sv) >= 10 and sv["date"].iloc[-1] >= px["date"].iloc[-1] - pd.Timedelta(days=5))
    if f["has_finra"]:
        ratio = sv["short_vol"] / sv["total_vol"].replace(0, np.nan)
        f["sv_ratio"] = float(ratio.iloc[-1] * 100)
        sd = ratio.iloc[-21:-1].std()
        f["sv_z"] = float((ratio.iloc[-1] - ratio.iloc[-21:-1].mean()) / sd) if sd and sd > 0 else 0
    # SI
    si = si_asof(b, asof)
    shares, fl_look = b.shares_asof(asof)
    f["float_lookahead"] = fl_look
    if si:
        f["si"] = si["si"]; f["si_est"] = si["est"]; f["si_chg"] = si["chg_pct"]; f["dtc"] = si["dtc"]
        f["si_float"] = si["est"] / shares * 100 if shares else None
        f["si_float_prev"] = si["prev"] / shares * 100 if shares and si.get("prev") else None
        f["si_settle"] = str(si["settle"])[:10]
    # 차입
    bor = b.bor[b.bor["ts"] <= asof + pd.Timedelta(hours=23)] if len(b.bor) else b.bor
    if len(bor):
        last = bor.iloc[-1]; f["avail"] = float(last["available"]); f["fee"] = float(last["fee"])
        f["borrow_ts"] = str(last["ts"])[:16]; f["borrow_days"] = int(bor["ts"].dt.date.nunique())
        pd_ = bor[bor["ts"].dt.date < last["ts"].date()]
        if len(pd_): f["fee_prev"] = float(pd_.iloc[-1]["fee"]); f["avail_prev"] = float(pd_.iloc[-1]["available"])
        old = bor[bor["ts"] <= bor["ts"].iloc[-1] - pd.Timedelta(days=5)]
        if len(old):
            f["avail_chg"] = (f["avail"] / max(float(old.iloc[-1]["available"]), 1) - 1) * 100
            f["fee_chg"] = f["fee"] - float(old.iloc[-1]["fee"])
            f["fee_accel"] = f["fee_chg"] - (float(old.iloc[-1]["fee"]) - float(bor[bor["ts"] <= old["ts"].iloc[-1] - pd.Timedelta(days=5)]["fee"].iloc[-1])) if len(bor[bor["ts"] <= old["ts"].iloc[-1] - pd.Timedelta(days=5)]) else 0
    # FTD (공개 지연 반영)
    ftd = b.ftd[b.ftd["publish_date"] <= asof] if len(b.ftd) else b.ftd
    if len(ftd) >= 3:
        f["ftd_last"] = float(ftd["qty"].iloc[-1]); med_f = float(ftd["qty"].tail(20).median() or 0)
        f["ftd_mult"] = f["ftd_last"] / med_f if med_f > 0 else (5.0 if f["ftd_last"] > 0 else 0)
    f["threshold"] = bool(len(b.thr) and ((b.thr <= asof) & (b.thr >= asof - pd.Timedelta(days=7))).any())
    # 공시(희석)
    fil = b.fil[b.fil["filed"] <= asof] if len(b.fil) else b.fil
    f["dilution_recent"] = bool(len(fil) and fil[(fil["filed"] >= asof - pd.Timedelta(days=45)) & fil["form"].str.match(r"^(S-1|S-3|F-1|F-3|424B)")].shape[0] > 0)
    try:
        rs = reg_status(b.fil, asof + pd.Timedelta(days=1))   # asof 당일 제출분까지 (라이브는 장후 공시도 반영)
        f["reg_pending"], f["reg_effect"], f["def301"] = rs["pending"], rs["effect"], rs["def301"]
        f["reg_last"] = str(rs["reg_last"].date()) if rs["reg_last"] is not None else None
        f["def301_date"] = str(rs["def_date"].date()) if rs["def_date"] is not None else None
    except Exception: pass
    # 시장 국면
    if b.regime is not None and len(b.regime):
        rg = b.regime[b.regime.index <= asof]
        f["regime"] = int(rg.iloc[-1]) if len(rg) else 1
    else:
        f["regime"] = 1
    # 진입 구간 맵
    if with_map:
        bands, meta = entry_map(b, asof, p, si_est=f.get("si_est"))
        if meta:
            f["loss_pct"] = meta["loss_pct"]; f["reignite"] = meta["reignite"]
            f["reignite_reach"] = f["price"] / meta["reignite"] if meta["reignite"] else 0
            f["_bands"], f["_meta"] = bands, meta
    # 숏 커버 압력 지수 (0-100)
    comp = [min(f.get("loss_pct", 0) / 100, 1) * 40, min(f.get("dtc", 0) / 10, 1) * 20,
            (20 if f.get("avail") is not None and f["avail"] < p["avail_low"] else 0) + (0 if f.get("fee") is None else min(f["fee"] / 100, 1) * 0),
            min(max(f.get("reignite_reach", 0) - 0.7, 0) / 0.3, 1) * 20]
    f["cover_pressure"] = float(sum(comp))
    f.update(spike_feats(b, px, asof, shares, fil, p))
    return f

def spike_feats(b, px, asof, shares, fil, p):
    """급등 잠재력 조건 (모두 asof 시점까지의 데이터만 사용)."""
    o = {}
    c, h, l, op, v = (px[k].values.astype(float) for k in ("close", "high", "low", "open", "volume"))
    o["float_m"] = shares / 1e6 if shares else None
    if shares:
        o["float_rot"] = float(v[-1] / shares)                       # 당일 거래량 ÷ 유통주식
    gap = op[-1] / c[-2] - 1 if c[-2] > 0 else 0
    o["gap"] = float(gap * 100); o["gap_hold"] = bool(gap >= 0.08 and c[-1] >= op[-1])
    o["gap_fade"] = bool(gap >= 0.08 and c[-1] < op[-1])
    o["brk20"] = bool(c[-1] > h[-21:-1].max()); o["brk52"] = bool(len(h) > 60 and c[-1] > h[-253:-1].max())
    rng10 = h[-11:-1].max() / max(l[-11:-1].min(), 1e-9) - 1
    o["squeeze_break"] = bool(rng10 < 0.30 and c[-1] > h[-11:-1].max())
    o["vol_streak"] = int(next((i for i in range(1, 8) if not (v[-i] > v[-i - 1])), 8) - 1) if len(v) > 9 else 0
    o["close_pos"] = float((c[-1] - l[-1]) / (h[-1] - l[-1])) if h[-1] > l[-1] else 0.5
    o["day_range"] = float(h[-1] / l[-1] - 1) if l[-1] > 0 else 0
    o["ssr"] = bool(len(c) > 3 and l[-2] <= c[-3] * 0.9)               # 전일 저가가 전전일 종가 대비 -10% → 당일 SSR
    pc = np.r_[np.nan, c[:-1]]; up = h / pc - 1
    o["runner_n"] = int(np.nansum(up[-251:-1] >= 0.5))                 # 1년 내 장중 +50% 날 수
    o["halt_n"] = int(np.nansum(up[-61:-1] >= 0.35))                  # 60일 내 +35% 이상 (LULD 정지 가능성 추정)
    if len(fil):
        rec = fil[fil["filed"] >= asof - pd.Timedelta(days=3)]
        o["catalyst"] = bool(rec["form"].isin(["8-K", "6-K", "8-K/A"]).any())
        per = fil[fil["form"].isin(["10-Q", "10-K", "20-F", "10-K/A"])]
        if len(per):
            nxt = per["filed"].max() + pd.Timedelta(days=91)            # 다음 분기 공시 추정
            o["earn_days"] = int((nxt - asof).days)
        off = fil[fil["form"].str.match(r"^424B", na=False) & (fil["filed"] >= asof - pd.Timedelta(days=30)) & (fil["filed"] <= asof - pd.Timedelta(days=3))]
        reg = fil[fil["form"].str.match(r"^(S-1|S-3|F-1|F-3)", na=False) & (fil["filed"] >= asof - pd.Timedelta(days=10))]
        o["offering_done"] = bool(len(off) and not len(reg))
    f4 = [x for x in (b.f4 or []) if x.get("filed") and asof - pd.Timedelta(days=30) <= pd.Timestamp(x["filed"]) <= asof]
    if b.f4 is not None and len(b.f4): o["insider_buy"] = bool(any(x.get("code") == "P" and x.get("shares", 0) > 0 and not x.get("bad") for x in f4))
    sp = [(pd.Timestamp(d), r) for d, r in (b.info.get("splits") or []) if r and r < 1]
    o["rs_recent"] = bool(any(asof - pd.Timedelta(days=120) <= d <= asof for d, r in sp))
    rnd = [r for r in (1, 2, 3, 5, 10) if c[-2] < r <= c[-1]]
    o["round_reclaim"] = rnd[0] if rnd else None
    ind = f"{b.info.get('industry') or ''} {b.info.get('sector') or ''} {b.info.get('longName') or ''}"
    o["theme"] = bool(re.search(HOT_THEME, ind, re.I)) if ind.strip() else None
    inst = b.info.get("heldPercentInstitutions")
    o["inst_pct"] = float(inst) * 100 if inst is not None else None
    return o

def live_feats(info, intraday_df=None, hot_industries=None):
    """라이브 전용 조건: 프리/시간외 등락, VWAP 회복, 동조 (과거 시점 재현 불가)."""
    o = {}
    pm = info.get("preMarketChangePercent"); ah = info.get("postMarketChangePercent")
    if pm is not None: o["pm_chg"] = float(pm) * (100 if abs(pm) < 3 else 1)
    if ah is not None: o["ah_chg"] = float(ah) * (100 if abs(ah) < 3 else 1)
    if intraday_df is not None and len(intraday_df) > 30 and "ts" in intraday_df:
        d = intraday_df[intraday_df["ts"].dt.date == intraday_df["ts"].iloc[-1].date()]
        if len(d) > 15:
            tp = (d["high"] + d["low"] + d["close"]) / 3
            vw = (tp * d["volume"]).cumsum() / d["volume"].cumsum().replace(0, np.nan)
            below = bool((d["close"] < vw).iloc[:-5].any()); now_above = bool((d["close"].iloc[-3:] > vw.iloc[-3:]).all())
            o["vwap_reclaim"] = bool(below and now_above)
    if hot_industries is not None:
        o["sympathy"] = bool(info.get("industry") and info.get("industry") in hot_industries)
    return o

def signals(f, p):
    s = {}
    s["vol"] = min(max((f.get("vol_ratio", 0) - 1) / (p["vol_mult"] - 1), 0), 1.5) if f.get("vol_ratio") else 0
    s["sv"] = min(max(f["sv_z"] / p["sv_z"], 0), 1.5) if "sv_z" in f else None
    s["si_float"] = min(f["si_float"] / p["si_float_pct"], 1.5) if f.get("si_float") is not None else None
    s["si_change"] = min(max(f["si_chg"] / p["si_change_pct"], 0), 1.5) if "si_chg" in f else None
    s["loss_side"] = min(max((f["loss_pct"] - 20) / (p["loss_side_pct"] - 20), 0), 1.5) if "loss_pct" in f else None
    s["reignite"] = min(max((f["reignite_reach"] - 0.6) / (p["reignite_near"] - 0.6), 0), 1.5) if f.get("reignite_reach") else None
    if f.get("avail") is not None:
        s["borrow"] = 1.0 if f["avail"] < p["avail_low"] else (min(max(-f.get("avail_chg", 0) / 50, 0), 1))
    else:
        s["borrow"] = None
    s["fee"] = min(f["fee"] / p["fee_pct"], 1.5) if f.get("fee") is not None else None
    s["ftd"] = min(max((f["ftd_mult"] - 1) / 2, 0), 1.5) if "ftd_mult" in f else None
    s["threshold"] = 1.0 if f.get("threshold") else 0.0
    s["coil"] = 1.0 if f.get("bbw_pctile", 50) <= p["bbw_pctile"] else 0.0
    fm = f.get("float_m")
    s["low_float"] = (min(max((p["low_float_m"] * 2 - fm) / p["low_float_m"], 0), 1.5) if fm is not None else None)
    s["float_rot"] = min(f["float_rot"] / p["float_rot_x"], 1.5) if f.get("float_rot") is not None else None
    s["dtc"] = min(f["dtc"] / p["dtc_days"], 1.5) if f.get("dtc") is not None else None
    s["gap_hold"] = 1.0 if f.get("gap_hold") else (0.3 if f.get("gap_fade") else 0.0)
    s["breakout"] = 1.2 if f.get("brk52") else (1.0 if f.get("brk20") else 0.0)
    s["squeeze_break"] = 1.0 if f.get("squeeze_break") else 0.0
    s["vol_streak"] = min(f.get("vol_streak", 0) / 3, 1.5)
    s["close_high"] = 1.0 if f.get("close_pos", 0) >= 0.85 and f.get("day_range", 0) >= 0.05 else 0.0
    s["ssr"] = 1.0 if f.get("ssr") else 0.0
    s["runner"] = min(f.get("runner_n", 0) / 2, 1.5)
    s["halt_hist"] = min(f.get("halt_n", 0) / 1, 1.5)
    s["catalyst"] = (1.0 if f.get("catalyst") else 0.0) if "catalyst" in f else None
    s["insider_buy"] = (1.0 if f.get("insider_buy") else 0.0) if "insider_buy" in f else None
    s["earnings_soon"] = (1.0 if 0 <= f["earn_days"] <= 10 else 0.0) if f.get("earn_days") is not None else None
    s["offering_done"] = (1.0 if f.get("offering_done") else 0.0) if "offering_done" in f else None
    s["rs_lowfloat"] = 1.0 if f.get("rs_recent") and (fm or 1e9) < p["low_float_m"] else 0.0
    s["round_reclaim"] = 1.0 if f.get("round_reclaim") else 0.0
    s["theme"] = (1.0 if f["theme"] else 0.0) if f.get("theme") is not None else None
    s["low_inst"] = (1.0 if f["inst_pct"] < p["low_inst_pct"] else 0.0) if f.get("inst_pct") is not None else None
    # 라이브 전용
    pm = f.get("pm_chg"); s["pm_gap"] = min(max(pm / 10, 0), 1.5) if pm is not None and f.get("_live") else None
    ah = f.get("ah_chg"); s["ah_move"] = min(max(ah / 10, 0), 1.5) if ah is not None and f.get("_live") else None
    s["vwap_reclaim"] = (1.0 if f.get("vwap_reclaim") else 0.0) if "vwap_reclaim" in f else None
    s["options_calls"] = min(f["call_vol_oi"] / 2, 1.5) if f.get("call_vol_oi") is not None else None
    s["sympathy"] = (1.0 if f.get("sympathy") else 0.0) if "sympathy" in f else None
    return s

def score(f, p):
    s = signals(f, p)
    num = den = 0.0; on = []
    for k, wk, name in SIGNALS:
        if s.get(k) is None: continue
        if s[k] >= 1.0: on.append(k)
        if k in ("borrow", "fee"): continue      # 대차 데이터는 과거 이력이 없어 미검증 → 가중평균에서 빼고 아래 보정점(±2)으로만 반영
        w = float(p[wk]); num += w * min(s[k], 1.0); den += w
    sc = num / den * 100 if den else 0
    if f.get("dilution_recent"): sc *= (1 - p["dilution_penalty"])
    try: sr = short_read(f)
    except Exception: sr = {"lines": [], "brief": [], "adj": 0, "why": []}
    if f.get("reg_pending"):   # scripts/offering_study.py: 가격 미정 S-1/F-1 대기 성공률 34.1%(n=1992) vs 36.9%, 5개 구간 +4/−3/+3/−10/−7%p → 효과 작음·−2만
        sr = dict(sr, adj=float(sr.get("adj") or 0) - 2, why=list(sr.get("why") or []) + ["가격 미정 공모 서류(S-1/F-1) 대기: 공모 물량 대기 중이라 과거 성공률 낮음 −2 (효과 작음)"])
    sc = max(0.0, sc + float(sr.get("adj") or 0))
    thr = p["flag_score"] + (p["regime_adj"] if f.get("regime", 1) < 0 else (p["regime_adj"] / 2 if f.get("regime", 1) == 0 else 0))
    level = 1 + sum(sc >= x for x in (25, 40, 55, 70))
    conf = len([k for k in on if k not in ("coil", "theme", "low_inst", "low_float")])
    legacy = bool(sc >= thr and conf >= p["min_confluence"])
    try: rp = research_predict(s, f)
    except Exception: rp = None
    return {"short": sr, "score": round(sc, 1), "level": int(level), "confluence": conf, "on": on, "signals": s,
            "flagged": rp["flag"] if rp else legacy, "flag_legacy": legacy, "rprob": rp["prob"] * 100 if rp else None, "research": rp,
            "threshold_used": thr, "available": [k for k in s if s[k] is not None]}

# ---------------------------------------------------------------- 공매도 잔고 · 대차 쉬운 말 요약 + 종합점수 보정
def kn(v):
    """1.2만 / 3.4억 식 한국어 숫자."""
    v = float(v or 0)
    if v >= 1e8: return f"{v / 1e8:.1f}억".replace(".0억", "억")
    if v >= 1e4: return f"{v / 1e4:.1f}만".replace(".0만", "만")
    return f"{v:,.0f}"

def short_read(f):
    """공매도 잔고(FINRA, 월 2회)·대차이자/빌릴 수 있는 주식(IBKR, 하루 여러 번) 쉬운 말 + 종합점수 보정점.
    보정 근거 (scripts/short_borrow_study.py, model/short_study.json):
      · 유통 대비 숏 30%+ 또는 숏 잔고 20%+ 감소 → 과거 5개 학습구간 모두 성공률 7~9%p 낮음 → -3점 (검증됨, 효과 작음)
      · 대차이자/빌릴 주식: 무료 과거 이력이 없어 검증 불가 → ±2점 '참고' (데이터가 쌓이면 재검증)"""
    L, why, adj, B = [], [], 0.0, []
    sf, sfp, sc, dtc = f.get("si_float"), f.get("si_float_prev"), f.get("si_chg"), f.get("dtc")
    if sf is not None:
        tag = "적음" if sf < 5 else "보통" if sf < 15 else "많음" if sf < 30 else "매우 많음·과밀"
        t = f"공매도 잔고 유통주의 {sf:.1f}% ({tag})" if sf < 10 else f"공매도 잔고 유통주의 {sf:.0f}% ({tag})"
        if sfp is not None: t += f", 지난번 대비 {sf - sfp:+.1f}%p"
        L.append(t); B.append(t)
    elif f.get("si"):
        L.append(f"공매도 잔고 {kn(f['si'])}주 (유통주식 수 확인 안 됨)")
    if sc is not None and f.get("si"):
        hint = " — 숏이 빠지는 중" if sc <= -20 else " — 숏이 쌓이는 중" if sc >= 20 else ""
        L.append(f"공매도 잔고 지난 공표 대비 {sc:+.0f}%{hint}" + (f" (결제일 {f['si_settle'][5:].replace('-', '/')})" if f.get("si_settle") else ""))
    if dtc:
        L.append(f"숏이 다 갚는 데 {dtc:.1f}일치 거래량 필요" + (" (길수록 탈출 어려움)" if dtc >= 3 else ""))
    fee, av = f.get("fee"), f.get("avail")
    if fee is not None:
        lv = "싼 편" if fee < 5 else "보통" if fee < 30 else "비쌈" if fee < 100 else "매우 비쌈"
        fs = (lambda v: f"{v:.0f}%" if v >= 10 else f"{v:.1f}%" if v >= 1 else f"{v:.2f}%")
        t = f"대차이자 연 {fs(fee)} ({lv}, 비쌀수록 숏 보유 부담 ↑)"
        if f.get("fee_prev") is not None and abs(fee - f["fee_prev"]) >= 0.5: t += f", 전일 {fs(f['fee_prev'])}"
        L.append(t); B.append(t)
    if av is not None:
        d = "없음 — 새로 숏 치기 어려움" if av <= 0 else "거의 없음" if av < 1e4 else "적음" if av < 5e4 else "넉넉" if av >= 5e5 else "보통"
        t = f"빌릴 수 있는 주식 {'1천만주 이상' if av >= 1e7 else kn(av) + '주'} ({d})"
        if f.get("avail_prev") is not None and f["avail_prev"] > 0 and abs(av / f["avail_prev"] - 1) >= 0.2:
            t += f", 전일 {kn(f['avail_prev'])}주"
        L.append(t); B.append(t)
    # --- 보정점
    if (sf is not None and sf >= 30) or (sc is not None and f.get("si") and sc <= -20):
        adj -= 3; why.append("숏 과밀(유통 30%+) 또는 숏 이탈(-20%↓): 과거 성공률 낮음 −3")
    if fee is not None and av is not None:
        r5 = f.get("ret5") or 0
        if fee >= 50 and (f.get("dilution_recent") or r5 <= -15):
            adj -= 2; why.append("대차이자 매우 비싼데 증자·급락 중: 숏이 확신하는 하락주일 수 있음 −2 (참고·검증 전)")
        elif fee >= 30 and av < 5e4 and (sc is None or sc >= 0) and r5 > 0:
            adj += 2; why.append("대차 비싸고 빌릴 주식 거의 없음 + 숏 유지/증가 + 주가 상승: 숏 압박 +2 (참고·검증 전)")
    if not B and L: B = L[:1]
    return {"lines": L, "brief": B, "adj": adj, "why": why, "borrow": fee is not None, "borrow_ts": f.get("borrow_ts"), "borrow_days": f.get("borrow_days")}

# ---------------------------------------------------------------- 공모 전 펌핑: 공시 상태 (시점 기준, 백테스트·실시간 공용)
REG_OPEN = r"^(S-1|F-1)(/A)?$"
REG_CLOSE = r"^(424B\d|S-1MEF|F-1MEF|RW)$"
def reg_status(fil, asof, pend_days=120):
    """fil: asof '전날까지' 제출된 공시(form, filed, items). 반환 dict(pending, effect, def301, atm, ...).
    pending = 최근 pend_days 안에 S-1/F-1(/A) 제출됐는데 그 뒤로 가격 확정(424B1/3/4·MEF)이나 철회(RW)가 없음."""
    out = {"pending": False, "effect": False, "def301": False, "atm": False, "reg_last": None, "reg_first": None, "closed": None, "def_date": None}
    if fil is None or not len(fil): return out
    asof = pd.Timestamp(asof)
    h = fil[fil["filed"] < asof]
    form = h["form"].astype(str)
    reg = h[form.str.match(REG_OPEN)]
    clo = h[form.str.match(REG_CLOSE)]
    if len(reg):
        last = reg["filed"].max(); lc = clo["filed"].max() if len(clo) else None
        if (lc is None or lc < last) and last >= asof - pd.Timedelta(days=pend_days):
            out["pending"] = True; out["reg_last"] = last
            prev = reg[reg["filed"] > lc] if lc is not None else reg
            out["reg_first"] = prev["filed"].min()
            eff = h[(form == "EFFECT") & (h["filed"] >= out["reg_first"])]
            out["effect"] = bool(len(eff))
        elif lc is not None: out["closed"] = lc
    it = h["items"].astype(str) if "items" in h else pd.Series("", index=h.index)
    d = h[form.str.startswith("8-K") & it.str.contains(r"\b3\.01\b") & (h["filed"] >= asof - pd.Timedelta(days=180))]
    if len(d): out["def301"] = True; out["def_date"] = d["filed"].max()
    out["atm"] = bool(len(h[form.str.match(r"^424B5") & (h["filed"] >= asof - pd.Timedelta(days=60))]))
    return out

# ---------------------------------------------------------------- 정밀 검증 모델 (model/research.json)
_RES = {"mt": None, "obj": None}
def research():
    """scripts/research.py 결과. 파일이 없으면 None (기존 보정표 방식으로 대체)."""
    from pathlib import Path
    fp = Path(__file__).resolve().parents[1] / "model" / "research.json"
    if not fp.exists(): return None
    mt = fp.stat().st_mtime
    if _RES["mt"] != mt:
        r = json.loads(fp.read_text(encoding="utf-8"))
        if r.get("model") == "M3_gbm":
            import pickle
            gp = fp.parent / "gbm.pkl"
            r["_gbm"] = pickle.loads(gp.read_bytes()) if gp.exists() else None
        _RES.update(mt=mt, obj=r)
    base = _RES["obj"]
    key, defs = active_def_key(), research_defs()
    d = (defs or {}).get("defs", {}).get(key) if key else None
    if not d: return base
    ck = (mt, key, _DEFS["mt"])
    if _RES.get("ck") != ck:
        r = dict(base)
        o = d["oos"]
        r.update(model="M1_gated", signals=defs["signals"], weights=d["weights"], iso=d["iso"], threshold=d["threshold"],
                 compare={"M1_gated": {"auc": o["auc"], "brier": o["brier"]}}, n_rows=o["n_test"], base_rate=d.get("base_rate"),
                 target={"gain": (d.get("target_pct") or 0) / 100, "days": d["horizon_days"]}, def_key=key, def_label=d["label"], def_kind=d["kind"])
        _RES.update(ck=ck, def_obj=r)
    return _RES["def_obj"]

_DEFS = {"mt": None, "obj": None}
def research_defs():
    """scripts/target_grid.py 결과: 성공 정의별로 재학습·보정된 M1_gated (model/research_defs.json)."""
    from pathlib import Path
    fp = Path(__file__).resolve().parents[1] / "model" / "research_defs.json"
    if not fp.exists(): return None
    mt = fp.stat().st_mtime
    if _DEFS["mt"] != mt: _DEFS.update(mt=mt, obj=json.loads(fp.read_text(encoding="utf-8")))
    return _DEFS["obj"]

def active_def_key():
    """관리 탭에서 고른 성공 정의 (기본 = 권장 정의 'setup'). 'legacy' = 기존 research.json(+30%/5일)."""
    k = (db.get_setting("params", {}) or {}).get("success_def") or ((research_defs() or {}).get("recommended") or "setup")
    return None if k == "legacy" else k

def goal_text(short=False):
    """확률 카드 문구: 선택된 성공 정의."""
    r = research() or {}
    if r.get("def_kind") == "setup":
        return f'{r["target"]["days"]}일 내 재점화 도달(지지 이탈 전)' if not short else f'{r["target"]["days"]}일 재점화'
    if r.get("def_key"):
        return r["def_label"] if not short else r["def_label"].split(":")[0]
    t = r.get("target") or {}
    return f'{t.get("days", 5)}일 내 +{(t.get("gain") or 0.3) * 100:.0f}%'

def _xrow(r, s, f):
    sig = r["signals"]
    v = np.array([np.nan if s.get(k) is None else float(s[k]) for k in sig])
    X = np.nan_to_num(np.minimum(v, 3.0), nan=0.0); miss = np.isnan(v).astype(float)
    ex = [math.log(max(float(f.get("price") or 0.01), 0.01)), math.log1p(float(f.get("dollar_vol20") or 0)), float(bool(f.get("dilution_recent"))), float(f.get("regime", 1))]
    return np.r_[X, miss, ex], v

def research_predict(s, f):
    """검증 모델의 보정 확률 (0~1). 반환 dict 또는 None."""
    r = research()
    if not r: return None
    x, v = _xrow(r, s, f)
    m = r["model"]
    if m in ("M0_saved", "M1_gated"):
        w = np.array([float(r["weights"].get(k, 0)) for k in r["signals"]])
        on = ~np.isnan(v); den = float((w * on).sum())
        raw = float((np.nansum(np.minimum(v, 1.0) * w) + 0.01 * np.nansum(np.minimum(v, 3.0) * w)) / den * 100) if den > 0 else 0.0
        if m == "M0_saved" and f.get("dilution_recent"): raw *= 0.75
    elif m == "M2_logit":
        L = r["logit"]; z = (x - np.array(L["mean"])) / np.array(L["std"])
        raw = float(1 / (1 + math.exp(-(float(np.dot(z, L["coef"])) + L["intercept"]))))
    else:
        g = r.get("_gbm")
        if g is None: return None
        raw = float(g.predict_proba(x.reshape(1, -1))[0, 1])
    ix, iy = list(r["iso"]["x"]), list(r["iso"]["y"])
    while len(iy) > 2 and iy[-1] - iy[-2] > 0.2:     # 맨 끝 표본 1~2개짜리 급점프(예: 0.53→0.999)는 과신 → 직전 구간으로 제한
        ix.pop(); iy.pop()
    prob = float(np.interp(raw, ix, iy))
    t = r["threshold"]
    return {"prob": prob, "raw": raw, "flag": raw >= float(t.get("raw", 1e9)), "thr": float(t.get("prob", 0)), "top_pct": t.get("q", 0) * 100, "model": m}

def exit_rule(p=None):
    """검증된 청산 규칙 (표본외 기대값이 양수일 때만 '권장'). 없으면 None."""
    r = research()
    if not r or "exit" not in r: return None
    e = r["exit"]; c = e["final"]
    return {"stop": c["stop"] * 100, "tp": None if c["tp"] is None else c["tp"] * 100, "partial": bool(c["partial"]), "trail": None if not c["trail"] else c["trail"] * 100,
            "hold": int(c["hold"]), "entry": c["entry"], "top_pct": c["q"] * 100, "positive": bool(e.get("positive_oos")),
            "oos": e.get("nested_stats", {}), "final_stats": e.get("final_stats", {})}

# ---------------------------------------------------------------- 결과 라벨 (미래, 백테스트 전용)
def outcome(px, asof, p):
    fut = px[px["date"] > asof].head(int(p["horizon_days"]))
    if len(fut) < int(p["horizon_days"]): return None
    c0 = float(px[px["date"] <= asof]["close"].iloc[-1])
    tgt, stp = c0 * (1 + p["target_pct"] / 100), c0 * (1 - p["stop_pct"] / 100)
    trade = None
    for r in fut.itertuples(index=False):
        if r.low <= stp: trade = -p["stop_pct"]; break       # 같은 날 둘 다면 보수적으로 손절 우선
        if r.high >= tgt: trade = p["target_pct"]; break
    end = (float(fut["close"].iloc[-1]) / c0 - 1) * 100
    if trade is None: trade = end
    return {"hit": int(float(fut["high"].max()) >= tgt), "max_ret": (float(fut["high"].max()) / c0 - 1) * 100,
            "min_ret": (float(fut["low"].min()) / c0 - 1) * 100, "end_ret": end, "trade_ret": trade}

# ---------------------------------------------------------------- 확률 보정
def latest_run_id():
    r = db.q("SELECT id FROM bt_runs ORDER BY id DESC LIMIT 1")
    return int(r["id"].iloc[0]) if len(r) else None

def probability(sc, p, run_id=None, s=None):
    if s is not None and s.get("rprob") is not None:      # 정밀 검증 모델 (워크포워드 · isotonic 보정)
        r = research()
        return {"prob": s["rprob"], "n": r.get("n_rows"), "msg": "", "model": r.get("model"), "brier": r["compare"][r["model"]]["brier"],
                "val_n": r.get("n_rows"), "auc": r["compare"][r["model"]]["auc"], "source": "research"}
    run_id = run_id or latest_run_id()
    if not run_id: return {"prob": None, "n": 0, "msg": "타임머신 검증 기록 없음"}
    cal = db.q("SELECT * FROM calibration WHERE run_id=? ORDER BY bin", (run_id,))
    if len(cal) == 0: return {"prob": None, "n": 0, "msg": "보정표 없음"}
    row = cal[(cal["lo"] <= sc) & (cal["hi"] > sc)]
    if len(row) == 0: row = cal.iloc[[-1]] if sc >= cal["hi"].max() else cal.iloc[[0]]
    r = row.iloc[0]
    m = json.loads(db.q("SELECT metrics FROM bt_runs WHERE id=?", (run_id,))["metrics"].iloc[0])
    if int(r["n"]) < int(p["min_samples"]):
        return {"prob": None, "n": int(r["n"]), "msg": "데이터 부족", "run_id": run_id, "brier": m.get("val", {}).get("brier")}
    # 라플라스 보정
    prob = (int(r["hits"]) + 1) / (int(r["n"]) + 2) * 100
    return {"prob": prob, "n": int(r["n"]), "hits": int(r["hits"]), "run_id": run_id, "bin": (float(r["lo"]), float(r["hi"])),
            "brier": m.get("val", {}).get("brier"), "val_n": m.get("val", {}).get("n"), "msg": ""}

# ---------------------------------------------------------------- 백테스트 (타임머신)
def metrics(df):
    if len(df) == 0: return {"n": 0}
    tp = int(((df.flagged == 1) & (df.hit == 1)).sum()); fp = int(((df.flagged == 1) & (df.hit == 0)).sum())
    fn = int(((df.flagged == 0) & (df.hit == 1)).sum()); tn = int(((df.flagged == 0) & (df.hit == 0)).sum())
    fl = df[df.flagged == 1].sort_values("asof")
    eq = (1 + fl["trade_ret"] / 100 * 0.1).cumprod() if len(fl) else pd.Series([1.0])   # 신호당 자본 10% 투입 가정
    mdd = float(((eq / eq.cummax()) - 1).min() * 100) if len(fl) else 0
    wins = fl[fl.trade_ret > 0]["trade_ret"]; losses = fl[fl.trade_ret <= 0]["trade_ret"]
    pr = (df["score"] / 100).clip(0, 1)
    return {"n": len(df), "tp": tp, "fp": fp, "fn": fn, "tn": tn, "base_rate": float(df.hit.mean() * 100),
            "accuracy": (tp + tn) / len(df) * 100, "precision": tp / (tp + fp) * 100 if tp + fp else None,
            "recall": tp / (tp + fn) * 100 if tp + fn else None, "hit_rate": tp / (tp + fp) * 100 if tp + fp else None,
            "flags": tp + fp, "avg_trade": float(fl.trade_ret.mean()) if len(fl) else None,
            "avg_win": float(wins.mean()) if len(wins) else None, "avg_loss_wrong": float(fl[fl.hit == 0]["trade_ret"].mean()) if fp else None,
            "expectancy": float(fl.trade_ret.mean()) if len(fl) else None, "max_dd": mdd,
            "avg_mae": float(fl.min_ret.mean()) if len(fl) else None}

def run_backtest(tickers, start, end, p, step=3, train_frac=0.6, label="", progress=None):
    """walk-forward: 기간 앞 train_frac 은 학습(확률 보정·가중치 제안), 뒤는 검증."""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    reg = regime_series()
    rows = []
    for ti, t in enumerate(tickers):
        b = Bundle(t, reg)
        if len(b.px) < 60: continue
        dates = [d for d in b.px["date"] if start <= d <= end][::step]
        for d in dates:
            f = features(b, d, p)
            if f is None: continue
            o = outcome(b.px, d, p)
            if o is None: continue
            s = score(f, p)
            feats = {k: (None if v is None else round(float(v), 3)) for k, v in s["signals"].items()}
            feats.update({"vol_ratio": f.get("vol_ratio"), "loss_pct": f.get("loss_pct"), "si_float": f.get("si_float"),
                          "reignite_reach": f.get("reignite_reach"), "rsi": f.get("rsi"), "ret5": f.get("ret5")})
            rows.append({"ticker": t, "asof": d, "score": s["score"], "level": s["level"], "confluence": s["confluence"],
                         "flagged": int(s["flagged"]), "feats": feats, **o})
        if progress: progress((ti + 1) / len(tickers), t)
    df = pd.DataFrame(rows)
    if len(df) == 0: return None, None
    cut = df["asof"].quantile(train_frac)
    df["split"] = np.where(df["asof"] <= cut, "train", "val")
    tr, va = df[df.split == "train"], df[df.split == "val"]
    # 확률 보정표: 학습 구간 점수 구간별 적중률
    nb = int(p["calib_bins"])
    edges = list(np.unique(np.quantile(tr["score"], np.linspace(0, 1, nb + 1)))) if len(tr) > nb else [0, 100]
    edges[0], edges[-1] = -0.01, 100.01
    cal = []
    for i in range(len(edges) - 1):
        sub = tr[(tr.score >= edges[i]) & (tr.score < edges[i + 1])]
        cal.append((i, float(edges[i]), float(edges[i + 1]), len(sub), int(sub.hit.sum())))
    def prob_of(s):
        for _, lo, hi, n, h in cal:
            if lo <= s < hi: return (h + 1) / (n + 2)
        return float(tr.hit.mean())
    m = {"train": metrics(tr), "val": metrics(va), "all": metrics(df), "cut": str(cut.date()), "importance": importance(tr, p)}
    if len(va):
        pv = va["score"].apply(prob_of); m["val"]["brier"] = float(((pv - va["hit"]) ** 2).mean())
        m["val"]["calib"] = [{"bin": i, "pred": (h + 1) / (n + 2) * 100, "actual": float(va[(va.score >= lo) & (va.score < hi)].hit.mean() * 100) if len(va[(va.score >= lo) & (va.score < hi)]) else None,
                              "n_val": int(len(va[(va.score >= lo) & (va.score < hi)]))} for i, lo, hi, n, h in cal]
    m["period"] = [str(start.date()), str(end.date())]; m["tickers"] = list(tickers)
    rid = db.exec_("INSERT INTO bt_runs(ts,label,params,metrics) VALUES(?,?,?,?)", (db.now_kst(), label, json.dumps(p), json.dumps(m, default=str)))
    db.upsert_rows("calibration", ["run_id", "bin", "lo", "hi", "n", "hits"], [(rid,) + c for c in cal])
    db.upsert_rows("bt_samples", ["run_id", "ticker", "asof", "split", "score", "level", "confluence", "flagged", "feats", "hit", "max_ret", "end_ret", "min_ret"],
                   [(rid, r.ticker, r.asof.strftime("%Y-%m-%d"), r.split, r.score, r.level, r.confluence, r.flagged, json.dumps(r.feats), r.hit, r.max_ret, r.end_ret, r.min_ret) for r in df.itertuples()])
    return rid, m

def importance(tr, p):
    """신호별 기여도: 신호 ON 일 때 적중률 / 기본 적중률 (lift) → 가중치 조정 제안."""
    out = []
    if len(tr) == 0: return out
    base = tr.hit.mean()
    for k, wk, name in SIGNALS:
        vals = tr["feats"].apply(lambda d: d.get(k))
        mask = vals.notna()
        if mask.sum() < 10: out.append({"signal": name, "key": k, "n_on": 0, "lift": None, "w": p[wk], "w_new": p[wk]}); continue
        on = tr[mask & (vals >= 1.0)]
        lift = (on.hit.mean() / base) if len(on) >= 5 and base > 0 else None
        w_new = round(float(p[wk]) * float(np.clip(lift, 0.5, 2.0)), 2) if lift is not None else p[wk]
        corr = float(np.corrcoef(vals[mask].astype(float), tr.loc[mask, "hit"])[0, 1]) if vals[mask].std() > 0 else 0
        out.append({"signal": name, "key": k, "n_on": int(len(on)), "hit_on": float(on.hit.mean() * 100) if len(on) else None,
                    "lift": lift, "corr": corr, "w": p[wk], "w_new": w_new})
    return out

# ---------------------------------------------------------------- 유사 패턴
def similar_cases(sig, k=25):
    rid = latest_run_id()
    if not rid: return None
    df = db.q("SELECT ticker, asof, feats, hit, max_ret, end_ret FROM bt_samples WHERE run_id=?", (rid,))
    if len(df) < 30: return None
    keys = [k_ for k_, _, _ in SIGNALS]
    X = np.array([[ (json.loads(x).get(kk) if json.loads(x).get(kk) is not None else 0) for kk in keys] for x in df["feats"]], dtype=float)
    q_ = np.array([sig.get(kk) if sig.get(kk) is not None else 0 for kk in keys], dtype=float)
    d = np.sqrt(((np.minimum(X, 1.5) - np.minimum(q_, 1.5)) ** 2).sum(axis=1))
    idx = np.argsort(d)[:k]
    sub = df.iloc[idx].assign(dist=d[idx])
    return {"n": len(sub), "hit_rate": float(sub.hit.mean() * 100), "avg_max": float(sub.max_ret.mean()), "avg_end": float(sub.end_ret.mean()),
            "cases": sub[["ticker", "asof", "hit", "max_ret", "end_ret", "dist"]].head(10)}

# ---------------------------------------------------------------- 부가 분석
def fade_stats(px, jump=30.0):
    """과거 급등(+jump% 일간) 이후 되돌림 속도."""
    if len(px) < 30: return None
    c = px["close"].values; h = px["high"].values; out = []
    for i in range(1, len(px) - 1):
        g = (h[i] / c[i - 1] - 1) * 100
        if g >= jump:
            rec = {"date": px["date"].iloc[i].strftime("%Y-%m-%d"), "gain": g}
            for k in (1, 3, 5, 10):
                if i + k < len(px): rec[f"d{k}"] = (c[i + k] / h[i] - 1) * 100
            gain_abs = h[i] - c[i - 1]
            later = c[i + 1:i + 11]
            rec["half_back"] = bool(len(later) and (later.min() <= h[i] - gain_abs / 2))
            out.append(rec)
    return pd.DataFrame(out)

def delisting(px):
    c = px["close"].values[::-1]; n = 0
    for x in c:
        if x < 1: n += 1
        else: break
    return {"days_below_1": n, "notice": n >= 30, "days_to_notice": max(0, 30 - n) if n else None,
            "compliance_left": max(0, 180 - int((n - 30) * 7 / 5)) if n >= 30 else None}

def dilution(b: Bundle, asof=None):
    asof = pd.Timestamp(asof or dt.date.today())
    sc, why = 0, []
    fil = b.fil[b.fil["filed"] <= asof] if len(b.fil) else b.fil
    def recent(pattern, days):
        return fil[(fil["filed"] >= asof - pd.Timedelta(days=days)) & fil["form"].str.match(pattern)] if len(fil) else fil
    r1 = recent(r"^(S-1|S-3|F-1|F-3)", 180)
    if len(r1): sc += 25; why.append(f"증권신고서(셸프) {r1['form'].iloc[0]} {r1['filed'].iloc[0]:%Y-%m-%d}")
    r2 = recent(r"^424B", 60)
    if len(r2): sc += 25; why.append(f"공모/ATM 설명서 424B {len(r2)}건 (60일)")
    if len(fil):
        r3 = fil[(fil["filed"] >= asof - pd.Timedelta(days=90)) & (fil["form"] == "8-K") & fil["items"].str.contains("3.02", na=False)]
        if len(r3): sc += 15; why.append("8-K 3.02 비등록 증권 발행")
        rs = fil[(fil["filed"] >= asof - pd.Timedelta(days=365)) & (fil["form"] == "8-K") & fil["items"].str.contains("3.03|5.03", na=False)]
    else:
        rs = fil
    f = b.facts or {}
    runway = None
    cash = sorted([x for x in f.get("cash", []) if x.get("filed") and pd.Timestamp(x["filed"]) <= asof], key=lambda x: x["end"])
    opcf = [x for x in f.get("opcf", []) if x.get("filed") and pd.Timestamp(x["filed"]) <= asof and x.get("start")]
    burn_q = None
    if opcf:
        opcf.sort(key=lambda x: x["end"]); last = opcf[-1]
        months = max((pd.Timestamp(last["end"]) - pd.Timestamp(last["start"])).days / 30.4, 1)
        burn_q = -float(last["val"]) / months * 3
    if cash and burn_q and burn_q > 0:
        runway = float(cash[-1]["val"]) / (burn_q / 3)
        if runway < 6: sc += 20; why.append(f"현금 런웨이 약 {runway:.1f}개월")
        elif runway < 12: sc += 10; why.append(f"현금 런웨이 약 {runway:.1f}개월")
    recent = lambda x: x.get("filed") and x.get("val") and pd.Timestamp(x["filed"]) <= asof and pd.Timestamp(x["end"]) >= asof - pd.Timedelta(days=500)
    shares = sorted([x for x in f.get("shares", []) if x.get("filed") and x.get("val") and pd.Timestamp(x["filed"]) <= asof], key=lambda x: x["end"])
    if shares and not recent(shares[-1]): shares = []
    sh_growth = None
    if len(shares) >= 2:
        last = shares[-1]; old = [x for x in shares if pd.Timestamp(x["end"]) <= pd.Timestamp(last["end"]) - pd.Timedelta(days=330)]
        if old and old[-1]["val"]:
            sh_growth = (last["val"] / old[-1]["val"] - 1) * 100
            if sh_growth > 30: sc += 15; why.append(f"1년 주식수 +{sh_growth:.0f}%")
    war = sorted([x for x in f.get("warrants", []) if recent(x)], key=lambda x: x["end"])
    if war and shares and shares[-1]["val"] and war[-1]["val"] / shares[-1]["val"] > 0.2:
        sc += 15; why.append(f"워런트 {war[-1]['val'] / 1e6:.1f}m (주식수 대비 {war[-1]['val'] / shares[-1]['val'] * 100:.0f}%)")
    if any(recent(x) for x in f.get("convertible", [])): why.append("전환사채 존재(XBRL, 최근)")
    pf = sorted(f.get("public_float", []), key=lambda x: x["end"])
    price = float(b.px["close"].iloc[-1]) if len(b.px) else None
    float_usd = (b.info.get("floatShares") or 0) * (price or 0) or (pf[-1]["val"] if pf else None)
    baby = bool(float_usd and float_usd < 75e6)
    splits = [s for s in (b.info.get("splits") or []) if s[1] < 1]
    return {"score": min(sc, 100), "why": why, "runway_m": runway, "burn_q": burn_q, "share_growth": sh_growth, "baby_shelf": baby,
            "float_usd": float_usd, "reverse_splits": splits, "rs_8k": int(len(rs)) if len(fil) else 0,
            "shelf_capacity": "XBRL로 잔여 한도 산출 불가 (S-3 본문 수동 확인 필요)"}

def liquidity(f, info):
    w = []
    if f.get("dollar_vol20", 0) < 1e6: w.append(f"20일 평균 거래대금 ${f.get('dollar_vol20', 0) / 1e3:,.0f}k (저유동성)")
    b, a = info.get("bid"), info.get("ask")
    spread = None
    if b and a and a > 0 and b > 0:
        spread = (a - b) / ((a + b) / 2) * 100
        if spread > 25: spread = None   # 장외 시간 Yahoo 호가는 비정상값이 많아 무시
        elif spread > 2: w.append(f"호가 스프레드 {spread:.1f}%")
    return {"warnings": w, "spread": spread}

SENT_POS = ["approval", "approved", "fda", "partnership", "contract", "award", "record", "breakthrough", "acquire", "acquisition", "patent", "positive", "launch", "uplist", "merger", "grant", "beats", "surge"]
SENT_NEG = ["offering", "dilution", "priced", "reverse split", "delist", "deficiency", "lawsuit", "investigation", "bankrupt", "warrant", "default", "misses", "downgrade", "resign", "going concern", "halt"]
def sentiment(items):
    out = []
    for it in items[:20]:
        t = it.get("title", "").lower()
        s = sum(w in t for w in SENT_POS) - sum(w in t for w in SENT_NEG) * 1.5
        out.append({**it, "sent": s})
    tot = sum(x["sent"] for x in out)
    return out, tot

def event_log(b: Bundle, f, meta):
    """최근 주요 이벤트 자동 생성 (모두 asof 이전 데이터)."""
    ev = []
    px = b.px.tail(15)
    if len(px) > 2:
        mv = px["volume"].median()
        for r in px.itertuples():
            if r.volume > 3 * mv: ev.append((r.date, f"거래량 급증 {r.volume / 1e6:.2f}m (중앙값 {r.volume / mv:.1f}배)"))
        hi = px.loc[px["high"].idxmax()]; lo = px.loc[px["low"].idxmin()]
        ev.append((hi["date"], f"15일 고가 ${hi['high']:.3f} 기록"))
        ev.append((lo["date"], f"15일 저가 ${lo['low']:.3f} 기록"))
    if len(b.si):
        for r in b.si.tail(2).itertuples():
            ev.append((r.publish_date, f"숏 잔고 공표({r.settle_date:%m/%d} 기준) {r.si / 1e6:.2f}m, DTC {r.dtc:.1f}"))
    if len(b.bor) > 1:
        bb = b.bor.tail(30)
        for i in range(1, len(bb)):
            a0, a1 = bb["available"].iloc[i - 1], bb["available"].iloc[i]
            f0, f1 = bb["fee"].iloc[i - 1], bb["fee"].iloc[i]
            if a0 and a1 < a0 * 0.5: ev.append((bb["ts"].iloc[i], f"빌릴 수 있는 주식 {kn(a0)} → {kn(a1)}주 (급감)"))
            if a1 > a0 * 2 and a0 > 0: ev.append((bb["ts"].iloc[i], f"빌릴 수 있는 주식 {kn(a0)} → {kn(a1)}주 (반납 유입)"))
            if f1 - f0 >= 20: ev.append((bb["ts"].iloc[i], f"대차이자 {f0:.1f}% → {f1:.1f}% 급등"))
    if len(b.fil):
        for r in b.fil.head(5).itertuples():
            if r.filed >= pd.Timestamp.today() - pd.Timedelta(days=30):
                ev.append((r.filed, f"SEC 공시 {r.form} {('(item ' + r.items + ')') if r.items else ''}"))
    if len(b.thr) and (b.thr >= pd.Timestamp.today() - pd.Timedelta(days=10)).any():
        ev.append((b.thr.max(), "Reg SHO Threshold 리스트 등재 (결제 실패 누적)"))
    ev = sorted(ev, key=lambda x: pd.Timestamp(x[0]))[-10:]
    if meta:
        ev.append((pd.Timestamp.today(), f"현재 ${f['price']:.3f}: 손실권 숏 {meta['loss_pct']:.0f}%, 재점화 ${meta['reignite']:.3f}까지 {(meta['reignite'] / f['price'] - 1) * 100:+.1f}%"))
    return ev

def buy_zone(f, meta, p):
    """손실권 하단(지지) 근처 매수 구간, 손익분기, 손절, 목표가, R:R (추정)."""
    if not meta or not meta.get("tranches"): return None
    price = f["price"]; w = meta["width"]
    below = [t for t in meta["tranches"] if t["lo"] < price]
    if below:
        cur = max(below, key=lambda t: t["lo"])   # 현재가를 포함하거나 바로 아래 덩어리
    else:   # 아래에 숏 매물대가 없음 → 21일 저점을 지지로 사용
        lo = min(meta["lo21"], price); cur = {"lo": lo, "hi": max(price, lo + w), "name": "21일 저점(매물대 없음)"}
    zone_lo = cur["lo"]; zone_hi = min(price, cur["lo"] + max(w, (min(cur["hi"], price) - cur["lo"]) * 0.35))
    gap_below = any(abs(g[1] - cur["lo"]) < w * 1.01 for g in meta["gaps"])
    stop = zone_lo - w * (0.5 if gap_below else 1.0)
    capped = []
    # 비정상 값 방지 (10/28 TRUG 손절 −$0.30, CDT 손절 −$25·목표 $25 @ $0.08): 매물대 폭이 주가보다 크거나 분할 전 가격이 섞인 경우
    if zone_lo <= 0 or zone_lo < price * 0.55:
        zone_lo = max(zone_lo, price * 0.7); zone_hi = max(min(zone_hi, price), zone_lo); capped.append("zone")
    if stop <= 0 or stop < price * 0.5:
        stop = max(stop, price * 0.5, 1e-4); capped.append("stop")
    if stop >= zone_lo: stop = zone_lo * 0.95
    entry = (zone_lo + zone_hi) / 2
    cost = (p["fee_rate"] + p["slippage"]) / 100
    be = entry * (1 + cost) / (1 - cost)
    above = sorted([t["hi"] for t in meta["tranches"] if t["hi"] > price])
    tp1 = meta["reignite"] if meta["reignite"] > price else (above[0] if above else meta["hi21"])
    tp2 = next((x for x in above if x > tp1 * 1.001), max(meta["hi21"], tp1 * 1.15))
    if tp1 > price * 3:      # +200% 넘는 목표 = 분할 전 가격 등 → 3배 이내 다음 레벨(없으면 21일 고가, 그것도 크면 +50%)
        ok_lv = [x for x in above if price < x <= price * 3] + ([meta["hi21"]] if price < meta["hi21"] <= price * 3 else [])
        tp1 = min(ok_lv) if ok_lv else price * 1.5; capped.append("tp1")
    if tp2 > price * 3 or tp2 <= tp1:
        tp2 = max(tp1 * 1.15, min(tp2, price * 3)); capped.append("tp2")
    net_tp1 = tp1 * (1 - cost); net_stop = stop * (1 - cost)
    risk = be - net_stop; reward = net_tp1 - be
    rr = reward / risk if risk > 0 else None
    return {"zone": (zone_lo, zone_hi), "entry": entry, "break_even": be, "stop": stop, "tp1": tp1, "tp2": tp2,
            "rr": rr, "rr_ok": bool(rr and rr >= 2), "gap_below": gap_below, "tranche": cur.get("name"), "capped": capped}

def position_size(account, risk_pct, entry, stop):
    if not entry or not stop or entry <= stop: return None
    risk_amt = account * risk_pct / 100
    sh = int(risk_amt / (entry - stop)); sh = min(sh, int(account / entry))
    return {"shares": sh, "cost": sh * entry, "risk_amt": sh * (entry - stop)}

def summary_ko(t, f, s, meta, dil, prob):
    """종목별 한국어 자동 요약: 왜 경보가 떴는지."""
    parts = []
    if meta:
        parts.append(f"추정 숏 잔고 {meta['total_rem'] / 1e6:.2f}m 중 {meta['loss_pct']:.0f}%가 손실권")
        parts.append(f"재점화 레벨 ${meta['reignite']:.3f} (도달률 {f['price'] / meta['reignite'] * 100:.0f}%)")
    if f.get("si_chg") is not None: parts.append(f"최근 공표 숏 잔고 {f['si_chg']:+.1f}%")
    if f.get("si_float") is not None: parts.append(f"유통 대비 {f['si_float']:.1f}%")
    if f.get("fee") is not None: parts.append(f"대차이자 연 {f['fee']:.1f}%")
    if f.get("avail") is not None: parts.append(f"빌릴 수 있는 주식 {'1천만+' if f['avail'] >= 1e7 else kn(f['avail'])}주")
    on = [SIG_NAME[k] for k in s["on"]]
    txt = f"{t}: " + ", ".join(parts) + "."
    if on: txt += f" 켜진 신호 {len(on)}개({', '.join(on)})."
    if f.get("dilution_recent") or (dil and dil["score"] >= 40): txt += " 단, 최근 희석(증자) 위험이 있어 점수를 깎았습니다."
    if f.get("regime", 1) < 0: txt += " 나스닥/러셀 약세장이라 기준을 높였습니다."
    if s["flagged"]: txt += f" → 동시 신호 {s['confluence']}개로 경보 조건 충족."
    else: txt += f" → 경보 조건 미충족 (점수 {s['score']:.0f}, 동시 신호 {s['confluence']}개)."
    return txt


# ---------------------------------------------------------------- 초보자용 한 줄 요약
def plain_summary(f, s=None, pxf=None):
    """전문 용어 없이 한 줄로: 지금 이 종목이 왜 눈에 띄는지 / 무엇을 조심할지."""
    if not f: return ""
    pxf = pxf or (lambda v: f"${v:.2f}" if v >= 1 else f"${v:.3f}")
    good, warn = [], []
    m = f.get("_meta") or {}
    lp, rg = f.get("loss_pct"), f.get("reignite")
    near = bool(rg and f.get("price") and f["price"] < rg <= f["price"] * 1.5)   # 50% 이내일 때만 언급
    if lp is not None and lp >= 60 and near:
        good.append(f"공매도 물량 대부분 손해 중, {pxf(rg)} 넘으면 급등 가능성 ↑")
    elif lp is not None and lp >= 60:
        good.append("공매도 물량 대부분 손해 중")
    elif near:
        good.append(f"{pxf(rg)} 넘으면 공매도 되사기 압박 ↑")
    fm = f.get("float_m")
    if fm is not None and 0.05 <= fm < 20: good.append(f"시장에 도는 주식 {fm * 100:,.0f}만 주뿐이라 쉽게 크게 움직임")
    vr = f.get("vol_ratio") or 0
    if vr >= 3: good.append(f"오늘 거래량 평소의 {'50' if vr >= 50 else f'{vr:.0f}'}배 이상, 관심 급증")
    if f.get("brk52"): good.append("1년 최고가 돌파")
    elif f.get("brk20"): good.append("한 달 고점 돌파")
    if f.get("gap_hold"): good.append("갭 상승 후 버티는 중")
    if f.get("catalyst"): good.append("최근 회사 공시 있음")
    if f.get("round_reclaim"): good.append(f"${f['round_reclaim']} 다시 회복")
    if f.get("dilution_recent"): warn.append("최근 유상증자 서류 제출, 주가 눌릴 위험")
    if f.get("gap_fade"): warn.append("갭 상승 후 밀리는 중")
    if f.get("price", 9) < 1: warn.append("$1 미만, 상장폐지 주의")
    parts = good[:2] + warn[:1]
    return " · ".join(parts) if parts else "뚜렷한 신호 없음, 지켜보기"

# ---------------------------------------------------------------- 과거 시점 케이스 카드 (SHFS 스타일, 룩어헤드 없음)
def _n(v):
    v = float(v or 0)
    return f"{v / 1e6:.2f}m" if v >= 1e6 else (f"{v / 1e3:.0f}k" if v >= 1e3 else f"{v:.0f}")

def pit_events(b: Bundle, asof, f, meta):
    """asof 시점까지 공개된 데이터만으로 만든 이벤트 로그."""
    asof = pd.Timestamp(asof); ev = []
    px = b.px[b.px["date"] <= asof].tail(21)
    if len(px) > 3:
        mv = float(px["volume"].median() or 1)
        for r in px.itertuples():
            if r.volume > 3 * mv: ev.append((r.date, f"거래량 급증 {_n(r.volume)} (21일 중앙값 {r.volume / mv:.1f}배) · 종가 ${r.close:.3f}"))
        hi = px.loc[px["high"].idxmax()]
        ev.append((hi["date"], f"21일 고가 ${hi['high']:.3f} 기록"))
    sv = b.sv[(b.sv["date"] <= asof)].tail(21) if len(b.sv) else b.sv
    if len(sv) >= 5:
        ratio = sv["short_vol"] / sv["total_vol"].replace(0, np.nan)
        base = float(ratio.iloc[:-1].median())
        for r, rt in zip(sv.itertuples(), ratio):
            if rt >= max(0.55, base + 0.15) and r.short_vol > sv["short_vol"].median() * 2:
                ev.append((r.date, f"FINRA 공매도 거래 {_n(r.short_vol)}주 (거래의 {rt * 100:.0f}%) — 신규 숏 유입"))
    if len(b.si):
        for r in b.si[b.si["publish_date"] <= asof].tail(2).itertuples():
            ev.append((r.publish_date, f"숏 잔고 공표({pd.Timestamp(r.settle_date):%m/%d} 결제 기준) {_n(r.si)}, DTC {float(r.dtc or 0):.1f}"))
    if len(b.fil):
        fl = b.fil[(b.fil["filed"] <= asof) & (b.fil["filed"] >= asof - pd.Timedelta(days=30))]
        for r in fl.head(4).itertuples():
            ev.append((r.filed, f"SEC 공시 {r.form}" + (" — 증자/희석 주의" if re.match(r"^(S-1|S-3|F-1|F-3|424B)", str(r.form)) else "")))
    if len(b.thr) and ((b.thr <= asof) & (b.thr >= asof - pd.Timedelta(days=10))).any():
        ev.append((b.thr[b.thr <= asof].max(), "Reg SHO Threshold 리스트 등재 (결제 실패 누적)"))
    ev = sorted(ev, key=lambda x: pd.Timestamp(x[0]))[-9:]
    if meta:
        ev.append((asof, f"경보일 ${f['price']:.3f}: 손실권 숏 {meta['loss_pct']:.0f}%, 재점화 ${meta['reignite']:.3f}까지 {(meta['reignite'] / f['price'] - 1) * 100:+.1f}%"))
    return ev

def pit_narrative(b: Bundle, asof, f, meta, bz):
    """SHFS 카드 스타일 한국어 서술 (모든 수치는 추정치)."""
    if not meta or not meta.get("tranches"): return "진입 구간 데이터 부족."
    asof = pd.Timestamp(asof); px = b.px[b.px["date"] <= asof].tail(21)
    trs = meta["tranches"]; price = f["price"]; rl = meta["reignite"]
    new = min(trs, key=lambda t: t["age"])
    hi_day = px.loc[px["high"].idxmax(), "date"] if len(px) else asof
    parts = [f"{pd.Timestamp(hi_day):%m/%d} 전후 급등 구간에서 신규 숏 약 {_n(new['init'])}주 유입({new['name']} ${new['lo']:.3f}~${new['hi']:.3f}, 잔존 {_n(new['rem'])}주·{new['ratio'] * 100:.0f}%)."]
    parts.append(f"경보일 ${price:.3f} 기준 추정 숏 잔고의 {meta['loss_pct']:.0f}%가 손실권, {meta['profit_pct']:.0f}%가 수익권.")
    over = [t for t in trs if t["hi"] <= rl * 1.0001 and t["hi"] > price]
    tgt = min([t for t in trs if t["hi"] > price], key=lambda t: t["hi"], default=None)
    if tgt is not None:
        parts.append(f"${rl:.3f} 돌파 시 {tgt['name'].replace(' 숏', '')} 물량({_n(tgt['rem'])}주) 전량 손실권 전환 → 커버(매수) 압력 지수 {f.get('cover_pressure', 0):.0f}/100.")
    else:
        parts.append(f"현재가 위에 남은 숏 덩어리가 적어 재점화 기준을 21일 고점 ${rl:.3f}로 둠.")
    if bz:
        if bz["stop"] > 0 and bz["zone"][0] > 0:
            parts.append(f"지지: {bz['tranche']} 하단 ${bz['zone'][0]:.3f} (이탈 ${bz['stop']:.3f} 시 셋업 무효).")
        else: parts.append("지지선 추정 불가(가격이 밴드 폭보다 낮음 → 셋업 판정 제외).")
    hi21 = meta["hi21"]
    if hi21 > rl * 1.001: parts.append(f"이후 21일 고점 ${hi21:.3f}({(hi21 / price - 1) * 100:+.0f}%) 재시험 여부가 2차 관문.")
    if meta.get("est_days"): parts.append(f"(맵 {meta['days']}일 중 {meta['est_days']}일은 FINRA 자료 없어 거래량×가정비율로 추정)")
    return " ".join(parts)

def hist_case(ticker, asof, p, H=10):
    """과거 시점 카드용 데이터: 경보 시점 구조 + 사후 결과 (사후 결과는 카드에 '사후'로 분리 표기)."""
    b = Bundle(ticker, regime_series()); asof = pd.Timestamp(asof)
    f = features(b, asof, p)
    if not f or "_meta" not in f: return None
    meta = f["_meta"]; bz = buy_zone(f, meta, p); s = score(f, p)
    fut = b.px[b.px["date"] > asof].head(H)
    rl, stop = meta["reignite"], (bz or {}).get("stop", 0)
    above = sorted([t["hi"] for t in meta["tranches"] if t["hi"] > rl * 1.001])
    ph = meta["hi21"] if meta["hi21"] > rl * 1.001 else (above[0] if above else max(meta["hi21"], rl * 1.15))
    post = []; res = "미도달(기간 종료)"; got_rl = False; price = f["price"]
    for i, r in enumerate(fut.itertuples(index=False), 1):
        lvl = price if got_rl else stop
        if r.low <= lvl:
            post.append((r.date, f"D+{i} 저가 ${r.low:.3f} — {'본전 스탑(재점화 후 되밀림)' if got_rl else '최신 차수 하단(지지) 이탈 → 셋업 실패'}"))
            if not got_rl: res = "실패(지지 이탈 먼저)"
            break
        if not got_rl and r.high >= rl:
            got_rl = True; res = "성공(재점화 도달)"; post.append((r.date, f"D+{i} 고가 ${r.high:.3f} — 재점화 ${rl:.3f} 돌파, 위 차수 전량 손실권 전환"))
        if got_rl and r.high >= ph:
            post.append((r.date, f"D+{i} 고가 ${r.high:.3f} — 고점 재시험 ${ph:.3f} 도달")); res = "성공+고점 재시험"; break
    if len(fut): post.append((fut["date"].iloc[-1], f"D+{len(fut)} 종가 ${fut['close'].iloc[-1]:.3f} ({(fut['close'].iloc[-1] / f['price'] - 1) * 100:+.1f}%) · 기간 최고 {(fut['high'].max() / f['price'] - 1) * 100:+.1f}%"))
    prev = b.px[b.px["date"] < asof]["close"]
    return {"ticker": ticker, "asof": asof, "b": b, "f": f, "s": s, "meta": meta, "bands": f.get("_bands"), "bz": bz,
            "events": pit_events(b, asof, f, meta), "narr": pit_narrative(b, asof, f, meta, bz), "post": post, "result": res, "ph": ph,
            "eh": {"prev_close": float(prev.iloc[-1]) if len(prev) else None, "last": f["price"]}, "session": "closed",
            "info": {"shortName": (b.info or {}).get("shortName", "")}, "live_log": pd.DataFrame(), "summary": plain_summary(f), "bp": _bp_hist(b, asof, f, bz, p, s)}

def _bp_hist(b, asof, f, bz, p, s):
    try:
        from . import buyprice
        sv = b.sv[b.sv["date"] <= asof] if b.sv is not None else None
        return buyprice.recommend(b.px[b.px["date"] <= asof], sv, f["price"], (bz or {}).get("stop"), p, alert=bool(s.get("flagged")))
    except Exception:
        return None
