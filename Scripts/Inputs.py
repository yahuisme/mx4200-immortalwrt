#!/usr/bin/env python3
"""Identify consumed firmware inputs, excluding repository documentation and CI."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = {
    'aurora': ('https://github.com/eamonxg/luci-theme-aurora.git', ('.',)),
    'aurora-config': ('https://github.com/eamonxg/luci-app-aurora-config.git', ('.',)),
    'yahuisme/packages': ('https://github.com/yahuisme/packages.git', ('luci-app-homeproxy', 'sing-box')),
}


def fingerprint(root, paths):
    digest = hashlib.sha256()
    for name in sorted(paths):
        p = root / name
        if p.is_symlink():
            content = str(p.readlink()).encode()
        else:
            content = p.read_bytes()
        digest.update(json.dumps([name, p.lstat().st_mode & 0o177777, hashlib.sha256(content).hexdigest()]).encode())
    return digest.hexdigest()


def local_fingerprint(root=ROOT):
    paths = [str(p.relative_to(root)) for directory in ('Config', 'files', 'package', 'patches', 'Scripts')
             for p in (root / directory).rglob('*')
             if (p.is_file() or p.is_symlink()) and '__pycache__' not in p.parts]
    # These workflow values are firmware inputs; scheduling/cache/CI are not.
    settings = [line.strip() for line in (root / '.github/workflows/MX4200.yml').read_text().splitlines()
                if line.strip().startswith(('WRT_THEME:', 'WRT_IP:', 'WRT_SSID:', 'WRT_WORD:'))]
    return hashlib.sha256(json.dumps([fingerprint(root, paths), settings]).encode()).hexdigest()


def package_fingerprint(root, directories):
    files = subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z', '--', *directories]).decode().split('\0')
    # Standalone package repos carry README/CI that the firmware never consumes.
    files = [p for p in files if p and not p.startswith(('.github/', 'README', 'LICENSE', '.gitignore'))]
    return fingerprint(root, files)


def record(lock, trees):
    lock['local_firmware_sha256'] = local_fingerprint()
    lock['custom_package_sha256'] = {key: package_fingerprint(trees[key], dirs) for key, (_, dirs) in PACKAGES.items()}
    lock['firmware_inputs_sha256'] = hashlib.sha256(json.dumps(
        [lock['local_firmware_sha256'], lock['custom_package_sha256']], sort_keys=True).encode()).hexdigest()


def probe(output):
    from Prepare import resolve, OFFICIAL, DONOR, run
    lock = resolve()
    for key, url in [('official', OFFICIAL), ('donor', DONOR)]:
        ref = 'refs/tags/' + lock[key + '_tag']
        refs = dict(line.split()[::-1] for line in run('git', 'ls-remote', url, ref, ref + '^{}').splitlines())
        lock[key + '_commit'] = refs.get(ref + '^{}', refs.get(ref))
        if not lock[key + '_commit']:
            raise ValueError('Missing release ref: ' + ref)
    with tempfile.TemporaryDirectory() as d:
        trees = {}
        lock['custom_packages'] = {}
        for i, (key, (url, _)) in enumerate(PACKAGES.items()):
            tree = Path(d) / str(i)
            command = ['git', 'clone', '--depth=1']
            if key == 'yahuisme/packages':
                command += ['--branch', 'main']
            run(*command, url, str(tree))
            trees[key] = tree
            lock['custom_packages'][key] = run('git', '-C', str(tree), 'rev-parse', 'HEAD')
        record(lock, trees)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(lock, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe', type=Path, required=True)
    probe(parser.parse_args().probe)
