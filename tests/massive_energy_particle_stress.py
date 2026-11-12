"""Massive Energy Particle Stress

생성·갱신 Compute Ubershader의 대량 에너지 오브를 시연한다.
CPU 제출 시간과 GPU 생성·갱신·렌더링 시간을 구분해 기록한다.
"""

import argparse
from collections import defaultdict
import json
from math import isfinite
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ferrial_drive.diagnostics import TimingRecorder
from ferrial_drive.particles import GpuParticleSystem
from ferrial_drive.ui.components import Rect
from ferrial_drive.ui_v2.pico_renderer import PicoV2Renderer

UNIT_TEST_ENTRYPOINT = 'standalone'
SAMPLE = ROOT / 'samples/massive_energy_particle_stress'


class MassiveEnergyParticleStress:
    def __init__(self, config_path=None, *, capacity=None, capture_path=None):
        self.config_path = Path(config_path) if config_path else SAMPLE / 'config.json'
        self.config = json.loads(self.config_path.read_text(encoding='utf-8'))
        if capacity is not None:
            self.config['capacity'] = capacity
        self.system = GpuParticleSystem(self.config['duration_seconds'], capacity=self.config['capacity'],
                                        tail_fraction=self.config['tail_fraction'], seed=self.config['seed'])
        self.running, self.paused = True, False
        self.renderer = self.backend = self.pico = None
        self.selection = 0
        self.requested = 0
        self.capture_path = Path(capture_path) if capture_path else None
        self.benchmark_requested = False
        self.benchmarking = False
        self.last_report = None
        self.last_gpu_result = None
        self.timings = TimingRecorder(enabled=True, session='massive-energy-particle-stress-interactive')

    def enter(self):
        import pico2d.pico2d as p
        self.pico = p
        font = (self.config_path.parent / self.config['font']).resolve()
        self.renderer = PicoV2Renderer({'body': font}, {'body': self.config['font_size']})
        self.backend = self.renderer.prepare_compute_particles(self.system, profiling=True)
        self.burst(self.config['counts'][self.selection])

    def burst(self, count, *, duration_seconds=None):
        count = min(count, self.system.capacity)
        width, height = self.config['width'], self.config['height']
        for side, amount in ((-1, (count + 1) // 2), (1, count // 2)):
            if amount == 0:
                continue
            start = (width * (0.25 if side < 0 else 0.75), height * 0.5)
            waypoint = (width * (0.3 if side < 0 else 0.7), height * 0.9)
            destination = (width * 0.5, height * 0.94)
            spread = min(width * 0.4, height * 0.72) / max(1, amount - 1)
            self.system.emit(start, waypoint, destination, count=amount, side=side,
                             spread_pixels=spread, duration_seconds=duration_seconds,
                             duration_variation=self.config.get('duration_variation', 0))
        self.requested = count

    def handle_event(self, event):
        p = self.pico
        if event.type != p.SDL_KEYDOWN or getattr(event, 'repeat', False):
            return
        if event.key in (p.SDLK_ESCAPE, p.SDLK_F10):
            self.running = False
        elif event.key == p.SDLK_p:
            self.paused = not self.paused
        elif event.key == p.SDLK_SPACE:
            self.burst(self.config['counts'][self.selection])
        elif event.key == p.SDLK_r:
            self.system.clear()
            self.requested = 0
        elif event.key == p.SDLK_b:
            self.benchmark_requested = True
        elif p.SDLK_1 <= event.key <= p.SDLK_4:
            self.selection = event.key - p.SDLK_1
            self.system.clear()
            self.burst(self.config['counts'][self.selection])

    def update(self, delta_seconds):
        if not self.paused:
            self.system.update(delta_seconds)

    def draw_particles(self):
        c = self.config['colors']
        self.renderer.clear(c['background'])
        with self.timings.scope('particles.cpu_submit'):
            self.renderer.draw_compute_particles(self.system, self.config['style'], c['energy'], c['text'], 1)

    def draw(self):
        self.draw_particles()
        c = self.config['colors']
        gpu = self.backend.collect_timings()
        if self.last_gpu_result and not gpu:
            gpu = self.last_gpu_result
        rows = self.timings.snapshot()['measurements']
        cpu = next((row['mean_ns'] / 1e6 for row in rows if row['name'] == 'particles.cpu_submit'), 0)
        text = [
            'Massive Energy Particle Stress',
            'GPU: ' + self.backend.gpu_info['renderer'],
            f'요청 수 {self.requested:,}  /  풀 {self.system.capacity:,}  /  GPU 메모리 {self.backend.allocated_bytes / 2**20:.1f} MiB',
            'CPU 제출 평균 %.3f ms' % cpu,
            'GPU 생성 %.3f / 갱신 %.3f / 렌더 %.3f ms' % tuple(gpu.get(key, 0) for key in ('spawn', 'update', 'render')),
            '1~4 입자 수 선택 / Space 생성 / P 정지 / R 초기화 / B 벤치마크 / Esc 종료',
            'GPU 값은 비동기 타이머 평균이다. 활성 수 readback은 벤치마크 종료 때만 수행한다.',
        ]
        if self.paused:
            text.append('일시정지')
        if self.last_report:
            text.append('벤치마크 저장: ' + self.last_report.name)
        self.renderer.rect(Rect(14, 14, self.config['width'] - 28, 28 * len(text) + 18), '#10252D', 0.92)
        for index, line in enumerate(text):
            self.renderer.text(line, 28, 26 + index * 28, 'body', c['text'] if index == 0 else c['muted'])
        if self.capture_path:
            self.renderer.save_frame(self.capture_path, self.config['width'], self.config['height'])
            self.capture_path = None
        if self.benchmark_requested:
            self.benchmark_requested = False
            from ferrial_drive.runtime import poll_events
            def cancelled():
                for event in poll_events(self.pico):
                    if event.type == self.pico.SDL_QUIT:
                        self.running = False
                        return True
                    if event.type == self.pico.SDL_KEYDOWN and event.key == self.pico.SDLK_ESCAPE:
                        return True
                return False
            self.run_benchmark(present=self.pico.update_canvas, poll_cancel=cancelled)

    def run_benchmark(self, *, counts=None, warmup=None, frames=None,
                      output_path=None, present=None, poll_cancel=None):
        """GPU 타이머와 CPU 제출 측정을 분리한다. readback은 측정 루프 밖에서만 한다."""
        options = self.config['benchmark']
        counts = list(counts or self.config['counts'])
        warmup = options['warmup_frames'] if warmup is None else warmup
        frames = options['measured_frames'] if frames is None else frames
        delta = options['fixed_delta_seconds']
        if type(warmup) is not int or warmup < 0 or type(frames) is not int or frames < 1:
            raise ValueError('예열은 0 이상, 측정 프레임은 양수 정수여야 한다.')
        if not isfinite(delta) or delta <= 0 or any(type(count) is not int or count <= 0 or count > self.system.capacity for count in counts):
            raise ValueError('고정 시간은 양수이며 입자 수는 풀 크기 이하여야 한다.')
        destination = Path(output_path) if output_path else ROOT / 'output/performance/massive_energy_particle_stress.json'
        destination.parent.mkdir(parents=True, exist_ok=True)
        results = []
        self.backend.reserve_timer_queries((warmup + frames) * 2 + 8)
        old_samples = self.backend.gpu_samples
        self.backend.collect_timings(wait=True)
        self.backend.gpu_samples = defaultdict(list)
        self.benchmarking = True
        try:
            for count in counts:
                self.system.clear()
                self.backend.collect_timings(wait=True)
                self.backend.gpu_samples.clear()
                lifetime = max(self.system.duration_seconds, (warmup + frames + 2) * delta + 1)
                self.burst(count, duration_seconds=lifetime)
                # 생성 시간을 측정한 뒤 예열/반복 갱신과 구분한다.
                self.draw_particles()
                self.backend.collect_timings(wait=True)
                spawn = list(self.backend.gpu_samples.get('spawn', []))
                for frame in range(warmup):
                    self.system.update(delta)
                    self.draw_particles()
                    if present:
                        present()
                    if poll_cancel and poll_cancel():
                        return None
                self.backend.collect_timings(wait=True)
                self.backend.gpu_samples.clear()
                recorder = TimingRecorder(enabled=True, session=f'massive-energy-{count}')
                old_timings, self.timings = self.timings, recorder
                try:
                    for frame in range(frames):
                        if poll_cancel and poll_cancel():
                            return None
                        self.system.update(delta)
                        self.draw_particles()
                        if present:
                            present()
                    self.backend.collect_timings(wait=True)
                finally:
                    self.timings = old_timings
                snapshot = self.backend.snapshot(max_particles=0)
                def summary(values):
                    return dict(samples=len(values), mean_ms=statistics.mean(values) if values else None,
                                min_ms=min(values) if values else None, max_ms=max(values) if values else None,
                                total_ms=sum(values))
                results.append(dict(requested_count=count, active_count=snapshot['active_count'],
                                    gpu_spawn=summary(spawn),
                                    gpu_update=summary(list(self.backend.gpu_samples.get('update', []))),
                                    gpu_render=summary(list(self.backend.gpu_samples.get('render', []))),
                                    cpu=recorder.snapshot()))
                recorder.write_json(destination.with_name(f'{destination.stem}_{count}_cpu.json'))
            report = dict(schema_version=1, name='Massive Energy Particle Stress',
                          backend='spawn-update-compute-ubershaders', compute_programs=2,
                          gpu=self.backend.gpu_info, canvas=[self.config['width'], self.config['height']],
                          style=self.config['style'], seed=self.system.seed,
                          capacity=self.system.capacity, allocated_bytes=self.backend.allocated_bytes,
                          duration_variation=self.config.get('duration_variation', 0),
                          warmup_frames=warmup, measured_frames=frames, fixed_delta_seconds=delta,
                          readback_in_measured_loop=False, gpu_timer='GL_TIME_ELAPSED',
                          includes_ui=False, includes_present=False, results=results)
            destination.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
            self.last_report = destination
            self.last_gpu_result = {stage: results[-1][f'gpu_{stage}']['mean_ms'] or 0 for stage in ('spawn', 'update', 'render')}
            return report
        finally:
            self.backend.gpu_samples = old_samples
            self.benchmarking = False

    def exit(self):
        if self.renderer is not None:
            self.renderer.close()
            self.renderer = self.backend = None


def create_test(**kwargs):
    return MassiveEnergyParticleStress(**kwargs)


def main():
    parser = argparse.ArgumentParser(description='Massive Energy Particle Stress')
    parser.add_argument('--config', type=Path)
    parser.add_argument('--capacity', type=int)
    parser.add_argument('--frames', type=int)
    parser.add_argument('--capture', type=Path)
    parser.add_argument('--benchmark', action='store_true')
    parser.add_argument('--counts', default=None)
    parser.add_argument('--warmup', type=int)
    parser.add_argument('--benchmark-frames', type=int)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--hidden', action='store_true')
    args = parser.parse_args()
    program = create_test(config_path=args.config, capacity=args.capacity, capture_path=args.capture)
    if not args.benchmark:
        from ferrial_drive.runtime import run_application
        run_application(program, width=program.config['width'], height=program.config['height'],
                        title='Massive Energy Particle Stress', frame_limit=args.frames)
        return
    from contextlib import nullcontext
    from unittest.mock import patch
    from ferrial_drive.rendering import PicoCanvas
    from ferrial_drive.runtime import poll_events
    import pico2d.pico2d as p
    create = p.SDL_CreateWindow
    def hidden(title, x, y, w, h, flags):
        return create(title, x, y, w, h, (flags & ~p.SDL_WINDOW_SHOWN) | p.SDL_WINDOW_HIDDEN)
    with patch.object(p, 'SDL_CreateWindow', side_effect=hidden) if args.hidden else nullcontext():
        canvas = PicoCanvas(program.config['width'], program.config['height'], 'Massive Energy Particle Stress').open()
    try:
        program.enter()
        def cancelled():
            return any(event.type == p.SDL_QUIT or (event.type == p.SDL_KEYDOWN and event.key == p.SDLK_ESCAPE)
                       for event in poll_events(p))
        report = program.run_benchmark(counts=[int(value) for value in args.counts.split(',')] if args.counts else None,
                                       warmup=args.warmup, frames=args.benchmark_frames, output_path=args.output,
                                       present=canvas.present, poll_cancel=cancelled)
        if report:
            program.draw()
            print(json.dumps({'output': str(program.last_report), 'results': [
                {key: row[key] for key in ('requested_count', 'active_count', 'gpu_spawn', 'gpu_update', 'gpu_render')}
                for row in report['results']]}, ensure_ascii=False))
    finally:
        program.exit()
        canvas.close()


if __name__ == '__main__':
    main()
