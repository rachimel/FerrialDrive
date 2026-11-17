"""별도 작업본으로 편집기의 위젯 연결과 실제 HUD 프레임을 확인한다."""

import json
from copy import deepcopy
from types import SimpleNamespace

from ferrial_drive.ui.theme import save_theme


def schedule_verification(app, destination):
    window = app.window
    destination.mkdir(parents=True, exist_ok=True)
    results = {"checks": {}, "errors": [], "direct_ui_input_verified": False}

    def check(name, condition):
        results["checks"][name] = bool(condition)
        if not condition:
            raise AssertionError(name)

    def safely(callback):
        def run():
            try:
                callback()
            except Exception as error:
                results["errors"].append(f"{type(error).__name__}: {error}")
                if callback in (inspect, inspect_fallback):
                    window.after(400, finalize)
        return run

    def exercise():
        save_theme(destination / "initial_theme.json", app.document)
        app.start_preview()

    def edit():
        regions = app.matching_regions(palette="accent", widget="health")
        if regions and app.preview_image is not None:
            left, top, right, bottom = regions[0]["bounds"]
            results["initial_health_pixel"] = app.preview_image.getpixel(((left + right) // 2, (top + bottom) // 2))[:3]
        app.selected_palette = "accent"
        app.select_palette()
        app.set_color("#E8BC78")

    def inspect():
        check("native_frame", app.preview_image is not None and app.preview_image.size == (1920, 1080))
        regions = app.matching_regions(palette="accent", widget="health")
        check("health_palette_region", bool(regions))
        left, top, right, bottom = regions[0]["bounds"]
        pixel = app.preview_image.getpixel(((left + right) // 2, (top + bottom) // 2))[:3]
        results["edited_health_pixel"] = pixel
        # HUD의 광택·주사선이 합성되므로 원색과의 바이트 일치를 요구하지 않는다.
        initial = results.get("initial_health_pixel", pixel)
        check("live_color_in_actual_hud", sum(abs(a - b) for a, b in zip(initial, pixel)) > 30 and pixel[0] > pixel[2] + 20)
        app.preview_image.save(destination / "hud_preview.png")
        app.focus_usage("health", "accent")
        app.zoom_widget.set(True)
        app.draw_preview()
        check("zoom_crops_actual_part", app.preview_transform[3] != (0, 0, 1920, 1080))
        check("zoom_has_clickable_part", bool(app.preview_hits))
        app.zoom_widget.set(False)
        app.draw_preview()
        # 검증은 편집기의 자체 입력 처리 함수를 호출한다. 실제 마우스 입력과 구분한다.
        left, top, right, bottom, _ = next(item for item in app.palette_hits if item[4] == "text")
        app.click_palette(SimpleNamespace(x=(left + right) / 2, y=(top + bottom) / 2))
        check("grid_selects_picker", app.palette_name() == "text" and app.hex_value.get() == app.document["palette"]["text"])
        check("shared_color_marks_multiple_parts", len({item[4] for item in app.preview_hits}) > 3)
        app.focus_usage("health", "text")
        app.document["palette"]["검증 색"] = "#4477AA"
        app.refresh_palette("검증 색")
        app.assign_selected_palette()
        check("assign_selected_palette", app.document["widgets"]["health"]["text"] == "검증 색")
        app.binding_value.set("상속")
        app.assign_color()
        check("restore_inherited_palette", "text" not in app.document["widgets"]["health"] and app.palette_name() == "text")
        app.selected_palette = "검증 색"
        app.select_palette()
        app.delete_color()
        check("delete_unbound_palette", "검증 색" not in app.document["palette"])
        app.selected_palette = "accent"
        app.select_palette()
        app.pick_hue(SimpleNamespace(y=70))
        app.pick_sv(SimpleNamespace(x=100, y=50))
        check("embedded_picker_updates_rgb", app.hex_value.get() == "#" + "".join(f"{value.get():02X}" for value in app.channels))
        app.set_color("#E8BC78")
        app.select_palette()
        app.verification_original = deepcopy(app.document)
        app.focus_usage("health", "text")
        app.selected_palette = "text"
        app.select_palette()
        app.delete_color()
        check("delete_bound_default_color", "text" not in app.document["palette"] and
              all("text" not in bindings.values() for bindings in app.document["widgets"].values()))
        check("deleted_role_shows_fallback", app.binding_value.get() == "Fallback" and
              app.hex_value.get() == app.fallback_colors["text"])
        for name in tuple(app.document["palette"]):
            app.selected_palette = name
            app.delete_color()
        check("delete_last_color", app.document["palette"] == {} and app.palette_name() is None)
        check("roles_remain_editable", "text" in app.available_roles.values() and "accent" in app.available_roles.values())
        save_theme(destination / "empty_theme.json", app.document)
        window.after(1000, safely(inspect_fallback))

    def inspect_fallback():
        check("actual_hud_fallback_frame", any(item["widget"] == "health" and item["role"] == "accent" and
              item["palette"] is None for item in app.preview_metadata.get("regions", [])))
        bounds = next(item["bounds"] for item in app.preview_metadata["regions"]
                      if item["widget"] == "health" and item["role"] == "accent")
        left, top, right, bottom = bounds
        pixel = app.preview_image.getpixel(((left + right) // 2, (top + bottom) // 2))[:3]
        results["fallback_health_pixel"] = pixel
        check("actual_hud_original_color_restored", sum(abs(a - b) for a, b in zip(pixel, results["initial_health_pixel"])) < 40)
        app.preview_image.save(destination / "fallback_hud.png")
        app.verification_fallback = deepcopy(app.document)
        app.set_color("#4477AA")
        check("edit_fallback_creates_bound_color", len(app.document["palette"]) == 1 and
              app.document["widgets"]["health"]["text"] == app.palette_name())
        app.document = app.verification_fallback
        app.selected_palette = None
        app.changed()
        app.select_binding()
        window.after(1000, finalize)

    def capture():
        from PIL import ImageGrab
        window.update_idletasks()
        widgets = {"palette_grid": app.palette_canvas, "color_picker": app.sv_canvas,
                   "picker_panel": app.picker_panel,
                   "preview": app.preview_canvas, "widget_selector": app.widget_combo,
                   "role_selector": app.role_combo, "binding_selector": app.binding_combo}
        results["layout"] = {name: {"x": widget.winfo_rootx() - window.winfo_rootx(),
                                     "y": widget.winfo_rooty() - window.winfo_rooty(),
                                     "width": widget.winfo_width(), "height": widget.winfo_height()}
                             for name, widget in widgets.items()}
        check("controls_fit_window", all(item["x"] >= 0 and item["y"] >= 0
              and item["x"] + item["width"] <= window.winfo_width()
              and item["y"] + item["height"] <= window.winfo_height() for item in results["layout"].values()))
        check("preview_width", app.preview_canvas.winfo_width() >= 900)
        try:
            window.lift()
            window.update_idletasks()
            picture = ImageGrab.grab(window=window.winfo_id())
            results["editor_capture_valid"] = any(high > low for low, high in picture.convert("RGB").getextrema())
            if results["editor_capture_valid"]:
                picture.save(destination / "editor.png")
        except OSError as error:
            results["editor_capture_valid"] = False
            results["editor_capture_error"] = str(error)
        save_theme(destination / "edited_theme.json", app.document)
        window.geometry("1280x900")

    def minimum_layout():
        window.update_idletasks()
        widgets = {"palette_grid": app.palette_canvas, "picker_panel": app.picker_panel,
                   "preview": app.preview_canvas, "widget_selector": app.widget_combo,
                   "role_selector": app.role_combo, "binding_selector": app.binding_combo}
        results["minimum_window"] = [window.winfo_width(), window.winfo_height()]
        results["minimum_resize_verified"] = results["minimum_window"] == [1280, 900]
        if not results["minimum_resize_verified"]:
            results["minimum_resize_note"] = "검증 환경에서 창 크기 변경 요청이 실제 창에 반영되지 않아 작은 창 검증은 미완료다."
            window.geometry("1560x980")
            return
        results["minimum_layout"] = {name: {"x": widget.winfo_rootx() - window.winfo_rootx(),
                                             "y": widget.winfo_rooty() - window.winfo_rooty(),
                                             "width": widget.winfo_width(), "height": widget.winfo_height()}
                                     for name, widget in widgets.items()}
        check("minimum_controls_fit_window", all(item["x"] >= 0 and item["y"] >= 0
              and item["x"] + item["width"] <= window.winfo_width()
              and item["y"] + item["height"] <= window.winfo_height() for item in results["minimum_layout"].values()))
        window.geometry("1560x980")

    def finish():
        results["passed"] = not results["errors"] and bool(results["checks"])
        (destination / "verification.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(results, ensure_ascii=False), flush=True)
        app.close()

    def finalize():
        safely(capture)()
        window.after(400, safely(minimum_layout))
        window.after(900, finish)

    window.after(300, safely(exercise))
    window.after(1800, safely(edit))
    window.after(4200, safely(inspect))
