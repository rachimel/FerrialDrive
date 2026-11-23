# CPU·메모리·GPU 기능 제한 벤치마크

`tests/hardware_profile_benchmark.py`는 Runner에서 선택하거나 직접 실행하는 독립 테스트다. **기본은 실제 검 이동 훈련장을 직접 조작한다.** Windows와 Pico2D/OpenGL이 필요하다. 게임 이미지·모델 없는 공개 도형 시연은 `--scenario demo`로 선택한다.

```text
python tests/hardware_profile_benchmark.py
python tests/hardware_profile_benchmark.py --scenario demo
python tests/hardware_profile_benchmark.py --auto --warmup 165 --frames 600
python tests/hardware_profile_benchmark.py --auto --no-resource-limits --gpu-profile none --warmup 165 --frames 600
python tests/hardware_profile_benchmark.py --auto --target-fps 165 --warmup 165 --frames 600
```

## Combat Test 연결과 보고서

기본 렌더러는 `native_gl`이다. SDL OpenGL과 비교할 때는 `--render-driver opengl`을 사용한다. 보고서의 `render_driver`에 요청한 경로를 기록한다. 직접 경로에서 `NativeGlRenderer.flush`는 호환 호출이 정점 상태를 정리한 비용이다. SDL 큐 제출 시간은 `SDL_RenderFlush`로 따로 기록한다.

화면 해상도는 게임 설정의 저장값을 적용한다. `resolution_initial`·`resolution`에 시작·종료 시 실제 출력 픽셀 수를, `logical_resolution`에 UI·월드의 논리 크기를 기록한다. `resolution_changed=true`이면 한 실행 중 서로 다른 출력 조건이 섞였으므로 고정 해상도 성능으로 해석하지 않는다. 텍스처 품질과 출력 해상도는 별도 설정이다.

Unit Test Runner에서 이 파일을 더블클릭·Enter·드롭하면 `Combat` / `Movement`를 선택한다. 둘 다 직접 조작·상세 계측이며 정상 창 종료 시 보고서를 저장한다. 자동 공격·프레임 제한은 추가하지 않는다. `Movement`는 CLI의 `--scenario sword`와 같다. Esc는 실행 선택 취소이며 기존 테스트를 유지한다. 파일 인자 실행은 `python Tools/unit_test_runner/run.py tests/hardware_profile_benchmark.py --preset combat` 또는 `--preset movement`를 사용한다.

Runner의 `Combat · 1,000기 · HP 10만`은 자원 제한 없이 24m 간격으로 적 1,000기를 배치한다. 플레이어 최대 HP는 100,000이며 F5 재시작 때 회복한다. 선택창의 `무음` 체크박스를 켜면 이번 실행의 효과음을 끈다. 직접 조작하고 정상 종료하면 보고서를 저장한다. `player_health_initial`에 시작한 현재·최대 HP를 기록한다.

`--scenario combat`은 `tests/combat_test_v1_5.py`와 같은 `EncounterApplication`과 적 배치 JSON을 사용한다. 기본 배치는 소형 22기·중형 6기·인간형 2기이며 `--encounter`로 다른 배치를 지정한다. 기존 훈련장 기본 실행은 유지한다.

```text
python tests/hardware_profile_benchmark.py --scenario combat
python tests/hardware_profile_benchmark.py --scenario combat --detail --quality medium
python tests/hardware_profile_benchmark.py --scenario combat --auto --auto-weapon smg --frames 600 --warmup 120
python tests/hardware_profile_benchmark.py --scenario combat --auto --auto-weapon smg --auto-overdrive --detail --quality medium --frames 600
python tests/hardware_profile_benchmark.py --scenario combat --auto --compare baseline no_hud no_camera_blur --rounds 2
python tests/hardware_profile_benchmark.py --scenario combat --movement-speed-multiplier 3
python tests/hardware_profile_benchmark.py --scenario combat --demo --auto --frames 120
```


```text
python tests/hardware_profile_benchmark.py --mute --scenario combat --enemy-count 1000 --enemy-spacing-m 12 --player-hp 100000 --auto --auto-weapon smg --target-fps 60 --warmup 30 --frames 120 --unpaced --no-resource-limits --gpu-profile none
```

