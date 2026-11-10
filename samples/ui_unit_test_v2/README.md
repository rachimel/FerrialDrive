# ui-unit-test-v2

`concept/ui-concept-v2.png`를 바탕으로 배치와 스타일을 다듬는 독립 UI 테스트다. 도안 이미지는 실행 입력이 아니며, 샘플 도형·수치와 저장소에 배포하는 폰트만 사용한다. 기존 v1과 별도 설정을 사용한다.

## 실행

Pico2D 1.5.1이 설치된 Python 3.11 환경에서 프로젝트 루트 기준으로 실행한다.

```text
python tests/ui_unit_test_v2.py
```

Unit Test Runner에서 `tests/ui_unit_test_v2.py`를 선택하거나 Runner 창에 드롭해도 실행한다. 최초 화면은 1280×720 전투 HUD다. `Esc`로 일시정지를 열고 `타이틀로`를 누르면 타이틀 화면을 확인한다. 설정은 아직 비활성이다.

## 조절 위치

- `ui_config.json`의 `v2.layout`: 미니맵·록온·타겟 HP·플레이어 HP·에너지·필살기 아이콘·레벨·무장·카운터 배치.
- `v2.layout.hp_bar`·`energy_bar`·`ultimate_center_x`: 바의 높이/오른쪽 끝과 아이콘 가로 위치. 마름모의 높이·크기와 두 바의 왼쪽 경계는 공통 계산한다.
- `v2.layout.energy_level_width_pixels`·`v2.style.level_curve_radius_pixels`: HP 옆에 붙는 레벨 영역의 폭과 곡선 강도. HP/에너지 공유 경계와 레벨 왼쪽 사선은 함께 계산한다.
- `v2.style.counters`: HIT/DAMAGE의 원근 `depth`(0~1)·기울기 `lean`/`slope`·최대 폭·오른쪽 여백. 숫자 갱신도 같은 투영을 사용한다.
- `v2.style.panel_cut_pixels`·`surface_opacity`: 사선 외곽과 면의 기본 표현. 기존 금속 사각 패널을 사용하지 않는다.
- `v2.style.hud_scale`: 전투 HUD 배율, 현재 0.9. 레이더·기체·메뉴는 제외하며 각각의 앵커를 유지한다.
- `v2.style.counter_plaque_height_pixels`·`counter_plaque_slant_pixels`: 숫자 아래 평행사변형 받침판의 두께와 사선. 색은 `colors.counter_plaque`다.
- `v2.style.lock_body_scale`·`lock_thickness_pixels`·`lock_accent_pixels`: 몸통 대비 테두리 배율과 기본/강조선 두께.
- `v2.style.lock_text_gap_pixels`·`lock_text_end_gap_pixels`: 강조선에 끝점을 맞추는 글자의 수직 간격과 끝 여백. 크기 값은 HUD 축소 전 논리 픽셀이다.
- `v2.style.weapon_outer_edge_pixels`: L자 대신 강조하는 무장 왼쪽 외곽의 두께.
- `ui_config.json`의 `colors`·`fonts`: 색상과 글꼴 역할·크기.
- `hud_sample.json`: HP·에너지·에너지 레벨·Overdrive 표기·HIT/DAMAGE·무장·샘플 표적명.
- 변경 뒤 Runner에서 재실행한다. 실행 중 샘플 원본을 저장하거나 수정하지 않는다.

## 샘플 조작

| 입력 | 확인할 표시 |
| --- | --- |
| F1 | 도움말 켜기/끄기 |
| 1 / 2 | 표적 / 플레이어 피해, HP 감소 효과·피해 숫자 |
| 3 / 4 | 에너지 10% 감소 / 증가·흡수 Trail |
| 5 / 6 | 에너지 레벨 / Overdrive 표기 변경 |
| 7 | 몸통 크기와 록온 테두리의 비례 비교: 1→1.5→0.75배 |
| G | 필살기 아이콘을 통과해 에너지 바로 향하는 흡수 Trail |
| R / T | 고정 샘플 표적명 교체 / 타겟 표시 유무 |
| C / Space | COUNTER / 대시 가능 표시 변경 |
| E / F | 활성 무기 / 로드아웃 변경 |
| F5 | 표시 초기화 |
| Esc | 일시정지 / 계속 |

도안 배치를 바로 볼 수 있도록 최초부터 98 HIT·12,004 DAMAGE·COUNTER를 표시한다. 이 값은 전투 규칙·자동 카운터 판정이 아니다. 에너지 조절·레벨·Overdrive 표기도 서로 독립적인 샘플 조작이다. V는 필살기 키 **후보 표기**이며 필살기를 발동하지 않는다. 무기 전환은 표시 상태를 바꾸며 v1의 전환 궤도 애니메이션을 복제하지 않았다.

미니맵 지형·접촉점과 플레이어·표적은 기본 도형이다. R은 고정 샘플 이름 순환이며 실제 거리·각도 후보 획득은 구현하지 않았다. 합의한 본편 규칙은 [원거리 표적 획득 명세](../../docs/ranged_targeting.md)를 따른다.

몸통 크기는 `target_body_size_pixels`로 공급한다. 게임에서는 전체 스프라이트 경계 대신 실제 몸통의 화면 Rect를 `HudV2State.target_body`로 전달한다. 01·02 로드아웃의 사선 외형은 유지하며 커서에 반응하는 3D 회전은 검토 후보로 남긴다.

## 검증

- v2 자동 검사 16개, 기존 UI 포함 71개 통과: 기존 경계 검사와 함께 마름모 공통 접점·레벨/HP 비침범·몸통 비례·받침판 평행 조건을 확인했다.
- Pico2D/SDL dummy에서 기본·긴 카운터·숫자 갱신·HP 감소·작은/큰 표적·자원/타겟 없음·흡수·일시정지·타이틀·도움말 11개 상태를 렌더링하고 자원을 해제했다. 주요 이미지를 열어 오른쪽 잘림·공유 경계·강조선/글자·무장 외곽을 확인했다. 기존 금속 패널 미생성과 배율/viewport/clip 복원도 확인했다.
- 실제 창 키·클릭 조작, Runner GUI 드롭, 애니메이션 사용감과 사용자 외관 승인은 미확인이다.
- 진입점의 `--scene menu`·`--frames 2`·`--capture output/ui_unit_test_v2/combat.png`는 장면 선택·프레임 제한·재생성 가능한 화면 저장용이다.
