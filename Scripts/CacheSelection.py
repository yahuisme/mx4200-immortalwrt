#!/usr/bin/env python3
"""Read-only freshness selection for the existing split/combined cache formats."""
import json
import os
import subprocess

# actions/cache identities observed for these exact workflow path lists.
VERSIONS = {
    'downloads': 'c969e45455a7049c743a299503807fb9f93797e7764ed338cfe8f4a2f3a50448',
    'ccache': '821656cf7f9e3fb4b915177dcd4d70054452790bc3fbfd7472a16d48d767aa6c',
    'legacy': '13022b4af3811274a225a1685c0a626eaa514c5dd38505291157e3798c8a4685',
}


def select(entries, ref, platform):
    latest = {}
    for tier, version in VERSIONS.items():
        prefix = ('mx4200-ccache-' if tier == 'ccache' else 'mx4200-build-') + platform + '-'
        matches = [e for e in entries if e['ref'] == ref and e['version'] == version
                   and e['key'].startswith(prefix) and int(e['size_in_bytes']) > 0]
        latest[tier] = max(matches, key=lambda e: (e['created_at'], e['id']), default=None)
    result = {tier + '-key': entry['key'] if entry else '' for tier, entry in latest.items()}
    for tier in ('downloads', 'ccache'):
        split, legacy = latest[tier], latest['legacy']
        use_legacy = bool(legacy and (not split or legacy['created_at'] > split['created_at']))
        result['legacy-' + tier] = str(use_legacy).lower()
    result['restore-legacy'] = str(any(result['legacy-' + t] == 'true' for t in ('downloads', 'ccache'))).lower()
    return result


def main():
    raw = subprocess.check_output(['gh', 'api', '--paginate', '--slurp',
        'repos/' + os.environ['GITHUB_REPOSITORY'] + '/actions/caches?per_page=100'], text=True)
    entries = [entry for page in json.loads(raw) for entry in page['actions_caches']]
    result = select(entries, os.environ['GITHUB_REF'], os.environ['CACHE_PLATFORM'])
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        for key, value in result.items():
            output.write(key + '=' + value + '\n')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
