"""숏 레이더 상세 카드 (레벨 맵 · 진입 구간 · 대차 변화 · 이벤트 로그 · 숏 커버 경보 · 공모 전 펌핑 감지).
모든 숫자는 실제 소스 값. 없으면 '데이터 없음'."""
from .ui import esc, px, h
from . import levels as LV

NA = '<span class="muted">데이터 없음</span>'
TAGC = {"과열": "red", "재점화": "yellow", "이탈": "green", "숏 손실권": "red", "돌파 완료": "yellow", "커버 진행 추정": "yellow", "숏 수익권": "green", "현재가 부근": ""}
ZC = {"top": "#ff4d5e", "break": "#fbbf24", "now": "#e5e7eb", "s1": "#60a5fa", "s2": "#3b82f6", "down": "#22c55e"}

def sp(v, d=1):
    return "N/A" if v is None else f"{v:+.{d}f}%"

def _ext(eh):
    """정규장 마감 · 프리 · 애프터 (저/고/마지막)."""
    eh = eh or {}
    cells = []
    rc = eh.get("reg_close") or eh.get("prev_close")
    cells.append(f'<div class="box"><div class="lab">정규장 마감</div><div class="val">{px(rc) if rc else "N/A"}</div><div class="tiny">{"고 " + px((eh.get("regular") or {}).get("hi")) + " · 저 " + px((eh.get("regular") or {}).get("lo")) if eh.get("regular") else ""}</div></div>')
    for k, lab in (("pre", "프리장"), ("post", "애프터")):
        x = eh.get(k) or {}
        if x.get("hi"):
            cells.append(f'<div class="box"><div class="lab">{lab}</div><div class="val">{px(x.get("last") or x["hi"])}</div><div class="tiny">고 {px(x["hi"])} · 저 {px(x.get("lo"))}</div></div>')
        else:
            cells.append(f'<div class="box"><div class="lab">{lab}</div><div class="val muted" style="font-size:13px">데이터 없음</div></div>')
    return '<div class="lv3">' + "".join(cells) + '</div>'

# ---------------------------------------------------------------- 숏 커버 경보
def card_cover(x):
    R = x.get("rad") or {}; ca = R.get("ca"); f = x["f"]
    if not ca:
        return f'<div class="card"><h3>🚨 숏 커버 경보</h3>{NA}{_ext(x.get("eh"))}</div>'
    lv = ca["level"]
    rows = "".join(f'<div class="ev"><div class="n" style="background:{"#ff4d5e" if ok else ("#2a3142" if ok is False else "#3d3210")}">{"✓" if ok else ("·" if ok is False else "?")}</div>'
                   f'<div><b>{esc(name)}</b><div class="tiny">{esc(det)}</div></div></div>' for name, ok, det in ca["checks"])
    tg, reach, nr = ca.get("trigger"), ca.get("reach"), ca.get("next_res")
    price = R.get("price") or f["price"]
    bar = ""
    if tg:
        bar = (f'<div class="between" style="margin-top:10px"><span class="muted">트리거 도달률</span><b>{min(reach, 999):.1f}%</b></div>'
               f'<div class="bar"><div style="width:{min(reach, 100):.1f}%"></div></div><div class="tiny">{px(price)} ÷ 트리거 {px(tg[0])} ({esc(tg[1])})</div>')
    av, fee = f.get("avail"), f.get("fee")
    si = f.get("si"); dtc = f.get("dtc")
    grid = (f'<div class="lv3"><div class="box"><div class="lab">공매도 잔고(공표)</div><div class="val">{LV.fp(si).replace("$", "") if si else "N/A"}</div><div class="tiny">FINRA 2주 단위</div></div>'
            f'<div class="box"><div class="lab">차입 가능</div><div class="val">{"N/A" if av is None else f"{av:,.0f}주"}</div><div class="tiny">IBKR</div></div>'
            f'<div class="box"><div class="lab">대차이자(연)</div><div class="val">{"N/A" if fee is None else f"{fee:.0f}%"}</div><div class="tiny">IBKR</div></div></div>'
            f'<div class="lv3"><div class="box"><div class="lab">대여 이용률</div><div class="val muted" style="font-size:13px">IBKR 미제공</div></div>'
            f'<div class="box"><div class="lab">대여 기관 수</div><div class="val muted" style="font-size:13px">IBKR 미제공</div></div>'
            f'<div class="box"><div class="lab">커버 소요일(DTC)</div><div class="val">{"N/A" if not dtc else f"{dtc:.1f}일"}</div></div></div>')
    return h('<div class="card rc">',
             f'<div class="between"><h3>🚨 숏 커버 경보 레벨 {lv} <span class="muted">/ 5</span></h3><span class="badge {"red" if ca["met"] >= 3 else ("yellow" if ca["met"] >= 2 else "")}">조건 {ca["met"]}/5 충족</span></div>',
             f'<div style="font-size:13px;line-height:1.5;margin:2px 0 6px">{esc(R.get("story") or "")}</div>', rows, bar,
             f'<div class="row" style="margin-top:8px"><div class="box"><div class="lab">트리거</div><div class="val yellow">{px(tg[0]) if tg else "N/A"}</div><div class="tiny">{sp(LV.pct(tg[0], price)) if tg else "위쪽 저항 없음"}</div></div>'
             f'<div class="box"><div class="lab">다음 저항</div><div class="val">{px(nr[0]) if nr else "N/A"}</div><div class="tiny">{(sp(LV.pct(nr[0], price)) + " · " + esc(nr[1])) if nr else "데이터 없음"}</div></div></div>',
             grid, '<h3 style="margin-top:10px">🌙 정규장 · 프리 · 애프터</h3>', _ext(x.get("eh")),
             '<div class="tiny" style="margin-top:6px">레벨 = 5개 조건 중 충족 수(최소 1). 대차 이력이 10/28부터 쌓이는 중이라 이 경보는 아직 <b>과거 검증 전</b>입니다. 이용률·대여 기관 수는 IBKR 무료 데이터에 없어 표시하지 않습니다.</div></div>')

