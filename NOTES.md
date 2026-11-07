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
