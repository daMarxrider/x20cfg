"""High-level access to an EasySMX X20 over its KeyLinker BLE channel."""
import queue
import threading
import time

from .att import ATT
from .protocol import Framer, obfuscate, deobfuscate, parse, MAX_PAYLOAD

WRITE_HANDLE = 0x07
NOTIFY_HANDLE = 0x09
CCCD_HANDLE = 0x0A
RESP = 25          # every reply comes back as cmd 0x19, keyed by seq
LIVE_INPUT = 31    # streamed controller state, ignored


class ProtocolError(Exception):
    pass


class Controller:
    def __init__(self, addr, verbose=False):
        self.verbose = verbose
        self.att = ATT(addr)
        self.framer = Framer()
        self._replies = {}
        self._cv = threading.Condition()
        self.att.on_notify = self._on_notify
        self.att.write(CCCD_HANDLE, b"\x01\x00")

    def close(self):
        self.att.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _on_notify(self, handle, value):
        if handle != NOTIFY_HANDLE:
            return
        f = parse(deobfuscate(value))
        if f is None or f["cmd"] == LIVE_INPUT:
            return
        if self.verbose:
            print("  <-", f["cmd"], hex(f["seq"]), f["payload"].hex(" "))
        if f["cmd"] == RESP:
            with self._cv:
                self._replies[f["seq"]] = f["payload"]
                self._cv.notify_all()

    def _send(self, frame, timeout=2.0, retries=2):
        seq = frame[2]
        for _ in range(retries + 1):
            with self._cv:
                self._replies.pop(seq, None)
            if self.verbose:
                print("  ->", frame.hex(" "))
            self.att.write(WRITE_HANDLE, obfuscate(frame))
            deadline = time.monotonic() + timeout
            with self._cv:
                while seq not in self._replies:
                    left = deadline - time.monotonic()
                    if left <= 0:
                        break
                    self._cv.wait(left)
                if seq in self._replies:
                    return self._replies.pop(seq)
        raise ProtocolError("no reply to cmd %d" % frame[0])

    def request(self, cmd, payload=()):
        return self._send(self.framer.build(cmd, payload))

    def read_paged(self, cmd, prefix=()):
        """Reads whose first reply byte is the total length; later pages are
        fetched by bumping the leading index byte (b1.C(fb, 104) pattern)."""
        first = self.request(cmd, [0, *prefix])
        total, data = first[0], list(first[1:])
        page = 0
        while len(data) < total:
            page += 1
            data += list(self.request(cmd, [page, *prefix]))
        return data[:total]

    def write_chunked(self, cmd, data):
        """Host-protocol write: data split into 15-byte chunks (b1.A1 & co)."""
        for i in range(0, max(len(data), 1), MAX_PAYLOAD):
            self._send(self.framer.build_chunk(cmd, data[i:i + MAX_PAYLOAD], i // MAX_PAYLOAD))

    # --- device info -------------------------------------------------------
    def info(self):
        p = self.request(145)
        c = p[1:]
        return {
            "vid": "%02x%02x" % (c[0], c[1]),
            "pid": "%02x%02x" % (c[2], c[3]),
            "firmware": "%x.%02x" % (c[4], c[5]),
            "model_byte": c[6] if len(c) > 6 else None,
        }

    # --- lighting ------------------------------------------------------------
    def read_lights(self):
        data = self.read_paged(183)
        return [Light.unpack(data[i:i + 6]) for i in range(0, len(data) - 5, 6)]

    def write_lights(self, lights):
        data = [b for light in lights for b in light.pack()]
        self.write_chunked(55, [len(data)] + data)

    # --- button remapping ------------------------------------------------------
    def read_keys(self):
        """Remappable physical keys, in the order the remap table uses."""
        r = self.request(176, [0, 3])
        total, raw = r[0], list(r[2:])
        page = 0
        while len(raw) + 1 < total:
            page += 1
            raw += list(self.request(176, [page, 3]))
        keys = []
        for b in raw:
            if b & 0x80:  # run-length: N consecutive codes ending here
                keys += [keys[-1] + i for i in range(1, b & 0x7F)]
            else:
                keys.append(b)
        return keys

    def read_mapping(self):
        """{physical key: emitted key} for every remappable key."""
        keys = self.read_keys()
        targets = self.read_paged(182)
        targets += [0] * (len(keys) - len(targets))
        return {k: (t or k) for k, t in zip(keys, targets)}

    def write_mapping(self, mapping):
        keys = self.read_keys()
        targets = [0 if mapping.get(k, k) == k else mapping[k] for k in keys]
        self.write_chunked(54, [len(keys)] + targets)


class Light:
    """One lighting zone: colour, brightness and optional breathing."""

    def __init__(self, r, g, b, brightness=255, breathing=False, speed=0):
        self.r, self.g, self.b = r, g, b
        self.brightness = brightness
        self.breathing = breathing
        self.speed = speed  # 0..2048, only meaningful with breathing

    @classmethod
    def unpack(cls, d):
        return cls(d[0], d[1], d[2], d[5], bool(d[4] & 0x80), ((d[4] & 0x0F) << 8) | d[3])

    def pack(self):
        flags = (0x80 if self.breathing else 0) | ((self.speed >> 8) & 0x0F)
        return [self.r, self.g, self.b, self.speed & 0xFF, flags, self.brightness]

    def __repr__(self):
        s = "#%02x%02x%02x brightness=%d" % (self.r, self.g, self.b, self.brightness)
        if self.breathing:
            s += " breathing speed=%d" % self.speed
        return s