# ---------------------------------------------------------------- 레벨 맵
def card_levels(x):
    R = x.get("rad") or {}; lm = R.get("lm")
    if not lm: return f'<div class="card"><h3>🗺️ 레벨 맵</h3>{NA}</div>'
    s, price = lm["summary"], lm["price"]
    rr = f'1 : {s["rr"]:.1f}' if s.get("rr") else "N/A"
    top = (f'<div class="lv3"><div class="box"><div class="lab">다음 저항</div><div class="val red">{sp(s["res_pct"])}</div><div class="tiny">{px(s["res"]) if s["res"] else "없음"}</div></div>'
           f'<div class="box"><div class="lab">1차 지지 이탈</div><div class="val blue">{sp(s["sup_pct"])}</div><div class="tiny">{px(s["sup"]) if s["sup"] else "없음"}</div></div>'
           f'<div class="box"><div class="lab">위험 : 보상</div><div class="val">{rr}</div><div class="tiny">목표 {px(s["target"]) if s.get("target") else "N/A"}</div></div></div>')
    rows = []
    for z in lm["zones"]:
        lo, hi = z["lo"], z["hi"]
        if lo and hi and abs(hi - lo) < 1e-9:
            rng, pc = px(lo), sp(z["pct_lo"])
        elif lo and not hi: rng, pc = f"{px(lo)} 이상", sp(z["pct_lo"])
        elif hi and not lo: rng, pc = f"{px(hi)} 이하", sp(z["pct_hi"])
        elif lo and hi: rng, pc = f"{px(lo)} ~ {px(hi)}", (sp(z["pct_lo"]) if z["key"] in ("top", "break") else f'{sp(z["pct_lo"])} ~ {sp(z["pct_hi"])}')
        else: rng, pc = "N/A", "N/A"
        now = f' <span class="badge">현재 {px(price)}</span>' if z["key"] == "now" else ""
        tag = f' <span class="badge {TAGC.get(z["tag"], "")}">{esc(z["tag"])}</span>' if z.get("tag") else ""
        rows.append(f'<div class="tr" style="border-left-color:{ZC.get(z["key"], "#2a3142")}"><div class="between"><b>{esc(z["name"])}{tag}{now}</b><span style="font-size:12px">{rng}</span></div>'
                    f'<div class="tiny">현재가 대비 {pc} · {esc(z["why"])}</div></div>')
    return h('<div class="card"><h3>🗺️ 레벨 맵 <span class="muted">(지지·저항 6구간)</span></h3>', top, "".join(rows),
             '<div class="tiny" style="margin-top:4px">근거: 최근 일봉 고가·저가, 5/10/20/60/120일 이동평균, 메우지 않은 갭, 프리·애프터 고저, 공모가·워런트 행사가(SEC). 가까운 가격끼리 묶어 구간으로 표시 (yfinance · SEC EDGAR).</div></div>')

