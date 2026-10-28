"""숏 레이더 — 나스닥 소형주 급등 탐지 (개인용). 실행: streamlit run app.py"""
import json, math, os, re, datetime as dt
import numpy as np, pandas as pd
import streamlit as st
from core import db, params as P, sources as src, model, live, scan, ui, toss, alerts as AL, cloud
from core.ui import esc, px, pct, num, h

st.set_page_config(page_title="숏 레이더", page_icon="📉", layout="centered", initial_sidebar_state="collapsed")
st.markdown(ui.CSS, unsafe_allow_html=True)

def _gate():
    """선택: st.secrets 에 APP_PASSWORD 가 있으면 비밀번호를 맞혀야 볼 수 있음 (클라우드 공개 주소 보호).
    한 번 맞히면 이 폰/브라우저에 1년짜리 쿠키(비밀번호 자체가 아닌 해시)를 남겨 다음부터는 묻지 않음."""
    import hmac, hashlib
    pw = AL._secret("APP_PASSWORD")
    if not pw: return
    tok = hmac.new(str(pw).encode(), b"shortradar-remember-v1", hashlib.sha256).hexdigest()
    try:
        ck = st.context.cookies.get("sr_auth")
        ck = ck if isinstance(ck, str) else ""
    except Exception: ck = ""
    try:
        qk = st.query_params.get("k")
        qk = qk if isinstance(qk, str) else ""
    except Exception: qk = ""
    has_ck = bool(ck) and hmac.compare_digest(ck, tok)
    has_qk = bool(qk) and hmac.compare_digest(qk, tok)   # 홈 화면 아이콘 주소에 넣어 둔 열쇠 (쿠키가 막히는 폰 대비)
    if has_ck or has_qk or st.session_state.get("auth_ok"):
        st.session_state["auth_ok"] = True
        ui.AUTHQ = f"k={tok}&"
        if not has_qk:
            try: st.query_params["k"] = tok      # 지금 주소에 열쇠를 붙여 둠 → 이 화면에서 홈 화면 추가하면 다음부터 안 물어봄
            except Exception: pass
        if not has_ck:   # 비밀번호를 맞힌 뒤 첫 화면에서 쿠키 저장 (다음부터 안 물어봄)
            import streamlit.components.v1 as components
            components.html(f"""<script>try{{window.parent.document.cookie="sr_auth={tok}; max-age=31536000; path=/; secure; samesite=lax";}}catch(e){{}}</script>""", height=0)
        return
    st.markdown("### 🔒 숏 레이더")
    v = st.text_input("비밀번호", type="password")
    if v:
        if hmac.compare_digest(v.encode(), str(pw).encode()):
            st.session_state["auth_ok"] = True; st.rerun()
        st.error("비밀번호가 틀렸습니다.")
    st.stop()
_gate()

def pwa_head():
    """홈 화면 설치용 메타 태그를 부모 문서 <head> 에 주입 (Streamlit 은 head 편집 불가 → same-origin iframe 스크립트)."""
    import streamlit.components.v1 as components
    components.html("""<script>
    (function(){ try {
      const d = window.parent.document, head = d.head;
      const add = (tag, attrs) => { const sel = tag + Object.entries(attrs).filter(([k]) => k==='rel'||k==='name').map(([k,v]) => `[${k}="${v}"]`).join('');
        let el = head.querySelector(sel); if (!el) { el = d.createElement(tag); head.appendChild(el); } for (const [k,v] of Object.entries(attrs)) el.setAttribute(k, v); };
      add('link', {rel:'manifest', href:'/app/static/manifest.json'});
      add('link', {rel:'apple-touch-icon', href:'/app/static/icon-180.png'});
      add('meta', {name:'apple-mobile-web-app-capable', content:'yes'});
      add('meta', {name:'mobile-web-app-capable', content:'yes'});
      add('meta', {name:'apple-mobile-web-app-status-bar-style', content:'black-translucent'});
      add('meta', {name:'apple-mobile-web-app-title', content:'숏 레이더'});
      add('meta', {name:'application-name', content:'숏 레이더'});
      add('meta', {name:'theme-color', content:'#0b0d12'});
      const vp = head.querySelector('meta[name="viewport"]'); if (vp) vp.setAttribute('content', 'width=device-width, initial-scale=1, viewport-fit=cover, maximum-scale=1');
    } catch (e) {} })();
    </script>""", height=0)
pwa_head()

qp = st.query_params
PAGE = qp.get("p", "home")
TICK = (qp.get("t") or db.get_setting("last_ticker", "SOUN") or "SOUN").upper()
p = P.load()
WATCH = db.get_setting("watchlist", ["SOUN", "OCGN"])
REFRESH_MIN = int(db.get_setting("refresh_min", 2))
LIVE_ON = bool(db.get_setting("live_on", True))
H_N, TGT = int(p["horizon_days"]), p["target_pct"]
GOAL = model.goal_text()  # 선택된 성공 정의 (관리 탭) — 확률 카드 문구

@st.cache_resource(show_spinner=False)
def _boot_lock():
    import threading
    return threading.Lock()

def bootstrap():
    """빈 DB(새 설치·Streamlit Cloud)일 때 1회: 무료 소스로 초기 데이터를 만든다. 진행 상황을 화면에 표시."""
    if db.kv_get("bootstrap_done"): return
    if len(db.q("SELECT 1 FROM prices WHERE ticker='QQQ' LIMIT 1")) and len(db.q("SELECT 1 FROM scans WHERE kind='screen' LIMIT 1")):
        db.kv_set("bootstrap_done", True); return
    lock = _boot_lock()
    if not lock.acquire(blocking=False):
        st.info("다른 창에서 초기 데이터를 만드는 중입니다. 잠시 후 새로고침하세요."); st.stop()
    try:
        with st.status("처음 실행: 무료 데이터로 초기 데이터베이스를 만드는 중 (보통 3~10분, 한 번만)", expanded=True) as stt:
            steps = [("1/4 나스닥 종목 목록", lambda: src.fetch_universe()),
                     ("2/4 시장 지수 · 관심종목 일봉", lambda: [src.fetch_prices(t, "2y") for t in ["QQQ", "IWM"] + WATCH] and [src.refresh_ticker(t) for t in WATCH]),
                     ("3/4 RegSHO Threshold 목록", lambda: src.update_threshold(5))]
            for lab, fn in steps:
                st.write(lab)
                try: fn()
                except Exception as e: st.write(f"  건너뜀: {e!r}"[:160])
            st.write("4/4 초소형주 스캔 (유니버스 일봉 일괄 다운로드 → 상위 종목 정밀분석)")
            bar = st.progress(0.0, "준비 중...")
            try: scan.run_scan(p, top_k=min(80, int(p["scan_top_k"])), progress=lambda fr, t: bar.progress(min(fr, 1.0), f"분석 중 {t}"))
            except Exception as e: st.write(f"  스캔 실패: {e!r}"[:160])
            db.kv_set("bootstrap_done", True)
            stt.update(label="초기 데이터 준비 완료", state="complete", expanded=False)
    finally:
        lock.release()
def cloud_sync():
    """클라우드: GitHub Actions 가 매일 만든 최신 DB 를 받아 씀 (15분마다 확인, 새 것이 있을 때만 다운로드)."""
    if not cloud.enabled(): return
    ph = st.empty()
    r = cloud.sync_db(progress=lambda m: ph.info("☁️ " + m))
    ph.empty()
    if r == "updated": st.cache_data.clear()
    elif r.startswith("error"): st.caption(f"☁️ 클라우드 데이터 동기화 실패 — 기존 데이터로 표시 ({r[6:80]})")
    st.session_state["cloud_sync"] = r
cloud_sync()
bootstrap()

def md(x):
    # 줄바꿈+들여쓰기가 마크다운 코드블록으로 해석되지 않도록 한 줄로 정리하고 블록 요소로 감쌈
    x = re.sub(r"\n\s*", " ", x)
    if not x.lstrip().startswith("<div"): x = "<div>" + x + "</div>"
    st.markdown(x, unsafe_allow_html=True)
def link(t, label=None): return f'<a href="?{ui.AUTHQ}p=stock&t={t}" target="_self" style="color:inherit;text-decoration:none">{label or t}</a>'

@st.cache_data(ttl=86400, show_spinner=False)
def _turl(t, mode):
    return toss.url(t, mode)

def turl(t): return _turl(str(t).upper(), db.get_setting("toss_mode", "onelink"))

def tsb(t, big=False):
    """토스증권 바로가기 버튼 (새 탭 · 앱이 있으면 앱으로)."""
    lab = "토스증권에서 열기 ↗" if big else "토스↗"
    return f'<a class="tsb{" big" if big else ""}" href="{esc(turl(t))}" target="_blank" rel="noopener">{lab}</a>'

def tlink(t, label=None): return link(t, label) + tsb(t)

def warm_toss(tickers):
    """화면에 나올 티커들의 토스 코드를 병렬로 미리 확인 (캐시 후엔 즉시)."""
    try: toss.prefetch(list(tickers))
    except Exception: pass

EMBED = {"on": False}   # 다른 페이지 안에 접힌 섹션으로 렌더링 중이면 상단바/면책문구 생략

def disclaimer():
    if not EMBED["on"]: md(ui.DISCLAIMER)

def embedded(fn, *a):
    EMBED["on"] = True
    try: fn(*a)
    finally: EMBED["on"] = False

def topbar(title, sub=""):
    if EMBED["on"]: return
    sess, _ = live.session_now()
    badge = f'<span class="badge {"live" if sess != "closed" and LIVE_ON else ""}">{"● 실시간" if sess != "closed" and LIVE_ON else "○ " + live.SESSION_KO[sess]}</span>'
    md(f'<div class="topbar"><div class="brand">{esc(title)}<small>{esc(sub)}</small></div><div>{badge}</div></div>')

@st.cache_resource(ttl=55, show_spinner=False)
def snap(t, pkey):
    if len(src.get_prices(t)) < 30:
        src.refresh_ticker(t); src.fetch_info(t)
    return live.snapshot(t, json.loads(pkey))

def get_snap(t):
    return snap(t.upper(), json.dumps(p, sort_keys=True))

def narrative(x):
    f, s, m = x["f"], x["s"], x["meta"]
    lv = s["level"]
    if not m: return "데이터가 부족해 진입 구간을 추정하지 못했습니다."
    rl = m["reignite"]; dist = (rl / f["price"] - 1) * 100
    head = {5: "숏 재축적이 강하게 진행 중입니다.", 4: "숏 물량이 다시 쌓이며 압력이 커지고 있습니다.", 3: "숏 재축적 조짐이 보입니다.",
            2: "숏 압력은 보통 수준입니다.", 1: "뚜렷한 숏 재축적 신호가 없습니다."}[lv]
    body = f" 추정 숏 잔고의 {m['loss_pct']:.0f}%가 손실권, {m['profit_pct']:.0f}%가 수익권입니다. 재점화 레벨 {px(rl)}까지 {dist:+.1f}% — 돌파하면 위쪽 차수 숏이 손실권으로 넘어가 커버(매수) 압력이 생길 수 있습니다(추정)."
    if f.get("si_chg") is not None: body += f" 최근 공표 숏 잔고 {f['si_chg']:+.1f}%."
    return head + body

def prob_card(x, compact=False):
    pr = x["prob"]
    if pr.get("prob") is None:
        main = '<span class="yellow">데이터 부족</span>' if pr.get("msg") == "데이터 부족" else f'<span class="muted" style="font-size:20px">{esc(pr.get("msg"))}</span>'
        note = f'표본 {pr.get("n", 0)}개 &lt; 최소 {int(p["min_samples"])}개 · 관리 → 타임머신 검증 실행 필요' if pr.get("msg") == "데이터 부족" else "추적 → 타임머신에서 검증을 1회 이상 실행하면 확률이 보정됩니다."
    else:
        c = "red" if pr["prob"] >= 25 else ("yellow" if pr["prob"] >= 10 else "")
        main = f'<span class="{c}">{pr["prob"]:.0f}%</span>'
        if pr.get("source") == "research":
            rs = x["s"].get("research") or {}
            note = (f'성공 정의: {esc((model.research() or {}).get("def_label") or "고정 +30%/5일(기존)")} · 정의별 재학습 · 검증 모델(워크포워드 5폴드 · 표본외 {pr["n"]:,}건) · 표본외 AUC {pr["auc"]:.2f} · Brier {pr["brier"]:.3f} · isotonic 보정 · '
                    f'경보 기준 = 상위 {rs.get("top_pct", 5):.0f}% (≈{rs.get("thr", 0) * 100:.0f}% 이상)')
        else: note = (f'타임머신 #{pr["run_id"]} 학습구간 · 점수구간 {pr["bin"][0]:.0f}~{pr["bin"][1]:.0f} · 표본 {pr["n"]}개 중 {pr["hits"]}회 적중 (라플라스 보정)'
                + (f' · 검증구간 Brier {pr["brier"]:.3f} (n={pr.get("val_n")})' if pr.get("brier") is not None else ""))
    if compact:
        return f'<div class="between"><div class="muted">{esc(GOAL)} 확률</div><div class="mid">{main}</div></div><div class="tiny">{note}</div>'
    return (f'<div class="card prob"><div class="muted">{esc(x["ticker"])} · {esc(GOAL)} 확률 (추정)</div><div class="pct">{main}</div>'
            f'<div class="tiny">{note}</div><div class="tiny">점수 {x["s"]["score"]:.0f}/100 · 동시 신호 {x["s"]["confluence"]}개</div>{exit_box(x)}</div>')

def exit_box(x):
    last = x["eh"].get("last") or x["f"]["price"]
    rl, sp, tpp, stop, tp, tag, er = key_levels(x, last)
    lv = (f'<div class="lv3"><div class="box"><div class="lab">손절 ({tag})</div><div class="val blue">{px(sp)}</div><div class="tiny">-{stop:.0f}%</div></div>'
          f'<div class="box"><div class="lab">익절 ({tag})</div><div class="val red">{px(tpp) if tpp else "N/A"}</div><div class="tiny">{f"+{tp:.0f}%" if tp else ""}</div></div>'
          f'<div class="box"><div class="lab">재점화 (추정)</div><div class="val yellow">{px(rl)}</div><div class="tiny">{pct((rl / last - 1) * 100) if rl else "N/A"}</div></div></div>')
    if er and er["positive"]:
        msg = f'검증된 청산 규칙: 표본외 기대값 {er["oos"]["exp"] * 100:+.2f}% / 거래 (n={er["oos"]["n"]}).'
    elif er:
        o = er["oos"]
        msg = (f'청산 규칙 검증 결과: 학습 구간에서 고른 규칙의 표본외 기대값이 {o["exp"] * 100:+.2f}% (95% CI {o["ci"][0] * 100:+.1f}~{o["ci"][1] * 100:+.1f}%, n={o["n"]}) 로 '
               f'<b>수익이 검증된 규칙은 없음</b>. 위 손절/익절은 기본 설정값(참고용)입니다. 자세히: docs/RESEARCH.md')
    else:
        msg = "청산 규칙 검증 기록 없음 (scripts/research.py 실행 필요). 위 값은 기본 설정값(참고용)."
    return lv + f'<div class="tiny" style="margin-top:6px">{msg}</div>'


def live_line(x):
    eh = x["eh"]; sess = live.SESSION_KO[x["session"]]
    return (f'<div class="tiny">{"<span class=\'badge live\'>실시간</span>" if x["session"] != "closed" and LIVE_ON else "<span class=\'badge\'>" + sess + "</span>"}'
            f' 갱신 {x["updated_kst"]} KST · 마지막 체결봉 {x["last_bar_kst"] or "N/A"} KST · {sess} · yfinance 무료 데이터는 지연될 수 있음</div>')

