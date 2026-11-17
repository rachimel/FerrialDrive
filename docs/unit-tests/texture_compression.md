# 텍스처 압축·공유 아틀라스 Unit Test

실행부터 첫 화면 표시 전까지의 로딩 지연과 GPU/메모리 적재량을 비교한다. 비교 프로그램은 독립 실행하며, 검증한 Oodle 후보는 검 이동 프로그램의 텍스처 품질 설정에도 연결한다. 비교의 계측 범위와 게임 전체 비용을 구분한다.

## 입력과 실행

- 진입점: `tests/texture_compression_test.py`. 모듈 docstring·Runner `standalone` 규약과 자체 창/입력/시간/자원 정리를 제공한다.
- 재사용 제작: `ferrial_drive/rendering/motion_atlas.py`, `texture_codecs.py`. 재사용 GPU 경로: `pico_motion_atlas.py`. 계측: `ferrial_drive/diagnostics/texture_metrics.py`와 공통 `TimingRecorder`.
- 공통 자동화: `python automate/run.py texture-compare`. 기본은 두 현행 카탈로그의 160클립 전체이며 `--all`로도 명시할 수 있다. `--clip`을 반복 지정하면 부분 집합만 준비한다.
- 실행 파일·로컬 설정·패키지는 `automate/`의 기존 경로 규칙을 따른다. 보존 원본은 기존 `data/runtime/frame_interpolation/`, 새 기체 후보는 `data/runtime/textures/`, 보고서·캡처는 해당 후보의 `benchmark/` 또는 `output/`이다. AI 에셋과 로컬 경로가 포함된 결과는 Git에서 제외한다.
- 공개 시연은 [기본 도형 샘플](../../samples/texture_comparison/README.md)로 수행한다. KTX/Oodle 런타임을 `output/`에 의존시키지 않는다.

```text
python automate/run.py texture-compare --all --output data/runtime/textures/sword_all_half_20261113
python tests/texture_compression_test.py --bundle data/runtime/textures/sword_all_half_20261113/comparison.json --benchmark --frames 120
python tests/texture_compression_test.py --bundle data/runtime/textures/sword_all_half_20261113/comparison.json
```

`--benchmark`는 일곱 경우를 별도 프로세스로 순차 실행한다. 창을 서로 겹쳐 성능을 재거나 이전 후보의 GPU 캐시를 남기지 않는다. OS 디스크 캐시는 비우지 않으므로 cold start 결과가 아니다. `--frames`·`--clip`·`--phase`·`--capture`·`--report`로 지정 실행이 가능하다. `--benchmark --case oodle_full` 또는 `--benchmark --case oodle_75`은 같은 클립의 기존 기준 측정에 새 후보만 추가한다.

새 측정은 `benchmark/runs/한국시각_고유ID/`에 저장하고 `benchmark/summary.json`은 최신 통합 보기로 유지한다. 재준비로 후보를 바꾼 경우 다시 측정한다. 초기 계측 도입 전의 반복 결과와 최신 결과를 구분하며 원본 보고서 경로는 통합 결과의 `case_artifacts`로 연결한다.

## 비교 후보와 아틀라스

| 후보 | 색상 | 벡터 | 배치 |
| --- | --- | --- | --- |
| 기존 | 원해상도 RGBA8 | 원해상도 signed16 RGBA | 기존 클립별 A/B/전방/후방 4장 |
| 공유 원해상도 | premultiplied RGBA8 | 무손실 RGBA8 | 고유 프레임·벡터의 공통 페이지 |
| 공유 반해상도 | 가로/세로 각각 절반 RGBA8 | 새 픽셀 단위로 변환한 절반 벡터 | 공통 페이지 |
| KTX2 | 반해상도 UASTC RDO→GPU BC7 | 위 반해상도 벡터와 동일 | 색상 KTX2+Zstd, 공유 벡터 zlib |
| Oodle Texture | 반해상도 BC7 RGBA, RDO lambda 30 | 위 반해상도 벡터와 동일 | 색상 BC7+zlib, 공유 벡터 zlib |
| 원해상도 Oodle | 원해상도 BC7 RGBA, RDO lambda 30 | 원해상도 벡터 무손실 | 색상 BC7+zlib, 공유 벡터 zlib |
| 75% Oodle | 가로/세로 각각 75% BC7 RGBA, RDO lambda 30 | 같은 비율로 변환한 무손실 벡터 | 색상 BC7+zlib, 공유 벡터 zlib |