# ---------------------------------------------------------------- 진입 구간
def card_entry(x):
    R = x.get("rad") or {}; ez = R.get("ez")
    if not ez: return f'<div class="card"><h3>🎯 가격대별 숏 진입 구간 (추정)</h3>{NA} — FINRA 공매도 거래량이 부족합니다.</div>'
    rows = []
    for b in ez["bands"]:
        col = "#22c55e" if (b["pl"] or 0) > 0 else "#ff4d5e"
        rows.append(f'<div class="tr {"profit" if (b["pl"] or 0) > 0 else "loss"}"><div class="between"><b>{px(b["lo"])} ~ {px(b["hi"])} <span class="badge {TAGC.get(b["tag"], "")}">{esc(b["tag"])}</span></b>'
                    f'<span style="font-size:12px">숏 손익 <b style="color:{col}">{sp(b["pl"])}</b></span></div>'
                    f'<div class="bar g" style="height:6px"><div style="width:{min(b["share"], 100):.0f}%;background:{col}"></div></div>'
                    f'<div class="tiny">물량 비중 {"1% 미만" if b["share"] < 1 else f"{b["share"]:.0f}%"} · 평균 진입 {px(b["vwap"])} · 공매도 비율 {b["ratio"]:.0f}% · {esc(b["days"])}</div></div>')
    o = ez.get("offer")
    ol = (f'<div class="gapbox">📌 <b>공급 기준선</b> {px(o["price"])} ({esc(o.get("form") or "")} {esc(o.get("date") or "")}) — 공모 참여자 기준 현재 {sp(o["gain"])} '
          f'{"수익 → 매도(공급) 나올 수 있음" if o["gain"] > 0 else "손실"} {f"<a href={chr(34)}{o["url"]}{chr(34)} target=_blank>원문</a>" if o.get("url") else ""}</div>') if o else ""
    return h('<div class="card"><h3>🎯 가격대별 숏 진입 구간 <span class="badge yellow">추정</span></h3>',
             f'<div class="row"><div class="box"><div class="lab">숏 평균 진입(추정)</div><div class="val">{px(ez["avg"])}</div><div class="tiny">숏 입장 {sp(ez["avg_pl"])}</div></div>'
             f'<div class="box"><div class="lab">손실권 숏 비중</div><div class="val {"red" if ez["loss_share"] >= 50 else ""}">{ez["loss_share"]:.0f}%</div><div class="tiny">현재가보다 싸게 판 숏</div></div></div>',
             ol, "".join(rows),
             f'<div class="tiny" style="margin-top:4px">계산: FINRA 일별 공매도 거래량 × 그날 평균가((고+저+종)/3), {esc(ez["from"])}~{esc(ez["to"])} {ez["n_days"]}거래일. '
             f'FINRA는 하루 늦게 나와 마지막 날짜가 {esc(ez["to"])}입니다. 실제 체결가별 분포가 아니고, 공매도 거래량은 잔고(남아 있는 숏)와 다릅니다.</div></div>')

