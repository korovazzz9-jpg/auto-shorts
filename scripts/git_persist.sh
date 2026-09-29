#!/usr/bin/env bash
# Коммитит файлы состояния обратно в master и пушит с повтором.
#
#   bash scripts/git_persist.sh "<сообщение коммита>" file1 file2 ...
#
# Зачем (2026-09-29, аудит): шаги «Persist …» делали `git pull --rebase` и сразу `git push`
# без повтора. В master пишут несколько потоков (daily-es, watchdog-es, prepare-batch,
# weekly-report, discover-niche, longform, track-baby), и если чужой push успевал между нашими
# pull и push, шаг падал, а состояние (очередь, recovery) терялось вместе с раннером.
# Повторять надо свежим pull+push, а не `gh run rerun` (он берёт устаревший SHA, см. CLAUDE.md).
# Конфликт содержимого повтор не лечит: после PERSIST_ATTEMPTS попыток шаг честно падает.
#
# Отсутствующие файлы пропускаются молча — как `[ -f x ] && git add x` в прежних шагах.
set -uo pipefail

msg="$1"
shift
branch="${PERSIST_BRANCH:-master}"
attempts="${PERSIST_ATTEMPTS:-4}"
pause="${PERSIST_SLEEP:-5}"

git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"

for f in "$@"; do
  if [ -e "$f" ]; then
    git add -- "$f"
  fi
done

if git diff --cached --quiet; then
  echo "no changes"
  exit 0
fi
git commit -q -m "$msg" || { echo "no changes"; exit 0; }

for i in $(seq 1 "$attempts"); do
  if git pull -q --rebase origin "$branch" && git push -q origin "HEAD:$branch"; then
    echo "persisted on attempt $i"
    exit 0
  fi
  git rebase --abort >/dev/null 2>&1 || true
  if [ "$i" -lt "$attempts" ]; then
    echo "push attempt $i failed, retrying"
    sleep $(( i * pause ))
  fi
done

echo "::error::state push failed after $attempts attempts"
exit 1
