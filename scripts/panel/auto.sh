#!/usr/bin/env bash
# Automatic virtual review panel (owner 2026-11-26: "알아서 상시로 돌아가도록 해야지"; docs/PANEL.md).
#   panel-auto.sh          hourly check (timer, 09–22 KST): runs only when lab has a new non-data change
#                          since the last reviewed commit, that change is at least 30 min old (deployed),
#                          and the panel has not run today. So at most one run per day.
#   panel-auto.sh --now    run now, ignoring the once-a-day and new-change rules.
# Cost (owner 11-26 "사용량이 많이 넘어갔는데"): the first run on the default model read ~50M cached tokens in its
# review phase alone, so runs use Sonnet and skip lab changes that do not touch pages.
# A run uses a detached worktree from origin/lab, captures the lab site, runs the Sonnet-only
# workflow, checks and publishes panel results to lab, and sends the existing Telegram summary.
# Owner 2026-11-26: direct lab publication and runtime repair approved. Reviewers only read.
set -u
OPS="$HOME/Babdoduk-ops"
REPO="$HOME/workspaces/Babdoduk"
WT="$HOME/workspaces/Babdoduk-wt"
PY="$OPS/.venv/bin/python"
CLAUDE="$HOME/.local/bin/claude"
STATE="$OPS/.local/panel-auto"
CODE=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
TOKEN_FILE="$HOME/.config/babdoduk/credentials/claude-oauth-token"
mkdir -p "$STATE"
exec 9>"$STATE/run.lock"
flock -n 9 || { echo "panel already running"; exit 0; }
"$PY" "$CODE/scripts/panel/auto_state.py" --state-dir "$STATE" --check || exit 0
now=0; [ "${1:-}" = "--now" ] && now=1
today=$(TZ=Asia/Seoul date +%F)