# ---------------------------------------------------------------- 대차비용 변화 + 이벤트 로그
def card_borrow_log(x):
    R = x.get("rad") or {}; br = R.get("br"); ev = R.get("ev") or []
    if br:
        trs = "".join(f'<tr style="{"background:rgba(255,77,94,.12)" if r["jump"] else ""}"><td>{esc(r["et"])}</td><td>{esc(r["kst"])}</td>'
                      f'<td>{"N/A" if r["fee"] is None else f"{r["fee"]:.1f}%"}</td><td>{"N/A" if r["avail"] is None else f"{r["avail"]:,.0f}"}</td>'
                      f'<td>{"".join(f"<span class={chr(34)}badge red{chr(34)}>{esc(j)}</span>" for j in r["jump"])}</td></tr>' for r in br)
        tb = f'<table class="t"><tr><th>미국 동부(ET)</th><th>한국(KST)</th><th>대차이자</th><th>차입 가능</th><th></th></tr>{trs}</table>'
    else:
        tb = f'<div class="tiny">IBKR 대차 목록에 없음 — {NA}</div>'
    evs = "".join(f'<div class="ev"><div class="n" style="{"background:#ff4d5e" if k == "트리거" else ""}">{i}</div><div class="d">{esc(d)}</div>'
                  f'<div><span class="badge">{esc(k)}</span>{esc(t)}{f" <a href={chr(34)}{u}{chr(34)} target=_blank>원문</a>" if u else ""}</div></div>'
                  for i, (_, d, k, t, u) in enumerate(ev, 1))
    return h('<div class="card"><h3>💸 대차비용 변화 <span class="muted">(값이 바뀐 시점만)</span></h3>', tb,
             '<div class="tiny">출처 IBKR 공개 대차 파일 · 빨간 줄 = 급변 (이자 ±20%p 또는 1.5배, 차입 0, 수량 절반 이하)</div>',
             '<h3 style="margin-top:12px">📜 이벤트 로그 <span class="muted">(최근 10일)</span></h3>', evs or f'<div class="tiny">{NA}</div>',
             '<div class="tiny">가격(일봉 ±15% 이상) · SEC 공시 · 뉴스(Yahoo) · 대차 급변 · 시간외 ±8% · 지금 트리거 상태</div></div>')

# ---------------------------------------------------------------- 공모 전 펌핑 감지
def card_offer(x):
    R = x.get("rad") or {}; o = R.get("off")
    if o is None: return f'<div class="card"><h3>🧯 공모·상장 위험 감지</h3>{NA} (SEC 조회 실패)</div>'
    if not o.get("source_ok"): return f'<div class="card"><h3>🧯 공모·상장 위험 감지</h3><div class="tiny">SEC EDGAR에서 이 종목을 찾지 못했어요 — {NA}</div></div>'
    tags = "".join(f'<span class="badge {"red" if t in ("공모 전 펌핑 주의", "상장 유지 미달", "현금 부족", "$1 미만") else "yellow"}">{esc(t)}</span>' for t in o["tags"])
    items = "".join(f'<div class="tr mixed"><div class="between"><b>{esc(it["title"])}</b><span class="tiny">{esc(it.get("date") or "")}</span></div>'
                    f'<div class="tiny">{esc(it["why"])}{f" <a href={chr(34)}{it["url"]}{chr(34)} target=_blank>원문</a>" if it.get("url") else ""}</div></div>' for it in o["items"])
    pen = '<div class="tiny red" style="margin-top:4px">점수 반영: 가격 미정 S-1/F-1 대기 → 종합점수 −2 (과거 검증: 성공률 34.1% vs 36.9%, 효과 작음)</div>' if x["f"].get("reg_pending") else ""
    est = o.get("est")
    el = f'<div class="tiny">💰 예상 공모 규모 약 ${est["amount"] / 1e6:,.1f}M ({esc(est["how"])}, {esc(est["src"])})</div>' if est and est.get("amount") else ""
    body = (tags and f'<div class="chips">{tags}</div>') + items + el if (o["tags"] or o["items"]) else '<div class="tiny">✅ 최근 공모 대기·상장 유지 미달·ATM 증자 서류 없음 (SEC EDGAR 기준)</div>'
    return h('<div class="card"><h3>🧯 공모 전 펌핑 · 상장 위험 감지</h3>', body, pen,
             '<div class="tiny" style="margin-top:4px">S-1/F-1 대기(424B 없음) · 효력 발생 · ATM(424B5) · 셸프 · 8-K 3.01 상장 유지 미달·기한 · $1 미만 일수 · 현금 런웨이 · 공모가/워런트 행사가 (SEC EDGAR 원문 자동 판독, 틀릴 수 있음)</div></div>')

