"""진입 타이밍 규칙 표본외 검증: 신호 당일 종가 매수(기준) vs 눌림 지정가 vs 돌파 확인.
- 신호: 셋업 라벨 재학습 M1 상위 5% (target_grid 와 동일, 5폴드 워크포워드 표본외) + 셋업 유효 + 10일 쿨다운
- 레벨(재점화 rl · 손절 stop · 2차 ph)은 신호일 종가 시점 값 고정 (룩어헤드 없음)
- 기간: 신호일 다음 거래일부터 10거래일 창 안에서 진입·청산 (기준과 같은 창)
- 청산: 50% 를 rl 에서 익절 → 나머지 본전 스탑, ph 또는 10일째 종가 청산. 같은 날 손절·목표 동시면 손절 우선. 비용 0.6%
- 체결일 당일에는 목표 체결을 인정하지 않고 손절만 인정 (보수적)
- 파라미터 선택은 중첩: 폴드 k 의 규칙은 폴드 1..k-1 결과로만 고름 → 폴드 2~5 가 진짜 표본외
출력: model/entry_timing.json"""
import sys, json, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT / "scripts"))
src = (ROOT / "scripts/target_grid.py").read_text(encoding="utf-8")
exec(compile(src[:src.index("OUT = {")], "target_grid_prefix", "exec"), globals())
COST = 0.006; H = 10

OR_S, TH_S, OF_S, R_S = run_def(Y_SETUP, VALID)
SEL = sel_mask(OR_S, TH_S, 0.05) & VALID
IDX = L.cooldown(np.where(SEL)[0], H)
FOLD = np.zeros(N, int)
for Fd in folds: FOLD[Fd["te"]] = Fd["k"]
print("signals", len(IDX), "check base exp", np.nanmean(SRET[IDX]), flush=True)

BARS = {t: g.reset_index(drop=True) for t, g in px.groupby("ticker")}
DPOS = {t: {d: i for i, d in enumerate(g["date"])} for t, g in BARS.items()}

def manage(o, h, l, c, j0, entry, rl, stop, ph, fill_day_guard=True):
    """o,h,l,c: 10일 창 배열. j0: 체결일(0-base). 반환 (ret, hit, fail)."""
    pos, real, st_, tp1 = 1.0, 0.0, stop, False
    if l[j0] <= stop:                                   # 체결일 손절 (보수적)
        return min(stop, o[j0] if o[j0] < entry else stop) / entry - 1 - COST, 0, 1
    for j in range(j0 + 1, len(o)):
        if l[j] <= st_:
            fill = min(o[j], st_); real += pos * (fill / entry - 1); pos = 0
            return real - COST, int(tp1), int(not tp1)
        if not tp1 and h[j] >= rl:
            fill = max(o[j], rl); tp1 = True; real += 0.5 * (fill / entry - 1); pos = 0.5; st_ = entry
        if tp1 and h[j] >= ph:
            fill = max(o[j], ph); real += pos * (fill / entry - 1); pos = 0
            return real - COST, 1, 0
    real += pos * (c[-1] / entry - 1)
    return real - COST, int(tp1), 0

def window(i):
    t = df.ticker.values[i]; d = pd.Timestamp(df["asof"].values[i]); b = BARS.get(t)
    if b is None or d not in DPOS[t]: return None
    p0 = DPOS[t][d]; w = b.iloc[p0 + 1: p0 + 1 + H]
    if len(w) < H: return None
    return b.iloc[p0], w.open.values.astype(float), w.high.values.astype(float), w.low.values.astype(float), w.close.values.astype(float)

def run_rule(i, rule):
    """반환 dict(filled, ret, hit) — 미체결이면 filled=0, ret=0."""
    wv = window(i)
    if wv is None: return None
    d0, o, h, l, c = wv
    price, rl, stop, ph = float(SX.price.values[i]), float(SX.rl.values[i]), float(SX.stop.values[i]), float(SX.ph.values[i])
    kind = rule[0]
    if kind == "close":                                  # 기준: 신호일 종가 매수 (setup_lib.score_path 와 동일 규칙)
        pos, real, st_, tp1 = 1.0, 0.0, stop, False
        for j in range(H):
            if l[j] <= st_:
                real += pos * (min(o[j], st_) / price - 1); return dict(filled=1, ret=real - COST, hit=int(tp1))
            if not tp1 and h[j] >= rl:
                tp1 = True; real += 0.5 * (max(o[j], rl) / price - 1); pos = 0.5; st_ = price
            if tp1 and h[j] >= ph:
                real += pos * (max(o[j], ph) / price - 1); return dict(filled=1, ret=real - COST, hit=1)
        return dict(filled=1, ret=real + pos * (c[-1] / price - 1) - COST, hit=int(tp1))
    if kind == "pull":                                   # 눌림 지정가: 종가 대비 -x% 에 D일간 매수 대기
        x, D = rule[1], rule[2]; lim = price * (1 - x)
        if lim <= stop * 1.01: return dict(filled=0, ret=0.0, hit=0)
        for j in range(D):
            if h[j] >= rl and l[j] > lim: return dict(filled=0, ret=0.0, hit=0)    # 먼저 목표 도달 → 놓침
            if l[j] <= lim:
                e = min(o[j], lim); r, hit, _ = manage(o, h, l, c, j, e, rl, stop, ph); return dict(filled=1, ret=r, hit=hit)
        return dict(filled=0, ret=0.0, hit=0)
    if kind == "brk":                                    # 돌파 매수스탑: 신호일 고가 +0.2% 넘으면 매수 (D일간)
        D = rule[1]; trig = float(d0.high) * 1.002
        for j in range(D):
            if h[j] >= trig:
                e = max(o[j], trig)
                if e >= rl * 0.995: return dict(filled=0, ret=0.0, hit=0)          # 이미 목표 근처 → 추격 금지
                r, hit, _ = manage(o, h, l, c, j, e, rl, stop, ph); return dict(filled=1, ret=r, hit=hit)
        return dict(filled=0, ret=0.0, hit=0)
    if kind == "cc":                                     # 종가 확인: 종가가 신호일 고가 위에서 마감하면 그 종가에 매수
        D = rule[1]; lvl = float(d0.high)
        for j in range(D):
            if l[j] <= stop: return dict(filled=0, ret=0.0, hit=0)
            if c[j] > lvl:
                if c[j] >= rl * 0.995 or j == H - 1: return dict(filled=0, ret=0.0, hit=0)
                # 체결은 종가 → 다음 날부터 관리 (체결일 손절 판정 없음: 종가 체결이므로)
                o2, h2, l2, c2 = o.copy(), h.copy(), l.copy(), c.copy(); l2[j] = c[j] + 1e-9
                r, hit, _ = manage(o2, h2, l2, c2, j, c[j], rl, stop, ph); return dict(filled=1, ret=r, hit=hit)
        return dict(filled=0, ret=0.0, hit=0)

