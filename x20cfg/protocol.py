"""KeyLinker frame codec (from com.pulsenet.inputset util/e.java).

Plain frame: [cmd, total_len, seq, rand, payload..., crc8]
On the wire every frame is additionally obfuscated (e.h() / e.g()).
"""
import os

CRC_TABLE = bytes([0, 121, 242, 139, 51, 74, 193, 184, 102, 31, 148, 237, 85, 44, 167, 222, 204, 181, 62, 71, 255, 134, 13, 116, 170, 211, 88, 33, 153, 224, 107, 18, 79, 54, 189, 196, 124, 5, 142, 247, 41, 80, 219, 162, 26, 99, 232, 145, 131, 250, 113, 8, 176, 201, 66, 59, 229, 156, 23, 110, 214, 175, 36, 93, 158, 231, 108, 21, 173, 212, 95, 38, 248, 129, 10, 115, 203, 178, 57, 64, 82, 43, 160, 217, 97, 24, 147, 234, 52, 77, 198, 191, 7, 126, 245, 140, 209, 168, 35, 90, 226, 155, 16, 105, 183, 206, 69, 60, 132, 253, 118, 15, 29, 100, 239, 150, 46, 87, 220, 165, 123, 2, 137, 240, 72, 49, 186, 195, 235, 146, 25, 96, 216, 161, 42, 83, 141, 244, 127, 6, 190, 199, 76, 53, 39, 94, 213, 172, 20, 109, 230, 159, 65, 56, 179, 202, 114, 11, 128, 249, 164, 221, 86, 47, 151, 238, 101, 28, 194, 187, 48, 73, 241, 136, 3, 122, 104, 17, 154, 227, 91, 34, 169, 208, 14, 119, 252, 133, 61, 68, 207, 182, 117, 12, 135, 254, 70, 63, 180, 205, 19, 106, 225, 152, 32, 89, 210, 171, 185, 192, 75, 50, 138, 243, 120, 1, 223, 166, 45, 84, 236, 149, 30, 103, 58, 67, 200, 177, 9, 112, 251, 130, 92, 37, 174, 215, 111, 22, 157, 228, 246, 143, 4, 125, 197, 188, 55, 78, 144, 233, 98, 27, 163, 218, 81, 40])
KEY_G = [51, 99, 157, 121, 242, 219, 162, 26, 170, 33, 139, 232, 116, 211, 88]
KEY_H = [161, 82, 213, 163, 245, 137, 246, 143, 240, 157, 72, 147, 234, 52, 49, 186, 195, 77, 198, 235,
         73, 96, 216, 163, 218, 42, 83, 141, 244, 97, 24, 191, 174, 215, 111, 81, 228, 160, 217, 146]

MAX_PAYLOAD = 15  # frames are at most 20 bytes


def crc8(data):
    c = 0
    for b in data:
        c = CRC_TABLE[c ^ b]
    return c


def obfuscate(p):
    """e.h(): plain frame -> wire bytes."""
    n = len(p)
    o = bytearray(n)
    s = p[2] + p[3]
    o[0] = p[0] ^ ((s - 154) & 0xFF)
    o[1] = p[1] ^ ((s + 155) & 0xFF)
    o[2] = ((p[2] - 173) & 0xFF) ^ p[3]
    o[3] = ((p[3] + 191) & 0xFF) ^ 219
    for i in range(4, n - 1):
        o[i] = p[i] ^ ((s - KEY_G[i - 4]) & 0xFF)
    o[n - 1] = p[n - 1]
    off = (o[3] & 2) * 10
    return bytes(o[i] ^ KEY_H[off + i] for i in range(n))


def deobfuscate(w):
    """e.g(): wire bytes -> plain frame."""
    n = len(w)
    off = 20 if (w[3] ^ KEY_H[3]) & 2 else 0
    o = bytearray(w[i] ^ KEY_H[off + i] for i in range(n))
    o[3] = ((o[3] ^ 219) - 191) & 0xFF
    o[2] = ((o[2] ^ o[3]) + 173) & 0xFF
    s = o[2] + o[3]
    o[1] ^= (s + 155) & 0xFF
    o[0] ^= (s - 154) & 0xFF
    for i in range(4, n - 1):
        o[i] ^= (s - KEY_G[i - 4]) & 0xFF
    return bytes(o)


class Framer:
    def __init__(self):
        self._seq = 0

    def next_seq(self):
        """e.K(): alternates the high bit on every frame."""
        self._seq += 1
        i = self._seq
        return (i % 128) + 128 if i % 2 == 0 else i % 128

    def chunk_header(self, n, chunk):
        """e.p() / e.I(): header bytes for chunked "host" writes (cmd 49..55).

        byte1 = 3-bit down-counter | total length, byte2 = toggle | chunk index | 3-bit counter.
        """
        self._down = (getattr(self, "_down", 8) or 8) - 1
        len_byte = ((self._down % 8) << 5) | (n + 5)
        self._up = getattr(self, "_up", 0) + 1
        seq = ((self._up % 2) << 7) | ((chunk & 0xF) << 3) | (self._up % 8)
        return len_byte, seq

    def build_chunk(self, cmd, payload, chunk):
        len_byte, seq = self.chunk_header(len(payload), chunk)
        return self.build(cmd, payload, seq=seq, len_byte=len_byte)

    def build(self, cmd, payload=(), seq=None, len_byte=None):
        payload = bytes(payload)
        assert len(payload) <= MAX_PAYLOAD
        if seq is None:
            seq = self.next_seq()
        if len_byte is None:
            len_byte = len(payload) + 5
        body = bytes([cmd, len_byte, seq, os.urandom(1)[0]]) + payload
        return body + bytes([crc8(body)])


def parse(plain):
    """Return dict for a plain frame, or None if the CRC is wrong."""
    if len(plain) < 5 or crc8(plain[:-1]) != plain[-1]:
        return None
    return {"cmd": plain[0], "len": plain[1], "seq": plain[2], "payload": plain[4:-1]}