- KTX2는 컨테이너/인코딩 경로, Oodle Texture는 BCn 인코더다. 두 후보를 같은 GPU BC7 목표로 맞춰 비교한다. RDO 파라미터의 수치가 서로 같은 품질을 뜻하지 않는다. 외부 압축까지 포함한 전체 파이프라인 비교이며 인코더만의 순수 우열 비교가 아니다.
- 페이지 최대 크기는 첫 비교값 2048×2048, 여백은 4픽셀이다. 타일 시작/크기를 4픽셀 경계에 맞추고 테두리 픽셀을 연장한다. 전체 데이터를 무조건 한 텍스처에 넣지 않고 GPU 최대 크기를 확인해 페이지로 나눈다.
- 색상과 수치 벡터는 별도 페이지다. 고유 색상/벡터는 크기+내용 해시로 공유하고, 클립은 인덱스만 참조한다. 캐시는 렌더러 수명 안에서 경로+내용 해시를 키로 하며 명시적으로 acquire/release한다. 후보 간 같은 벡터 파일도 공유할 수 있다.
- 바이트 채널을 이미지처럼 줄이지 않는다. 벡터를 signed16 변위로 해석한 뒤 면적 필터를 적용하고 실제 새 가로/세로 비율로 변위를 바꿔 재인코딩한다. 색상은 알파 사전 곱셈 후 채널별 면적 필터를 적용한다.
- BC7은 블록당 크기가 고정이다. 큰 아틀라스의 효과는 중복 제거·여백/바인딩 감소·캐시 공유이며, 아틀라스를 크게 했다는 이유만으로 BC7의 픽셀당 압축률이 증가하지 않는다.
- 제작 시 압축하며 실행 시 GPU 인코딩을 수행하지 않는다. KTX2는 libktx로 BC7으로 변환하고 Oodle은 BC7 블록을 복원해 올린다. 벡터는 손실 압축하지 않는다.
- 색상 아틀라스의 계약은 Premultiplied Alpha이며 제작 메타데이터에 `color_alpha_mode`를 명시한다. 아틀라스 로더는 다시 알파를 곱하지 않는다. 최종 셰이더 출력에서 RGB를 알파로 나누어 기존 straight-alpha 합성 경로에 연결한다. 일반 PNG 로더에 이 사전 변환 데이터를 그대로 넣어 이중 변환하지 않는다.

## 측정 항목과 해석

| 항목 | 실제 기록과 범위 |
| --- | --- |
| Texture Format | OpenGL `GL_TEXTURE_INTERNAL_FORMAT`·`GL_TEXTURE_COMPRESSED`. BC7 실제 적재를 확인한다. |
| GPU Storage | BC7은 `GL_TEXTURE_COMPRESSED_IMAGE_SIZE`. RGBA8은 조회한 크기×4의 논리 페이로드. 드라이버 할당량과 구분한다. |
| Disk Size | 해당 입력이 참조하는 파일을 중복 없이 집계한다. 후보별 별도 설치 크기이며 후보들을 함께 둘 때의 공유 절감과 다르다. |
| Read / Decode | 공통 `TimingRecorder`의 파일 읽기·해시 확인·압축 해제/BC7 변환을 구분한다. 기존 PNG 읽기/디코딩은 통합 측정하며 premultiply는 별도 기록한다. 중첩 구간을 합산하지 않는다. |
| Upload Time | GPU 완료 대기(`glFinish`)를 포함한 CPU 경과 시간. 순수 GPU 실행 시간으로 표현하지 않는다. |
| RAM | Windows Working Set·Private Bytes·Peak Working Set, 로딩 전/후·종료 전 값을 기록한다. 자원 준비 뒤 GC를 수행하되 OS working set을 강제로 비우지 않는다. |
| VRAM Usage | WDDM `GPU Process Memory`의 프로세스 `Dedicated Usage`·`Shared Usage`를 따로 기록한다. 로딩 전/직후/종료 전과 주기적 프레임 표본의 관측 최대값을 남기며 연속 측정 피크로 주장하지 않는다. 전용/공유를 RAM에 더하면 이중 집계할 수 있다. 카운터 미지원/표본 부재는 미측정이며 GPU Storage로 대체하지 않는다. |
| Frame Time | CPU update 이후 draw/present 완료까지와 GPU `GL_TIME_ELAPSED`의 비교 패널 실행 시간을 구분한다. 최초 8프레임과 품질 캡처 비용은 평균에서 제외한다. |
| First Present | Python 테스트 진입부터 첫 present 완료까지. 인터프리터/프로세스 생성 자체는 제외한다. |
| Image Quality | 같은 클립의 위상 0.15/0.5/0.85, 블러 켬/끔을 고정한 512px 화면 RGB의 PSNR과 11×11 Gaussian(sigma 1.5) SSIM. 배경에 의해 과대평가되지 않도록 움직이는 영역 합집합 지표도 기록한다. |

