"""Opt-in extracted-image inputs, shared by the three installed contract tests.

MX_ROOTFS_BASE=<extracted> requires all four <device>/fs roots. Alternatively
MX_MENU_ROOT=<fs> plus MX_MENU_DEVICE=<device> selects one explicit model.
Generic final os-release fields cannot identify a board; never guess from an
initramfs DTS, package presence, or a directory name.
"""
import os
from pathlib import Path

DEVICES = ('mx4200v1', 'mx4200v2', 'mx4300', 'homewrk')


def roots():
    base = os.environ.get('MX_ROOTFS_BASE')
    single = os.environ.get('MX_MENU_ROOT')
    assert not (base and single), 'set either MX_ROOTFS_BASE or MX_MENU_ROOT, not both'
    if base:
        selected = [(device, Path(base) / device / 'fs') for device in DEVICES]
    elif single:
        device = os.environ.get('MX_MENU_DEVICE')
        assert device in DEVICES, 'MX_MENU_DEVICE must explicitly name one of ' + ', '.join(DEVICES)
        selected = [(device, Path(single))]
    else:
        return []
    for device, root in selected:
        assert root.is_dir(), f'{device}: extracted root not found: {root}'
    return selected