# ---------------------------------------------------------------- 🧬 성공 패턴 일치 (참고)
def card_pattern(x):
    from . import pattern as PT
    pm = (x.get("rad") or {}).get("pat")
    if not pm: return f'<div class="card"><h3>🧬 성공 패턴 일치</h3>{NA}</div>'
    rows = "".join(f'<div class="tr"><div class="between"><span>{"✅" if it["on"] else "▫️"} {esc(it["label"])}</span><span class="tiny">{esc(it["val"])}</span></div></div>' for it in pm["hits"])
    col = "red" if pm["n"] >= 4 else ("yellow" if pm["n"] >= 3 else "")
    sp_ = ""
    if pm.get("spike") is not None:
        sp_ = (f'<div class="tiny" style="margin-top:6px">📊 과거 비슷한 자리(가격 4요소 {pm["k4"]}/4, {pm.get("n_hist") or 0:,}건): 5거래일 안 <b>+30% 터치 {pm["spike"] * 100:.0f}%</b> '
               f'(전체 평균 {pm["spike_base"] * 100:.0f}%) · 그런데 5일 뒤 종가 중앙값 {pm["fc5_med"] * 100:+.1f}% — 튀면 짧게 익절, 들고 가면 손해 나기 쉬움</div>')
    app_ = ""
    if pm.get("app_hit") is not None:
        app_ = f'<div class="tiny">앱 성공 기준(재점화 레벨 도달) 3개 이상 일치: {pm["app_hit"] * 100:.0f}% vs 평균 {pm["app_base"] * 100:.0f}% → 그래서 점수에는 넣지 않았어요</div>'
    return h(f'<div class="card"><div class="between"><h3>🧬 성공 패턴 일치</h3><span class="badge {col}">{pm["n"]}/{pm["m"]} · 참고</span></div>',
             '<div class="tiny" style="margin-bottom:4px">커뮤니티 성공 사례 14건(급락 → 프리/애프터 급등)의 직전 공통점과 비교. 종합점수·확률에는 반영 안 함.</div>',
             rows, sp_, app_,
             '<div class="tiny">5분봉 확인된 13건 중 11건은 프리장·애프터에서 먼저 터짐 (과거 시간외 데이터가 없어 검증은 못 함) · 자기 보고된 성공 사례라 실패 사례는 빠져 있음</div></div>')

# ---------------------------------------------------------------- 💣 희석·상폐 구조 (SURG 글 방식, 참고)
def card_structure(x):
    from . import structure as ST
    sm = (x.get("rad") or {}).get("st")
    if not sm: return f'<div class="card"><h3>💣 희석·상폐 구조</h3>{NA}</div>'
    vals = ST.values(sm)
    rows = "".join(f'<div class="tr"><div class="between"><span>{"✅" if sm["signs"].get(k) else ("❔" if sm["signs"].get(k) is None else "▫️")} {esc(lab)}</span></div>'
                   f'<div class="tiny">{esc(vals.get(k) or "데이터 없음")}</div></div>' for k, lab in ST.SIGNS)
    col = "red" if sm["n"] >= 4 else ("yellow" if sm["n"] >= 2 else "")
    return h(f'<div class="card"><div class="between"><h3>💣 희석·상폐 구조</h3><span class="badge {col}">{sm["n"]}/{sm["m"]} · 참고</span></div>',
             '<div class="tiny" style="margin-bottom:4px">전환사채 물량·주식수 급증·현금 런웨이·$0.10 상폐선·베이비 셸프·분기보고서 마감·호재 반응 약화 (SEC XBRL·공시 기준, ❔ = 데이터 없음)</div>',
             rows, warn_block((x.get("rad") or {}).get("ew")),
             '<div class="tiny" style="margin-top:6px">📊 과거 검증: 이 신호들이 켜진 날은 5일 안 +30% 터치는 조금 잦지만(넓은 표본) 5일 뒤 종가는 더 나쁘고, 앱 성공 기준으로는 오히려 낮음 → 점수에 넣지 않음. '
             '"터지면 짧게, 들고 가지 말기" 용도로만 보세요. 전환사채는 XBRL 유동분 위주라 과소추정될 수 있음. 시총·베이비 셸프 한도는 최신 주식수 기준(13D·신고서·6-K 공시 주식수와 그 뒤 발행 > 시세 > 마지막 10-Q). 현금·월 소모는 companyfacts 보다 새 6-K/10-Q XBRL 이 있으면 그 값.</div></div>')