# ---------------------------------------------------------------- 카드들
def card_alert(x):
    f, s, m, eh, info = x["f"], x["s"], x["meta"], x["eh"], x["info"]
    last = eh.get("last") or f["price"]; prev = eh.get("prev_close") or info.get("regularMarketPreviousClose")
    chg = (last / prev - 1) * 100 if prev else f["chg1"]
    rl = m.get("reignite"); reach = min(last / rl * 100, 100) if rl else 0
    hi21 = m.get("hi21")
    si_b = f'<span class="badge {"red" if (f.get("si_chg") or 0) > 0 else "green"}">SI {pct(f.get("si_chg"))}</span>' if f.get("si_chg") is not None else '<span class="badge">SI N/A</span>'
    ext = []
    if eh.get("pre"): ext.append(f'프리 {px(eh["pre"]["lo"])}~{px(eh["pre"]["hi"])}')
    if eh.get("post"): ext.append(f'애프터 {px(eh["post"]["lo"])}~{px(eh["post"]["hi"])}')
    reg_close = eh.get("reg_close") or (eh.get("prev_close") if x["session"] in ("pre",) else None)
    si_line = (f'{num(m["total_rem"])}주 · 유통 대비 {pct(f.get("si_float"), 1, False)}' if m else "N/A")
    dchg = f.get("si_chg")
    return h(f'<div class="card rc">',
             f'<div class="between"><div><div class="mid">{esc(x["ticker"]) if x.get("hist") else cpk(x["ticker"], copy_text(x["ticker"], x), href=False)}{"" if x.get("hist") else tsb(x["ticker"])} <span class="muted">{esc((info.get("shortName") or "")[:22])}</span></div>',
             f'<div class="big">{px(last)} <span class="{ui.cls(chg).replace("green", "blue")}" style="font-size:16px">{pct(chg, 2)}</span></div>',
             f'<div class="tiny">정규장 종가 {px(reg_close or f["price"])} · {" · ".join(ext) if ext else "프리/애프터 데이터 없음"}</div></div></div>',
             f'<div class="sumbig">▸ {esc(x.get("summary") or "")}</div>',
             f'<h3 style="margin-top:10px">🚨 숏 재축적 경보 레벨 {s["level"]} <span class="muted">/ 5</span> {si_b}</h3>',
             f'<div style="font-size:13px;line-height:1.5">{esc(x.get("narr") or narrative(x))}</div>',
             f'<div class="between" style="margin-top:10px"><span class="muted">재점화 레벨 도달률</span><b>{reach:.1f}%</b></div>',
             f'<div class="bar"><div style="width:{reach:.1f}%"></div></div>',
             f'<div class="tiny">{px(last)} / {px(rl)} (현재가 ÷ 재점화 레벨)</div>',
             f'<div class="row" style="margin-top:8px"><div class="box"><div class="lab">재점화 레벨</div><div class="val yellow">{px(rl)}</div><div class="tiny">{pct((rl / last - 1) * 100 if rl else None)}</div></div>',
             f'<div class="box"><div class="lab">21일 고점 재시험</div><div class="val">{px(hi21)}</div><div class="tiny">{pct((hi21 / last - 1) * 100 if hi21 else None)}</div></div></div>',
             f'<div class="box" style="margin-top:8px"><div class="lab">추정 숏 잔고 (추정)</div><div class="val">{si_line}</div>',
             f'<div class="tiny">최근 공표 대비 {pct(dchg)} · 공표 SI {num(f.get("si"))} (FINRA·Nasdaq, 결제일+8영업일 반영) · DTC {f.get("dtc", 0):.1f}일</div></div>',
             '</div>')

def card_borrow(x):
    f, b = x["f"], x["b"]
    bor = b.bor
    avail = f.get("avail"); fee = f.get("fee")
    if x.get("hist"):
        av_txt, av_sub, fee_sub, fee = "N/A", "과거 시점 빌릴 수 있는 주식 이력 없음 (무료 소스 없음)", "과거 대차이자 이력 없음 — 추정도 하지 않음", None
    elif len(bor) and fee is not None:
        av_txt = "1천만주+" if (avail or 0) >= 1e7 else (model.kn(avail) + "주")
        av_sub = (f'전일 {model.kn(f["avail_prev"])}주 · ' if f.get("avail_prev") is not None else "") + f'IBKR {(pd.Timestamp(f["borrow_ts"]) + pd.Timedelta(hours=9)).strftime("%m-%d %H:%M") if f.get("borrow_ts") else "-"} 한국시간'
        fee_sub = (f'전일 {f["fee_prev"]:.1f}% · ' if f.get("fee_prev") is not None else "") + f'기록 {f.get("borrow_days") or 1}일째 (오늘부터 쌓는 중)'
    else:
        av_txt, av_sub, fee_sub = "N/A", "IBKR 목록에 없음 (빌릴 수 없는 종목일 수 있음) 또는 아직 수집 전", "데이터 없음"
    sl = short_lines(x, 6); why = short_why(x)
    plain = ("".join(f'<div style="font-size:13px;line-height:1.5">• {esc(v)}</div>' for v in sl)
             + "".join(f'<div class="tiny">점수 보정: {esc(w)}</div>' for w in why)) if sl else ""
    evs = "".join(f'<div class="ev"><div class="n">{i}</div><div class="d">{pd.Timestamp(d):%m/%d}</div><div>{esc(t)}</div></div>' for i, (d, t) in enumerate(x["events"], 1))
    ll = x["live_log"]
    live_ev = "".join(f'<div class="ev"><div class="n" style="background:#ff4d5e">⚡</div><div class="d">{esc(r.ts[5:16])}</div><div>{esc(json.loads(r.data)["msg"])}</div></div>' for r in ll.itertuples()) if len(ll) else ""
    cp = f["cover_pressure"]
    if x.get("hist"): prev_cp = None  # 과거 카드: 저장값 갱신 안 함
    else:
        prev_cp = (db.kv_get(f"cp_prev:{x['ticker']}") or {}).get("v")
        db.kv_set(f"cp_prev:{x['ticker']}", {"v": cp})
    dcp = "" if prev_cp is None else f' <span class="{"red" if cp >= (prev_cp or cp) else "green"}">{"▲" if cp >= (prev_cp or cp) else "▼"}{abs(cp - (prev_cp or cp)):.0f}</span>'
    return h('<div class="card">',
             '<div class="row"><div class="box"><div class="lab">빌릴 수 있는 주식</div>', f'<div class="val">{av_txt}</div><div class="tiny">{esc(av_sub)}</div></div>',
             f'<div class="box"><div class="lab">대차이자 (연, IBKR)</div><div class="val">{"N/A" if fee is None else f"{fee:.1f}%"}</div><div class="tiny">{esc(fee_sub)}</div></div></div>',
             (f'<h3 style="margin-top:12px">🩳 공매도·대차 쉬운 설명</h3>{plain}' if plain else ""),
             '<h3 style="margin-top:12px">📜 이벤트 로그</h3>', live_ev, evs,
             f'<div class="between" style="margin-top:10px"><b>숏 커버 압력 지수</b><b>{cp:.0f}/100{dcp}</b></div>',
             f'<div class="bar"><div style="width:{cp:.0f}%"></div></div>',
             '<div class="tiny">손실권 숏 비중(40)+DTC(20)+차입 고갈(20)+재점화 근접(20) 합산 추정치. 높을수록 숏이 쫓겨 사야 할 압력이 큼.</div></div>')

def ladder_html(x, height=440):
    m, f, bz = x["meta"], x["f"], x["bz"]
    if not m or not m.get("tranches"): return '<div class="muted">진입 구간 데이터 없음</div>'
    price = x["eh"].get("last") or f["price"]
    trs = m["tranches"]
    lo = min([t["lo"] for t in trs] + [m["lo21"], (bz or {}).get("stop", price), (x.get("bp") or {}).get("price") or price]) * 0.97
    hi = max([t["hi"] for t in trs] + [m["hi21"], price]) * 1.02
    y = lambda v: (hi - v) / (hi - lo) * height
    out = [f'<div class="ladder" style="height:{height}px">']
    if bz:
        out.append(f'<div class="bz" style="top:{y(bz["zone"][1]):.0f}px;height:{max(y(bz["zone"][0]) - y(bz["zone"][1]), 4):.0f}px"></div>')
    for t in trs:
        prof = (t["lo"] + t["hi"]) / 2 > price
        col = "rgba(34,197,94," if prof else "rgba(255,77,94,"
        a = 0.25 + 0.6 * min(t["ratio"], 1)
        top, hgt = y(t["hi"]), max(y(t["lo"]) - y(t["hi"]), 14)
        out.append(f'<div class="tb" style="top:{top:.0f}px;height:{hgt:.0f}px;background:{col}{a:.2f});border:1px solid {col}0.9)">'
                   f'<b>{esc(t["name"])}</b> {px(t["lo"])}~{px(t["hi"])} · {num(t["rem"])}주 {esc(t["tag"])}</div>')
    lines = [(price, "#ffffff", "현재가", "solid"), (m["reignite"], "#fbbf24", "재점화", "dashed"), (m["hi21"], "#ff4d5e", "21일 고점", "dotted"),
             (m["lo21"], "#22c55e", "21일 저점", "dotted")]
    if bz: lines += [(bz["stop"], "#a78bfa", "손절", "dotted")]
    bp = x.get("bp") or {}
    if bp.get("price"): lines += [(bp["price"], "#38bdf8", "추천가", "solid")]
    for k, lab in (("ma20", "20일선"), ("ma60", "60일선")):
        v = ((bp.get("ref") or {}).get(k) or {}).get("price")
        if v: lines += [(v, "#94a3b8", lab, "dashed")]
    vis = sorted([(y(v), v, c, lab, sty) for v, c, lab, sty in lines if v is not None and lo <= v <= hi])
    # 라벨 겹침 방지: 선은 실제 위치에 두고, 라벨만 최소 19px 간격으로 아래로 밀어냄
    gap, last_y = 19, -1e9
    for yy, v, c, lab, sty in vis:
        ly = max(yy, last_y + gap); last_y = ly; dy = ly - yy
        out.append(f'<div class="ln" style="top:{yy:.0f}px;border-top:1.5px {sty} {c};color:{c}"><span style="top:{dy - 9:.0f}px">{px(v)}</span><b style="top:{dy - 9:.0f}px">{lab}</b></div>')
    out.append("</div>")
    leg = ('<div class="tiny">🟩 수익권 숏(진입가 &gt; 현재가) · 🟥 손실권 숏 · 진할수록 잔존 비율 높음 · '
           '<span class="blue">빗금 = 숏 진입 지지 구간(추정)</span> · <span style="color:#38bdf8">━ 추천가(백테스트 규칙)</span> · 회색 점선 = 20·60일선</div>')
    return "".join(out) + leg

def card_ladder(x):
    return h('<div class="card"><h3>🪜 진입 구간 사다리 (추정)</h3>', ladder_html(x), "</div>")

def band_table(x, rows=14):
    m, bands = x["meta"], x["bands"]
    if bands is None or len(bands) == 0: return '<div class="muted">데이터 없음</div>'
    trs = "".join(f'<tr><td><b>{esc(t["name"])}</b> <span class="tiny">{esc(t["tag"])}</span></td><td>{px(t["lo"])}~{px(t["hi"])}</td>'
                  f'<td>{num(t["rem"])}</td><td>{t["ratio"] * 100:.0f}%</td><td class="{"green" if t["side"] == "profit" else "red"}">{pct(((t["lo"] + t["hi"]) / 2 - m["price"]) / ((t["lo"] + t["hi"]) / 2) * 100)}</td></tr>'
                  for t in m["tranches"])
    return h('<table class="t"><tr><th>차수</th><th>구간</th><th>잔존</th><th>잔존%</th><th>숏 손익</th></tr>', trs, "</table>",
             '<div class="tiny" style="margin-top:4px">숏 손익 = (구간 중앙 − 현재가) ÷ 구간 중앙. +면 숏 수익권(초록), −면 손실권(빨강).</div>')

def card_table(x):
    m = x["meta"]
    if not m: return '<div class="card">데이터 없음</div>'
    return h('<div class="card"><h3>📊 밴드 상세표 (추정)</h3>',
             f'<div class="row" style="margin-bottom:8px"><div class="box"><div class="lab">총 잔존 숏(추정)</div><div class="val">{num(m["total_rem"])}</div></div>',
             f'<div class="box"><div class="lab">손실권</div><div class="val red">{m["loss_pct"]:.0f}%</div></div><div class="box"><div class="lab">수익권</div><div class="val green">{m["profit_pct"]:.0f}%</div></div></div>',
             band_table(x), "</div>")

def detail_map(x, width_override):
    """ENTRY ZONE DETAIL MAP 화면"""
    b, f = x["b"], x["f"]
    pp = dict(p); pp["band_width"] = width_override
    bands, m = model.entry_map(b, b.px["date"].iloc[-1], pp, si_est=f.get("si_est"))
    if not m: return '<div class="muted">데이터 없음</div>'
    price = x["eh"].get("last") or f["price"]
    out = [f'<div class="card"><div class="muted" style="letter-spacing:2px;font-size:10.5px">ENTRY ZONE DETAIL MAP</div>',
           f'<div class="between"><div class="mid">{esc(x["ticker"])} {px(price)}</div><div class="tiny">당일 저 {px(m["day_lo"])} · 고 {px(m["day_hi"])}</div></div>',
           f'<div class="row" style="margin-top:8px"><div class="box"><div class="lab">총 잔존 숏(추정)</div><div class="val">{num(m["total_rem"])}</div></div>',
           f'<div class="box"><div class="lab">손실 구간</div><div class="val red">{m["loss_pct"]:.0f}%</div></div><div class="box"><div class="lab">수익 구간</div><div class="val green">{m["profit_pct"]:.0f}%</div></div></div>',
           f'<div class="row" style="margin-top:8px"><div class="box"><div class="lab">현재가</div><div class="val">{px(price)}</div></div>',
           f'<div class="box"><div class="lab">재점화 레벨</div><div class="val yellow">{px(m["reignite"])}</div></div><div class="box"><div class="lab">고가(21일)</div><div class="val red">{px(m["hi21"])}</div></div></div>']
    for t in m["tranches"]:
        out.append(f'<div class="tr {t["side"]}"><div class="between"><b>{esc(t["name"])} {px(t["lo"])} ~ {px(t["hi"])}</b>'
                   f'{"<span class=badge>" + esc(t["tag"]) + "</span>" if t["tag"] else ""}</div>'
                   f'<div class="tiny">잔존 {num(t["rem"])}주 · 잔존율 {t["ratio"] * 100:.0f}% · 전체 잔존 중 {t["share_pct"]:.0f}% · 평균 {t["age"]:.0f}일 전 진입</div></div>')
    # 세부 밴드 + 점선 마커
    marks = [(price, "현재가", "#ffffff"), (x["eh"].get("reg_close") or f["price"], "정규장 종가", "#94a3b8"), (m["day_hi"], "당일 고가", "#ff4d5e"),
             (m["day_lo"], "당일 저가", "#22c55e"), (m["reignite"], "재점화 레벨", "#fbbf24")]
    bb = bands[bands["init"] > bands["init"].max() * 0.01].sort_values("lo", ascending=False)
    mx = bb["init"].max() if len(bb) else 1
    out.append(f'<h3 style="margin-top:12px">세부 밴드 (${m["width"]:g} 폭)</h3><div class="tiny">막대 전체 = 최초 추정 유입량, 채운 부분 = 잔존 추정량</div>')
    used = set()
    prev_lo = 1e18
    for r in bb.itertuples():
        for i, (v, lab, c) in enumerate(marks):
            if i not in used and v is not None and r.hi <= v < prev_lo:
                out.append(f'<div class="mark" style="border-color:{c};color:{c}">┈ {lab} {px(v)}</div>'); used.add(i)
        prof = r.mid > price
        col = "#22c55e" if prof else "#ff4d5e"
        out.append(f'<div class="band"><div>{px(r.lo)}~{px(r.hi)}</div><div class="bg" style="width:{max(r.init / mx * 100, 3):.0f}%">'
                   f'<div class="fg" style="width:{r.rem_ratio * 100:.0f}%;background:{col}"></div></div>'
                   f'<div style="text-align:right">{num(r.rem)}</div><div style="text-align:right" class="{"green" if prof else "red"}">{pct(r.pl_pct)}</div></div>')
        prev_lo = r.lo
    for i, (v, lab, c) in enumerate(marks):
        if i not in used and v is not None:
            out.append(f'<div class="mark" style="border-color:{c};color:{c}">┈ {lab} {px(v)}</div>')
    for g in m["gaps"]:
        out.append(f'<div class="gapbox">🕳️ <b>숏 물량 공백 구간 {px(g[0])} ~ {px(g[1])}</b><br>이 가격대에는 추정 숏 진입이 거의 없어 지지·저항이 약합니다. 가격이 빠르게 통과할 수 있습니다.</div>')
    est = m["est_days"]
    out.append(f'<div class="tiny" style="margin-top:6px">⚠️ 추정치: 최근 {m["days"]}거래일 중 {est}일은 FINRA 일별 공매도 거래량이 없어 '
               f'"거래량×{p["default_short_ratio"]:.0%}"로 가정했습니다. 잔존량은 {"공표 숏 잔고(SI)에 맞춰 스케일" if m["scaled_to_si"] else "잔존비율 가정"}했고, 손실권 밴드는 더 빨리 커버된다고 가정했습니다.</div></div>')
    return "".join(out)

