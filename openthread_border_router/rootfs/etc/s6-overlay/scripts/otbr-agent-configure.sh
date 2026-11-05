#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
# ==============================================================================
# Configure OTBR depending on add-on settings
# ==============================================================================

# shellcheck source=./openthread_border_router/rootfs/etc/s6-overlay/scripts/otbr-agent-common
. /etc/s6-overlay/scripts/otbr-agent-common

if bashio::config.has_value 'advanced.trel'; then
    otbr_apply_setting trel trel
else
    ot-ctl trel enable
fi

if bashio::config.true 'nat64'; then
    bashio::log.info "Enabling NAT64."
    ot-ctl nat64 enable
    ot-ctl dns server upstream enable
fi

mdns_localhostname="$(hostname)-otbr"
bashio::log.info "Setting OpenThread mDNS local hostname to ${mdns_localhostname}."
ot-ctl mdns localhostname "${mdns_localhostname}"
ot-ctl mdns enable

# To avoid asymmetric link quality the TX power from the controller should not
# exceed that of what other Thread routers devices typically use.
if bashio::config.has_value 'advanced.tx_power'; then
    otbr_apply_setting tx_power txpower
else
    ot-ctl txpower 6
fi

if ! otbr_has_advanced_settings; then
    exit 0
fi

otbr_apply_setting leader_weight leaderweight
otbr_apply_setting router_eligible routereligible
otbr_apply_setting route_preference br routeprf
otbr_apply_setting rio_preference br rioprf

# SRP is still stopped while Thread is disabled. Keep its native auto-enable
# control intact so border routing can start it once connectivity is ready.
otbr_apply_setting srp_anycast_sequence_number srp server seqnum
otbr_apply_setting srp_address_mode srp server addrmode

omr_mode="$(bashio::config 'advanced.omr_mode')"
case "${omr_mode}" in
    auto) otbr_cli br omrconfig auto || true ;;
    disabled) otbr_cli br omrconfig disable || true ;;
    custom)
        omr_prefix="$(bashio::config 'advanced.omr_prefix')"
        omr_preference="$(bashio::config 'advanced.omr_preference')"
        # OpenThread validates the IPv6 prefix itself, including its /64 length.
        if bashio::config.has_value 'advanced.omr_prefix' \
            && [[ "${omr_preference}" =~ ^(low|med|high)$ ]]; then
            otbr_cli br omrconfig custom "${omr_prefix}" "${omr_preference}" || true
        else
            bashio::log.warning "Custom OMR requires omr_prefix (IPv6 /64) and omr_preference (low, med, or high)."
        fi
        ;;
esac
if [[ "${omr_mode}" != "custom" ]] \
    && { bashio::config.has_value 'advanced.omr_prefix' || bashio::config.has_value 'advanced.omr_preference'; }; then
    bashio::log.warning "Ignoring omr_prefix and omr_preference without omr_mode: custom."
fi

# Resume only a saved network, as OTBR's TryResumeNetwork does, without reading
# dataset keys. PAN ID 0xffff stays available for fresh HA commissioning.
if pan_id="$(otbr_cli panid)"; then
    pan_id="${pan_id//$'\r'/}"
    if [[ "${pan_id}" =~ (^|$'\n')0x([[:xdigit:]]{4})($'\n'|$) ]]; then
        if [[ "${BASH_REMATCH[2],,}" == "ffff" ]]; then
            exit 0
        fi
        for _ in 1 2 3; do
            if otbr_cli ifconfig up && otbr_cli thread start; then
                exit 0
            fi
            otbr_cli ifconfig down || true
        done
    fi
fi
bashio::log.warning "Could not resume the saved Thread network. Check the command errors and restart the app."
