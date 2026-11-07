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
