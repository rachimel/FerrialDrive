# FDrive 공통 실행부·렌더링

본편·에셋 도구·독립 테스트는 같은 Pico2D/OpenGL 기반을 사용한다. 모듈을 import하는 것만으로 Pico2D를 불러오거나 창을 열지 않는다.

| 모듈 | 책임 |
| --- | --- |
| `ferrial_drive.runtime` | 프로그램 생명주기·입력 전달·초 단위 시간·표시 루프·프레임 제한·선택적 계측 |
| `ferrial_drive.rendering.canvas` | Pico2D 캔버스 생성/종료·OpenGL 요청·드라이버 정보 |
| `ferrial_drive.rendering.bicubic` | SDL 텍스처의 GPU Bicubic 표시·GL 상태 저장/복원 |
| `ferrial_drive.assets` | 에셋 검증·공유·핫 로드·스프라이트 표시 |
| `ferrial_drive.ui.pico_renderer` | 글자·도형·HUD 표현 |

공통 실행부는 `Tools`·테스트·특정 게임 장면을 참조하지 않는다. 본편 진입점과 전투/ADV 장면 관리는 아직 별도로 구성해야 한다.

## 검 Trail 정점 생성

훈련장의 기본 Trail은 `compute_sword_trail.ComputeSwordTrail`을 사용한다. CPU는 실제 궤적·판정과 표시 구간 분류를 유지하고, 작은 제어점 배열만 전송한다. GPU Compute가 곡선 보간·띠 정점·UV·색/알파를 생성하고 같은 SSBO를 vertex shader에서 바로 읽어 Instancing으로 표시한다. 런타임에서 정점을 CPU로 다시 읽지 않는다.

