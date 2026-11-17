"""발사 뒤 유예와 지수 회복량. 전투·훈련장이 같은 적분식을 사용한다."""

from math import exp, expm1, log1p


def recovery_time(config, time_seconds, last_shot_seconds):
    full = log1p(config.magazine_rounds * config.ammo_recovery_growth_per_second
                 / config.ammo_recovery_initial_rounds_per_second) / config.ammo_recovery_growth_per_second
    return min(full, max(0.0, time_seconds - last_shot_seconds - config.ammo_recovery_delay_seconds))


def recovered_rounds(config, start_seconds, end_seconds, last_shot_seconds):
    before = recovery_time(config, start_seconds, last_shot_seconds)
    after = recovery_time(config, end_seconds, last_shot_seconds)
    rate = config.ammo_recovery_growth_per_second
    return config.ammo_recovery_initial_rounds_per_second / rate * exp(rate * before) * expm1(rate * (after - before))
