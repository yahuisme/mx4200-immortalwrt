"""MU-EDCA transplant regression and optional prepared-source ABI check.

MUEDCA_HOSTAPD and MUEDCA_MAC80211 point at prepared source directories.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMPANION = 'package/network/services/hostapd/patches/900-hostapd-update-muedca-params.patch'


class MuedcaTests(unittest.TestCase):
    def test_companion_selected_and_fingerprinted(self):
        policy = json.loads((ROOT / 'Config/nss-policy.json').read_text())
        self.assertIn(COMPANION, policy['take'])
        self.assertIn(COMPANION, policy['edit_sha256'])

    def test_local_abi_patch_installed(self):
        spec = importlib.util.spec_from_file_location('prepare', ROOT / 'Scripts/Prepare.py')
        assert spec is not None and spec.loader is not None
        prepare = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(prepare)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            dest = output / 'package/network/services/hostapd/patches'
            dest.mkdir(parents=True)
            prepare.hostapd_muedca_patch(output)
            self.assertEqual((dest / '901-hostapd-muedca-backports-abi.patch').read_bytes(),
                             (ROOT / 'patches/hostapd/901-hostapd-muedca-backports-abi.patch').read_bytes())

    @unittest.skipUnless(os.getenv('MUEDCA_HOSTAPD') and os.getenv('MUEDCA_MAC80211'),
                         'set prepared source paths for compiled ABI verification')
    def test_prepared_abi_and_event_path(self):
        host = Path(os.environ['MUEDCA_HOSTAPD'])
        mac = Path(os.environ['MUEDCA_MAC80211'])
        headers = [host / 'src/drivers/nl80211_copy.h', mac / 'include/uapi/linux/nl80211.h']
        values = []
        with tempfile.TemporaryDirectory() as tmp:
            for index, header in enumerate(headers):
                source = Path(tmp) / f'abi{index}.c'
                binary = source.with_suffix('')
                source.write_text('#include <stdio.h>\n#include "' + str(header) + '"\n'
                                  'int main(void) { printf("%d %d\\n", '
                                  'NL80211_CMD_UPDATE_HE_MUEDCA_PARAMS, '
                                  'NL80211_ATTR_HE_MUEDCA_PARAMS); return 0; }\n')
                subprocess.run(['cc', '-Wall', '-Werror', str(source), '-o', str(binary)], check=True)
                values.append(subprocess.check_output([str(binary)], text=True).strip())
        print('compiled MU-EDCA command/attribute: hostapd=' + values[0] + ', mac80211=' + values[1])
        self.assertEqual(values[0], values[1])
        for filename, token in [('src/drivers/driver_nl80211_event.c', 'case NL80211_CMD_UPDATE_HE_MUEDCA_PARAMS:'),
                                ('src/ap/drv_callbacks.c', 'case EVENT_UPDATE_MUEDCA_PARAMS:'),
                                ('src/ap/drv_callbacks.c', 'ieee802_11_update_beacons(hapd->iface)')]:
            self.assertIn(token, (host / filename).read_text())
        self.assertIn('NL80211_ATTR_HE_MUEDCA_PARAMS', (mac / 'net/wireless/nl80211.c').read_text())


if __name__ == '__main__':
    unittest.main()
