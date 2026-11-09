# FDrive Pose Tool

Blender 안에서 기존 모델의 포즈를 직접 편집한다. 프로젝트 루트의 **Pose Tool.lnk**를 실행한다. Asset Tool의 **포즈 편집** 버튼도 같은 Blender 편집기를 연다. 이미지 미리보기 작업자를 기다리지 않고 Blender 뷰포트에서 조작한다.

## 시작

기본 입력은 `data/models/basic_weapons/base_pose.blend`다. 지정한 파일이 없으면 오류를 표시하며 다른 동작 파일이나 샘플로 바꾸지 않는다. 원본을 보존하고 `Tools/pose_tool/workspace/<실행시각>/pose_work.blend`를 만든다. 루트 바로가기는 로컬 전용이며 Git에 포함하지 않는다.

```powershell
Tools/pose_tool/run_pose_tool.cmd
python Tools/pose_tool/run.py 모델.blend
python Tools/pose_tool/run.py --sample
python Tools/pose_tool/run.py 작업본.blend --work 작업본.blend
```

Blender 5.2.3 LTS에서 확인했다. 실행기는 전용 패널을 등록하므로 별도 플러그인 설치나 환경 설정 저장은 필요 없다. `.blend` 파일만 직접 열면 컨트롤은 유지되지만 전용 패널은 등록되지 않는다. **모델 / 작업본 열기**는 현재 작업을 보존하고 선택한 파일을 새 Blender 창에서 연다.

## 편집

뷰포트에서 `N`을 눌러 오른쪽 **Pose Tool** 탭을 선택한다.

- **동작**: 동작 선택 → 선택 동작 열기. 현재 프레임의 키를 먼저 기록하고 동작을 전환한다. 타임라인과 재생은 Blender 기본 기능을 사용한다.
- **파츠**: 몸체·IK / 손가락 / 총·칼·칼집 / 기타에서 선택한다. 손바닥 중앙에 손 목표가 있다. 손을 회전하면 손목 볼이 같이 회전한다.
- **월드 축 이동/회전**: 작은 축별 `−`/`+` 아이콘을 사용한다. 이동량과 각도를 입력한다. 마우스 이동 화살표는 굵게 표시한다. `G`, `R`, `X/Y/Z`와 Blender 기본 변환 도구도 사용할 수 있다.
- **팔꿈치·무릎**: 실제 관절에 표시된 원을 끌어 굽힘 방향을 조절한다. 손/발 목표는 유지한다. 내부의 먼 pole 제어점은 숨긴다. 완전히 편 관절은 먼저 골반·손/발을 움직여 굽힘을 만든다.
- **손가락**: 손이나 손가락을 선택하면 **주먹 / 손 펴기**가 나타난다. 반복 클릭해도 더 꺾이지 않는 절대 자세다. 손가락·관절별 굽힘/펴기와 직접 회전도 지원한다. 검지·중지·약지·소지는 손가락 뿌리의 공통 가로축과 손바닥 면을 기준으로 같이 말린다. 손가락마다 다른 rest roll과 좌우 방향을 보정한다. 기본 매핑의 손바닥 안쪽은 기존 무기 파지와 같은 Hand 로컬 -Z다. 주먹은 기본 프리셋이며 무기 접촉이나 관절 간섭을 자동 해결하지 않는다.
- **이전 프레임 파츠 복제**: 선택한 파츠만 복사한다. 컨트롤/무기는 월드 배치, 손가락은 로컬 자세를 사용한다. 손 전체는 손가락도 포함한다. 직전 프레임이 다른 동작에 있어도 복사한다.
- **독립 무기**: 총은 한 조립 파츠이며 칼·칼집은 각각 독립 파츠다. 프레임별 기존 월드 배치를 보존한다. **칼 → 칼집 자동 정렬**은 `Sword_StowAnchor`와 칼집 사이의 제작 좌표 관계로 현재 칼을 한 번 정렬한다. 정렬 후에도 독립 파츠다.
- **Ctrl+Z / Ctrl+Shift+Z**: Blender 기본 되돌리기/다시 실행이다. 화면 버튼도 제공한다. 원격 미리보기용 48단계 이력을 사용하지 않는다.

자동 키를 켜서 시작한다. 기본 이동/회전과 패널 변환은 현재 프레임 키에 반영한다. 프레임을 바꾸기 전 **현재 프레임 포즈 키 저장**, 종료 전 **작업본 저장**을 사용한다. 손가락은 회전으로 조절하며 연결 본의 평행이동은 제한한다. 손목·무릎 제어와 rest 본/웨이트/메시 수정은 구분한다.

