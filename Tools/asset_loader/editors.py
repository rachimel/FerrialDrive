"""제작 설정·프레임 조립 입력창. 처리와 저장은 화면 밖의 모듈에 위임한다."""

from datetime import datetime
from math import ceil, isfinite
import os
from pathlib import Path
import tempfile
from uuid import uuid4

from .assembly import SpriteAssembly
from .production import WORKSPACE, render_config
from Tools.theme_reference import load_theme


def editor_window(title):
    import tkinter as tk
    from tkinter import ttk

    theme = load_theme()
    colors = theme["colors"]
    root = tk.Tk()
    root.title(title)
    root.configure(bg=colors["background"])
    root.resizable(True, True)
    style = ttk.Style(root)
    style.theme_use("clam")
    font = ("TkDefaultFont", -theme["fonts"]["small"]["size"])
    if os.name == "nt":
        import ctypes
        import pico2d.pico2d as pico
        settings = theme["fonts"]["small"]
        path = Path(__file__).resolve().parents[2] / "data/fonts" / settings["path"]
        gdi = ctypes.WinDLL("gdi32")
        gdi.AddFontResourceExW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p]
        gdi.RemoveFontResourceExW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p]
        if gdi.AddFontResourceExW(str(path), 0x10, None):
            def release(event):
                if event.widget is root:
                    gdi.RemoveFontResourceExW(str(path), 0x10, None)
            root.bind("<Destroy>", release, add=True)
            pico.TTF_Init()
            face = pico.TTF_OpenFont(str(path).encode("utf-8"), settings["size"])
            try:
                if face:
                    family = pico.TTF_FontFaceFamilyName(face)
                    if family:
                        font = (family.decode("utf-8"), -settings["size"])
            finally:
                if face:
                    pico.TTF_CloseFont(face)
                pico.TTF_Quit()
    style.configure(".", font=font)
    style.configure("TFrame", background=colors["background"])
    style.configure("TLabel", background=colors["background"], foreground=colors["text"])
    style.configure("TCheckbutton", background=colors["background"], foreground=colors["text"])
    style.configure("TEntry", fieldbackground=colors["input"], foreground=colors["text"])
    style.configure("TButton", background=colors["button"], foreground=colors["button_text"], padding=6)
    style.configure("Treeview", background=colors["panel"], fieldbackground=colors["panel"], foreground=colors["text"], rowheight=28)
    style.map("Treeview", background=[("selected", colors["selected"])])
    content = ttk.Frame(root, padding=20)
    content.pack(fill="both", expand=True)
    content.columnconfigure(1, weight=1)
    return root, content


def render_dialog(asset_id, source=None):
    import tkinter as tk
    from tkinter import filedialog, ttk

    root, content = editor_window("3D 프리렌더")
    result = None
    fields = {}
    defaults = [("source", "모델 (.blend)", str(source) if source else ""), ("root", "모델 루트", ""),
        ("asset_id", "에셋 ID", asset_id or "model"), ("animation", "동작 이름", "idle"),
        ("frames", "Blender 프레임", "1,3,5,7"), ("fps", "FPS", "8"),
        ("width", "너비 (px)", "160"), ("height", "높이 (px)", "160"),
        ("scale", "정사영 범위", "4.5"), ("samples", "렌더 샘플", "32")]
    for row, (key, label, default) in enumerate(defaults):
        ttk.Label(content, text=label).grid(row=row, column=0, sticky="w", padx=(0, 20), pady=5)
        variable = tk.StringVar(value=default)
        fields[key] = variable
        ttk.Entry(content, textvariable=variable, width=40).grid(row=row, column=1, sticky="ew", pady=5)
    def browse():
        path = filedialog.askopenfilename(parent=root, filetypes=[("Blender 모델", "*.blend")])
        if path:
            fields["source"].set(path)
    ttk.Button(content, text="…", command=browse, width=3).grid(row=0, column=2, padx=(8, 0))
    sample, camera, auto_fit = tk.BooleanVar(value=False), tk.BooleanVar(value=False), tk.BooleanVar(value=True)
    ttk.Checkbutton(content, text="기본 도형 샘플", variable=sample).grid(row=10, column=1, sticky="w", pady=5)
    def camera_mode():
        auto_fit.set(not camera.get())
        automatic.state(["disabled"] if camera.get() else ["!disabled"])
    ttk.Checkbutton(content, text="모델에 저장된 카메라 사용", variable=camera,
                    command=camera_mode).grid(row=11, column=1, sticky="w", pady=5)
    automatic = ttk.Checkbutton(content, text="기체·그림자 자동 맞춤", variable=auto_fit)
    automatic.grid(row=12, column=1, sticky="w", pady=5)
    error = tk.StringVar()
    ttk.Label(content, textvariable=error, wraplength=480).grid(row=13, column=0, columnspan=3, sticky="w", pady=8)
    def accept():
        nonlocal result
        try:
            source = None if sample.get() else Path(fields["source"].get()).resolve()
            if source is not None and (source.suffix.lower() != ".blend" or not source.is_file()):
                raise ValueError("저장된 .blend 모델을 선택한다.")
            config = render_config(asset_id=fields["asset_id"].get(), animation_name=fields["animation"].get(),
                frames=fields["frames"].get(), fps=fields["fps"].get(), width=fields["width"].get(),
                height=fields["height"].get(), ortho_scale=fields["scale"].get(), samples=fields["samples"].get(),
                root_object=fields["root"].get(), use_scene_camera=camera.get(), auto_fit=auto_fit.get())
            result = source, config
            root.destroy()
        except (OSError, ValueError) as problem:
            error.set(str(problem))
    ttk.Button(content, text="렌더 시작", command=accept).grid(row=14, column=1, sticky="e")
    root.bind("<Escape>", lambda _: root.destroy())
    root.mainloop()
    return result


