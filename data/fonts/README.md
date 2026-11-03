# UI 테스트 폰트

현재 글꼴은 역할별로 분리한다. 크기·배치·색·카운터 효과는 기존 설정을 유지한다.

## 새 실행 환경의 준비

현재 Git에 포함된 S-Core Dream 외에 아래 OTF 3개를 프로젝트 기준 경로에 준비해야 한다. 이 파일들은 기존 제외 규칙에 따라 로컬에 보관하며, 저장소를 복제하는 것만으로 UI 테스트의 모든 폰트가 갖춰지지는 않는다. 시스템 글꼴 설치 대신 해당 경로의 파일을 직접 읽는다.

| 파일 경로 | 용도 |
| --- | --- |
| `data/fonts/Cafe24OhsquareAir-v2.0/Cafe24OhsquareAir-v2.0.otf` | 타이틀·메뉴·버튼 |
| `data/fonts/Cafe24Ohsquare-v2.0/Cafe24Ohsquare-v2.0.otf` | 일시정지 제목 |
| `data/fonts/학교안심 운동장/HakgyoansimUndongjangOTFL.otf` | HIT·DAMAGE·이번 피해 숫자 |

Cafe24 일반형은 아래 공식 패키지, Air는 같은 [공식 배포처](https://fonts.cafe24.com/)에서 준비한다. 학교안심 운동장은 사용자 제공 OTF를 사용한다. 내려받은 폰트에 동봉된 이용 조건도 함께 보관한다.

## 역할과 출처

- `Cafe24OhsquareAir-v2.0/Cafe24OhsquareAir-v2.0.otf`: 메뉴 제목·소제목·본문·설명·버튼·순번의 비교 시안. 사용자 제공 폰트이며 `docs/licenses/License-OhsquareAir.pdf`가 함께 있다.
- `Cafe24Ohsquare-v2.0/Cafe24Ohsquare-v2.0.otf`: 일시정지 제목 전용 26px. Air보다 굵은 일반형이며 Bold라는 별도 굵기 파일을 지정한 것은 아니다. [공식 배포처](https://fonts.cafe24.com/)의 [일반형 패키지](https://img.cafe24.com/csdstatic/freefonts/download/kr/Cafe24Ohsquare-v2.0.zip)를 2026-11-03 받아 원본 OTF를 사용한다. 동봉 라이선스는 `docs/licenses/License-Ohsquare.pdf`, 원본 ZIP은 `output/font-downloads/Cafe24Ohsquare-v2.0.zip`에 보관한다. 폰트 바이너리는 기존 data 제외 규칙을 유지한다.
- `학교안심 운동장/HakgyoansimUndongjangOTFL.otf`: HIT 숫자 76px·이번 피해 숫자 36px·누적 DAMAGE 숫자 60px.
- `s_core_dream/SCDream6.otf`(Bold): HUD의 TARGET 14px.
- `s_core_dream/SCDream5.otf`(Medium): 전투 HUD 제목.
- `s_core_dream/SCDream4.otf`(Regular): 적 이름 18px·HUD 본문·버튼·설명·HIT/DAMAGE 라벨.

`s_core_dream/`에는 SCDream2~6와 `LICENSE.txt`를 보관한다. [공식 배포처](https://s-core.co.kr/company/font/)의 `S-Core_Dream_OTF.zip` 원본 파일이다. 역할별 경로·크기는 `samples/ui_unit_test/ui_config.json`에서 설정한다. 이전 Cafe24 PRO Slim Fit·Max는 현재 UI에서 참조하지 않는다.

이전 깍두기 도면체의 출처는 [공식 저장소](https://github.com/dynamic-potato/kkakdugi-drafting)이며 현재 UI의 실행 조건이 아니다. 사용자 제공 로컬 폰트·공식 다운로드 폰트·기존 Git 포함 폰트는 구분한다. 폰트 바이너리는 원본을 유지하며 이번 Ohsquare 일반형도 Git에 추가하지 않았다.

2026-11-03 설정 경로를 읽어 파일 존재 여부를 확인했다. 실제 렌더링·화면 확인은 사용자 확인 전이다.