현재 그래픽 설정과 카메라에서 직접 조작하는 무음 시험은 다음과 같이 실행한다. 창을 닫으면 보고서를 저장한다.

```text
python tests/hardware_profile_benchmark.py --mute --scenario combat --enemy-count 1000 --enemy-spacing-m 24 --player-hp 100000 --no-resource-limits --gpu-profile none
```

같은 조건에서 24m 간격을 주면 더 넓게 분산된다. `--auto`의 시뮬레이션 시간은 고정 스텝이며 실제 표시 FPS와 프레임 시간은 `report.json`에 별도로 기록한다.

일반 교전에서는 록온 HUD로 선택한 적의 이름과 체력을 표시한다. 무음 자동 교전에 `--compare baseline debug_enemy_labels no_hud --rounds 2`를 추가해 비용을 비교한다. `debug_enemy_labels`는 화면 내 각 적에 이름·상태·체력 막대와 Break 글자를 추가한다. 기존 `no_enemy_labels` 인자도 기본 표시로 실행된다. `no_hud`는 플레이어 HUD 그리기를 생략한다. 각 회차의 `cpu_ms.draw_submit_ms`와 `work_ms.p95`를 확인한다.

기체 묶음의 비용은 위 명령에 `--compare individual_enemy_parts individual_enemy_shadows baseline --rounds 2`를 추가해 같은 프로세스에서 실행 순서를 뒤집어 비교한다. 첫 조건은 근거리 본체·그림자를 개별 제출하고 둘째는 그림자만 개별 제출한다. 기본 경로는 둘 다 묶는다. 세 조건 모두 근거리 보간율과 원거리 공유 정책이 같다. `enemy_rendering_last`의 `batched_bodies`는 묶어 그린 기체 수, `body_batch_submits`와 `near_shadow_batch_submits`는 각각 본체 PBR과 지면 그림자 표시의 인스턴스 드로우 횟수다. 깊이 타일 갱신과 최종 화면 합성은 이 두 횟수에 포함하지 않는다.

