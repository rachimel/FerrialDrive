# 이동·UI 훈련장

효과음은 [사운드 준비·출처 안내](../sound_effects/README.md)를 따른다. `python automate/run.py sound-effects`로 공통 음원을 준비하며 `--demo` 음원은 같은 명령에 `--demo`를 붙여 따로 준비한다. `--mute`로 효과음을 끈다. 사용자 선택 음원은 별도 교체 bank가 있을 때 적용한다.

실제 에셋 실행 전에는 `python automate/run.py trail-texture`로 Trail 결 파일을 준비한다. 공개 도형 `--demo`는 파일이 없으면 로딩 중에 메모리에서 준비한다. `python automate/run.py trail-texture --demo`로 준비 파일을 미리 만들 수도 있다. [준비 파일과 로딩](../../docs/tool-usage/trail_texture_preparation.md)

Pico2D가 설치된 환경에서 프로젝트 루트 기준으로 실행한다.

총은 900 RPM·탄속 5,500 투영 월드 픽셀/초이며, `movement_config.json`의 `weapons.gun`에서 조정한다. `weapons.swap_speed=2`로 수납·인출을 가속한다. 우클릭 유지/해제는 대시·부스트 중에도 조준 진입/해제 모션을 재생한다. 총탄의 밝은 탄두·꼬리 텍스처는 `weapons.effects`로 크기와 색을 조정하며 추가 이미지 파일 없이 로딩에서 준비한다.

조준 진입·해제는 `weapons.aim_speed=2`로 가속하며 일반 상태에서 약 0.333초다. Overdrive 배율과 곱하며 표적 획득 대기 시간과 구분한다.

록온 첫 획득은 즉시, 이미 획득한 적에서 더 가까운 마우스 후보로 교체할 때만 1초를 기다린다. 사망·비활성 표적 또는 플레이어 기체 전체의 화면 이탈 시 해제한다. 총은 록온 표적을 향해 발사하고 실제로 맞은 적으로 록온을 바꾸지 않는다. 미획득 중에는 마우스로 자유 사격한다. 록온 중 카메라는 플레이어·표적의 중간점을 추적한다. 총탄 Trail 길이는 108픽셀이며 실제 누적 비행 거리까지 늘어난다.

`targeting.acquisition=visible`은 현재 화면에 본체 표시 영역이 일부라도 보이는 적만 획득·교체 후보로 사용한다. 획득 거리 제한과 조준별 거리 확장은 사용하지 않는다. 기존 표적은 거리 제한 없이 유지하며, 사망·비활성 또는 현재 록온 화면에서 플레이어 기체의 표시 사각형 전체가 벗어나면 해제한다. 일부가 보이면 유지하며 줌은 반영하고 피격 흔들림은 제외한다. 화면 이탈 표적은 플레이어 중심 화면에서도 해당 적이 보일 때 다시 허용한다. 우클릭 해제만으로 풀리지 않는다. 획득·유지와 총탄 사거리는 별도 규칙이다. 새 획득·교체 후보는 플레이어 중심 화면에서도 보여야 하며, 복귀 중인 록온 카메라에만 보이는 먼 적은 제외한다.

Q는 화면 내 주변 후보 중 커서에 가장 가까운 적으로 즉시 록온한다. 선택은 자동 교체로부터 1초 보호하며 후보가 없으면 기존 표적을 유지한다. Q는 종료 키로 사용하지 않고 F10으로 종료한다. `targeting.screen_distance_switch.enabled=true`로 화면 거리 교체를 시험한다. 화면 반폭·반높이로 정규화한 간격 0.7에서 시작·0.55에서 복귀하며, 기존보다 25% 이상 가까운 후보가 0.25초 유지되면 교체한다. 대체 후보가 없으면 유지한다. 모든 대기 시간은 Overdrive와 무관한 실제 초다. 세부 조건은 표적 규칙을 따른다.

이동별 임시 카메라 줌은 `movement_config.json`의 `camera_zoom`에서 조정한다. 정지·일반 이동 1배, 대시 0.9배·부스트 0.85배, 전환 0.2초다. 중앙 레이더는 `../ui_unit_test_v2/ui_config.json`의 `radar`로 조정한다. 정지 반경 260px·일반 이동 90%·대시 75%·부스트 70%이며 대시·부스트는 불투명 표시다.

```text
python tests/sword_movement_test.py
```

