# Combat Test v1.5

기존 플레이어 이동·검·기관단총·록온·HUD에 기본 도형 적 30기의 교전을 연결한다.

| 유형 | 초기 수 | 배치·역할 |
| --- | --- | --- |
| 소형 | 22기 | 2~3기씩 8무리, 중앙에서 23/31m 부근의 근접 접근형 |
| 중형 | 6기 | 중앙에서 48m 부근의 사격·거리 조절형 |
| 인간형 | 2기 | 중앙에서 37m 부근, 거리에 따라 근접·사격 선택 |

Pico2D가 설치된 Python으로 프로젝트 루트에서 실행하거나 Runner에서 `tests/combat_test_v1_5.py`를 선택한다.

```text
python tests/combat_test_v1_5.py
python tests/combat_test_v1_5.py --demo --mute
python tests/combat_test_v1_5_speed_test.py
python tests/combat_test_v1_5.py --enemy-count 900 --enemy-spacing-m 24 --mute
python tests/combat_test_v1_5_speed_test.py --enemy-count 1000 --enemy-spacing-m 24 --mute
```

3배속 진입점은 플레이어 약출력 대시 150m/s·강출력 대시 300m/s·부스트 시작 750m/s와 공격 전진 3배를 적용한다. 모션·공격 시간·적 이동·적 공격·탄환·넉백·효과 시간은 기본 교전과 같다. 카메라 이동 응답은 0.05초이며 Overdrive의 기존 이동 배율과 곱한다. 동일한 `--demo`·`--mute`·`--script`·`--report` 옵션을 지원한다.

WASD 이동·Shift 대시·Space 부스트·좌클릭 공격·우클릭 조준·Q 커서 최근접 록온·E 검/총 전환·F5 전체 재시작·Esc 일시정지·F10 종료. 화면 거리 교체 실험은 공통 이동 설정을 따른다. 적 전멸 또는 플레이어 HP 소진 시 교전을 종료한다. F5는 시작할 때 선택한 수와 위치로 재배치한다.

Runner에서 두 Combat 테스트의 기본 30기 또는 무음 900·1,000기를 선택한다. 부하 시험은 기존 출현 순서대로 기종을 반복해 플레이어를 중심으로 배치한다. 하드웨어 벤치마크의 1,000기 프리셋도 같은 24m 대형을 사용하며 현재 GPU에서 자원 제한 없이 측정한다. 밀집 비교는 `--enemy-spacing-m 12`를 사용한다.

`encounter.json`의 `spawns`에서 출현 수·위치를, `profiles`에서 체력·속도·공격 수치를 조정한다. 거리 단위는 m, 시간 단위는 초다. 초기 배치에서는 적끼리 겹치지 않는다. 기존 프로필의 HP·피해량·공격 간격을 사용하며 동시 공격 수를 제한하지 않는다.

검 명중 시 0.12초 동안 선형 감속하는 넉백을 적용한다. 소형 3m·중형 1.4m·인간형 0.7m이며 `knockback`에서 조정한다. 검날 궤적의 실제 이동 방향을 지면 미터 좌표로 환산하고, 궤적이 없는 경우 공격 방향을 사용한다. 넉백 중 적의 이동·공격은 중단한다. 사망한 적은 판정·록온에서 즉시 제외하고 0.22초 동안 밀림·분리된 도형의 페이드만 표시한다. 마지막 적을 처치해도 사망 표현은 마무리되며 일시정지 중에는 멈춘다. 총탄은 탄도 방향을 역투영해 소형 0.3m·중형 0.14m·인간형 0.07m를 0.06초 동안 약하게 민다. `gun_knockback`에서 조정한다. 총탄 넉백은 적 이동·공격을 중단하지 않으며 재명중은 속도를 누적하지 않고 반응만 갱신한다. 진행 중인 검 넉백은 총탄이 덮어쓰지 않는다.

기본 도형은 추가 이미지나 모델 없이 렌더러로 표시한다. `--demo`의 글꼴·공개 수치 궤적·Trail 준비는 [이동 훈련장 안내](../sword_movement/README.md)를 따른다. 일반 실행의 플레이어 에셋은 같은 훈련장 설정을 재사용한다. 적 모델·애니메이션이나 상·하체 분리 렌더를 새로 제작하지 않는다.

전투 규칙은 `ferrial_drive/combat/enemy_encounter.py`, 기존 전투/HUD 연결은 `encounter_application.py`, 도형 표시는 `encounter_view.py`가 소유한다. 플레이어의 검/총 판정은 기존 투영 원형 표적을 재사용하며, 적 탄환은 이동 선분과 플레이어 이동을 함께 검사한다. 지형 길찾기·플레이어와 적의 몸체 차단·무적 시간은 이 교전 모듈에 추가하지 않았다.

