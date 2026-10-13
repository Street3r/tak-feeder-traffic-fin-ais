# tak-feeder-traffic-fin-ais

> [!WARNING]
> **Work in progress. Not recommended for use.** This fork is being improved
> and has not been tested against a live TAK server yet. Things may change or
> break without notice.

Sends the AIS ship traffic of Finnish waters to a TAK server as CoT. The data
comes from Fintraffic's Digitraffic marine MQTT service.

Fork of [sgofferj/tak-feeder-traffic-fin-ais](https://github.com/sgofferj/tak-feeder-traffic-fin-ais)
by Stefan Gofferje. The Node.js feeder is rewritten in Python on the logic of
his [trakbridge-plugin-ais-digitraffic](https://github.com/sgofferj/trakbridge-plugin-ais-digitraffic).

## What it sends

| Field | Value |
|---|---|
| UID | `AIS-<MMSI>` (unchanged from upstream) |
| Callsign | ship name, or `IMO:…` / `MMSI:…` if the name is not known yet |
| Type | `a-<affiliation>` + ship type, e.g. `a-f-S-X-M-C` (Finnish cargo ship) |
| Speed / course | m/s (from knots) and course over ground |

```
Name: BALTIC STAR
IMO: 1234567
MMSI: 230123456
Radio callsign: OJAB
Country (MMSI): Finland
Type: 70 (Cargo, all ships of this type)
Status: Under way using engine
Speed: 10.0 kn
Destination: HELSINKI
Last position: 14:20:00
Source: Fintraffic / digitraffic.fi, CC BY 4.0
#AIS #cargo
```

### Affiliation

- **By flag:** the first three digits of the MMSI (MID) give the country and
  its affiliation from [countries.json](src/tak_feeder_traffic_fin_ais/countries.json),
  the same table as upstream.
- **`AIS_FOC_SUSPECT=1`:** also marks Panama, Liberia, Comoros and the Cook
  Islands suspect, as trakbridge-plugin-ais-digitraffic does. Off by default.
- **`AIS_AFFIL_OVERRIDES`:** your own changes, e.g. `538:s,626:s`.
- **Shadow fleet (`SHADOWFLEET=1`):** vessels on the
  [tak-shadowfleet-id](https://github.com/sgofferj/tak-shadowfleet-id) list
  (matched by IMO, or by MMSI if the IMO is missing) become suspect and get the
  sanctions, other names, listed flag and type in the remarks and the
  `#shadowfleet` tag. **A match never softens the affiliation:** a hostile flag
  stays hostile. The list is downloaded daily; the last good copy is used if
  the download fails. Off by default. The list is licensed **CC BY-NC 4.0**
  (non-commercial use only) and is credited in the remarks.

### Send rate

Vessels that moved or got new metadata are sent every `UPDATE_INTERVAL`
seconds, the rest every `REFRESH_INTERVAL` seconds. Vessels silent for
`MAX_AGE` seconds are dropped. Names, IMO numbers and types are saved to
`DATA_DIR`, so after a restart ships have names right away instead of waiting
for their next metadata message.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `COT_URL` | `udp://239.2.3.1:6969` | TAK server. Old name `REMOTE_SERVER_URL` works |
| `PYTAK_TLS_CLIENT_CERT` / `PYTAK_TLS_CLIENT_KEY` | | Client certificate and unencrypted key (PEM). Old names `REMOTE_SSL_USER_CERTIFICATE` / `REMOTE_SSL_USER_KEY` work |
| `PYTAK_TLS_DONT_VERIFY` | `0` | `1` = do not verify the server certificate |
| `MQTT_URL` | `wss://meri.digitraffic.fi:443/mqtt` | Digitraffic MQTT |
| `DIGITRAFFIC_USER` | `tak-feeder-traffic-fin-ais` | Application name in the MQTT client id |
| `AIS_TYPES` | (all) | Only these AIS ship types |
| `AIS_FOC_SUSPECT` | `0` | See *Affiliation* |
| `AIS_AFFIL_OVERRIDES` | | `MID:affiliation,...` |
| `AISDB` | (built-in) | Path to an own countries.json |
| `SHADOWFLEET` | `0` | See *Affiliation* |
| `SHADOWFLEET_URL` | tak-shadowfleet-id `main` | Shadow fleet list |
| `DATA_DIR` | `/var/lib/tak-feeder` | Metadata cache and the saved shadow fleet list |
| `UPDATE_INTERVAL` | `5` | Seconds between send rounds (old name `UPDATE_RATE`) |
| `REFRESH_INTERVAL` | `30` | Re-send unmoved vessels this often |
| `STALE_SECONDS` | `90` | Marker lifetime without new data |
| `MAX_AGE` | `600` | Stop sending a vessel silent this long |
| `TIMEZONE` | `Europe/Helsinki` | Time zone of the last position time |
| `HEALTH_MAX_SILENCE` | `300` | Unhealthy when no AIS data for this long |
| `DEBUG` | `0` | Debug logging |

`UUID`, `CALLSIGN`, `MYCOT` and `LOGCOT` of the old feeder are no longer used:
they configured the heartbeat marker, which is gone.

## Running

Image for amd64 and arm64: `ghcr.io/street3r/tak-feeder-traffic-fin-ais:latest`.

```yaml
services:
  feeder-ais:
    image: ghcr.io/street3r/tak-feeder-traffic-fin-ais:latest
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./certs:/data:ro
      - ais-data:/var/lib/tak-feeder

volumes:
  ais-data:
```

The container runs as uid 10001; the key must be readable by it.

## Data

AIS: Fintraffic / digitraffic.fi, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
Shadow fleet list (optional): tak-shadowfleet-id by Stefan Gofferje from
OpenSanctions and the UK FCDO sanctions list,
[CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/). Its author
gives no guarantee that the list is complete or correct.

## Credits and changes

Original work © Stefan Gofferje:
[tak-feeder-traffic-fin-ais](https://github.com/sgofferj/tak-feeder-traffic-fin-ais),
[trakbridge-plugin-ais-digitraffic](https://github.com/sgofferj/trakbridge-plugin-ais-digitraffic)
and [tak-shadowfleet-id](https://github.com/sgofferj/tak-shadowfleet-id),
used with his permission.

Changes in this fork (Street3r):

- 2026-10-13
  - Rewritten in Python (pytak, paho-mqtt) on the logic of the TrakBridge plugin.
  - **Fixed:** ship type mapping now covers all AIS types 0–99; search and
    rescue and anti-pollution vessels showed as law enforcement, fishing
    vessels were not recognised.
  - **Fixed:** the heartbeat marker at 0,0 (callsign from `CALLSIGN`) is gone.
  - Ship names, IMO and type are saved to disk and survive restarts.
  - Name fallbacks, trimmed names, type description, navigation status,
    speed in knots, `#AIS #<category>` tags, data source in the remarks.
  - Optional ship type filter, flag-of-convenience switch, own affiliation
    overrides and the shadow fleet list (never softens the affiliation).
  - Moved vessels sent every round, the rest every `REFRESH_INTERVAL`.
  - pytak reconnects to TAK after outages without losing state.
  - Standard variable names with the old ones as aliases; health check;
    unprivileged container; tests and CI.

## License

GNU General Public License v3.0 or later, see [LICENSE](LICENSE).
The shadow fleet list is not part of this repository; it is downloaded at
run time under its own license.
