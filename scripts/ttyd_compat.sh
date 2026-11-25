#!/bin/bash
set -euo pipefail

recipe="$1/feeds/packages/utils/ttyd"
patch_dir="$recipe/patches"
patch_name=110-run-libuv-loop.patch
source_patch="$(dirname "$0")/ttyd-patches/$patch_name"
makefile="$recipe/Makefile"

# This backport is for the reviewed 1.7.7 tarball. Stop on recipe drift
# rather than silently shipping a broken terminal or stacking an unknown fix.
if ! grep -Fxq 'PKG_VERSION:=1.7.7' "$makefile" ||
   ! grep -Fxq 'PKG_HASH:=039dd995229377caee919898b7bd54484accec3bba49c118e2d5cd6ec51e3650' "$makefile"; then
    echo 'ttyd: unreviewed source; check libwebsockets compatibility before building' >&2
    exit 1
fi
target="$patch_dir/$patch_name"
if [[ -L "$target" ]] || { [[ -e "$target" ]] && ! cmp -s "$source_patch" "$target"; }; then
    echo 'ttyd: conflicting compatibility patch in package feed' >&2
    exit 1
fi

# APK requires an integer revision. The backport upgrades r1 to r2; stop
# for review if upstream changes its release (retire this on proven absorption).
case "$(grep -E '^[[:space:]]*PKG_RELEASE[[:space:]]*[:+?]?=' "$makefile" || true)" in
    PKG_RELEASE:=1)
        [[ -e "$target" ]] || install -D -m 644 "$source_patch" "$target"
        sed -i 's/^PKG_RELEASE:=1$/PKG_RELEASE:=2/' "$makefile"
        exit 0 ;;
    PKG_RELEASE:=2)
        [[ -f "$target" ]] && exit 0 ;;
esac
echo 'ttyd: unreviewed package release; check upstream compatibility before building' >&2
exit 1
