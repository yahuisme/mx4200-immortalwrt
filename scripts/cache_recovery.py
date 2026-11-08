#!/usr/bin/env python3
"""Disposable cache restore boundary; core build and cleanup errors stay fatal."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import gzip
import zlib
import sys
from contextlib import redirect_stdout

try:
    from . import cache_helper
except ImportError:
    import cache_helper

try:
    from . import cache as toolchain, bootstrap_cache as bootstrap
except ImportError:
    import cache as toolchain
    import bootstrap_cache as bootstrap


def clear(path):
    if path.is_symlink():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def clear_restored(kind, root):
    if kind == 'toolchain':
        for name in ('build_dir', 'staging_dir'):
            clear(root / name)
    elif kind == 'bootstrap':
        bootstrap.clear_host(root)
    else:
        clear(root)
        root.mkdir(parents=True, exist_ok=True)


def restore(kind, root, archive, expected, restored, outcome):
    exact = kind in ('toolchain', 'bootstrap')
    candidate = archive / (kind + '.tar.gz')
    # Cleanup is outside the archive rejection catch: permissions/programming
    # errors are not corruption and must not permit a contaminated build.
    clear_restored(kind, root)
    hit = False
    try:
        if outcome == 'success' and restored and (not exact or restored == expected) and candidate.is_file():
            if exact:
                keyfile = archive / 'key'
                if keyfile.is_symlink() or not keyfile.is_file() or candidate.is_symlink():
                    raise ValueError('missing/linked exact cache metadata')
                # Read only metadata here; raw restore retains its strict checks.
                keyfile.read_text()
                with redirect_stdout(sys.stderr):
                    if kind == 'toolchain':
                        toolchain.restore(root, archive, expected)
                        if (not (root / 'build_dir/host').is_dir()
                                or not (root / 'staging_dir/host').is_dir()
                                or not list(root.glob('build_dir/toolchain-*'))
                                or not list(root.glob('staging_dir/toolchain-*'))):
                            raise ValueError('incomplete toolchain artifact set')
                        binary = root / 'staging_dir/host/bin/ccache'
                        if (binary.is_symlink() or not binary.is_file() or not binary.stat().st_size
                                or not os.access(binary, os.X_OK)):
                            raise ValueError('missing nonempty executable host ccache')
                    else:
                        bootstrap.restore(root, archive, expected)
            else:
                subprocess.run(['tar', '--gzip', '-xf', str(candidate), '-C', str(root)],
                               check=True)
            hit = True
    except (ValueError, EOFError, tarfile.TarError, gzip.BadGzipFile, zlib.error,
            subprocess.CalledProcessError) as exc:
        print(f'::warning::Cache restore rejected; cold {kind}: {exc}', file=sys.stderr)
    if not hit:
        clear_restored(kind, root)
        archive.mkdir(parents=True, exist_ok=True)
        # Archive directories are Docker bind mounts: remove their contents,
        # never the mount point itself. Cleanup failures remain fatal.
        for path in archive.iterdir():
            if path.is_symlink() or path.is_file():
                path.unlink()
            else:
                clear(path)
    print('hit=' + str(hit).lower())
    print('matched-key=' + (restored if hit else ''))
    print('poisoned=' + str(exact and not hit and bool(restored or outcome != 'success')).lower())


def invalidate(prefix, key, poisoned):
    """Permit repair only after exact current-ref eviction and full readback.

    Never use gh's key-based deletion, which can remove other refs. Default-
    branch fallback entries are deliberately retained on non-default branches.
    """
    ok = not poisoned
    if poisoned:
        try:
            if prefix not in ('tc-v1-mx4200-arm64-', 'tb-v1-mx4200-arm64-'):
                raise ValueError('only exact cache tiers may be invalidated')
            ref = cache_helper.validate(prefix, key)
            before = cache_helper.inv()
            bad = [e for e in before if e['key'] == key and e['ref'] == ref]
            protected = {e['id'] for e in before if e not in bad}
            for entry in bad:
                subprocess.run(['gh', 'cache', 'delete', str(entry['id'])],
                               check=True, stdout=sys.stderr)
            after = cache_helper.inv()
            if (any(e['key'] == key and e['ref'] == ref for e in after)
                    or not protected <= {e['id'] for e in after}):
                raise ValueError('exact eviction/protected inventory readback failed')
            ok = True
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
            with redirect_stdout(sys.stderr):
                cache_helper.warn(f'exact repair disabled; cold build continues: {exc}')
    print('save=' + str(ok).lower())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='mode', required=True)
    unpack = commands.add_parser('restore')
    unpack.add_argument('kind', choices=['ccache', 'dl', 'toolchain', 'bootstrap'])
    unpack.add_argument('root', type=Path)
    unpack.add_argument('archive', type=Path)
    unpack.add_argument('expected')
    unpack.add_argument('--restored', default='')
    unpack.add_argument('--outcome', default='success')
    evict = commands.add_parser('invalidate')
    evict.add_argument('prefix')
    evict.add_argument('key')
    evict.add_argument('--poisoned', choices=['true', 'false'], required=True)
    args = parser.parse_args()
    if args.mode == 'restore':
        restore(args.kind, args.root, args.archive, args.expected, args.restored, args.outcome)
    else:
        invalidate(args.prefix, args.key, args.poisoned == 'true')
