# 하한 사양 벤치마크 시연

공개 도형 시연은 별도 리소스 준비 없이 실행한다. Trail 결 파일이 없으면 로딩 중에 메모리에서 준비한다. 실제 에셋 시나리오를 실행하려면 `python automate/run.py trail-texture`로 Trail 결을 미리 준비한다. [준비 파일 안내](../../docs/tool-usage/trail_texture_preparation.md)

Windows·Pico2D·OpenGL 환경에서 프로젝트 루트의 `python tests/hardware_profile_benchmark.py --scenario demo`를 실행한다. 프로필은 이 폴더의 `profile.json`이며 기본 도형 훈련장을 직접 조작한다. 실제 게임 이미지·모델 없이 같은 벤치마크 경로를 확인한다. 공개 글꼴은 저장소의 `data/fonts/`를 사용한다. `--scenario demo`를 생략하면 실제 에셋 훈련장이 기본이다.

확인할 결과는 CPU/메모리 제한의 Windows 조회 일치, 기능 위반 여부, 최소 목표 60FPS 예산 약 16.67ms 초과 비율이다. 기준 장비 RAM은 8GB이며 프로세스/Job의 2GiB 커밋 상한과 구분한다. 권장 목표의 시간 예산은 `--target-fps 165`로 약 6.06ms를 검사하며 권장 부품은 미정이다. 결과는 `output/performance/hardware_profile/`의 새 폴더에 저장한다. 시연 입력은 수정하지 않는다. 이 프로필은 UHD 630의 처리량이나 전체 RAM 8GB 환경을 에뮬레이션하지 않는다.

기본 Movement는 본편과 같은 Shock Bot 1기 훈련 배치를 사용한다. 적 없는 기존 이동 부하와 수치를 비교할 때는 이 배치 변경을 고려한다.

WASD·마우스·좌클릭·Shift·Space 입력을 사용하고 창을 닫으면 저장한다. 자동 반복은 `--auto --frames 600`으로 선택한다. 실제 에셋 연결, 제한 없는 비교와 재사용 모듈 연결은 [사용법](../../docs/tool-usage/hardware_profile_benchmark.md)을 따른다.

다수 적 교전은 `--scenario combat`으로 선택한다. 게임 이미지·모델 없는 시연은 `--scenario combat --demo --auto --frames 120`이다. 같은 공개 적 배치와 실제 교전 모듈을 사용하며 샘플 원본은 수정하지 않는다. 각 실행 폴더의 `report.json`과 `report.md`에서 원자료와 한국어 표 보고서를 확인한다.
