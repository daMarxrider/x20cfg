# x20cfg

Configure an **EasySMX X20** controller from Linux — RGB lighting and back-button /
button remapping — speaking the same BLE protocol as the Android *KeyLinker* app.
No dependencies, no root: it talks ATT over a raw kernel L2CAP socket.

## GUI

`python -m x20cfg gui` (needs GTK4 + libadwaita + PyGObject). Click a button on the
controller drawing to remap it, or a light zone to change colour/brightness/breathing,
then press **Apply**. Pressed buttons are highlighted live.

## Usage

The controller just needs to be connected normally over Bluetooth (Xbox mode). The
config channel's address (`98:B6:ED:…`) is derived from the paired gamepad;
override with `--addr` or `X20_ADDR`.

```sh
python -m x20cfg info
python -m x20cfg light                              # show all zones
python -m x20cfg light -c ff00ff                    # all zones magenta
python -m x20cfg light -z 1 -c 00ff00 -b 128        # zone 1 green, half brightness
python -m x20cfg light -z 4 --breathing --speed 500
python -m x20cfg map                                # show mapping
python -m x20cfg map BACK1=A BACK2=B                # remap back buttons
python -m x20cfg map --reset                        # restore defaults
```

Or `pip install --user .` and use `x20cfg ...`. `-v` dumps protocol frames.

Key names: A B X Y LB RB LT RT SELECT START L3 R3 UP DOWN LEFT RIGHT HOME BACK1 BACK2
(or raw KeyLinker codes).

See `NOTES.md` for the reverse-engineered protocol.
