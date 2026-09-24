"""Rounded, anti-aliased controls for plain tkinter/ttk.

Tk cannot draw smooth rounded shapes, so the shapes are rendered into images here
(supersampled signed-distance shapes, blended onto the card colour) and used as
stretchable ttk image elements. The widgets stay real ttk widgets, so keyboard,
mouse wheel and dropdown behaviour are unchanged.
"""
import math
import tkinter as tk

_IMAGES = []  # PhotoImages must stay referenced or Tk discards them


# --- Shape rendering ---------------------------------------------------------

def _rgb(color):
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def _render(width, height, shapes, bg, samples=3):
    """shapes: [(sdf, colour)] painted in order; sdf(x, y) <= 0 means inside."""
    bg_rgb = _rgb(bg)
    layers = [(sdf, _rgb(color)) for sdf, color in shapes]
    offsets = [(i + 0.5) / samples for i in range(samples)]
    count = samples * samples
    rows = []
    for y in range(height):
        row = []
        for x in range(width):
            r = g = b = 0
            for oy in offsets:
                for ox in offsets:
                    px, py = x + ox, y + oy
                    c = bg_rgb
                    for sdf, color in layers:
                        if sdf(px, py) <= 0:
                            c = color
                    r += c[0]
                    g += c[1]
                    b += c[2]
            row.append("#%02x%02x%02x" % (r // count, g // count, b // count))
        rows.append("{" + " ".join(row) + "}")
    image = tk.PhotoImage(width=width, height=height)
    image.put(" ".join(rows))
    _IMAGES.append(image)
    return image


def _rounded_rect(x0, y0, x1, y1, radius, corners=(True, True, True, True)):
    """corners: rounded (top-left, top-right, bottom-right, bottom-left)."""
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    half_w, half_h = (x1 - x0) / 2, (y1 - y0) / 2

    def sdf(px, py):
        top, left = py < cy, px < cx
        index = (0 if left else 1) if top else (3 if left else 2)
        r = radius if corners[index] else 0
        qx = abs(px - cx) - (half_w - r)
        qy = abs(py - cy) - (half_h - r)
        return math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - r
    return sdf


def _circle(cx, cy, radius):
    return lambda px, py: math.hypot(px - cx, py - cy) - radius


def _segment(ax, ay, bx, by, half_thickness):
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy

    def sdf(px, py):
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
        return math.hypot(px - ax - t * dx, py - ay - t * dy) - half_thickness
    return sdf


def box_image(width, height, radius, fill, border, border_width, bg, corners=(True,) * 4):
    inner_radius = max(radius - border_width, 0)
    return _render(width, height, [
        (_rounded_rect(0, 0, width, height, radius, corners), border),
        (_rounded_rect(border_width, border_width, width - border_width,
                       height - border_width, inner_radius, corners), fill),
    ], bg)


def chevron_image(width, height, direction, color, bg, thickness):
    """A small V-shaped arrow pointing "up" or "down"."""
    left, mid, right = width * 0.32, width * 0.5, width * 0.68
    top, bottom = height * 0.36, height * 0.64
    if direction == "up":
        top, bottom = bottom, top
    half = thickness / 2
    return _render(width, height, [
        (_segment(left, top, mid, bottom, half), color),
        (_segment(mid, bottom, right, top, half), color),
    ], bg)


# --- ttk styles ----------------------------------------------------------------

class Palette:
    def __init__(self, colors):
        self.card = colors["card"]
        self.text = colors["text"]
        self.muted = colors["muted"]
        self.accent = colors["accent"]
        self.accent_dark = colors["accent_dark"]
        self.field_border = "#c9d1dd"
        self.field_hover = "#9fb0c8"
        self.disabled_fill = "#f4f6f9"
        self.disabled_border = "#e3e7ee"
        self.disabled_text = "#a3abb8"
        self.soft = "#eef2f8"


def ui_scale(root):
    return max(1.0, root.winfo_fpixels("1i") / 96.0)


def install_styles(root, style, colors, font_family):
    """Creates Round.TSpinbox, Round.TCombobox, rounded TButton/Accent.TButton and a
    slim scrollbar on top of the 'clam' theme."""
    p = Palette(colors)
    s = ui_scale(root)
    px = lambda v: max(1, round(v * s))
    radius, bw = px(7), px(1)
    size = 2 * radius + 4
    edge = radius + 1

    # Field (spinbox/combobox background)
    def field(fill, border, width=bw):
        return box_image(size, size, radius, fill, border, width, p.card)
    field_normal = field(p.card, p.field_border)
    field_hover = field(p.card, p.field_hover)
    field_focus = field(p.card, p.accent, px(2))
    field_disabled = field(p.disabled_fill, p.disabled_border)
    for widget in ("Spinbox", "Combobox"):
        style.element_create(
            f"Round.{widget}.field", "image", field_normal,
            ("disabled", field_disabled), ("focus", field_focus), ("hover", field_hover),
            border=edge, padding=px(2), sticky="nsew")

    # Arrows
    thick = 1.6 * s
    up = chevron_image(px(18), px(12), "up", p.muted, p.card, thick)
    up_dis = chevron_image(px(18), px(12), "up", p.disabled_text, p.disabled_fill, thick)
    up_act = chevron_image(px(18), px(12), "up", p.accent, p.card, thick)
    down = chevron_image(px(18), px(12), "down", p.muted, p.card, thick)
    down_dis = chevron_image(px(18), px(12), "down", p.disabled_text, p.disabled_fill, thick)
    down_act = chevron_image(px(18), px(12), "down", p.accent, p.card, thick)
    combo_down = chevron_image(px(26), px(16), "down", p.muted, p.card, thick)
    combo_down_dis = chevron_image(px(26), px(16), "down", p.disabled_text, p.disabled_fill, thick)
    style.element_create("Round.Spinbox.uparrow", "image", up,
                         ("disabled", up_dis), ("active", up_act), sticky="")
    style.element_create("Round.Spinbox.downarrow", "image", down,
                         ("disabled", down_dis), ("active", down_act), sticky="")
    style.element_create("Round.Combobox.downarrow", "image", combo_down,
                         ("disabled", combo_down_dis), sticky="")

    style.layout("Round.TSpinbox", [
        ("Round.Spinbox.field", {"sticky": "nswe", "children": [
            ("null", {"side": "right", "sticky": "ns", "children": [
                ("Round.Spinbox.uparrow", {"side": "top", "sticky": "e"}),
                ("Round.Spinbox.downarrow", {"side": "bottom", "sticky": "e"}),
            ]}),
            ("Spinbox.padding", {"sticky": "nswe", "children": [
                ("Spinbox.textarea", {"sticky": "nswe"}),
            ]}),
        ]}),
    ])
    # Vertical padding 5 gives spinboxes, comboboxes and buttons the same height.
    style.configure("Round.TSpinbox", padding=(px(8), px(5), px(2), px(5)),
                    foreground=p.text, selectbackground="#cfe2f6", selectforeground=p.text,
                    insertcolor=p.text)
    style.map("Round.TSpinbox", foreground=[("disabled", p.disabled_text)])

    style.layout("Round.TCombobox", [
        ("Round.Combobox.field", {"sticky": "nswe", "children": [
            ("Round.Combobox.downarrow", {"side": "right", "sticky": "ns"}),
            ("Combobox.padding", {"sticky": "nswe", "children": [
                ("Combobox.textarea", {"sticky": "nswe"}),
            ]}),
        ]}),
    ])
    style.configure("Round.TCombobox", padding=(px(10), px(5), px(2), px(5)), foreground=p.text)
    style.map("Round.TCombobox",
              foreground=[("disabled", p.disabled_text), ("readonly", p.text)],
              selectbackground=[("readonly", p.card)],
              selectforeground=[("readonly", p.text)],
              fieldbackground=[("readonly", p.card)])
    root.option_add("*TCombobox*Listbox.font", (font_family, 10))
    root.option_add("*TCombobox*Listbox.background", p.card)
    root.option_add("*TCombobox*Listbox.foreground", p.text)
    root.option_add("*TCombobox*Listbox.selectBackground", p.accent)
    root.option_add("*TCombobox*Listbox.selectForeground", "white")
    root.option_add("*TCombobox*Listbox.borderWidth", 0)
    root.option_add("*TCombobox*Listbox.relief", "flat")
    style.configure("ComboboxPopdownFrame", borderwidth=1, relief="solid")

    # Buttons
    def button(fill, border):
        return box_image(size, size, radius, fill, border, bw, p.card)
    style.element_create(
        "Accent.Button.border", "image", button(p.accent, p.accent),
        ("disabled", button("#a9c4e0", "#a9c4e0")),
        ("pressed", button("#0a4b85", "#0a4b85")),
        ("active", button(p.accent_dark, p.accent_dark)),
        border=edge, padding=bw, sticky="nsew")
    style.element_create(
        "Soft.Button.border", "image", button(p.card, p.field_border),
        ("disabled", button(p.disabled_fill, p.disabled_border)),
        ("pressed", button("#e4eaf3", p.field_hover)),
        ("active", button(p.soft, p.field_hover)),
        border=edge, padding=bw, sticky="nsew")
    for name, element in (("Accent.TButton", "Accent.Button.border"),
                          ("TButton", "Soft.Button.border")):
        style.layout(name, [
            (element, {"sticky": "nswe", "children": [
                ("Button.padding", {"sticky": "nswe", "children": [
                    ("Button.label", {"sticky": "nswe"}),
                ]}),
            ]}),
        ])
    style.configure("Accent.TButton", padding=(px(16), px(5)), foreground="white",
                    font=(font_family, 10, "bold"))
    style.map("Accent.TButton", foreground=[("disabled", "#eef3f9")])
    style.configure("TButton", padding=(px(14), px(5)), foreground=p.text)
    style.map("TButton", foreground=[("disabled", p.disabled_text)])

    # Slim scrollbar with a rounded thumb (on the log's light background)
    trough = "#f7f8fb"
    thumb_w = px(8)
    thumb = lambda color: box_image(thumb_w, thumb_w * 2 + 2, thumb_w // 2, color, color, 1, trough)
    style.element_create("Slim.Vertical.Scrollbar.thumb", "image", thumb("#cfd6e1"),
                         ("pressed", thumb("#9fb0c8")), ("active", thumb("#b4c0d1")),
                         border=(0, thumb_w // 2 + 1, 0, thumb_w // 2 + 1), sticky="ns")
    style.layout("Slim.Vertical.TScrollbar", [
        ("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
            ("Slim.Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"}),
        ]}),
    ])
    style.configure("Slim.Vertical.TScrollbar", troughcolor=trough, bordercolor=trough,
                    lightcolor=trough, darkcolor=trough, background=trough,
                    arrowsize=px(12), padding=px(2))


# --- Custom widgets ------------------------------------------------------------

class SegmentedToggle(tk.Frame):
    """A two-or-more option pill, e.g. AM | PM, bound to a StringVar."""

    def __init__(self, parent, values, variable, colors, height, segment_width=None,
                 font_family="Segoe UI", command=None):
        p = Palette(colors)
        super().__init__(parent, bg=p.card)
        s = ui_scale(parent)
        radius = max(1, round(7 * s))
        width = segment_width or round(46 * s)
        self.variable = variable
        self.command = command
        self.values = list(values)
        self.labels = []
        self.images = {}
        last = len(self.values) - 1
        for i, value in enumerate(self.values):
            corners = (i == 0, i == last, i == last, i == 0)
            self.images[i] = {
                "on": box_image(width, height, radius, p.accent, p.accent, 1, p.card, corners),
                "off": box_image(width, height, radius, p.card, p.field_border, 1, p.card, corners),
                "hover": box_image(width, height, radius, p.soft, p.field_hover, 1, p.card, corners),
            }
            label = tk.Label(self, text=value, compound="center", bd=0, padx=0, pady=0,
                             highlightthickness=0, bg=p.card, cursor="hand2",
                             font=(font_family, 10, "bold"))
            label.pack(side="left")
            label.bind("<Button-1>", lambda e, v=value: self.select(v))
            label.bind("<Enter>", lambda e, i=i: self._hover(i, True))
            label.bind("<Leave>", lambda e, i=i: self._hover(i, False))
            self.labels.append(label)
        self._colors = p
        variable.trace_add("write", lambda *a: self._refresh())
        self._refresh()

    def select(self, value):
        if self.variable.get() != value:
            self.variable.set(value)
            if self.command:
                self.command()

    def _hover(self, index, inside):
        if self.values[index] != self.variable.get():
            self.labels[index].configure(image=self.images[index]["hover" if inside else "off"])

    def _refresh(self):
        for i, value in enumerate(self.values):
            on = value == self.variable.get()
            self.labels[i].configure(image=self.images[i]["on" if on else "off"],
                                     fg="white" if on else self._colors.text)


class ToggleSwitch(tk.Frame):
    """An on/off switch with a clickable text label, bound to a BooleanVar."""

    def __init__(self, parent, text, variable, colors, command=None, font_family="Segoe UI"):
        p = Palette(colors)
        super().__init__(parent, bg=p.card)
        s = ui_scale(parent)
        w, h = round(40 * s), round(22 * s)
        r, knob = h / 2, h / 2 - 3 * s

        def switch(track, on):
            cx = w - r if on else r
            return _render(w, h, [
                (_rounded_rect(0, 0, w, h, r), track),
                (_circle(cx, h / 2, knob), "#ffffff"),
            ], p.card)
        self.images = {
            (True, False): switch(p.accent, True), (True, True): switch(p.accent_dark, True),
            (False, False): switch("#c2cad6", False), (False, True): switch("#a9b3c2", False),
        }
        self.variable = variable
        self.command = command
        self.hovering = False
        self.switch = tk.Label(self, bd=0, highlightthickness=0, bg=p.card, cursor="hand2")
        self.switch.pack(side="left")
        self.text = tk.Label(self, text=text, bg=p.card, fg=p.text, font=(font_family, 10),
                             cursor="hand2")
        self.text.pack(side="left", padx=(round(8 * s), 0))
        for widget in (self.switch, self.text):
            widget.bind("<Button-1>", lambda e: self.toggle())
            widget.bind("<Enter>", lambda e: self._hover(True))
            widget.bind("<Leave>", lambda e: self._hover(False))
        variable.trace_add("write", lambda *a: self._refresh())
        self._refresh()

    def toggle(self):
        self.variable.set(not self.variable.get())
        if self.command:
            self.command()

    def _hover(self, inside):
        self.hovering = inside
        self._refresh()

    def _refresh(self):
        self.switch.configure(image=self.images[(bool(self.variable.get()), self.hovering)])
