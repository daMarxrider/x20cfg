"""GTK4 / libadwaita GUI: click a button or light zone on the controller to edit it."""
import math
import os
import struct
import sys
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Adw, Gdk, GLib, Gtk, Pango, PangoCairo  # noqa: E402

from . import keys  # noqa: E402
from .device import Controller, Light, find_address  # noqa: E402

# Canvas design space; everything is scaled to fit the widget.
W, H = 1000, 720
ACCENT = (0.21, 0.52, 0.89)


class Shape:
    def __init__(self, kind, ident, geom, label=""):
        self.kind = kind      # "key" or "zone"
        self.ident = ident    # key code or zone index
        self.geom = geom      # ("circle", cx, cy, r) | ("rect", x, y, w, h) | ("ring", cx, cy, r, width)
        self.label = label

    def contains(self, x, y):
        g = self.geom
        if g[0] == "circle":
            return math.hypot(x - g[1], y - g[2]) <= g[3]
        if g[0] == "ring":
            return abs(math.hypot(x - g[1], y - g[2]) - g[3]) <= g[4]
        return g[1] <= x <= g[1] + g[3] and g[2] <= y <= g[2] + g[4]

    def center(self):
        g = self.geom
        if g[0] == "rect":
            return g[1] + g[3] / 2, g[2] + g[4] / 2
        return g[1], g[2]


def key(code, geom, label=None):
    return Shape("key", code, geom, label or keys.name(code))


# Order matters: zones are listed first so buttons drawn on top win hit-tests.
SHAPES = [
    Shape("zone", 0, ("ring", 300, 250, 64, 9), "1"),
    Shape("zone", 1, ("ring", 620, 390, 60, 9), "2"),
    Shape("zone", 2, ("rect", 98, 330, 20, 170), "3"),
    Shape("zone", 3, ("rect", 882, 330, 20, 170), "4"),
    key(7, ("rect", 215, 34, 150, 40), "LT"),
    key(8, ("rect", 635, 34, 150, 40), "RT"),
    key(5, ("rect", 222, 84, 150, 28), "LB"),
    key(6, ("rect", 628, 84, 150, 28), "RB"),
    key(11, ("circle", 300, 250, 48), "L3"),
    key(12, ("circle", 620, 390, 44), "R3"),
    key(14, ("rect", 365, 335, 30, 42), "▲"),
    key(13, ("rect", 365, 405, 30, 42), "▼"),
    key(16, ("rect", 323, 376, 42, 30), "◀"),
    key(15, ("rect", 395, 376, 42, 30), "▶"),
    key(4, ("circle", 700, 192, 26)),
    key(3, ("circle", 643, 250, 26)),
    key(2, ("circle", 757, 250, 26)),
    key(1, ("circle", 700, 308, 26)),
    key(9, ("circle", 440, 250, 15), "⧉"),
    key(10, ("circle", 560, 250, 15), "≡"),
    key(17, ("circle", 500, 175, 24), "⌂"),
    key(93, ("rect", 330, 650, 140, 40), "BACK1"),
    key(94, ("rect", 530, 650, 140, 40), "BACK2"),
]
LETTER_COLORS = {1: (0.42, 0.78, 0.35), 2: (0.90, 0.33, 0.30), 3: (0.30, 0.55, 0.95), 4: (0.95, 0.80, 0.25)}

# evdev codes of the Xbox-mode HID gamepad -> KeyLinker key codes
EV_KEYS = {0x130: 1, 0x131: 2, 0x133: 3, 0x134: 4, 0x136: 5, 0x137: 6,
           0x13A: 9, 0x13B: 10, 0x13C: 17, 0x13D: 11, 0x13E: 12}
ABS_BRAKE, ABS_GAS, ABS_HAT0X, ABS_HAT0Y = 0x0A, 0x09, 0x10, 0x11


