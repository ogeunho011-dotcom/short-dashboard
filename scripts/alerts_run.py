"""급등 신호 알림 스캐너 (PC 반복 실행 · GitHub Actions 1회 실행 공용).

  python scripts/alerts_run.py              # 1회 (장 마감 시간이면 건너뜀)
  python scripts/alerts_run.py --loop 10    # 10분마다 반복 (프리·정규·애프터 시간에만)
  python scripts/alerts_run.py --force      # 장 시간 무시하고 1회
  python scripts/alerts_run.py --test       # 테스트 알림만 전송
  python scripts/alerts_run.py --dry        # 판정만, 전송 안 함
  python scripts/alerts_run.py --grade      # 지난 알림 채점만

대상: 관심종목 + 최근 스크리너의 '가능/대기' 상위(점수순) — 관리 탭 '알림 대상 최대 종목 수'."""
import sys, os, time, json, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import db, params as P, live, alerts, scan

def targets(c):
    watch = db.get_setting("watchlist", ["SOUN", "OCGN"])
    df, _ = scan.last_scan()
    extra = []
    if len(df):
        d = df[df.status.isin(["가능", "대기"]) | df.flagged.astype(bool)].sort_values("score", ascending=False)
        extra = d.ticker.tolist()
    return list(dict.fromkeys(watch + extra))[: int(c.get("max_tickers", 25))]

def once(force=False, dry=False):
    t0 = time.time()
    sess = live.session_now()[0]
    if sess == "closed" and not force:
        print("장 마감 시간 — 건너뜀 (--force 로 강제)")
        alerts.grade_all(); return []
    c = alerts.cfg(); p = P.load()
    snaps = []
    for t in targets(c):
        db.exec_("DELETE FROM kv WHERE k=?", (f"live1m:{t}",))     # 1분봉 새로 받기
        try:
            snaps.append((t, live.snapshot(t, p, refresh_borrow=False)))
        except Exception as e:
            print(f"  {t}: 실패 {type(e).__name__}: {str(e)[:80]}")
    new = alerts.run(snaps, sess if sess != "closed" else "regular", dry=dry, c=c)
    alerts.grade_all()
    for r in new:
        print(f"[{'전송' if r['sent'] else ('억제: ' + str(r['suppressed']) if r['suppressed'] else ('dry' if r['dry'] else '실패 ' + json.dumps(r['result'])))}] {r['title']}")
    print(f"세션 {sess} · 종목 {len(snaps)} · 새 알림 {len(new)} · {time.time() - t0:.0f}s")
    return new

if __name__ == "__main__":
    db.init()
    a = sys.argv
    if os.environ.get("GITHUB_ACTIONS"):
        c0 = alerts.cfg()
        if c0["channel"] in ("ntfy", "both") and not os.environ.get("NTFY_TOPIC"):
            print("::error::GitHub Secrets 에 NTFY_TOPIC 이 없습니다. 저장소 Settings → Secrets and variables → Actions 에서 추가하세요."); sys.exit(1)
    if "--test" in a:
        print("테스트 전송:", alerts.test()); sys.exit(0)
    if "--grade" in a:
        alerts.grade_all(); print(alerts.forward_stats()); sys.exit(0)
    if "--loop" in a:
        mins = int(a[a.index("--loop") + 1])
        print(f"{mins}분마다 실행 (프리 04:00~애프터 20:00 ET). 이 창을 닫으면 멈춥니다.")
        while True:
            try: once(dry="--dry" in a)
            except Exception as e: print("오류:", e)
            time.sleep(mins * 60)
    else:
        once(force="--force" in a, dry="--dry" in a)
