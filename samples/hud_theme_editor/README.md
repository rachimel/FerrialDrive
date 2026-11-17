# HUD 테마 편집 시연 데이터

- `default_theme.json`: 공개 가능한 수치 색상 29개와 위젯 14개 연결. 실제 게임 에셋이 필요 없다.
- `preview_input.json`: 훈련장 기본 도형·레벨 3·에너지 흡수를 보여주는 지정 입력이다. 원본을 덮어쓰지 않는다.
- 환경: Python·Tkinter·Pico2D·Pillow와 프로젝트에 포함한 공개 폰트.

프로젝트 루트에서 `python automate/run.py trail-texture --demo`로 미리보기용 결을 준비하고 `python automate/run.py hud-theme`를 실행한다. 게임 에셋 사용을 끈 상태에서 기본 도형과 실제 HUD가 툴 안에 표시돼야 한다.

색상 그리드의 **강조**를 선택하면 전체 이름 **기본 선·강조**와 내장 피커가 표시되고 레이더·테두리·무기 표시의 사용처가 강조된다. **체력** 칩의 색을 바꾸면 플레이어 체력과 미니맵의 연결 부위를 함께 확인한다. 부위 버튼으로 대상을 선택하고 별도 색을 연결하면 다른 위젯의 연결은 유지한다. 편집 작업본은 도구의 `workspace/`, 화면과 로그는 `output/hud_theme_editor/`, 저장·게임 적용한 테마는 `data/settings/hud_theme.json`으로 분리한다.