재미용 3배속은 `python tests/sword_movement_speed_test.py`로 실행한다. Runner에서도 별도로 선택할 수 있다. 일반 이동 90m/s·대시 300m/s·부스트 시작 750m/s이며 공격 전진도 3배다. 모션 재생·가감속 시간·맵 크기는 유지한다. 기체가 화면을 벗어나지 않도록 카메라 응답 시간은 0.05초로 맞춘다. 기본 설정 파일은 변경하지 않으며, 같은 실행 옵션을 지원한다.

Runner에서 `tests/sword_movement_test.py`를 선택하거나 창에 드롭해도 별도 프로세스로 실행한다. 게임 에셋 없이 입력·카메라·눈금을 시연하려면 같은 명령에 `--demo`를 붙인다. 공개 글꼴은 `data/fonts/SUITE-otf/SUITE-Bold.otf`를 사용한다.

실제 에셋으로 실행하는 이동·UI와 독립 파츠 합성 훈련장은 본편의 `game/training_encounter.json`을 공유한다. Shock Bot 1기의 `r03` 파츠·군집 아틀라스와 Break 동작을 사용한다. 교전이 끝나면 F5로 다시 시작한다.

실제 에셋 경로에서는 회색 마찰·흙 파편·노즐 분사 연기·에너지 Trail을 함께 표시한다. 부스트/대시 공격에서는 효과를 강화하고 일반 공격은 3·4타에 발생한다. `movement_config.json`의 `ground_effects`로 조정한다. 마찰은 0.05초, 입자는 최대 128개다. 백웨폰 출력은 별도 준비 상태이며 이 훈련장의 장착·스왑에는 아직 연결하지 않았다.

| 입력 | 동작 |
| --- | --- |
| WASD | 화면 기준 이동. 검 달리기는 이동 방향, 총 이동은 조준 방향 유지 |
| Shift 유지 + WASD | 마우스 조준 방향을 바라보는 접지 대시 |
| Space | 0.08초 준비 후 250m/s에서 이동 목표 속도로 감속하는 부스트. 입력이 없으면 조준 방향 사용 |
| 마우스 | 대기·대시·부스트의 조준과 카메라 시선 오프셋 |
| 좌클릭 | 검 1→2→3→4타 / 총 사격. 유지 시 자동 공격·연사 |
| I | 기체 프레임 보간·블러와 원본 12fps 표시 비교 |
| 1 / 2 / 3 | 에너지 레벨. 기체 발광·검 Trail·명중 범위·전신 잔상 비교 |
| G | 거리 눈금 표시 전환 |
| H | 그림자 표시 전환 |
| F5 | 이동·표적·UI 초기화와 훈련장 중앙 복귀 |
| R | 완충 후 Standby에서 Overdrive 발동 |
| Esc | 일시정지·재개 |
| F1 / F2 | 선택 표적 피해 / 플레이어 피격 |
| F3 / F4 / 4 | 에너지 감소 / 흡수 회복 / 레벨 순환 |
| F6 / F7 / F8 / F9 | Overdrive 강제 발동·해제 / 록온 크기 / 흡수 / 대시 표시 |
| E / F | 검↔총 수납·인출 / 로드아웃 전환 |
| C / T / V / B | COUNTER / 표적 활성 / 필살기 표시 / 대화창 |
| 우클릭 유지 | 총 조준 자세·정확도 / 자동 표적 선택의 조준 범위 확대 |
| Q | 커서 최근접 주변 후보로 즉시 록온 |
| F10 | 종료 |

- 흙바닥 1,000m × 1,000m, 중앙에서 시작한다. 10m 눈금과 100m 강조선·좌표·속도·미니맵을 표시한다.
- idle→달리기·idle→대시·달리기↔대시에는 0.2초 SmoothStep 가감속을 적용한다. 이동 키를 놓으면 마지막 방향으로 0.2초 관성 감속해 정지하며 최고 속도 기준 달리기 약 3m·대시 약 10m를 더 이동한다. 감속 중 새 이동 입력은 즉시 방향을 바꾼다. 부스트는 입력을 놓아도 진행하고, 종료 후 남은 입력으로 달리기·대시에 복귀한다.
- 창 포커스를 잃으면 일시정지하고 누른 키를 해제한다. 창을 선택한 뒤 Esc로 재개한다.
- 검 공격은 1.5배속으로 재생하며 타격 시작 순간의 마우스 방향으로 전진한다. 일반 공격 전진은 WASD로 조종하지 않으며 다음 타격에서 현재 마우스 방향을 다시 읽는다. 속도는 일반/대시 기준 1·2·4타 50/90m/s, 3타 70/120m/s다. `combat.acceleration=constant`로 첫 프레임부터 고정 속도를 적용한다. Shift 변경은 진행 중인 타격에도 적용한다. 부스트가 없는 연결 대기에서는 WASD로 일반 이동에 복귀한다.
- Space로 부스트해도 공격 시간·다음 타격 예약·자동 연계·Trail을 유지한다. 준비와 추진 중에도 공격을 계속 재생하고 위치 이동은 부스트가 우선한다. 종료 뒤 진행 중인 타격의 공격 이동으로 이어진다. 표적 A/B/C의 검 명중을 표시하며 시연용 HP·피해 숫자·HIT/DAMAGE·에너지 흡수를 함께 확인한다. 본편 피해 규칙·전용 부스트 공격은 별도 범위다.
- UI v2의 HUD·타이틀·일시정지·무기 카드·스캔라인과 월드 전용 카메라 블러를 재사용한다. HP·에너지·록온·피해 숫자·흡수·무장 전환은 훈련장 상태와 시연 입력으로 갱신한다. 미니맵 좌표·부스트 준비는 실제 상태를 사용한다.

