"""HUD 테마 편집기
팔레트·위젯 연결을 편집하고 툴 내부의 실제 Pico2D HUD 미리보기에 즉시 반영한다.
"""

import argparse
import colorsys
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "Tools"))

from ferrial_drive.ui.theme import COLOR_LABELS, DEFAULT_THEME_PATH, WIDGET_LABELS, save_theme, validate_theme
from theme_reference import load_theme
from Tools.hud_theme_editor.parts import PALETTE_LABELS, SHORT_LABELS, WIDGET_ROLES, delete_palette_color, palette_usages

SAMPLE = ROOT / "samples/hud_theme_editor/default_theme.json"
WORKSPACE = Path(__file__).resolve().parent / "workspace"
OUTPUT = ROOT / "output/hud_theme_editor"
PALETTE_ROW_HEIGHT = 44
PICKER_HEIGHT = 128
FALLBACK_LABEL = "Fallback"
ANY_PALETTE = object()


class ThemeEditor:
    def __init__(self, window, *, path=None, workspace=None, output=None):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk, self.window = tk, ttk, window
        self.path = Path(path) if path else DEFAULT_THEME_PATH
        self.workspace = Path(workspace) if workspace else WORKSPACE
        self.output = Path(output) if output else OUTPUT
        self.document = validate_theme(json.loads((self.path if self.path.is_file() else SAMPLE).read_text(encoding="utf-8-sig")))
        self.saved = deepcopy(self.document)
        self.fallback_colors = {role: color for role, color in json.loads(
            (ROOT / "samples/ui_unit_test_v2/ui_config.json").read_text(encoding="utf-8"))["colors"].items()
            if role not in ("energy", "energy_fill")}
        self.updating = False
        self.preview = self.preview_stream = None
        self.live_frame = self.output / "live_preview.png"
        self.control_path = self.workspace / "preview_control.json"
        self.preview_signature = None
        self.preview_image = self.preview_photo = None
        self.zoom_widget = tk.BooleanVar(value=False)
        self.selected_palette = None
        self.preview_metadata = {}
        self.preview_hits = []
        self.palette_hits = []
        self.usage_signature = None
        self.hue = 0
        self.saturation = self.value = 0
        self.pending_write = None
        self.theme = load_theme()
        self.colors = self.theme["colors"]
        self.preview_path = self.workspace / "preview_theme.json"
        self._style()
        window.title("Ferrial Drive | HUD 테마 편집기")
        window.geometry("1560x980")
        window.minsize(1280, 900)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(1, weight=1)
        window.protocol("WM_DELETE_WINDOW", self.close)
        self.status = tk.StringVar(value="팔레트 색을 편집하거나 위젯의 역할에 색을 연결한다.")
        toolbar = ttk.Frame(window, padding=16)
        toolbar.grid(row=0, column=0, sticky="ew")
        ttk.Label(toolbar, text="HUD 테마 편집기", style="Title.TLabel").pack(side="left")
        for label, command in (("열기", self.open_file), ("다른 이름으로 저장", self.save_as),
                               ("저장·게임 적용", self.save), ("편집 되돌리기", self.revert)):
            ttk.Button(toolbar, text=label, command=command).pack(side="right", padx=4)
        panes = ttk.Panedwindow(window, orient="horizontal")
        panes.grid(row=1, column=0, sticky="nsew", padx=16)
        palette_panel, widget_panel = (ttk.Frame(panes, padding=12) for _ in range(2))
        panes.add(palette_panel, weight=0)
        panes.add(widget_panel, weight=1)
        palette_panel.configure(width=334)
        ttk.Label(palette_panel, text="팔레트 · 컬러피커", style="Heading.TLabel").pack(anchor="w", pady=(0, 6))
        self.palette_hint = tk.StringVar(value="색상 칩 선택 · 방향키 이동")
        ttk.Label(palette_panel, textvariable=self.palette_hint, style="Muted.TLabel", width=30).pack(anchor="w", pady=(0, 6))
        palette_list = ttk.Frame(palette_panel)
        palette_list.pack(fill="x")
        self.palette_canvas = tk.Canvas(palette_list, width=298, height=PALETTE_ROW_HEIGHT * 6, highlightthickness=0,
                                        bg=self.colors["panel"], takefocus=True)
        palette_scroll = ttk.Scrollbar(palette_list, orient="vertical", command=self.palette_canvas.yview)
        palette_scroll.pack(side="right", fill="y")
        self.palette_canvas.configure(yscrollcommand=palette_scroll.set)
        self.palette_canvas.pack(side="left", fill="x", expand=True)
        self.palette_canvas.bind("<Configure>", lambda event: self.draw_palette())
        self.palette_canvas.bind("<Button-1>", self.click_palette)
        self.palette_canvas.bind("<Motion>", self.hover_palette)
        self.palette_canvas.bind("<MouseWheel>", lambda event: self.palette_canvas.yview_scroll(-int(event.delta / 120), "units"))
        for key, step in (("Left", -1), ("Right", 1), ("Up", -5), ("Down", 5)):
            self.palette_canvas.bind(f"<{key}>", lambda event, amount=step: self.move_palette(amount))
        row = ttk.Frame(palette_panel)
        row.pack(fill="x", pady=(6, 14))
        for label, command in (("추가", self.add_color), ("이름", self.rename_color), ("삭제", self.delete_color)):
            ttk.Button(row, text=label, command=command, width=7).pack(side="left", expand=True)
        picker_panel = ttk.Frame(palette_panel)
        self.picker_panel = picker_panel
        picker_panel.pack(fill="x")
        self.color_name = tk.StringVar()
        ttk.Label(picker_panel, textvariable=self.color_name, style="Heading.TLabel", wraplength=300).pack(anchor="w", pady=(0, 8))
        picker_surface = ttk.Frame(picker_panel)
        picker_surface.pack(fill="x")
        self.sv_canvas = tk.Canvas(picker_surface, width=258, height=PICKER_HEIGHT, highlightthickness=0, cursor="crosshair")
        self.sv_canvas.pack(side="left", fill="x", expand=True)
        self.hue_canvas = tk.Canvas(picker_surface, width=22, height=PICKER_HEIGHT, highlightthickness=0, cursor="crosshair")
        self.hue_canvas.pack(side="left", padx=(8, 0))
        for canvas, command in ((self.sv_canvas, self.pick_sv), (self.hue_canvas, self.pick_hue)):
            canvas.bind("<Button-1>", command)
            canvas.bind("<B1-Motion>", command)
        self.sv_canvas.bind("<Configure>", lambda event: self.draw_picker())
        hex_row = ttk.Frame(picker_panel)
        hex_row.pack(fill="x", pady=(10, 8))
        self.swatch = tk.Canvas(hex_row, width=38, height=28, highlightthickness=1,
                                highlightbackground=self.colors["line"], bg=self.colors["panel"])
        self.swatch.pack(side="left", padx=(0, 8))
        self.hex_value = tk.StringVar()
        hex_entry = ttk.Entry(hex_row, textvariable=self.hex_value, width=10)
        hex_entry.pack(side="left", fill="x", expand=True)
        hex_entry.bind("<Return>", lambda event: self.apply_hex())
        ttk.Button(hex_row, text="적용", command=self.apply_hex, width=4).pack(side="left", padx=(6, 0))
        self.channels = []
        for name in ("R", "G", "B"):
            channel_row = ttk.Frame(picker_panel)
            channel_row.pack(fill="x")
            ttk.Label(channel_row, text=name, width=2).pack(side="left")
            variable = tk.IntVar(value=0)
            self.channels.append(variable)
            tk.Scale(channel_row, variable=variable, from_=0, to=255, orient="horizontal", resolution=1,
                     showvalue=False, sliderlength=14, width=12,
                     command=self.slide_color, bg=self.colors["panel"], fg=self.colors["text"],
                     troughcolor=self.colors["input"], highlightthickness=0, activebackground=self.colors["accent"]).pack(side="left", fill="x", expand=True)
            ttk.Label(channel_row, textvariable=variable, width=3, anchor="e").pack(side="left")
        ttk.Label(picker_panel, text="같은 팔레트에 연결된 부위가 함께 변경된다.\n에너지 레벨·Overdrive 상태색은 별도 유지.",
                  wraplength=300, style="Muted.TLabel").pack(anchor="w", pady=(12, 0))
        widget_panel.columnconfigure(0, weight=1)
        widget_panel.rowconfigure(1, weight=1, minsize=340)
        preview_heading = ttk.Frame(widget_panel)
        preview_heading.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(preview_heading, text="HUD 미리보기", style="Heading.TLabel").pack(side="left")
        ttk.Checkbutton(preview_heading, text="선택 부위 확대", variable=self.zoom_widget, command=self.draw_preview).pack(side="right")
        self.preview_canvas = tk.Canvas(widget_panel, width=1100, height=600, bg=self.colors["background"], highlightthickness=0)
        self.preview_canvas.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        self.preview_canvas.bind("<Configure>", lambda event: self.draw_preview())
        self.preview_canvas.bind("<Button-1>", self.click_preview)
        preview_controls = ttk.Frame(widget_panel)
        preview_controls.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        for label, request in (("HUD", {"scene": "combat"}), ("메뉴", {"scene": "menu"}), ("일시정지", {"paused": True}),
                               ("명중", {"action": "damage_target"}), ("피격", {"action": "damage_player"}),
                               ("Overdrive", {"action": "overdrive"}), ("무장 전환", {"action": "swap"}),
                               ("대화", {"action": "dialogue"})):
            ttk.Button(preview_controls, text=label, command=lambda value=request: self.send_preview(value), width=0).pack(side="left", padx=2)
        self.usage_title = tk.StringVar()
        ttk.Label(widget_panel, textvariable=self.usage_title, style="Muted.TLabel").grid(row=3, column=0, sticky="w")
        self.usage_panel = ttk.Frame(widget_panel)
        self.usage_panel.grid(row=4, column=0, sticky="ew", pady=(4, 10))
        binding_panel = ttk.Frame(widget_panel)
        binding_panel.grid(row=5, column=0, sticky="ew")
        for column in (1, 3, 5):
            binding_panel.columnconfigure(column, weight=1)
        ttk.Label(binding_panel, text="편집 부위").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.widget_value = tk.StringVar(value=WIDGET_LABELS["health"])
        self.widget_combo = ttk.Combobox(binding_panel, textvariable=self.widget_value, values=list(WIDGET_LABELS.values()), state="readonly", width=14)
        self.widget_combo.grid(row=0, column=1, sticky="ew")
        self.widget_combo.bind("<<ComboboxSelected>>", lambda event: self.select_widget())
        ttk.Label(binding_panel, text="색 역할").grid(row=0, column=2, padx=(12, 6))
        self.role_value = tk.StringVar()
        self.role_combo = ttk.Combobox(binding_panel, textvariable=self.role_value, state="readonly", width=13)
        self.role_combo.grid(row=0, column=3, sticky="ew")
        self.role_combo.bind("<<ComboboxSelected>>", self.select_binding)
        ttk.Label(binding_panel, text="연결 색").grid(row=0, column=4, padx=(12, 6))
        self.binding_value = tk.StringVar()
        self.binding_combo = ttk.Combobox(binding_panel, textvariable=self.binding_value, state="readonly", width=13)
        self.binding_combo.grid(row=0, column=5, sticky="ew")
        self.binding_combo.bind("<<ComboboxSelected>>", lambda event: self.assign_color())
        binding_actions = ttk.Frame(widget_panel)
        binding_actions.grid(row=6, column=0, sticky="ew", pady=(6, 0))
        self.binding_description = tk.StringVar()
        ttk.Label(binding_actions, textvariable=self.binding_description, style="Muted.TLabel").pack(side="left")
        ttk.Button(binding_actions, text="선택 색 연결", command=self.assign_selected_palette).pack(side="right")
        footer = ttk.Frame(window, padding=(16, 8))
        footer.grid(row=2, column=0, sticky="ew")
        self.real_assets = tk.BooleanVar(value=False)
        ttk.Checkbutton(footer, text="실제 게임 에셋 사용", variable=self.real_assets).pack(side="left")
        ttk.Button(footer, text="미리보기 다시 시작", command=self.start_preview).pack(side="left", padx=12)
        ttk.Button(footer, text="미리보기 종료", command=self.stop_preview).pack(side="left")
        ttk.Label(footer, text="미리보기의 강조 영역을 클릭하여 부위 선택", style="Muted.TLabel").pack(side="right")
        ttk.Label(window, textvariable=self.status, style="Muted.TLabel", padding=(16, 6), wraplength=1200).grid(row=3, column=0, sticky="ew")
        window.bind("<Control-s>", lambda event: self.save())
        window.bind("<Control-o>", lambda event: self.open_file())
        initial_palette = self.document["widgets"].get("health", {}).get("accent",
                            self.document["widgets"].get("global", {}).get("accent"))
        self.refresh_palette(initial_palette)
        self.refresh_bindings()
        self.select_palette()
        self.write_preview()
        window.after(300, self.poll_preview)

    def _style(self):
        import ctypes
        from PIL import ImageFont
        colors = self.colors
        fonts = {}
        for role, config in self.theme["fonts"].items():
            path = ROOT / "data/fonts" / config["path"]
            if os.name == "nt":
                ctypes.windll.gdi32.AddFontResourceExW(str(path), 0x10, None)
            family = ImageFont.truetype(str(path), config["size"]).getname()[0]
            fonts[role] = (family, -config["size"])
        self.window.configure(bg=colors["background"])
        self.fonts = fonts
        style = self.ttk.Style(self.window)
        style.theme_use("clam")
        style.configure(".", background=colors["panel"], foreground=colors["text"], font=fonts["body"])
        style.configure("TFrame", background=colors["panel"])
        style.configure("TLabel", background=colors["panel"], foreground=colors["text"])
        style.configure("Title.TLabel", font=fonts["title"], foreground=colors["accent"])
        style.configure("Heading.TLabel", font=fonts["title"])
        style.configure("Muted.TLabel", foreground=colors["muted"], font=fonts["small"])
        style.configure("TButton", background=colors["button"], foreground=colors["button_text"], padding=(10, 7))
        style.map("TButton", background=[("active", colors["button_hover"])])
        style.configure("Treeview", background=colors["input"], fieldbackground=colors["input"], rowheight=29)
        style.map("Treeview", background=[("selected", colors["selected"])], foreground=[("selected", colors["text"])])
        style.configure("TEntry", fieldbackground=colors["input"], foreground=colors["text"])
        style.configure("TCombobox", fieldbackground=colors["input"], foreground=colors["text"])
        style.map("TCombobox", fieldbackground=[("readonly", colors["input"])],
                  foreground=[("readonly", colors["text"])], selectbackground=[("readonly", colors["selected"])])
        self.window.option_add("*TCombobox*Listbox.background", colors["input"])
        self.window.option_add("*TCombobox*Listbox.foreground", colors["text"])

    def palette_name(self):
        return self.selected_palette

    def widget_key(self):
        return next(key for key, value in WIDGET_LABELS.items() if value == self.widget_value.get())

    def refresh_palette(self, selected=None):
        selected = selected or self.palette_name()
        if selected not in self.document["palette"]:
            selected = next(iter(self.document["palette"]), None)
        self.selected_palette = selected
        self.binding_combo["values"] = [FALLBACK_LABEL, *(COLOR_LABELS.get(name, name) for name in self.document["palette"])]
        self.select_palette()

    def draw_palette(self):
        from tkinter.font import Font
        canvas = self.palette_canvas
        canvas.delete("all")
        self.palette_hits = []
        cell_width = max(298, canvas.winfo_width()) / 5
        font = Font(root=self.window, font=self.fonts["small"])
        if not self.document["palette"]:
            canvas.create_text(149, 110, text="팔레트 없음\nFallback 색 사용", justify="center",
                               fill=self.colors["muted"], font=self.fonts["body"])
        for index, (name, color) in enumerate(self.document["palette"].items()):
            x, y = (index % 5) * cell_width + 3, (index // 5) * PALETTE_ROW_HEIGHT + 3
            right = x + cell_width - 7
            canvas.create_rectangle(x, y, right, y + 27, fill=color, outline=self.colors["line"])
            if name == self.palette_name():
                canvas.create_rectangle(x - 2, y - 2, right + 2, y + 29, outline=self.colors["text"], width=2)
                ink = "#101F27" if sum(int(color[i:i + 2], 16) for i in (1, 3, 5)) > 400 else "#D8E6ED"
                canvas.create_text((x + right) / 2, y + 13, text="✓", fill=ink, font=self.fonts["small"])
            label = PALETTE_LABELS.get(name, name)
            short = label
            if font.measure(short) > cell_width - 7:
                while label and font.measure(label + "…") > cell_width - 7:
                    label = label[:-1]
                short = label + "…"
            canvas.create_text((x + right) / 2, y + 36, text=short, fill=self.colors["text"], font=self.fonts["small"])
            self.palette_hits.append((x, y, right, y + 41, name))
        canvas.configure(scrollregion=(0, 0, canvas.winfo_width(), ((len(self.palette_hits) + 4) // 5) * PALETTE_ROW_HEIGHT))

    def palette_at(self, event):
        x, y = self.palette_canvas.canvasx(event.x), self.palette_canvas.canvasy(event.y)
        return next((name for left, top, right, bottom, name in self.palette_hits
                     if left <= x <= right and top <= y <= bottom), None)

    def click_palette(self, event):
        name = self.palette_at(event)
        if name:
            self.palette_canvas.focus_set()
            self.selected_palette = name
            self.select_palette()

    def hover_palette(self, event):
        name = self.palette_at(event)
        self.palette_hint.set(f"{COLOR_LABELS.get(name, name)} · {self.document['palette'][name]}" if name else "색상 칩 선택 · 방향키 이동")

    def move_palette(self, amount):
        names = list(self.document["palette"])
        if not names:
            return "break"
        current = names.index(self.palette_name()) if self.palette_name() in names else 0
        index = max(0, min(len(names) - 1, current + amount))
        self.selected_palette = names[index]
        self.select_palette()
        top = self.palette_canvas.canvasy(0)
        row_top, row_bottom = (index // 5) * PALETTE_ROW_HEIGHT, (index // 5 + 1) * PALETTE_ROW_HEIGHT
        if row_top < top or row_bottom > top + self.palette_canvas.winfo_height():
            self.palette_canvas.yview_moveto(row_top / (((len(names) + 4) // 5) * PALETTE_ROW_HEIGHT))
        return "break"

    def select_palette(self, event=None):
        name = self.palette_name()
        if name is None:
            role = self.role_key() if hasattr(self, "available_roles") else "text"
            self.show_picker(self.fallback_colors.get(role, self.fallback_colors["text"]),
                             f"Fallback · {COLOR_LABELS.get(role, role) or '기본색'}")
            self.draw_palette()
            self.draw_picker()
            self.refresh_usage()
            self.draw_preview()
            return
        color = self.document["palette"][name]
        self.show_picker(color, COLOR_LABELS.get(name, name))
        if hasattr(self, "available_roles"):
            bindings = {**self.document["widgets"].get("global", {}),
                        **self.document["widgets"].get(self.widget_key(), {})}
            if bindings.get(self.role_key()) != name:
                label = next((label for label, role in self.available_roles.items() if bindings.get(role) == name), None)
                if label is not None:
                    self.role_value.set(label)
                    self.select_binding(sync_palette=False)
        self.draw_palette()
        self.draw_picker()
        self.refresh_usage()
        self.draw_preview()

    def show_picker(self, color, title):
        self.updating = True
        self.color_name.set(title)
        self.hex_value.set(color)
        self.swatch.configure(bg=color)
        for variable, index in zip(self.channels, (1, 3, 5)):
            variable.set(int(color[index:index + 2], 16))
        self.hue, self.saturation, self.value = colorsys.rgb_to_hsv(*(variable.get() / 255 for variable in self.channels))
        self.updating = False

    def draw_picker(self):
        from PIL import Image, ImageTk
        width, height = max(2, self.sv_canvas.winfo_width()), PICKER_HEIGHT
        image = Image.new("RGB", (width, height))
        image.putdata([tuple(round(channel * 255) for channel in colorsys.hsv_to_rgb(self.hue, x / (width - 1), 1 - y / (height - 1)))
                       for y in range(height) for x in range(width)])
        self.sv_photo = ImageTk.PhotoImage(image, master=self.window)
        self.sv_canvas.delete("all")
        self.sv_canvas.create_image(0, 0, anchor="nw", image=self.sv_photo)
        x, y = self.saturation * (width - 1), (1 - self.value) * (height - 1)
        self.sv_canvas.create_oval(x - 5, y - 5, x + 5, y + 5, outline="black", width=3)
        self.sv_canvas.create_oval(x - 4, y - 4, x + 4, y + 4, outline="white", width=1)
        self.hue_canvas.delete("all")
        for y in range(height):
            color = "#" + "".join(f"{round(channel * 255):02X}" for channel in colorsys.hsv_to_rgb(y / (height - 1), 1, 1))
            self.hue_canvas.create_line(0, y, 22, y, fill=color)
        y = self.hue * (height - 1)
        self.hue_canvas.create_rectangle(0, y - 2, 21, y + 2, outline="white", width=2)

    def pick_sv(self, event):
        self.saturation = max(0, min(1, event.x / max(1, self.sv_canvas.winfo_width() - 1)))
        self.value = 1 - max(0, min(1, event.y / (PICKER_HEIGHT - 1)))
        self.apply_hsv()

    def pick_hue(self, event):
        self.hue = max(0, min(1, event.y / (PICKER_HEIGHT - 1)))
        self.apply_hsv()

    def apply_hsv(self):
        self.set_color("#" + "".join(f"{round(channel * 255):02X}" for channel in colorsys.hsv_to_rgb(self.hue, self.saturation, self.value)))

    def set_color(self, color):
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            self.status.set("색상은 #RRGGBB 형식으로 입력한다.")
            return
        name = self.palette_name()
        if name is None:
            role = self.role_key()
            if role is None:
                return
            widget = self.widget_key()
            base = f"{SHORT_LABELS[widget]} 색"
            name, number = base, 2
            while name in self.document["palette"]:
                name, number = f"{base} {number}", number + 1
            self.document["palette"][name] = color.upper()
            self.document["widgets"].setdefault(widget, {})[role] = name
            self.selected_palette = name
            self.binding_combo["values"] = [FALLBACK_LABEL, *(COLOR_LABELS.get(key, key) for key in self.document["palette"])]
            self.color_name.set(name)
        if name:
            self.document["palette"][name] = color.upper()
            self.swatch.configure(bg=color)
            self.hex_value.set(color.upper())
            self.updating = True
            for variable, index in zip(self.channels, (1, 3, 5)):
                variable.set(int(color[index:index + 2], 16))
            self.updating = False
            self.draw_palette()
            self.draw_picker()
            self.changed()

    def slide_color(self, value=None):
        if not self.updating:
            hue, self.saturation, self.value = colorsys.rgb_to_hsv(*(variable.get() / 255 for variable in self.channels))
            if self.saturation:
                self.hue = hue
            self.set_color("#" + "".join(f"{variable.get():02X}" for variable in self.channels))

    def apply_hex(self):
        self.set_color(self.hex_value.get().strip())
        self.select_palette()

    def choose_color(self):
        from tkinter.colorchooser import askcolor
        color = askcolor(self.hex_value.get(), parent=self.window, title="팔레트 색 선택")[1]
        if color:
            self.set_color(color)
            self.select_palette()

    def refresh_bindings(self):
        widget = self.widget_key()
        inherited = self.document["widgets"].get("global", {})
        supported = set(self.fallback_colors) if widget == "global" else set(WIDGET_ROLES[widget])
        supported.update(item["role"] for item in self.preview_metadata.get("regions", []) if item["widget"] == widget)
        supported.update(self.document["widgets"].get(widget, {}))
        self.available_roles = {COLOR_LABELS.get(role, role): role for role in self.fallback_colors if role in supported}
        self.role_combo["values"] = list(self.available_roles)
        if self.role_value.get() not in self.available_roles:
            self.role_value.set(next(iter(self.available_roles), ""))
        self.select_binding(sync_palette=False)

    def select_widget(self):
        self.refresh_bindings()
        self.select_binding()
        self.draw_preview()

    def role_key(self):
        return self.available_roles.get(self.role_value.get())

    def select_binding(self, event=None, *, sync_palette=True):
        role = self.role_key()
        if role is None:
            return
        name = self.document["widgets"].get(self.widget_key(), {}).get(role)
        self.binding_value.set(COLOR_LABELS.get(name, name) if name else FALLBACK_LABEL)
        effective = self.document["widgets"].get("global", {}).get(role) if name is None else name
        color = self.document["palette"].get(effective, self.fallback_colors.get(role))
        suffix = " · 전체 기본값 상속" if name is None and effective else " · Fallback 기본색" if effective is None else ""
        self.binding_description.set(f"{color}{suffix}")
        if sync_palette:
            self.selected_palette = effective
            self.select_palette()

    def assign_color(self):
        role = self.role_key()
        if role is None:
            self.status.set("색을 연결할 위젯 역할을 먼저 선택한다.")
            return
        widget, name = self.widget_key(), self.binding_value.get()
        name = next((key for key in self.document["palette"] if COLOR_LABELS.get(key, key) == name), name)
        if name in (FALLBACK_LABEL, "상속"):
            self.document["widgets"].setdefault(widget, {}).pop(role, None)
        elif name in self.document["palette"]:
            self.document["widgets"].setdefault(widget, {})[role] = name
        self.changed()
        self.select_binding()

    def assign_selected_palette(self):
        name = self.palette_name()
        if name is not None:
            self.binding_value.set(COLOR_LABELS.get(name, name))
            self.assign_color()

    def add_color(self):
        from tkinter.simpledialog import askstring
        name = askstring("팔레트 색 추가", "색 이름", parent=self.window)
        if name and name.strip() and name.strip() not in self.document["palette"]:
            name = name.strip()
            self.document["palette"][name] = self.hex_value.get()
            self.refresh_palette(name)
            self.changed()

    def rename_color(self):
        from tkinter.simpledialog import askstring
        old = self.palette_name()
        if old is None:
            self.status.set("이름을 바꿀 팔레트 색을 선택한다.")
            return
        name = askstring("팔레트 이름", "새 이름", initialvalue=old, parent=self.window)
        if not name or not name.strip() or name == old:
            return
        name = name.strip()
        if name in self.document["palette"]:
            self.status.set("이미 사용 중인 팔레트 이름이다.")
            return
        self.document["palette"][name] = self.document["palette"].pop(old)
        for bindings in self.document["widgets"].values():
            for role, value in tuple(bindings.items()):
                if value == old:
                    bindings[role] = name
        self.refresh_palette(name)
        self.changed()

    def delete_color(self):
        name = self.palette_name()
        if name is None:
            return
        count = delete_palette_color(self.document, name)
        self.selected_palette = None
        self.binding_combo["values"] = [FALLBACK_LABEL, *(COLOR_LABELS.get(key, key) for key in self.document["palette"])]
        self.changed()
        self.select_binding()
        self.draw_palette()
        self.status.set(f"{COLOR_LABELS.get(name, name)} 삭제 · {count}개 연결 Fallback 전환 · 저장·게임 적용 전")

    def changed(self):
        self.refresh_bindings()
        self.refresh_usage()
        self.draw_preview()
        self.status.set("미리보기 반영 중 · 저장·게임 적용 전에는 실제 게임 테마를 변경하지 않는다.")
        if self.pending_write:
            self.window.after_cancel(self.pending_write)
        self.pending_write = self.window.after(100, self.write_preview)

    def matching_regions(self, *, palette=ANY_PALETTE, widget=None):
        result = []
        for item in self.preview_metadata.get("regions", []):
            if widget is not None and item["widget"] != widget:
                continue
            # 렌더 직후의 원본 메타데이터에 현재 편집 연결을 해석하여 즉시 강조한다.
            bindings = {**self.document["widgets"].get("global", {}),
                        **self.document["widgets"].get(item["widget"], {})}
            if palette is ANY_PALETTE or bindings.get(item["role"]) == palette:
                result.append(item)
        return result

    def refresh_usage(self):
        name = self.palette_name()
        regions = self.preview_metadata.get("regions", [])
        usages = palette_usages(self.document, name, regions)
        visible = {item["widget"] for item in self.matching_regions(palette=name)}
        if name is None:
            widget = self.widget_key()
            usages = {widget: [self.role_key()]} if self.role_key() else {}
            visible.intersection_update({widget})
        signature = (name, tuple((key, tuple(roles)) for key, roles in usages.items()), tuple(sorted(visible)))
        if signature == self.usage_signature:
            return
        self.usage_signature = signature
        for child in self.usage_panel.winfo_children():
            child.destroy()
        self.usage_title.set(f"{COLOR_LABELS.get(name, name) if name else FALLBACK_LABEL} 적용 부위 {len(usages)} · 현재 화면 {len(visible)} · 부위 버튼으로 선택")
        for index, (widget, roles) in enumerate(usages.items()):
            label = SHORT_LABELS[widget] + (" ●" if widget in visible else "")
            button = self.ttk.Button(self.usage_panel, text=label, width=0,
                                     command=lambda key=widget, role=roles[0]: self.focus_usage(key, role))
            button.grid(row=index // 7, column=index % 7, sticky="ew", padx=(0, 4), pady=2)
        if not usages:
            self.ttk.Label(self.usage_panel, text="연결된 사용처 없음 · 부위와 색 역할을 고른 뒤 ‘선택 색 연결’ 사용",
                           style="Muted.TLabel").grid(row=0, column=0, sticky="w", pady=8)

    def focus_usage(self, widget, role):
        self.widget_value.set(WIDGET_LABELS[widget])
        self.refresh_bindings()
        self.role_value.set(COLOR_LABELS.get(role, role))
        self.select_binding(sync_palette=self.palette_name() is None)
        self.draw_preview()
        if not self.matching_regions(widget=widget):
            self.status.set(f"{WIDGET_LABELS[widget]} · 현재 화면에 표시되지 않는다. 메뉴·명중·대화 등 해당 상태에서 확인한다.")

    def write_preview(self):
        self.pending_write = None
        try:
            save_theme(self.preview_path, self.document)
        except (OSError, ValueError) as error:
            self.status.set(str(error))

    def save(self):
        try:
            save_theme(self.path, self.document)
            save_theme(DEFAULT_THEME_PATH, self.document)
            self.saved = deepcopy(self.document)
            self.status.set(f"저장·게임 적용 완료 · {self.path}")
        except (OSError, ValueError) as error:
            self.status.set(str(error))

    def save_as(self):
        from tkinter.filedialog import asksaveasfilename
        path = asksaveasfilename(parent=self.window, title="테마 저장", defaultextension=".json", filetypes=[("테마", "*.json")])
        if path:
            try:
                save_theme(path, self.document)
                self.path, self.saved = Path(path), deepcopy(self.document)
                self.status.set(f"테마 사본 저장 완료 · {path}")
            except (OSError, ValueError) as error:
                self.status.set(str(error))

    def open_file(self):
        from tkinter.filedialog import askopenfilename
        path = askopenfilename(parent=self.window, title="테마 열기", filetypes=[("테마", "*.json")])
        if not path:
            return
        try:
            document = validate_theme(json.loads(Path(path).read_text(encoding="utf-8-sig")))
        except (OSError, ValueError) as error:
            self.status.set(str(error))
            return
        self.path, self.document = Path(path), document
        self.saved = deepcopy(document)
        self.refresh_palette()
        self.changed()

    def revert(self):
        self.document = deepcopy(self.saved)
        self.refresh_palette()
        self.changed()

    def start_preview(self, *, frames=None, capture=None):
        self.stop_preview()
        self.write_preview()
        self.preview_image = None
        self.preview_metadata = {}
        self.preview_hits = []
        try:
            self.preview_signature = (self.live_frame.stat().st_mtime_ns,
                                      self.live_frame.with_suffix(".json").stat().st_mtime_ns)
        except OSError:
            self.preview_signature = None
        self.draw_preview()
        self.output.mkdir(parents=True, exist_ok=True)
        command = [sys.executable, "-B", str(ROOT / "tests/sword_movement_test.py"), "--mute",
                   "--theme-file", str(self.preview_path), "--settings-file", str(self.workspace / "preview_settings.json"),
                   "--script", str(ROOT / "samples/hud_theme_editor/preview_input.json"),
                   "--report", str(self.output / "preview_report.json"), "--preview-frame", str(self.live_frame),
                   "--preview-control", str(self.control_path), "--preview-hidden"]
        if not self.real_assets.get():
            command.append("--demo")
        if frames:
            command.extend(("--frames", str(frames)))
        if capture:
            command.extend(("--capture", str(capture), "--capture-frame", str(max(1, (frames or 120) - 1))))
        self.preview_stream = (self.output / "preview.log").open("w", encoding="utf-8")
        environment = os.environ.copy()
        environment["PYTHONUTF8"] = "1"
        self.preview = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=self.preview_stream,
                                        stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.send_preview({"scene": "combat"})
        self.status.set("툴 안에서 실제 Pico2D HUD를 미리본다. 편집한 색은 자동 반영한다.")

    def send_preview(self, request):
        self.workspace.mkdir(parents=True, exist_ok=True)
        temporary = self.control_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.control_path)

    def draw_preview(self):
        canvas = self.preview_canvas
        canvas.delete("all")
        self.preview_hits = []
        width, height = max(1, canvas.winfo_width()), max(1, canvas.winfo_height())
        if self.preview_image is None:
            canvas.create_text(width / 2, height / 2, text="HUD 미리보기 준비 중", fill=self.colors["muted"], font=self.fonts["body"])
            return
        from PIL import Image, ImageTk
        image = self.preview_image.copy()
        image_width, image_height = image.size
        crop = (0, 0, image_width, image_height)
        if self.zoom_widget.get():
            areas = [item["bounds"] for item in self.matching_regions(widget=self.widget_key())]
            if areas:
                crop = (max(0, min(box[0] for box in areas) - 30), max(0, min(box[1] for box in areas) - 36),
                        min(image_width, max(box[2] for box in areas) + 30), min(image_height, max(box[3] for box in areas) + 30))
                image = image.crop(crop)
        scale = min(width / image.width, height / image.height)
        image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.Resampling.LANCZOS)
        self.preview_photo = ImageTk.PhotoImage(image, master=self.window)
        origin_x, origin_y = (width - image.width) / 2, (height - image.height) / 2
        canvas.create_image(origin_x, origin_y, anchor="nw", image=self.preview_photo)
        # 선택 색이 실제로 제출된 그리기 범위를 부위별로 합쳐 표시한다.
        groups = {}
        selected_regions = self.matching_regions(palette=self.palette_name())
        if self.palette_name() is None:
            selected_regions = [item for item in selected_regions
                                if item["widget"] == self.widget_key() and item["role"] == self.role_key()]
        for item in selected_regions:
            widget = item["widget"]
            left, top, right, bottom = item["bounds"]
            previous = groups.get(widget, (left, top, right, bottom))
            groups[widget] = (min(left, previous[0]), min(top, previous[1]), max(right, previous[2]), max(bottom, previous[3]))
        label_boxes = []
        for widget, (left, top, right, bottom) in groups.items():
            left, top, right, bottom = max(left, crop[0]), max(top, crop[1]), min(right, crop[2]), min(bottom, crop[3])
            if right <= left or bottom <= top:
                continue
            x1, y1 = origin_x + (left - crop[0]) * scale, origin_y + (top - crop[1]) * scale
            x2, y2 = origin_x + (right - crop[0]) * scale, origin_y + (bottom - crop[1]) * scale
            ink = self.colors["text"] if widget == self.widget_key() else self.colors["accent"]
            canvas.create_rectangle(x1 - 3, y1 - 3, x2 + 3, y2 + 3, outline=self.colors["background"], width=5)
            canvas.create_rectangle(x1 - 3, y1 - 3, x2 + 3, y2 + 3, outline=ink, width=2)
            label = canvas.create_text(max(4, x1), max(4, y1 - 23), anchor="nw", text=SHORT_LABELS[widget],
                                       fill=self.colors["background"], font=self.fonts["small"])
            box = canvas.bbox(label)
            dx = min(0, width - box[2] - 4)
            canvas.move(label, dx, 0)
            box = canvas.bbox(label)
            while any(box[0] < old[2] and box[2] > old[0] and box[1] < old[3] and box[3] > old[1] for old in label_boxes) and box[1] > 20:
                canvas.move(label, 0, -20)
                box = canvas.bbox(label)
            background = canvas.create_rectangle(box[0] - 3, box[1] - 1, box[2] + 3, box[3] + 1, fill=ink, outline="")
            canvas.tag_raise(label, background)
            label_boxes.append(box)
            self.preview_hits.append((x1 - 4, y1 - 4, x2 + 4, y2 + 4, widget))
            self.preview_hits.append((*box, widget))
        self.preview_transform = origin_x, origin_y, scale, crop

    def click_preview(self, event):
        hits = [item for item in self.preview_hits if item[0] <= event.x <= item[2] and item[1] <= event.y <= item[3]]
        if hits:
            widget = min(hits, key=lambda item: (item[2] - item[0]) * (item[3] - item[1]))[4]
            regions = self.matching_regions(palette=self.palette_name(), widget=widget)
            if regions:
                role = self.role_key() if self.palette_name() is None else regions[0]["role"]
                self.focus_usage(widget, role)

    def stop_preview(self):
        if self.preview is not None and self.preview.poll() is None:
            self.preview.terminate()
            try:
                self.preview.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.preview.kill()
                self.preview.wait()
        self.preview = None
        if self.preview_stream:
            self.preview_stream.close()
            self.preview_stream = None

    def poll_preview(self):
        try:
            metadata_path = self.live_frame.with_suffix(".json")
            signature = self.live_frame.stat().st_mtime_ns, metadata_path.stat().st_mtime_ns
            if signature != self.preview_signature:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                if metadata.get("image_signature") != signature[0]:
                    raise OSError("미리보기 프레임 교체 중")
                from PIL import Image
                with Image.open(self.live_frame) as image:
                    self.preview_image = image.copy()
                self.preview_metadata = metadata
                self.preview_signature = signature
                self.refresh_usage()
                self.draw_preview()
        except (OSError, ValueError):
            pass
        if self.preview is not None and self.preview.poll() is not None:
            code = self.preview.returncode
            self.stop_preview()
            self.status.set("미리보기 종료" if code == 0 else f"미리보기 실행 오류 · {self.output / 'preview.log'}")
        self.window.after(100, self.poll_preview)

    def close(self):
        self.stop_preview()
        self.window.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--theme", type=Path)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--verify", type=Path, help="별도 미리보기·편집 화면·변경 테마 검증 결과 폴더")
    args = parser.parse_args()
    if args.self_check:
        data = validate_theme(json.loads((args.theme or SAMPLE).read_text(encoding="utf-8-sig")))
        print(json.dumps({"palette": len(data["palette"]), "widgets": len(data["widgets"])}, ensure_ascii=False))
        return
    import tkinter as tk
    window = tk.Tk()
    app = ThemeEditor(window, path=args.theme,
                      workspace=args.verify / "workspace" if args.verify else None,
                      output=args.verify / "runtime" if args.verify else None)
    if args.verify:
        from Tools.hud_theme_editor.verification import schedule_verification
        schedule_verification(app, args.verify)
    else:
        window.after(300, app.start_preview)
    try:
        window.mainloop()
    finally:
        app.stop_preview()


if __name__ == "__main__":
    main()
