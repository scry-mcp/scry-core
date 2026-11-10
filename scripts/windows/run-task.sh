#!/usr/bin/env bash
# Run one step on the Windows host as the interactive task scry-<step>, confirm none is left, and
# fetch its logs into a directory of this run, which it names and its caller removes once read.
# The logs of a step that ended and was fetched are removed from the host; one that timed out or
# whose launch failed keeps them there, since its log came back cut or it may still be writing.
set -uo pipefail
: "${SCRY_WIN_SSH:?set SCRY_WIN_SSH to the Windows host, user@host}"
: "${SCRY_WIN_ROOT:?set SCRY_WIN_ROOT to the Windows run root, C:/.../scry-win}"
step=${1:?usage: run-task.sh <step> [seconds]}
# The step names files on the host, some of them removed below.
case "$step" in *[!A-Za-z0-9_-]*) echo "usage: a step is letters, digits, - and _; got $step" >&2; exit 2;; esac
seconds=${2:-7200}
# A template: with none, macOS's mktemp ignores TMPDIR.
out=$(mktemp -d "${TMPDIR:-/tmp}/scry-win-XXXXXX")
root=${SCRY_WIN_ROOT//\//\\}
ssh -o BatchMode=yes "$SCRY_WIN_SSH" \
  "powershell -NoProfile -File $root\\launch.ps1 -Step $step -Seconds $seconds" \
  | tr -d '\r' > "$out/$step.out"
launch_rc=${PIPESTATUS[0]}
echo "launch_rc=$launch_rc"
left=$(ssh -o BatchMode=yes "$SCRY_WIN_SSH" \
  '@(Get-ScheduledTask -TaskName "scry-*" -ErrorAction SilentlyContinue).Count' | tr -d '\r')
echo "tasks_left=$left"
scp -q -r "$SCRY_WIN_SSH:$SCRY_WIN_ROOT/logs/$step" "$out/"
fetch_rc=$?
echo "fetch_rc=$fetch_rc files=$(find "$out/$step" -type f 2>/dev/null | wc -l) out=$out"
if [ "$fetch_rc" -eq 0 ] && [ "$launch_rc" -eq 0 ] && [ "$(head -n 1 "$out/$step.out")" = DONE ]; then
  ssh -o BatchMode=yes "$SCRY_WIN_SSH" "powershell -NoProfile -Command Remove-Item -Recurse" \
    "-Force -ErrorAction SilentlyContinue $root\\logs\\$step, $root\\logs\\$step.log," \
    "$root\\logs\\$step.done"
  echo "host_logs_removed_rc=$?"
fi
cat "$out/$step.out"
[ "$launch_rc" -eq 0 ] && [ "$left" = "0" ]
