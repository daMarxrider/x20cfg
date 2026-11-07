# EasySMX X20 reverse-engineering notes

## Classic Bluetooth (gamepad link)
- Address `98:B6:EA:72:61:D1`, presents as "Xbox Wireless Controller" (045E:02FD).
- SDP: only HID (0x1124) and PnP (0x1200) records; no SPP/RFCOMM.
- HID descriptor is the stock Xbox one: input reports 1 (sticks/buttons) and 2 (guide),
  output report 3 (rumble), input report 4 (battery). No vendor/feature reports,
  so configuration does not go over the classic HID link.

## BLE side (config channel?)
- Separate LE identity `98:B6:ED:72:61:D1`, name "Xpert2", public address.
- Advertisement: manufacturer data company 0x6C42, payload `75 65`; no service UUIDs.
- BlueZ `Device1.Connect` hangs indefinitely (no error) whether or not scanning is
  active -> advertisement looks non-connectable in the normal state.
- UPDATE: a raw kernel L2CAP LE socket (CID 4) connects in <1s; only bluetoothd's
  Connect path hangs. The tool therefore uses its own ATT client (`x20cfg/att.py`).

## GATT table (98:B6:ED:72:61:D1)
| handle | uuid | props | role |
|---|---|---|---|
| 0x07 | d7f010e1-660d-46e9-96c3-19c4148bdab5 | write | commands to controller |
| 0x09 | d7f010e2-660d-46e9-96c3-19c4148bdab5 | notify | responses (CCCD 0x0a) |
| 0x0d | ff13 | write | (unused by app for X20) |
| 0x0f | ff14 | notify | |
| 0x12 | ff15 | read/write | |

App: `com.pulsenet.inputset` (KeyLinker 3.73). BLE manager `util/b.java`, frame
builder/obfuscation `util/e.java`.

## Protocol (verified live)
- Frames: `[cmd, len, seq, rand, payload(<=15)…, crc8]`, obfuscated with e.h()/e.g()
  (see `x20cfg/protocol.py`). Replies are always cmd 0x19 with the request's seq.
- Enable notifications: write `01 00` to handle 0x0a.
- 145 (0x91): device info -> VID 1013, PID 2009, fw 1.22, model byte 0x52.
- 29 `[2,223,171]`: keepalive; also starts cmd-31 live-input streaming.

### Reads (reply byte0 = total length, page N fetched with first byte = N)
| cmd | args | page |
|---|---|---|
| 176 | [0,1] | ? (tag 1) |
| 176 | [0,3] | key mapping |
| 176 | [0,4] | turbo |
| 176 | [0,5] | macros |
| 177 | [0] | sticks (2x7 bytes) |
| 178 | [0] | triggers (2x7 bytes) |
| 179 | [0] | motors / other |
| 180 | [0] | ? |
| 181 | [0,0] | macro detail |
| 182 | [0] | ? |
| 183 | [0] | lighting |

### Lighting (read 183, write 55 chunked)
4 zones x 6 bytes: `r, g, b, speed_lo, flags, brightness` where
`flags` bit7 = breathing, bits0-3 = speed bits 8-11 (speed 0..2048).
Write: cmd 55 with `[24, zone bytes…]` split in 15-byte chunks; chunk headers
use e.p()/e.I() (3-bit counter + chunk index). Verified: write + readback.
