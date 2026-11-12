# Massive Energy Particle Stress

에너지 오브의 생성·갱신 Compute Ubershader와 간접 Instancing을 확인하는 독립 Unit Test다. 게임 상태·모델·AI 이미지 없이 공개 폰트와 수치 설정만 사용한다. Pico2D와 OpenGL 4.3 이상이 필요하다.

```text
python tests/massive_energy_particle_stress.py
```

Runner에서 `massive_energy_particle_stress.py`를 선택하거나 실행된 Runner 창에 드롭해도 별도 창으로 실행한다. 제목은 **Massive Energy Particle Stress**다.

| 입력 | 동작 |
| --- | --- |
| 1~4 | 1,024 / 4,096 / 8,192 / 16,384개 선택·초기화·생성 |
| Space | 선택한 수를 추가 생성. 풀이 가득 차면 이전 생성 슬롯을 순환 덮어쓰기 |
| P | 시간 갱신 정지·재개 |
| R | GPU 풀·생성 카운터 초기화 |
| B | 네 입자 수의 벤치마크를 순서대로 실행·저장. 실행 중 Esc는 측정 취소 |
| Esc / F10 | 일반 시연 종료 |

설정은 `config.json`이다. `capacity`는 풀 크기, `counts`는 네 선택 수, `style.samples`는 Trail 구간 수 1~64다. 수명·색·두께·반경·고정 seed를 조절할 수 있다. 좌우 각각 6개 고정 경로를 사용하며 GPU가 경로 번호를 선택한다. 폰트 경로는 샘플 위치를 기준으로 해석한다.

## 벤치마크

```text
python tests/massive_energy_particle_stress.py --benchmark
python tests/massive_energy_particle_stress.py --benchmark --hidden --counts 1024,4096,8192,16384 --warmup 30 --benchmark-frames 120
```

- 기본은 예열 30프레임·측정 120프레임·고정 1/60초다. 측정 중 소멸하지 않도록 해당 실행의 수명을 늘린다. 생성은 왼쪽/오른쪽 요청 두 번을 먼저 측정한다.
- CPU 시간은 공통 `TimingRecorder`의 **입자 렌더 호출 경과 시간**이다. dispatch·그리기 제출·드라이버 대기를 포함하며 UI 글자·present는 제외한다. 순수 Python 계산 시간으로 해석하지 않는다.
- GPU 시간은 `GL_TIME_ELAPSED`로 생성·갱신·렌더를 따로 측정한다. 모든 측정 프레임을 수집하도록 쿼리를 미리 확보한다. 생성 `total_ms`는 두 요청의 합, `mean_ms`는 요청당 평균이다. 갱신·렌더 평균은 프레임당 시간이다. 배리어·CPU API 호출·UI·화면 합성 전체 시간을 의미하지 않는다.
- GPU 상태·활성 수의 동기식 readback은 각 측정 구간이 끝난 뒤에만 수행한다. 측정 구간 안에서는 GPU가 활성 목록·간접 그리기 개수를 만든다.
- 결과는 `output/performance/massive_energy_particle_stress.json`, CPU 원본은 같은 폴더의 입자 수별 `_cpu.json`이다. `--output`으로 별도 경로를 지정한다. GPU 제조사·렌더러·드라이버 버전·해상도·설정·실제 활성 수·샘플 수를 기록한다. 옵티머스 환경에서는 기존 창과 새 프로세스가 같은 GPU인지 결과로 확인한다.
- `--capacity`는 최대 65,536이다. 실제 사용 가능 크기는 GPU의 SSBO 한도·메모리에 따라 제한된다. 기본 풀 16,384개는 버퍼·아틀라스 약 83.8MiB를 사용한다.
- 같은 화면에 입자를 집중시키는 고정 시연이다. 일반 게임 장면 FPS·전체 프레임 성능·실제 창 사용감·최종 외관 승인과 구분한다.

`--capture output/compute_particles/stress.png`로 재생성 가능한 화면을 저장한다. UI에 실제 선택된 OpenGL GPU와 CPU/GPU 시간을 표시한다.
