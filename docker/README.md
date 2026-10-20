# ARM64 Debian builder

Uses the same environment-only ARM64 recipe as W1700K: official Debian base,
checksum-verified Go bootstrap at `/usr/lib/go`, no preseeded source or toolchain.
The workflow inspects the image ID before running it and records a separate
recipe/package/architecture fingerprint for exact toolchain cache compatibility.

Cache archives use pigz for parallel gzip; speed gains require CI measurement.
The prepared official feed's Go bootstrap floor is checked before configuration.
Host LLVM is not installed; selecting `CONFIG_USE_LLVM_HOST=y` fails before download.

Run `bash /builder-context/smoke.sh` inside a clean image to check commands,
headers, bootstrap Go, Git and archive operations without compilation.
`tests/test_builder_image.py` covers image selection, failure paths and fingerprint
invalidation. Environment checks do not replace a firmware build or hardware test.
