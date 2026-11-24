#!/usr/bin/env python3
"""Select older MX4200/MX4300 Releases from one complete API inventory."""
from datetime import datetime
import json
import re
import sys

DATE = r'(?P<date>[0-9]{2}\.[0-9]{2}\.[0-9]{2})'
TIME = r'(?P<time>[0-9]{2}\.[0-9]{2}\.[0-9]{2})'
VERSION = r'[0-9]+\.[0-9]+\.[0-9]+'
REV = r'r[1-9][0-9]*'
PATTERNS = (
    re.compile(rf'(?P<series>MX4200|MX4300(?:-HomeWRK)?)'
               rf'-ImmortalWrt-(?:{VERSION}-)?{REV}-{DATE}_{TIME}'),
    re.compile(rf'(?P<series>MX4200)_ImmortalWrt_(?:v?{VERSION}_)?{DATE}-{TIME}(?:_{REV})?'),
    re.compile(rf'(?P<series>MX4200)_ImmortalWrt_v?{VERSION}_{REV}_{DATE}-{TIME}'),
)


def production_tag(tag):
    for pattern in PATTERNS:
        match = pattern.fullmatch(tag)
        if match:
            built = match['date'] + '_' + match['time']
            try:
                datetime.strptime(built, '%y.%m.%d_%H.%M.%S')
            except ValueError:
                return None
            return match['series'].removesuffix('-HomeWRK'), built
    return None


def published_at(row):
    value = row.get('published_at')
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z', value):
        raise ValueError('Missing or invalid publication timestamp: ' + row['tag_name'])
    return datetime.fromisoformat(value)


def select(pages, mx4200, mx4300):
    if not isinstance(pages, list) or not pages or any(not isinstance(page, list) for page in pages):
        raise ValueError('Invalid Release inventory pages')
    # Match per_page=100 in the workflow. A premature short or empty page
    # can mean the inventory moved while GitHub was paginating it.
    if any(len(page) != 100 for page in pages[:-1]) or not 1 <= len(pages[-1]) <= 100:
        raise ValueError('Inconsistent Release inventory page sizes')
    ids, inventory = set(), {}
    for page in pages:
        for row in page:
            if (not isinstance(row, dict) or type(row.get('id')) is not int or row['id'] <= 0
                    or not isinstance(row.get('tag_name'), str) or not row['tag_name']
                    or type(row.get('draft')) is not bool or type(row.get('prerelease')) is not bool):
                raise ValueError('Invalid Release inventory entry')
            tag = row['tag_name']
            if row['id'] in ids or tag in inventory:
                raise ValueError('Duplicate Release ID or tag across pages')
            ids.add(row['id'])
            inventory[tag] = row

    current = {}
    for series, tag in (('MX4200', mx4200), ('MX4300', mx4300)):
        row, parsed = inventory.get(tag), production_tag(tag)
        if row is None or row['draft'] or row['prerelease'] or parsed is None or parsed[0] != series:
            raise ValueError('Current publication missing from inventory: ' + tag)
        current[series] = (published_at(row), parsed[1])

    old = []
    for tag, row in inventory.items():
        parsed = production_tag(tag)
        if parsed is None or row['draft'] or row['prerelease']:
            continue
        series, built = parsed
        latest_publication, latest_build = current[series]
        # A newer build may already have published before this one. Equal
        # timestamps also cannot establish a strictly older Release.
        if published_at(row) < latest_publication and built < latest_build:
            old.append(tag)
    return old


if __name__ == '__main__':
    try:
        old_tags = select(json.load(sys.stdin), *sys.argv[1:])
    except ValueError as error:
        sys.exit(str(error))
    print('\n'.join(old_tags))
