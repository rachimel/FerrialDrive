# Ferrial HUD Square

학교안심 운동장을 바탕으로 만든 **프로젝트용 숫자 수정본**이다. 원본 제작처의 공식 변형판을 뜻하지 않는다.

후속 전체 윤곽·가로 확장 요청은 별도 [Ferrial HUD Square Wide](../ferrial_hud_square_wide/README.md)에서 처리한다. 이 파일은 이전 비교본과 Wide 생성 입력으로 보존하며, 현재 전투 HUD 설정은 Wide를 참조한다.

- 원본: `../학교안심 운동장/HakgyoansimUndongjangOTFL.otf`. 원본 파일은 수정하지 않는다.
- 원본 저작권: Copyright © KERIS. All rights reserved. 제작사는 디자인210.
- 수정: ASCII 숫자 0~9의 둥근 모서리를 직각으로 바꾸고, 0의 두 내부 삼각형을 단일 직사각형 공간으로 합쳐 사선을 제거한다.
- 유지: 숫자 외 12,604개 글리프의 윤곽, 문자 매핑, 전체 글자 폭·사이드베어링, 원본 저작권 고지.
- 수정본 식별: 가족명 `Ferrial HUD Square`, PostScript 이름 `FerrialHudSquare-Regular`.
- 이전 시안의 사용처: HIT 숫자 76px·누적 DAMAGE 숫자 60px·개별 피격 피해 숫자 36px, 전투 제목 42px·TARGET 14px·표적명/카운터 레이블 18px·HUD 본문 20px·작은 이름표 16px. **이 숫자 수정본의 한글·영문 윤곽은 원본과 동일**하며, Wide는 별도 사본에서 전체 윤곽을 변경한다.
- 이용 조건: 원본의 SIL Open Font License 1.1을 승계하며 저작권 고지와 전문을 `LICENSE.txt`에 보관한다.
- 재생성: [숫자 수정본 생성 도구](../../../Tools/font_variant/README.md). 원본/생성본 해시와 변경 글리프는 `manifest.json`을 따른다.

형상·메트릭 보존 검사와 Pillow/실제 Pico2D(SDL dummy) 렌더링을 확인했다. 실제 창에서의 사용자 시각 승인과 구분한다.
