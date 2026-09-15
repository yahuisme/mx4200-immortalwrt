"""Package-scoped fixup checks; optional real upstream include coverage."""
import importlib.util
import os
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('gnutls', ROOT / 'Scripts/GnuTLS.py')
assert spec is not None and spec.loader is not None
gnutls = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gnutls)

# Minimal hook fixture, not a source compilation.
HOOKS = '''ifneq ($(filter gettext-version,$(PKG_FIXUP)),)
Hooks/Configure/Pre += gettext_version_target autoreconf_target
endif
ifneq ($(filter autoreconf,$(PKG_FIXUP)),)
ifeq ($(filter autoreconf,$(Hooks/Configure/Pre)),)
Hooks/Configure/Pre += autoreconf_target
endif
endif
'''


class GnuTLSTests(unittest.TestCase):
    def tree(self, directory, hooks=HOOKS, fixup='autoreconf gettext-version'):
        root = Path(directory)
        recipe = root / 'feeds/packages/libs/gnutls/Makefile'
        recipe.parent.mkdir(parents=True)
        recipe.write_text('PKG_NAME:=gnutls\nPKG_FIXUP:=' + fixup + '\nPKG_INSTALL:=1\n')
        (root / 'include').mkdir()
        (root / 'include/autotools.mk').write_text(hooks)
        return root, recipe

    def test_duplicate_and_idempotency_preserve_other_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            root, recipe = self.tree(d)
            original = recipe.read_bytes()
            include = (root / 'include/autotools.mk').read_bytes()
            gnutls.optimize(root)
            self.assertEqual(recipe.read_bytes(), original.replace(b'autoreconf gettext-version', b'gettext-version'))
            changed = recipe.stat().st_mtime_ns
            gnutls.optimize(root)
            self.assertEqual(recipe.stat().st_mtime_ns, changed)
            self.assertEqual((root / 'include/autotools.mk').read_bytes(), include)

    def test_upstream_deduplicated_is_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            root, recipe = self.tree(d, HOOKS.replace('filter autoreconf,$(Hooks', 'filter autoreconf_target,$(Hooks'))
            before = recipe.read_bytes(), recipe.stat().st_mtime_ns
            gnutls.optimize(root)
            self.assertEqual((recipe.read_bytes(), recipe.stat().st_mtime_ns), before)

    def test_unknown_recipe_or_missing_implicit_hook_fails_without_write(self):
        for hooks, fixup in [(HOOKS, 'autoreconf'), (HOOKS.replace('gettext_version_target autoreconf_target', 'gettext_version_target'), 'gettext-version'), ('', 'gettext-version')]:
            with self.subTest(hooks=hooks, fixup=fixup), tempfile.TemporaryDirectory() as d:
                root, recipe = self.tree(d, hooks, fixup)
                before = recipe.read_bytes()
                with self.assertRaises(ValueError):
                    gnutls.optimize(root)
                self.assertEqual(recipe.read_bytes(), before)

    @unittest.skipUnless(os.environ.get('GNUTLS_PRISTINE_SOURCE'), 'set GNUTLS_PRISTINE_SOURCE for real upstream recipe/include')
    def test_real_upstream_recipe_and_include(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for relative in ('feeds/packages/libs/gnutls/Makefile', 'include/autotools.mk'):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(Path(os.environ['GNUTLS_PRISTINE_SOURCE']) / relative, target)
            recipe = root / 'feeds/packages/libs/gnutls/Makefile'
            before = recipe.read_bytes()
            gnutls.optimize(root)
            self.assertEqual(recipe.read_bytes(), before.replace(b'PKG_FIXUP:=autoreconf gettext-version', b'PKG_FIXUP:=gettext-version'))
            gnutls.optimize(root)
