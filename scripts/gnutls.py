#!/usr/bin/env python3
"""Remove only GnuTLS's redundant autoreconf fixup after checking native hooks."""
from pathlib import Path
import subprocess
import sys


def optimize(root):
    root = Path(root).resolve()
    recipe = root / 'feeds/packages/libs/gnutls/Makefile'
    text = recipe.read_text()
    lines = [line for line in text.splitlines() if line.startswith('PKG_FIXUP:=')]
    if len(lines) != 1 or lines[0] not in (
            'PKG_FIXUP:=autoreconf gettext-version', 'PKG_FIXUP:=gettext-version'):
        raise ValueError('unexpected GnuTLS PKG_FIXUP; review upstream recipe')

    def hooks(fixup):
        # Load the real include without invoking configure or host tools.
        result = subprocess.run(
            ['make', '--no-print-directory', '-s', '-f', '-', 'print-hooks'],
            cwd=root, input=fixup + '\ninclude include/autotools.mk\n'
            '.PHONY: print-hooks\nprint-hooks:\n'
            '\t@echo $(Hooks/Configure/Pre)\n',
            text=True, capture_output=True, check=True)
        return result.stdout.strip().split()

    before = hooks(lines[0])
    if before == ['gettext_version_target', 'autoreconf_target']:
        return  # Already applied, or upstream fixed hook deduplication.
    after = 'PKG_FIXUP:=gettext-version'
    if (before != ['gettext_version_target', 'autoreconf_target', 'autoreconf_target']
            or hooks(after) != ['gettext_version_target', 'autoreconf_target']):
        raise ValueError('unexpected GnuTLS configure hooks; refusing to remove autoreconf')
    recipe.write_text(text.replace(lines[0] + '\n', after + '\n', 1))
    print('GnuTLS: removed duplicate autoreconf; gettext and one autoreconf retained.')


if __name__ == '__main__':
    optimize(sys.argv[1])
