"""Pinned official HomeWRK initramfs acquisition, without target compilation."""
import hashlib
import importlib.util
import io
import json
from unittest.mock import patch
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/official_initramfs.py"


def helper():
    spec = importlib.util.spec_from_file_location("official_initramfs", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
NAME = "immortalwrt-25.12.2-qualcommax-ipq807x-linksys_homewrk-initramfs-uImage.itb"
URL = "https://downloads.immortalwrt.org/releases/25.12.2/targets/qualcommax/ipq807x/" + NAME
PIN = {"group": "mx4300-homewrk", "version": "25.12.2", "url": URL, "name": NAME, "size": 17190648,
       "sha256": "35d0ed3e46b090dbb433a973b743cc02fb1b3e609be85ecbbe1d401596d2c929"}


class ConfigTests(unittest.TestCase):
    def test_default_config_is_exact_official_pin(self):
        self.assertTrue(SCRIPT.is_file(), "official initramfs helper is missing")
        self.assertEqual(helper().load_config(), PIN)

    def test_rejects_invalid_config_and_symlink(self):
        module = helper()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pin.json"
            changes = [("version", "25.12.3"), ("url", URL + "?extra"),
                       ("name", "../" + NAME), ("group", "mx4200"),
                       ("size", 0), ("size", -1), ("size", True),
                       ("size", "17"), ("sha256", "A" * 64),
                       ("sha256", "f" * 63), ("sha256", None)]
            for key, value in changes:
                with self.subTest(key=key, value=value):
                    path.write_text(json.dumps(dict(PIN, **{key: value})))
                    with self.assertRaises(ValueError):
                        module.load_config(path)
            for config in ({}, [], dict(PIN, extra=True)):
                path.write_text(json.dumps(config))
                with self.assertRaises(ValueError):
                    module.load_config(path)
            path.write_text("")
            with self.assertRaises(ValueError):
                module.load_config(path)
            path.write_text(json.dumps(PIN))
            link = path.with_name("link.json")
            link.symlink_to(path)
            with self.assertRaises(ValueError):
                module.load_config(link)


class VerifyTests(unittest.TestCase):
    def test_copied_script_loads_its_own_pin_without_build_profile(self):
        data = b"private relocated fixture"
        config = dict(PIN, size=len(data), sha256=hashlib.sha256(data).hexdigest())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "scripts/official_initramfs.py"
            script.parent.mkdir()
            shutil.copyfile(SCRIPT, script)
            pin = root / "user/default/official-initramfs.json"
            pin.parent.mkdir(parents=True)
            pin.write_text(json.dumps(config))
            image = root / NAME
            image.write_bytes(data)
            result = subprocess.run([sys.executable, "-c",
                "import json,sys; sys.path.insert(0,sys.argv[1]); import official_initramfs as m; print(json.dumps(m.verify(sys.argv[2])))",
                str(script.parent), str(image)], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), config)

    def test_verifies_bytes_and_rejects_corruption_truncation_empty_symlink(self):
        module = helper()
        self.assertTrue(callable(getattr(module, "verify", None)), "verify API is missing")
        data = b"reviewed fixture FIT payload\0" * 10000
        config = dict(PIN, size=len(data), sha256=hashlib.sha256(data).hexdigest())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / NAME
            path.write_bytes(data)
            self.assertEqual(module.verify(path, config), config)
            for payload in (data[:-1], b"!" + data[1:], b"", data + b"extra"):
                with self.subTest(length=len(payload)):
                    path.write_bytes(payload)
                    with self.assertRaises(ValueError):
                        module.verify(path, config)
            path.write_bytes(data)
            link = path.with_name("link.itb")
            link.symlink_to(path)
            with self.assertRaises(ValueError):
                module.verify(link, config)
            with self.assertRaises(ValueError):
                module.verify(path.parent, config)
            with self.assertRaises(ValueError):
                module.verify(path.with_name("missing"), config)
            with self.assertRaises(ValueError):
                module.verify(path, dict(config, group="mx4200"))


