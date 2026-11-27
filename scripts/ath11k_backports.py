#!/usr/bin/env python3
"""Install the reviewed ath11k patches after the native mac80211 chain."""
from hashlib import sha256
from pathlib import Path
import re
import sys

PATCH_DIR = Path(__file__).with_name('ath11k-patches')
PAYLOAD = ('990-rxdma-page-frag-24254.patch', '991-mesh-amsdu-26866.patch',
           '992-unique-sta-addr-25520.patch')
SOURCE_HASH = '6ec76a4cb0988b5382b2fc5053610a56ada90b8ef6a5a4f2807cd433badb9454'
CHAIN_HASH = 'e4abdec9a759a297021a8d17a9f7b46e92081481d9d263482c757db4b3cf4fc3'


def assignments(text, key):
    # Count qualified/reassigned fields as well, even though only the exact
    # reviewed assignments below are allowed.
    return re.findall(rf'^[ \t]*(?:(?:override|export|unexport|private)[ \t]+)*'
                      rf'{key}[ \t]*(?:[:+?!]?=|::=|:::=)[^\n]*', text, re.M)


def chain_hash(paths):
    digest = sha256()
    for path in sorted(paths):
        digest.update(path.name.encode() + b'\0' + sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def prepare(root):
    recipe = Path(root) / 'package/kernel/mac80211'
    makefile = recipe / 'Makefile'
    text = makefile.read_text()
    for key, value in (('PKG_SOURCE_VERSION', '7.2'), ('PKG_HASH', SOURCE_HASH)):
        if assignments(text, key) != [f'{key}:={value}']:
            raise ValueError('unreviewed ath11k source; review all backports')
    release = assignments(text, 'PKG_RELEASE')
    directory = recipe / 'patches/ath11k'
    upstream = []
    installed = set()
    payload = {name: (PATCH_DIR / name).read_bytes() for name in PAYLOAD}
    if not all(payload.values()):
        raise ValueError('empty ath11k backport')
    for path in directory.iterdir():
        if path.is_symlink() or not path.is_file() or path.suffix != '.patch':
            raise ValueError('unreviewed ath11k patch directory entry: ' + path.name)
        if path.name in payload:
            if path.read_bytes() != payload[path.name]:
                raise ValueError('conflicting ath11k patch: ' + path.name)
            installed.add(path.name)
        else:
            upstream.append(path)
    if chain_hash(upstream) != CHAIN_HASH:
        raise ValueError('unreviewed ath11k patch chain; check upstream absorption and replay')
    if release == ['PKG_RELEASE:=17'] and installed == set(PAYLOAD):
        return
    if release != ['PKG_RELEASE:=15'] or installed:
        raise ValueError('unreviewed ath11k package release or partial backport')
    for name, content in payload.items():
        with (directory / name).open('xb') as dest:
            dest.write(content)
    makefile.write_text(re.sub(r'^PKG_RELEASE:=15$', 'PKG_RELEASE:=17', text, count=1, flags=re.M))


if __name__ == '__main__':
    try:
        prepare(sys.argv[1])
    except (IndexError, OSError, ValueError) as error:
        sys.exit(f'ERROR: ath11k backports: {error}')
