"""NSS userspace policy and opt-in real-source checks."""
import json
import os
import re
import subprocess
from pathlib import Path
import unittest

from Tests.test_source import ROOT, prepare

PATCHES = tuple('package/network/utils/iproute2/patches/' + name for name in
                ('400-add-nss-qdisc.patch', '500-add-nssmirred.patch'))
CLIENTS = ('bridge-mgr', 'vlan-mgr', 'pppoe', 'qdisc', 'igs', 'tun6rd',
           'l2tpv2', 'pptp', 'map-t', 'gre', 'tunipip6', 'lag-mgr',
           'netlink', 'eogremgr', 'vxlanmgr', 'match', 'mirror', 'wifi-meshmgr')


class NSSTests(unittest.TestCase):
    def test_userspace_patches_reviewed(self):
        policy = json.loads((ROOT / 'Config/nss-policy.json').read_text())
        for name in PATCHES:
            with self.subTest(name=name):
                self.assertIn(name, policy['take'])
                self.assertRegex(policy['edit_sha256'][name], r'^[0-9a-f]{64}$')

    def test_new_iproute2_extension_rejected(self):
        policy = json.loads((ROOT / 'Config/nss-policy.json').read_text())
        # Isolate extension checking from already-reviewed file fingerprints.
        policy.update(take=[], edit_sha256={})
        for name in ('patches/600-nss-new.patch', 'patches/400-add-nss-qdisc.patch',
                     'patches/500-add-nssmirred.patch', 'Makefile'):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'NSS extension'):
                prepare.validate_delta(ROOT, ROOT, policy,
                                       {'package/network/utils/iproute2/' + name: []})
        prepare.validate_delta(ROOT, ROOT, policy, {'package/network/utils/other/Makefile': []})

    def test_supported_clients_installed(self):
        config = (ROOT / 'Config/MX4200.txt').read_text().splitlines()
        for package in ('tc-full',) + tuple('kmod-qca-nss-drv-' + x for x in CLIENTS):
            with self.subTest(package=package):
                self.assertIn('CONFIG_PACKAGE_' + package + '=y', config)
        self.assertNotIn('CONFIG_BROKEN=y', config)

    @unittest.skipUnless(os.getenv('NSS_OFFICIAL') and os.getenv('NSS_DONOR'),
                         'set NSS_OFFICIAL and NSS_DONOR to real release trees')
    def test_real_release_fingerprints(self):
        official, donor = Path(os.environ['NSS_OFFICIAL']), Path(os.environ['NSS_DONOR'])
        policy = json.loads((ROOT / 'Config/nss-policy.json').read_text())
        for name in PATCHES:
            self.assertTrue((donor / name).is_file())
            self.assertEqual(prepare.file_delta(official, donor, name), policy['edit_sha256'][name])

    @unittest.skipUnless(os.getenv('NSS_TC'), 'set NSS_TC to the compiled real tc binary')
    def test_real_tc_parsers(self):
        for args, expected in ((['qdisc', 'add', 'dev', 'lo', 'root', 'nssfq_codel', 'help'],
                                'Usage: ... nssfq_codel'),
                               (['actions', 'add', 'action', 'nssmirred', 'help'],
                                'Usage: nssmirred redirect')):
            result = subprocess.run([os.environ['NSS_TC'], *args], text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            self.assertIn(expected, result.stdout)
            self.assertNotIn('Unknown', result.stdout)

    def test_client_inventory_matches_supported_recipes(self):
        recipe = (ROOT / 'package/qca-nss/qca-nss-clients/Makefile').read_text()
        definitions = re.findall(r'^define KernelPackage/qca-nss-drv-([^/\n]+)\n(.*?)^endef',
                                 recipe, re.M | re.S)
        supported = {name for name, body in definitions
                     if not any(gate in body for gate in
                                ('@BROKEN', '@TARGET_ipq806x', '@TARGET_qualcommbe'))}
        self.assertEqual(set(CLIENTS), supported)

    def test_client_autoload_policy(self):
        recipe = (ROOT / 'package/qca-nss/qca-nss-clients/Makefile').read_text()
        definitions = dict(re.findall(
            r'^define KernelPackage/qca-nss-drv-([^/\n]+)\n(.*?)^endef',
            recipe, re.M | re.S))
        on_demand = {'qdisc', 'igs', 'netlink', 'eogremgr', 'match', 'mirror'}
        for name in CLIENTS:
            with self.subTest(name=name):
                body = definitions[name]
                if name in on_demand:
                    self.assertNotIn('AUTOLOAD', body)
                else:
                    self.assertRegex(body, r'AUTOLOAD:=\$\(call AutoLoad,(51|60),')
        # This legacy mirred helper is not installed; IGS is an action module,
        # not a service that should invent an ingress policy at boot.
        self.assertNotIn('./files/qca-nss-mirred.init', recipe)
        netlink = (ROOT / 'package/qca-nss/qca-nss-clients/files/qca-nss-netlink.init').read_text()
        self.assertNotRegex(netlink, r'(?m)^\s*START=')
        self.assertNotRegex(netlink, r'(?m)^\s*STOP=')

    @unittest.skipUnless(os.getenv('NSS_CONFIG'), 'set NSS_CONFIG to real defconfig output')
    def test_real_defconfig(self):
        config = Path(os.environ['NSS_CONFIG']).read_text().splitlines()
        for package in ('tc-full',) + tuple('kmod-qca-nss-drv-' + x for x in CLIENTS):
            with self.subTest(package=package):
                self.assertIn('CONFIG_PACKAGE_' + package + '=y', config)
        for symbol in ('NSS_DRV_SHAPER_ENABLE', 'NSS_DRV_IGS_ENABLE'):
            self.assertIn('CONFIG_' + symbol + '=y', config)


if __name__ == '__main__':
    unittest.main()
