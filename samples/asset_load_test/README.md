# 프리렌더 에셋 로딩 샘플

`tests/asset_load_test.py`는 게임과 독립적으로 **기본 도형 모델·짧은 애니메이션 → 저장된 Blender 작업본 재로딩 → 8방향 본체/그림자 렌더 → 시트 패킹 → Pico2D 재생**을 확인한다. 기존 전투 HUD 테스트와 별도다.

## 실행

Python·Pico2D와 Blender가 필요하다. 현재 검증 환경은 `game2d` Python·Blender 5.2.3 LTS·Cycles CPU다. 다른 Blender 버전·GPU 렌더링은 확인하지 않았다. 추가 Pillow·fontTools·Blender MCP 서버 없이 실행한다.

- Runner의 파일 목록에서 `tests/asset_load_test.py`를 선택하거나 열린 GUI에 드롭한다.
- 직접 실행: 프로젝트 루트에서 `python tests/asset_load_test.py`.
- 최초 실행은 별도 백그라운드 Blender를 시작한다. 편집 중인 Blender 창·장면에는 연결하지 않는다.
- Windows에서는 Runner의 재드롭·종료로 테스트가 강제 종료될 때도 소유한 Blender 프로세스가 함께 정리되도록 관리한다. 다른 Blender 창은 대상이 아니다.
- 다음 실행은 설정·렌더/패킹 코드·입력 장면 파일이 같은 마지막 성공 결과를 재사용한다. **R** 또는 `--rebuild`로 별도 작업본부터 다시 렌더한다. `--scene`이 있으면 원본을 다시 읽으며 원본 파일은 덮어쓰지 않는다. 없으면 기본 도형을 재생성한다.
- Blender 자동 탐색은 `--blender`, `BLENDER_EXECUTABLE`, PATH, Windows 설치 정보·기본 설치 위치 순서다. 설치되지 않았다면 경로 오류를 표시한다. 대체 도형을 런타임에 그려 성공으로 보이지 않는다.

```powershell
python tests/asset_load_test.py --blender "설치 폴더/blender.exe" --rebuild
python tests/asset_load_test.py --build-only
python tests/asset_load_test.py --scene "입력 장면.blend" --config "렌더 설정.json" --rebuild
python tests/asset_load_test.py --bundle "output/asset_load_test/<생성된 폴더>/bundle.json"
```

`--bundle`은 이미지·메타데이터만 읽으며 Blender가 필요 없다. `--frames 3`은 자동 실행 확인용 프레임 제한이다. 다른 작업 폴더에서 실행할 때도 스크립트·기본 샘플 경로는 스크립트 위치를 기준으로 찾는다.

`--scene` 입력은 `ActorRoot` 아래에 본체 메시를 두고 `ShadowCatcher`와 카메라가 설정된 장면이다. 프레임은 지정한 장면의 애니메이션에서 추출한다. 설정의 `animation_name`으로 `idle` 등의 동작 이름을 지정하며 생략 시 `walk`를 사용한다. 임의 장면의 자동 리깅·카메라 자동 배치는 수행하지 않는다.

후속 그림자 개선: 최초 샘플의 8 samples·큰 광원에서 보인 노이즈를 줄이기 위해 기본값을 본체 64 / 그림자 128 samples·denoise·광원 크기 0.6으로 조정했다. 실제 기체 비교본은 같은 경로에서 본체 128 / 그림자 256을 사용했다.

## 조작과 기대 결과

| 조작 | 기대 결과 |
| --- | --- |
| 방향 카드 클릭 / ← → | 8방향 중 선택, 같은 프레임 위상 유지 |
| Space / 재생·정지 버튼 | 모든 방향의 재생 일시정지·재개 |
| `.` / 다음 프레임 | 정지 상태로 한 프레임 이동·마지막에서 반복 |
| B / 본체 | 본체 표시 전환, 그림자는 독립 유지 |
| S / 그림자 | 그림자 표시 전환, 본체는 독립 유지 |
| R / 재렌더 | 기존 성공 결과를 유지하며 새 Blender 작업본·출력 생성 |
| Esc / 창 X | 해당 테스트 종료, 진행 중인 소유 Blender 프로세스도 정리 |

주황색 면은 모델의 앞쪽이다. 위쪽에서 8방향을 원래 배율로, 아래쪽에서 선택 방향과 분리 그림자를 3배로 확인한다. 바닥 십자는 발 기준점이다. 방향·프레임이 바뀌어도 접지 위치가 흔들리지 않는지 확인한다. 확대 시 보이는 저해상도·샘플 노이즈는 확인용 기본 에셋의 품질이며 최종 미술 기준이 아니다.

## 입력과 결과

- 입력 `render_config.json`: 160×160px, 8방향, 프레임 1/3/5/7, 8 FPS, 정사영 카메라·광원·Cycles 설정. 수치는 이 샘플의 비교값이며 게임 규격 확정이 아니다.
- 기본 도형과 애니메이션 생성 코드: `Tools/blender_pipeline/render_asset_sample.py`. 실제 게임 에셋·AI 원화·세이브를 요구하지 않는다.
- 작업본: `Tools/blender_pipeline/workspace/asset_load_test/<실행 ID>/sample.blend`.
- 출력: `output/asset_load_test/<실행 ID>/`. 실행마다 새 폴더를 만들고 원본 설정·기존 작업본을 덮어쓰지 않는다.
- `frames/`: 본체 32장·그림자 32장. 각 방향은 45도 간격의 월드 XY 회전이며 고정 카메라를 공유한다.
- `body.png`, `shadow.png`: 각각 640×1280px 시트. 행=방향, 열=프레임이다.
- `body.json`, `shadow.json`: 기존 SSheetCutil v1과 같은 이미지·동작·프레임 영역·피봇·FPS 규격이다. 좌표 원점은 **왼쪽 아래**다.
- `bundle.json`: 게임용 진입점. 본체/그림자 프로젝트·방향/동작 대응·설정 해시를 담는다. 프로젝트 경로는 번들 기준 상대 경로다.
- `rendered_frames.json`: 렌더 입력·Blender 버전·프레임별 대응. `pixel_report.json`: 알파·잘림 검사. `blender.log`: 렌더 실패 확인 자료.
- `latest.json`: 모든 렌더·패킹·검사를 통과한 결과만 가리킨다. 실패·취소는 이전 성공 경로를 바꾸지 않는다.

프레임 묶음을 다시 패킹할 때는 기존 도구의 실제 진입점을 사용한다.

```powershell
python Tools/SSheetCutil.py --pack-prerender "output/asset_load_test/<실행 ID>/rendered_frames.json"
```

생성된 `body.json`·`shadow.json`은 기존 시트 편집기에서도 불러올 수 있다. 편집기 전체의 Sonic 전용 구조 분리·8방향 전용 편집 UI는 이번 범위가 아니다.

## 확인 범위

실제 Blender 렌더·저장 작업본 재로딩·64프레임 패킹·Pico2D 로딩과 SDL dummy 렌더링, 자동 검사 7개를 확인했다. Blender가 없는 재생 경로·다른 작업 디렉터리·기존 시트 편집기의 JSON 읽기도 확인했다. 실제 창 직접 조작·최종 미술 품질·GPU 성능은 확인 전이다.

이번 첫 구현은 **움직이는 엔티티의 최소 경로**다. 실제 기체 모델/리그 연결, 여러 동작, 고정·파괴 오브젝트, 맵 구역 렌더·이음새·가림·통행 데이터는 후속 검증 범위다. [테스트 명세](../../docs/unit-tests/asset_load_test.md)를 따른다.
