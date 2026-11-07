"""KeyLinker key codes (from the app's ic_*_code_0xNN_* icon table)."""

NAMES = {
    1: "A", 2: "B", 3: "X", 4: "Y", 5: "LB", 6: "RB", 7: "LT", 8: "RT",
    9: "SELECT", 10: "START", 11: "L3", 12: "R3",
    13: "DOWN", 14: "UP", 15: "RIGHT", 16: "LEFT", 17: "HOME",
    93: "BACK1", 94: "BACK2",
}
CODES = {v: k for k, v in NAMES.items()}
CODES.update({"BACK": 9, "VIEW": 9, "MENU": 10, "L1": 5, "R1": 6, "L2": 7, "R2": 8})


def name(code):
    return NAMES.get(code, str(code))


def code(text):
    t = text.strip().upper()
    if t in CODES:
        return CODES[t]
    if t.isdigit():
        return int(t)
    raise ValueError("unknown key %r (known: %s)" % (text, ", ".join(NAMES.values())))
