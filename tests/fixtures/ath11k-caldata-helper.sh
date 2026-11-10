# From ImmortalWrt 4fc16f2985a358bd43bb522e43f05395fcbd6ed5:
# package/base-files/files/lib/functions/caldata.sh (OpenWrt GPL-2.0).
ath11k_remove_regdomain() {
	local target=$1
	local regdomain
	local regdomain_data

	regdomain=$(hexdump -v -n 2 -s 0x34 -e '1/1 "%02x"' $target)
	caldata_patch_data "0000" 0x34 0xa "$target"

	for offset in 0x450 0x458 0x500 0x5a8; do
		regdomain_data=$(hexdump -v -n 2 -s $offset -e '1/1 "%02x"' $target)

		if [ "$regdomain" == "$regdomain_data" ]; then
			caldata_patch_data "0000" $offset 0xa "$target"
		fi
	done
}