생성 다음의 shader storage 접근은 `glMemoryBarrier(GL_SHADER_STORAGE_BARRIER_BIT)`로 연결한다. 검사에서만 사용하는 CPU readback에는 별도 buffer update barrier를 사용한다. 메모리 가시성은 [Khronos 공식 설명](https://wikis.khronos.org/opengl/GLAPI/glMemoryBarrier)을 따른다.

OpenGL 4.3 기능이 없는 경로는 CPU 표시로 돌아간다. Compute 컴파일·실행 오류를 정상 CPU 성공으로 숨기지 않는다. CPU 기준 구현은 `PicoSwordEffects(..., trail_backend="cpu")`, 훈련장 설정은 `sword_effects.trail_renderer`로 선택한다. 기본 프로그램은 Compute를 요청하며 첫 Trail 표시 때 프로그램을 준비한다.

검 궤적·충돌·타격당 중복 명중 방지는 CPU 전투 모듈의 책임이다. GPU 정점과 CPU 원본의 좌표·UV·알파 및 실제 화면은 별도 검사한다. 실측과 미검증 범위는 [최신 기록](ai-dev-log/2026-11-15-compute-trail-shadow-quality.md)을 따른다.

## 본편 연결

일반적인 실행은 `ferrial_drive.runtime.run_application(program, width=..., height=..., title=...)`을 호출한다. `program`은 다음 규약을 제공한다.

| 항목 | 역할 |
| --- | --- |
| `running` | 실행 중인 bool. 종료할 때 False로 바꾼다. |
| `enter()` | 열린 캔버스에서 게임 장면·에셋·UI 자원 준비 |
| `handle_event(event)` | 입력 처리. Esc 등 게임별 입력은 프로그램에서 결정 |
| `update(delta_seconds)` | 초 단위 경과 시간으로 갱신 |
| `draw()` | 화면 지우기와 장면/UI 그리기 |
| `exit()` | 에셋 관리자·폰트·텍스처 해제. 부분 초기화 실패에도 호출 가능해야 함 |

기본은 OpenGL·60FPS 제한·VSync 꺼짐이다. `frames_per_second`, `vsync`, 검증용 `frame_limit`를 실행 인자로 지정한다. VSync는 창 생성 시 요청하는 값이다. `renderer_info(pico).vsync_flag`는 SDL이 보고한 플래그이며 실제 표시 타이밍 측정을 대신하지 않는다. 근거: [SDL 렌더러 정보](https://wiki.libsdl.org/SDL2/SDL_RendererInfo). 본편 설정 UI·저장·실행 중 VSync 변경 기능은 별도다.

`accept_text = True`이면 UTF-8 입력·IME 조합·반복 키를 전달한다. `render_driver` 속성으로 기본 OpenGL 요청을 바꿀 수 있다. `None`이면 SDL이 선택한다. 실제 드라이버가 OpenGL이 아니면 에셋 Bicubic은 Linear로 대체된다. GLSL 컴파일 실패는 오류로 보고한다.

SDL 종료 입력은 루프가 처리한다. 시작·입력·갱신·그리기에서 예외가 발생해도 `exit()` 다음에 캔버스를 닫는다. 한 프로세스의 렌더 스레드에서 캔버스 하나만 사용한다. 멀티 윈도우·멀티 렌더 스레드 구조가 아니다. 경과 시간 전달은 가변 주기이며 고정 주기 게임 시뮬레이션은 아직 포함하지 않는다.

## 별도 루프와 자원 수명

자체 게임 루프가 필요하면 `with PicoCanvas(width, height, title) as canvas:`를 사용한다. `canvas.pico`에서 기존 Pico2D/SDL API를 사용하고 `canvas.present()`로 표시한다. `canvas.info`는 실제 드라이버 이름과 SDL이 보고한 가속·VSync 플래그·렌더 타깃 지원 정보다.

본편·이동 훈련·전투 테스트와 하드웨어 벤치마크의 기본 렌더러는 `native_gl`이다. 창·입력·이미지 해석·오디오는 Pico2D와 SDL을 사용한다. 텍스처·렌더 타깃·뷰포트·클립·블렌드와 화면 표시는 FDrive의 OpenGL 코드가 관리하며 SDL 렌더러 생성과 큐 제출은 생략한다. OpenGL 4.3 호환 프로필이 필요하다. 비교용 `--render-driver opengl`과 SDL dummy 자동 검사 경로를 지원한다. 독립 도구의 `PicoCanvas()` 기본 드라이버는 `opengl`이다. [그림자·성능 비교](ai-dev-log/2026-11-23-native-gl-direct-optimization.md)

직접 경로에서 연속 바닥 타일은 순서를 유지한 채 한 번 제출한다. 공통 셰이더 패스는 직접 경로가 설정한 상태를 재사용하고, 별도 GL 패스에서 이어지는 경계는 실제 상태를 확인한다. 아틀라스 텍스처는 빈 RGBA 저장소를 만들지 않고 원래 채널 및 압축 형식으로 올린다.

생성 순서는 **캔버스 → 에셋 관리자·UI → 장면**이다. 종료는 **장면·에셋 관리자·폰트/텍스처 → 캔버스** 순서다. 렌더러가 닫힌 뒤 GPU 자원을 그리거나 해제하지 않는다. `run_application()`의 `exit()`는 이 순서를 보장하는 연결 지점이다. 캔버스가 게임의 에셋 관리자를 대신 소유하지는 않는다.

OpenGL 요청을 위해 바꾼 SDL 드라이버 힌트는 초기화 후 원래 값으로 돌린다. 생성에 실패한 경우 소프트웨어 렌더러를 시도하며 SDL dummy는 OpenGL을 요청하지 않는다. 적용 여부는 요청값 대신 실제 드라이버와 `resource.filtering`으로 확인한다. Pico2D 라이브러리 원본은 수정하지 않는다.

## 스프라이트와 SDL UI 합성

`PicoAssetBackend`·`PicoSprite`는 같은 `rendering.bicubic` 구현을 사용한다. 샤프닝은 프리렌더 패킹 단계이고 Bicubic은 화면 표시 단계다. 프레임별 경계·알파 처리를 유지한다.

여러 에셋은 `with resource.render_batch():` 안에서 연속으로 그릴 수 있다. 이 문맥은 GL 상태 변경과 복원을 묶는다. GPU 인스턴싱이나 여러 스프라이트를 한 번의 GPU 그리기 명령으로 합치는 기능은 아니다. 문맥 안에서 SDL UI 그리기·뷰포트/배율·렌더 타깃 변경을 섞지 않는다. 배치가 끝난 뒤 기존 SDL 도형·글자·HUD를 그린다.

이전 `ferrial_drive.ui.standalone.run_preview`와 `ferrial_drive.assets.bicubic` import는 호환 어댑터다. 새 실행부는 `runtime`, 새 렌더링 구현은 `rendering`을 사용한다.

## 근거리 적 시트의 GL 상태

교전 뷰의 `EnemyUpscaleScratch`는 기종 간에 `EnemyGlSheet`, 네이티브 확대 입력, SMAA 중간 타깃과 필터를 공유한다. 준비된 페이지를 사용하는 근거리 PBR 배치는 기종에 관계없이 이 경로를 쓴다. 확대가 필요한 시트는 합성부터 Bicubic·SMAA까지 같은 GL 구간에서 그린다.

상태 관리자는 각 시트의 SDL 경계에서 상태를 확보하고 복구한다. 한 구간에서는 프로그램, FBO, 뷰포트, 블렌드와 텍스처 유닛의 바인딩을 기억한다. 크기가 바뀐 타깃의 FBO만 교체한다. 최종 출력 시트는 기종별로 보관해서 SDL의 발 위치 순 합성에 사용한다. [그래픽스 작업 가이드라인](graphics_guidelines.md)

## 독립 실행·검증

### 지면 효과 배치

`PicoGroundEffects`의 기본 `backend="batched"`는 로딩 중 원본 PNG 시트를 공통 RGBA 아틀라스로 조립한다. 원본 파일은 수정하지 않는다. 파티클별 위치·회전·반전·색·수명·가림 수치는 재사용 CPU 버퍼에 채워 한 번 업로드하고 `GroundEffectBatch`가 인스턴싱한다. 현재 공통 아틀라스에서는 파티클 수와 관계없이 비어 있지 않은 레이어마다 한 번 제출한다. 기체 앞·뒤 레이어는 각각 제출하며 입자 순서는 정렬하지 않는다. 연기 알파·마찰 cutout·Trail 음영 계산은 개별 경로와 공통 GLSL 본문을 사용한다.

버퍼와 데이터 텍스처는 용량이 늘어날 때만 확장하며 매 호출 재생성하지 않는다. texture unit 1·unpack/PBO·clip·scale·render target 상태를 복원하고 기존 Pico2D/SDL 그리기와 합성한다. `backend="individual"`은 대조용으로 보존하며 원본 개별 텍스처는 이 경로를 처음 쓸 때만 불러온다. 기본 실행은 공통 아틀라스만 GPU에 보관한다. 개별/배치 대조 실행은 두 텍스처 세트를 함께 보유하므로 메모리 비교 결과로 사용하지 않는다.

`tests/automated/test_ground_effect_batch.py`는 원본 게임 에셋 없는 최소 패턴으로 순서·버퍼 재사용을 검사한다. `FDRIVE_GPU_TESTS=1`로 실행하면 회전·반전·앞뒤 가림·스케일·클리핑·렌더 타깃의 개별/배치 픽셀 비교와 GL 상태·실패 복구를 검사한다. 실기 UHD 630 성능 검증과 구분한다. 자동 대조 명령은 [하드웨어 벤치마크 안내](tool-usage/hardware_profile_benchmark.md)를 따른다.

```text
python -m unittest tests.automated.test_rendering_runtime -q
```

표시 확인은 `tests/asset_loader_test.py`의 공개 도형 샘플 또는 `tests/sword_movement_test.py --demo`로 수행한다.

실제 GPU 검사는 `FDRIVE_GPU_TESTS=1`을 지정하고 `python -m unittest tests.automated.test_asset_bicubic_gpu -q`로 실행한다. Windows에서는 숨긴 실제 OpenGL 창을 사용한다. 자동 검사는 import 부작용·자원 종료 순서·예외 정리·재시작·힌트 복원과 Bicubic 픽셀/클립/SDL 합성을 구분한다. 대상 내장 그래픽 기기의 FHD 165FPS·수백 기·이펙트·HUD 동시 성능은 별도 실측 대상이다.
