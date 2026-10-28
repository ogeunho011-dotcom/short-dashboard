"""주간 모델 성과 리포트 → data/weekly_YYYYMMDD.md
과거 경보(스캔 기록이 아닌, 타임머신 최신 실행의 검증 구간) + 최근 7일 라이브 트리거 요약."""
import sys, os, json, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import db, model

def build():
    rid = model.latest_run_id()
    lines = [f"# 주간 모델 리포트 ({dt.date.today()})", ""]
    if rid:
        m = json.loads(db.q("SELECT metrics FROM bt_runs WHERE id=?", (rid,))["metrics"].iloc[0])
        v = m["val"]
        f = lambda x: "N/A" if x is None else f"{x:.1f}"
        lines += [f"## 최신 타임머신 #{rid} (검증 구간, walk-forward)", f"- 표본 {v.get('n')} · 기본율 {f(v.get('base_rate'))}% · 경보 {v.get('flags')}건",
                  f"- 정밀도(적중률) {f(v.get('precision'))}% · 재현율 {f(v.get('recall'))}% · 정확도 {f(v.get('accuracy'))}%",
                  f"- 틀릴 때 평균 손실 {f(v.get('avg_loss_wrong'))}% · 기대값 {f(v.get('expectancy'))}% · MDD {f(v.get('max_dd'))}%", ""]
        imp = [x for x in m.get("importance", []) if x.get("lift")]
        if imp:
            lines.append("## 신호 기여도 (lift 상위)")
            for x in sorted(imp, key=lambda x: -x["lift"])[:6]:
                lines.append(f"- {x['signal']}: lift {x['lift']:.2f} (ON {x['n_on']}건) → 제안 가중치 {x['w_new']}")
            lines.append("")
    since = (dt.datetime.now() - dt.timedelta(days=7)).strftime("%Y-%m-%d")
    lg = db.q("SELECT ts,ticker,data FROM scans WHERE kind LIKE 'live_%' AND ts >= ?", (since,))
    lines.append(f"## 최근 7일 라이브 트리거 {len(lg)}건")
    for r in lg.tail(20).itertuples():
        lines.append(f"- {r.ts} {r.ticker}: {json.loads(r.data)['msg']}")
    lines += ["", "_추정치 기반 · 투자 권유 아님_"]
    os.makedirs("data", exist_ok=True)
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", f"weekly_{dt.date.today():%Y%m%d}.md")
    open(path, "w", encoding="utf-8").write("\n".join(lines))
    return path

if __name__ == "__main__":
    print(build())
