# shellcheck shell=ash
# Private UCI work for MX4200 first-boot scripts. They run in boot's subshell.
mx_defaults_finish() {
    [ "$mx_keep_stage" = 1 ] || rm -rf "$mx_stage"
    [ "$1" -eq 0 ] || echo 'MX4200 defaults: presets not applied' >&2
}

mx_defaults_begin() {
    local name="$1" pending
    shift
    # A failed first boot must not authorize writes after users can log in.
    local marker="/etc/.mx4200-$name-attempted"
    [ ! -e "$marker" ] || exit 0
    # Without a persistent barrier it is safer to retire than retry later.
    if ! ( umask 077; set -C; : > "$marker" ); then
        echo "MX4200 defaults: cannot record first-boot attempt; skipping $name" >&2
        exit 0
    fi

    mx_stage="$(mktemp -d /etc/config/.mx4200-XXXXXX)" || exit 1
    mx_keep_stage=0
    trap 'mx_defaults_finish "$?"' EXIT
    mkdir "$mx_stage/delta" "$mx_stage/next" || exit 1
    for name in "$@"; do
        [ -f "/etc/config/$name" ] && [ ! -L "/etc/config/$name" ] || exit 1
        # Finalize preceding defaults for these packages before cloning them.
        # -t alone still loads /tmp/.uci. Leaving those deltas pending would
        # replay earlier add_list operations at boot's global commit.
        pending="$(uci -q changes "$name")" || exit 1
        [ -z "$pending" ] || uci -q commit "$name" || exit 1
        cp -p "/etc/config/$name" "$mx_stage/$name" || exit 1
        cp -p "$mx_stage/$name" "$mx_stage/next/$name" || exit 1
    done
}

mx_uci() {
    uci -q -c "$mx_stage/next" -C '' -t "$mx_stage/delta" "$@"
}

mx_defaults_commit() {
    local name rollback expected actual
    for name in "$@"; do
        expected="$(mx_uci -N export "$name")" || return 1
        mx_uci commit "$name" || return 1
        # UCI may return success after a truncated write. An absolute export
        # path reads the file without applying any saved deltas.
        actual="$(cd "$mx_stage/next" && uci -q -N export "/proc/self/cwd/$name")" || return 1
        if [ "$actual" != "$expected" ]; then
            echo "MX4200 defaults: committed $name differs from staged settings" >&2
            return 1
        fi
    done
    for name in "$@"; do
        # Same-filesystem replacement. If a later rename fails, restore only
        # the packages already published; nothing enters boot's shared deltas.
        if ! mv -f "$mx_stage/next/$name" "/etc/config/$name"; then
            for rollback in "$@"; do
                [ "$rollback" != "$name" ] || break
                if ! mv -f "$mx_stage/$rollback" "/etc/config/$rollback"; then
                    mx_keep_stage=1
                    echo "MX4200 defaults: failed to restore $rollback; original retained at $mx_stage/$rollback" >&2
                fi
            done
            return 1
        fi
    done
}