def bp_html(x):
    """추천 매수가 블록 (core/buyprice.py · 근거 = model/buy_price.json 백테스트)."""
    bp = x.get("bp")
    if not bp: return '<div class="tiny muted">추천 매수가: 데이터 부족(일봉 20일 미만)</div>'
    refs = " · ".join(f'{esc(v["name"])} {px(v["price"])} <span class="{"green" if v["pct"] < 0 else "red"}">({v["pct"]:+.1f}%)</span>'
                      for k, v in bp["ref"].items() if k != "ivwap")
    iv = bp["ref"].get("ivwap")
    ivt = f'<div class="tiny">오늘 장중 VWAP {px(iv["price"])} ({iv["pct"]:+.1f}%) — 참고용, 과거 1분봉이 짧아 검증 안 됨</div>' if iv else ""
    if bp.get("price") is None:
        return h('<div class="bpbox"><div class="between"><b>💵 추천 매수가</b><span class="badge yellow">추천 안 함</span></div>',
                 "".join(f'<div class="tiny">• {esc(e)}</div>' for e in bp["evidence"]),
                 f'<div class="tiny" style="margin-top:4px">참고 이동평균선: {refs}</div>{ivt}</div>')
    ev = "".join(f'<div class="ev2">• {esc(e)}</div>' for e in bp["evidence"][:3])
    wk = "".join(f'<div class="tiny">· {esc(w)}</div>' for w in bp["weak"])
    return h('<div class="bpbox">',
             f'<div class="between"><b>💵 추천 매수가 (지정가 · 다음 거래일)</b><span class="badge">{esc(bp["name"])}</span></div>',
             f'<div class="bpp">{px(bp["price"])} <span class="tiny">기준가 {px(bp["refp"])} 대비 {bp["pct"]:+.1f}%</span></div><div class="tiny" style="margin:-6px 0 8px">허용 범위 {px(bp["lo"])}~{px(bp["hi"])} (±ATR 0.15배)</div>',
             f'<div class="row"><div class="box"><div class="lab">체결 가능성</div><div class="val">{bp["fill"] * 100:.0f}%</div><div class="tiny">과거 같은 깊이(ATR {bp["k_atr"]:.2f}배) 다음 날 도달률 · 평균 {(bp.get("fill_avg") or 0) * 100:.0f}%</div></div>',
             f'<div class="box"><div class="lab">손절</div><div class="val" style="color:#a78bfa">{px(bp["stop"]) if bp["stop"] else "N/A"}</div><div class="tiny">{pct((bp["stop"] / bp["price"] - 1) * 100) if bp["stop"] else ""}</div></div>',
             f'<div class="box"><div class="lab">손익분기</div><div class="val">{px(bp["break_even"])}</div><div class="tiny">비용 왕복 반영</div></div></div>',
             f'<div style="margin-top:6px">{ev}</div>',
             f'<details><summary class="tiny">⚠️ 한계 · 참고 이동평균선 보기</summary>{wk}<div class="tiny" style="margin-top:4px">참고 이동평균선: {refs}</div>{ivt}'
             '<div class="tiny">근거: scripts/buy_price.py 백테스트(워크포워드 표본외 폴드 2~5 · 비용 0.6% · 룩어헤드 없음) · docs/ENTRY_TIMING.md 5절</div></details></div>')

def card_buyzone(x):
    bz, f = x["bz"], x["f"]
    if not bz: return h('<div class="card"><h3>🎯 추천 매수가</h3>', bp_html(x), '<div class="muted">숏 진입 구간 산출 불가</div></div>')
    bp = x.get("bp") or {}
    ent = bp.get("price") or bz["entry"]; be = bp.get("break_even") or bz["break_even"]
    rr = (bz["tp1"] - be) / (be - bz["stop"]) if be > bz["stop"] else None
    basis = "추천가" if bp.get("price") else "숏 지지 구간 기준가"
    return h('<div class="card"><h3>🎯 추천 매수가 · 목표 · 손익</h3>', bp_html(x),
             f'<div class="row" style="margin-top:8px"><div class="box"><div class="lab">숏 진입 구간 지지대</div><div class="val blue">{px(bz["zone"][0])}~{px(bz["zone"][1])}</div><div class="tiny">{esc(bz["tranche"])} 하단 지지{" · 아래 공백구간(손절 타이트)" if bz["gap_below"] else ""}</div></div>',
             f'<div class="box"><div class="lab">1차 목표 (재점화)</div><div class="val red">{px(bz["tp1"])}</div><div class="tiny">{basis} 대비 {pct((bz["tp1"] / ent - 1) * 100)}</div></div>',
             f'<div class="box"><div class="lab">2차 목표</div><div class="val red">{px(bz["tp2"])}</div><div class="tiny">{pct((bz["tp2"] / ent - 1) * 100)}</div></div></div>',
             f'<div class="between" style="margin-top:8px"><b>R:R ({basis}·1차 목표, 비용 반영)</b><span class="badge {"green" if (rr or 0) >= 2 else "red"}">{"N/A" if rr is None else f"{rr:.2f}"} {"" if (rr or 0) >= 2 else "· R:R 부족(2 미만)"}</span></div>',
             f'<div class="tiny">손절 {px(bz["stop"])} = 최신 숏 차수 하단(백테스트와 같은 손절). 목표·지지대는 숏 진입 구간 추정에서 계산한 참고값이며 보장하지 않습니다.</div></div>')

# ---------------------------------------------------------------- 페이지: 종목
def page_stock():
    topbar("종목 상세", "숏 재축적 · 진입 구간")
    c1, c2 = st.columns([3, 1])
    t = c1.text_input("티커", TICK, label_visibility="collapsed", placeholder="티커 입력 (예: SOUN)").upper().strip()
    if c2.button("새로고침", width="stretch"):
        snap.clear(); src.refresh_ticker(t); db.exec_("DELETE FROM kv WHERE k=?", (f"live1m:{t}",))
    db.set_setting("last_ticker", t)
    run_every = f"{REFRESH_MIN * 60}s" if LIVE_ON and live.session_now()[0] != "closed" else None

    @st.fragment(run_every=run_every)
    def body():
        with st.spinner("데이터 계산 중..."):
            x = get_snap(t)
        if x is None:
            st.error("가격 데이터가 부족하거나 티커를 찾을 수 없습니다."); return
        md(live_line(x))
        md(f'<div style="margin:2px 0 6px"><span class="cpchip">{cpk(t, copy_text(t, x), href=False, label="📋 " + esc(t) + " 꾹 눌러 복사")}</span> {tsb(t, big=True)} <span class="tiny">앱이 깔려 있으면 토스증권 앱의 {esc(t)} 화면으로, 아니면 웹으로 열립니다</span></div>')
        for kind, msg in x["triggers"]:
            md(f'<div class="card rc" style="padding:9px 12px">⚡ <b>라이브 트리거</b> · {esc(msg)}</div>')
        md(prob_card(x))
        md('<div class="carousel">' + card_alert(x) + card_borrow(x) + card_ladder(x) + card_table(x) + '</div><div class="dots">◀ 옆으로 넘기기 · 1 경보 · 2 차입/이벤트 · 3 사다리 · 4 밴드표 ▶</div>')
        dil = x["dil"]
        md(f'<div class="card"><h3>🧾 자동 요약</h3><div style="font-size:13px;line-height:1.55">{esc(model.summary_ko(t, x["f"], x["s"], x["meta"], dil, x["prob"]))}</div></div>')
        sig = x["s"]["signals"]
        chips = "".join(f'<span class="chip {"on" if (v or 0) >= 1 else ""}">{esc(model.SIG_NAME[k])} {"N/A" if v is None else f"{min(v, 1.5) * 100:.0f}"}</span>' for k, v in sig.items())
        md(f'<div class="card"><h3>🔔 동시 신호 (Confluence) {x["s"]["confluence"]}개 / 기준 {int(p["min_confluence"])}개</h3><div class="chips">{chips}</div>'
           f'<div class="tiny">숫자 = 신호 강도(100 이상이면 ON). N/A = 무료 소스에서 데이터 없음. {"✅ 경보 조건 충족" if x["s"]["flagged"] else "경보 조건 미충족"}</div></div>')
        md(card_buyzone(x))
        return x
    x = body()
    if x is None:
        x = get_snap(t)
        if x is None: return
    w = st.select_slider("세부 밴드 폭($)", options=[0.0, 0.01, 0.02, 0.05, 0.1, 0.25, 0.5, 1.0], value=float(p["band_width"]) if p["band_width"] in (0.01, 0.02, 0.05, 0.1, 0.25, 0.5, 1.0) else 0.0,
                         format_func=lambda v: "자동" if v == 0 else f"${v:g}")
    md(detail_map(x, w))
    safety(x)
    extras(x)
    disclaimer()

def safety(x):
    f, dil, dl, liq, bz = x["f"], x["dil"], x["delist"], x["liq"], x["bz"]
    st.markdown("#### 🛡️ 안전장치")
    with st.expander("포지션 크기 · 손절 계산기", expanded=False):
        fx = src.fetch_usdkrw()
        acc = st.number_input("계좌 금액 ($)", 100.0, 1e8, float(db.get_setting("account", 10000)), step=500.0)
        risk = st.slider("1회 허용 손실 (%)", 0.25, 5.0, float(db.get_setting("risk_pct", 1.0)), 0.25)
        bpx = (x.get("bp") or {}).get("price")
        entry = st.number_input("진입가 (기본: 추천 매수가)" if bpx else "진입가", 0.0001, 1e5, float(bpx or (bz["entry"] if bz else f["price"])), format="%.4f")
        stop = st.number_input("손절가 (기본: 진입맵 손실권 하단)", 0.0001, 1e5, float(bz["stop"] if bz else f["price"] * 0.85), format="%.4f")
        db.set_setting("account", acc); db.set_setting("risk_pct", risk)
        ps = model.position_size(acc, risk, entry, stop)
        if ps:
            tp1 = bz["tp1"] if bz else entry * 1.3
            md(f'<div class="card"><div class="row"><div class="box"><div class="lab">매수 수량</div><div class="val">{ps["shares"]:,}주</div></div>'
               f'<div class="box"><div class="lab">투입 금액</div><div class="val">${ps["cost"]:,.0f}</div><div class="tiny">₩{ps["cost"] * fx:,.0f}</div></div>'
               f'<div class="box"><div class="lab">손절 시 손실</div><div class="val red">-${ps["risk_amt"]:,.0f}</div><div class="tiny">-₩{ps["risk_amt"] * fx:,.0f}</div></div></div>'
               f'<div class="tiny" style="margin-top:6px">1차 목표 {px(tp1)} 도달 시 +${ps["shares"] * (tp1 - entry):,.0f} (₩{ps["shares"] * (tp1 - entry) * fx:,.0f}) · 환율 {fx:,.1f}원 (open.er-api.com)</div></div>')
        else:
            st.warning("손절가가 진입가보다 낮아야 합니다.")
    md(h('<div class="card">',
         f'<div class="between"><h3>💧 희석(증자) 위험 점수</h3><span class="badge {"red" if dil["score"] >= 50 else ("yellow" if dil["score"] >= 25 else "green")}">{dil["score"]}/100</span></div>',
         "".join(f'<div class="tiny">• {esc(w)}</div>' for w in dil["why"]) or '<div class="tiny">최근 희석 공시 없음</div>',
         f'<div class="tiny">현금 런웨이 {"N/A" if dil["runway_m"] is None else f"약 {dil["runway_m"]:.1f}개월"} · 분기 현금소모 {num(dil["burn_q"])} · 1년 주식수 변화 {pct(dil["share_growth"])} · '
         f'{"<span class=red>베이비 셸프 대상(유통시총 &lt; $75M → 셸프 사용 1/3 제한)</span>" if dil["baby_shelf"] else "베이비 셸프 아님"} · 셸프 잔여한도: {esc(dil["shelf_capacity"])}</div>',
         f'<div class="tiny">역분할 이력: {", ".join(f"{d} (1:{1 / r:.0f})" for d, r in dil["reverse_splits"]) or "없음"} · 최근 1년 8-K 3.03/5.03: {dil["rs_8k"]}건</div></div>'))
    lw = liq["warnings"]
    md(h('<div class="card">', '<h3>🚰 유동성 · 상장폐지</h3>',
         "".join(f'<div class="tiny red">⚠️ {esc(w)}</div>' for w in lw) or f'<div class="tiny">20일 평균 거래대금 ${num(f.get("dollar_vol20"))} · 스프레드 {pct(liq["spread"], 2, False)}</div>',
         f'<div class="tiny" style="margin-top:4px">$1 미만 연속 {dl["days_below_1"]}거래일 · ' + (
             f'<span class="red">나스닥 결손 통지 대상(30일) · 180일 유예 잔여 약 {dl["compliance_left"]}일 · 역분할 가능성 높음</span>' if dl["notice"] else
             (f'<span class="yellow">통지까지 {dl["days_to_notice"]}거래일</span>' if dl["days_below_1"] else "해당 없음")) + '</div></div>'))

