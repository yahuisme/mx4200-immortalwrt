# stage2 calls this before killing processes; retain native upgrade indication.
indicate_upgrade() {
	case "$(cat /tmp/sysinfo/board_name 2>/dev/null)" in
		linksys,mx4200v1|linksys,mx4200v2)
			touch /tmp/mx4200-led-upgrade
			echo 0 > /sys/class/leds/red:status/brightness
			;;
	esac
	. /etc/diag.sh
	set_state upgrade
}
