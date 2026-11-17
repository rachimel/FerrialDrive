# UI 테스트 폰트

2026-11-05 사용자 요청으로 글꼴을 역할별로 조정했다. 무기 이름은 기존 표시보다 10% 확대하고 개별 피해는 10% 축소하며, 학교안심 운동장 원본·숫자 수정본·전체 Wide 수정본을 구분한다.

## 새 실행 환경의 준비

현재 UI 설정에서 참조하는 폰트와 이용 조건은 `.gitignore`의 지정 경로로 배포한다. 별도 폰트 다운로드·시스템 설치 없이 프로젝트 경로에서 직접 읽는다. Python·Pico2D 실행 환경은 별도로 준비한다. 수정본 생성에만 필요한 fontTools는 UI 실행 의존성이 아니다.

| 파일 경로 | 용도 |
| --- | --- |
| `data/fonts/SUITE-otf/SUITE-Bold.otf` | 메뉴 타이틀·소제목 |
| `data/fonts/SUITE-otf/SUITE-Light.otf` | UI v2 OVERDRIVE의 이전 가는 굵기 비교본 |
| `data/fonts/SUITE-otf/SUITE-Regular.otf` | UI v2 OVERDRIVE 문구·16px·에너지 바 폭 75%에 맞춘 자간 |
| `data/fonts/gamwulchifreegothic/GamwulchiFreeGothic.otf` | 탄약 숫자·무기 이름 |
| `data/fonts/Paperlogy-1.001/Paperlogy-7Bold.ttf` | 이전 무기 이름 비교본 보존 |
| `data/fonts/ferrial_hud_square_wide/FerrialHudSquareWide-Regular.otf` | HIT·누적 DAMAGE·개별 피해 숫자, 전투 제목·TARGET·표적명·HUD 본문·레이블·일시정지·로드아웃 번호 |
| `data/fonts/ferrial_hud_square/FerrialHudSquare-Regular.otf` | 이전 숫자 수정본 보존·Wide 생성 입력 |
| `data/fonts/학교안심 운동장/HakgyoansimUndongjangOTFL.otf` | 수정본 재생성에 사용하는 원본 |
| `data/fonts/Cafe24OhsquareAir-v2.0/Cafe24OhsquareAir-v2.0.otf` | 메뉴 본문·버튼·설명·순번 |
| `data/fonts/s_core_dream/SCDream5.otf` | 이전 로드아웃 번호 비교본 보존 |

