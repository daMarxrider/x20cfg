"""x20cfg: configure EasySMX X20 lighting and button mapping on Linux."""
import argparse
import sys

from . import keys
from .device import Controller, find_address

def parse_color(text):
    t = text.lstrip("#")
    if len(t) != 6:
        raise argparse.ArgumentTypeError("colour must be RRGGBB")
    return tuple(int(t[i:i + 2], 16) for i in (0, 2, 4))


def cmd_info(c, args):
    for k, v in c.info().items():
        print("%-10s %s" % (k, v))


def cmd_light(c, args):
    lights = c.read_lights()
    if args.color is None and args.brightness is None and args.breathing is None and args.speed is None:
        for i, light in enumerate(lights, 1):
            print("zone %d: %r" % (i, light))
        return
    zones = range(len(lights)) if args.zone == "all" else [int(z) - 1 for z in args.zone.split(",")]
    for i in zones:
        light = lights[i]
        if args.color is not None:
            light.r, light.g, light.b = args.color
        if args.brightness is not None:
            light.brightness = args.brightness
        if args.breathing is not None:
            light.breathing = args.breathing
        if args.speed is not None:
            light.speed = args.speed
    c.write_lights(lights)
    for i, light in enumerate(c.read_lights(), 1):
        print("zone %d: %r" % (i, light))


def print_mapping(mapping):
    for src, dst in mapping.items():
        print("%-6s -> %s" % (keys.name(src), keys.name(dst)))


def cmd_map(c, args):
    mapping = c.read_mapping()
    if args.reset:
        mapping = {k: k for k in mapping}
    for spec in args.assign:
        src, _, dst = spec.partition("=")
        if not dst:
            sys.exit("expected KEY=TARGET, got %r" % spec)
        s, d = keys.code(src), keys.code(dst)
        if s not in mapping:
            sys.exit("%s is not remappable on this controller" % src)
        mapping[s] = d
    if args.reset or args.assign:
        c.write_mapping(mapping)
        mapping = c.read_mapping()
    print_mapping(mapping)


def main(argv=None):
    p = argparse.ArgumentParser(prog="x20cfg", description=__doc__)
    p.add_argument("--addr", help="BLE address (default: derived from the paired controller)")
    p.add_argument("-v", "--verbose", action="store_true", help="dump protocol frames")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("gui", help="open the graphical editor")
    sub.add_parser("info", help="show device info").set_defaults(func=cmd_info)

    lp = sub.add_parser("light", help="show or change RGB lighting")
    lp.add_argument("-z", "--zone", default="all", help="zone number(s), e.g. 1 or 1,3 (default: all)")
    lp.add_argument("-c", "--color", type=parse_color, help="colour as RRGGBB")
    lp.add_argument("-b", "--brightness", type=int, choices=range(256), metavar="0-255")
    lp.add_argument("--breathing", action=argparse.BooleanOptionalAction, default=None)
    lp.add_argument("--speed", type=int, choices=range(2049), metavar="0-2048", help="breathing speed")
    lp.set_defaults(func=cmd_light)

    mp = sub.add_parser("map", help="show or change button mapping")
    mp.add_argument("assign", nargs="*", help="KEY=TARGET, e.g. BACK1=A BACK2=LB")
    mp.add_argument("--reset", action="store_true", help="restore every key to itself first")
    mp.set_defaults(func=cmd_map)

    args = p.parse_args(argv)
    if args.cmd == "gui":
        from .gui import run
        return run(args.addr)
    try:
        addr = args.addr or find_address()
    except LookupError as e:
        sys.exit(str(e))
    with Controller(addr, verbose=args.verbose) as c:
        args.func(c, args)


if __name__ == "__main__":
    main()
