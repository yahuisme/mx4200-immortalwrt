#!/usr/bin/env python3
"""Fingerprint toolchain inputs and stabilize fresh-checkout recipe timestamps."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

INPUTS = ('tools', 'toolchain', 'include', 'scripts',
          'target/linux/generic', 'target/linux/qualcommax', 'config',
          'rules.mk', 'Makefile', 'Config.in', '.config', 'feeds.conf.default')
EPOCH = 946684800


def cache_key(root, host):
    digest = hashlib.sha256(host.encode())
    for name in INPUTS:
        path = root / name
        if not path.exists():
            raise ValueError('Missing cache input: ' + name)
        if path.is_symlink():
            raise ValueError('Linked cache input: ' + name)
        for item in sorted(path.rglob('*')) if path.is_dir() else [path]:
            relative = item.relative_to(root)
            if relative.parent == Path('scripts/config') and (
                    item.suffix == '.o' or item.name in ('conf', 'mconf', 'nconf', 'qconf', 'gconf',
                                                       'mconf_check', 'qconf-moc.cc') or
                    item.name.endswith(('-conf-cfg', 'conf-cfg', 'conf-bin', 'conf-cflags', 'conf-libs'))):
                continue
            if item.is_symlink():
                raise ValueError('Linked cache input: ' + str(relative))
            elif item.is_file():
                content = item.read_bytes()
            else:
                continue
            digest.update(json.dumps([str(item.relative_to(root)), item.lstat().st_mode,
                                     hashlib.sha256(content).hexdigest()]).encode())
            # Only source inputs: never change build/staging completion stamps.
            # Changed content/mode gets a new exact cache key, not a warm fallback.
            os.utime(item, (EPOCH, EPOCH), follow_symlinks=False)
    return digest.hexdigest()


def main():
    root = Path(sys.argv[1]).resolve()
    host = json.dumps([str(root), os.uname().machine,
                       os.environ.get('ImageOS', ''), os.environ['ImageVersion'],
                       subprocess.check_output(['dpkg-query', '-W', '-f=${Package}=${Version}\n'], text=True)])
    key = cache_key(root, host)
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        output.write('key=' + key + '\n')
    print('Toolchain cache input: ' + key)


if __name__ == '__main__':
    main()