def extras(x):
    t, f, b, info = x["ticker"], x["f"], x["b"], x["info"]
    st.markdown("#### 📚 참고 지표")
    tabs = st.tabs(["기술", "촉매", "뉴스", "내부자/옵션", "통계", "유사패턴"])
    with tabs[0]:
        md(h('<div class="card"><div class="row">', f'<div class="box"><div class="lab">RSI(14)</div><div class="val">{f.get("rsi", 0):.0f}</div></div>',
             f'<div class="box"><div class="lab">볼린저 %B</div><div class="val">{f.get("bb_pctb", 0):.2f}</div><div class="tiny">폭 백분위 {f.get("bbw_pctile", 0):.0f}</div></div>',
             f'<div class="box"><div class="lab">20일 VWAP</div><div class="val">{px(f.get("vwap20"))}</div><div class="tiny">{"위" if f["price"] > f.get("vwap20", 0) else "아래"}</div></div></div>',
             f'<div class="row" style="margin-top:8px"><div class="box"><div class="lab">매수/매도 압력(5일, 추정)</div><div class="val {"red" if f.get("pressure", 0) > 0 else "blue"}">{f.get("pressure", 0) * 100:+.0f}</div><div class="tiny">종가 위치×거래량 (−100 매도 ~ +100 매수)</div></div>',
             f'<div class="box"><div class="lab">시장 국면 (QQQ·IWM)</div><div class="val">{ {1: "강세", 0: "중립", -1: "약세"}[f.get("regime", 1)] }</div><div class="tiny">50일선·20일 수익률</div></div></div></div>'))
        ipo = info.get("firstTradeDateMilliseconds")
        if ipo:
            age = (dt.datetime.now() - dt.datetime.fromtimestamp(ipo / 1000)).days
            st.caption(f"상장 후 {age}일 · {'⚠️ 보호예수(락업) 해제 구간 가능 (상장 6개월 전후)' if 120 <= age <= 220 else '락업 이슈 낮음 (추정)'}")
        hr = scan.hot_runner_corr(t)
        if hr and hr["avg"] is not None:
            st.caption(f"최근 급등주({', '.join(hr['hot'][-5:])}) 수익률 상관 평균 {hr['avg']:.2f}")
    with tabs[1]:
        ed = info.get("earnings_dates") or []
        rows = [f"• 실적 발표 예정: {', '.join(ed) or 'N/A (yfinance)'}"]
        fil = b.fil.head(8)
        for r in fil.itertuples():
            rows.append(f"• {r.filed:%Y-%m-%d} {r.form} {('item ' + r.items) if r.items else ''}")
        st.markdown("\n".join(rows))
        fj = [f for f in reversed(_flog()) if f.get("ticker") == t][:6]
        if fj:
            md('<div class="card"><h3>📢 최근 공시 판정 (자동)</h3>' + "".join(filing_row(f, False) for f in fj)
               + '<div class="tiny">8-K 항목 번호 + 보도자료 키워드 판정 · 틀릴 수 있음 · 원문 확인</div></div>')
        st.caption("FDA 일정: 무료 공개 API가 없어 미구현. 러셀 재편: 매년 6월 정기 재편(2026년부터 반기 재편 도입 발표) — 정확한 날짜는 FTSE Russell 공지 확인.")
        pr = earnings_runup(t)
        if pr is not None and len(pr):
            st.caption(f"실적 전 5일 평균 수익률 {pr['pre5'].mean():+.1f}% (표본 {len(pr)})")
            st.dataframe(pr, hide_index=True, width="stretch")
    with tabs[2]:
        items, tot = model.sentiment(src.fetch_news(t))
        st.caption(f"Yahoo RSS 헤드라인 키워드 감성 합계 {tot:+.1f} (단순 키워드 방식 · 참고용)")
        for it in items[:10]:
            st.markdown(f"{'🟢' if it['sent'] > 0 else ('🔴' if it['sent'] < 0 else '⚪')} [{it['title']}]({it['link']})  \n<span class='tiny'>{esc(it.get('date', ''))}</span>", unsafe_allow_html=True)
        bz = src.fetch_reddit_buzz(t)
        st.caption(f"소셜 버즈: {bz if bz else 'Reddit/StockTwits 접속 불가 (이 서버에서 차단됨 · 내 PC에서는 동작할 수 있음)'} · X(트위터)는 무료 API 없음으로 제외")
    with tabs[3]:
        ins = src.insider_trades(t)
        if ins:
            d = pd.DataFrame(ins); buys = d[d.code == "P"]; sells = d[d.code == "S"]
            st.caption(f"최근 Form 4: 장내매수(P) {len(buys)}건 {buys.shares.sum():,.0f}주 · 장내매도(S) {len(sells)}건 {sells.shares.sum():,.0f}주")
            st.dataframe(d, hide_index=True, width="stretch")
        else:
            st.caption("Form 4 없음/조회 실패")
        st.caption("13F 기관 변동: 분기 대량 파일 파싱 필요 → 미구현. 참고: 기관 보유비율 " + (pct((info.get("heldPercentInstitutions") or 0) * 100, 1, False)))
        op = src.fetch_options(t)
        if op and op.get("calls"):
            c = pd.DataFrame(op["calls"]); price = f["price"]
            near = c[(c.strike >= price) & (c.strike <= price * 1.3)]
            gamma = near.openInterest.sum() * 100 / max(info.get("averageVolume10days") or 1, 1) * 100
            st.caption(f"옵션 만기 {op['expiry']}: 콜 거래량 {op['call_vol']:,.0f} / 풋 {op['put_vol']:,.0f} · 콜 미결제 {op['call_oi']:,.0f} · "
                       f"현재가~+30% 콜 OI×100 = 평균 거래량의 {gamma:.1f}% {'⚠️ 감마 스퀴즈 잠재' if gamma > 20 else ''}")
        else:
            st.caption("상장 옵션 없음")
    with tabs[4]:
        fs = model.fade_stats(b.px)
        if fs is not None and len(fs):
            st.caption(f"과거 +30% 급등 {len(fs)}회 · 10일 내 상승분 절반 반납 {fs.half_back.mean() * 100:.0f}% · 고점 대비 5일 후 평균 {fs['d5'].mean():+.1f}%")
            st.dataframe(fs.round(1), hide_index=True, width="stretch")
        else:
            st.caption("최근 2년 +30% 급등 이력 없음")
        pm = scan.premarket_stats(t)
        if len(pm):
            st.caption("프리마켓 갭 vs 정규장 (최근 5거래일, 1분봉)")
            st.dataframe(pm.round(2), hide_index=True, width="stretch")
        ftd = b.ftd.tail(10)
        st.caption(f"SEC FTD 최근: {', '.join(f'{r.date:%m/%d} {r.qty:,.0f}' for r in ftd.itertuples()) or '없음'} (공개 약 3주 지연) · "
                   f"Reg SHO Threshold: {'최근 등재 ⚠️' if f.get('threshold') else '미등재'}")
        sv = b.sv.tail(5)
        st.caption("FINRA 일별 공매도 비율: " + (", ".join(f"{r.date:%m/%d} {r.short_vol / max(r.total_vol, 1) * 100:.0f}%" for r in sv.itertuples()) if len(sv) else
                   "N/A (이 서버에서 FINRA 차단 · 관리 탭에서 파일 업로드 가능)") + (f" · z={f['sv_z']:.2f}" if "sv_z" in f else ""))
    with tabs[5]:
        sm = model.similar_cases(x["s"]["signals"])
        if sm:
            st.caption(f"현재와 신호 구성이 비슷한 과거 {sm['n']}건: {H_N}일 내 +{TGT:.0f}% 도달 {sm['hit_rate']:.0f}% · 평균 최대상승 {sm['avg_max']:+.1f}% · 평균 종료수익 {sm['avg_end']:+.1f}%")
            st.dataframe(sm["cases"].round(2), hide_index=True, width="stretch")
        else:
            st.caption("타임머신 표본이 부족합니다 (추적 탭에서 검증 실행).")

# ---------------------------------------------------------------- 티커 꾹 누르기 → 정리 글 복사
APP_URL_DEFAULT = "https://short-dashboard-6afz8yyoz9rgornvinw6zi.streamlit.app"

def dash_base():
    """복사 글에 넣을 대시보드 주소 (로그인 열쇠 k 등 쿼리는 절대 넣지 않음)."""
    from urllib.parse import urlsplit
    u = (AL._secret("DASH_URL") or db.get_setting("dash_url", "") or APP_URL_DEFAULT).strip()
    try:
        sp = urlsplit(u if "://" in u else "https://" + u)
        if sp.scheme != "https" or not sp.netloc: raise ValueError
        return f"https://{sp.netloc}{sp.path.rstrip('/')}"
    except Exception:
        return APP_URL_DEFAULT

def dash_link(t): return f"{dash_base()}/?p=stock&t={str(t).upper()}"

_FL_CACHE = {}
def last_filing(t, days=30):
    """최근 공시 판정 1건 (호재/악재/중립) — 알림 기록(alert-data) 기준."""
    if "rows" not in _FL_CACHE: _FL_CACHE["rows"] = _flog()
    cut = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    for f in reversed(_FL_CACHE["rows"]):
        if f.get("ticker") == t and str(f.get("filed") or f.get("accepted_kst") or "9999")[:10] >= cut[:10]: return f
    return None

def _filing_line(t):
    f = last_filing(t)
    if not f: return None
    lab = POL_KO.get(f.get("polarity"), ("중립", ""))[0]
    when = esc_plain(f.get("accepted_kst") or str(f.get("filed") or "")[5:10].replace("-", "/"))
    return f"📢 최근 공시: {when} {f.get('form') or ''} {lab} — {f.get('label') or '일반 공시'} (키워드 판정, 원문 확인 필수)"

def esc_plain(v): return re.sub(r"\s+", " ", str(v or "")).strip()

def _ma_refs(bp):
    return " · ".join(f'{v["name"]} {px(v["price"])}({v["pct"]:+.1f}%)' for k, v in ((bp or {}).get("ref") or {}).items() if k != "ivwap")

def copy_text(t, x):
    """종목 정리 글 (카톡·메모에 붙여넣기용 평문)."""
    t = str(t).upper()
    eh, f, s, info = x["eh"], x["f"], x["s"], x.get("info") or {}
    last = eh.get("last") or f["price"]; prev = eh.get("prev_close")
    chg = (last / prev - 1) * 100 if prev else f.get("chg1")
    nm = esc_plain(info.get("shortName") or info.get("longName") or "")
    L = [f"📈 {t}" + (f" · {nm}" if nm else ""), f"현재가 {px(last)} ({pct(chg, 2)})"]
    pr = (x.get("prob") or {}).get("prob"); rs = raw_score(x)
    pl = f"🔥 {GOAL} 확률(추정) {pr:.0f}%" if pr is not None else "🔥 오를 확률(추정) 데이터 부족"
    if rs is not None: pl += f" · 종합점수 {rs:.0f}점"
    L.append(pl)
    sm = esc_plain(x.get("summary"))
    if sm: L.append(f"▸ {sm}")
    st_ = f"숏 재축적 레벨 {s.get('level')}/5 · 동시 신호 {s.get('confluence')}개"
    if s.get("flagged"): st_ += " · 🚨 경보 조건 충족"
    L.append(st_)
    on = [model.SIG_NAME.get(k, k) for k in (s.get("on") or [])]
    if on: L.append("핵심 근거: " + ", ".join(on[:5]))
    for _, msg in (x.get("triggers") or [])[:2]: L.append(f"⚡ {esc_plain(msg)}")
    sl = short_lines(x, 6)
    if sl:
        L.append("🩳 공매도·대차: " + " / ".join(esc_plain(v) for v in sl))
        for w in short_why(x): L.append(f"  점수 보정: {esc_plain(w)}")
    L.append("")
    bp, bz = x.get("bp") or {}, x.get("bz") or {}
    if bp.get("price"):
        L.append(f"💵 추천 매수가 {px(bp['price'])} ({esc_plain(bp.get('name'))}, 기준가 {px(bp.get('refp'))} 대비 {bp.get('pct', 0):+.1f}%) · 허용 {px(bp.get('lo'))}~{px(bp.get('hi'))}")
        if bp.get("evidence"): L.append("  근거: " + esc_plain(bp["evidence"][0])[:160])
    elif bp:
        L.append("💵 추천 매수가: 추천 안 함 — " + esc_plain((bp.get("evidence") or [""])[0])[:120])
    else:
        L.append("💵 추천 매수가: 데이터 부족")
    ma = _ma_refs(bp)
    if ma: L.append(f"  이동평균선: {ma}")
    be = bp.get("break_even") or bz.get("break_even")
    if be: L.append(f"⚖️ 손익분기 {px(be)} (수수료·슬리피지 왕복 반영)")
    stop = bp.get("stop") or bz.get("stop")
    if stop: L.append(f"🛑 손절 {px(stop)}")
    if bz.get("tp1"): L.append(f"🎯 1차 목표(재점화) {px(bz['tp1'])} · 2차 {px(bz.get('tp2'))}")
    if bz.get("zone"): L.append(f"🪜 숏 진입 지지 구간 {px(bz['zone'][0])}~{px(bz['zone'][1])}")
    L.append("")
    try: pens = AL.penalties(x)
    except Exception: pens = []
    pens = [p_ for p_ in pens if not str(p_).startswith("최근 악재 공시")]
    if pens: L.append("⚠️ 감점 요인: " + " / ".join(esc_plain(p_) for p_ in pens[:4]))
    else: L.append("✅ 증자·역분할 감점 요인 없음 (최근 공시 기준)")
    dw = (x.get("dil") or {}).get("why") or []
    if dw: L.append(f"🧾 희석 위험 {(x.get('dil') or {}).get('score', 0):.0f}/100: " + ", ".join(esc_plain(w) for w in dw[:3]))
    fl = _filing_line(t)
    if fl: L.append(fl)
    L += ["", f"🔗 {dash_link(t)}", "※ 숏 레이더 추정치 · 투자 권유 아님"]
    return "\n".join(L).replace("\n\n\n", "\n\n").strip()

def copy_text_row(r):
    """스캔 목록 행으로 만든 정리 글 (상세 계산 없이 화면에 있는 값)."""
    t = str(r.ticker).upper()
    g = lambda k: getattr(r, k, None)
    ok = lambda v: v is not None and not (isinstance(v, float) and math.isnan(v))
    nm = esc_plain(g("name") or "")
    L = [f"📈 {t}" + (f" · {nm}" if nm else ""), f"현재가 {px(g('price'))} ({pct(g('chg1'), 2) if ok(g('chg1')) else 'N/A'})",
         f"🔥 종합점수 {g('score'):.0f}점 · 상태 {g('status')} · 레벨 {g('level')}/5 · 동시 신호 {g('conf')}개" + (" · 🚨 경보 조건 충족" if g("flagged") else "")]
    sm = esc_plain(g("summary"))
    if sm: L.append(f"▸ {sm}")
    on = [model.SIG_NAME.get(k, k) for k in str(g("on") or "").split(",") if k]
    if on: L.append("핵심 근거: " + ", ".join(on[:5]))
    if ok(g("upside")): L.append(f"🎯 재점화 레벨까지 {pct(g('upside'), 0)} (추정)")
    if ok(g("runway")): L.append(f"⏳ 현금 런웨이 약 {g('runway'):.0f}개월 · 희석 점수 {g('dil_score')}")
    bad = [lab for k, lab in (("dilution", "증자/희석"), ("reverse_split", "역분할"), ("lawsuit", "소송")) if g(k) is True or (ok(g(k)) and bool(g(k)))]
    L.append("⚠️ 감점 요인: " + ", ".join(bad) if bad else "✅ 증자·역분할·소송 감점 요인 없음")
    fl = _filing_line(t)
    if fl: L.append(fl)
    L += ["확률·추천 매수가·손익분기는 상세 화면에서 확인", "", f"🔗 {dash_link(t)}", "※ 숏 레이더 추정치 · 투자 권유 아님"]
    return "\n".join(L)

def cpk(t, text, href=True, label=None):
    """꾹 누르면 복사되는 티커. 짧게 누르면 기존처럼 상세 화면으로 이동."""
    from urllib.parse import quote
    t = str(t).upper()
    data = f' data-copy="{quote(text, safe="")}" data-tk="{esc(t)}"'
    inner = label or esc(t)
    if href: return f'<a class="cpk" href="?{ui.AUTHQ}p=stock&t={esc(t)}" target="_self"{data}>{inner}</a>'
    return f'<span class="cpk"{data}>{inner}</span>'