- 직접 조작은 창을 닫으면 저장한다. `--auto`는 레벨 3으로 2초마다 전투·HP·무장을 초기화하고 가장 가까운 생존 적을 조준한다. 기본 무장은 검이며 `--auto-weapon smg`로 기관단총을 선택한다. 전환 애니메이션과 재초기화 비용도 측정에 포함한다. `--auto-overdrive`는 매 반복 시작에 기존 강제 발동 경로를 사용한다. 실제 충전 구간을 측정하는 옵션은 아니다. 두 옵션은 `--auto`와 함께 사용한다.
- `--movement-speed-multiplier 3`은 3배속 combat test의 같은 배율 옵션이다. `--demo`는 게임 이미지·모델 없이 플레이어 도형을 사용하며 실제 에셋 결과와 구분한다.
- 매 실행의 `report.json`에 원자료, `<시각>.md`에 한국어 표 보고서를 저장한다. 실패한 실행도 원인이 있는 범위에서 보고서를 생성하며 미측정값을 0으로 채우지 않는다. `limits_final.json`을 읽어 최대 프로세스 커밋을 보고한다. `python -m ferrial_drive.diagnostics.benchmark_report <실행폴더>/report.json`으로 보고서와 계측 데이터가 있는 Flamegraph를 다시 생성할 수 있다.
- 측정한 계측 구간이 있으면 보고서 옆에 `flamegraph.svg`를 저장한다. 직접 조작은 `report/interactive/<시각>/`에서 보고서의 링크로 연다. 아래 블록이 호출자이며, 폭은 측정 구간 전체에서 누적한 wall 시간 비중이다. 마우스를 올리면 경로와 포함·자체 시간을 확인할 수 있다. 자동 대조는 조건·회차마다 폭을 따로 정규화하므로 절대 시간은 각 합계나 블록의 ms 값을 확인한다.
- Flamegraph 아래의 표는 블록과 같은 호출 경로 순서와 깊이로 전체 함수·구간 이름을 표시한다. 포함 시간·자체 시간은 ms이며, 시간 비중은 해당 그래프에서 계측한 전체 시간 대비 포함 시간이다. 같은 부모 아래에서는 첫 호출 순서로 배치하고 반복 호출은 경로별로 누적한다. 순서가 없는 이전 원자료는 이름순으로 배치하고 표에 표시한다.
- Flamegraph는 벤치마크에서 실제로 계측된 함수·구간만 표시한다. 준비 프레임은 제외하며 대기와 계측 오버헤드는 포함할 수 있다. 전체 Python 스택 샘플링은 [FDrive Profiler](../../Tools/profiler/README.md)를 사용한다.
- 직접 조작은 보존한 예산 초과 프레임 중 `draw_live_combat_motion`이 실행된 프레임의 포즈 준비·그림자 준비·그림자 제출·파츠 합성 시간을 별도 표에 남긴다. 호출 경로의 자체 wall 시간은 가장 가까운 계측 구간에 한 번만 집계한다. 그림자 준비에는 캐스터 표면 생성이 포함되며 그 밖의 모션 비용은 기타로 표시한다. 각 행에서 `flamegraphs/frame-<번호>.svg`를 열 수 있다. 해당 호출 경로만 보존하며 직접 조작의 기존 최근 3,600프레임 보존 범위를 따른다.
- 직접 조작의 예산 초과 프레임은 대화창 그리기를 텍스트·필터 폴리곤·스캔라인·기타로 나눠 `dialogue_timings_ns`와 Markdown 표에 남긴다. 텍스트에는 `rich_text` 안의 글자 측정과 배치가 포함된다. 스캔라인 내부의 호출은 스캔라인에만 집계하며 HUD 레이아웃 사전 탐색과 다른 패널 비용은 제외한다.
- `draw_breakdown.combat_activity`는 **측정 구간 update 직후**의 생존 적 수·양측 투사체 수 평균/최대, 전투 진행·Overdrive 프레임 수와 마지막 적 렌더링 통계를 기록한다. 마지막 렌더링 통계는 전체 평균이 아니다. 적 사망·전투 종료로 부하가 낮아진 구간을 확인한다.
- 기본 계측에 `update.total`을 추가한다. `--detail`에서 `update.targets`, `update.guns`, `update.hud`, `update.encounter`, `update.enemies.*`, `world.enemies`, `world.gun_effects`를 구분한다. `update.enemies._move`는 다수 적 이동·밀어내기 호출을 포함한다. 중첩 구간은 합산하지 않는다. 준비 프레임과 반복 초기화 내부 호출은 이 구간 집계에서 제외하지만 프레임 작업 시간에는 반복 초기화를 포함한다.
- 보고서는 p50/p95/p99·최대 프레임 시간, 예산 초과율, 처리 구간, 조건별 각 회차를 표시한다. 병목 확정이나 자동 최적화를 수행하지 않는다. cProfile·상세 계측 결과로 FPS 목표 달성을 확정하지 않고 같은 조건의 기본 계측 실행과 함께 검토한다.

기본 프로필은 `samples/hardware_profile_benchmark/profile.json`이다. 최소 사양 검증 기준은 i3-10100·UHD 630·RAM 8GB·SSD 256GB에서 FHD 60FPS이며, **현재 PC를 해당 장비 성능으로 보정한 것이 아니다.** 권장 목표는 FHD 165FPS이며 구체적인 부품은 미정이다. 현재 기본 제한은 논리 CPU 8개·Job CPU 시간 상한 50%·프로세스/Job 커밋 상한 2048MiB다. 메모리 상한은 사용자가 지정한 2GiB 여유이며, 자원 사용량 절감이나 목표 예산 충족을 뜻하지 않는다. 8개 논리 CPU의 affinity는 4코어/8스레드의 구조나 성능을 재현하지 않는다. P/E 코어 구성·클럭·캐시·메모리 대역폭·GPU 처리량·저장 장치 속도는 바뀌지 않으며, 전체 RAM 8GB 환경도 에뮬레이션하지 않는다.

## 자원 제한

