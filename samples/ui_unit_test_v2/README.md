# 훈련장 HUD 설정

- `ui_config.json`: UI v2 배치·폰트·효과·시연 조작 수치.
- `hud_sample.json`: 체력·무장·대화창의 초기 시연 상태.

`python tests/sword_movement_test.py`로 실행한다. 게임 에셋 없는 도형 시연은 `--demo`를 사용한다.

[조작과 설정](../sword_movement/README.md), [UI 표시 명세](../../docs/unit-tests/ui_unit_test_v2.md), [통합 범위](../../docs/unit-tests/ui_unit_test.md)를 따른다. 시연용 수치를 본편 전투 규칙으로 간주하지 않는다.

주요 표시값은 `v2.layout.dash_x=480`, `v2.style.shared_swap_slot`, `weapon_card.attribute_letter_spacing_pixels=10`, `weapon_card.ammo_gradient_bottom_ratio=0.93`, `counter_visibility`에서 조절한다. 미사일·카운터 슬롯 PNG는 `python samples/ui_unit_test_v2/make_slot_icons.py`로 준비한다(Pillow 필요). 기본 도형만 사용하며 출력은 `icons/`에 원본과 함께 보존한다. 슬롯 색·테두리·배율을 바꾸면 PNG를 다시 준비한다. 기체·검 효과는 이동 설정의 `overdrive_rim`·`sword_effects`가 소유한다.

공통 스왑 슬롯은 120px·내부 도안 1.28배, 미사일 원 테두리는 3.5px·불투명도 0.6이다. 카운터의 원 테두리는 표시하지 않는다. 투명 문양과 UI 패널을 분리하고 테마 색을 적용한다. 사용키 안내는 게임 설정의 `interface.show_key_hints`에서 관리하며 설정 메뉴에서 저장 즉시 켜고 끈다.

[외부 테마 편집기](../../Tools/hud_theme_editor/README.md)에서 팔레트·위젯 연결과 내장 미리보기를 편집한다.

텍스처 품질은 원본 기준 높음 75%·보통 50%·낮음 25%이며 저장 즉시 현재 실행에 반영한다. 기본 무장 샘플에는 추가 속성 아이콘이 없다.
