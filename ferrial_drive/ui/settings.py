"""게임 설정의 입력·선택 상태와 저장 후 즉시 적용을 연결한다."""

from dataclasses import fields, replace
from contextlib import nullcontext

from .components import Button, ButtonInput, Rect
from .popup import PopupMotion
from ferrial_drive.rendering.canvas import prepare_output_resolution
from ferrial_drive.settings import SCREEN_RESOLUTIONS, UPSCALE_AA_MODES


class GraphicsSettingsMenu:
    def __init__(self, store):
        self.store = store
        self.saved = self.draft = store.load()
        self.opened = False
        self.inputs = ButtonInput()
        self.error = None
        self.prepare_apply = None
        self.applying = False
        self.motion = PopupMotion()
        self.restart_required_fields = ()
        self.logical_size = None

    def enable_buttons(self, config):
        self.logical_size = config.window["width"], config.window["height"]
        self.motion = PopupMotion(**config.data.get("popup_style", {}).get("motion", {}))
        restart_fields = tuple(config.data["graphics_settings"].get("restart_required_fields", ()))
        if not set(restart_fields) <= {field.name for field in fields(self.saved)}:
            raise ValueError("재시작 필요 항목은 실제 게임 설정 필드여야 한다.")
        self.restart_required_fields = restart_fields
        for scene in ("menu", "pause"):
            config.buttons[scene] = tuple(replace(button, enabled=True) if button.action == "settings" else button
                                          for button in config.buttons.get(scene, ()))

    def open(self):
        self.draft = self.saved
        self.error = None
        self.opened = True
        self.inputs.reset()
        self.motion.open()

    def cancel(self):
        self.draft = self.saved
        self.opened = False
        self.error = None
        self.inputs.reset()
        self.motion.reset()

    def update(self, delta_seconds):
        if self.opened:
            self.motion.update(delta_seconds)

    @property
    def requires_restart(self):
        return any(getattr(self.draft, name) != getattr(self.saved, name) for name in self.restart_required_fields)

    def panel_rect(self, config):
        width, height = config.data["graphics_settings"]["panel_size_pixels"]
        return Rect((config.window["width"]-width)/2, (config.window["height"]-height)/2, width, height)

    def buttons(self, config):
        layout = config.data["graphics_settings"]
        panel = self.panel_rect(config)
        padding, gap = layout["padding_pixels"], layout["gap_pixels"]
        width = (panel.width-padding*2-gap*2)/3
        y = panel.y+layout["quality_row_y_pixels"]
        labels = layout["labels"]
        choices = tuple(Button(f"texture_{name}", f"texture_{name}", labels[name],
                               Rect(panel.x+padding+index*(width+gap), y, width, layout["option_height_pixels"]))
                        for index, name in enumerate(("high", "medium", "low")))
        resolution_width = (panel.width-padding*2-gap*(len(SCREEN_RESOLUTIONS)-1))/len(SCREEN_RESOLUTIONS)
        resolutions = tuple(Button(f"resolution_{w}x{h}", f"resolution_{w}x{h}", f"{w} x {h}",
                            Rect(panel.x+padding+index*(resolution_width+gap),
                                 panel.y+layout.get("resolution_row_y_pixels", 284),
                                 resolution_width, layout["option_height_pixels"]))
                            for index, (w, h) in enumerate(SCREEN_RESOLUTIONS))
        aa_choices = ()
        if "upscale_aa_row_y_pixels" in layout:
            width = (panel.width - 2 * padding - gap) / len(UPSCALE_AA_MODES)
            aa_choices = tuple(Button(f"upscale_aa_{mode}", f"upscale_aa_{mode}", labels[mode],
                                      Rect(panel.x + padding + index * (width + gap),
                                           panel.y + layout["upscale_aa_row_y_pixels"],
                                           width, layout["option_height_pixels"]))
                               for index, mode in enumerate(UPSCALE_AA_MODES))
        footer_y = panel.y+panel.height-padding-layout["button_height_pixels"]
        footer_width = layout["button_width_pixels"]
        hint_label = labels.get("key_hints", "사용키 표시")
        hint_value = labels.get("on", "켬") if self.draft.show_key_hints else labels.get("off", "끔")
        hint = Button("key_hints_toggle", "key_hints_toggle", f"{hint_label} · {hint_value}",
                      Rect(panel.x+padding, panel.y+layout.get("key_hints_row_y_pixels", 270),
                           panel.width-padding*2, layout["button_height_pixels"]))
        volume = ()
        if "effects_volume_row_y_pixels" in layout:
            content_width = panel.width - padding * 2
            volume = (Button("effects_volume", "effects_volume", labels["effects_volume"],
                             Rect(panel.x + padding + content_width * .36,
                                  panel.y + layout["effects_volume_row_y_pixels"],
                                  content_width * .51, layout["button_height_pixels"])),)
        return choices + resolutions + aa_choices + (hint,) + volume + (Button("settings_cancel", "settings_cancel", labels["cancel"],
                                  Rect(panel.x+padding, footer_y, footer_width, layout["button_height_pixels"])),
                          Button("settings_save", "settings_save", labels["save"],
                                  Rect(panel.x+panel.width-padding-footer_width, footer_y, footer_width, layout["button_height_pixels"])))

    def pointer(self, kind, x, y, config):
        if self.motion.entering:
            self.inputs.reset()
            return None
        buttons = self.buttons(config)
        was_adjusting_volume = self.inputs.pressed_id == "effects_volume"
        result = self.inputs.handle(kind, x, y, buttons)
        if self.inputs.pressed_id == "effects_volume" or (was_adjusting_volume and kind == "up"):
            track = next(button.rect for button in buttons if button.action == "effects_volume")
            value = round(100 * (x - track.x) / track.width)
            self.draft = replace(self.draft, effects_volume_percent=max(0, min(100, value)))
            return None
        if result.action:
            return self.perform(result.action)
        return None

    def perform(self, action):
        if action in ("texture_high", "texture_medium", "texture_low"):
            self.draft = replace(self.draft, texture_quality=action.removeprefix("texture_"))
        elif action in {f"resolution_{w}x{h}" for w, h in SCREEN_RESOLUTIONS}:
            self.draft = replace(self.draft, screen_resolution=tuple(map(int, action.removeprefix("resolution_").split("x"))))
        elif action in {f"upscale_aa_{mode}" for mode in UPSCALE_AA_MODES}:
            self.draft = replace(self.draft, upscale_aa=action.removeprefix("upscale_aa_"))
        elif action == "key_hints_toggle":
            self.draft = replace(self.draft, show_key_hints=not self.draft.show_key_hints)
        elif action == "settings_cancel":
            self.cancel()
            return "settings_closed"
        elif action == "settings_save":
            self.applying = True
            self.error = None
            try:
                change = self.prepare_apply(self.draft) if self.prepare_apply else nullcontext(None)
                with change as apply:
                    display = (prepare_output_resolution(self.draft.screen_resolution, self.logical_size)
                               if self.logical_size and self.draft.screen_resolution != self.saved.screen_resolution
                               else nullcontext(None))
                    with display as commit_display:
                        self.store.save(self.draft)
                        if apply is not None:
                            apply()
                        if commit_display is not None:
                            commit_display()
            except (OSError, ValueError, RuntimeError) as error:
                self.error = str(error)
                return None
            finally:
                self.applying = False
            self.saved = self.draft
            self.opened = False
            self.inputs.reset()
            self.motion.reset()
            return "settings_saved"
        return None