관련 자동 검사는 `python -m unittest tests.automated.test_enemy_encounter`로 실행한다. 자동 검사·렌더 확인과 30기 전투의 실제 조작감·성능 평가는 구분한다.

## 적 렌더링

`rendering.backend=auto`는 OpenGL에서 `instanced`, 소프트웨어 렌더러에서 `batched`를 선택한다. 몸체·선·HP바·적 탄환을 순서대로 모으고 공통 쿼드 인스턴스로 한 번에 제출한다. 이름·상태 문구는 도형 뒤의 텍스트 층이다. `batched`는 기존 SDL 정점 배치를 재사용하고 `immediate`는 비교용 개별 호출이다. 선은 1px 쿼드와 정사각 끝점으로 통일하므로 기존 SDL 선과 픽셀 단위로 완전히 동일하지는 않다.

`--profile`에서 `combat.enemies.draw` 시간을 수집하고 `--report`의 별도 `_encounter.json`에 최종 프레임 도형 수·제출 수·인스턴스 업로드 바이트를 기록한다. 이 값은 적 도형 범위이며 글자·플레이어·HUD·전체 프레임의 GPU 드로우 수가 아니다.

## SMG·Overdrive

총탄 사거리는 총구에서 방향에 관계없이 월드 거리 75m이며 `weapons.range_m`으로 조정한다. 록온 거리와 구분한다. Bullet Trail의 LV1/LV2/LV3 길이는 108/135/162 투영 px이며 Overdrive도 현재 레벨 길이를 사용한다. `weapons.effects.length_pixels`·`length_scales_by_energy_level`에서 조정하며 실제 이동 거리까지만 표시한다.

SMG 피해는 레벨 1/2/3·Overdrive에서 15/20/25/35이며 발사 시 탄환에 저장한다. 탄창은 60발, 관통은 1회로 서로 다른 적 최대 2기를 맞힌다. Overdrive는 실제 10초, 탄약 소모 없이 빈 탄창에서도 사격하며 명중점마다 반경 3m·추가 피해 18의 폭발을 생성한다. 직격 대상도 폭발 범위 안이면 추가 피해를 받는다. 자동으로 탄창을 채우지는 않으며 종료 후에는 현재 잔탄으로 일반 소모·회복 규칙을 사용한다. 사격 사건은 기존 회복 유예 시계를 갱신한다. 검 피해는 60/80/100·Overdrive 150이며 검·총·폭발의 명중 흡수 배율은 0.5다. 발사 반동·폭발/피격 VFX는 [훈련장 전투 수치](../../docs/unit-tests/sword_movement.md)를 따른다.

Bullet Trail은 현재 에너지색을 정점 색상으로 공급한다. 텍스처를 매 프레임 재생성하지 않는다. 실제 총탄 충돌점에는 재질과 관계없이 현재 에너지색의 작은 광륜·십자형 섬광을 0.16초 동안 표시한다. 기본 반경은 36px, 상한은 64개이며 `contact_effects.energy_impact`에서 조정한다. 강철·금속 명중은 한 발에 4개의 불꽃을 폭 3.2px·최대 0.24초 동안 함께 표시하며, 주황색 외곽과 흰 중심을 가산 합성한다. 검의 22개·0.55초와 구분한다. 총탄 명중 카메라 피드백은 일반 10px·Overdrive 16px, 타격별 재시작 방식이며 누적 진폭을 더하지 않는다. `movement_config.json`의 `weapons.damage_by_energy_level`·`overdrive_damage`·`contact_effects`·`effects.*hit_camera_pixels`에서 조정한다.

넉백 재현은 `--script samples/combat_test_v1_5/knockback_input.json --frames 120 --report output/combat_test_v1_5/knockback/report.json`을 추가한다. 검 반복·일시정지·재개·초기화를 포함하며 실제 HP에 따라 사망 여부는 달라진다. 현재 확인 범위와 잠정 수치는 [개발 기록](../../docs/ai-dev-log/2026-11-17-combat-v1-5-crowd-knockback.md)을 따른다.

PBR 적은 `rendering.shared_frame_distance_m` 안쪽과 현재 록온 대상에서 기존 보간 품질을 사용한다. 바깥에서는 동일한 기종·방향·모션의 24fps 표본과 지면 그림자를 공유한다. 기본 반경은 16m이며 설정을 생략하면 모든 PBR 적에 기존 보간을 사용한다. 이 거리는 AI·공격·접촉 판정에 영향을 주지 않는다.