COPY_JS = r"""
(function(){
  var W = window, D = document;
  if (W.__srCopyV === 2) return; W.__srCopyV = 2;
  var LP = 480, timer = null, el = null, armed = false, sx = 0, sy = 0, lastTouch = 0, suppressUntil = 0;
  var IOS = /iP(hone|ad|od)/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  function dec(s){ try { return decodeURIComponent(s || ""); } catch (e) { return s || ""; } }
  function toast(msg){
    var t = D.getElementById("sr-toast");
    if (!t) { t = D.createElement("div"); t.id = "sr-toast"; D.body.appendChild(t); }
    t.textContent = msg; t.className = "on"; clearTimeout(t._h);
    t._h = setTimeout(function(){ t.className = ""; }, 1800);
  }
  function execCopy(txt){
    var ta = D.createElement("textarea"), ok = false, sel = W.getSelection();
    ta.value = txt; ta.setAttribute("readonly", "");
    ta.style.cssText = "position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;font-size:16px;border:0;padding:0;";
    D.body.appendChild(ta);
    try {
      if (IOS) {
        ta.contentEditable = true; ta.readOnly = false;
        var r = D.createRange(); r.selectNodeContents(ta); sel.removeAllRanges(); sel.addRange(r);
        ta.setSelectionRange(0, txt.length);
      } else {
        try { ta.focus({preventScroll: true}); } catch (e) { ta.focus(); }
        ta.select(); ta.setSelectionRange(0, txt.length);
      }
      ok = D.execCommand("copy") && (IOS || D.activeElement === ta);
    } catch (e) { ok = false; }
    D.body.removeChild(ta); try { sel.removeAllRanges(); } catch (e) {}
    return ok;
  }
  function sheet(txt, tk){
    var s = D.getElementById("sr-copysheet");
    if (s) s.remove();
    s = D.createElement("div"); s.id = "sr-copysheet";
    s.innerHTML = '<div class="b"><div class="h"></div><textarea readonly></textarea><div class="r"><button class="c">📋 복사</button><button class="x">닫기</button></div></div>';
    s.querySelector(".h").textContent = tk + " 정리 — 아래 '복사'를 눌러 주세요";
    var ta = s.querySelector("textarea"); ta.value = txt;
    s.querySelector(".x").onclick = function(){ s.remove(); };
    s.querySelector(".c").onclick = function(){
      var done = function(){ s.remove(); toast("📋 " + tk + " 정리 복사됨"); };
      if (execCopy(txt)) return done();
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(txt).then(done, function(){ ta.focus(); ta.select(); toast("글을 길게 눌러 직접 복사해 주세요"); });
      else { ta.focus(); ta.select(); toast("글을 길게 눌러 직접 복사해 주세요"); }
    };
    s.onclick = function(e){ if (e.target === s) s.remove(); };
    D.body.appendChild(s);
  }
  function doCopy(t){
    var txt = dec(t.getAttribute("data-copy")), tk = t.getAttribute("data-tk") || "";
    if (!txt) return;
    try { navigator.vibrate && navigator.vibrate(20); } catch (e) {}
    if (execCopy(txt)) { toast("📋 " + tk + " 정리 복사됨"); return; }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(txt).then(function(){ toast("📋 " + tk + " 정리 복사됨"); }, function(){ sheet(txt, tk); });
    } else sheet(txt, tk);
  }
  function target(e){ var n = e.target; if (n && n.nodeType !== 1) n = n.parentElement; return n && n.closest ? n.closest("[data-copy]") : null; }
  function cancel(){ clearTimeout(timer); timer = null; if (el) el.classList.remove("cpk-hold", "cpk-armed"); el = null; armed = false; }
  function start(t, x, y){
    cancel(); el = t; sx = x; sy = y; armed = false; el.classList.add("cpk-hold");
    timer = setTimeout(function(){ armed = true; if (el) el.classList.add("cpk-armed"); }, LP);
  }
  function finish(e){
    if (!el) return;
    var t = el, a = armed; cancel();
    if (a) { if (e && e.cancelable) e.preventDefault(); suppressUntil = Date.now() + 800; doCopy(t); }
  }
  D.addEventListener("touchstart", function(e){ lastTouch = Date.now(); var t = target(e); if (!t || e.touches.length > 1) { cancel(); return; } var p = e.touches[0]; start(t, p.clientX, p.clientY); }, {capture: true, passive: true});
  D.addEventListener("touchmove", function(e){ if (!el) return; var p = e.touches[0]; if (Math.abs(p.clientX - sx) > 10 || Math.abs(p.clientY - sy) > 10) cancel(); }, {capture: true, passive: true});
  D.addEventListener("touchend", function(e){ lastTouch = Date.now(); finish(e); }, {capture: true, passive: false});
  D.addEventListener("touchcancel", function(e){ if (el && armed) { var t = el; cancel(); suppressUntil = Date.now() + 800; doCopy(t); } else cancel(); }, {capture: true, passive: true});
  D.addEventListener("mousedown", function(e){ if (e.button !== 0 || Date.now() - lastTouch < 1000) return; var t = target(e); if (t) start(t, e.clientX, e.clientY); }, true);
  D.addEventListener("mousemove", function(e){ if (el && Date.now() - lastTouch > 1000 && (Math.abs(e.clientX - sx) > 6 || Math.abs(e.clientY - sy) > 6)) cancel(); }, true);
  D.addEventListener("mouseup", function(e){ if (Date.now() - lastTouch < 1000) return; finish(e); }, true);
  D.addEventListener("click", function(e){ if (Date.now() < suppressUntil && target(e)) { e.preventDefault(); e.stopPropagation(); } }, true);
  D.addEventListener("contextmenu", function(e){ var t = target(e); if (t) { e.preventDefault(); if (el === t) { armed = true; t.classList.add("cpk-armed"); } } }, true);
  D.addEventListener("selectstart", function(e){ if (target(e)) e.preventDefault(); }, true);
  D.addEventListener("dragstart", function(e){ if (target(e)) e.preventDefault(); }, true);
})();
"""

def copy_js():
    """복사 스크립트를 부모 문서(앱 화면)에 1번만 심음 — Streamlit 마크다운은 JS 를 지우므로 같은 출처 iframe 에서 주입."""
    import streamlit.components.v1 as components
    components.html("<script>(function(){try{var d=window.parent.document;if(d.getElementById('sr-copy-js-v2'))return;"
                    "var s=d.createElement('script');s.id='sr-copy-js-v2';s.textContent=" + json.dumps(COPY_JS) + ";d.head.appendChild(s);}catch(e){}})();</script>", height=0)
copy_js()

COPY_HINT = '<div class="tiny" style="margin:-2px 2px 4px">👆 티커를 꾹 누르면 정리 글이 복사돼요 (카톡·메모에 붙여넣기)</div>'

def earnings_runup(t):
    k = f"earnhist:{t}"
    c = db.kv_get(k, 86400 * 3)
    if c is None:
        try:
            import yfinance as yf
            ed = yf.Ticker(t).get_earnings_dates(limit=12)
            c = [str(d.date()) for d in ed.index] if ed is not None else []
        except Exception:
            c = []
        db.kv_set(k, c)
    pxd = src.get_prices(t)
    if not c or len(pxd) == 0: return None
    out = []
    for d in c:
        d = pd.Timestamp(d)
        before = pxd[pxd.date < d]
        if len(before) < 6 or d > pxd.date.max(): continue
        out.append({"실적일": d.strftime("%Y-%m-%d"), "pre5": (before.close.iloc[-1] / before.close.iloc[-6] - 1) * 100})
    return pd.DataFrame(out)

def key_levels(x, last):
    """재점화 / 손절 / 익절 가격. 손절·익절은 검증된 청산 규칙(표본외 기대값 양수일 때) 또는 기본 설정(참고)."""
    er = model.exit_rule()
    if er and er["positive"]: stop, tp, tag = er["stop"], er["tp"], "검증"
    else: stop, tp, tag = float(p["stop_pct"]), float(p["target_pct"]), "참고"
    rl = (x.get("meta") or {}).get("reignite")
    return rl, last * (1 - stop / 100), (last * (1 + tp / 100) if tp else None), stop, tp, tag, er

def home_card(t, x, top=""):
    eh, f, s, info = x["eh"], x["f"], x["s"], x.get("info") or {}
    last = eh.get("last") or f["price"]; prev = eh.get("prev_close")
    chg = (last / prev - 1) * 100 if prev else f["chg1"]
    pr = (x.get("prob") or {}).get("prob")
    pv = f'{pr:.0f}%' if pr is not None else "—"
    pc = "red" if pr is not None and pr >= 25 else ("yellow" if pr is not None and pr >= 10 else "")
    rs = raw_score(x)
    sc_txt = f' · 종합점수 <b>{rs:.0f}</b>점' if rs is not None else ""
    rl, sp, tpp, stop, tp, tag, er = key_levels(x, last)
    flag = '<span class="badge red">경보 조건 충족</span>' if s["flagged"] else ""
    trig = '<span class="badge red">트리거</span>' if x["triggers"] else ""
    return h(f'<div class="hc"><a class="ov" href="?{ui.AUTHQ}p=stock&t={t}" target="_self" aria-label="{esc(t)} 상세"></a><div class="card {"rc" if s["flagged"] else ""}">', top,
             f'<div class="t1"><div><div class="sym">{cpk(t, copy_text(t, x))}{tsb(t)}</div><div class="nm">{esc((info.get("shortName") or "")[:30])}</div></div>',
             f'<div class="pr"><div class="v">{px(last)}</div><div class="c {ui.cls(chg).replace("green", "blue")}">{pct(chg, 2)}</div></div></div>',
             f'<div class="pb"><div class="pv {pc}">{pv}</div><div class="pl"><div class="lab">{esc(GOAL)} 확률 (추정){sc_txt} {flag}{trig}</div>',
             f'<div class="meter"><div style="width:{min(pr or 0, 100):.0f}%"></div></div></div></div>',
             f'<div class="sumline">{esc(x.get("summary") or "")}</div>',
             (f'<div class="tiny" style="margin:2px 0 4px">🩳 {esc(" · ".join(short_lines(x, 3, "brief")))}</div>' if short_lines(x, 3, "brief") else ""),
             '<div class="lv3">',
             f'<div class="box"><div class="lab">재점화 (추정)</div><div class="val yellow">{px(rl)}</div><div class="tiny">{pct((rl / last - 1) * 100) if rl else "N/A"}</div></div>',
             f'<div class="box"><div class="lab">손절 ({tag})</div><div class="val blue">{px(sp)}</div><div class="tiny">-{stop:.0f}%</div></div>',
             f'<div class="box"><div class="lab">익절 ({tag})</div><div class="val red">{px(tpp) if tpp else "추적손절"}</div><div class="tiny">{f"+{tp:.0f}%" if tp else ""}</div></div>',
             '</div>', f'<div class="foot">{live_line(x)}</div></div></div>')

# ---------------------------------------------------------------- 홈: 방금 알림 온 종목
RAW_ALERTS = "https://raw.githubusercontent.com/{repo}/alert-data/data/alerts/alerts_log.json"

def recent_alert_log():
    """alert-data 브랜치의 알림 기록 (2분 캐시). 저장소 설정이 없으면 공개 저장소 원본에서 직접."""
    try:
        r = AL.fetch_remote_log(ttl=120)
        if isinstance(r, list): return r
    except Exception:
        pass
    k = "remote:raw_alerts_log"
    c = db.kv_get(k, 120)
    if c is not None: return c.get("v") or []
    repo = os.environ.get("GH_REPO") or "ogeunho011-dotcom/short-dashboard"
    try:
        import requests
        rr = requests.get(RAW_ALERTS.format(repo=repo), timeout=10)
        out = rr.json() if rr.status_code == 200 else []
        db.kv_set(k, {"v": out if isinstance(out, list) else []})
        return out if isinstance(out, list) else []
    except Exception:
        return AL.load_log() or []

def fresh_alerts(log=None, hours=24, limit=8):
    """최근 hours 시간 안에 실제로 폰에 보낸 알림 → 티커별 최신 1건 (최신순). 같은 종목 여러 번이면 횟수·종류 합침."""
    log = recent_alert_log() if log is None else log
    now = dt.datetime.now(dt.timezone.utc)
    by = {}
    for r in log or []:
        if not r.get("sent") or r.get("dry") or not r.get("ticker"): continue
        if "test" in (r.get("types") or []): continue
        try: ts = dt.datetime.fromisoformat(str(r.get("ts_utc")).replace("Z", "+00:00"))
        except Exception: continue
        if ts.tzinfo is None: ts = ts.replace(tzinfo=dt.timezone.utc)
        if now - ts > dt.timedelta(hours=hours) or ts > now + dt.timedelta(minutes=10): continue
        t = str(r["ticker"]).upper()
        g = by.setdefault(t, {"ticker": t, "n": 0, "types": [], "last": None, "ts": None})
        g["n"] += 1
        for k in r.get("types") or []:
            if k not in g["types"]: g["types"].append(k)
        if g["ts"] is None or ts > g["ts"]: g["ts"], g["last"] = ts, r
    return sorted(by.values(), key=lambda g: g["ts"], reverse=True)[:limit]

def alert_strip(g):
    """카드 맨 위 알림 줄: 종류 · 한국시간, 주의 문구, 공시 원문 링크."""
    r = g["last"]; types = r.get("types") or []
    hm = g["ts"].astimezone(live.KST)
    when = f"{hm:%H:%M}" if hm.date() == dt.datetime.now(live.KST).date() else f"{hm:%m/%d %H:%M}"
    if "filing" in types:
        fl = r.get("filing") or {}
        lab = f'📢 호재 공시 · {esc(fl.get("label") or (r.get("msgs") or [""])[0])}'
    else:
        emo = "⚡" if "spike" in types else "🚀"
        lab = emo + " " + esc(" · ".join(AL.TYPE_KO.get(k, k) for k in types))
    more = f' <span class="tiny">(24시간 {g["n"]}번)</span>' if g["n"] > 1 else ""
    notes = []
    if "spike" in g["types"]: notes.append('⚠️ 추격 매수 주의 — 이미 급등한 뒤라 과거엔 이후 평균이 마이너스였어요')
    if "filing" in g["types"]:
        fl = (r.get("filing") or {}) if "filing" in types else {}
        u = fl.get("url")
        notes.append('⚠️ 키워드 자동 판정 · 원문 확인 필수' + (f' <a href="{esc(u)}" target="_blank" rel="noopener" style="position:relative;z-index:3">원문↗</a>' if u else ""))
    pxs = f' · 알림 때 {px(r.get("price"))}' if r.get("price") else ""
    return (f'<div style="background:#3a1d24;border:1px solid #ff4d5e55;border-radius:10px;padding:6px 10px;margin:-4px 0 10px;font-size:13px">'
            f'<b>{lab}</b> · {when} 한국시간{pxs}{more}'
            + "".join(f'<div class="tiny" style="margin-top:2px">{n}</div>' for n in notes) + '</div>')

def alerts_home():
    md('<div class="sec">🔔 방금 알림 온 종목</div>')
    gs = fresh_alerts()
    if not gs:
        md('<div class="tiny" style="margin:2px 2px 8px">아직 최근 24시간 동안 알림 온 종목이 없어요.</div>'); return
    warm_toss([g["ticker"] for g in gs])
    for g in gs:
        try: x = get_snap(g["ticker"])
        except Exception: x = None
        if x is None:
            md(h('<div class="card">', alert_strip(g), f'<div class="sym" style="font-size:20px;font-weight:900">{tlink(g["ticker"])}</div>',
                 f'<div class="tiny">{esc((g["last"].get("title") or ""))} · 종목 데이터를 아직 못 불러왔어요</div></div>'))
        else:
            md(home_card(g["ticker"], x, alert_strip(g)))
    md('<div class="tiny">최근 24시간 안에 폰으로 보낸 알림 기준 · 종목당 가장 최근 알림 1개 · 몇 분마다 새로 확인 (추정, 보장 아님)</div>')

# ---------------------------------------------------------------- 페이지: 홈
def top_picks(n=5, pool=20):
    """최근 스캔에서 악재 공시(증자·역분할·소송) 없는 상위 pool 종목의 확률을 계산해 높은 순 n개."""
    df, _ = scan.last_scan()
    if df is None or len(df) == 0: return []
    m = np.ones(len(df), bool)
    for k in ("dilution", "reverse_split", "lawsuit"):
        if k in df: m &= ~df[k].fillna(False).astype(bool).values
    out = []
    for t in df[m].sort_values("score", ascending=False).ticker.head(pool):
        try: x = get_snap(t)
        except Exception: continue
        pr = (x or {}).get("prob") or {}
        if pr.get("prob") is not None: out.append((t, x, (round(pr["prob"], 1), raw_score(x) or 0)))
    out.sort(key=lambda o: o[2], reverse=True)     # 확률 같으면 종합점수 높은 순
    return [(t, x) for t, x, _ in out[:n]]

def raw_score(x):
    """보정 전 종합점수 (0~100). 확률은 과거 검증 구간별로 묶여 같은 값이 나올 수 있어, 순위 구분용으로 함께 표시."""
    s = (x or {}).get("s") or {}
    r = (s.get("research") or {}).get("raw")
    v = r if r is not None else s.get("score")
    if v is None: return None
    v = float(v) + float((s.get("short") or {}).get("adj") or 0)   # 공매도 과밀·이탈 / 대차 보정 (확률에는 미반영)
    return max(0.0, min(100.0, v))

def short_lines(x, n=4, key="lines"):
    return list((((x or {}).get("s") or {}).get("short") or {}).get(key) or [])[:n]

def short_why(x):
    return list((((x or {}).get("s") or {}).get("short") or {}).get("why") or [])

def page_home():
    topbar("숏 레이더", "나스닥 초소형주 숏 분석")
    sess, now_et = live.session_now()
    md(f'<div class="tiny">{dt.datetime.now(live.KST):%m/%d %H:%M} KST · 미국 {live.SESSION_KO[sess]} · 자동 갱신 {REFRESH_MIN}분 {"켜짐" if LIVE_ON else "꺼짐"}</div>')
    run_every = f"{REFRESH_MIN * 60}s" if LIVE_ON and sess != "closed" else None

    @st.fragment(run_every=run_every or "180s")
    def alerts_sec():
        alerts_home()
    alerts_sec()

    @st.fragment(run_every=run_every)
    def top5():
        md('<div class="sec">🔥 오를 확률 TOP 5</div>')
        md(COPY_HINT)
        tops = top_picks(5)
        if not tops:
            md('<div class="card tiny">아직 스캔 결과가 없어요. 매일 자동 업데이트 뒤에 채워집니다.</div>'); return
        warm_toss([t for t, _ in tops])
        for i, (t, x) in enumerate(tops, 1):
            md(home_card(t, x))
        md('<div class="tiny">최근 스캔 상위 종목 중 확률이 높은 순 · 증자/역분할/소송 공시가 있는 종목은 뺐어요 (추정, 보장 아님)</div>')
    top5()
    md('<div class="sec">⭐ 관심종목</div>')

    @st.fragment(run_every=run_every)
    def cards():
        warm_toss(WATCH)
        slots = [st.empty() for _ in WATCH]
        for ph in slots: ph.markdown(ui.skeleton(5), unsafe_allow_html=True)
        for t, ph in zip(WATCH, slots):
            x = get_snap(t)
            with ph.container():
                if x is None: md(f'<div class="card">{esc(t)}: 데이터 없음</div>'); continue
                md(home_card(t, x))
    cards()
    md('<div class="sec">🎯 선별 · 초소형주 스크리너</div>')
    embedded(page_select)
    with st.expander("🔭 발굴 — 거래량 이상 상위 40"):
        embedded(page_discover)
    with st.expander("🧩 테마 — 업종별 스캔 결과"):
        embedded(page_theme)
    with st.expander("📈 전일 +30% 급등주 다음날 통계"):
        embedded(gainer_stats)
    disclaimer()

