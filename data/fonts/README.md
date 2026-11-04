# UI 테스트 폰트

현재 글꼴은 역할별로 분리한다. 폰트 배포 정리에서는 크기·배치·색·카운터 효과를 변경하지 않는다.

## 새 실행 환경의 준비

현재 UI 설정에서 참조하는 폰트는 모두 Git에 포함한다. 저장소를 복제하면 S-Core Dream과 아래 OTF 3개가 함께 준비되며, 별도 폰트 다운로드·시스템 글꼴 설치 없이 프로젝트 경로에서 직접 읽는다. Python·Pico2D 실행 환경은 별도로 준비한다.

| 파일 경로 | 용도 |
| --- | --- |
| `data/fonts/Cafe24OhsquareAir-v2.0/Cafe24OhsquareAir-v2.0.otf` | 타이틀·메뉴·버튼 |
| `data/fonts/Cafe24Ohsquare-v2.0/Cafe24Ohsquare-v2.0.otf` | 일시정지 제목 |
| `data/fonts/학교안심 운동장/HakgyoansimUndongjangOTFL.otf` | HIT·DAMAGE·이번 피해 숫자 |

Cafe24는 [공식 배포처](https://fonts.cafe24.com/)와 배포 패키지의 이용 조건, 학교안심 운동장은 [KERIS 공식 안내](https://copyright.keris.or.kr/wft/fntDwnldView?fntGrpId=GFT202312110000000000016)의 OFL·재배포 허용을 확인했다. 폰트별 `LICENSE.txt`에 저작권 고지와 SIL Open Font License 1.1 전문을 보관한다. Cafe24 원본 라이선스 PDF도 `docs/licenses/`에 유지한다.

## 역할과 출처

- `Cafe24OhsquareAir-v2.0/Cafe24OhsquareAir-v2.0.otf`: 메뉴 제목·소제목·본문·설명·버튼·순번의 비교 시안. 사용자 제공 폰트이며 [공식 Air 패키지](https://img.cafe24.com/csdstatic/freefonts/download/kr/Cafe24OhsquareAir-v2.0.zip)의 OTF와 바이트 일치를 확인했다. 동봉 안내는 `docs/licenses/License-OhsquareAir.pdf`다.
- `Cafe24Ohsquare-v2.0/Cafe24Ohsquare-v2.0.otf`: 일시정지 제목 전용 26px. Air보다 굵은 일반형이며 Bold라는 별도 굵기 파일을 지정한 것은 아니다. [공식 일반형 패키지](https://img.cafe24.com/csdstatic/freefonts/download/kr/Cafe24Ohsquare-v2.0.zip)를 2026-11-03 받아 원본 OTF를 사용하고 패키지와 바이트 일치를 확인했다. 동봉 안내는 `docs/licenses/License-Ohsquare.pdf`다.
- `학교안심 운동장/HakgyoansimUndongjangOTFL.otf`: HIT 숫자 76px·이번 피해 숫자 36px·누적 DAMAGE 숫자 60px. 사용자 제공 OTF 원본을 유지한다. 저작권자는 KERIS, 제작사는 디자인210이다.
- `s_core_dream/SCDream6.otf`(Bold): HUD의 TARGET 14px.
- `s_core_dream/SCDream5.otf`(Medium): 전투 HUD 제목·로드아웃 번호 14px·잔탄수 48px. 비사용 무기의 잔탄은 0.5배로 축소한다.
- `s_core_dream/SCDream4.otf`(Regular): 적 이름 18px·HUD 본문·버튼·설명·HIT/DAMAGE 레이블 18px.

`s_core_dream/`에는 SCDream2~6와 `LICENSE.txt`를 보관한다. [공식 배포처](https://s-core.co.kr/company/font/)의 `S-Core_Dream_OTF.zip` 원본 파일이다. 역할별 경로·크기는 `samples/ui_unit_test/ui_config.json`에서 설정한다. 이전 Cafe24 PRO Slim Fit·Max는 현재 UI에서 참조하지 않는다.

Unit Test Runner도 같은 역할을 적용한다. 실행기·소개 제목은 굵기가 더 있는 Cafe24 써라운드 일반형 20px, 목록·파일명·경로·소개·상태·오류는 SCDream4 Regular 18px다. 상단 버튼은 후속 요청으로 제거했다. 설정은 `Tools/unit_test_runner/theme.py`에 두고 프로젝트 폰트 원본을 직접 읽는다. Runner만 복사해 폰트가 없는 환경은 Pico2D 기본 글꼴로 대체한다. game2d의 SDL dummy 화면 추출로 글꼴 배치를 확인했으며 실제 데스크톱 직접 조작은 확인 전이다.

## 배포 범위와 확인 상태

사용자가 삭제한 이전 깍두기 도면체 4개 파일은 저장소에서도 제거한다. `.gitignore`는 현재 UI용 OTF·이용 조건의 지정 경로만 포함하며, 사용하지 않는 TTF·ZIP·기타 로컬 폰트는 제외한다. 폰트 바이너리는 수정·변환하지 않는다.

2026-11-03 현재 설정의 모든 폰트 경로·파일 존재, Cafe24 공식 OTF·라이선스 PDF의 바이트 일치와 커밋 대상 원본의 SHA-256을 대조했다. 실제 UI 실행·렌더링은 수행하지 않았다.