def warn_block(W):
    """참고 경고 4종 (역분할 주총·내부자 부채→주식 교환·$0.10 10일 연속·상폐 결정/청문)."""
    if W is None: return '<div class="tr"><div class="tiny">⚠️ 참고 경고(역분할 주총·부채 교환·$0.10·상폐 청문): 데이터 없음</div></div>'
    if not W: return '<div class="tr"><div class="tiny">⚠️ 참고 경고: 해당 없음 (최근 150일 공시·종가 기준)</div></div>'
    from . import events as EV
    items = "".join(f'<div class="tiny">• {esc(w["text"])} <span class="badge {"red" if w.get("scored") else ""}">{"점수 반영" if w.get("scored") else "참고"}</span>'
                    + (f' <a href="{esc(w["url"])}" target="_blank">원문</a>' if w.get("url") else "") + '</div>' for w in W)
    return f'<div class="tr"><div class="tiny"><b>⚠️ 참고 경고</b> — {esc(EV.study_note())}</div>{items}</div>'


# ---------------------------------------------------------------- 🏦 자금줄·세력 구조 (참고)
def card_finance(x):
    from . import finance as FZ
    F = (x.get("rad") or {}).get("fin")
    if not F: return f'<div class="card"><h3>🏦 자금줄·세력 구조</h3>{NA}</div>'
    vals = FZ.values(F)
    rows = "".join(f'<div class="tr"><div class="between"><span>{"✅" if F["signs"].get(k) else ("❔" if F["signs"].get(k) is None else "▫️")} {esc(lab)}</span></div>'
                   f'<div class="tiny">{esc(vals.get(k) or "데이터 없음")}</div></div>' for k, lab in FZ.SIGNS)
    an = FZ.analog_text(F)
    an_ = ('<div class="tr"><div class="tiny"><b>같은 자금줄 다른 종목 과거</b> (분할 조정 일봉, 상폐 종목 일부 빠짐)<br>' + "<br>".join(esc(a) for a in an) + '</div></div>') if an else ""
    wr = F.get("warr")
    wr_ = f'<div class="tr"><div class="tiny">🎟️ 워런트 {wr["w"]:,.0f}주 = 주식수의 {wr["pct"]:.0f}% ({esc(wr["end"])} 기준, XBRL)</div></div>' if wr else '<div class="tr"><div class="tiny">🎟️ 워런트 오버행: 데이터 없음</div></div>'
    tm = F.get("terms") or {}
    tm_ = ""
    if tm:
        bits = []
        if tm.get("shares"): bits.append(f'재판매 등록 {tm["shares"]:,.0f}주' + (f' = 현재 주식수(yfinance, 늦게 반영될 수 있음)의 <b>{tm["pct_out"]:.0f}%</b>' if tm.get("pct_out") else ""))
        if tm.get("pct"): bits.append("본문 가격 조건: 최저가·VWAP·종가의 " + "·".join(f"{v:g}" for v in tm["pct"]) + "% (ELOC 매수가·전환가 섞여 있을 수 있음)")
        if tm.get("commit"): bits.append(f'약정 한도 ${tm["commit"] / 1e6:,.1f}M')
        tm_ = f'<div class="tr"><div class="tiny">📄 ELOC 등록서류({esc(tm.get("filed") or "")}) 본문: {" · ".join(bits)} (문장 자동 추출, 틀릴 수 있음)</div></div>' if bits else ""
    col = "red" if F["n"] >= 4 else ("yellow" if F["n"] >= 2 else "")
    S = FZ.study(); note = S.get("note_ko") or "검증 결과 파일 없음"
    snap = f'스냅샷 {esc((F.get("built") or "")[:10]) or "없음"}' + ("" if F.get("has_snap") else " · 자금줄·ELOC 스냅샷 없음(❔)")
    return h(f'<div class="card"><div class="between"><h3>🏦 자금줄·세력 구조</h3><span class="badge {col}">{F["n"]}/{F["m"]} · 참고</span></div>',
             '<div class="tiny" style="margin-bottom:4px">전환사채·ELOC 자주 쓰는 투자자 공시 · ELOC 재판매 등록과 효력(EFFECT) · 역분할 횟수 · 현재가 위 매물대 '
             f'(SEC 전문검색·제출목록, yfinance · {snap}, ❔ = 데이터 없음)</div>',
             rows, tm_, an_, wr_,
             f'<div class="tiny" style="margin-top:6px">📊 과거 검증: {esc(note)}</div></div>')

