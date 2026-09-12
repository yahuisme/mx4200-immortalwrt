#!/usr/bin/env python3
"""Fingerprint restored/final download contents without modifying source archives."""
import hashlib
import json
import os
from pathlib import Path
import sys


def main():
    root = Path(sys.argv[1])
    digest = hashlib.sha256()
    count = 0
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            content = hashlib.sha256(os.readlink(path).encode()).hexdigest()
        elif path.is_file():
            with path.open('rb') as stream:
                content = hashlib.file_digest(stream, 'sha256').hexdigest()
        else:
            continue
        digest.update(json.dumps([str(path.relative_to(root)), path.lstat().st_mode,
                                  content]).encode())
        count += 1
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        output.write(f'digest={digest.hexdigest()}\nfiles={count}\n')
    print(f'Download cache: {count} files, sha256={digest.hexdigest()}')


if __name__ == '__main__':
    main()
