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
- `v2.layout.energy_level_size`: 에너지 바 끝에 붙는 레벨 영역의 폭과 위쪽 확장 높이. 독립 위치 없이 한 외곽으로 연결한다.
- `v2.style.counters`: HIT/DAMAGE의 원근 `depth`(0~1)·기울기 `lean`/`slope`·최대 폭·오른쪽 여백. 숫자 갱신도 같은 투영을 사용한다.
- `v2.style.panel_cut_pixels`·`surface_opacity`: 사선 외곽과 면의 기본 표현. 기존 금속 사각 패널을 사용하지 않는다.
- `v2.style.hud_scale`: 전투 HUD 배율, 현재 0.9. 레이더·기체·메뉴는 제외하며 각각의 앵커를 유지한다.
- `v2.style.counter_baseline_pixels`·`lock_thickness_pixels`·`lock_label_gap_pixels`: 받침선·록온 외곽 두께와 글자 간격. 크기 값은 HUD 축소 전 논리 픽셀이다.
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
| G | 필살기 아이콘을 통과해 에너지 바로 향하는 흡수 Trail |
| R / T | 고정 샘플 표적명 교체 / 타겟 표시 유무 |
| C / Space | COUNTER / 대시 가능 표시 변경 |
| E / F | 활성 무기 / 로드아웃 변경 |
| F5 | 표시 초기화 |
| Esc | 일시정지 / 계속 |

도안 배치를 바로 볼 수 있도록 최초부터 98 HIT·12,004 DAMAGE·COUNTER를 표시한다. 이 값은 전투 규칙·자동 카운터 판정이 아니다. 에너지 조절·레벨·Overdrive 표기도 서로 독립적인 샘플 조작이다. V는 필살기 키 **후보 표기**이며 필살기를 발동하지 않는다. 무기 전환은 표시 상태를 바꾸며 v1의 전환 궤도 애니메이션을 복제하지 않았다.

미니맵 지형·접촉점과 플레이어·표적은 기본 도형이다. R은 고정 샘플 이름 순환이며 실제 거리·각도 후보 획득은 구현하지 않았다. 합의한 본편 규칙은 [원거리 표적 획득 명세](../../docs/ranged_targeting.md)를 따른다.

## 검증

- v2 자동 검사 12개, 기존 UI 포함 67개 통과: 독립 진입·창 없는 생성·표시 값 범위·흡수 경로·일시정지·상태 경계·원근면 방향·에너지/레벨 접점·HP 사선 끝단·축소된 흡수 도착점.
- Pico2D/SDL dummy에서 전투·숫자 갱신·HP 감소·자원 0·흡수·일시정지·타이틀·도움말 8개 화면을 렌더링하고 자원을 해제했다. 전투·HP 감소·자원 0·흡수·타이틀·일시정지 이미지를 열어 확인했다. 기존 금속 패널 텍스처 미생성과 배율/viewport/clip의 복원도 확인했다.
- 실제 창 키·클릭 조작, Runner GUI 드롭, 애니메이션 사용감과 사용자 외관 승인은 미확인이다.
- 진입점의 `--scene menu`·`--frames 2`·`--capture output/ui_unit_test_v2/combat.png`는 장면 선택·프레임 제한·재생성 가능한 화면 저장용이다.