Cafe24는 [공식 배포처](https://fonts.cafe24.com/)와 배포 패키지의 이용 조건, 학교안심 운동장은 [KERIS 공식 안내](https://copyright.keris.or.kr/wft/fntDwnldView?fntGrpId=GFT202312110000000000016)의 OFL·재배포 허용을 확인했다. 폰트별 `LICENSE.txt`에 저작권 고지와 SIL Open Font License 1.1 전문을 보관한다. Cafe24 원본 라이선스 PDF도 `docs/licenses/`에 유지한다.

## 현재 역할과 출처

- `SUITE-otf/SUITE-Bold.otf`: 메뉴 헤더. 타이틀 64px·소제목 26px. 일시정지는 후속 요청으로 Wide로 변경했다. 사용자가 제공한 원본과 OFL `LICENSE`를 사용한다. [공식 저장소](https://github.com/sun-typeface/SUITE)를 참고한다.
- `gamwulchifreegothic/GamwulchiFreeGothic.otf`: 탄약 숫자 48px·비사용 0.5배. 무기 이름은 14px 역할에 활성 1.1배·비사용 0.88배로 표시해 직전 대비 10% 키웠다. 사용자 제공 원본과 동봉 `gamwulchifg.pdf`·[출처 기록](gamwulchifreegothic/SOURCE.md)을 보관한다.
- `Paperlogy-1.001/Paperlogy-7Bold.ttf`: 이전 무기 이름 비교용 14px Bold를 보존한다. 현재 무기 이름은 가물치 무료고딕이다. 사용자 제공 원본이며 [제작자 안내](https://freesentation.blog/paperlogyfont)와 [공식 OFL](https://github.com/Freesentation/paperlogy/blob/main/OFL%20license.txt)을 참고한다. 저작권 고지·OFL 전문은 `LICENSE.txt`에 보관한다.
- `ferrial_hud_square_wide/FerrialHudSquareWide-Regular.otf`: 전투 HUD·피해·카운터·일시정지 26px·로드아웃 번호 14px의 현재 비교본. 한글·영문·기호 전체의 곡선을 직선·사선 모서리로 바꾸고 가로 120% / 세로 100%로 확장했다. 기존 역할별 크기는 유지한다. [제작 기준·이용 조건·검증 범위](ferrial_hud_square_wide/README.md)를 따른다.
- `ferrial_hud_square/FerrialHudSquare-Regular.otf`: 숫자 0~9만 각지게 만들고 0 사선을 제거한 이전 비교본. Wide 생성 입력과 비교용으로 보존한다. [이전 수정 내역](ferrial_hud_square/README.md)을 따른다.
- `학교안심 운동장/HakgyoansimUndongjangOTFL.otf`: 수정본 생성에 사용하는 사용자 제공 OTF 원본을 보존한다. 개별 피해 숫자도 후속 요청으로 수정본을 사용한다. 저작권자는 KERIS, 제작사는 디자인210이다.
- `Cafe24OhsquareAir-v2.0/Cafe24OhsquareAir-v2.0.otf`: 메뉴 본문·설명·버튼·순번. [공식 Air 패키지](https://img.cafe24.com/csdstatic/freefonts/download/kr/Cafe24OhsquareAir-v2.0.zip)와의 바이트 일치는 이전 배포 정리에서 확인했다. 동봉 안내는 `docs/licenses/License-OhsquareAir.pdf`다.
- `Cafe24Ohsquare-v2.0/Cafe24Ohsquare-v2.0.otf`: 이전 일시정지 제목. 도구 공통 테마에서 계속 사용하며, 이번 게임 UI 헤더 변경과 구분한다. [공식 패키지](https://img.cafe24.com/csdstatic/freefonts/download/kr/Cafe24Ohsquare-v2.0.zip)와 동봉 안내 `docs/licenses/License-Ohsquare.pdf`를 보존한다.
- `s_core_dream/SCDream5.otf`(Medium): 이전 로드아웃 번호 14px 비교본을 보존한다.
- `s_core_dream/SCDream4.otf`(Regular): 기존 HUD 본문용 원본을 보관하며 도구 공통 테마에서 사용한다. 전투 HUD 텍스트는 후속 비교 요청으로 Ferrial HUD Square Wide를 적용한다.

`s_core_dream/`에는 SCDream2~6와 `LICENSE.txt`를 보관한다. [공식 배포처](https://s-core.co.kr/company/font/)의 `S-Core_Dream_OTF.zip` 원본 파일이다. 역할별 경로·크기는 `samples/ui_unit_test/ui_config.json`에서 설정한다. 이전 Cafe24 PRO Slim Fit·Max는 현재 UI에서 참조하지 않는다.

Unit Test Runner의 실행기·소개 제목은 기존 Cafe24 써라운드 일반형 20px, 목록·파일명·경로·소개·상태·오류는 SCDream4 Regular 18px다. 이번 게임 UI 폰트 변경과 구분하며 도구 공통 테마는 변경하지 않았다. 설정은 `Tools/theme_reference/theme.json`과 이를 읽는 `Tools/unit_test_runner/theme.py`를 따른다.

## 배포 범위와 확인 상태

`.gitignore`는 UI가 사용하는 원본·수정본과 이용 조건의 지정 경로만 포함한다. 사용하지 않는 굵기·TTF·웹폰트·기타 로컬 폰트는 제외한다. **원본과 이전 숫자 수정본은 보존하고 전체 확장본은 `ferrial_hud_square_wide/`에 별도로 생성**한다.

초기 숫자 수정본 검사: 2026-11-05 수정본의 숫자 10개 변경·그 외 12,604개 윤곽·문자 매핑·글자 폭/사이드베어링·저작권 고지 보존을 확인했다. UI 자동 검사 50개와 Pico2D SDL dummy의 탄약 0/45/999·HIT 101·DAMAGE 102,030·일시정지 렌더링을 확인했다. 실제 창 직접 조작·사용자 시각 승인은 확인 전이다.

Wide 검사: 글리프 순서·매핑·윤곽 수/방향·세로 메트릭 보존과 가로 120%를 확인했다. 매핑된 실제 윤곽 3,787개의 래스터 출력에 소실·세로 범위 이상은 없었다. UI 검사 50개와 Pico2D SDL dummy HUD·긴 표적명·피해 팝업·일시정지 렌더링을 확인했다. 복잡 기호의 크기별 픽셀 차이와 최종 사용자 시각 승인은 Wide 안내의 확인 범위를 따른다.
