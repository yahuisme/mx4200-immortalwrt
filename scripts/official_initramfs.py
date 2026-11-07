#!/usr/bin/env python3
"""Acquire the pinned official HomeWRK RAM-boot image (not a local build)."""
import argparse
import hashlib
import http.client
import json
import os
import re
import sys
import tempfile
import urllib.request
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / "user/default/official-initramfs.json"
VERSION = "25.12.2"
NAME = f"immortalwrt-{VERSION}-qualcommax-ipq807x-linksys_homewrk-initramfs-uImage.itb"
URL = f"https://downloads.immortalwrt.org/releases/{VERSION}/targets/qualcommax/ipq807x/{NAME}"


def _validate_config(config):
    expected = {"group": "mx4300-homewrk", "version": VERSION, "url": URL, "name": NAME}
    if not isinstance(config, dict) or set(config) != set(expected) | {"size", "sha256"}:
        raise ValueError("unexpected official initramfs configuration fields")
    if any(config[key] != value for key, value in expected.items()):
        raise ValueError("official initramfs identity must match the reviewed pin")
    if type(config["size"]) is not int or config["size"] <= 0:
        raise ValueError("official initramfs size must be a positive integer")
    if not isinstance(config["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", config["sha256"]):
        raise ValueError("official initramfs sha256 must be 64 lowercase hex digits")
    return dict(config)


def load_config(path=None):
    """Return the validated repository-owned official-image pin."""
    path = Path(path if path is not None else CONFIG)
    if path.is_symlink() or not path.is_file() or not path.stat().st_size:
        raise ValueError("missing, empty or symlink official initramfs configuration")
    return _validate_config(json.loads(path.read_text()))


def verify(path, config=None):
    """Verify a nonempty regular image's exact size and streamed SHA-256.

    Return the validated pin for provenance consumers. The local filename need
    not match the pin, allowing verification of private download temporaries.
    """
    config = load_config() if config is None else _validate_config(config)
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not path.stat().st_size:
        raise ValueError("missing, empty or symlink official initramfs image")
    if path.stat().st_size != config["size"]:
        raise ValueError("official initramfs size mismatch")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(128 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != config["sha256"]:
        raise ValueError("official initramfs SHA-256 mismatch")
    return config


def download(destination, record=None):
    """Stream to a private same-filesystem temporary; publish only verified bytes."""
    config = load_config()
    destination = Path(destination)
    if destination.is_symlink():
        raise ValueError("official initramfs destination must not be a symlink")
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / config["name"]
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise ValueError("official initramfs target must be a regular file")
    if record is not None:
        record = Path(record)
        if record.resolve() == target.resolve() or record.resolve() == CONFIG.resolve():
            raise ValueError("official initramfs record must not overwrite the image or configuration")
        if record.is_symlink() or (record.exists() and not record.is_file()):
            raise ValueError("official initramfs record must be a regular file")
    partial = None
    record_partial = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination, prefix=".official-initramfs-", delete=False) as stream:
            partial = Path(stream.name)
            received = 0
            with urllib.request.urlopen(config["url"], timeout=30) as response:
                while block := response.read(min(128 * 1024, config["size"] - received + 1)):
                    received += len(block)
                    if received > config["size"]:
                        raise ValueError("official initramfs exceeds pinned size")
                    stream.write(block)
            stream.flush()
            os.fsync(stream.fileno())
        verify(partial, config)
        if record is not None:
            record = Path(record)
            record.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", dir=record.parent, prefix=".official-record-", delete=False) as stream:
                record_partial = Path(stream.name)
                stream.write(json.dumps(config, indent=2) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        os.replace(partial, target)
        if record_partial is not None:
            assert record is not None
            os.replace(record_partial, record)
        return target
    finally:
        for path in (partial, record_partial):
            if path is not None:
                path.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", metavar="DEST_DIR", type=Path)
    parser.add_argument("--record", type=Path, help="write verified official-image provenance JSON")
    args = parser.parse_args(argv)
    try:
        download(args.destination, args.record)
    except (OSError, ValueError, http.client.HTTPException) as error:
        print(f"official initramfs: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
