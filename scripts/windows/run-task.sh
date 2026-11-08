#!/usr/bin/env bash
# Run one step on the Windows host as the interactive task scry-<step>, confirm none is left, and
# fetch its logs into a directory of this run, which it names.
set -uo pipefail
: "${SCRY_WIN_SSH:?set SCRY_WIN_SSH to the Windows host, user@host}"
: "${SCRY_WIN_ROOT:?set SCRY_WIN_ROOT to the Windows run root, C:/.../scry-win}"
step=${1:?usage: run-task.sh <step> [seconds]}
seconds=${2:-7200}
out=$(mktemp -d)
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
echo "fetch_rc=$? files=$(find "$out/$step" -type f 2>/dev/null | wc -l) out=$out"
cat "$out/$step.out"
[ "$launch_rc" -eq 0 ] && [ "$left" = "0" ]