- 부모가 테스트 자식을 시작하고, 자식은 게임·Pico2D import 전에 stdin 신호를 기다린다. 부모는 Windows Job과 affinity를 적용하고 조회 결과가 요청과 일치할 때만 신호를 보낸다. 제한을 적용하지 못하면 종료한다.
- `--logical-cpus 8`, `--cpu-percent 50`, `--memory-mib 2048`로 덮어쓴다. 이전 1GiB 상한을 별도 확인하려면 `--memory-mib 1024`를 사용한다. 현재 허용된 CPU 중 낮은 번호부터 선택한다. CPU 번호와 실제 상한은 보고서에 남긴다. 다중 processor group의 전체 코어 선택은 구현하지 않았다.
- CPU 상한은 스케줄링 구간의 실행 시간 할당량이다. 소진하면 다음 구간까지 멈출 수 있다. 느린 CPU의 명령 처리 속도와 같지 않다. 50%가 메인 스레드를 절반 속도로 만든다는 뜻도 아니다.
- 메모리 상한은 물리 RAM이나 VRAM이 아닌 **committed virtual memory**다. 프로세스/Job 전체에 적용한다. 기존 1GiB 게임 전체 예산의 모든 CPU/GPU 자원을 통합 제한하지 않는다. GPU 전용/공유 메모리는 WDDM 카운터를 별도 기록하며 private bytes와 단순 합산하지 않는다.
- 커밋 상한의 1/16과 128MiB 중 작은 값을 종료 여유로 둔다. 프레임 시작 전 Private Bytes가 이 구간에 들어오면 측정을 중단하고 그때까지의 결과와 `memory_stop`을 저장한다. Runner의 `Combat · 실기 제한 없음`은 동일한 30기 교전을 CPU·커밋 제한 없이 실행한다.
- 전투 수치 커널은 NumPy가 초기화되기 전에 OpenBLAS 작업 스레드 기본값을 1로 둔다. 이동·탄환의 Numba 커널은 같은 경로를 사용한다. 호출자가 지정한 OpenBLAS·OpenMP 스레드 설정과 이미 초기화된 NumPy를 존중한다.
- Job 핸들을 닫으면 그 Job의 자식만 정리한다. Codex·Runner 부모나 컴퓨터 전체의 CPU·전원·RAM 설정은 바꾸지 않는다.
- Windows API 의미는 [CPU rate control](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_cpu_rate_control_information), [extended limits](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information)를 따른다. 별도 psutil/pywin32 설치는 필요 없다.

## UHD 630 검토 프로필의 검사 범위

기본 Combat·Movement는 현행 PBR을 실제 GPU 기능으로 실행하며 CPU·커밋 제한을 적용한다. UHD 630 기능 가드는 `--gpu-profile uhd630_gl45_conservative`로 선택한다. 프래그먼트 텍스처 16단위에서 동작하는 베이크 경로를 검토하려면 `--player-pipeline baked`를 함께 지정한다.

