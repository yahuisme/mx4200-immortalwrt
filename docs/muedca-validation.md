# Dynamic MU-EDCA hostapd companion

The selected ath11k and mac80211 `203-mac80211-ath11k-fw-dynamic-muedca.patch`
patches emit firmware MU-EDCA updates over nl80211. The matching LiBwrt
`900-hostapd-update-muedca-params.patch` must also be selected: it decodes the
four AC parameter triplets, dispatches `EVENT_UPDATE_MUEDCA_PARAMS`, updates
hostapd's HE MU-EDCA configuration/counts and regenerates beacons.

Do not copy the companion without the local native follow-up
`patches/hostapd/901-hostapd-muedca-backports-abi.patch`. The hostapd nl80211
copy ends earlier than backports 6.18.39. The follow-up inserts the two
intervening upstream commands and eight attributes before the private
MU-EDCA entries, preserving all existing upstream identifiers.

| Prepared header | MU-EDCA command | MU-EDCA attribute |
| --- | ---: | ---: |
| Donor hostapd companion without follow-up | 158 | 338 |
| Hostapd with local follow-up | 160 | 346 |
| Selected mac80211/backports 6.18.39 | 160 | 346 |

`Prepare.py` installs the follow-up in the native hostapd patch directory and
records its SHA256 in `source-lock.json` under `local_patch_sha256`. The donor
companion remains covered by the existing selected-edit fingerprint policy.
Future backports/header upgrades require rerunning the compiled ABI check;
matching symbol names or successfully applying patches is not sufficient.

## Verification

Local validation used official and donor `v25.12.2`, a fresh generated tree,
and an isolated copy of the previously prepared buildroot; original sources
and existing prepared trees were left untouched.

- RED: the new tests failed for the missing companion selection and missing
  installation helper before the fix (`muedca-red.log`).
- Real native prepare completed with exit 0:
  `make package/network/services/hostapd/prepare V=s 'TAR=tar --no-same-permissions'`.
  Both 900 and 901 patches applied, and the wpad-full-openssl prepared stamp
  was created (`muedca-hostapd-prepare.log`). No full firmware compile was run.
- With the prepared hostapd/backports source paths supplied, all three
  independent tests passed. They compile and execute C probes against each
  actual header and verify the event/Beacon call path (`muedca-green.log`).
- Complete source generation succeeded and included both patches and the
  follow-up hash (`muedca-generate.log`).

Evidence files are in `/root/mx4200-nss-investigation/`. Reproduce the
independent ABI test from this repository with:

```sh
MUEDCA_HOSTAPD=/path/to/prepared/hostapd-2025.08.26~ca266cc2 \
MUEDCA_MAC80211=/path/to/prepared/backports-6.18.39 \
python3 -m unittest Tests.test_muedca -v
```

Without these environment variables the compiled integration check is
explicitly skipped, while policy/installation regression tests still run.
This verifies source preparation and ABI agreement, not radio firmware
runtime behavior or successful on-device Beacon transmission.
