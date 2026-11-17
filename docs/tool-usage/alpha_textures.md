# 그림자 알파 전용 데이터

그림자는 게임 품질에 따라 **높음 50%·보통 25%·낮음 12.5%**의 가로·세로 해상도를 사용한다. R8 알파를 BOX 면적 필터로 미리 축소하며 원본 PNG·프레임·피봇은 보존한다. 기체의 75%·50%·25%와 별도 배율이다.

| 품질 | 그림자 배율 | 준비 파일 | 현재 18시트 R8 적재량 |
| --- | ---: | --- | ---: |
| 높음 | 50% | `.png.alpha8.x2` | 약 67.04MiB |
| 보통 | 25% | `.png.alpha8.x4` | 약 16.77MiB |
| 낮음 | 12.5% | `.png.alpha8.x8` | 약 4.20MiB |

한 번에 선택한 등급만 적재한다. 위 수치는 그림자 텍셀 페이로드이며 게임 전체 메모리나 드라이버 사용량이 아니다.

## 준비

프로젝트 루트에서 Pico2D 실행에 쓰는 Python으로 실행한다. 준비에만 Pillow가 필요하며 기존 `automate/runtime/texture_compare/python`을 재사용한다. 런타임 로더는 Pillow를 import하지 않는다.

```text
python automate/run.py alpha-textures --catalog data/runtime/catalog/prerender/player_sword_boost_prepare_8dir_shadow/catalog.json --catalog data/runtime/catalog/prerender/player_sword_combo_movement_8dir_shadow/catalog.json --quality-profiles
python automate/run.py alpha-textures --image data/example/shadow.png --quality-profiles
python automate/run.py alpha-textures --image data/example/shadow.png --scale 1
```

`--catalog`·`--image`는 여러 번 지정할 수 있다. 카탈로그의 `shadow` 시트만 선택하고 같은 이미지 경로는 한 번 처리한다. 원본 PNG·시트 JSON·프레임 배치·피봇은 수정하지 않는다. 생성물은 원본 옆에 임시 파일로 완성한 뒤 원자적으로 교체한다. PNG를 다시 출력했으면 준비 명령도 다시 실행한다.

`--quality-profiles`는 3등급을 함께 준비한다. 생략하면 기존 `.png.alpha8` 하나를 만드는 호환 경로이며 `--scale`은 기본 0.5, 선택값 1/0.5/0.25/0.125다. 작은 홀수 크기는 올림하고 최소 1px로 유지한다. GPU 텍스처 크기와 원본 논리 좌표를 구분하며 실제 메모리 추정에는 축소 크기를 쓴다.

`GameSettings.shadow_scale`에서 등급을 고르고 `PicoAssetBackend(alpha_scale=...)`가 해당 파일을 적재한다. 설정 메뉴 저장 성공 때 기체·그림자를 함께 교체한다. 준비·저장 실패 시 후보를 해제하고 이전 등급을 유지하며, 진행 상태와 원래 프레임 좌표는 유지한다.

## 적재와 오류

- 품질을 지정한 경로는 해당 배율 파일을 요구한다. 기존 `.png.alpha8`이 정확히 같은 크기이면 호환해서 사용할 수 있다. 준비 데이터가 없거나 오래되면 위 `--quality-profiles` 명령으로 다시 준비한다. 다른 배율을 조용히 선택하지 않는다.
- 배율을 지정하지 않은 기존 API는 `.png.alpha8`을 사용하고, 파일 부재·원본 변경 시 기존 PNG 읽기 경로를 유지한다.

- 파일 구성: `FDALPHA1` 식별자, little-endian 텍스처 폭·높이, 원본 SHA-256, 준비된 알파 SHA-256을 담은 80바이트 헤더와 위쪽 원점의 8비트 알파 픽셀이다. 압축하지 않는다. 모든 배율이 같은 규격을 사용하며 이름이 지정한 배율과 실제 크기도 검사한다.
- 원본과 알파 페이로드의 해시·길이를 검사한다. 검증 비용도 로딩 시간에 포함된다.
- 배율 미지정 호환 API에서만 전용 데이터 부재·원본 변경 시 기존 PNG 경로를 사용한다. 실행 중 제작 파일을 자동 생성·갱신하지 않는다.
- 전용 데이터가 잘렸거나 손상됐으면 명시적인 오류로 처리한다. 준비 명령으로 다시 생성한다.
- GPU 저장은 기존 R8·검정 RGB/알파 swizzle을 유지한다. 전송 행 정렬·stride 상태를 저장·복원한다.

원본 PNG를 보존하므로 저장 공간은 추가로 필요하다. 생성물은 원본과 함께 로컬 `data/`에서 관리하고 공개 저장소에 포함하지 않는다. 무압축 읽기가 느린 저장 장치에서는 별도 성능 확인이 필요하다.

## 부드러운 표시

현재 훈련장의 `presentation.shadow_softness_pixels=5`, `shadow_contact_radius_pixels=56`을 사용한다. 별도의 그림자 텍스처를 더 만들지 않고 GPU에서 5×5 가중 필터를 적용한다. 원점에 가까운 접지 영역의 반경은 작게, 떨어진 영역은 크게 적용하는 2D 근사이며 광원 크기·실제 높이 기반의 물리적 반그림자 계산은 아니다.

프레임 밖은 투명하게 취급해 이웃 프레임을 읽지 않고, 출력 영역을 반경만큼 확장해 번짐이 잘리지 않게 한다. 현재·다음 프레임의 서로 다른 크기·피봇은 유지한다. 보간을 끄면 프레임 위상을 정수로 고정하되 부드러운 그림자 표시는 유지한다.

## 검증

[게임 없는 기본 도형 시연](../../samples/alpha_textures/README.md)을 사용한다. 파일 계약 검사는 `tests/automated/test_alpha_data.py`, 실제 OpenGL 표시 비교는 `FDRIVE_GPU_TESTS=1`의 `tests/automated/test_alpha_texture_gpu.py`를 사용한다. 자동 픽셀 비교·실제 게임 로딩 계측과 사용자의 직접 조작 확인은 구분한다.

실제 3등급 교체·동일 자세 캡처는 `output/performance/shadow_quality_20261115/`에 기록했다. 등급별 교체와 실패 복구는 자동 GPU 검사로, 저해상도 외관의 사용자 승인은 별도로 구분한다.