# ---------------------------------------------------------------- 페이지: 선별 (Rabbitstock 스타일)
def page_select():
    topbar("종목 선별", "PICK · 필터 · 런웨이")
    q = st.text_input("검색", "", placeholder="🔍 티커 또는 회사명 검색", label_visibility="collapsed")
    df, meta = scan.last_scan()
    c1, c2 = st.columns([2, 1])
    if c2.button("지금 스캔", width="stretch", help=f"나스닥 초소형주 유니버스 일봉 → 상위 {int(p['scan_top_k'])}종목 정밀분석 (캐시 시 약 1분, 첫 실행은 수 분)"):
        bar = st.progress(0.0, "스캔 중...")
        scan.run_scan(p, progress=lambda fr, t: bar.progress(fr, f"분석 중 {t}"))
        st.rerun()
    c1.caption(f"최근 스캔: {meta['ts']} · 유니버스 {meta['universe']}종목 → 1차 {meta['ranked']} → 정밀 {meta['scored']}" if meta else "스캔 기록 없음")
    if len(df) == 0:
        st.info("아직 스캔 결과가 없습니다. '지금 스캔'을 누르거나 scripts/update_daily.py 를 실행하세요."); return
    if q:
        u = db.q("SELECT ticker,name FROM universe")
        hit = u[u.ticker.str.contains(q.upper()) | u.name.fillna("").str.contains(q, case=False)].head(10)
        for r in hit.itertuples(): md(f'<div class="chip">{tlink(r.ticker, "<b>" + r.ticker + "</b> " + esc(r.name[:30]))}</div>')
    ex = {"dilution": "희석/증자", "reverse_split": "역분할", "lawsuit": "소송"}
    sel = st.session_state.setdefault("ex", {"dilution": True, "reverse_split": True, "lawsuit": True})
    cols = st.columns(3)
    for i, (k, lab) in enumerate(ex.items()):
        sel[k] = cols[i].toggle(f"{lab} 제외 ({int(df[k].sum())})", sel[k])
    tabs = st.tabs(["PICK +30%", "종목 선별", "런웨이"])
    mask = np.ones(len(df), bool)
    for k in ex:
        if sel[k]: mask &= ~df[k].astype(bool).values
    passed = df[mask]
    def grid(d, show):
        warm_toss(d.ticker)
        cells = []
        for i, r in enumerate(d.itertuples(), 1):
            ok = r.status == "가능"
            cells.append(f'<div class="tk {"ok" if ok else ""}"><a class="ov" href="?{ui.AUTHQ}p=stock&t={r.ticker}" target="_self" aria-label="{esc(r.ticker)} 상세"></a><div class="no">{i:02d}</div><div class="sym">{cpk(r.ticker, copy_text_row(r))}{tsb(r.ticker)}</div>'
                         f'<div class="st {"red" if ok else ("yellow" if r.status == "대기" else "muted")}">{esc(r.status)}</div><div class="tiny">{show(r)}</div>'
                         f'<div class="sum">▸ {esc(getattr(r, "summary", "") or "")}</div></div>')
        md('<div class="grid">' + "".join(cells) + '</div>')
    with tabs[0]:
        d = passed.sort_values(["flagged", "score"], ascending=False)
        md(f'<div class="muted" style="margin:6px 0">{len(df)}종목 중 <b class="red">{int(d.flagged.sum())}</b>종목 통과 (경보 조건) · 대기 {int((d.status == "대기").sum())}</div>')
        grid(d.head(30), lambda r: f'예상 {pct(r.upside, 0) if r.upside is not None and not pd.isna(r.upside) else "N/A"} · 점수 {r.score:.0f}')
        st.caption("예상 % = 재점화 레벨까지 거리 (추정, 보장 아님)")
    with tabs[1]:
        d = passed.sort_values("score", ascending=False)
        md(f'<div class="muted" style="margin:6px 0">{len(df)}종목 중 {len(d)}종목 통과 (제외 필터 적용)</div>')
        grid(d, lambda r: f'Lv{r.level} · 신호 {r.conf} · {px(r.price)}')
    with tabs[2]:
        d = passed.assign(rw=passed.runway.fillna(999)).sort_values("rw")
        grid(d, lambda r: f'런웨이 {"N/A" if pd.isna(r.runway) else f"{r.runway:.0f}개월"} · 희석 {r.dil_score}')
        st.caption("런웨이 = 현금 ÷ 월 영업현금소모 (SEC XBRL, 최신 공시 기준). 짧을수록 증자 위험↑")
    disclaimer()

# ---------------------------------------------------------------- 페이지: 오늘 / 발굴 / 테마
def page_today():
    topbar("오늘", "경보 · 트리거")
    df, meta = scan.last_scan()
    if len(df):
        al = df[(df.conf >= int(p["min_confluence"]))].sort_values("score", ascending=False)
        warm_toss(al.ticker)
        md(f'<div class="card"><h3>🔔 Confluence 경보 (동시 신호 ≥{int(p["min_confluence"])})</h3>' + ("".join(
            f'<div class="between" style="padding:4px 0">{tlink(r.ticker, "<b>" + r.ticker + "</b>")}<span class="tiny">{esc(", ".join(model.SIG_NAME.get(k, k) for k in r.on.split(",") if k))}</span><span>점수 {r.score:.0f}</span></div>'
            for r in al.itertuples()) or '<div class="muted">해당 종목 없음</div>') + '</div>')
    lg = db.q("SELECT ts,ticker,kind,data FROM scans WHERE kind LIKE 'live_%' ORDER BY rowid DESC LIMIT 30")
    alert_log_card()
    warm_toss(lg.ticker)
    md('<div class="card"><h3>⚡ 라이브 트리거 로그</h3>' + ("".join(f'<div class="ev"><div class="d">{esc(r.ts[5:16])}</div><div>{tlink(r.ticker, "<b>" + r.ticker + "</b>")} {esc(json.loads(r.data)["msg"])}</div></div>' for r in lg.itertuples()) or '<div class="muted">아직 없음</div>') + '</div>')
    if not EMBED["on"]: gainer_stats()
    disclaimer()

def gainer_stats():
    g = scan.gainer_continuation(30)
    if len(g):
        md(h('<div class="card"><h3>📈 전일 +30% 급등주 다음날 (DB 내 종목)</h3>',
             f'<div class="tiny">표본 {len(g)} · 다음날 시가 갭 평균 {g.next_open.mean():+.1f}% · 다음날 고가 평균 {g.next_high.mean():+.1f}% · 종가 평균 {g.next_close.mean():+.1f}% · 종가 상승 비율 {(g.next_close > 0).mean() * 100:.0f}%</div></div>'))

def page_discover():
    topbar("발굴", "거래량 이상 · 응축")
    u = scan.universe()
    qr = scan.quick_rank(list(u.ticker), p)
    if len(qr) == 0:
        st.info("가격 데이터가 없습니다. 선별 탭에서 스캔을 먼저 실행하세요."); return
    qr = qr.merge(u[["ticker", "name"]], on="ticker", how="left").head(40)
    warm_toss(qr.ticker)
    md('<div class="card"><h3>🔭 거래량 이상 상위 40</h3>' + "".join(
        f'<div class="between" style="padding:3px 0;border-bottom:1px dashed #262c3b;font-size:12.5px">{tlink(r.ticker, "<b>" + r.ticker + "</b>")} <span class="tiny">{esc(str(r.name)[:16])}</span>'
        f'<span>{px(r.price)} · 거래량 {"50배+" if r.vol_ratio >= 50 else f"{r.vol_ratio:.1f}배"} · 5일 {pct(r.ret5, 0)}</span></div>' for r in qr.itertuples()) + '</div>')
    disclaimer()

def page_theme():
    topbar("테마", "섹터별 스캔 결과")
    df, _ = scan.last_scan()
    if len(df) == 0: st.info("스캔 결과 없음"); return
    warm_toss(df.ticker)
    df["sector"] = [(db.kv_get(f"info:{t}") or {}).get("industry") or "기타" for t in df.ticker]
    for sec, g in df.groupby("sector"):
        md(f'<div class="card"><div class="between"><b>{esc(sec)}</b><span class="muted">{len(g)}종목 · 평균 점수 {g.score.mean():.0f}</span></div><div class="chips">'
           + "".join(f'<span class="chip {"on" if r.flagged else ""}">{tlink(r.ticker)} {r.score:.0f}</span>' for r in g.sort_values("score", ascending=False).itertuples()) + '</div></div>')

# ---------------------------------------------------------------- 페이지: 실시간
def page_live():
    topbar("실시간", "관심종목 라이브")
    sess, _ = live.session_now()
    st.caption(f"자동 갱신 {REFRESH_MIN}분 · yfinance 1분봉(prepost) · 무료 데이터는 수 분 지연될 수 있음 · 현재 미국 {live.SESSION_KO[sess]}")
    @st.fragment(run_every=f"{REFRESH_MIN * 60}s" if LIVE_ON else None)
    def tbl():
        warm_toss(WATCH)
        rows = []
        for t in WATCH:
            x = get_snap(t)
            if not x: continue
            eh = x["eh"]; last = eh.get("last") or x["f"]["price"]; prev = eh.get("prev_close")
            rows.append(f'<tr><td>{cpk(t, copy_text(t, x), label="<b>" + esc(t) + "</b>")}{tsb(t)}</td><td>{px(last)}</td><td class="{ui.cls((last / prev - 1) if prev else 0).replace("green", "blue")}">{pct((last / prev - 1) * 100 if prev else None)}</td>'
                        f'<td>{x["s"]["score"]:.0f}</td><td>{"—" if x["prob"].get("prob") is None else f"{x["prob"]["prob"]:.0f}%"}</td><td>{px(x["meta"].get("reignite"))}</td><td class="red">{"⚡" * len(x["triggers"])}</td></tr>')
        md(f'<div class="card"><div class="tiny"><span class="badge {"live" if sess != "closed" else ""}">실시간</span> 갱신 {dt.datetime.now(live.KST):%H:%M:%S} KST</div>'
           f'<table class="t"><tr><th>종목</th><th>현재</th><th>등락</th><th>점수</th><th>확률</th><th>재점화</th><th>트리거</th></tr>{"".join(rows)}</table></div>')
        lg = db.q("SELECT ts,ticker,data FROM scans WHERE kind LIKE 'live_%' ORDER BY rowid DESC LIMIT 15")
        for r in lg.itertuples(): md(f'<div class="ev"><div class="d">{esc(r.ts[5:16])}</div><div>{tlink(r.ticker, "<b>" + r.ticker + "</b>")} {esc(json.loads(r.data)["msg"])}</div></div>')
    tbl()
    with st.expander("🔔 오늘 — Confluence 경보 · 전체 트리거 로그", expanded=True):
        embedded(page_today)
    st.caption("폰 알림: 클라우드(GitHub Actions) 또는 PC 의 run_alerts.bat / run_alerts.command — 설정은 관리 탭 · README 참고")
    disclaimer()


# ---------------------------------------------------------------- 성공·실패 사례 분석 요약 (docs/SUCCESS_ANALYSIS.md)
def success_analysis_box():
    from pathlib import Path
    f = Path(__file__).resolve().parent / "model" / "success_analysis.json"
    if not f.exists(): return
    J = json.loads(f.read_text(encoding="utf-8")); fb, fa = J["final"]["before"], J["final"]["after"]
    pc = lambda v, d=1: f"{v*100:.{d}f}%"
    with st.expander("🔍 왜 올랐고 왜 실패했나 — 사례 원인 분석 · 최종 적중률 (연구 요약)", expanded=False):
        st.markdown(f"**최종 적중률 (표본외 · 상위 5% 경보 · 5거래일 내 +30%)**: **{pc(fb['prec'])}** (95% CI {pc(fb['ci'][0])}–{pc(fb['ci'][1])}, n={fb['n']:,}) · 기본율 {pc(fb['base'])} · lift {fb['lift']:.2f}배 · AUC {fb['auc']:.3f}")
        st.markdown(f"사례 분석 반영 실험 모델: {pc(fa['prec'])} (CI {pc(fa['ci'][0])}–{pc(fa['ci'][1])}, n={fa['n']:,}, AUC {fa['auc']:.3f}) — 차이 CI {J['final']['diff_ci'][0]*100:+.1f}–{J['final']['diff_ci'][1]*100:+.1f}%p 로 **유의하지 않아 미채택**. "
                    f"매매 기대값(청산 규칙 학습폴드 선택): 이전 {pc(fb['exp'],2)} → 실험 {pc(fa['exp'],2)}, 둘 다 CI 가 0 포함 → **검증된 수익 규칙 없음**.")
        st.caption(f"이벤트 기준(같은 종목 7일 내 경보 묶음, {J['final']['n_events']}개): 첫 경보 적중 {pc(J['final']['event_first'])}, 한 번이라도 적중 {pc(J['final']['event_any'])}")
        c1, c2 = st.columns(2)
        c1.markdown(f"**성공 원인 (n={J['n_success']})**\n\n" + "\n".join(f"- {c['cat']}: {c['n']} ({pc(c['pct'],0)})" for c in J["success_cats"]))
        c2.markdown(f"**실패 원인 (n={J['n_fail']})**\n\n" + "\n".join(f"- {c['cat']}: {c['n']} ({pc(c['pct'],0)})" for c in J["fail_cats"]))
        t = J["timing"]
        st.markdown(f"- 원인이 확인된 성공 {t['known']}건 중 **{t['after']}건은 재료가 경보 이후에 공개** → 재료보다 거래량·가격이 먼저 움직임\n"
                    "- **경보 볼 때 확인할 것**: 최근 30일 안에 424B(공모) 공시가 있으면 과거 적중률이 약 절반 (아래 표)\n"
                    "- 같은 PR 급등이라도 직후 공모·재판매 등록·역분할 발표가 붙으면 실패 쪽. 역분할 '직후'는 급등, '발표 시점'은 덤프가 많았음")
        st.dataframe(pd.DataFrame([dict(특징=x["f"], 경보수=x["n"], 적중률=pc(x["hit"]), 나머지=pc(x["rest"]), 배수=round(x["lift"], 2)) for x in J["features"]]), hide_index=True, width="stretch")
        cfg = {"근거": st.column_config.LinkColumn("근거", display_text="열기")}
        for nm, rows in (("성공 사례", J["success"]), ("실패 사례", J["fail"])):
            st.markdown(f"**{nm}** (링크 = 실제 기사/SEC 공시, 없으면 검색 링크)")
            st.dataframe(pd.DataFrame([{"티커": r["ticker"], "경보일": r["date"], "5일최고": pc(r["max5"], 0), "10일최저": pc(r["min10"], 0), "분류": r["cat"], "원인": r["cause"], "근거": r["link"], "경보시 신호": r["signals"]} for r in rows]),
                         hide_index=True, width="stretch", column_config=cfg, height=260)
        st.caption("전체 보고서: docs/SUCCESS_ANALYSIS.md · 수작업 분류(오류 가능) · 생존 편향 있음 · 모든 수치는 과거 데이터 추정치 · 투자 권유 아님")

# ---------------------------------------------------------------- 과거 사례 카드 (시점 기준 SHFS 스타일 재구성)
@st.cache_resource(show_spinner=False, max_entries=20)
def _hist(t, d):
    return model.hist_case(t, d, p)

