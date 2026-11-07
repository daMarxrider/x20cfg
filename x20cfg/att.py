"""Minimal BLE ATT client over a raw kernel L2CAP socket (no bluetoothd/bleak)."""
import socket
import struct
import threading
import queue
import uuid as _uuid

ATT_CID = 4
BDADDR_LE_PUBLIC = 1
BASE_UUID = "-0000-1000-8000-00805f9b34fb"


def _uuid_from_bytes(b):
    if len(b) == 2:
        return "%08x" % struct.unpack("<H", b)[0] + BASE_UUID
    return str(_uuid.UUID(bytes=b[::-1]))


class ATTError(Exception):
    pass


class ATT:
    def __init__(self, addr, timeout=10):
        self.sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, socket.BTPROTO_L2CAP)
        self.sock.bind(("00:00:00:00:00:00", 0, ATT_CID, BDADDR_LE_PUBLIC))
        self.sock.settimeout(timeout)
        self.sock.connect((addr, 0, ATT_CID, BDADDR_LE_PUBLIC))
        self.sock.settimeout(None)
        self.timeout = timeout
        self.responses = queue.Queue()
        self.on_notify = None
        self.mtu = 23
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        rsp = self._request(bytes([0x02]) + struct.pack("<H", 247), 0x03)
        self.mtu = min(247, struct.unpack("<H", rsp[1:3])[0])

    def close(self):
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()

    def _read_loop(self):
        while True:
            try:
                pdu = self.sock.recv(1024)
            except OSError:
                self.responses.put(None)
                return
            if not pdu:
                self.responses.put(None)
                return
            op = pdu[0]
            if op in (0x1B, 0x1D):  # notification / indication
                handle = struct.unpack("<H", pdu[1:3])[0]
                if op == 0x1D:
                    self.sock.send(bytes([0x1E]))
                if self.on_notify:
                    self.on_notify(handle, pdu[3:])
            else:
                self.responses.put(pdu)

    def _request(self, pdu, expect):
        self.sock.send(pdu)
        rsp = self.responses.get(timeout=self.timeout)
        if rsp is None:
            raise ATTError("disconnected")
        if rsp[0] == 0x01:
            raise ATTError("error opcode=%02x handle=%04x code=%02x" % (rsp[1], *struct.unpack("<H", rsp[2:4]), rsp[4]))
        if rsp[0] != expect:
            raise ATTError("unexpected response %s" % rsp.hex())
        return rsp

    def _iter_type(self, op, start, end, type16):
        """Read By (Group) Type iteration; yields (handle, end_or_None, value)."""
        while start <= end:
            try:
                rsp = self._request(bytes([op]) + struct.pack("<HHH", start, end, type16), op + 1)
            except ATTError as e:
                if "code=0a" in str(e):  # attribute not found
                    return
                raise
            ln = rsp[1]
            last = start
            for i in range(2, len(rsp), ln):
                item = rsp[i:i + ln]
                if op == 0x10:
                    h, e = struct.unpack("<HH", item[:4])
                    yield h, e, item[4:]
                    last = e
                else:
                    h = struct.unpack("<H", item[:2])[0]
                    yield h, None, item[2:]
                    last = h
            if last >= 0xFFFF:
                return
            start = last + 1

    def services(self):
        return [(h, e, _uuid_from_bytes(v)) for h, e, v in self._iter_type(0x10, 1, 0xFFFF, 0x2800)]

    def characteristics(self, start, end):
        out = []
        for h, _, v in self._iter_type(0x08, start, end, 0x2803):
            props, vh = v[0], struct.unpack("<H", v[1:3])[0]
            out.append((h, props, vh, _uuid_from_bytes(v[3:])))
        return out

    def read(self, handle):
        return self._request(bytes([0x0A]) + struct.pack("<H", handle), 0x0B)[1:]

    def write(self, handle, data, response=True):
        pdu = struct.pack("<H", handle) + bytes(data)
        if response:
            self._request(bytes([0x12]) + pdu, 0x13)
        else:
            self.sock.send(bytes([0x52]) + pdu)
