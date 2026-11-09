"""기존 에셋 자원으로 그리는 메인 미리보기의 프레임 목록."""

from ferrial_drive.ui.components import Rect


FRAME_STRIP = Rect(276, 568, 696, 136)
FRAME_PAGE = 7
FRAME_STRIDE = 98
ANIMATION_VIEW = Rect(276, 88, 696, 472)


class FrameStrip:
    def __init__(self):
        self.reset()

    def reset(self):
        self.offset = 0
        self.follow_playback = True

    def clamp(self, count):
        self.offset = max(0, min(max(0, count - FRAME_PAGE), self.offset))

    def reveal(self, index, count):
        self.offset = min(max(self.offset, index - FRAME_PAGE + 1), index)
        self.clamp(count)

    def scroll(self, delta, count):
        self.offset -= delta
        self.clamp(count)
        self.follow_playback = False

    def slots(self, count):
        self.clamp(count)
        for slot, index in enumerate(range(self.offset, min(count, self.offset + FRAME_PAGE))):
            yield index, Rect(FRAME_STRIP.x + 4 + slot * FRAME_STRIDE, 590, 92, 110)

    def hit(self, x, y, count):
        return next((index for index, rect in self.slots(count) if rect.contains(x, y)), None)

    def draw(self, app):
        clip = app.clip
        if clip is None:
            return
        count, selected = len(clip.frames), app.frame_index
        if self.follow_playback:
            self.reveal(selected, count)
        r, colors = app.renderer, app.theme['colors']
        r.rect(FRAME_STRIP, colors['panel'])
        r.text('프레임', FRAME_STRIP.x + 8, FRAME_STRIP.y + 4, 'small', colors['text'])
        r.text(f'{self.offset + 1}~{min(count, self.offset + FRAME_PAGE)} / {count} · 휠 이동',
               FRAME_STRIP.x + 448, FRAME_STRIP.y + 4, 'small', colors['muted'], max_width=240)
        resource = app.handle.resource
        with r.clip(FRAME_STRIP):
            for index, slot in self.slots(count):
                r.rect(slot, colors['selected'] if index == selected else colors['input'])
                if index == selected:
                    r.rect(slot, colors['accent'], filled=False)
                image = Rect(slot.x + 4, slot.y + 4, slot.width - 8, 66)
                frame = clip.frames[index]
                width, height = frame.rect[2:]
                scale = min((image.width - 8) / width, (image.height - 8) / height)
                x = image.x + image.width / 2 + (frame.pivot[0] - width / 2) * scale
                y = 800 - image.y - image.height / 2 + (frame.pivot[1] - height / 2) * scale
                with r.clip(image):
                    resource.draw(app.clip_name, index, x, y, scale=scale,
                                  body=app.show_body, shadow=app.show_shadow)
                r.text(str(index + 1), slot.x + 8, slot.y + 74, 'small', colors['text'])
                duration = f'{clip.durations_ms[index]:.1f}'.rstrip('0').rstrip('.')
                r.text(f'{duration} ms', slot.x + 8, slot.y + 92, 'small', colors['muted'], max_width=80)