def assembly_dialog(definition, image_size, clip_name, asset_id):
    import tkinter as tk
    from tkinter import ttk

    assembly = SpriteAssembly(definition, image_size=image_size)
    root, content = editor_window("애니메이션 조립")
    root.minsize(650, 540)
    result = None
    source = tk.StringVar(value=clip_name)
    name, fps, px, py = (tk.StringVar() for _ in range(4))
    together = tk.BooleanVar(value=True)
    error = tk.StringVar()
    selection = ttk.Combobox(content, values=assembly.names, textvariable=source, state="readonly")
    ttk.Label(content, text="원본 동작 / 방향").grid(row=0, column=0, sticky="w", padx=(0, 20))
    selection.grid(row=0, column=1, sticky="ew", pady=6)
    for row, (label, variable) in enumerate((("동작 이름", name), ("FPS", fps), ("피봇 X (px)", px), ("피봇 Y (px)", py)), 1):
        ttk.Label(content, text=label).grid(row=row, column=0, sticky="w")
        ttk.Entry(content, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=6)
    ttk.Checkbutton(content, text="모든 방향에 적용", variable=together,
                    state="normal" if assembly.bundle else "disabled").grid(row=5, column=1, sticky="w", pady=6)
    tree = ttk.Treeview(content, columns=("index", "rect"), show="headings", selectmode="extended", height=8)
    tree.heading("index", text="원본 프레임")
    tree.heading("rect", text="영역 (x, y, w, h)")
    tree.column("index", width=110, stretch=False)
    tree.column("rect", width=280)
    tree.grid(row=6, column=0, columnspan=3, sticky="nsew", pady=8)
    content.rowconfigure(6, weight=1)
    ttk.Label(content, text="드래그 순서 변경 · Delete 제외 · Ctrl+D 반복").grid(row=7, column=0, columnspan=3, sticky="w")
    ttk.Label(content, textvariable=error, wraplength=680).grid(row=8, column=0, columnspan=3, sticky="w", pady=10)
    colors = load_theme()["colors"]
    canvas = tk.Canvas(content, width=240, height=200, bg=colors["input"], highlightthickness=0)
    canvas.grid(row=0, column=2, rowspan=5, padx=(20, 0))
    playing = tk.BooleanVar(value=True)
    ttk.Checkbutton(content, text="재생", variable=playing).grid(row=5, column=2, sticky="w", padx=(20, 0))
    # Tk가 직접 읽지 못하는 JPG/BMP도 기존 SDL 이미지 경로로 변환한다.
    import pico2d.pico2d as pico
    from .production import WORKSPACE
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="preview-", dir=WORKSPACE) as directory:
        surface = pico.IMG_Load(str(assembly.images["body"]).encode("utf-8"))
        try:
            if not surface or pico.IMG_SavePNG(surface, str(Path(directory) / "atlas.png").encode("utf-8")) != 0:
                root.destroy()
                raise OSError("조립 미리보기 이미지 로딩 실패")
            atlas = tk.PhotoImage(file=str(Path(directory) / "atlas.png"), master=root)
        finally:
            if surface:
                pico.SDL_FreeSurface(surface)
    previews, rectangles = [], []
    cursor = 0
    def populate(_=None):
        nonlocal cursor
        row = assembly.row(source.get())
        name.set(row["name"].rsplit("/", 1)[0])
        fps.set(f'{row["fps"]:g}')
        pivots = {tuple(frame["pivot"]) for frame in row["frames"]}
        px.set(str(row["frames"][0]["pivot"][0]) if len(pivots) == 1 else "")
        py.set(str(row["frames"][0]["pivot"][1]) if len(pivots) == 1 else "")
        tree.delete(*tree.get_children())
        previews.clear()
        rectangles.clear()
        cursor = 0
        for index, frame in enumerate(row["frames"]):
            tree.insert("", "end", values=(index + 1, str(tuple(frame["rect"]))))
            x, y, width, height = frame["rect"]
            cropped = tk.PhotoImage(master=root, width=width, height=height)
            root.tk.call(str(cropped), "copy", str(atlas), "-from", x, atlas.height() - y - height, x + width, atlas.height() - y)
            factor = max(1, ceil(max(width / 220, height / 180)))
            if factor > 1:
                cropped = cropped.subsample(factor, factor)
            previews.append(cropped)
            rectangles.append((width, height, frame["pivot"], cropped.width() / width))
    def drop(event):
        target = tree.identify_row(event.y)
        selected = tree.selection()
        if target and target not in selected:
            index = tree.index(target)
            for offset, item in enumerate(selected):
                tree.move(item, "", index + offset)
    def remove(_):
        for item in tree.selection():
            tree.delete(item)
    def duplicate(_):
        for item in tree.selection():
            tree.insert("", tree.index(item) + 1, values=tree.item(item, "values"))
        return "break"
    def apply():
        try:
            order = [int(tree.item(item, "values")[0]) - 1 for item in tree.get_children()]
            pivot = None if not px.get().strip() and not py.get().strip() else (float(px.get()), float(py.get()))
            current = assembly.apply(source.get(), name.get(), order, float(fps.get()), pivot, all_directions=together.get())
            selection.configure(values=assembly.names)
            source.set(current)
            populate()
            error.set("")
            return True
        except (ValueError, KeyError, StopIteration) as problem:
            error.set(str(problem))
            return False
    def save():
        nonlocal result
        if not apply():
            return
        try:
            folder = WORKSPACE / "sprites" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8])
            result = assembly.save(folder, asset_id=asset_id), source.get()
            root.destroy()
        except (OSError, ValueError) as problem:
            error.set(str(problem))
    def animate():
        nonlocal cursor
        items = tree.get_children()
        if items:
            if not playing.get() and tree.selection():
                item = tree.selection()[0]
            else:
                item = items[cursor % len(items)]
            index = int(tree.item(item, "values")[0]) - 1
            canvas.delete("all")
            canvas.create_image(120, 100, image=previews[index])
            width, height, pivot, scale = rectangles[index]
            try:
                candidate = (float(px.get()), float(py.get())) if px.get() and py.get() else pivot
                if all(isfinite(value) for value in candidate):
                    pivot = candidate
            except ValueError:
                pass
            x = 120 + (pivot[0] - width / 2) * scale
            y = 100 - (pivot[1] - height / 2) * scale
            canvas.create_line(x - 6, y, x + 6, y, fill=colors["accent"])
            canvas.create_line(x, y - 6, x, y + 6, fill=colors["accent"])
            if playing.get():
                cursor += 1
        try:
            rate = max(0.1, min(240, float(fps.get())))
        except ValueError:
            rate = 8
        root.after(max(4, round(1000 / rate)), animate)
    selection.bind("<<ComboboxSelected>>", populate)
    tree.bind("<ButtonRelease-1>", drop)
    tree.bind("<Delete>", remove)
    tree.bind("<Control-d>", duplicate)
    ttk.Button(content, text="동작 적용", command=apply).grid(row=9, column=0, sticky="w")
    ttk.Button(content, text="스프라이트 저장", command=save).grid(row=9, column=1, sticky="e")
    root.bind("<Escape>", lambda _: root.destroy())
    populate()
    animate()
    root.mainloop()
    return result
