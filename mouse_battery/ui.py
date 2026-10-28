"""Tkinter interface for MouseBattery."""

from __future__ import annotations

import ctypes
import json
import math
import os
import queue
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from typing import Optional

from . import __version__
from .devices import Device, Snapshot, collect

# ---------------------------------------------------------------------------
# Palette and typography
# ---------------------------------------------------------------------------
BG_TOP = "#0A0D12"
BG_BOTTOM = "#0D121A"
SURFACE = "#111720"
SURFACE_HOVER = "#17202B"
SURFACE_SELECTED = "#182230"
BORDER = "#202A38"
BORDER_SOFT = "#1A2330"
TEXT = "#F2F6FC"
MUTED = "#8D99AD"
DIM = "#5E6A7E"
FAINT = "#414C5E"

GREEN = "#4ADE80"
AMBER = "#FBBF24"
ORANGE = "#FB923C"
RED = "#F87171"
BLUE = "#60A5FA"
TEAL = "#2DD4BF"
PURPLE = "#A78BFA"

FONT_CN = "Microsoft YaHei UI"
FONT_EN = "Segoe UI"

WINDOW_W = 430
WINDOW_H = 610
FLOAT_W = 220
FLOAT_H = 66
FLOAT_KEY = "#010203"


def _enable_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _focus_existing_window() -> bool:
    try:
        hwnd = ctypes.windll.user32.FindWindowW(None, "鼠标电量")
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 9)
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            return True
    except Exception:
        pass
    return False


def _blend(fg: str, bg: str, amount: float) -> str:
    fg_rgb = tuple(int(fg[i : i + 2], 16) for i in (1, 3, 5))
    bg_rgb = tuple(int(bg[i : i + 2], 16) for i in (1, 3, 5))
    rgb = tuple(round(b + (f - b) * amount) for f, b in zip(fg_rgb, bg_rgb))
    return "#" + "".join(f"{c:02X}" for c in rgb)


def _level_color(level: int) -> str:
    if level >= 60:
        return GREEN
    if level >= 30:
        return AMBER
    if level >= 15:
        return ORANGE
    return RED


def _level_text(level: int) -> str:
    if level >= 80:
        return "电量充足"
    if level >= 50:
        return "状态良好"
    if level >= 30:
        return "电量一般"
    if level >= 15:
        return "电量偏低"
    return "电量很低"


def _resource_path(relative: str) -> Path:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / relative
    return Path(__file__).resolve().parent.parent / relative


class BatteryApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.dpi_scale = max(1.0, root.winfo_fpixels("1i") / 96.0)
        self.width = self.s(WINDOW_W)
        self.height = self.s(WINDOW_H)
        self.float_width = self.s(FLOAT_W)
        self.float_height = self.s(FLOAT_H)
        self.settings = self._load_settings()
        self.topmost = bool(self.settings.get("topmost", False))
        self.auto_refresh = bool(self.settings.get("auto", True))
        self.interval = int(self.settings.get("interval", 60))
        if self.interval not in (30, 60, 300, 0):
            self.interval = 60
        self.mode = "main"
        self.main_pos: Optional[list[int]] = None
        self.float_pos: Optional[list[int]] = None
        self._drag_offset: Optional[tuple[int, int]] = None
        self._initial_floating = bool(self.settings.get("floating", False))
        self.selected_key: Optional[str] = None
        self.snapshot: Optional[Snapshot] = None
        self.charge_state: dict[str, Optional[bool]] = {}
        self.charge_history: dict[str, list[tuple[float, int, int]]] = {}
        self.charge_evidence: dict[str, float] = {}
        self.display_level: float = 0.0
        self.target_level: Optional[int] = None
        self.animation_id: Optional[str] = None
        self.auto_id: Optional[str] = None
        self.poll_id: Optional[str] = None
        self.refreshing = False
        self.closed = False
        self.result_queue: queue.Queue[Snapshot] = queue.Queue()

        self._setup_window()
        self._create_fonts()
        self._build_canvas()
        self._draw_shell()
        self._update_switch()
        self._update_pin()
        if self._initial_floating:
            self._enter_float(initial=True)
        self.refresh()
        self._poll_results()

    # ------------------------------------------------------------------
    # Setup and geometry
    # ------------------------------------------------------------------
    def s(self, value: float) -> int:
        return int(round(value * self.dpi_scale))

    def _setup_window(self) -> None:
        self.root.title("鼠标电量")
        self.root.configure(bg=BG_TOP)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        icon = _resource_path("assets/icon.ico")
        if icon.exists():
            try:
                self.root.iconbitmap(default=str(icon))
            except tk.TclError:
                pass

        x = self.settings.get("x")
        y = self.settings.get("y")
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        if (
            isinstance(x, int)
            and isinstance(y, int)
            and -self.width + self.s(90) < x < screen_w - self.s(90)
            and 0 <= y < screen_h - self.s(70)
        ):
            pos = f"+{x}+{y}"
        else:
            pos = f"+{max(0, (screen_w - self.width) // 2)}+{max(0, (screen_h - self.height) // 2 - self.s(18))}"
        self.root.geometry(f"{self.width}x{self.height}{pos}")
        self.root.attributes("-topmost", self.topmost)
        self.root.update_idletasks()
        self._apply_dark_titlebar()

        self.root.bind("<F5>", lambda _e: self.refresh())
        self.root.bind("<Control-r>", lambda _e: self.refresh())
        self.root.bind("<Escape>", lambda _e: self._on_escape())

    def _apply_dark_titlebar(self) -> None:
        try:
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            enabled = ctypes.c_int(1)
            dwm = ctypes.windll.dwmapi
            for attribute in (20, 19):
                if dwm.DwmSetWindowAttribute(
                    hwnd, attribute, ctypes.byref(enabled), ctypes.sizeof(enabled)
                ) == 0:
                    break
        except Exception:
            pass

    def _create_fonts(self) -> None:
        self.f_title = tkfont.Font(family=FONT_CN, size=15, weight="bold")
        self.f_eyebrow = tkfont.Font(family=FONT_EN, size=7, weight="bold")
        self.font_number = tkfont.Font(family=FONT_EN, size=42, weight="bold")
        self.font_percent = tkfont.Font(family=FONT_EN, size=20, weight="bold")
        self.f_gauge_label = tkfont.Font(family=FONT_CN, size=8)
        self.font_status = tkfont.Font(family=FONT_CN, size=8, weight="bold")
        self.font_name = tkfont.Font(family=FONT_CN, size=15, weight="bold")
        self.f_subtitle = tkfont.Font(family=FONT_CN, size=8)
        self.f_meta = tkfont.Font(family=FONT_CN, size=8)
        self.f_section = tkfont.Font(family=FONT_CN, size=9, weight="bold")
        self.f_hint = tkfont.Font(family=FONT_CN, size=7)
        self.f_row_name = tkfont.Font(family=FONT_CN, size=9, weight="bold")
        self.f_row_sub = tkfont.Font(family=FONT_CN, size=7)
        self.f_row_pct = tkfont.Font(family=FONT_EN, size=11, weight="bold")
        self.f_badge = tkfont.Font(family=FONT_EN, size=6, weight="bold")
        self.f_button = tkfont.Font(family=FONT_CN, size=10, weight="bold")
        self.f_small = tkfont.Font(family=FONT_CN, size=8)
        self.f_tiny = tkfont.Font(family=FONT_CN, size=7)
        self.f_empty_title = tkfont.Font(family=FONT_CN, size=10, weight="bold")
        self.f_empty_body = tkfont.Font(family=FONT_CN, size=8)
        self.f_float_name = tkfont.Font(family=FONT_CN, size=9, weight="bold")
        self.f_float_sub = tkfont.Font(family=FONT_CN, size=7)
        self.f_float_num = tkfont.Font(family=FONT_EN, size=11, weight="bold")
        self.f_float_pct = tkfont.Font(family=FONT_EN, size=6, weight="bold")
        self.f_float_btn = tkfont.Font(family=FONT_CN, size=7, weight="bold")

    def _build_canvas(self) -> None:
        self.canvas = tk.Canvas(
            self.root,
            width=self.width,
            height=self.height,
            highlightthickness=0,
            bd=0,
            bg=BG_TOP,
        )
        self.canvas.pack(fill="both", expand=True)

    # ------------------------------------------------------------------
    # Drawing helpers
    # ------------------------------------------------------------------
    def _round_rect(self, x1, y1, x2, y2, radius, **kwargs):
        r = min(radius, (x2 - x1) / 2, (y2 - y1) / 2)
        points = [
            x1 + r, y1,
            x2 - r, y1,
            x2, y1,
            x2, y1 + r,
            x2, y2 - r,
            x2, y2,
            x2 - r, y2,
            x1 + r, y2,
            x1, y2,
            x1, y2 - r,
            x1, y1 + r,
            x1, y1,
        ]
        return self.canvas.create_polygon(
            points, smooth=True, splinesteps=24, **kwargs
        )

    def _ellipsize(self, text: str, font: tkfont.Font, max_width: int) -> str:
        if font.measure(text) <= max_width:
            return text
        suffix = "…"
        low, high = 0, len(text)
        while low < high:
            mid = (low + high + 1) // 2
            if font.measure(text[:mid] + suffix) <= max_width:
                low = mid
            else:
                high = mid - 1
        return text[:low].rstrip() + suffix

    def _draw_gradient(self) -> None:
        steps = 48
        for i in range(steps):
            y1 = int(self.height * i / steps)
            y2 = int(self.height * (i + 1) / steps) + 1
            color = _blend(BG_BOTTOM, BG_TOP, i / (steps - 1))
            self.canvas.create_rectangle(
                0, y1, self.width, y2, fill=color, outline=color
            )

    # ------------------------------------------------------------------
    # Static shell
    # ------------------------------------------------------------------
    def _draw_shell(self) -> None:
        c = self.canvas
        self._draw_gradient()

        # Header
        self.header_glow = c.create_oval(
            self.s(24), self.s(22), self.s(42), self.s(40),
            fill=_blend(GREEN, BG_TOP, 0.14), outline="",
        )
        self.header_dot = c.create_oval(
            self.s(29), self.s(27), self.s(37), self.s(35),
            fill=GREEN, outline="",
        )
        c.create_text(
            self.s(52), self.s(14),
            text="鼠标电量", anchor="nw", font=self.f_title, fill=TEXT,
        )
        c.create_text(
            self.s(53), self.s(39),
            text="MOUSE BATTERY", anchor="nw", font=self.f_eyebrow, fill=DIM,
        )

        self.float_bg = self._round_rect(
            self.s(268), self.s(15), self.s(332), self.s(41), self.s(13),
            fill=SURFACE, outline=BORDER,
        )
        self.float_text = c.create_text(
            self.s(300), self.s(28),
            text="悬浮", font=self.f_hint, fill=MUTED,
        )
        for item in (self.float_bg, self.float_text):
            c.tag_bind(item, "<Button-1>", lambda _e: self._enter_float())
            c.tag_bind(item, "<Enter>", lambda _e: self._float_hover(True))
            c.tag_bind(item, "<Leave>", lambda _e: self._float_hover(False))

        self.pin_bg = self._round_rect(
            self.s(340), self.s(15), self.s(404), self.s(41), self.s(13),
            fill=SURFACE, outline=BORDER,
        )
        self.pin_text = c.create_text(
            self.s(372), self.s(28),
            text="置顶", font=self.f_hint, fill=MUTED,
        )
        for item in (self.pin_bg, self.pin_text):
            c.tag_bind(item, "<Button-1>", lambda _e: self._toggle_topmost())
            c.tag_bind(item, "<Enter>", lambda _e: c.configure(cursor="hand2"))
            c.tag_bind(item, "<Leave>", lambda _e: c.configure(cursor="arrow"))

        # Gauge
        self.gcx = self.s(215)
        self.gcy = self.s(153)
        self.gr = self.s(78)
        self.gauge_width = self.s(13)
        box = (
            self.gcx - self.gr, self.gcy - self.gr,
            self.gcx + self.gr, self.gcy + self.gr,
        )
        self.gauge_glow = c.create_arc(
            *box, start=90, extent=359.9, style="arc",
            outline=_blend(GREEN, BG_TOP, 0.12),
            width=self.s(24),
        )
        c.create_arc(
            *box, start=90, extent=359.9, style="arc",
            outline="#1B2430", width=self.gauge_width,
        )
        self.gauge_arc = c.create_arc(
            *box, start=90, extent=-0.1, style="arc",
            outline=GREEN, width=self.gauge_width,
        )
        self.gauge_cap = c.create_oval(
            self.gcx - self.s(3), self.gcy + self.s(3),
            self.gcx + self.s(3), self.gcy + self.s(5),
            fill=GREEN, outline="",
        )
        self.gauge_number = c.create_text(
            self.gcx, self.gcy + self.s(13),
            text="—", anchor="sw", font=self.font_number, fill=TEXT,
        )
        self.gauge_percent = c.create_text(
            self.gcx, self.gcy + self.s(13),
            text="", anchor="sw", font=self.font_percent, fill=MUTED,
        )
        self.gauge_label = c.create_text(
            self.gcx, self.gcy + self.s(38),
            text="剩余电量", font=self.f_gauge_label, fill=MUTED,
        )

        # Selected device
        self.name_text = c.create_text(
            self.gcx, self.s(285),
            text="正在读取…", font=self.font_name, fill=TEXT,
        )
        self.subtitle_text = c.create_text(
            self.gcx, self.s(310),
            text="", font=self.f_subtitle, fill=MUTED,
        )
        self.meta_text = c.create_text(
            self.gcx, self.s(330),
            text="", font=self.f_meta, fill=DIM,
        )

        # Divider and section title
        c.create_line(
            self.s(26), self.s(347), self.s(404), self.s(347),
            fill=BORDER_SOFT,
        )
        self.section_text = c.create_text(
            self.s(26), self.s(363),
            text="设备", anchor="w", font=self.f_section, fill="#CBD5E1",
        )
        self.count_text = c.create_text(
            self.s(60), self.s(363),
            text="", anchor="w", font=self.f_hint, fill=DIM,
        )
        self.section_hint = c.create_text(
            self.s(404), self.s(363),
            text="点击切换", anchor="e", font=self.f_hint, fill=FAINT,
        )

        # Refresh button
        self.refresh_bg = self._round_rect(
            self.s(26), self.s(502), self.s(404), self.s(544),
            self.s(13), fill="#EDF2F8", outline="",
        )
        self.refresh_text = c.create_text(
            self.s(215), self.s(523),
            text="刷新电量", font=self.f_button, fill="#0A0E14",
        )
        for item in (self.refresh_bg, self.refresh_text):
            c.tag_bind(item, "<Button-1>", lambda _e: self.refresh())
            c.tag_bind(item, "<Enter>", lambda _e: self._refresh_hover(True))
            c.tag_bind(item, "<Leave>", lambda _e: self._refresh_hover(False))

        # Auto refresh row
        self.switch_track = self._round_rect(
            self.s(26), self.s(558), self.s(66), self.s(580),
            self.s(11), fill="#26303D", outline="",
        )
        self.switch_knob = c.create_oval(
            self.s(29), self.s(561), self.s(45), self.s(577),
            fill="#D7E0EC", outline="",
        )
        self.auto_text = c.create_text(
            self.s(76), self.s(569),
            text="自动刷新", anchor="w", font=self.f_small, fill="#AAB5C7",
        )
        for item in (self.switch_track, self.switch_knob, self.auto_text):
            c.tag_bind(item, "<Button-1>", lambda _e: self._toggle_auto())
            c.tag_bind(item, "<Enter>", lambda _e: c.configure(cursor="hand2"))
            c.tag_bind(item, "<Leave>", lambda _e: c.configure(cursor="arrow"))

        self.interval_text = c.create_text(
            self.s(404), self.s(569),
            text="", anchor="e", font=self.f_small, fill=DIM,
        )
        c.tag_bind(self.interval_text, "<Button-1>", lambda _e: self._cycle_interval())
        c.tag_bind(self.interval_text, "<Enter>", lambda _e: c.configure(cursor="hand2"))
        c.tag_bind(self.interval_text, "<Leave>", lambda _e: c.configure(cursor="arrow"))

        c.create_text(
            self.s(26), self.s(590),
            text="本地读取 · 不联网", anchor="w", font=self.f_tiny, fill=FAINT,
        )
        c.create_text(
            self.s(404), self.s(590),
            text=f"v{__version__}", anchor="e", font=self.f_tiny, fill=FAINT,
        )

        self._paint_gauge(None, animate=False)
        self._paint_status(None, "正在读取…", BLUE)

    # ------------------------------------------------------------------
    # Floating widget
    # ------------------------------------------------------------------
    def _enter_float(self, initial: bool = False) -> None:
        if self.mode == "float" or self.closed:
            return
        if self.animation_id:
            try:
                self.root.after_cancel(self.animation_id)
            except tk.TclError:
                pass
            self.animation_id = None

        self.main_pos = [self.root.winfo_x(), self.root.winfo_y()]
        self.mode = "float"
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-transparentcolor", FLOAT_KEY)
        self.root.configure(bg=FLOAT_KEY)
        self.canvas.configure(
            width=self.float_width,
            height=self.float_height,
            bg=FLOAT_KEY,
        )

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        if self.float_pos:
            fx, fy = self.float_pos
        else:
            fx = self.settings.get("float_x")
            fy = self.settings.get("float_y")
        if not (
            isinstance(fx, int)
            and isinstance(fy, int)
            and -self.float_width + self.s(80) < fx < screen_w - self.s(80)
            and 0 <= fy < screen_h - self.s(60)
        ):
            fx = max(self.s(16), screen_w - self.float_width - self.s(32))
            fy = max(self.s(16), screen_h - self.float_height - self.s(96))

        self.root.geometry(f"{self.float_width}x{self.float_height}+{fx}+{fy}")
        self.canvas.delete("all")
        self._draw_float_shell()
        self._render_float(self._selected_device())
        self.root.update_idletasks()
        self._save_settings()

    def _exit_float(self) -> None:
        if self.mode != "float" or self.closed:
            return
        self.float_pos = [self.root.winfo_x(), self.root.winfo_y()]
        self.mode = "main"
        self.root.attributes("-transparentcolor", "")
        self.root.overrideredirect(False)
        self.root.attributes("-topmost", self.topmost)
        self.root.configure(bg=BG_TOP)
        self.canvas.configure(
            width=self.width,
            height=self.height,
            bg=BG_TOP,
        )

        if self.main_pos:
            mx, my = self.main_pos
        else:
            mx = max(0, (self.root.winfo_screenwidth() - self.width) // 2)
            my = max(0, (self.root.winfo_screenheight() - self.height) // 2 - self.s(18))
        self.root.geometry(f"{self.width}x{self.height}+{mx}+{my}")
        self.canvas.delete("all")
        self._draw_shell()
        self._update_switch()
        self._update_pin()
        self._apply_dark_titlebar()
        if self.snapshot:
            self._apply_snapshot(self.snapshot)
        if self.refreshing:
            self._set_refreshing_ui(True)
        self.root.update_idletasks()
        self._save_settings()

    def _draw_float_shell(self) -> None:
        c = self.canvas
        fw, fh = self.float_width, self.float_height
        c.configure(bg=FLOAT_KEY)

        # The transparent color key leaves a clean rounded card on the desktop.
        self._round_rect(
            self.s(2), self.s(2), fw - self.s(2), fh - self.s(2), self.s(15),
            fill="#0D131C", outline="#2A3546", tags="float_drag",
        )
        c.create_line(
            self.s(14), self.s(2.5), fw - self.s(14), self.s(2.5),
            fill="#1A2634", tags="float_drag",
        )

        self.f_cx = self.s(31)
        self.f_cy = self.s(33)
        self.f_r = self.s(19)
        self.f_width = self.s(5)
        box = (
            self.f_cx - self.f_r, self.f_cy - self.f_r,
            self.f_cx + self.f_r, self.f_cy + self.f_r,
        )
        c.create_arc(
            *box, start=90, extent=359.9, style="arc",
            outline="#1B2430", width=self.f_width, tags="float_drag",
        )
        self.f_arc = c.create_arc(
            *box, start=90, extent=-0.1, style="arc",
            outline=GREEN, width=self.f_width, tags="float_drag",
        )
        self.f_cap = c.create_oval(
            self.f_cx - self.s(2), self.f_cy,
            self.f_cx + self.s(2), self.f_cy + self.s(4),
            fill=GREEN, outline="", tags="float_drag",
        )
        self.f_number = c.create_text(
            self.f_cx, self.f_cy + self.s(4),
            text="—", anchor="sw", font=self.f_float_num, fill=TEXT,
            tags="float_drag",
        )
        self.f_percent = c.create_text(
            self.f_cx, self.f_cy + self.s(4),
            text="", anchor="sw", font=self.f_float_pct, fill=MUTED,
            tags="float_drag",
        )

        self.f_name = c.create_text(
            self.s(56), self.s(9),
            text="正在读取…", anchor="nw", font=self.f_float_name,
            fill=TEXT, tags="float_drag",
        )
        self.f_status = c.create_text(
            self.s(56), self.s(26),
            text="", anchor="nw", font=self.f_float_sub,
            fill=MUTED, tags="float_drag",
        )
        self.f_bar_x1 = self.s(56)
        self.f_bar_x2 = fw - self.s(16)
        self.f_bar_y = self.s(49)
        c.create_rectangle(
            self.f_bar_x1, self.f_bar_y, self.f_bar_x2, self.f_bar_y + self.s(3),
            fill="#222C3A", outline="", tags="float_drag",
        )
        self.f_bar = c.create_rectangle(
            self.f_bar_x1, self.f_bar_y, self.f_bar_x1, self.f_bar_y + self.s(3),
            fill=GREEN, outline="", tags="float_drag",
        )

        # Controls
        self.f_expand_bg = self._round_rect(
            fw - self.s(62), self.s(5), fw - self.s(30), self.s(23),
            self.s(8), fill="#151D28", outline="#263141", tags="float_expand",
        )
        self.f_expand_text = c.create_text(
            fw - self.s(46), self.s(14),
            text="展开", font=self.f_float_btn, fill=MUTED, tags="float_expand",
        )
        self.f_close_bg = self._round_rect(
            fw - self.s(26), self.s(5), fw - self.s(6), self.s(23),
            self.s(8), fill="#151D28", outline="#263141", tags="float_close",
        )
        self.f_close_text = c.create_text(
            fw - self.s(16), self.s(14),
            text="×", font=self.f_float_btn, fill=MUTED, tags="float_close",
        )

        c.tag_bind("float_drag", "<ButtonPress-1>", self._float_press)
        c.tag_bind("float_drag", "<B1-Motion>", self._float_drag)
        c.tag_bind("float_drag", "<ButtonRelease-1>", self._float_release)
        c.tag_bind("float_drag", "<Double-Button-1>", lambda _e: self._exit_float())
        c.tag_bind("float_drag", "<Enter>", lambda _e: c.configure(cursor="fleur"))
        c.tag_bind("float_drag", "<Leave>", lambda _e: c.configure(cursor="arrow"))

        for item in (self.f_expand_bg, self.f_expand_text):
            c.tag_bind(item, "<Button-1>", lambda _e: self._exit_float())
            c.tag_bind(item, "<Enter>", lambda _e: self._float_control_hover(True, "expand"))
            c.tag_bind(item, "<Leave>", lambda _e: self._float_control_hover(False, "expand"))
        for item in (self.f_close_bg, self.f_close_text):
            c.tag_bind(item, "<Button-1>", lambda _e: self._on_close())
            c.tag_bind(item, "<Enter>", lambda _e: self._float_control_hover(True, "close"))
            c.tag_bind(item, "<Leave>", lambda _e: self._float_control_hover(False, "close"))

    def _float_control_hover(self, hovering: bool, which: str) -> None:
        if self.mode != "float":
            return
        bg = self.f_expand_bg if which == "expand" else self.f_close_bg
        text = self.f_expand_text if which == "expand" else self.f_close_text
        self.canvas.itemconfigure(
            bg, fill="#243244" if hovering else "#151D28",
            outline="#3A4A60" if hovering else "#263141",
        )
        self.canvas.itemconfigure(text, fill=TEXT if hovering else MUTED)
        self.canvas.configure(cursor="hand2" if hovering else "fleur")

    def _float_press(self, event: tk.Event) -> None:
        self._drag_offset = (
            event.x_root - self.root.winfo_x(),
            event.y_root - self.root.winfo_y(),
        )

    def _float_drag(self, event: tk.Event) -> None:
        if not self._drag_offset or self.mode != "float":
            return
        dx, dy = self._drag_offset
        self.root.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")

    def _float_release(self, _event: tk.Event) -> None:
        self._drag_offset = None
        if self.mode == "float":
            self.float_pos = [self.root.winfo_x(), self.root.winfo_y()]
            self._save_settings()

    def _render_float(self, device: Optional[Device]) -> None:
        if self.mode != "float" or not hasattr(self, "f_arc"):
            return
        c = self.canvas
        if device is None:
            c.itemconfigure(self.f_arc, state="hidden")
            c.itemconfigure(self.f_cap, state="hidden")
            c.itemconfigure(self.f_number, text="?", fill=MUTED)
            c.coords(self.f_number, self.f_cx, self.f_cy + self.s(2))
            c.itemconfigure(self.f_number, anchor="center")
            c.itemconfigure(self.f_percent, text="")
            c.itemconfigure(self.f_name, text="未连接")
            c.itemconfigure(self.f_status, text="等待设备", fill=DIM)
            c.coords(self.f_bar, self.f_bar_x1, self.f_bar_y, self.f_bar_x1, self.f_bar_y + self.s(3))
            return

        color = _level_color(device.level)
        extent = -359.9 * device.level / 100.0
        c.itemconfigure(self.f_arc, state="normal", extent=extent, outline=color)
        if device.level <= 0:
            c.itemconfigure(self.f_cap, state="hidden")
        else:
            angle = math.radians(90 - 3.6 * device.level)
            x = self.f_cx + self.f_r * math.cos(angle)
            y = self.f_cy - self.f_r * math.sin(angle)
            radius = self.f_width / 2
            c.coords(self.f_cap, x - radius, y - radius, x + radius, y + radius)
            c.itemconfigure(self.f_cap, state="normal", fill=color)

        number = str(device.level)
        num_width = self.f_float_num.measure(number)
        pct_width = self.f_float_pct.measure("%")
        gap = self.s(1)
        start = self.f_cx - (num_width + gap + pct_width) / 2
        baseline = self.f_cy + self.s(4)
        c.coords(self.f_number, start, baseline)
        c.itemconfigure(
            self.f_number, text=number, anchor="sw",
            font=self.f_float_num, fill=color,
        )
        c.coords(self.f_percent, start + num_width + gap, baseline)
        c.itemconfigure(
            self.f_percent, text="%", anchor="sw",
            font=self.f_float_pct, fill=_blend(color, TEXT, 0.2),
        )

        name = self._ellipsize(device.name, self.f_float_name, self.s(98))
        c.itemconfigure(self.f_name, text=name)
        status, status_color = self._device_status(device)
        c.itemconfigure(
            self.f_status,
            text=f"{device.transport} · {status}",
            fill=status_color if device.charging else _blend(color, MUTED, 0.35),
        )
        fill_width = (self.f_bar_x2 - self.f_bar_x1) * device.level / 100
        c.coords(
            self.f_bar,
            self.f_bar_x1, self.f_bar_y,
            max(self.f_bar_x1, self.f_bar_x1 + fill_width), self.f_bar_y + self.s(3),
        )
        c.itemconfigure(self.f_bar, fill=color)

    # ------------------------------------------------------------------
    # State and refresh
    # ------------------------------------------------------------------
    def _load_settings(self) -> dict:
        path = Path(os.environ.get("APPDATA", Path.home())) / "MouseBattery" / "settings.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_settings(self) -> None:
        path = Path(os.environ.get("APPDATA", Path.home())) / "MouseBattery" / "settings.json"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if self.mode == "float":
                self.float_pos = [self.root.winfo_x(), self.root.winfo_y()]
            else:
                self.main_pos = [self.root.winfo_x(), self.root.winfo_y()]
            main_pos = self.main_pos or [None, None]
            float_pos = self.float_pos or [None, None]
            data = {
                "topmost": self.topmost,
                "auto": self.auto_refresh,
                "interval": self.interval,
                "floating": self.mode == "float",
                "x": main_pos[0],
                "y": main_pos[1],
                "float_x": float_pos[0],
                "float_y": float_pos[1],
            }
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _float_hover(self, hovering: bool) -> None:
        if self.mode != "main" or not hasattr(self, "float_bg"):
            return
        self.canvas.itemconfigure(
            self.float_bg, fill=SURFACE_HOVER if hovering else SURFACE,
            outline="#334155" if hovering else BORDER,
        )

    def _refresh_hover(self, hovering: bool) -> None:
        if self.refreshing or self.mode != "main":
            return
        self.canvas.itemconfigure(
            self.refresh_bg, fill="#FFFFFF" if hovering else "#EDF2F8"
        )

    def _set_refreshing_ui(self, active: bool) -> None:
        self.refreshing = active
        if self.mode != "main":
            return
        if active:
            self.canvas.itemconfigure(
                self.refresh_bg, fill="#1B2430", outline=BORDER
            )
            self.canvas.itemconfigure(
                self.refresh_text, text="正在读取…", fill=MUTED
            )
        else:
            self.canvas.itemconfigure(
                self.refresh_bg, fill="#EDF2F8", outline=""
            )
            self.canvas.itemconfigure(
                self.refresh_text, text="刷新电量", fill="#0A0E14"
            )

    def refresh(self) -> None:
        if self.refreshing or self.closed:
            return
        self._set_refreshing_ui(True)
        if self.snapshot is None and self.mode == "main":
            self._paint_status(None, "正在读取…", BLUE)
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self) -> None:
        try:
            snapshot = collect()
        except Exception as exc:  # last-resort guard: never kill the UI thread
            snapshot = Snapshot(
                devices=[], timestamp=time.time(), mouse_error=f"读取失败：{exc}"
            )
        self.result_queue.put(snapshot)

    def _poll_results(self) -> None:
        if self.closed:
            return
        try:
            snapshot = self.result_queue.get_nowait()
        except queue.Empty:
            snapshot = None
        if snapshot is not None:
            self._apply_snapshot(snapshot)
            self._set_refreshing_ui(False)
            self._schedule_auto()
        self.poll_id = self.root.after(80, self._poll_results)

    def _apply_snapshot(self, snapshot: Snapshot) -> None:
        self.snapshot = snapshot
        self._update_charge_flags(snapshot)
        keys = {device.key for device in snapshot.devices}
        if self.selected_key not in keys:
            self.selected_key = self._pick_default(snapshot.devices)
        selected = self._selected_device()
        if self.mode == "float":
            self._render_float(selected)
            return
        self._render_selected(selected)
        self._render_rows(snapshot)
        self._paint_gauge(
            selected.level if selected else None,
            color=_level_color(selected.level) if selected else DIM,
            animate=True,
        )
        if selected:
            status, status_color = self._device_status(selected)
            self._paint_status(selected.level, status, status_color)
        else:
            self._clear_status()
        self._update_header_dot(_level_color(selected.level) if selected else DIM)

    def _device_status(self, device: Device) -> tuple[str, str]:
        if device.charging is True:
            return "充电中", TEAL
        return _level_text(device.level), _level_color(device.level)

    def _update_charge_flags(self, snapshot: Snapshot) -> None:
        """Infer charging from the level/voltage trend.

        The 64-byte ATK report does not expose a verified charging bit (byte 6
        stayed 1 with the cable unplugged), so a rising level/voltage is the
        only reliable signal available.
        """
        now = snapshot.timestamp
        for device in snapshot.devices:
            if device.transport != "2.4G" or not device.voltage_mv:
                device.charging = self.charge_state.get(device.key)
                continue

            history = self.charge_history.setdefault(device.key, [])
            if not history or now - history[-1][0] > 2:
                history.append((now, device.level, device.voltage_mv))
            history[:] = [sample for sample in history if now - sample[0] <= 300]

            state = self.charge_state.get(device.key)
            positive = False
            negative = False

            # A one-step increase is already meaningful; a two-step window
            # reduces jitter from the gauge.
            if len(history) >= 2:
                previous = history[-2]
                if (
                    device.level > previous[1]
                    and device.voltage_mv >= previous[2] - 5
                ):
                    state = True
                    positive = True
                elif (
                    device.level < previous[1]
                    or device.voltage_mv <= previous[2] - 8
                ):
                    state = False
                    negative = True

            candidates = [
                sample for sample in history if now - sample[0] >= 45
            ]
            baseline = max(candidates, key=lambda sample: sample[0]) if candidates else None
            if baseline is not None and not negative:
                dv = device.voltage_mv - baseline[2]
                dl = device.level - baseline[1]
                if dv >= 8 and dl >= 0:
                    state = True
                    positive = True
                elif dv <= -8 or dl <= -1:
                    state = False

            if state is True:
                if positive or device.key not in self.charge_evidence:
                    self.charge_evidence[device.key] = now
                elif now - self.charge_evidence[device.key] > 360:
                    state = False
            elif state is False:
                self.charge_evidence.pop(device.key, None)

            self.charge_state[device.key] = bool(state) if state is not None else None
            device.charging = state

    def _pick_default(self, devices: list[Device]) -> Optional[str]:
        if not devices:
            return None
        for device in devices:
            if device.transport == "2.4G":
                return device.key
        for device in devices:
            if device.is_mouse:
                return device.key
        return devices[0].key

    def _selected_device(self) -> Optional[Device]:
        if not self.snapshot:
            return None
        for device in self.snapshot.devices:
            if device.key == self.selected_key:
                return device
        return None

    # ------------------------------------------------------------------
    # Rendering dynamic parts
    # ------------------------------------------------------------------
    def _render_selected(self, device: Optional[Device]) -> None:
        c = self.canvas
        if device is None:
            c.itemconfigure(self.name_text, text="未检测到设备")
            c.itemconfigure(self.subtitle_text, text="插入 2.4G 接收器，或连接蓝牙设备")
            c.itemconfigure(
                self.meta_text,
                text="等待设备连接后自动显示电量",
                fill=DIM,
            )
            return

        max_name = self.s(350)
        name = self._ellipsize(device.name, self.font_name, max_name)
        c.itemconfigure(self.name_text, text=name)
        if device.transport == "2.4G":
            subtitle = f"接收器 {device.subtitle.replace('接收器 ', '', 1)}"
        else:
            subtitle = f"蓝牙设备 · {device.address}" if device.address else "蓝牙设备"
        c.itemconfigure(self.subtitle_text, text=subtitle)

        stamp = time.strftime("%H:%M:%S", time.localtime(self.snapshot.timestamp)) if self.snapshot else "--:--:--"
        bits = []
        if device.voltage_mv:
            bits.append(f"{device.voltage_mv / 1000:.2f} V")
        bits.append(device.source)
        bits.append(f"{stamp} 更新")
        c.itemconfigure(self.meta_text, text="  ·  ".join(bits), fill=DIM)

    def _render_rows(self, snapshot: Snapshot) -> None:
        c = self.canvas
        c.delete("rows")
        devices = snapshot.devices
        visible = devices[:2]
        self.canvas.itemconfigure(
            self.count_text, text=f"{snapshot.count} 台"
        )
        if snapshot.count > 2:
            hint = f"共 {snapshot.count} 台 · 仅显示前 2 台"
        elif len(visible) > 1:
            hint = "点击切换"
        elif len(visible) == 1:
            hint = "仅显示已连接"
        else:
            hint = ""
        self.canvas.itemconfigure(self.section_hint, text=hint)

        if not devices:
            self._draw_empty_state(snapshot)
            return

        y = self.s(380)
        for index, device in enumerate(visible):
            self._draw_row(index, device, y)
            y += self.s(50) + self.s(6)

    def _draw_empty_state(self, snapshot: Snapshot) -> None:
        c = self.canvas
        y1 = self.s(380)
        y2 = self.s(488)
        self._round_rect(
            self.s(26), y1, self.s(404), y2, self.s(14),
            fill="#0F151D", outline=BORDER_SOFT, tags="rows",
        )
        # Simple battery illustration
        bx, by = self.s(215), y1 + self.s(30)
        c.create_line(
            bx - self.s(11), by - self.s(6), bx + self.s(7), by - self.s(6),
            bx + self.s(11), by - self.s(2), bx + self.s(11), by + self.s(5),
            bx + self.s(7), by + self.s(9), bx - self.s(11), by + self.s(9),
            bx - self.s(15), by + self.s(5), bx - self.s(15), by - self.s(2),
            bx - self.s(11), by - self.s(6),
            fill=FAINT, width=self.s(1.4), tags="rows",
        )
        c.create_line(
            bx + self.s(12), by - self.s(2), bx + self.s(15), by - self.s(2),
            bx + self.s(15), by + self.s(5), bx + self.s(12), by + self.s(5),
            fill=FAINT, width=self.s(1.4), tags="rows",
        )
        c.create_text(
            self.s(215), y1 + self.s(53),
            text="未找到可读取电量的设备",
            font=self.f_empty_title, fill="#C8D2E1", tags="rows",
        )
        message = snapshot.mouse_error or "请确认接收器已插好，或先在系统中连接蓝牙设备"
        if len(message) > 46:
            message = message[:44] + "…"
        c.create_text(
            self.s(215), y1 + self.s(73),
            text=message, font=self.f_empty_body, fill=DIM,
            width=self.s(330), justify="center", tags="rows",
        )
        c.create_text(
            self.s(215), y1 + self.s(93),
            text="读取在本地完成，不会连接网络",
            font=self.f_tiny, fill=FAINT, tags="rows",
        )

    def _draw_row(self, index: int, device: Device, y: int) -> None:
        c = self.canvas
        x1, x2 = self.s(26), self.s(404)
        y2 = y + self.s(50)
        tag = f"row{index}"
        color = _level_color(device.level)
        selected = device.key == self.selected_key
        bg = SURFACE_SELECTED if selected else SURFACE
        outline = "#314054" if selected else BORDER
        self._round_rect(
            x1, y, x2, y2, self.s(13),
            fill=bg, outline=outline, tags=("rows", tag),
        )
        if selected:
            c.create_rectangle(
                x1 + self.s(1), y + self.s(11), x1 + self.s(4), y2 - self.s(11),
                fill=color, outline="", tags=("rows", tag),
            )

        # Transport badge
        badge_color = "#1C2B3B" if device.transport == "2.4G" else "#252140"
        badge_text_color = "#93C5FD" if device.transport == "2.4G" else "#C4B5FD"
        self._round_rect(
            x1 + self.s(12), y + self.s(10),
            x1 + self.s(47), y + self.s(27), self.s(6),
            fill=badge_color, outline="", tags=("rows", tag),
        )
        c.create_text(
            x1 + self.s(29.5), y + self.s(18.5),
            text="2.4G" if device.transport == "2.4G" else "BT",
            font=self.f_badge, fill=badge_text_color, tags=("rows", tag),
        )

        name = self._ellipsize(device.name, self.f_row_name, self.s(205))
        c.create_text(
            x1 + self.s(57), y + self.s(8),
            text=name, anchor="nw", font=self.f_row_name, fill=TEXT,
            tags=("rows", tag),
        )
        c.create_text(
            x2 - self.s(14), y + self.s(8),
            text=f"{device.level}%", anchor="ne", font=self.f_row_pct, fill=color,
            tags=("rows", tag),
        )
        subtitle = (
            f"{device.subtitle} · {device.voltage_mv / 1000:.2f} V"
            if device.voltage_mv
            else device.subtitle
        )
        subtitle = self._ellipsize(subtitle, self.f_row_sub, self.s(255))
        c.create_text(
            x1 + self.s(57), y + self.s(27),
            text=subtitle, anchor="nw", font=self.f_row_sub, fill=DIM,
            tags=("rows", tag),
        )
        c.create_rectangle(
            x1 + self.s(57), y + self.s(40), x2 - self.s(14), y + self.s(43),
            fill="#222C3A", outline="", tags=("rows", tag),
        )
        fill_width = max(self.s(2), (x2 - self.s(14) - (x1 + self.s(57))) * device.level / 100)
        c.create_rectangle(
            x1 + self.s(57), y + self.s(40), x1 + self.s(57) + fill_width, y + self.s(43),
            fill=color, outline="", tags=("rows", tag),
        )

        c.tag_bind(tag, "<Button-1>", lambda _e, key=device.key: self._select(key))
        c.tag_bind(tag, "<Enter>", lambda _e: self.canvas.configure(cursor="hand2"))
        c.tag_bind(tag, "<Leave>", lambda _e: self.canvas.configure(cursor="arrow"))

    def _select(self, key: str) -> None:
        if key == self.selected_key or not self.snapshot:
            return
        self.selected_key = key
        selected = self._selected_device()
        self._render_selected(selected)
        self._render_rows(self.snapshot)
        self._paint_gauge(
            selected.level if selected else None,
            color=_level_color(selected.level) if selected else DIM,
            animate=True,
        )
        if selected:
            status, status_color = self._device_status(selected)
            self._paint_status(selected.level, status, status_color)
            self._update_header_dot(_level_color(selected.level))
        else:
            self._clear_status()
            self._update_header_dot(DIM)

    # ------------------------------------------------------------------
    # Gauge, status, header accent
    # ------------------------------------------------------------------
    def _paint_gauge(self, level: Optional[int], color: str = GREEN, animate: bool = True) -> None:
        if level is None:
            self.target_level = None
            self._set_arc(None, DIM)
            return
        self.target_level = max(0, min(100, int(level)))
        if animate and self.display_level <= 0:
            self.display_level = 0.0
        if animate:
            start = self.display_level
            started = time.monotonic()
            duration = 0.45
            if self.animation_id:
                self.root.after_cancel(self.animation_id)
                self.animation_id = None

            def step() -> None:
                t = min(1.0, (time.monotonic() - started) / duration)
                eased = 1 - (1 - t) ** 3
                value = start + (self.target_level - start) * eased
                self._set_arc(value, color)
                if t < 1.0:
                    self.animation_id = self.root.after(16, step)
                else:
                    self.animation_id = None
                    self.display_level = float(self.target_level)

            step()
        else:
            self.display_level = float(self.target_level)
            self._set_arc(self.display_level, color)

    def _set_arc(self, value: Optional[float], color: str) -> None:
        c = self.canvas
        if value is None:
            c.itemconfigure(self.gauge_arc, state="hidden")
            c.itemconfigure(self.gauge_glow, state="hidden")
            c.itemconfigure(self.gauge_cap, state="hidden")
            c.itemconfigure(self.gauge_number, text="?", fill=MUTED)
            c.coords(self.gauge_number, self.gcx, self.gcy + self.s(2))
            c.itemconfigure(self.gauge_number, anchor="center")
            c.itemconfigure(self.gauge_percent, text="")
            c.coords(self.gauge_label, self.gcx, self.gcy + self.s(45))
            c.itemconfigure(self.gauge_label, text="等待设备", fill=DIM)
            return

        value = max(0.0, min(100.0, value))
        extent = -359.9 * value / 100.0
        c.itemconfigure(self.gauge_arc, state="normal", extent=extent, outline=color)
        c.itemconfigure(self.gauge_glow, state="normal", outline=_blend(color, BG_TOP, 0.10))
        if value <= 0.1:
            c.itemconfigure(self.gauge_cap, state="hidden")
        else:
            angle = math.radians(90 - 3.6 * value)
            x = self.gcx + self.gr * math.cos(angle)
            y = self.gcy - self.gr * math.sin(angle)
            radius = self.gauge_width / 2
            c.coords(self.gauge_cap, x - radius, y - radius, x + radius, y + radius)
            c.itemconfigure(self.gauge_cap, state="normal", fill=color)

        number = str(int(round(value)))
        self._center_number(number, color)
        c.coords(self.gauge_label, self.gcx, self.gcy + self.s(38))
        c.itemconfigure(self.gauge_label, text="剩余电量", fill=MUTED)

    def _center_number(self, number: str, color: str) -> None:
        c = self.canvas
        num_width = self.font_number.measure(number)
        pct_width = self.font_percent.measure("%")
        gap = self.s(2)
        total = num_width + gap + pct_width
        start = self.gcx - total / 2
        baseline = self.gcy + self.s(15)
        c.coords(self.gauge_number, start, baseline)
        c.itemconfigure(
            self.gauge_number,
            text=number, anchor="sw", font=self.font_number, fill=color,
        )
        c.coords(self.gauge_percent, start + num_width + gap, baseline)
        c.itemconfigure(
            self.gauge_percent,
            text="%", anchor="sw", font=self.font_percent, fill=_blend(color, TEXT, 0.2),
        )

    def _clear_status(self) -> None:
        self.canvas.delete("status")

    def _paint_status(self, level: Optional[int], text: str, color: str) -> None:
        c = self.canvas
        c.delete("status")
        font = self.font_status
        width = font.measure(text) + self.s(38)
        height = self.s(24)
        x1 = self.gcx - width / 2
        x2 = self.gcx + width / 2
        y1 = self.s(246)
        y2 = y1 + height
        self._round_rect(
            x1, y1, x2, y2, height / 2,
            fill=_blend(color, BG_TOP, 0.14),
            outline=_blend(color, BG_TOP, 0.36),
            tags="status",
        )
        c.create_oval(
            x1 + self.s(13), (y1 + y2) / 2 - self.s(2.5),
            x1 + self.s(18), (y1 + y2) / 2 + self.s(2.5),
            fill=color, outline="", tags="status",
        )
        c.create_text(
            x1 + self.s(24), (y1 + y2) / 2,
            text=text, anchor="w", font=font, fill=color, tags="status",
        )

    def _update_header_dot(self, color: str) -> None:
        self.canvas.itemconfigure(self.header_dot, fill=color)
        self.canvas.itemconfigure(
            self.header_glow, fill=_blend(color, BG_TOP, 0.16)
        )

    # ------------------------------------------------------------------
    # Controls
    # ------------------------------------------------------------------
    def _toggle_topmost(self) -> None:
        self.topmost = not self.topmost
        self.root.attributes("-topmost", self.topmost)
        self._update_pin()
        self._save_settings()

    def _update_pin(self) -> None:
        if self.topmost:
            self.canvas.itemconfigure(
                self.pin_bg, fill=_blend(TEAL, BG_TOP, 0.16), outline=_blend(TEAL, BG_TOP, 0.5)
            )
            self.canvas.itemconfigure(self.pin_text, fill=TEAL)
        else:
            self.canvas.itemconfigure(self.pin_bg, fill=SURFACE, outline=BORDER)
            self.canvas.itemconfigure(self.pin_text, fill=MUTED)

    def _toggle_auto(self) -> None:
        self.auto_refresh = not self.auto_refresh
        self._update_switch()
        self._save_settings()
        if self.auto_refresh:
            self._schedule_auto()
        else:
            self._cancel_auto()

    def _update_switch(self) -> None:
        c = self.canvas
        if self.auto_refresh:
            c.itemconfigure(self.switch_track, fill=_blend(TEAL, BG_TOP, 0.5))
            c.coords(
                self.switch_knob,
                self.s(47), self.s(561), self.s(63), self.s(577),
            )
            c.itemconfigure(self.switch_knob, fill="#F8FAFC")
            c.itemconfigure(self.auto_text, fill="#DCE6F2")
        else:
            c.itemconfigure(self.switch_track, fill="#26303D")
            c.coords(
                self.switch_knob,
                self.s(29), self.s(561), self.s(45), self.s(577),
            )
            c.itemconfigure(self.switch_knob, fill="#D7E0EC")
            c.itemconfigure(self.auto_text, fill="#AAB5C7")
        self._update_interval_label()

    def _update_interval_label(self) -> None:
        if self.interval == 0:
            label = "仅手动"
        elif self.interval < 60:
            label = f"每 {self.interval} 秒  ›"
        else:
            label = f"每 {self.interval // 60} 分钟  ›"
        self.canvas.itemconfigure(self.interval_text, text=label)

    def _cycle_interval(self) -> None:
        options = [30, 60, 300, 0]
        try:
            index = options.index(self.interval)
        except ValueError:
            index = 1
        self.interval = options[(index + 1) % len(options)]
        if self.interval == 0:
            self.auto_refresh = False
        self._update_switch()
        self._save_settings()
        if self.auto_refresh:
            self._schedule_auto()
        else:
            self._cancel_auto()

    def _cancel_auto(self) -> None:
        if self.auto_id:
            try:
                self.root.after_cancel(self.auto_id)
            except tk.TclError:
                pass
            self.auto_id = None

    def _schedule_auto(self) -> None:
        self._cancel_auto()
        if not self.auto_refresh or self.interval <= 0 or self.closed:
            return
        self.auto_id = self.root.after(self.interval * 1000, self._auto_tick)

    def _auto_tick(self) -> None:
        self.auto_id = None
        self.refresh()

    def _on_escape(self) -> None:
        if self.mode == "float":
            self._exit_float()
        else:
            self._on_close()

    def _on_close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self._save_settings()
        self._cancel_auto()
        if self.animation_id:
            try:
                self.root.after_cancel(self.animation_id)
            except tk.TclError:
                pass
        if self.poll_id:
            try:
                self.root.after_cancel(self.poll_id)
            except tk.TclError:
                pass
        self.root.destroy()


def run() -> int:
    _enable_dpi_awareness()
    if _focus_existing_window():
        return 0
    root = tk.Tk()
    BatteryApp(root)
    root.mainloop()
    return 0
