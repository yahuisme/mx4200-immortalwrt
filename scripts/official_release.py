#!/usr/bin/env python3
"""Resolve the build-wide latest official stable release and HomeWRK metadata."""
import argparse
import json
from pathlib import Path

try:
    from .official_initramfs import resolve
except ImportError:
    from official_initramfs import resolve


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('record', type=Path)
    args = parser.parse_args()
    record = resolve()
    args.record.parent.mkdir(parents=True, exist_ok=True)
    args.record.write_text(json.dumps(record, indent=2) + '\n')
    print('v' + record['version'])


if __name__ == '__main__':
    main()
