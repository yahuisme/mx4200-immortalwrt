# ARM64 Debian builder

The builder uses a digest-pinned Debian ARM64 base and installs a checksum-verified
Go bootstrap at `/usr/lib/go`. It contains no firmware source or prebuilt firmware toolchain.
The workflow runs the inspected image ID and uses a separate fingerprint of the
recipe, architecture and installed packages for toolchain cache keys.

Before building, the workflow checks the Go bootstrap against the selected feed's
minimum version and rejects `CONFIG_USE_LLVM_HOST=y` because host LLVM is not installed.

With `docker/` mounted at `/builder-context`, run `bash /builder-context/smoke.sh`
in a fresh container to check build prerequisites without compiling.
See [builder tests](../tests/test_builder_image.py) for image selection and cache key checks.
