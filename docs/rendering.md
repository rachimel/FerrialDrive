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

생성 순서는 **캔버스 → 에셋 관리자·UI → 장면**이다. 종료는 **장면·에셋 관리자·폰트/텍스처 → 캔버스** 순서다. 렌더러가 닫힌 뒤 GPU 자원을 그리거나 해제하지 않는다. `run_application()`의 `exit()`는 이 순서를 보장하는 연결 지점이다. 캔버스가 게임의 에셋 관리자를 대신 소유하지는 않는다.

OpenGL 요청을 위해 바꾼 SDL 드라이버 힌트는 초기화 후 원래 값으로 돌린다. 생성에 실패한 경우 소프트웨어 렌더러를 시도하며 SDL dummy는 OpenGL을 요청하지 않는다. 적용 여부는 요청값 대신 실제 드라이버와 `resource.filtering`으로 확인한다. Pico2D 라이브러리 원본은 수정하지 않는다.

## 스프라이트와 SDL UI 합성

`PicoAssetBackend`·`PicoSprite`는 같은 `rendering.bicubic` 구현을 사용한다. 샤프닝은 프리렌더 패킹 단계이고 Bicubic은 화면 표시 단계다. 프레임별 경계·알파 처리를 유지한다.

여러 에셋은 `with resource.render_batch():` 안에서 연속으로 그릴 수 있다. 이 문맥은 GL 상태 변경과 복원을 묶는다. GPU 인스턴싱이나 여러 스프라이트를 한 번의 GPU 그리기 명령으로 합치는 기능은 아니다. 문맥 안에서 SDL UI 그리기·뷰포트/배율·렌더 타깃 변경을 섞지 않는다. 배치가 끝난 뒤 기존 SDL 도형·글자·HUD를 그린다.

이전 `ferrial_drive.ui.standalone.run_preview`와 `ferrial_drive.assets.bicubic` import는 호환 어댑터다. 새 실행부는 `runtime`, 새 렌더링 구현은 `rendering`을 사용한다.

## 독립 실행·검증

```text
python tests/rendering_test.py
python tests/rendering_test.py --frames 2
python -m unittest tests.automated.test_rendering_runtime -q
```

도형 샘플은 공개 `samples/asset_loader/`만 사용하며 Blender·실제 게임 모델·카탈로그 등록이 필요 없다. 15개 스프라이트와 SDL 문자/선을 합성한다. **1/2/3**으로 Nearest/Linear/Bicubic을 바꾸고 **Esc**로 닫는다. 독립 Runner에서도 선택할 수 있다.

실제 GPU 검사는 `FDRIVE_GPU_TESTS=1`을 지정하고 `python -m unittest tests.automated.test_asset_bicubic_gpu -q`로 실행한다. Windows에서는 숨긴 실제 OpenGL 창을 사용한다. 자동 검사는 import 부작용·자원 종료 순서·예외 정리·재시작·힌트 복원과 Bicubic 픽셀/클립/SDL 합성을 구분한다. 대상 Iris 기기의 수백 기·이펙트·HUD 동시 성능과 60FPS는 별도 실측 대상이다.
