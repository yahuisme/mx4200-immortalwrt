#!/bin/bash
# Build a pristine official HomeWRK RAM system; never use project customizations.
set -euo pipefail
source=${DK_OPENWRT:?}
ram=/bld/ramboot
name=immortalwrt-qualcommax-ipq807x-linksys_homewrk-initramfs-uImage.itb
[ ! -e "$ram" ] || { echo "RAM build directory already exists" >&2; exit 1; }
revision=$(git -C "$source" rev-parse --verify HEAD)
# Clone committed official objects, not the customized source worktree.
git clone --no-hardlinks --no-checkout "$source" "$ram"
git -C "$ram" checkout -B master "$revision"
git -C "$ram" remote set-url origin https://github.com/immortalwrt/immortalwrt.git
git -C "$ram" update-ref refs/remotes/origin/master "$revision"
git -C "$ram" config branch.master.remote origin
git -C "$ram" config branch.master.merge refs/heads/master
cd "$ram"
cp feeds.conf.default feeds.conf
# Match the main build's actual official feed commits without copying mutations.
while read -r kind feed url rest; do
    [[ "$kind" = src-git || "$kind" = src-git-full ]] || continue
    [[ "$feed" =~ ^[A-Za-z0-9_-]+$ && -e "$source/feeds/$feed/.git" ]]
    git clone --no-hardlinks --no-checkout "$source/feeds/$feed" "feeds/$feed"
    sha=$(git -C "$source/feeds/$feed" rev-parse --verify HEAD)
    git -C "feeds/$feed" checkout --detach "$sha"
    git -C "feeds/$feed" remote set-url origin "${url%%[;^]*}"
done < feeds.conf
./scripts/feeds update -i
./scripts/feeds install -a
ln -s /dlcache dl
python3 /cache-scripts/check_go.py "$ram" /usr/lib/go
# Native-resolve an independent canonical seed before adding host controls.
# The producer retains/binds that baseline and compares the complete final config.
python3 /cache-scripts/check_ramboot.py --configure "$ram" "$source" /build-record/ramboot.json
export FORCE_UNSAFE_CONFIGURE=1 CCACHE_MAXSIZE=3G CCACHE_NOHASHDIR=true CCACHE_COMPILERCHECK=content
make download -j8
python3 /cache-scripts/check_ramboot.py --baseline /build-record/ramboot-baseline.config "$ram" "$source" /build-record/ramboot.json
make -j"$(($(nproc) + 1))" || make -j1 V=s
# Native make may re-resolve .config; do not trust the pre-build subset/proof.
python3 /cache-scripts/check_ramboot.py --baseline /build-record/ramboot-baseline.config "$ram" "$source" /build-record/ramboot.json
python3 /cache-scripts/check_initramfs.py "$ram/bin/targets/qualcommax/ipq807x/$name" --source "$ram" --record /build-record/initramfs.json
python3 /cache-scripts/stage_ramboot.py "$ram/bin/targets/qualcommax/ipq807x" "$DK_BIN/targets/qualcommax/ipq807x"
