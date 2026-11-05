#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
# ==============================================================================
# Apply optional Thread settings after Home Assistant discovery
# ==============================================================================

# shellcheck source=./openthread_border_router/rootfs/etc/s6-overlay/scripts/otbr-agent-common
. /etc/s6-overlay/scripts/otbr-agent-common

configure_srp_anycast() {
    local seed=0 sequence_number previous attempt sequence_file=/data/thread/srp-anycast-sequence
    if bashio::config.has_value 'srp_anycast_sequence_number'; then
        seed="$(bashio::config 'srp_anycast_sequence_number')"
    fi
    sequence_number="${seed}"
    if [[ -f "${sequence_file}" ]] && previous=$(cat "${sequence_file}"); then
        if [[ "${previous}" =~ ^([0-9]{1,3})\ ([0-9]{1,3})$ ]] \
            && ((10#${BASH_REMATCH[1]} == seed && 10#${BASH_REMATCH[2]} <= 255)); then
            sequence_number=$(((10#${BASH_REMATCH[2]} + 1) % 256))
        fi
    fi

    # Save before use: a failed configuration must not reuse an advertised number.
    if ! { printf '%s %s\n' "${seed}" "${sequence_number}" > "${sequence_file}.tmp" \
        && mv "${sequence_file}.tmp" "${sequence_file}"; }; then
        bashio::log.warning "Cannot save SRP anycast sequence number; keeping the default SRP mode."
        return
    fi

    # Explicit disable also turns off auto-enable. Restore border routing's
    # control even when setting the address mode or sequence number fails.
    if otbr_cli srp server disable; then
        # Do not advertise anycast with a stale sequence number.
        if otbr_cli srp server seqnum "${sequence_number}"; then
            otbr_cli srp server addrmode anycast || true
        fi
    fi
    for attempt in 1 2 3; do
        if otbr_cli srp server auto enable; then
            return
        fi
        if ((attempt < 3)); then
            sleep 1
        fi
    done
    bashio::log.warning "Could not restore SRP auto-enable after 3 attempts; SRP may remain disabled. Restart the app after resolving the command failure."
}

if bashio::config.has_value 'leader_weight'; then
    otbr_cli leaderweight "$(bashio::config 'leader_weight')" || true
fi

if bashio::config.true 'srp_anycast'; then
    configure_srp_anycast
fi

if ! bashio::config.has_value 'omr_preference' && ! bashio::config.true 'take_leadership'; then
    exit 0
fi

# Discovery must precede this wait: on a fresh installation Home Assistant needs
# the REST API to commission the Thread network. All command calls are bounded.
deadline=$((SECONDS + 120))
while ((SECONDS < deadline)); do
    state="$(otbr_cli state)" || break
    state="${state%%$'\n'*}"
    state="${state%$'\r'}"
    case "${state}" in
        child|router|leader) break ;;
    esac
    sleep 2
done

case "${state:-}" in
    child|router|leader) ;;
    *)
        bashio::log.warning "Thread did not attach; restart the app after commissioning to apply OMR preference and leadership settings."
        exit 0
        ;;
esac

if bashio::config.has_value 'omr_preference'; then
    if omr_prefix="$(otbr_cli br omrprefix local)"; then
        omr_prefix="${omr_prefix%%$'\n'*}"
        omr_prefix="${omr_prefix%$'\r'}"
        if [[ "${omr_prefix}" =~ ^[[:xdigit:]:]+/64$ ]]; then
            otbr_cli br omrconfig custom "${omr_prefix}" "$(bashio::config 'omr_preference')" || true
        else
            bashio::log.warning "No local OMR /64 prefix available; OMR preference was not applied."
        fi
    fi
fi

if bashio::config.true 'take_leadership'; then
    # The role may have changed while applying the OMR preference.
    if state="$(otbr_cli state)"; then
        state="${state%%$'\n'*}"
        case "${state%$'\r'}" in
            child|router)
                bashio::log.warning "Taking Thread leadership creates a new partition; other routers decide whether to merge."
                otbr_cli state leader || true
                ;;
        esac
    fi
fi