class DownloadTests(unittest.TestCase):
    def test_record_preparation_failure_preserves_existing_image(self):
        module = helper()
        data = b"fixture bytes"
        config = dict(PIN, size=len(data), sha256=hashlib.sha256(data).hexdigest())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pin = root / "pin.json"
            pin.write_text(json.dumps(config))
            dest = root / "dest"
            dest.mkdir()
            target = dest / NAME
            target.write_bytes(b"old image")
            blocker = root / "not-directory"
            blocker.write_text("unchanged")
            with patch.object(module, "CONFIG", pin), patch("urllib.request.urlopen", return_value=io.BytesIO(data)), patch("sys.stderr", new_callable=io.StringIO):
                self.assertEqual(module.main([str(dest), "--record", str(blocker / "record.json")]), 1)
            self.assertEqual(target.read_bytes(), b"old image")
            self.assertEqual(list(dest.iterdir()), [target])
            self.assertEqual(blocker.read_text(), "unchanged")

    def test_symlink_target_and_record_alias_cannot_be_published(self):
        module = helper()
        data = b"fixture bytes"
        config = dict(PIN, size=len(data), sha256=hashlib.sha256(data).hexdigest())
        for kind in ("image-link", "record-alias", "record-link"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                pin = root / "pin.json"
                pin.write_text(json.dumps(config))
                target = root / NAME
                victim = root / "untouched"
                victim.write_bytes(b"untouched")
                record = root / "record.json"
                if kind == "image-link":
                    target.symlink_to(victim)
                else:
                    target.write_bytes(b"old image")
                    if kind == "record-alias":
                        record = target
                    else:
                        record.symlink_to(victim)
                with patch.object(module, "CONFIG", pin), patch("urllib.request.urlopen", return_value=io.BytesIO(data)) as request, patch("sys.stderr", new_callable=io.StringIO):
                    self.assertEqual(module.main([str(root), "--record", str(record)]), 1)
                    request.assert_not_called()
                self.assertEqual(victim.read_bytes(), b"untouched")
                if kind == "image-link":
                    self.assertTrue(target.is_symlink())
                else:
                    self.assertEqual(target.read_bytes(), b"old image")

    def test_oversized_response_is_stopped_and_preserves_existing_files(self):
        module = helper()
        data = b"expected bytes"
        config = dict(PIN, size=len(data), sha256=hashlib.sha256(data).hexdigest())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pin = root / "pin.json"
            pin.write_text(json.dumps(config))
            dest = root / "dest"
            dest.mkdir()
            target = dest / NAME
            target.write_bytes(b"previous image")
            record = root / "record.json"
            record.write_text("previous record")

            class Oversize(io.BytesIO):
                def read(self, size=None):
                    block = super().read(size)
                    if not block:
                        raise AssertionError("oversized download was not stopped early")
                    return block

            with patch.object(module, "CONFIG", pin), patch("urllib.request.urlopen", return_value=Oversize(data * 100)), patch("sys.stderr", new_callable=io.StringIO) as stderr:
                self.assertEqual(module.main([str(dest), "--record", str(record)]), 1)
                self.assertIn("exceeds pinned size", stderr.getvalue())
            self.assertEqual(target.read_bytes(), b"previous image")
            self.assertEqual(record.read_text(), "previous record")
            self.assertEqual(list(dest.iterdir()), [target])

    def test_failed_download_preserves_image_record_and_cleans_partial(self):
        module = helper()
        import http.client
        import urllib.error
        data = b"expected bytes"
        config = dict(PIN, size=len(data), sha256=hashlib.sha256(data).hexdigest())

        class Interrupted(io.BytesIO):
            def read(self, size=None):
                if self.tell():
                    raise http.client.IncompleteRead(b"partial")
                return super().read(3)

        failures = [b"wrong content!", data[:-1], b"", urllib.error.URLError("offline"), Interrupted(data)]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                pin = root / "pin.json"
                pin.write_text(json.dumps(config))
                dest = root / "dest"
                dest.mkdir()
                target = dest / NAME
                target.write_bytes(b"previous image")
                record = root / "record.json"
                record.write_text("previous record")
                network = patch("urllib.request.urlopen", side_effect=failure) if isinstance(failure, Exception) else patch("urllib.request.urlopen", return_value=io.BytesIO(failure) if isinstance(failure, bytes) else failure)
                with patch.object(module, "CONFIG", pin), network, patch("sys.stderr", new_callable=io.StringIO) as stderr:
                    self.assertEqual(module.main([str(dest), "--record", str(record)]), 1)
                    self.assertIn("official initramfs:", stderr.getvalue())
                self.assertEqual(target.read_bytes(), b"previous image")
                self.assertEqual(record.read_text(), "previous record")
                self.assertEqual(list(dest.iterdir()), [target])

    def test_cli_download_verifies_before_atomic_replace_and_records_pin(self):
        module = helper()
        self.assertTrue(callable(getattr(module, "main", None)), "download CLI is missing")
        data = b"private fixture, not firmware" * 20000
        config = dict(PIN, size=len(data), sha256=hashlib.sha256(data).hexdigest())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "pin.json"
            config_path.write_text(json.dumps(config))
            dest = root / "images"
            dest.mkdir()
            target = dest / NAME
            target.write_bytes(b"previous verified image")
            record = root / "evidence/official.json"

            class Response(io.BytesIO):
                def read(self, size=None):
                    assert size is not None
                    self_test.assertGreater(size, 0)
                    self_test.assertLessEqual(size, 128 * 1024)
                    self_test.assertEqual(target.read_bytes(), b"previous verified image")
                    self_test.assertFalse(record.exists())
                    return super().read(size)

            self_test = self
            with patch.object(module, "CONFIG", config_path), patch("urllib.request.urlopen", return_value=Response(data)) as request:
                self.assertEqual(module.main([str(dest), "--record", str(record)]), 0)
            self.assertEqual(target.read_bytes(), data)
            self.assertEqual(json.loads(record.read_text()), config)
            self.assertEqual(list(dest.iterdir()), [target])
            self.assertEqual(request.call_args.kwargs["timeout"], 30)


if __name__ == "__main__":
    unittest.main()