[Intel 명세](https://www.intel.com/content/www/us/en/products/sku/199283/intel-core-i310100-processor-6m-cache-up-to-4-30-ghz/specifications.html)의 OpenGL 4.5를 기준으로, 현재 프로젝트가 쓰는 기능만 허용한다. `uhd630_gl45_conservative`라는 이름은 **UHD 630 실기의 전체 cap 덤프나 드라이버 에뮬레이터**를 뜻하지 않는다. 수치들은 실기 확인 전의 보수적인 검사 상한이다. Compute·SSBO·Instancing·BC7을 사용할 수 있다.

| 검사 항목 | 상한·정책 |
| --- | --- |
| GL 진입점 | 현재 프로젝트의 검토된 함수 목록. 새 함수·벤더 전용 함수는 차단 |
| GLSL | 450 이하, 확장의 require/enable/warn 차단 |
| 2D 텍스처 | 한 변 16,384px 이하 |
| 활성 텍스처 단위 | 16개 이하 |
| 단일 버퍼 할당 | 128MiB 이하. SSBO 외 버퍼에도 적용하는 보수적 정책 |
| SSBO binding | 8개 이하 |
| Compute dispatch | 축마다 65,535 이하 |
| Compute local size | 숫자로 선언한 축 1,024/1,024/64 이하, 총 1,024 이하 |
| shared memory 질의 | 32KiB 이하로 제한. 셰이더 실제 선언 용량 분석은 제외 |

호스트가 더 낮은 cap이면 올리지 않는다. `actual_caps`와 `effective_caps`를 따로 기록한다. 실제 GPU 이름과 버전을 위장하지 않는다. 프로젝트 공통 `bind_gl` 및 SDL 텍스처 생성 3경로를 검사한다. SDL 내부 GL 호출, 전체 GLSL 자원 사용량·매크로로 만든 local size, GL 상수·형식 전체, 드라이버 특이 동작은 완전히 검증하지 않는다. [OpenGL 명세](https://registry.khronos.org/OpenGL/specs/gl/glspec45.core.pdf)의 전체 적합성 검사를 대체하지 않으며, 실제 UHD 630 실행 검증이 필요하다.

## 계측과 결과

- 직접 조작은 WASD·마우스 조준·좌클릭 공격·Shift 대시·Space 부스트 등 기존 입력을 그대로 받는다. Esc는 일시정지이며 **창 닫기로 종료·결과 저장**한다. F3/F4 에너지 조절·E/F 무장/로드아웃 등 기존 HUD 입력도 전달한다. 자동 공격·자동 초기화는 하지 않는다.
- 직접 조작은 `--frames`를 생략하면 시간 제한 없이 실행한다. 직접 조작과 자동 측정 모두 창 제목에 최근 약 1초 FPS, 직전 프레임의 HUD·월드 ms, 최신 프로세스 RAM Working Set과 GPU 메모리를 표시한다. GPU는 WDDM 전용·공유 값 또는 DXGI 로컬 값을 보여 준다. 현재 저장 설정을 결과 폴더로 복사해 사용하며 사용자 설정 파일은 건드리지 않는다. 품질을 고정하려면 `--quality`로 등급을 지정한다. 이름별 해상도는 현행 설정을 따르고 실제 아틀라스 `divisor`를 함께 기록한다.
- 장시간 조작 시 프레임·GPU 표본은 최근 최대 3,600개만 보관한다. `observed_fps`·분포·목표 판정은 그 표본 구간, `session_observed_fps`와 `total_measured_frames`는 전체 측정 세션이다. HUD/월드 구간 집계는 측정 시작부터 전체 세션을 포함한다.
- 직접 조작에서는 `--detail`과 관계없이 보존 표본 중 작업 예산을 넘긴 각 프레임에 실제 발사 수·총기 슬롯, 백웨폰 미사일 발사 수, 로드아웃 전환 시작·적용과 현재 상태를 붙인다. 예열 이후부터 기록하며 입력이 거절되거나 공발이면 발사 기록을 남기지 않는다.
- Markdown의 **느린 프레임과 전투 이벤트** 표는 프레임 번호, 측정 시작 이후 초, 작업 시간, 실제 이벤트와 함수별 포함·자체 wall 시간 및 호출 수를 함께 표시한다. 자체 시간 기준 상위 5개와 이벤트에 해당하는 함수를 보여 준다. `benchmark.frames[].function_timings_ns`에 계측한 모든 함수가 있고 각 값은 `[호출 횟수, 포함 ns, 자체 ns]`다. `function_scopes`는 구간 이름과 함수 이름을 연결한다. 자체 시간은 계측한 하위 호출을 뺀 값이며 계측 오버헤드와 드라이버의 내부 실행 시간은 따로 보정하지 않는다.

- 기본은 FHD 1920×1080, 최소 목표 60FPS 제한, VSync 꺼짐이다. 권장 목표의 시간 예산은 `--target-fps 165`로 선택한다. `--unpaced`면 프레임 대기를 없앤다. `--target-fps`는 자동 갱신 시간과 프레임 예산을 같이 바꾼다. 일반 게임 실행의 60FPS 기본값은 유지한다.
- 직접 조작은 실제 프레임 경과 시간으로 갱신한다. `--auto`만 고정 `1 / target_fps`초로 레벨 3 공격을 유지하고, **측정 시작을 기준으로** 시뮬레이션 2초마다 초기화한다. 기본은 `1/60`초이며 권장 목표는 `1/165`초다. 자동 시험은 종료 이벤트만 반영하며 렌더가 느리면 시뮬레이션도 실제 시간보다 느리다. catch-up 테스트는 아니다.
- 기본 준비는 120프레임이며 자동 시험의 기본 측정은 600프레임이다. 초기 셰이더 준비와 에셋 로딩은 전투 프레임에서 제외하고 `load_seconds`에 따로 기록한다. 이 값은 전체 프로세스 시작 시간이 아니다.
- `work_ms`는 이벤트·갱신·그리기 제출·present의 wall 시간이다. 대기는 `interval_ms`에 포함한다. `observed_fps`는 샘플링 비용을 포함한 측정 구간 전체 시간으로 계산한다. 계측 오버헤드는 별도 보정하지 않는다.
- p50/p95/p99, 선택한 프레임 예산(최소 약 16.67ms·권장 약 6.06ms)의 초과 횟수·비율, 전체 완료 여부를 함께 기록한다. `target_met`은 측정 완료·work 초과 0회·실측 FPS가 목표의 99% 이상일 때만 참이다. 기능 위반이 있으면 `status=feature_violation`이므로 성공한 실행으로 해석하지 않는다.
- `GL_TIME_ELAPSED`는 draw와 SDL flush 구간이며 제출 간격도 포함할 수 있다. CPU wall 시간이나 GPU 전용 실행 시간과 같지 않다. HUD와 월드는 공통 `TimingRecorder`로 측정 구간만 분리한다.
- 직접 조작 결과는 `report/interactive/<시각>/`에 저장하고, `report/직접조작.md`는 기존 폴더를 포함해 `input_mode=interactive` 보고서만 모아 링크한다. 기본 자동 결과는 `output/performance/hardware_profile/<시각>/`에 저장한다. `--output`으로 새 폴더를 지정할 수 있다. 각 실행 폴더에 `report.json`, 시각을 붙인 Markdown, `limits_final.json`, `timings.json`을 함께 남긴다.

## HUD·월드 병목 분석

지면 효과 대조는 다음 명령을 사용한다. `--auto-dash`는 자동 반복마다 오른쪽 이동과 대시를 유지해 입자 부하를 만든다. 생략한 기존 자동 입력은 유지한다. 지면 입자 난수 상태는 각 조건 시작에 같은 상태로 복원한다. 게임의 정상 초기화 규칙은 바꾸지 않는다.

```text
python tests/hardware_profile_benchmark.py --scenario combat --auto --auto-weapon smg --auto-dash --quality low --detail --compare ground_individual ground_batched --rounds 2 --warmup 60 --frames 240
```

`ground_individual`은 파티클별 uniform·쿼드 제출, `ground_batched`는 공통 아틀라스·인스턴스 제출이다. 앞·뒤 레이어와 입자 순서는 유지한다. `draw_breakdown.ground_effects_backend`, `ground_effects_per_frame`에 실제 경로와 입자·드로우·업로드 bytes·CPU 버퍼 재할당의 프레임 평균을 기록한다. 입자는 앞·뒤 레이어 제출 합계이므로 두 레이어에 걸친 공간 분할 입자는 중복 집계될 수 있다. `--detail`에서는 `world.ground_effects` wall 시간도 기록하고 Markdown에 조건별 표를 만든다. 상세 계측·CPU 제한을 포함한 결과이며 전체 게임 FPS 개선과 해당 구간의 절감량을 구분한다.

```text
python tests/hardware_profile_benchmark.py --auto --detail --frames 660 --warmup 90
python tests/hardware_profile_benchmark.py --auto --call-profile --frames 330 --warmup 90
python tests/hardware_profile_benchmark.py --auto --compare baseline no_hud no_trail no_ui_blur no_camera_blur no_actor_blur no_rings --rounds 2 --frames 330 --warmup 90
python tests/hardware_profile_benchmark.py --auto --quality medium --compare cpu_trail compute_trail --rounds 2 --frames 660 --warmup 90
python tests/hardware_profile_benchmark.py --auto --compare no_hud_batch baseline --rounds 2 --frames 360 --warmup 120 --unpaced
```

`--detail`은 HUD 표시/패널 사전 순회·구성 요소·월드 지형/그림자/Trail/잔상/기체/지면 효과·블러 준비/합성 시간을 구분하고 SDL 호출 수를 센다. `draw_breakdown.timings`의 중첩 구간은 합산하지 않는다. 상세 계측 오버헤드를 포함하므로 실제 절감량은 별도 대조를 우선한다. 공유 기체 아틀라스의 draw에는 본체와 잔상이 모두 들어간다.

`--variant`는 테스트 프로세스에서만 해당 표시를 생략한다. 게임 규칙·판정·제품 설정 변경이 아니다. `--compare`는 한 번 로드한 같은 장면·설정에서 여러 조건을 순차 실행하고 홀수/짝수 회차의 순서를 뒤집는다. 중간에 파일을 편집해도 이미 로드한 장면을 다시 읽지 않는다. 기본 조건마다 준비 프레임을 실행해 캐시를 준비한다. 보고서의 `comparisons`와 `progress.jsonl`에 각 결과를 남기고 `config_snapshot`에 실제 사용 설정을 기록한다. 맨 위 benchmark는 마지막 실행 조건이며 비교 평균이 아니다.

`no_hud_batch`는 표시를 생략하지 않고 HUD 큐만 끈다. baseline은 같은 도형을 연속 상태별로 묶고 정점·인덱스·사각형 버퍼를 재사용한다. `hud_batch_enabled`는 활성 여부, `hud_batch_last`는 마지막 HUD 배치의 요청·실제 제출·버퍼 할당 수다. 마지막 배치 값은 측정 전체의 평균이 아니다. 큐를 끈 경우 마지막 배치 값은 null이다. 상세 SDL 호출 수에는 `SDL_RenderFillRects`도 포함한다. 큐를 켜기 전의 다른 소스·품질 결과와 이 대조를 합산하지 않는다.

블러 대조는 UI 영역 필터·카메라 월드 필터·기체 시간축 셔터를 각각 구분한다. 잔상 자체나 프레임 보간을 끄는 조건은 아니다. `--call-profile`은 별도 시험에서 `calls.prof`를 저장하며 자체 오버헤드가 커 FPS 판정용으로 사용하지 않는다. 전체 draw의 GPU elapsed는 기록하지만 세부 항목별 GPU 전용 시간은 아직 측정하지 않는다.

`cpu_trail`과 `compute_trail`은 같은 전투·판정을 유지한 채 정점 생성 경로만 바꾼다. `trail_backend`와 `trail_fallback`으로 실제 Compute 사용을 확인한다. 현재 기본 baseline은 Compute이며 이전 CPU 기본 기록과 구분한다. 이 가드는 UHD 630 처리량을 에뮬레이션하지 않는다.

## 다른 프로그램 연결

재사용 모듈은 `ferrial_drive/diagnostics/`에 있다. `resource_limits.ResourceLimits/WindowsJobLimits/run_gated_child/wait_for_limits`로 제한 적용을 구성한다. 자식 진입점은 게임 import 전에 반드시 게이트를 기다린다. 제한 없는 일반 실행과 분리한다.

캔버스를 만든 뒤 리소스를 불러오기 전에 `gpu_profile.Uhd630Profile(pico)` 범위를 열고, 리소스를 닫은 뒤 범위를 끝낸다. GL 함수는 같은 모듈의 `bind_gl`로 가져온다. `frame_benchmark.benchmark_program`은 공통 `update/draw/running` 실행 규약과 열린 `PicoCanvas`에 연결한다. 창과 `enter/exit`는 호출자가 소유하며 모듈 import는 창이나 제한을 만들지 않는다.

기본 도형·플레이어 1기 훈련장과 `combat`의 현재 설정 배치를 측정한다. 수백 기·여러 에셋 기종과 QHD는 별도 시나리오로 측정해야 한다. 실기 보정 전 결과를 i3-10100/UHD 630의 FPS로 환산하지 않는다.
