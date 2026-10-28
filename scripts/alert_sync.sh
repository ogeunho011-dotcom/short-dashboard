#!/usr/bin/env bash
# 장중 반복 작업용: 알림 기록 브랜치(alertdata/) 동기화. 사용: alert_sync.sh pull | push
# 대시보드가 알림 설정(alert_cfg.json)을 같은 브랜치에 저장하므로, 매 회차 pull 로 최신 설정을 받고
# 바뀐 기록만 commit/push. 충돌 시 이 작업의 기록을 우선(-X theirs = rebase 중 내 커밋).
set -u
cd "${ALERT_REPO_DIR:-alertdata}" || exit 0
br="${ALERT_BRANCH:-alert-data}"
if [ "${1:-}" = "pull" ]; then
  git pull -q --rebase --autostash -X theirs origin "$br" 2>/dev/null || { git rebase --abort 2>/dev/null; echo "pull 실패(계속 진행)"; }
  exit 0
fi
git add -A data/alerts data/borrow 2>/dev/null
git diff --cached --quiet && exit 0
git -c user.name="shortradar-bot" -c user.email="41898282+github-actions[bot]@users.noreply.github.com" commit -q -m "alerts $(date -u +%Y-%m-%dT%H:%MZ)"
for i in 1 2 3; do
  git push -q origin "HEAD:$br" 2>/dev/null && exit 0
  git pull -q --rebase -X theirs origin "$br" 2>/dev/null || git rebase --abort 2>/dev/null
  sleep 3
done
echo "push 실패 (다음 회차에 재시도)"
exit 0
