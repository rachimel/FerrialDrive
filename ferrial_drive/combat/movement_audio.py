"""공격 활성 구간·실제 명중·부스트 시작을 효과음에 연결한다."""

from ferrial_drive.rendering.motion_vectors import target_phase
from math import floor
from random import Random


class MovementSoundCues:
    def __init__(self, player, active_windows, *, easing="accelerate", motion=None):
        self.player = player
        self.active_windows = active_windows
        self.easing = easing
        self.motion = motion or {"pebble_interval_seconds": [0.1, 0.24], "run_steps_per_cycle": 2}
        self.metal_replaces_hit = getattr(player, "bank", {}).get("hit_metal", {}).get("replaces_hit") is True
        self.random = Random(61)
        self.reset()

    def reset(self):
        self.last_strike_id = -1
        self.last_attack_step_id = -1
        self.boost_active = False
        self.dash_active = False
        self.run_step = None
        self.pebble_remaining_seconds = 0
        self.player.reset()

    def update(self, delta_seconds, controller, steps, hits, *, prepare_before_seconds=0,
               energy_level=1, run_phase=None, scraping=False, dashing=False, hit_materials=None):
        self.player.update(delta_seconds)
        boost_active = controller.boost_remaining_seconds > 0
        # 한 프레임에 준비와 분사가 모두 끝나도 시작음을 놓치지 않는다.
        if (boost_active and not self.boost_active) or 0 < prepare_before_seconds <= delta_seconds:
            self.player.play("boost")
        self.boost_active = boost_active
        for step in steps:
            attack_index = int(step.clip_name[6:8]) - 1
            phase = target_phase(step.end_seconds / step.duration_seconds, easing=self.easing)
            contact_phases = self.motion.get("attack_step_phases")
            if (contact_phases and step.strike_id > self.last_attack_step_id
                    and phase >= contact_phases[attack_index]):
                # 접지 시연은 타격마다 한 번만 처리한다. 활주·부스트에서 늦게 따라 재생하지 않는다.
                if not step.dash and not step.boosting:
                    self.player.play("step", gain=self.motion.get("attack_step_gain", 0.3))
                self.last_attack_step_id = step.strike_id
            if step.strike_id > self.last_strike_id and phase >= self.active_windows[attack_index][0]:
                self.player.play(f"swing_{attack_index + 1}", energy_level=energy_level)
                self.last_strike_id = step.strike_id
        if hits:
            metal_hit = any((hit_materials or {}).get(target_id) == "metal" for _, target_id in hits)
            if not (metal_hit and self.metal_replaces_hit):
                self.player.play("hit", energy_level=energy_level)
            if metal_hit:
                self.player.play("hit_metal", energy_level=energy_level)
        dash_active = dashing and not boost_active and prepare_before_seconds <= 0
        if dash_active and not self.dash_active:
            self.player.play("dash_ignite")
        self.player.set_loop("dash_jet", dash_active)
        self.dash_active = dash_active
        self.player.set_loop("scrape", scraping,
                             gain=self.motion.get("dash_scrape_gain", 1) if dash_active else 1)
        if scraping:
            self.pebble_remaining_seconds -= delta_seconds
            if self.pebble_remaining_seconds <= 0:
                self.player.play("pebble")
                self.pebble_remaining_seconds = self.random.uniform(*self.motion["pebble_interval_seconds"])
        else:
            self.pebble_remaining_seconds = 0
        step = floor(run_phase * self.motion["run_steps_per_cycle"]) if run_phase is not None else None
        if step is not None and step != self.run_step:
            self.player.play("step")
        self.run_step = step