범위는 **보간 계층만**이다. 일반 본체/그림자 시트·HUD·바닥의 공통 적재와 본편 전투는 제외한다. 160클립의 적재량을 측정하더라도 기본 품질 비교는 지정한 한 클립의 6개 시점이며 전체 방향·모션 품질 검증을 뜻하지 않는다. `--clip`으로 검증 대상을 바꾸고 사용자 실제 조작·시각 승인은 별도 기록한다.

측정 결과가 있으면 기본 진입은 측정표를 먼저 열며 이때 전체 비교 에셋을 다시 적재하지 않는다. `Tab`으로 실제 화면 비교로 전환할 때 로드한다. 화면 비교는 `1~6`·좌우 화살표·`Space`·`B`·`Z`·`C`를 사용한다. `C`의 복제 인스턴스는 같은 GPU 자원을 재사용하며 기체 수만큼 디스크/텍스처를 다시 로드하지 않는다.

## 게임 품질 연결

검 이동 프로그램의 타이틀·일시정지 설정에서 높음(원본의 75% Oodle)·보통(50% Oodle)·낮음(25% Oodle)을 선택한다. 첫 실행 기본은 낮음이며 저장하면 현재 실행에 적용한다. 새 자원을 준비한 뒤 교체하며 위치·콤보·게이지·일시정지 상태를 유지한다. 준비나 저장에 실패하면 기존 설정과 자원을 유지한다. 현재 160클립의 보간 GPU Storage는 각각 약 508.69/236.06/65.96MiB다.

전체 프로그램은 중복 PNG 본체를 제외하고 50% 해상도 그림자를 R8 알파로 적재한다. 그림자 약 67.04MiB와 HUD/바닥은 위 보간 수치 밖이다. 품질 설정은 수치 벡터도 함께 줄이며 그림자 해상도는 별도 설정을 따른다. 실제 WDDM 메모리·게임 전체 로딩 시간으로 위 수치를 대체하지 않는다.

기존 비교 묶음에 특정 해상도의 Oodle 후보를 추가하려면 `python automate/run.py texture-compare --help`의 준비 인자와 `--add-oodle-scale 0.25`를 사용한다. 배율은 0.25·0.5·0.75·1.0을 지원하며 원본 입력은 보존한다.

## 설계 검토와 보류

- 더 큰 4096/8192 페이지의 효과·페이지별 메모리 상주·패킹 개선은 첫 측정 이후 검토한다. 단일 클립은 현재 셰이더에서 색상 2페이지·벡터 2페이지까지 참조하며 초과하면 조용히 오표시하지 않고 재준비를 요구한다.
- 공유 아틀라스 셰이더의 인덱스·분기·uniform 비용 때문에 GPU 프레임이 빨라질지는 별도 문제다. 메모리 감소와 GPU 시간 회귀를 함께 보고한다.
- 화면 전체 프레임 보간은 별도 후속 실험이다. 개별 데이터 재사용, 화면 움직임 추정, UI 제외, 가림, 입력/표시 지연과 실제 채움 면적을 비교하기 전 기존 방식을 대체하지 않는다.
- 검 달리기/대시 방향 통일과 옆걸음·뒷걸음 제작은 이번 압축 실험에서 구현하지 않는다.

실제 결과와 문제 해결 과정은 [방향·로딩 조사](../ai-dev-log/2026-11-13-movement-direction-loading.md)와 [텍스처 비교 구현 기록](../ai-dev-log/2026-11-13-texture-atlas-comparison.md)에 남긴다.

출처: [KTX2 공식 도구](https://github.khronos.org/KTX-Software/ktxtools/ktx_create.html), [KTX2 BC7 변환](https://github.khronos.org/KTX-Software/ktxtools/ktx_transcode.html), [Oodle Texture](https://www.radgametools.com/oodletexture.htm), [Microsoft PDH](https://learn.microsoft.com/en-us/windows/win32/perfctrs/using-the-pdh-functions-to-consume-counter-data).
