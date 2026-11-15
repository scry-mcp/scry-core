#!/usr/bin/env bash
# Copy a repository's working tree, tracked and untracked, over its clone on the Windows host;
# a tracked file deleted here is deleted there too.
set -euo pipefail
: "${SCRY_WIN_SSH:?set SCRY_WIN_SSH to the Windows host, user@host}"
: "${SCRY_WIN_ROOT:?set SCRY_WIN_ROOT to the Windows run root, C:/.../scry-win}"
repo=${1:?usage: push-tree.sh <scry-core|scry-mame|scry-dosbox-x>}
here=$(cd "$(dirname "$0")" && pwd)
out=$(mktemp -d)
trap 'rm -rf "$out"' EXIT
cd "$here/../../../$repo"
{ git ls-files -z; git ls-files -z --others --exclude-standard; } | sort -zu \
  | while IFS= read -r -d '' file; do if [ -f "$file" ]; then printf '%s\0' "$file"; fi; done \
  | COPYFILE_DISABLE=1 tar --no-xattrs -c --null -T - -f "$out/$repo.tree.tar"
git ls-files -z --deleted > "$out/$repo.deleted"
scp -q "$out/$repo.tree.tar" "$SCRY_WIN_SSH:$SCRY_WIN_ROOT/$repo.tree.tar"
scp -q "$out/$repo.deleted" "$SCRY_WIN_SSH:$SCRY_WIN_ROOT/$repo.deleted"
"$here/msys.sh" <<REMOTE
cd "\$(cygpath -u '$SCRY_WIN_ROOT')/$repo" && git reset -q --hard && git clean -qfd \
  && find . -name '._*' -delete && tar -xf ../$repo.tree.tar \
  && xargs -0 -r rm -f -- < ../$repo.deleted \
  && echo "$repo tree in: \$(git status --porcelain | wc -l) changed"
REMOTE
