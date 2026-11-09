"""실제 분리 시트 합성과 연결 전 순서 도식을 같은 패널에 표시한다."""

from ferrial_drive.ui.components import Rect


COLORS = {"body": "#7A91A0", "left_hand": "#4BBEE1", "right_hand": "#EB8569", "sheath": "#A072BE",
          "side_slot_l": "#749A75", "side_slot_r": "#749A75", "stowed_sword": "#BBB87D", "stowed_gun": "#C7A579",
          "detached_sword": "#BABFC9", "detached_gun": "#BA9B83"}
SHAPES = {"body": (.32, .18, .36, .58), "left_hand": (.18, .35, .38, .15),
          "right_hand": (.44, .50, .40, .14), "sheath": (.34, .26, .10, .60),
          "side_slot_l": (.25, .62, .17, .14), "side_slot_r": (.59, .62, .17, .14),
          "stowed_sword": (.28, .30, .08, .48), "stowed_gun": (.63, .55, .18, .25),
          "detached_sword": (.07, .16, .07, .30), "detached_gun": (.86, .18, .10, .20)}


def draw_preview(panel, rect):
    r, c = panel.app.renderer, panel.app.theme["colors"]
    r.rect(rect, c["input"])
    with r.clip(rect):
        if panel.preview_resource:
            name = panel.motion_key + "/" + panel.direction_name
            if name not in panel.preview_resource.clips:
                r.text("선택 동작/방향의 시트가 없다.", rect.x + 12, rect.y + 12, "small", c["muted"])
                return
            clip = panel.preview_resource.clips[name]
            index = int(panel.preview_time * clip.fps) % len(clip.frames)
            frame = clip.frames[index]
            scale = min((rect.width - 24) / frame.rect[2], (rect.height - 24) / frame.rect[3])
            x = rect.x + rect.width / 2 + (frame.pivot[0] - frame.rect[2] / 2) * scale
            y = 800 - rect.y - rect.height / 2 + (frame.pivot[1] - frame.rect[3] / 2) * scale
            source_frames = panel.preview_resource.mech.rows[name]["source_frames"]
            current_frame = panel.order_frame if panel.order_frame is not None else source_frames[index]
            # 현재 편집 내용은 자원을 다시 읽지 않고 순서에 즉시 반영한다.
            row = next((row for row in panel.current_motion["overrides"]
                        if (row["direction"], row["frame"]) == (panel.direction_name, current_frame)), None)
            order = row["order"] if row else panel.current_motion["orders"][panel.direction_name]
            if panel.order_frame in source_frames:
                index = source_frames.index(panel.order_frame)
            panel.preview_resource.draw(name, index, x, y, scale=scale, layer_order=order)
            label = "도형 합성 예제" if panel.preview_is_sample else "조립"
            r.text(f"{label} · {index + 1}/{len(clip.frames)}", rect.x + 8, rect.y + 8, "small", c["muted"])
        else:
            size = min(rect.height - 26, rect.width * .65)
            left, top = rect.x + (rect.width - size) / 2, rect.y + 8
            for key in panel.current_order:
                x, y, width, height = SHAPES[key]
                r.rect(Rect(left + x * size, top + y * size, width * size, height * size), COLORS[key])
            r.text("순서 도식 · 실물 시트 미연결", rect.x + 8, rect.y + rect.height - 22, "small", c["muted"])