검 Trail과 실제 판정은 레벨별 칼날 길이 2.4/3.6/5.0배, 대시 공격에서는 추가 1.35배의 시험값을 사용한다. 전신 잔상은 최대 0/4/8개이며 생성 당시 에너지색을 원래 명암과 55/70/85% 혼합하고 수명에 따라 투명도와 명도를 함께 낮춘다. 3타 찌르기는 `>`로 표시하고 Y축 판정은 위아래 ±1.5m의 여유를 준다. 상세 수치와 미연결 범위는 [검 효과 명세](../../docs/unit-tests/sword_movement.md#검-trail에너지-레벨명중-확인)를 따른다.

공개 수치 궤적 `trail_sample.json`은 게임 에셋을 포함하지 않는다. `python samples/sword_movement/make_trail_sample.py`로 재생성하며 `--demo`가 이를 읽는다. 실제 기체 전신 잔상은 로컬 게임 에셋이 있는 경로에서 확인한다.

방향 설계는 검 달리기·대시 모두 이동 방향을 바라보도록 통일한다. 위 입력표는 현재 실행 코드의 동작이며 검 대시 방향 통일은 미반영이다. 검의 옆걸음·뒷걸음과 조준 방향 유지 이동은 향후 과제다. 총은 조준 방향을 유지하고 전진·후진·좌우 이동 모션을 선택한다. [현재 명세와 과제](../../docs/unit-tests/sword_movement.md)를 따른다.

## 접촉 스커트·총·Energy Mask 연결

로컬 접촉 스커트 후보의 27종과 이동 전환·부스트 13종을 8방향으로 연결한다. 스커트는 Unreal의 다리 메시 접촉에 따른 최소 힌지 보정 결과를 재생한다. 관성·감쇠가 있는 Chaos 동역학이나 실행 중 3D 충돌 계산은 포함하지 않는다. 기존 후보의 전진 총 달리기 2종에는 급개방이 남아 있다.

기본 `movement_config.json`은 `player_contact_runtime_aligned_20261117` 카탈로그와 품질별 아틀라스를 사용한다. 현재 27종의 기체 왼쪽 총 수납을 기준으로 전환 13종을 맞춘다. 이 후보의 수납 예외이며 전체 장비의 반대편 수납 규칙을 변경하지 않는다. 실제 출력·자동 입력 재생·사용자 외관 승인 범위는 [연결 기록](../../docs/ai-dev-log/2026-11-17-contact-runtime-gun-energy.md)을 따른다.

총은 기존 시험 규칙인 45발·0.085초 연사·사격 후 1초 유예와 지수 탄약 회복을 사용한다. 빈 탄창 시도는 회복 유예를 다시 시작하지 않으며 수납 중에도 회복한다. Overdrive의 쿨다운 배율로 연사가 빨라지고 탄약 회복은 실제 경과 초를 따른다. 총 피해는 LV1/LV2/LV3/Overdrive에서 12/16/20/30이다. 발사 시 피해를 저장한다. Overdrive는 10초이며 빈 탄창에서도 탄약 소모 없이 사격한다. Bullet Trail은 현재 에너지색을 사용하고 금속 명중 불꽃은 4개·최대 0.18초다. 총탄 명중 카메라 진폭은 일반 6px·Overdrive 8px다. 총 효과음은 현재 사운드 bank를 재사용한다.

사격·조준·수납/인출 중에도 이동·대시·부스트를 유지한다. 일반 검 공격 중 전환은 막고 부스트 중에는 전환을 허용한다. 수납/인출은 제작된 전신 클립을 사용한다. 총 부스트는 총 대시 클립을 공유한다. 총구 섬광·검 Trail·접지 좌표는 저장된 Unreal 본 변환을 투영한다.

OpenGL 아틀라스의 Energy Mask는 기체와 같은 전후 프레임·벡터·위상으로 보간한다. 레벨 1/2/3과 Overdrive 표시색을 HUD·Trail과 공유한다. 색상은 BC7, 마스크·벡터는 무손실이며 높음/보통/낮음 해상도를 각각 준비한다. 소프트웨어 렌더러의 마스크 색상 변경은 이번 연결 범위 밖이다.

## 오버드라이브 무지개색 시험

`python tests/overdrive_rainbow_test.py`로 실행하거나 Runner에서 같은 파일을 선택·드롭한다. F6으로 강제 발동·해제하고 좌클릭으로 검 Trail을 확인한다. R은 기존 완충·Standby 조건을 따른다. 오버드라이브 중 기체 림·Trail·잔상·HUD가 같은 시간 기준의 색상으로 순환한다. 기본 주기는 실제 시간 3초이며 `movement_config.json`의 `overdrive_rainbow.cycle_seconds`로 조정한다. 일시정지는 색상 순환도 멈추고 종료·초기화는 원래 팔레트로 복원한다. 저장 테마와 피해량·지속 시간은 유지한다.

공통 훈련장의 `--demo`, `--script`, `--capture`, `--report` 옵션을 함께 사용할 수 있다. 기본 도형 시연은 HUD·검 Trail을 확인하며 실제 기체 림은 로컬 에셋 경로에서 확인한다. 기본 훈련장에서도 `--overdrive-rainbow`로 켜고 무지개색 진입점에서는 `--no-overdrive-rainbow`로 해제할 수 있다. 반복 검증 입력은 `overdrive_rainbow_input.json`이다.

## 설정과 에셋

`movement_config.json`의 거리는 미터, 속도는 m/s, 시간은 초다. 기본 이동은 30m/s·대시는 100m/s다. 부스트 준비 0.08초 동안 일반 이동을 이어가고 등 스러스터를 수직 준비→수평으로 전환한다. 실제 분사는 출발 시 켜며 250m/s→현재 이동 목표 속도를 0.2초 SmoothStep으로 감속한다. 목표는 일반 30·대시 100·입력 없음 0m/s다. 고정 입력의 추진 구간 거리는 각각 28/35/25m이며 준비 중 이동은 별도다. 모션 전환은 0.12초, 경계 반경은 2.5m다. 달리기 주기는 실제 속도/기준 12.22m/s로 재생한다.

보간은 기존 양방향 Unreal 모션 벡터를 사용한다. 달리기와 공격은 선형 위상 `p(t)=t`를 사용한다. 공격은 `combat.easing=linear`로 선택하며 타격 전체 시간·재생 배속은 유지한다. 그림자·검 궤적·판정 구간·원본 프레임에도 같은 시간을 적용한다. 공격 이동은 가속 없이 고정 속도를 쓰며 일반 이동의 0.2초 가감속과 구분한다. 그림자는 두 프레임의 알파를 한 번 보간한다.

카메라 블러는 이동축을 따라 강도 계수 0.35·최대 9px·17회 샘플·방향 치우침 0.65를 사용한다. 월드에만 적용하고 HUD는 필터 밖에 둔다. 기체 블러는 강도 20%·기본 노출 8ms이며 재생 배율로 환산한다. 전신 잔상은 별도의 블러 없이 저장된 자세를 그린다. OpenGL에서는 이동 128개·공격 32개를 공유 아틀라스 캐시로 미리 올리고 그림자는 원본 알파를 R8로 올린다.

- 실제 기체: 로컬 `data/runtime/catalog/prerender/player_sword_boost_prepare_8dir_shadow/catalog.json`. 시트 제한 안에서 나눈 메카 번들과 프레임별 그림자를 등록한다.
- 공격: 로컬 `data/runtime/catalog/prerender/player_sword_combo_movement_8dir_shadow/catalog.json`. 기존 4타를 같은 원점·그림자로 출력한다.
- 보간: `data/runtime/frame_interpolation/player_sword_boost_prepare/catalog.json`, `data/runtime/frame_interpolation/sword_movement_combo/catalog.json`. 공격 벡터는 같은 AnimSequence의 기존 UI v2 데이터를 재사용하고 원점 피봇을 정렬했다.
- 그림자는 기존 Unreal 중성 수신면 비교 패스와 기존 파츠 로더를 사용한다. 바닥→그림자→본체 순서이며 `shadow_opacity` 기본값은 기존 로더와 같은 0.5다. 그림자 없는 기체 카탈로그는 오류로 알린다.
- 흙: 로컬 `data/runtime/images/textures/polyhaven/dirt/dirt_diff_1k.png`(원본 1024×1024px). [Dirt / Charlotte Baglioni / Poly Haven](https://polyhaven.com/a/dirt), [CC0](https://polyhaven.com/license). 원래 촬영 범위는 폭 2m지만, 현재는 사용자 요청으로 10m 간격에 성기게 반복한다. 화면에서 약 256×82px이며 최종 지면 재질·스케일을 확정하지 않는다.
- 설정의 경로는 설정 파일 위치를 기준으로 해석한다. 실행 위치나 개인 절대 경로를 요구하지 않는다.
- AI 생성 기체·시트·화면 출력은 공개 저장소에 포함하지 않는다. 로컬 에셋이 없으면 `--demo`를 사용한다.

## 텍스처 품질

Esc 일시정지 또는 타이틀의 **설정**에서 원본 기준 **높음 75%·보통 50%·낮음 25%**를 선택하고 저장한다. 기본은 낮음 25%이며 현재 실행에 바로 적용한다. 교체 중 게임 진행 상태를 보존한다. 뒤로/Esc는 저장하지 않는다. 기본 저장 파일은 `data/settings/game_settings.json`, 시험 파일은 `--settings-file 경로`로 분리한다.

설정은 기체 색상·보간 벡터의 가로와 세로 해상도를 함께 선택한다. HUD·바닥·그림자는 그대로다. `texture_quality_profiles`의 로컬 Oodle BC7/무손실 벡터 후보가 필요하며, 없는 후보를 다른 품질로 조용히 대체하지 않는다. 현재 보간 GPU Storage는 높음 약 885MiB·중간 508MiB·낮음 236MiB이며 원해상도 그림자와 UI/바닥/입자는 별도다. 실제 물리 VRAM 점유량과 구분한다.

## 재현 가능한 확인

```text
python tests/sword_movement_test.py --demo --script samples/sword_movement/smoke_input.json --frames 240
python tests/sword_movement_test.py --script samples/sword_movement/smoke_input.json --frames 240 --capture-frame 75 --capture output/sword_movement_20261113/movement.png --report output/sword_movement_20261113/input_report.json
python -m unittest discover -s tests/automated -p test_sword_movement.py -v
python tests/sword_movement_test.py --script samples/sword_movement/acceleration_input.json --frames 155 --report output/movement_acceleration/report.json
python tests/sword_movement_test.py --script samples/sword_movement/transition_input.json --frames 390 --report output/sword_movement/review/report.json --record-directory output/sword_movement/review/movie
python tests/sword_movement_test.py --script samples/sword_movement/energy_trail_input.json --frames 400 --report output/sword_energy_trail/report.json
python tests/sword_movement_test.py --demo --script samples/sword_movement/energy_trail_input.json --frames 400 --report output/sword_energy_trail/demo/report.json
python tests/sword_movement_test.py --script samples/sword_movement/feedback_combo_boost_input.json --frames 300 --report output/feedback_combo_boost/report.json
```

사전 지정 입력은 60Hz로 갱신하며 OS 포커스 변화에 의한 일시정지를 적용하지 않는다. 물리 키보드·마우스 조작과 구분한다. 일반 실행은 실제 경과 시간을 사용한다. `--profile output/performance/sword_movement.json`으로 공통 계측을 선택적으로 켤 수 있다. `--report`의 그리기 경과 시간은 CPU 호출 시간이며 GPU 시간이 아니다.

검 Trail은 휘두른 곡선을 따라 여러 가닥이 길게 흐르며 양끝이 가늘어지는 파란 검빛이다. 몸 주변의 붙어 있는 검풍은 공격 유효 구간에만 300° 근접 판정을 설명한다. 검풍은 회색·알파 0.28에 주변 바닥 텍스처 색을 45% 섞는다. 등 뒤 좌우 30°씩은 비우며 레벨별 크기 배율 1/1.25/1.5를 표시 반경·띠 폭·판정에 함께 적용한다. 완충 후 OVERDRIVE가 뜬 Standby에서는 기체·검에 빨간 림과 1.8초 호흡을 표시한다. 에너지 마스크 밝기 제어는 보류한다.
