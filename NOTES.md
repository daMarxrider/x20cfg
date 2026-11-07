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