def body_path(cr):
    cr.move_to(500, 125)
    cr.curve_to(420, 118, 330, 100, 250, 110)
    cr.curve_to(160, 120, 120, 170, 100, 260)
    cr.curve_to(70, 380, 60, 520, 110, 580)
    cr.curve_to(150, 630, 230, 620, 260, 560)
    cr.curve_to(300, 480, 360, 440, 500, 440)
    cr.curve_to(640, 440, 700, 480, 740, 560)
    cr.curve_to(770, 620, 850, 630, 890, 580)
    cr.curve_to(940, 520, 930, 380, 900, 260)
    cr.curve_to(880, 170, 840, 120, 750, 110)
    cr.curve_to(670, 100, 580, 118, 500, 125)
    cr.close_path()


def rounded_rect(cr, x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def find_event_device():
    for d in sorted(os.listdir("/sys/class/input")):
        if not d.startswith("event"):
            continue
        try:
            with open("/sys/class/input/%s/device/uniq" % d) as f:
                if f.read().strip().lower().startswith("98:b6:"):
                    return "/dev/input/" + d
        except OSError:
            pass
    return None


class LiveInput(threading.Thread):
    """Highlights buttons as the gamepad reports them (i.e. after remapping)."""

    def __init__(self, on_change):
        super().__init__(daemon=True)
        self.on_change = on_change
        self.pressed = set()

    def run(self):
        fmt = "llHHi"
        size = struct.calcsize(fmt)
        while True:
            path = find_event_device()
            if not path:
                time.sleep(2)
                continue
            try:
                with open(path, "rb") as f:
                    while True:
                        _, _, typ, code, value = struct.unpack(fmt, f.read(size))
                        if self._apply(typ, code, value):
                            GLib.idle_add(self.on_change)
            except OSError:
                self.pressed.clear()
                GLib.idle_add(self.on_change)
                time.sleep(2)

    def _set(self, k, on):
        if on == (k in self.pressed):
            return False
        (self.pressed.add if on else self.pressed.discard)(k)
        return True

    def _apply(self, typ, code, value):
        if typ == 1 and code in EV_KEYS:
            return self._set(EV_KEYS[code], value != 0)
        if typ == 3:
            if code == ABS_BRAKE:
                return self._set(7, value > 100)
            if code == ABS_GAS:
                return self._set(8, value > 100)
            if code == ABS_HAT0X:
                return self._set(16, value < 0) | self._set(15, value > 0)
            if code == ABS_HAT0Y:
                return self._set(14, value < 0) | self._set(13, value > 0)
        return False


class Window(Adw.ApplicationWindow):
    def __init__(self, app, addr):
        super().__init__(application=app, title="X20 Config", default_width=1180, default_height=720)
        self.addr = addr
        self.busy = threading.Lock()
        self.lights = []
        self.mapping = {}
        self.info = {}
        self.dirty = set()        # {"lights", "mapping"}
        self.selected = None
        self.hover = None

        self.title = Adw.WindowTitle(title="EasySMX X20", subtitle="Connecting…")
        header = Adw.HeaderBar(title_widget=self.title)
        self.reload_btn = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Reload from controller")
        self.reload_btn.connect("clicked", lambda *_: self.load())
        header.pack_start(self.reload_btn)
        self.apply_btn = Gtk.Button(label="Apply", sensitive=False)
        self.apply_btn.add_css_class("suggested-action")
        self.apply_btn.connect("clicked", lambda *_: self.apply())
        header.pack_end(self.apply_btn)
        reset_btn = Gtk.Button(icon_name="edit-undo-symbolic", tooltip_text="Reset all buttons to default")
        reset_btn.connect("clicked", self.on_reset_mapping)
        header.pack_end(reset_btn)

        self.canvas = Gtk.DrawingArea(hexpand=True, vexpand=True)
        self.canvas.set_draw_func(self.draw)
        click = Gtk.GestureClick()
        click.connect("pressed", self.on_click)
        self.canvas.add_controller(click)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self.on_motion)
        self.canvas.add_controller(motion)
        self.canvas.add_tick_callback(self.on_tick)

        self.panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18,
                             margin_top=18, margin_bottom=18, margin_start=18, margin_end=18)
        scroller = Gtk.ScrolledWindow(child=self.panel, width_request=400, hexpand=False,
                                      hscrollbar_policy=Gtk.PolicyType.NEVER)

        content = Gtk.Box()
        content.append(self.canvas)
        content.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        content.append(scroller)

        self.toasts = Adw.ToastOverlay(child=content)
        view = Adw.ToolbarView(content=self.toasts)
        view.add_top_bar(header)
        self.set_content(view)

        self.live = LiveInput(self.canvas.queue_draw)
        self.live.start()
        self.rebuild_panel()
        self.load()

    # --- device I/O (worker thread, one short BLE session per action) -------
    def run_bg(self, label, work, done):
        if not self.busy.acquire(blocking=False):
            self.toast("Still busy, try again in a moment")
            return
        self.title.set_subtitle(label)
        self.reload_btn.set_sensitive(False)
        self.apply_btn.set_sensitive(False)

        def worker():
            try:
                addr = self.addr or find_address()
                with Controller(addr) as c:
                    result = work(c)
                GLib.idle_add(finish, None, result)
            except Exception as e:  # report anything the device/socket throws
                GLib.idle_add(finish, e, None)

        def finish(err, result):
            self.busy.release()
            self.reload_btn.set_sensitive(True)
            if err:
                self.title.set_subtitle("Not connected")
                self.toast("Error: %s" % err)
            else:
                done(result)
            self.update_apply()
            return False

        threading.Thread(target=worker, daemon=True).start()

    def load(self):
        def work(c):
            return c.info(), c.read_lights(), c.read_mapping()

        def done(res):
            self.info, self.lights, self.mapping = res
            self.dirty.clear()
            self.title.set_subtitle("Firmware %s" % self.info["firmware"])
            self.rebuild_panel()
            self.canvas.queue_draw()

        self.run_bg("Reading settings…", work, done)

    def apply(self):
        dirty, lights, mapping = set(self.dirty), self.lights, dict(self.mapping)

        def work(c):
            if "lights" in dirty:
                c.write_lights(lights)
            if "mapping" in dirty:
                c.write_mapping(mapping)
            return c.read_lights(), c.read_mapping()

        def done(res):
            self.lights, self.mapping = res
            self.dirty.clear()
            self.title.set_subtitle("Firmware %s" % self.info.get("firmware", "?"))
            self.rebuild_panel()
            self.canvas.queue_draw()
            self.toast("Saved to controller")

        self.run_bg("Writing settings…", work, done)

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=3))

    def mark(self, what):
        self.dirty.add(what)
        self.update_apply()
        self.canvas.queue_draw()

    def update_apply(self):
        self.apply_btn.set_sensitive(bool(self.dirty) and not self.busy.locked())

    def on_reset_mapping(self, *_):
        if not self.mapping:
            return
        self.mapping = {k: k for k in self.mapping}
        self.mark("mapping")
        self.rebuild_panel()

    # --- canvas ---------------------------------------------------------------
    def transform(self, w, h):
        s = min(w / W, h / H) * 0.95
        return s, (w - W * s) / 2, (h - H * s) / 2

    def to_design(self, x, y):
        s, ox, oy = self.transform(self.canvas.get_width(), self.canvas.get_height())
        return (x - ox) / s, (y - oy) / s

    def hit(self, x, y):
        dx, dy = self.to_design(x, y)
        for shape in reversed(SHAPES):
            if shape.contains(dx, dy):
                return shape
        return None

    def on_click(self, _gesture, _n, x, y):
        shape = self.hit(x, y)
        self.selected = (shape.kind, shape.ident) if shape else None
        self.rebuild_panel()
        self.canvas.queue_draw()

    def on_motion(self, _ctrl, x, y):
        shape = self.hit(x, y)
        hover = (shape.kind, shape.ident) if shape else None
        if hover != self.hover:
            self.hover = hover
            self.canvas.set_cursor(Gdk.Cursor.new_from_name("pointer" if shape else "default"))
            self.canvas.queue_draw()

    def on_tick(self, *_):
        if any(light.breathing for light in self.lights):
            self.canvas.queue_draw()
        return GLib.SOURCE_CONTINUE

    def zone_rgb(self, light):
        k = light.brightness / 255
        if light.breathing:
            period = 0.6 + light.speed / 400
            k *= 0.2 + 0.8 * (0.5 + 0.5 * math.sin(time.monotonic() * 2 * math.pi / period))
        return light.r / 255 * k, light.g / 255 * k, light.b / 255 * k

    def draw(self, _area, cr, w, h):
        s, ox, oy = self.transform(w, h)
        cr.translate(ox, oy)
        cr.scale(s, s)

        body_path(cr)
        cr.set_source_rgb(0.16, 0.17, 0.19)
        cr.fill_preserve()
        cr.set_source_rgb(0.32, 0.33, 0.36)
        cr.set_line_width(3)
        cr.stroke()

        cr.set_source_rgb(0.5, 0.5, 0.55)
        self.text(cr, 500, 630, "REAR", 15)

        for shape in SHAPES:
            ident = (shape.kind, shape.ident)
            if shape.kind == "zone":
                self.draw_zone(cr, shape)
            else:
                self.draw_key(cr, shape)
            if ident == self.selected or ident == self.hover:
                cr.set_source_rgba(*ACCENT, 1.0 if ident == self.selected else 0.5)
                cr.set_line_width(4)
                self.outline(cr, shape, pad=5)
                cr.stroke()

    def outline(self, cr, shape, pad=0):
        g = shape.geom
        if g[0] == "circle":
            cr.new_sub_path()
            cr.arc(g[1], g[2], g[3] + pad, 0, 2 * math.pi)
        elif g[0] == "ring":
            cr.new_sub_path()
            cr.arc(g[1], g[2], g[3] + g[4] + pad, 0, 2 * math.pi)
        else:
            rounded_rect(cr, g[1] - pad, g[2] - pad, g[3] + 2 * pad, g[4] + 2 * pad, 10 + pad)

    def draw_zone(self, cr, shape):
        if shape.ident >= len(self.lights):
            rgb = (0.25, 0.25, 0.28)
        else:
            rgb = self.zone_rgb(self.lights[shape.ident])
        g = shape.geom
        cr.set_source_rgb(*rgb)
        if g[0] == "ring":
            cr.new_sub_path()
            cr.arc(g[1], g[2], g[3], 0, 2 * math.pi)
            cr.set_line_width(g[4] * 2)
            cr.stroke()
        else:
            rounded_rect(cr, *g[1:], 10)
            cr.fill()

    def draw_key(self, cr, shape):
        code = shape.ident
        pressed = code in self.live.pressed
        cr.set_source_rgb(*((0.62, 0.64, 0.70) if pressed else (0.27, 0.28, 0.31)))
        self.outline(cr, shape)
        cr.fill()

        cx, cy = shape.center()
        cr.set_source_rgb(*LETTER_COLORS.get(code, (0.92, 0.92, 0.94)))
        self.text(cr, cx, cy, shape.label, 20 if len(shape.label) <= 2 else 15)

        target = self.mapping.get(code, code)
        if target != code:
            cr.set_source_rgb(*ACCENT)
            cr.set_line_width(3)
            self.outline(cr, shape, pad=1)
            cr.stroke()
            badge = "→ " + keys.name(target)
            tw, _ = self.text_size(cr, badge, 14)
            bx, by = cx, cy + self.radius(shape) + 16
            rounded_rect(cr, bx - tw / 2 - 7, by - 11, tw + 14, 22, 8)
            cr.fill()
            cr.set_source_rgb(1, 1, 1)
            self.text(cr, bx, by, badge, 14)

    @staticmethod
    def radius(shape):
        g = shape.geom
        return g[3] if g[0] == "circle" else g[4] / 2

    @staticmethod
    def layout(cr, s, size):
        layout = PangoCairo.create_layout(cr)
        font = Pango.FontDescription.from_string("Sans Bold")
        font.set_absolute_size(size * Pango.SCALE)
        layout.set_font_description(font)
        layout.set_text(s, -1)
        return layout

    def text_size(self, cr, s, size):
        _, logical = self.layout(cr, s, size).get_pixel_extents()
        return logical.width, logical.height

    def text(self, cr, x, y, s, size):
        layout = self.layout(cr, s, size)
        _, logical = layout.get_pixel_extents()
        cr.move_to(x - logical.width / 2, y - logical.height / 2)
        PangoCairo.show_layout(cr, layout)

    # --- side panel -----------------------------------------------------------
    def rebuild_panel(self):
        while (child := self.panel.get_first_child()) is not None:
            self.panel.remove(child)
        if self.selected is None:
            self.panel_overview()
        elif self.selected[0] == "key":
            self.panel_key(self.selected[1])
        else:
            self.panel_zone(self.selected[1])

    def panel_overview(self):
        group = Adw.PreferencesGroup(
            title="Controller",
            description="Click a button to remap it, or a light zone to change its colour. "
                        "Pressed buttons light up live (showing what the controller sends).")
        for k, v in self.info.items():
            group.add(Adw.ActionRow(title=k.replace("_", " ").title(), subtitle=str(v)))
        self.panel.append(group)
        if self.lights:
            lg = Adw.PreferencesGroup(title="All light zones")
            self.light_rows(lg, list(range(len(self.lights))))
            self.panel.append(lg)

    def panel_key(self, code):
        group = Adw.PreferencesGroup(title="Button %s" % keys.name(code))
        self.panel.append(group)
        if code not in self.mapping:
            group.set_description("This button can't be remapped on the X20.")
            return
        targets = list(self.mapping)
        row = Adw.ComboRow(title="Sends", model=Gtk.StringList.new([keys.name(t) for t in targets]))
        current = self.mapping[code]
        if current in targets:
            row.set_selected(targets.index(current))

        def changed(r, _pspec):
            self.mapping[code] = targets[r.get_selected()]
            self.mark("mapping")

        row.connect("notify::selected", changed)
        group.add(row)

        reset = Gtk.Button(label="Reset to %s" % keys.name(code), halign=Gtk.Align.START)
        reset.add_css_class("pill")
        reset.connect("clicked", lambda *_: row.set_selected(targets.index(code)))
        self.panel.append(reset)

    def panel_zone(self, index):
        group = Adw.PreferencesGroup(title="Light zone %d" % (index + 1),
                                     description="Zone positions on the drawing are not confirmed yet.")
        self.panel.append(group)
        if index >= len(self.lights):
            group.set_description("Not loaded yet.")
            return
        self.light_rows(group, [index])

    def light_rows(self, group, zones):
        first = self.lights[zones[0]]

        def update(fn):
            for z in zones:
                fn(self.lights[z])
            self.mark("lights")

        color_btn = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False), valign=Gtk.Align.CENTER)
        rgba = Gdk.RGBA()
        rgba.red, rgba.green, rgba.blue, rgba.alpha = first.r / 255, first.g / 255, first.b / 255, 1
        color_btn.set_rgba(rgba)

        def on_color(btn, _pspec):
            c = btn.get_rgba()
            rgb = [round(v * 255) for v in (c.red, c.green, c.blue)]

            def setc(light):
                light.r, light.g, light.b = rgb
            update(setc)

        color_btn.connect("notify::rgba", on_color)
        row = Adw.ActionRow(title="Colour")
        row.add_suffix(color_btn)
        row.set_activatable_widget(color_btn)
        group.add(row)

        group.add(self.scale_row("Brightness", 0, 255, first.brightness,
                                 lambda v: update(lambda light: setattr(light, "brightness", v))))

        speed_row = self.scale_row("Breathing speed", 0, 2048, first.speed,
                                   lambda v: update(lambda light: setattr(light, "speed", v)))
        speed_row.set_sensitive(first.breathing)
        breathe = Adw.SwitchRow(title="Breathing", active=first.breathing)

        def on_breathe(r, _pspec):
            update(lambda light: setattr(light, "breathing", r.get_active()))
            speed_row.set_sensitive(r.get_active())

        breathe.connect("notify::active", on_breathe)
        group.add(breathe)
        group.add(speed_row)

    @staticmethod
    def scale_row(title, lo, hi, value, on_change):
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, 1)
        scale.set_value(value)
        scale.set_hexpand(True)
        scale.set_size_request(170, -1)
        scale.set_draw_value(True)
        scale.set_value_pos(Gtk.PositionType.RIGHT)
        scale.connect("value-changed", lambda s: on_change(int(s.get_value())))
        row = Adw.ActionRow(title=title)
        row.add_suffix(scale)
        return row


def run(addr=None):
    app = Adw.Application(application_id="io.github.damarxrider.x20cfg")
    app.connect("activate", lambda a: Window(a, addr).present())
    return app.run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(run())
