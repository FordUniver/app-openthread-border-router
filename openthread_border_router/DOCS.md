# Home Assistant App: OpenThread Border Router

## Installation

Follow these steps to get the app (formerly known as add-on) installed on your system:

1. In Home Assistant, go to **Settings** > **Apps** > **Install app**.
2. Find the **OpenThread Border Router** app and select it.
3. Select the **Install** button.

## How to use

You will need a 802.15.4 capable radio supported by OpenThread flashed with OpenThread
RCP firmware:

- Home Assistant Yellow
- Home Assistant SkyConnect/Connect ZBT-1
- Home Assistant Connect ZBT-2

These devices are all capable to run OpenThread and will be flashed with the correct
firmware by Home Assistant Core.

If you are using Home Assistant Yellow, choose `/dev/ttyAMA1` as device.

### Alternative radios

The website [openthread.io maintains a list of supported platforms][openthread-platforms]
lists other Thread capable radios. A well documented Radio for development is the
Nordic Semiconductor [nRF52840 Dongle][nordic-nrf52840-dongle]. The Dongle needs
a recent version of the OpenThread RCP firmware.
[This article][nordic-nrf52840-dongle-install] outlines the steps to install the
RCP firmware for the nRF52840 Dongle.

Once the firmware is loaded follow the following steps:

1. Select the correct `device` in the app configuration tab and press `Save`.
2. Start the app.

### OpenThread Border Router

This app makes your Home Assistant installation an OpenThread Border Router
(OTBR). The border router can be used to comission Matter devices which connect
through Thread. Home Assistant Core will automatically detect this app and
create a new integration named "Open Thread Border Router". With Home Assistant
Core 2023.3 and newer the OTBR will get configured automatically. The Thread
integration allows to inspect the network configuration.

### Web interface (advanced)

There is also a web interface provided by the OTBR. However, the web
interface has caveats (e.g. forming a network does not generate an off-mesh
routable IPv6 prefix which causes changing IPv6 addressing on first app
restart). It is still possible to enable the web interface for debugging
purpose. Make sure to expose both the Web UI port and REST API port (the
latter needs to be on port 8081) on the host interface. To do so, click on
"Show disabled ports" and enter a port (e.g. 8080) in the OpenThread Web UI
and 8081 in the OpenThread REST API port field).

## Configuration

App configuration:

| Configuration      | Description                                                                       |
| ------------------ | --------------------------------------------------------------------------------- |
| device (mandatory) | Serial port where the OpenThread RCP Radio is attached                            |
| baudrate           | Serial port baudrate (depends on firmware)                                        |
| flow_control       | If hardware flow control should be enabled (depends on firmware)                  |
| otbr_log_level     | Set the log level of the OpenThread BorderRouter Agent                            |
| firewall           | Enable OpenThread Border Router firewall to block unnecessary traffic             |
| nat64              | Enable NAT64 to allow Thread devices accessing IPv4 addresses                     |
| advanced           | Optional native Thread controls (see below)                                       |
| network_device     | IP address and port to connect to a network-based RCP (see below)                 |
| beta               | Enable beta mode to run a newer, experimental version of OpenThread Border Router |

> [!WARNING]
> The OTBR expects the RCP connected radio to be on a reliable link such as
> UART or SPI. Using TCP/IP to reach a remote RCP radio breaks this assumption.
> If the TCP/IP connection fails, the OTBR will not shutdown cleanly and leave
> stale routes in your network. This will lead to Thread devices to be
> potentially unreachable for up to 30 minutes (route lifetime) even when other
> routers are available.
>
> The RCP protocol is not designed to be transferred over an IP network: It is
> a timing-sensitive protocol. You might experience Thread issues if your
> network link has excessive latencies. As Thread is networking capable,
> running a Thread border router on the system the RCP radio is plugged in is
> recommended.

> [!NOTE]
> When using a network device, you still need to set a dummy serial port device, e.g. `/dev/ttyS3`.

### Advanced settings

The configuration form groups these optional controls under the collapsed
**Advanced settings** section. In YAML, place them under `advanced`.
The default is `advanced: {}`: the app retains its 6 dBm transmit power and
TREL enablement, and OpenThread controls leadership, routing, and SRP.
Remove a field to restore its default on the next app restart.

