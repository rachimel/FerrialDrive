"""이동 상태별 레이더 크기·불투명도 전환. 입력·렌더러와 독립이다."""

from ferrial_drive.animation import ScalarAnimation


class RadarMotion:
    def __init__(self, settings):
        self.settings = settings
        self.scale = ScalarAnimation(1, 1, 0)
        self.solid_ratio = ScalarAnimation(0, 0, 0)

    def update(self, movement_state, delta_seconds):
        duration = self.settings["transition_seconds"]
        targets = (("scale", self.settings["scale_by_state"][movement_state]),
                   ("solid_ratio", float(movement_state in ("dash", "boost"))))
        for name, target in targets:
            animation = getattr(self, name)
            if target != animation.end_value:
                animation = ScalarAnimation(animation.value, target, duration)
                setattr(self, name, animation)
            animation.update(delta_seconds)