## 저장과 출력

**작업본 저장**은 현재 포즈 키를 포함한다. **다른 이름**으로 별도 작업본을 저장할 수 있다. 원본 경로 덮어쓰기는 거부한다.

**현재 동작 출력**에서 새 폴더를 선택한다. 별도 Blender 프로세스에서 굽기 때문에 편집 장면과 기본 Undo를 다시 불러오지 않는다.

- `poses.json`, `base.blend`: 기존 애니메이션 파이프라인의 표본과 기반 사본.
- `baked/animations.blend`, `baked/clips.json`: 원래 리그로 재생하는 출력 동작.
- `baked/export_configs/*.json`: 신규 기본 240×240 프리렌더 설정.

출력 뒤 **출력 → Asset Tool 3D 렌더**를 누르면 해당 설정을 불러온 Asset Tool 창을 연다. 렌더 시작은 별도다. 독립 무기는 `extra_root_objects`로 전달해 본체와 같은 출력 방향으로 회전한다. 이후 포즈를 수정했다면 현재 동작을 다시 출력한다.

## 구조

| 파일 | 책임 |
| --- | --- |
| `run.py`, `run_pose_tool.cmd` | 입력 파일 검증과 Blender 실행 |
| `bootstrap.py`, `addon.py` | 별도 작업본·패널·뷰포트 준비 |
| `native.py`, `gizmos.py` | 네이티브 파츠 UI·관절 드래그·월드 축 조작 |
| `profile.py`, `scene.py` | 본 매핑·IK·동작별 Action·저장·표본 출력 |
| `part_editing.py` | 손목 연결·손가락·독립 무기·복제·칼집 정렬 |
| `exporting.py` | 별도 프로세스 굽기와 렌더 설정 전달 |
| `worker.py`, `session.py`, `history.py` | 이전 Asset Tool 내장 편집의 검사·호환 경로 |

매핑은 `default_profile()` JSON 구조를 따른다. upper/lower는 직접 연결하며 end 원점은 lower 끝과 맞아야 한다. 새 모델의 본 이름과 손가락 구조가 다르면 매핑과 굽힘 축을 확인한다. 공개 가능한 기본 도형 샘플은 `samples/pose_tool/`에 있다.

## 확인 범위

`tests/blender/check_pose_native.py`는 기본 도형 또는 실제 모델에서 월드 이동·무기 독립성·손목 회전·주먹의 반복 클릭·손 펴기·무릎 굽힘·이전 프레임 복제·칼집 정렬·저장·출력을 검사한다. `--screen`은 실제 창과 Blender 기본 Undo의 장면 복구를 검사한다. Python 타이머 호출의 Undo 기록과 실제 키보드 입력은 구분한다.

```powershell
& $blender_exe --background --factory-startup --python-exit-code 1 --python tests/blender/check_pose_native.py -- --output output/pose_tool/새검사폴더 --export
& $blender_exe --factory-startup --python-exit-code 1 --python tests/blender/check_pose_native.py -- --source 모델.blend --output output/pose_tool/새화면폴더 --screen
& $blender_exe --factory-startup --enable-event-simulate --window-geometry 50 50 1500 1000 --python-exit-code 1 --python tests/blender/check_pose_native.py -- --source 모델.blend --output output/pose_tool/새키보드검사폴더 --screen --ui-input
```

공통 성능 기록은 `output/performance/`에 남긴다. 키 저장·장면 평가 시간과 화면의 입력 지연/GPU 시간은 구분한다. 전체 연속 간섭·무기 핏·모든 관절 가동 한계·사용자 사용감 승인은 별도다. 원본·작업본·이미지는 공개 코드 커밋에 포함하지 않는다. Blender [Gizmo API](https://docs.blender.org/api/5.2/bpy.types.Gizmo.html)와 프로젝트의 기존 애니메이션 파이프라인을 사용한다.

손가락 회귀 검사: `tests/blender/check_pose_fingers.py -- --source 모델.blend --output 새검사폴더 --capture`. 양손 네 손가락의 실제 관절 방향·손바닥 쪽 변위·주먹 반복 적용·증분 굽힘·저장/재로딩을 검사하고 손바닥/측면 확대 이미지를 남긴다. 플러그인 수정 후에는 실행기로 작업본을 새 창에서 다시 열고 **주먹**을 다시 적용한다.