RULES = [("close",)] + [("pull", x, D) for x in (0.03, 0.05, 0.08, 0.12) for D in (1, 3)] + [("brk", D) for D in (1, 3)] + [("cc", D) for D in (1, 3)]
def name(r):
    return {"close": "신호일 종가 매수(기준)", "pull": "눌림 지정가 -{:.0%} · {}일 대기", "brk": "돌파 매수스탑(신호일 고가+0.2%) · {}일", "cc": "종가 확인(신호일 고가 위 마감) · {}일"}[r[0]].format(*r[1:])

t0 = time.time()
RES = {r: {} for r in RULES}
for i in IDX:
    for r in RULES:
        o = run_rule(i, r)
        if o is not None: RES[r][i] = o
print("simulated", round(time.time() - t0), "s", flush=True)

def summarize(r, ks):
    rows = [(i, v) for i, v in RES[r].items() if FOLD[i] in ks]
    if not rows: return dict(n_sig=0)
    sig = np.array([v["ret"] for _, v in rows]); fil = np.array([v["filled"] for _, v in rows]).astype(bool)
    tr = sig[fil]; hits = np.array([v["hit"] for _, v in rows])[fil]
    return dict(n_sig=int(len(rows)), fill=float(fil.mean()), n_trade=int(fil.sum()),
                exp_trade=float(tr.mean()) if len(tr) else None, ci_trade=boot(tr) if len(tr) > 1 else None,
                exp_signal=float(sig.mean()), ci_signal=boot(sig),
                hit=float(hits.mean()) if len(hits) else None, hit_ci=wil(int(hits.sum()), int(len(hits))) if len(hits) else None,
                win=float((tr > 0).mean()) if len(tr) else None)

OUT = {"created": time.strftime("%Y-%m-%d %H:%M KST"), "n_signals": int(len(IDX)), "cost": COST, "H": H,
       "rules": {name(r): dict(all=summarize(r, {1, 2, 3, 4, 5}), f2_5=summarize(r, {2, 3, 4, 5})) for r in RULES}}
# 중첩 선택: 폴드 k 규칙 = 폴드 1..k-1 의 신호당 기대값 최대 (미체결 0)
chosen, picks = [], []
for k in range(2, 6):
    prev = set(range(1, k))
    best = max(RULES, key=lambda r: np.mean([v["ret"] for i, v in RES[r].items() if FOLD[i] in prev]) if any(FOLD[i] in prev for i in RES[r]) else -9)
    chosen.append(name(best)); picks += [(i, RES[best][i]) for i in RES[best] if FOLD[i] == k]
sig = np.array([v["ret"] for _, v in picks]); fil = np.array([v["filled"] for _, v in picks]).astype(bool); hits = np.array([v["hit"] for _, v in picks])[fil]
OUT["nested"] = dict(chosen=chosen, n_sig=int(len(sig)), fill=float(fil.mean()), n_trade=int(fil.sum()),
                     exp_signal=float(sig.mean()), ci_signal=boot(sig), exp_trade=float(sig[fil].mean()), ci_trade=boot(sig[fil]),
                     hit=float(hits.mean()), hit_ci=wil(int(hits.sum()), int(len(hits))))
OUT["baseline_f2_5"] = OUT["rules"][name(("close",))]["f2_5"]
json.dump(OUT, open(ROOT / "model/entry_timing.json", "w"), ensure_ascii=False, indent=1)
for k, v in OUT["rules"].items():
    a = v["f2_5"]; print(f"{k:34s} sig {a['n_sig']} fill {a['fill']:.2f} trade {a['n_trade']} exp_t {a['exp_trade'] or 0:+.4f} exp_s {a['exp_signal']:+.4f} {a['ci_signal']} hit {a['hit'] or 0:.3f}")
print("NESTED", OUT["nested"])