def hist_cards_box():
    from pathlib import Path
    fp = Path(__file__).resolve().parent / "model" / "case_cards.json"
    if not fp.exists(): return
    C = json.loads(fp.read_text(encoding="utf-8"))
    G = (model.research_defs() or {}).get("grid_note")
    with st.expander(f"🗂️ 과거 사례 카드 — 경보 시점 그대로 재구성 ({len(C)}건, 숏 차수·재점화·커버 압력)", expanded=False):
        st.caption("각 카드는 경보일 종가까지 공개된 데이터만으로 다시 계산한 것입니다(FINRA 일별 공매도 실데이터 + Nasdaq 공표 SI로 스케일). "
                   "차수·잔존 수량·손실권 비율은 모두 추정치이며, 과거 시점의 대차이자·빌릴 수 있는 주식 수는 무료 소스가 없어 표시하지 않습니다.")
        f1, f2 = st.columns(2)
        grp = f1.selectbox("구분", ["전체", "성공 사례", "실패 사례"], key="hc_grp")
        res = f2.selectbox("셋업 결과", ["전체", "성공+고점 재시험", "성공(재점화 도달)", "실패(지지 이탈 먼저)", "미도달(기간 종료)"], key="hc_res")
        C = sorted(C, key=lambda c: (c.get("cat") == "데이터 오류", c["group"] != "success", c["date"]))
        L = [c for c in C if (grp == "전체" or c["group"] == {"성공 사례": "success", "실패 사례": "fail"}[grp]) and (res == "전체" or c["result"] == res)]
        if not L: st.info("조건에 맞는 사례 없음"); return
        lab = lambda c: ("⚠️데이터오류 · " if c.get("cat") == "데이터 오류" else "") + f'{c["ticker"]} · {c["date"]} · {"급등" if c["group"] == "success" else "실패"} 사례 · 셋업 {c["result"]} · 레벨 {c["level"]} · 커버압력 {c["cp"]:.0f}'
        i = st.selectbox("사례 선택", range(len(L)), format_func=lambda j: lab(L[j]), key="hc_pick")
        c = L[i]
        x = _hist(c["ticker"], c["date"])
        if not x: st.warning("이 시점 데이터가 부족합니다."); return
        x = dict(x, hist=True)
        md(f'<div class="card"><div class="tiny">⏪ 시점 {c["date"]} 종가 기준 재구성 · 셋업 결과: <b>{esc(c["result"])}</b> · 분류: {esc(c.get("cat") or "")}</div>'
           f'<div style="font-size:13px;margin-top:4px">원인(수작업 조사): {esc(c.get("cause") or "")}</div></div>')
        md('<div class="carousel">' + card_alert(x) + card_borrow(x) + card_ladder(x) + card_table(x) + '</div><div class="dots">◀ 옆으로 넘기기 · 1 경보 · 2 이벤트/커버압력 · 3 사다리 · 4 밴드표 ▶</div>')
        post = "".join(f'<div class="ev"><div class="n" style="background:#64748b">▶</div><div class="d">{pd.Timestamp(d):%m/%d}</div><div>{esc(t)}</div></div>' for d, t in x["post"])
        md(f'<div class="card"><h3>📈 사후 결과 (경보 이후 — 카드 계산에는 사용 안 함)</h3>{post}'
           '<div class="tiny">판정 규칙: 같은 날 손절과 익절이 모두 닿으면 손절 우선(보수적). 재점화 도달 시 50% 익절 + 손절을 진입가로 상향, 나머지는 21일 고점 재시험 또는 10거래일 종가 청산.</div></div>')
        if c.get("link"): st.markdown(f"[근거 링크 열기]({c['link']})")

def success_def_box():
    D = model.research_defs()
    if not D: st.caption("성공 정의별 모델 없음 (scripts/target_grid.py 실행 필요)"); return
    with st.expander("🎯 성공 정의 · 확률 카드 기준 (정의마다 따로 재학습·보정)", expanded=True):
        cur = P.load(); keys = list(D["defs"]) + ["legacy"]
        nm = lambda k: ("⭐ 권장 · " if k == D.get("recommended") else "") + (D["defs"][k]["label"] if k in D["defs"] else "기존 모델(고정 +30%/5일, research.json)")
        k0 = cur.get("success_def") or D.get("recommended", "setup")
        k = st.selectbox("확률 카드에 쓸 성공 정의", keys, index=keys.index(k0) if k0 in keys else 0, format_func=nm)
        if k in D["defs"]:
            o = D["defs"][k]["oos"]; t5 = o["top5"]
            st.caption(f"표본외(5폴드 워크포워드): 기본율 {o['base'] * 100:.1f}% · 상위 5% 적중 {t5['prec'] * 100:.1f}% (95% CI {t5['ci'][0] * 100:.1f}–{t5['ci'][1] * 100:.1f}%, n={t5['n']:,}) · "
                       f"lift {t5['lift']:.2f}배 · AUC {o['auc']:.3f} · Brier {o['brier']:.3f}")
        st.dataframe(pd.DataFrame([{"정의": nm(q), "기본율%": round(v["oos"]["base"] * 100, 1), "상위5% 적중%": round(v["oos"]["top5"]["prec"] * 100, 1),
                                    "lift": round(v["oos"]["top5"]["lift"], 2), "AUC": round(v["oos"]["auc"], 3)} for q, v in D["defs"].items()]),
                     hide_index=True, width="stretch", height=240)
        st.caption("적중률이 높은 정의 = 목표가 가까운 정의일 뿐, 수익과는 별개입니다. 비용 0.6% 반영 매매 기대값은 docs/TARGET_GRID.md 참고 (어떤 정의도 95% CI가 0을 넘지 못함).")
        if st.button("성공 정의 저장", width="stretch"):
            P.save(dict(cur, success_def=k)); snap.clear(); st.success("저장됨 — 확률 카드가 이 정의로 다시 계산됩니다"); st.rerun()

# ---------------------------------------------------------------- 페이지: 추적 (타임머신 · 일지 · 리포트)
def page_track():
    topbar("타임머신", "백테스트 · 기록 · 매매일지 · 주간 리포트")
    tabs = st.tabs(["⏳ 타임머신", "📜 기록", "📓 매매일지", "🗓️ 주간 리포트"])
    with tabs[0]:
        md('<div class="card"><b>컨닝 모드 배제</b><div class="tiny">각 날짜 t 에서는 t 이전에 <b>공개된</b> 데이터만 사용합니다: 숏 잔고는 결제일+8영업일 후, FTD는 +21일 후, SEC 주식수는 공시일 이후, 가격·거래량은 t 종가까지. '
           '정답(라벨)은 t+1~t+N 고가로만 채점합니다. 기간 앞 60%로 확률을 보정(학습)하고 뒤 40%로 검증(walk-forward)합니다.</div></div>')
        success_analysis_box()
        forward_box()
        hist_cards_box()
        df, _ = scan.last_scan()
        default = ",".join(dict.fromkeys(WATCH + (list(df.sort_values("score", ascending=False).ticker.head(18)) if len(df) else [])))
        tick = st.text_area("검증 종목 (쉼표 구분)", default, height=70)
        c1, c2, c3 = st.columns(3)
        start = c1.date_input("시작", dt.date.today() - dt.timedelta(days=330))
        end = c2.date_input("종료", dt.date.today() - dt.timedelta(days=8))
        step = c3.number_input("간격(거래일)", 1, 20, 3)
        pp = dict(p)
        with st.expander("모델 파라미터 조정 (이번 검증에만 적용 · 저장은 관리 탭)"):
            cc = st.columns(2)
            for i, k in enumerate(["horizon_days", "target_pct", "stop_pct", "flag_score", "min_confluence", "regime_adj", "vol_mult", "si_change_pct", "loss_side_pct", "fee_pct"]):
                pp[k] = cc[i % 2].number_input(P.LABELS[k], value=float(p[k]), key=f"bt_{k}")
            st.markdown("**가중치**")
            cc = st.columns(3)
            for i, (k, wk, n) in enumerate(model.SIGNALS):
                pp[wk] = cc[i % 3].number_input(n, 0.0, 5.0, float(p[wk]), 0.1, key=f"bt_{wk}")
        label = st.text_input("메모(라벨)", "")
        if st.button("▶ 타임머신 실행", type="primary", width="stretch"):
            tl = [t.strip().upper() for t in tick.split(",") if t.strip()]
            bar = st.progress(0.0, "데이터 준비...")
            for i, t in enumerate(tl):
                if len(src.get_prices(t)) < 200: src.fetch_prices(t, "2y")
                if len(src.get_short_interest(t)) == 0: src.fetch_short_interest(t)
                if len(src.get_filings(t)) == 0: src.fetch_filings(t)
                bar.progress((i + 1) / len(tl) * 0.3, f"데이터 {t}")
            rid, m = model.run_backtest(tl, start, end, pp, step=int(step), label=label, progress=lambda fr, t: bar.progress(0.3 + fr * 0.7, f"검증 {t}"))
            snap.clear()
            st.session_state["bt_show"] = rid
        rid = st.session_state.get("bt_show") or model.latest_run_id()
        if rid: show_run(rid)
    with tabs[1]:
        runs = db.q("SELECT id, ts, label, metrics FROM bt_runs ORDER BY id DESC LIMIT 50")
        rows = []
        for r in runs.itertuples():
            m = json.loads(r.metrics); v = m.get("val", {})
            rows.append({"#": r.id, "시각": r.ts, "메모": r.label, "종목수": len(m.get("tickers", [])), "표본": m.get("all", {}).get("n"),
                         "검증 정밀도%": v.get("precision"), "검증 재현율%": v.get("recall"), "검증 기대값%": v.get("expectancy"), "검증 MDD%": v.get("max_dd")})
        st.dataframe(pd.DataFrame(rows).round(1), hide_index=True, width="stretch")
        pick = st.number_input("실행 번호 상세 보기", 0, 100000, 0)
        if pick: show_run(int(pick))
    with tabs[2]:
        journal()
    with tabs[3]:
        rp = sorted([f for f in os.listdir("data") if f.startswith("weekly_")]) if os.path.isdir("data") else []
        if st.button("주간 리포트 생성"):
            from scripts.weekly_report import build
            build(); st.rerun()
        if rp:
            st.markdown(open(os.path.join("data", rp[-1]), encoding="utf-8").read())
        else:
            st.caption("리포트 없음 (scripts/weekly_report.py)")
    disclaimer()

def show_run(rid):
    r = db.q("SELECT * FROM bt_runs WHERE id=?", (rid,))
    if len(r) == 0: return
    m = json.loads(r["metrics"].iloc[0]); pr = json.loads(r["params"].iloc[0])
    st.markdown(f"##### 실행 #{rid} · {r['ts'].iloc[0]} · {pr['horizon_days']}일 내 +{pr['target_pct']:.0f}% · 학습/검증 분기 {m.get('cut')}")
    def mrow(name, x):
        f = lambda v, s="%": "N/A" if v is None else f"{v:.1f}{s}"
        return (f'<tr><td>{name}</td><td>{x.get("n", 0)}</td><td>{f(x.get("base_rate"))}</td><td>{x.get("flags", 0)}</td><td>{f(x.get("accuracy"))}</td><td>{f(x.get("precision"))}</td>'
                f'<td>{f(x.get("recall"))}</td><td class="red">{f(x.get("avg_loss_wrong"))}</td><td>{f(x.get("max_dd"))}</td><td><b>{f(x.get("expectancy"))}</b></td></tr>')
    md('<div class="card" style="overflow-x:auto"><table class="t"><tr><th>구간</th><th>표본</th><th>기본율</th><th>경보</th><th>정확도</th><th>정밀도<br>(적중률)</th><th>재현율</th><th>틀릴 때<br>평균손실</th><th>MDD</th><th>기대값</th></tr>'
       + mrow("학습", m["train"]) + mrow("<b>검증</b>", m["val"]) + mrow("전체", m["all"]) + '</table>'
       f'<div class="tiny">기본율 = 아무 날이나 샀을 때 {pr["horizon_days"]}일 내 +{pr["target_pct"]:.0f}% 도달 비율. 거래 규칙: 신호일 종가 매수 → +{pr["target_pct"]:.0f}% 익절 / -{pr["stop_pct"]:.0f}% 손절 / 기간 종료 청산 (같은 날 둘 다면 손절로 간주). '
       'MDD = 신호마다 자본 10% 투입 가정 누적곡선. 정확도는 경보가 드물수록 기본적으로 높게 나오므로 정밀도·기대값을 보세요.</div></div>')
    cal = m.get("val", {}).get("calib")
    if cal:
        st.markdown("**확률 보정 검증** (학습구간 예측 vs 검증구간 실제)")
        st.dataframe(pd.DataFrame(cal).rename(columns={"bin": "구간", "pred": "예측%", "actual": "검증 실제%", "n_val": "검증 표본"}).round(1), hide_index=True, width="stretch")
    imp = pd.DataFrame(m.get("importance", []))
    if len(imp):
        st.markdown("**신호별 기여도 (학습구간)** — lift = 신호 ON 시 적중률 ÷ 기본율")
        st.dataframe(imp.drop(columns=["key"]).rename(columns={"signal": "신호", "n_on": "ON 표본", "hit_on": "ON 적중%", "lift": "lift", "corr": "상관", "w": "현재 가중치", "w_new": "제안 가중치"}).round(2),
                     hide_index=True, width="stretch")
        if st.button("제안 가중치 적용 (관리 설정에 저장)", key=f"apply_{rid}"):
            cur = P.load()
            for r_ in imp.itertuples():
                wk = dict((k, w) for k, w, _ in model.SIGNALS)[r_.key]; cur[wk] = float(r_.w_new)
            P.save(cur); snap.clear(); st.success("저장됨. 다시 타임머신을 돌려 검증하세요 (과최적화 주의).")

def journal():
    st.caption("직접 매매를 기록하면 반복되는 실수를 분석합니다. (모의투자 기능 없음)")
    with st.form("jf", clear_on_submit=True):
        c = st.columns(3)
        d = c[0].date_input("날짜", dt.date.today()); t = c[1].text_input("티커").upper(); side = c[2].selectbox("방향", ["매수", "공매도"])
        c = st.columns(4)
        e = c[0].number_input("진입가", 0.0, format="%.4f"); x = c[1].number_input("청산가(0=보유)", 0.0, format="%.4f")
        sh = c[2].number_input("수량", 0, step=100); stp = c[3].number_input("계획 손절가", 0.0, format="%.4f")
        reason = st.text_input("진입 이유 (예: 재점화 돌파, 추격, 뉴스)"); notes = st.text_input("메모")
        if st.form_submit_button("기록 추가") and t and e > 0:
            db.exec_("INSERT INTO journal(date,ticker,side,entry,exit,shares,stop,reason,notes) VALUES(?,?,?,?,?,?,?,?,?)", (str(d), t, side, e, x or None, sh, stp or None, reason, notes))
    j = db.q("SELECT * FROM journal ORDER BY date DESC")
    if len(j) == 0: st.caption("기록 없음"); return
    j["pl%"] = np.where(j["exit"].notna(), (j["exit"] / j["entry"] - 1) * 100 * np.where(j["side"] == "공매도", -1, 1), np.nan)
    st.dataframe(j.round(2), hide_index=True, width="stretch")
    mis = []
    for r in j.itertuples():
        if not r.stop: mis.append(("손절가 미설정", r.ticker))
        elif r.exit and r.side == "매수" and r.exit < r.stop * 0.98: mis.append(("손절 미준수 (계획보다 더 손실)", r.ticker))
        if r.reason and any(k in r.reason for k in ("추격", "FOMO", "급등")): mis.append(("급등 추격 매수", r.ticker))
        pxd = src.get_prices(r.ticker)
        if len(pxd):
            dd = pxd[pxd.date <= pd.Timestamp(r.date)]
            if len(dd) > 1 and dd.close.iloc[-1] / dd.close.iloc[-2] > 1.3: mis.append(("+30% 이상 오른 날 진입", r.ticker))
            if len(dd) > 20 and (dd.close * dd.volume).tail(20).mean() < 1e6: mis.append(("저유동성 종목 진입", r.ticker))
        if r.stop and r.entry and r.side == "매수":
            pass
    closed = j[j["pl%"].notna()]
    if len(closed):
        st.caption(f"청산 {len(closed)}건 · 승률 {(closed['pl%'] > 0).mean() * 100:.0f}% · 평균 {closed['pl%'].mean():+.1f}% · 평균 이익 {closed[closed['pl%'] > 0]['pl%'].mean():+.1f}% / 평균 손실 {closed[closed['pl%'] <= 0]['pl%'].mean():+.1f}%")
    if mis:
        cnt = pd.Series([m for m, _ in mis]).value_counts()
        st.markdown("**반복되는 실수**\n" + "\n".join(f"- {k}: {v}회" for k, v in cnt.items()))


