#!/bin/bash
set -euo pipefail

recipe="$1/feeds/packages/utils/ttyd"
patch_dir="$recipe/patches"
patch_name=110-run-libuv-loop.patch
source_patch="$(dirname "$0")/ttyd-patches/$patch_name"

# This backport is for the reviewed 1.7.7 tarball. Stop on recipe drift
# rather than silently shipping a broken terminal or stacking an unknown fix.
if ! grep -Fxq 'PKG_VERSION:=1.7.7' "$recipe/Makefile" ||
   ! grep -Fxq 'PKG_HASH:=039dd995229377caee919898b7bd54484accec3bba49c118e2d5cd6ec51e3650' "$recipe/Makefile"; then
    echo 'ttyd: unreviewed source; check libwebsockets compatibility before building' >&2
    exit 1
fi
if [[ -e "$patch_dir/$patch_name" || -L "$patch_dir/$patch_name" ]]; then
    if [[ ! -L "$patch_dir/$patch_name" ]] && cmp -s "$source_patch" "$patch_dir/$patch_name"; then
        exit 0
    fi
    echo 'ttyd: conflicting compatibility patch in package feed' >&2
    exit 1
fi
install -D -m 644 "$source_patch" "$patch_dir/$patch_name"
