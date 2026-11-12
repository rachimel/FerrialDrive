"""생성·갱신 Compute Ubershader와 GPU 활성 목록을 사용하는 파티클 렌더러."""

from collections import defaultdict, deque
from contextlib import contextmanager
import ctypes as ct
import os

from ferrial_drive.particles import SpawnParticles, StepParticles
from ferrial_drive.ui_v2.particle_texture import ATLAS_SIZE, build_particle_atlas
from .bicubic import BicubicSampler
from .instanced_particles import InstancedParticles, FRAGMENT_SHADER
from .particle_compute_shaders import MAX_SEGMENTS, PARTICLE_BYTES, PATH_POINTS, SPAWN_SHADER, UPDATE_SHADER, VERTEX_SHADER


SSBO = 0x90D2
SSBO_BINDING = 0x90D3
INDIRECT = 0x8F3F
STORAGE_BARRIER = 0x2000
COMMAND_BARRIER = 0x40


class ComputeParticles(InstancedParticles):
    def __init__(self, pico, system, *, profiling=False):
        self.system = system
        self.capacity = system.capacity
        self.textures, self.buffers = [], []
        self.compute_programs = {}
        self.generation = -1
        self.last_segments = None
        self.profiling = profiling
        self.query_names, self.query_free, self.query_pending = [], [], []
        self.gpu_samples = defaultdict(lambda: deque(maxlen=240))
        self.spawn_requests_submitted = 0
        self.frame_particle_upload_bytes = 0
        self.receipt_buffers, self.receipt_pending = [], []
        self.dispatch_counts = {'spawn': 0, 'update': 0}
        BicubicSampler.__init__(self, pico, None, vertex_shader=VERTEX_SHADER, fragment_shader=FRAGMENT_SHADER,
                                extra_uniforms=('transform', 'base_color', 'core_color', 'head_width',
                                                'orb_radius', 'segments', 'mode'))
        try:
            self.compute_programs['spawn'] = self._compile_compute(SPAWN_SHADER, (
                'capacity', 'request_count', 'request_seed', 'effect_type', 'anchors', 'destination', 'spawn_settings',
                'gain_units', 'arrival_spacing', 'effect_intensity', 'duration_settings'))
            self.compute_programs['update'] = self._compile_compute(UPDATE_SHADER, ('capacity', 'delta_seconds', 'segments',
                'energy_enabled', 'energy_geometry', 'energy_ratio', 'energy_acknowledged',
                'energy_charge_mode', 'energy_charge_total'))
            with self.batch(), self._state():
                self._allocate()
            self.gpu_info = {key: self.glGetString(value).decode(errors='replace') for key, value in
                             (('vendor', 0x1F00), ('renderer', 0x1F01), ('version', 0x1F02))}
        except BaseException:
            self.close()
            raise

    def _bind_functions(self):
        super()._bind_functions()
        uint, integer, pointer = ct.c_uint, ct.c_int, ct.c_void_p
        signatures = {
            'glGenBuffers': (None, [integer, pointer]), 'glDeleteBuffers': (None, [integer, pointer]),
            'glBufferData': (None, [uint, ct.c_ssize_t, pointer, uint]),
            'glBufferSubData': (None, [uint, ct.c_ssize_t, ct.c_ssize_t, pointer]),
            'glGetBufferSubData': (None, [uint, ct.c_ssize_t, ct.c_ssize_t, pointer]),
            'glClearBufferData': (None, [uint, uint, uint, uint, pointer]),
            'glBindBufferBase': (None, [uint, uint, uint]),
            'glGetIntegeri_v': (None, [uint, uint, pointer]),
            'glGetInteger64v': (None, [uint, pointer]),
            'glDispatchCompute': (None, [uint, uint, uint]),
            'glMemoryBarrier': (None, [uint]), 'glUniform1ui': (None, [integer, uint]),
            'glDrawArraysIndirect': (None, [uint, pointer]),
            'glGetError': (uint, []), 'glGetProgramInfoLog': (None, [uint, integer, pointer, pointer]),
            'glGetString': (ct.c_char_p, [uint]),
            'glCopyBufferSubData': (None, [uint, uint, ct.c_ssize_t, ct.c_ssize_t, ct.c_ssize_t]),
            'glFenceSync': (pointer, [uint, uint]), 'glDeleteSync': (None, [pointer]),
            'glClientWaitSync': (uint, [pointer, uint, ct.c_uint64]),
            'glFlush': (None, []),
            'glGenQueries': (None, [integer, pointer]), 'glDeleteQueries': (None, [integer, pointer]),
            'glBeginQuery': (None, [uint, uint]), 'glEndQuery': (None, [uint]),
            'glGetQueryiv': (None, [uint, uint, pointer]),
            'glGetQueryObjectiv': (None, [uint, uint, pointer]),
            'glGetQueryObjectui64v': (None, [uint, uint, pointer]),
        }
        prototype = ct.WINFUNCTYPE if os.name == 'nt' else ct.CFUNCTYPE
        for name, (result, arguments) in signatures.items():
            address = self.pico.SDL_GL_GetProcAddress(name.encode())
            if not address:
                raise RuntimeError('Compute 파티클 기능 미지원: ' + name)
            setattr(self, name, prototype(result, *arguments)(address))

    def _compile_compute(self, source, names):
        shader, program = self.glCreateShader(0x91B9), 0
        try:
            pointer = ct.c_char_p(source)
            self.glShaderSource(shader, 1, ct.byref(pointer), None)
            self.glCompileShader(shader)
            status = ct.c_int()
            self.glGetShaderiv(shader, 0x8B81, ct.byref(status))
            if not status.value:
                message = ct.create_string_buffer(4096)
                self.glGetShaderInfoLog(shader, 4096, None, message)
                raise RuntimeError('Compute 컴파일 실패: ' + message.value.decode(errors='replace'))
            program = self.glCreateProgram()
            self.glAttachShader(program, shader)
            self.glLinkProgram(program)
            self.glGetProgramiv(program, 0x8B82, ct.byref(status))
            if not status.value:
                message = ct.create_string_buffer(4096)
                self.glGetProgramInfoLog(program, 4096, None, message)
                raise RuntimeError('Compute 링크 실패: ' + message.value.decode(errors='replace'))
            return program, {name: self.glGetUniformLocation(program, name.encode()) for name in names}
        except BaseException:
            if program:
                self.glDeleteProgram(program)
            raise
        finally:
            self.glDeleteShader(shader)

    @contextmanager
    def _state(self):
        generic = self.integer(SSBO_BINDING)
        indirect, unpack_buffer = self.integer(0x8F43), self.integer(0x88EF)
        copy_read, copy_write = self.integer(0x8F36), self.integer(0x8F37)
        unpack_keys = (0x0CF5, 0x0CF2, 0x0CF3, 0x0CF4)
        unpack = tuple(self.integer(key) for key in unpack_keys)
        indexed = []
        for index in range(7):
            value = ct.c_int()
            self.glGetIntegeri_v(SSBO_BINDING, index, ct.byref(value))
            indexed.append(value.value)
        try:
            self.glBindBuffer(0x88EC, 0)
            for key, value in zip(unpack_keys, (4, 0, 0, 0)):
                self.glPixelStorei(key, value)
            for index, name in enumerate(self.buffers):
                self.glBindBufferBase(SSBO, index, name)
            yield
        finally:
            for index, name in enumerate(indexed):
                self.glBindBufferBase(SSBO, index, name)
            self.glBindBuffer(SSBO, generic)
            self.glBindBuffer(INDIRECT, indirect)
            self.glBindBuffer(0x8F36, copy_read)
            self.glBindBuffer(0x8F37, copy_write)
            self.glBindBuffer(0x88EC, unpack_buffer)
            for key, value in zip(unpack_keys, unpack):
                self.glPixelStorei(key, value)

    def _allocate(self):
        sizes = (self.capacity * PARTICLE_BYTES, 16, self.capacity * 4, 32,
                 12 * 4 * 16, self.capacity * PATH_POINTS * 16, self.capacity * (MAX_SEGMENTS + 1) * 32)
        limit = ct.c_int64()
        self.glGetInteger64v(0x90DE, ct.byref(limit))
        if max(sizes) > limit.value:
            raise RuntimeError(f'입자 풀 버퍼가 GPU의 SSBO 한도 {limit.value}바이트를 넘는다.')
        names = (ct.c_uint * 7)()
        self.glGenBuffers(7, names)
        self.buffers = list(names)
        for index, (name, size) in enumerate(zip(self.buffers, sizes)):
            self.glBindBuffer(SSBO, name)
            self.glBufferData(SSBO, size, None, 0x88E8)
            error = self.glGetError()
            if error:
                raise RuntimeError(f'파티클 GPU 버퍼 할당 실패: {index}, GL {error:#x}')
            self.glBindBufferBase(SSBO, index, name)
        data = [value for profile in self.system.profiles for point in profile for value in (*point, 0, 0)]
        profiles = (ct.c_float * len(data))(*data)
        self.glBindBuffer(SSBO, self.buffers[4])
        self.glBufferSubData(SSBO, 0, ct.sizeof(profiles), profiles)
        texture = ct.c_uint()
        self.glGenTextures(1, ct.byref(texture))
        self.textures = [texture.value]
        pixels = ct.create_string_buffer(build_particle_atlas())
        self._texture(0, *ATLAS_SIZE, pixels, floating=False)
        self.glTexParameteri(0x0DE1, 0x2801, 0x2601)
        self.glTexParameteri(0x0DE1, 0x2800, 0x2601)
        receipts = (ct.c_uint * 3)()
        self.glGenBuffers(3, receipts)
        self.receipt_buffers = list(receipts)
        for name in receipts:
            self.glBindBuffer(0x8F37, name)
            self.glBufferData(0x8F37, 16, None, 0x88E1)
        self.allocated_bytes = sum(sizes) + ATLAS_SIZE[0] * ATLAS_SIZE[1] * 4 + 48

    def _zero(self, index):
        zero = ct.c_uint(0)
        self.glBindBuffer(SSBO, self.buffers[index])
        self.glClearBufferData(SSBO, 0x8236, 0x8D94, 0x1405, ct.byref(zero))

    def _draw_headers(self, segments):
        self.glMemoryBarrier(0x0200 | STORAGE_BARRIER | COMMAND_BARRIER)
        commands = (ct.c_uint * 8)((segments + 1) * 2, 0, 0, 0, 4, 0, 0, 0)
        self.glBindBuffer(SSBO, self.buffers[3])
        self.glBufferSubData(SSBO, 0, ct.sizeof(commands), commands)

    @contextmanager
    def _measure(self, stage):
        if not self.profiling:
            yield
            return
        if not self.query_names:
            self.reserve_timer_queries(64)
        current = ct.c_int()
        self.glGetQueryiv(0x88BF, 0x8865, ct.byref(current))
        if not self.query_free or current.value:
            yield
            return
        query = self.query_free.pop()
        self.glBeginQuery(0x88BF, query)
        try:
            yield
        finally:
            self.glEndQuery(0x88BF)
            self.query_pending.append((stage, query))

    def reserve_timer_queries(self, count):
        extra = count - len(self.query_names)
        if extra > 0:
            names = (ct.c_uint * extra)()
            self.glGenQueries(extra, names)
            self.query_names.extend(names)
            self.query_free.extend(names)

    def collect_timings(self, *, wait=False):
        if wait:
            self.glFlush()
        remaining = []
        for stage, query in self.query_pending:
            ready = ct.c_int()
            self.glGetQueryObjectiv(query, 0x8867, ct.byref(ready))
            if ready.value or wait:
                elapsed = ct.c_uint64()
                self.glGetQueryObjectui64v(query, 0x8866, ct.byref(elapsed))
                self.gpu_samples[stage].append(elapsed.value / 1_000_000)
                self.query_free.append(query)
            else:
                remaining.append((stage, query))
        self.query_pending = remaining
        return {stage: sum(values) / len(values) for stage, values in self.gpu_samples.items() if values}

    def _spawn(self, request):
        program, uniforms = self.compute_programs['spawn']
        self.glUseProgram(program)
        self.glUniform1ui(uniforms['capacity'], self.capacity)
        self.glUniform1ui(uniforms['request_count'], request.count)
        self.glUniform1ui(uniforms['request_seed'], self.system.seed)
        self.glUniform1i(uniforms['effect_type'], request.effect_type)
        self.glUniform1ui(uniforms['gain_units'], request.gain_units)
        self.glUniform1f(uniforms['arrival_spacing'], request.arrival_spacing_seconds)
        self.glUniform1f(uniforms['effect_intensity'], request.intensity)
        self.glUniform2f(uniforms['duration_settings'], request.duration_variation, self.spawn_requests_submitted % 65536)
        self.glUniform4f(uniforms['anchors'], *request.start, *request.waypoint)
        self.glUniform4f(uniforms['destination'], *request.destination, 0, 0)
        self.glUniform4f(uniforms['spawn_settings'], request.duration_seconds, request.side,
                         request.spread_pixels, self.system.tail_fraction)
        with self._measure('spawn'):
            self.glDispatchCompute((request.count + 63) // 64, 1, 1)
        self.glMemoryBarrier(STORAGE_BARRIER)
        self.spawn_requests_submitted += 1
        self.dispatch_counts['spawn'] += 1

    def _update(self, delta_seconds, segments):
        self._draw_headers(segments)
        program, uniforms = self.compute_programs['update']
        self.glUseProgram(program)
        self.glUniform1ui(uniforms['capacity'], self.capacity)
        self.glUniform1f(uniforms['delta_seconds'], delta_seconds)
        self.glUniform1i(uniforms['segments'], segments)
        target = self.system.energy_target
        self.glUniform1i(uniforms['energy_enabled'], int(target is not None))
        self.glUniform4f(uniforms['energy_geometry'], *(target[:4] if target else (0, 0, 0, 0)))
        self.glUniform1f(uniforms['energy_ratio'], target[4] if target else 0)
        self.glUniform1ui(uniforms['energy_acknowledged'], self.system.arrived_units)
        self.glUniform1i(uniforms['energy_charge_mode'], int(self.system.energy_charge_total is not None))
        self.glUniform1f(uniforms['energy_charge_total'], self.system.energy_charge_total or 0)
        with self._measure('update'):
            self.glDispatchCompute((self.capacity + 63) // 64, 1, 1)
        self.glMemoryBarrier(STORAGE_BARRIER | COMMAND_BARRIER)
        self.dispatch_counts['update'] += 1

    def _process(self, segments):
        if type(segments) is not int or not 1 <= segments <= MAX_SEGMENTS:
            raise ValueError(f'Trail 구간 수는 1~{MAX_SEGMENTS} 정수여야 한다.')
        dirty = self.last_segments != segments
        # 이전 프레임의 셰이더 접근 뒤에 같은 풀과 draw buffer를 재사용한다.
        self.glMemoryBarrier(STORAGE_BARRIER | 0x0200 | COMMAND_BARRIER)
        if self.generation != self.system.generation:
            self._clear_receipt_fences()
            self._zero(0)
            self._zero(1)
            self.generation = self.system.generation
            dirty = True
        for command in self.system.commands:
            if isinstance(command, SpawnParticles):
                self._spawn(command)
                dirty = True
            elif isinstance(command, StepParticles):
                self._update(command.delta_seconds, segments)
                dirty = False
        if dirty:
            self._update(0, segments)
        self.system.commands.clear()
        self.last_segments = segments

    def render(self, settings, color, core_color, scale=(1, 1)):
        self.collect_timings()
        with self.batch(), self._state():
            if self.generation == self.system.generation:
                self._poll_arrivals()
            self._process(settings['samples'])
            self.glUseProgram(self.program)
            vx, vy, _, _ = self.viewport
            self.glUniform4f(self.uniforms['transform'], vx, vy, *scale)
            self.glUniform4f(self.uniforms['base_color'], *color)
            self.glUniform4f(self.uniforms['core_color'], *core_color)
            self.glUniform1f(self.uniforms['head_width'], settings['head_width_pixels'])
            self.glUniform1f(self.uniforms['orb_radius'], settings['orb_radius_pixels'])
            self.glUniform1i(self.uniforms['segments'], settings['samples'])
            self.glActiveTexture(0x84C0)
            self.glBindTexture(0x0DE1, self.textures[0])
            self.glUniform1i(self.uniforms['artwork'], 0)
            self.glBindBuffer(INDIRECT, self.buffers[3])
            with self._measure('render'):
                self.glUniform1i(self.uniforms['mode'], 0)
                self.glDrawArraysIndirect(0x0005, None)
                self.glUniform1i(self.uniforms['mode'], 1)
                self.glDrawArraysIndirect(0x0005, ct.c_void_p(16))
            self._queue_receipt()

    def _clear_receipt_fences(self):
        for _, fence in self.receipt_pending:
            self.glDeleteSync(fence)
        self.receipt_pending.clear()

    def _queue_receipt(self):
        if self.system.pending_gain_units <= 0 or len(self.receipt_pending) >= len(self.receipt_buffers):
            return
        used = {name for name, _ in self.receipt_pending}
        target = next(name for name in self.receipt_buffers if name not in used)
        self.glMemoryBarrier(0x0200 | STORAGE_BARRIER)
        self.glBindBuffer(0x8F36, self.buffers[1])
        self.glBindBuffer(0x8F37, target)
        self.glCopyBufferSubData(0x8F36, 0x8F37, 0, 0, 16)
        self.receipt_pending.append((target, self.glFenceSync(0x9117, 0)))

    def _poll_arrivals(self, *, wait=False):
        while self.receipt_pending:
            buffer, fence = self.receipt_pending[0]
            status = self.glClientWaitSync(fence, 1 if wait else 0, 1_000_000_000 if wait else 0)
            if status == 0x911B:
                break
            if status not in (0x911A, 0x911C):
                raise RuntimeError('파티클 회복 집계 fence 확인 실패')
            values = (ct.c_uint * 4)()
            self.glBindBuffer(0x8F36, buffer)
            self.glGetBufferSubData(0x8F36, 0, 16, values)
            self.system.accept_receipt(values[1], values[2], values[3])
            self.glDeleteSync(fence)
            self.receipt_pending.pop(0)

    def poll_arrivals(self, *, wait=False):
        """일반 루프는 timeout=0으로 준비된 집계만 읽는다. wait는 검증용이다."""
        if self.generation != self.system.generation:
            return
        with self.batch(), self._state():
            self._poll_arrivals(wait=wait)

    def snapshot(self, *, max_particles=24):
        """검증·벤치마크 종료 전용 동기식 readback. 실제 프레임 루프에서는 호출하지 않는다."""
        with self.batch(), self._state():
            self.glMemoryBarrier(0x0200 | STORAGE_BARRIER)
            commands, counter = (ct.c_uint * 8)(), (ct.c_uint * 4)()
            self.glBindBuffer(SSBO, self.buffers[3])
            self.glGetBufferSubData(SSBO, 0, ct.sizeof(commands), commands)
            self.glBindBuffer(SSBO, self.buffers[1])
            self.glGetBufferSubData(SSBO, 0, 16, counter)
            count = min(self.capacity, max_particles)
            stride = PARTICLE_BYTES // 4
            data = (ct.c_float * (count * stride))()
            self.glBindBuffer(SSBO, self.buffers[0])
            self.glGetBufferSubData(SSBO, 0, ct.sizeof(data), data)
            return dict(active_count=commands[1] // 2, draw_commands=list(commands),
                        spawn_cursor=counter[0], arrived_units=counter[1], arrival_count=counter[2], cancelled_units=counter[3],
                        particles=[list(data[i * stride:(i + 1) * stride]) for i in range(count)])

    def close(self):
        self._clear_receipt_fences()
        if self.receipt_buffers:
            names = (ct.c_uint * len(self.receipt_buffers))(*self.receipt_buffers)
            self.glDeleteBuffers(len(names), names)
            self.receipt_buffers.clear()
        if self.query_names:
            names = (ct.c_uint * len(self.query_names))(*self.query_names)
            self.glDeleteQueries(len(names), names)
            self.query_names.clear()
            self.query_pending.clear()
        for program, _ in self.compute_programs.values():
            self.glDeleteProgram(program)
        self.compute_programs.clear()
        if self.buffers:
            names = (ct.c_uint * len(self.buffers))(*self.buffers)
            self.glDeleteBuffers(len(names), names)
            self.buffers.clear()
        if self.textures:
            names = (ct.c_uint * len(self.textures))(*self.textures)
            self.glDeleteTextures(len(names), names)
            self.textures.clear()
        if self.program:
            self.glDeleteProgram(self.program)
            self.program = 0