# ---------------------------------------------------------------- 복사 글용
def copy_lines(x):
    R = x.get("rad") or {}; L = []
    eh = x.get("eh") or {}
    ex = []
    for k, lab in (("pre", "프리"), ("post", "애프터")):
        v = eh.get(k) or {}
        if v.get("hi"): ex.append(f"{lab} {px(v.get('lo'))}~{px(v['hi'])} (마지막 {px(v.get('last') or v['hi'])})")
    L.append("🌙 " + (" / ".join(ex) if ex else "프리/애프터 데이터 없음"))
    lm = R.get("lm")
    if lm:
        s = lm["summary"]
        L.append(f"🗺️ 다음 저항 {px(s['res']) if s['res'] else 'N/A'} ({sp(s['res_pct'])}) · 1차 지지 {px(s['sup']) if s['sup'] else 'N/A'} ({sp(s['sup_pct'])})"
                 + (f" · 위험:보상 1:{s['rr']:.1f}" if s.get("rr") else ""))
    ca = R.get("ca")
    if ca:
        tg = ca.get("trigger")
        L.append(f"🚨 숏 커버 경보 {ca['level']}/5 (조건 {ca['met']}/5)" + (f" · 트리거 {px(tg[0])} 도달률 {ca['reach']:.0f}%" if tg else ""))
    ez = R.get("ez")
    if ez and ez.get("avg"): L.append(f"🎯 숏 평균 진입(추정) {px(ez['avg'])} · 손실권 숏 {ez['loss_share']:.0f}%" + (f" · 공급 기준선 {px(ez['offer']['price'])} ({sp(ez['offer']['gain'])})" if ez.get("offer") else ""))
    br = R.get("br")
    if br:
        r = br[0]; L.append(f"💸 대차이자 {r['fee']:.0f}% · 차입 가능 {r['avail']:,.0f}주 ({r['kst']} KST)" + (f" · {', '.join(r['jump'])}" if r["jump"] else ""))
    try:
        from . import pattern as PT
        pl = PT.line(R.get("pat"))
        if pl: L.append(pl)
    except Exception: pass
    try:
        from . import finance as FZ
        fl = FZ.line(R.get("fin"))
        if fl: L.append(fl)
    except Exception: pass
    try:
        from . import structure as ST
        sl = ST.line(R.get("st"))
        if sl: L.append(sl)
        if R.get("st"):
            v = ST.values(R["st"]); L.append("   " + v["runway"] + " · " + v["shgrow"])
    except Exception: pass
    for w in R.get("ew") or []:
        L.append(f"⚠️ {w['text']} [{'점수 반영' if w.get('scored') else '참고'}]")
    o = R.get("off")
    if o and o.get("tags"): L.append("🧯 공모·상장 위험: " + ", ".join(o["tags"]) + (f" — {o['items'][0]['why'][:90]}" if o.get("items") else ""))
    return L