tg() {
  MSG="$1" "$PY" - <<'PY'
import os, sys
from pathlib import Path
sys.path.insert(0, os.path.expanduser("~/Babdoduk-ops/scripts"))
from ggongbab.instagram.telegram_review import credentials
from render_cardnews import send_text
token, chat = credentials(Path(os.path.expanduser("~/Babdoduk-ops/.local")))
if token and chat:
    print(send_text(os.environ["MSG"][:4000], token, chat))
PY
}
fail() { echo "FAIL: $1"; tg "⚠️ 가상 평가단 자동 실행이 안 됐어요.
$1

Claude에게 '평가단 다시 돌려줘'라고 말해 주세요."; exit 1; }

git -C "$REPO" fetch -q origin || { echo "fetch failed; next hour"; exit 0; }
lab=$(git -C "$REPO" rev-parse origin/lab)
last=$(cat "$STATE/reviewed" 2>/dev/null || true)
if [ "$now" = 0 ]; then
  [ "$(cat "$STATE/ran-on" 2>/dev/null)" = "$today" ] && { echo "already ran today"; exit 0; }
  if [ -n "$last" ] && git -C "$REPO" diff --quiet "$last" "$lab" -- '*.html' css/ js/ i18n/ shared/ data/content/; then
    echo "no new page change on lab since ${last:0:7}"; exit 0
  fi
  changed=$(git -C "$REPO" log -1 --format=%ct "$lab" -- '*.html' css/ js/ i18n/ shared/ data/content/)
  [ $(( $(date +%s) - changed )) -lt 1800 ] && { echo "lab change younger than 30 min; next hour"; exit 0; }
fi

# Preserve earlier worktrees; use a detached snapshot rather than creating a task branch.
name="panel-run-$(TZ=Asia/Seoul date +%Y%m%d-%H%M%S)"
dir="$WT/$name"
git -C "$REPO" worktree add -q --detach "$dir" origin/lab || fail "작업 폴더를 못 만들었어요."
echo "$dir" >> "$STATE/worktrees"
cap="$dir/.local/panel/$name"
cd "$dir"

"$PY" "$CODE/scripts/panel/auto_state.py" --state-dir "$STATE" --clear > /dev/null
echo "== capture $(date)"
"$PY" scripts/panel/capture.py --out "$cap" > "$STATE/capture.log" 2>&1 || {
  echo "capture failed; next hour"; tail -3 "$STATE/capture.log"; exit 0; }

echo "== panel $(date)"
[ -s "$TOKEN_FILE" ] && export CLAUDE_CODE_OAUTH_TOKEN="$(cat "$TOKEN_FILE")"
start=$(date +%s)
prompt="밥도둑 가상 평가단 자동 실행입니다. Workflow 도구로 워크플로를 실행하세요: scriptPath=$CODE/scripts/panel/workflow.js, args={\"repo\": \"$dir\", \"capture\": \"$cap\"}. 끝날 때까지 기다린 뒤, 반환값을 고치지 말고 JSON 그대로 Write 도구로 $cap/result.json 에 저장하세요. 다른 파일은 만들거나 고치지 말고, 끝나면 DONE이라고만 답하세요."
timeout 3h "$CLAUDE" -p "$prompt" --model sonnet --allowedTools Workflow Write Read Glob Grep --output-format json \
  > "$STATE/claude.json" 2> "$STATE/claude.err"
if [ ! -s "$cap/result.json" ]; then
  "$PY" "$CODE/scripts/panel/auto_state.py" --result "$STATE/claude.json" --state-dir "$STATE" > /dev/null
  if [ "$?" = 75 ]; then
    retry=$("$PY" "$CODE/scripts/panel/auto_state.py" --state-dir "$STATE" --retry-calendar)
    systemd-run --user --collect --unit="babdoduk-panel-retry-$(date +%s)" --on-calendar="$retry" \
      /usr/bin/bash "$CODE/scripts/panel/auto.sh" --now || fail "사용량 한도 뒤 재시도 예약에 실패했어요."
    echo "usage limit reached; retry scheduled, not marked as completed"
    exit 0
  fi
  fail "평가가 결과를 남기지 않았어요. 운영 기록을 확인해 주세요."
fi
run=$(find "$HOME/.claude/projects" -path '*/subagents/workflows/wf_*/journal.jsonl' -newermt "@$start" -printf '%T@ %h\n' 2>/dev/null | sort -n | tail -1 | cut -d' ' -f2-)

echo "== publish $(date)"
"$PY" scripts/panel/publish.py --result "$cap/result.json" --capture "$cap" || fail "결과 정리(publish)가 안 됐어요."
[ -n "$run" ] && "$PY" scripts/panel/live.py export --run "$run"
git add -- data/panel/latest.json data/panel/timeline.json data/panel/shots
git -c user.name=joshualikaist commit -q -m "panel: automatic review of lab ${lab:0:7} ($today)

Agent: Claude" || fail "결과를 저장(commit)하지 못했어요."

echo "== quick checks $(date)"
if ! "$PY" scripts/check_all.py --quick > "$STATE/check.log" 2>&1; then
  fail "빠른 검사에 실패했어요. 결과를 실험 사이트에 올리지 않았어요."
fi
git fetch -q origin || fail "실험 브랜치 확인에 실패했어요."
# Only generated-data movement may be integrated unattended. Source movement needs a fresh review.
if ! git merge-base --is-ancestor origin/lab HEAD; then
  others=$(git log --format='%an' HEAD..origin/lab | grep -v '^babdoduk-content-bot$' || true)
  [ -n "$others" ] && fail "평가 중 실험 사이트 코드가 바뀌었어요. 결과 게시를 보류했어요."
  paths=$(git diff --name-only "$lab" origin/lab | grep -v '^data/' || true)
  [ -n "$paths" ] && fail "평가 중 코드가 바뀌었어요. 결과 게시를 보류했어요."
  git merge -q --no-edit origin/lab || fail "새 데이터를 합치지 못했어요."
fi
git push -q git@github-motar:joshualikaist/Babdoduk.git HEAD:lab || fail "평가 결과 업로드에 실패했어요."
echo "$lab" > "$STATE/reviewed"
echo "$today" > "$STATE/ran-on"
check="빠른 검사 통과 · 실험 사이트에 결과를 올렸어요"
msg=$("$PY" - "$dir/data/panel/latest.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
threads = {t["id"]: t for t in d["threads"]}
lines = [f"{i}. {threads[g]['title']} (심각도 {threads[g]['severity']})" for i, g in enumerate(d["top"][:5], 1) if g in threads]
overall = d.get("overall", "")
print((overall[:350] + "…") if len(overall) > 350 else overall)
print("\n가장 중요한 것:\n" + "\n".join(lines))
PY
)
tg "🧐 가상 평가단이 실험 사이트(${lab:0:7})를 봤어요.

$msg

$check
https://babdoduk-lab.vercel.app/panel.html"
echo "done: $name"
