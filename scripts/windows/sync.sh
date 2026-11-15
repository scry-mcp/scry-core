#!/usr/bin/env bash
# Runs on the Windows host, in the run root: brings the bare mirrors and the clones to the bundles
# copied beside them.
set -u
W=$(cd "$(dirname "$0")" && pwd)
failed=0
for r in scry-core scry-mame scry-dosbox-x; do
  git -C "$W/bare/$r.git" fetch -q "$W/$r.bundle" "+refs/heads/main:refs/heads/main" "+refs/tags/*:refs/tags/*" \
    || { echo "$r fetch-bundle rc=$?"; failed=1; continue; }
  git -C "$W/$r" fetch -q origin --tags && git -C "$W/$r" checkout -q main && git -C "$W/$r" reset -q --hard origin/main
  rc=$?
  [ "$rc" -eq 0 ] || failed=1
  echo "$r rc=$rc $(git -C "$W/$r" log --oneline -1) dirty=$(git -C "$W/$r" status --porcelain | wc -l)"
done
exit "$failed"