| Setting                       | Native CLI setting    | Purpose                                                                          |
| ----------------------------- | --------------------- | -------------------------------------------------------------------------------- |
| `tx_power`                    | `txpower`             | Radio transmit power in dBm (-128 to 127; app default 6)                         |
| `leader_weight`               | `leaderweight`        | Weight for partitions formed by this device as leader (0 to 255)                 |
| `router_eligible`             | `routereligible`      | `enable` or `disable` eligibility to become a Thread router                      |
| `trel`                        | `trel`                | `enable` or `disable` Thread Radio Encapsulation Link over the backbone          |
| `omr_mode`                    | `br omrconfig`        | `auto`, `custom`, or `disabled` advertisement of this border router's OMR prefix |
| `omr_prefix`                  | `br omrconfig custom` | Explicit IPv6 /64 prefix, required in custom mode                                |
| `omr_preference`              | `br omrconfig custom` | `low`, `med`, or `high` prefix preference, required in custom mode               |
| `route_preference`            | `br routeprf`         | `low`, `med`, or `high` external route preference in Thread Network Data         |
| `rio_preference`              | `br rioprf`           | `low`, `med`, or `high` Route Information Option preference on the backbone      |
| `srp_address_mode`            | `srp server addrmode` | `unicast` or `anycast` SRP server advertisement                                  |
| `srp_anycast_sequence_number` | `srp server seqnum`   | Fixed anycast sequence number (0 to 255)                                         |

For example, these options set transmit power and the weight for partitions
this device forms. All other controls keep their defaults:

```yaml
advanced:
  tx_power: 6
  leader_weight: 72
```

The radio and its firmware determine the supported transmit power range.
Higher power can produce asymmetric links: devices hear the border router but
cannot reach it with their own weaker transmitters.

Leader weight affects the preference between Thread partitions when they merge.
It does not elect a new leader in an existing partition or change the weight
advertised by a partition whose leadership was already established. The app does
not force leadership or create a new partition. Disabling router eligibility
makes this device operate as a child and can disrupt connectivity.

An off-mesh-routable (OMR) prefix supplies addresses used to reach Thread devices
from the backbone network. Its preference affects which prefix border routers
favor; it is separate from DNS, Thread leadership, and the two route preferences.
Custom mode requires both an explicit valid IPv6 /64 and a preference. The app
never copies or invents a prefix. OpenThread validates the supplied prefix.
`omr_prefix` and `omr_preference` are ignored outside custom mode. `disabled` maps
to `br omrconfig disable`: this border router stops advertising its own OMR prefix
but can use one advertised by another border router. Border routing remains
enabled. Leave either route preference unset for OpenThread to choose it
automatically.

Service Registration Protocol (SRP) address mode affects how clients find and
select a server. It does not transfer registrations between border routers or
guarantee selection of this server. Border routing retains control over when SRP
runs. The sequence number is a literal value: setting it does not select anycast
mode, and the app does not increment or persist a counter. Reusing the same
anycast sequence after a server restart can delay client re-registration. These
controls do not implement an automatic SRP failover policy.

Changes take effect when the app restarts. With any advanced value configured,
the app starts OTBR with automatic attachment paused, applies the controls, then
resumes a saved network. A fresh installation remains available for Home
Assistant to discover and commission; no dataset is created by these options.
Optional command failures are logged and do not skip network resume. If the
resume commands themselves fail, the app logs a warning; resolve the reported
error and restart it. An empty group uses the original automatic attachment path.

## Support

Got questions?

You have several options to get them answered:

- The [Home Assistant Discord Chat Server][discord].
- The Home Assistant [Community Forum][forum].
- Join the [Reddit subreddit][reddit] in [/r/homeassistant][reddit]

In case you've found a bug, please [open an issue on our GitHub][issue].

[discord]: https://www.home-assistant.io/join-chat
[forum]: https://community.home-assistant.io
[reddit]: https://reddit.com/r/homeassistant
[issue]: https://github.com/home-assistant/app-openthread-border-router/issues
[openthread-platforms]: https://openthread.io/platforms
[nordic-nrf52840-dongle]: https://www.nordicsemi.com/Products/Development-hardware/nrf52840-dongle
[nordic-nrf52840-dongle-install]: https://docs.nordicsemi.com/bundle/ncs-latest/page/nrf/protocols/thread/tools.html#configuring_a_radio_co-processor