# ---------------------------------------------------------------- 폰 알림: 기록 · 사후 적중률 · 설정
GRADE_KO = {"hit": ("적중", "green"), "miss": ("실패", "red"), "open": ("채점 중", ""), "open_hit": ("목표 도달·진행", "yellow"), "n/a": ("채점 불가", "")}

def _alog():
    try: return AL.dashboard_log()
    except Exception: return AL.load_log(), "이 컴퓨터"

def alert_log_card(limit=20):
    log, where = _alog()
    rows = [r for r in reversed(log) if not r.get("dry")][:limit]
    warm_toss([r["ticker"] for r in rows])
    def one(r):
        g, gc = GRADE_KO.get(r.get("grade"), (r.get("grade"), ""))
        st_ = "📲 전송" if r.get("sent") else ("🔕 " + r["suppressed"] if r.get("suppressed") else "⚠ 전송 실패")
        pen = f' <span class="badge red">⚠ {esc(r["penalties"][0])}</span>' if r.get("penalties") else ""
        if r.get("filing"):
            fl = r["filing"]
            return (f'<div class="ev"><div class="d">{esc(r["ts_kst"][5:])}</div><div>{tlink(r["ticker"], "<b>" + esc(r["ticker"]) + "</b>")} '
                    f'📢 호재 공시 · <a href="{esc(fl.get("url") or "")}" target="_blank">{esc(fl.get("form"))}</a> {esc(fl.get("label"))} <span class="tiny">{st_}</span>{pen}'
                    f'<div class="tiny">{esc((fl.get("headline") or "")[:120])}</div></div></div>')
        return (f'<div class="ev"><div class="d">{esc(r["ts_kst"][5:])}</div><div>{tlink(r["ticker"], "<b>" + esc(r["ticker"]) + "</b>")} '
                f'{esc(" · ".join(AL.TYPE_KO.get(k, k) for k in r["types"]))} · {px(r.get("price"))} <span class="tiny">{st_}</span> <span class="badge {gc}">{esc(g)}</span>{pen}</div></div>')
    md(f'<div class="card"><h3>📲 보낸 알림 기록</h3>' + ("".join(one(r) for r in rows) or '<div class="muted">아직 보낸 알림이 없습니다.</div>')
       + f'<div class="tiny">기록 위치: {esc(where)} · 채점: 알림 다음 거래일부터 10거래일 일봉으로 목표(재점화 레벨) 먼저 닿으면 적중, 손절 먼저 또는 미도달이면 실패</div></div>')

def forward_box():
    log, where = _alog()
    fs = AL.forward_stats(log)
    if fs["n"]:
        body = (f'채점 완료 <b>{fs["n"]}</b>건 중 적중 <b>{fs["hits"]}</b>건 → <b>{fs["rate"]:.1f}%</b> (95% CI {fs["ci"][0]:.1f}–{fs["ci"][1]:.1f}%)'
                + (f' · 평균 수익 {fs["avg_ret"]:+.2f}% (비용 0.6% 차감, 50% 익절+본전 스탑 규칙)' if fs.get("avg_ret") is not None else ""))
    else:
        body = "아직 채점이 끝난 알림이 없습니다 (알림 후 최대 10거래일 필요)."
    md(f'<div class="card"><h3>🧾 실전 알림 사후 적중률 (전진 검증)</h3><div style="font-size:13px">{body}</div>'
       f'<div class="tiny">전체 알림 {fs["total"]}건 · 채점 중 {fs["open"]}건 · 과거 백테스트(표본외) 상위 5% 셋업 적중 55.6%와 비교하세요. 표본이 30건 미만이면 우연 변동이 큽니다. 기록: {esc(where)}</div></div>')
    good_filings_card()

def _flog():
    try: return AL.dashboard_filings() or []
    except Exception: return []

POL_KO = {"pos": ("호재", "green"), "neg": ("악재", "red"), "neutral": ("중립", "")}
def filing_row(f, with_ticker=True):
    lab, cl = POL_KO.get(f.get("polarity"), ("중립", ""))
    tk = (tlink(f["ticker"], "<b>" + esc(f["ticker"]) + "</b>") + " ") if with_ticker else ""
    return (f'<div class="ev"><div class="d">{esc(f.get("accepted_kst") or "")}</div><div>{tk}<span class="badge {cl}">{lab}</span> '
            f'<a href="{esc(f.get("url") or "")}" target="_blank">{esc(f.get("form"))}</a> {esc(f.get("label") or "")}'
            f'<div class="tiny">{esc((f.get("headline") or "")[:130])}</div></div></div>')

def good_filings_card(limit=8):
    rows = [f for f in reversed(_flog()) if f.get("polarity") == "pos"][:limit]
    md('<div class="card"><h3>📢 호재 공시 알림 (최근)</h3>' + ("".join(filing_row(f) for f in rows) or '<div class="muted">아직 잡힌 호재 공시가 없습니다.</div>')
       + '<div class="tiny">감시 종목(관심종목·최근 스캔 상위·최근 알림 종목)의 SEC 새 공시를 8-K 항목 번호와 보도자료 키워드로 자동 판정합니다. '
         '증자·역분할·상폐 경고 같은 악재가 함께 있으면 호재로 보지 않습니다. 키워드 판정이라 틀릴 수 있으니 원문을 꼭 확인하세요.</div></div>')

def alert_settings():
    c = AL.cfg()
    with st.expander("📲 폰 알림 (급등 신호) · 토스 링크", expanded=True):
        st.markdown(f"**1) 폰에 ntfy 앱 설치 → ‘구독(Subscribe)’ → 주제 이름 입력:** `{c['ntfy_topic']}`"
                    + (" *(클라우드 Secrets 값 사용 중)*" if c.get("ntfy_topic_from_secret") else ""))
        st.caption("주제 이름이 곧 비밀번호입니다. 남이 알면 알림을 볼 수 있으니 공유하지 마세요. 서버: " + c["ntfy_server"])
        a, b = st.columns(2)
        ch = a.selectbox("알림 채널", ["ntfy", "telegram", "both"], index=["ntfy", "telegram", "both"].index(c["channel"]),
                         format_func={"ntfy": "ntfy (기본·무료)", "telegram": "텔레그램", "both": "둘 다"}.get)
        en = b.toggle("알림 켜기", c.get("enabled", True))
        types = st.multiselect("알림 받을 신호", list(AL.TYPE_KO)[:-1], c["types"], format_func=AL.TYPE_KO.get)
        a, b, d = st.columns(3)
        pm = a.number_input("확률 기준 % (0=모델 상위5%)", 0.0, 100.0, float(c["prob_min"]), 5.0)
        cp = b.number_input("커버 압력 기준 (0~100)", 0.0, 100.0, float(c["cp_min"]), 5.0)
        gp = d.number_input("프리마켓 갭 기준 %", 0.0, 500.0, float(c["gap_min"]), 5.0)
        a, b = st.columns(2)
        sc = a.number_input("장중 급등: 전일 대비 % 이상", 5.0, 300.0, float(c.get("spike_chg", 15)), 5.0)
        sr = b.number_input("장중 급등: 거래량 배수 이상 (시간 보정)", 1.0, 50.0, float(c.get("spike_rvol", 3)), 0.5)
        st.caption("‘장중 급등 포착’은 레벨과 상관없이 울립니다. 백테스트상 급등 당일 이후 평균 수익은 마이너스(되돌림)라 추격 매수 경고를 붙입니다. "
                   "‘호재 공시’는 새 공시마다 한 번씩 울립니다(재알림 간격 미적용).")
        a, b, d = st.columns(3)
        ml = a.slider("최소 레벨", 1, 5, int(c["min_level"]))
        cd = b.number_input("재알림 간격(분)", 15, 1440, int(c["cooldown_min"]), 15)
        mx = d.number_input("대상 최대 종목 수", 5, 60, int(c.get("max_tickers", 25)), 5)
        a, b, d, e = st.columns(4)
        qo = a.toggle("방해 금지", c["quiet_on"]); qs = b.text_input("시작(KST)", c["quiet_start"]); qe = d.text_input("끝(KST)", c["quiet_end"])
        qm = e.selectbox("방해 금지 중", ["silent", "skip"], index=["silent", "skip"].index(c["quiet_mode"]), format_func={"silent": "무음으로 받기", "skip": "보내지 않기"}.get)
        pmode = st.radio("증자(424B 30일)·역분할·희석 위험 종목", ["mark", "suppress"], index=["mark", "suppress"].index(c["penalty_mode"]),
                         format_func={"mark": "⚠ 표시하고 보내기", "suppress": "보내지 않기 (기록만)"}.get, horizontal=True)
        tm = st.radio("토스 링크 방식", list(toss.MODES), index=list(toss.MODES).index(db.get_setting("toss_mode", "onelink")), format_func=toss.MODES.get, horizontal=True)
        du = st.text_input("대시보드 주소 (알림에 ‘대시보드’ 버튼, 선택)", c.get("dash_url") or "", placeholder="https://내앱.streamlit.app")
        b1, b2, b3 = st.columns(3)
        if b1.button("알림 설정 저장", type="primary", width="stretch"):
            rr = AL.save_cfg(dict(c, channel=ch, enabled=en, types=types, prob_min=pm, cp_min=cp, gap_min=gp, spike_chg=sc, spike_rvol=sr, min_level=ml, cooldown_min=cd, max_tickers=mx,
                             quiet_on=qo, quiet_start=qs[:5], quiet_end=qe[:5], quiet_mode=qm, penalty_mode=pmode, toss_mode=tm))
            db.set_setting("toss_mode", tm); db.set_setting("dash_url", du.strip()); _turl.clear()
            st.success("저장됨" + {None: "", True: " · GitHub(클라우드 알림 스캐너)에도 반영됨", False: " · ⚠ GitHub 반영 실패 (GH_TOKEN 권한: Contents 읽기/쓰기 확인)"}[rr])
        if b2.button("테스트 알림 보내기", width="stretch"):
            res = AL.test(AL.cfg())
            st.write("결과: " + ", ".join(f"{k} HTTP {v}" for k, v in res.items()) + (" ✅ 폰을 확인하세요" if AL.ok(res) else " ❌ 실패 (채널 설정 확인)"))
        if b3.button("주제 이름 새로 만들기", width="stretch", disabled=bool(c.get("ntfy_topic_from_secret"))):
            AL.save_cfg(dict(c, ntfy_topic=AL.new_topic())); st.rerun()
        tg = bool(c.get("tg_token") and c.get("tg_chat"))
        st.caption(f"텔레그램: {'설정됨' if tg else '미설정 (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 를 환경변수 또는 Secrets 에)'} · "
                   "알림은 이 화면이 아니라 ‘알림 스캐너’가 보냅니다: 클라우드면 GitHub Actions(자동), PC면 run_alerts.bat / run_alerts.command 실행")
        st.markdown(f"토스 링크 예시: {tsb('SOUN')} {tsb('TSLA')}", unsafe_allow_html=True)

# ---------------------------------------------------------------- 페이지: 관리
def page_admin():
    topbar("관리", "설정 · 데이터 소스")
    md('<div class="card"><h3>🧠 페르소나</h3><div style="font-size:13px">이 도구는 <b>나스닥 소형주 급등 탐지 전문가</b> 관점으로 설계됐습니다: 숏 재축적 → 손실권 전환 → 커버 압력을 추적하고, '
       '희석·상폐·유동성 위험을 먼저 거릅니다. 단, 모든 수치는 무료 데이터 기반 추정이며 투자 자문이 아닙니다.</div></div>')
    w = st.text_input("관심종목 (쉼표)", ",".join(WATCH))
    c = st.columns(2)
    rm = c[0].slider("자동 갱신 (분)", 1, 5, REFRESH_MIN); lo = c[1].toggle("장중 실시간 자동 갱신", LIVE_ON)
    if st.button("저장", type="primary"):
        db.set_setting("watchlist", [x.strip().upper() for x in w.split(",") if x.strip()]); db.set_setting("refresh_min", rm); db.set_setting("live_on", lo)
        st.success("저장됨"); st.rerun()
    alert_settings()
    forward_box()
    with st.expander("🔬 유니버스 · 스캔 필터 (초소형~소형주, 급등 잠재력)", expanded=True):
        cur = P.load(); uk = ["univ_max_mcap_m", "univ_max_price", "univ_min_price", "univ_min_dv_k", "univ_max_zero_days", "vol_base_floor", "scan_top_k",
              "univ_max_float_m", "low_float_m", "float_rot_x", "dtc_days", "low_inst_pct"]
        cc = st.columns(2); nu = {}
        for i, k in enumerate(uk):
            nu[k] = cc[i % 2].number_input(P.LABELS.get(k, k), value=float(cur[k]), key=f"un_{k}", format="%.2f" if k in ("univ_max_price", "univ_min_price", "float_rot_x", "dtc_days", "low_inst_pct") else "%.0f")
        u_now = scan.universe(dict(cur, **nu))
        st.caption(f"현재 조건 유니버스: {len(u_now)}종목 (시총·가격 기준, 거래대금·무거래일 필터는 스캔 때 적용) · 기본값: 시총 ≤ $300M, 가격 $0.05~$10, 일평균 거래대금 ≥ $100K, 무거래일 ≤ 3일, 유통주식 ≤ 50M주(정밀 분석 후), '소형 유통' < 20M주")
        if st.button("유니버스 설정 저장", width="stretch"):
            P.save(dict(cur, **nu)); snap.clear(); st.success("저장됨 — 다음 스캔부터 적용")
    with st.expander("모델 파라미터 (전체)"):
        cur = P.load(); new = dict(cur)
        cc = st.columns(2)
        for i, k in enumerate([k for k in P.DEFAULTS if isinstance(P.DEFAULTS[k], (int, float))]):
            new[k] = cc[i % 2].number_input(P.LABELS.get(k, k), value=float(cur[k]), key=f"pa_{k}", format="%.4f" if cur[k] < 1 and cur[k] != 0 else "%.2f")
        b1, b2 = st.columns(2)
        if b1.button("파라미터 저장"): P.save(new); snap.clear(); st.success("저장됨")
        if b2.button("기본값 복원"): P.save(dict(P.DEFAULTS)); snap.clear(); st.success("복원됨")
    success_def_box()
    st.markdown("#### 데이터 소스 상태")
    ss = db.q("SELECT name AS 소스, CASE ok WHEN 1 THEN '✅' ELSE '❌' END AS 상태, msg AS 메시지, ts AS 시각 FROM source_status ORDER BY name")
    st.dataframe(ss, hide_index=True, width="stretch")
    st.markdown("#### FINRA 일별 공매도 파일 수동 업로드")
    st.caption("FINRA CDN이 막힌 환경용. https://cdn.finra.org/equity/regsho/daily/CNMSshvolYYYYMMDD.txt 를 브라우저로 받아 올리세요 (여러 개 가능).")
    ups = st.file_uploader("CNMSshvol*.txt", type=["txt"], accept_multiple_files=True)
    if ups and st.button("가져오기"):
        n = sum(src.import_finra_file(u) or 0 for u in ups); snap.clear(); st.success(f"{n}행 저장")
    c = st.columns(2)
    if c[0].button("관심종목 데이터 갱신"):
        with st.spinner("갱신 중..."):
            for t in WATCH: src.refresh_ticker(t); src.fetch_info(t, ttl=0)
            src.update_threshold(10); src.update_finra(10, WATCH)
        snap.clear(); st.success("완료")
    st.caption(f"DB: {db.DB_PATH}")
    disclaimer()

# 하단 탭 5개. 예전 주소(?p=today/select/discover/theme)는 통합된 페이지로 연결
ALIAS = {"select": "home", "discover": "home", "theme": "home", "today": "live"}
PAGE = ALIAS.get(PAGE, PAGE)
PAGES = {"home": page_home, "stock": page_stock, "live": page_live, "track": page_track, "admin": page_admin}
PAGES.get(PAGE, page_home)()
md(ui.nav(PAGE, TICK))
