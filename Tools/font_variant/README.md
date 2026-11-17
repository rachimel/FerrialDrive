# HUD 숫자 폰트 수정본 생성

`build_hud_font.py`는 학교안심 운동장 OTF에서 숫자 0~9만 각지게 바꾸고 0의 사선을 제거한 별도 OTF를 만든다. **폰트 원본은 보존**한다. 수정본의 가족명과 내부 이름도 별도로 지정한다.

## 실행

프로젝트 루트에서 Python과 `requirements.txt`의 fontTools를 사용한다. 폰트 생성 시에만 필요한 의존성으로 UI 실행에는 필요하지 않다.

```text
python Tools/font_variant/build_hud_font.py
python Tools/font_variant/build_hud_font.py --check
```

입력은 `data/fonts/학교안심 운동장/HakgyoansimUndongjangOTFL.otf`, 출력은 `data/fonts/ferrial_hud_square/`다. 현재 기준 원본의 SHA-256이 다르면 생성을 중단한다. 숫자 0의 내부 공간은 이 원본의 좌표를 기준으로 작성했다. 다른 폰트나 개정 원본에 그대로 적용하는 범용 변환기는 아니다.

생성 후 문자 매핑·전체 글자 폭/사이드베어링·원본 저작권 고지와 숫자 외 윤곽 보존, 숫자 곡선 제거·0의 내부 공간 수를 확인한다. 원본 라이선스와 생성 해시·변경 글리프 기록도 출력 폴더에 저장한다.

확인은 형상·폰트 구조에 한정된다. 시각적 적합성은 실제 HUD 크기의 렌더링과 사용자 확인을 별도로 진행한다.

## 전체 윤곽·가로 확장본

`build_wide_font.py`는 위 숫자 수정본을 입력으로 한글·영문·기호의 곡선을 각진 직선 윤곽으로 바꾸고 **가로만 기본 1.20배** 확장한다. 기존 폰트는 보존하고 `data/fonts/ferrial_hud_square_wide/FerrialHudSquareWide-Regular.otf`로 저장한다. 가족명도 `Ferrial HUD Square Wide`로 구분한다.

```text
python Tools/font_variant/build_wide_font.py
python Tools/font_variant/build_wide_font.py --check
python Tools/font_variant/build_wide_font.py --width-scale 1.20 --bevel 0.35
```

`--bevel`은 둥근 모서리에 남길 사선의 상대 비율이다. 완전한 네모로 합쳐질 수 있는 `ㅇ`과 `ㅁ`을 구분하고 기존 사선 획은 보존한다. 복잡한 곡선은 적응적으로 직선 분할한다. 변환으로 외곽이 뒤집히거나 새 교차가 생기면 원래 윤곽을 더 촘촘히 따라가는 직선으로 처리한다. 글리프 간 복잡한 기호 17개도 보수적인 분할 정책을 적용한다. 기준 원본의 전체 문자 비교에서 정한 항목이며 범용적인 모든 폰트용 알고리즘이 아니다.

생성 후 모든 글리프의 순서·매핑·윤곽 수와 방향·가로 메트릭 비율·세로 메트릭·저작권 고지·0 사선 제거·곡선 제거를 확인한다. `manifest.json`에 배율·모서리 비율·기호 처리 항목·원본/생성본 해시를 기록한다. 기존 원본의 빈 글리프를 새 문자로 보충하지 않는다.

세로 배율·줄 간격은 유지한다. 가로 확장에 따른 UI 말줄임·카운터 최대 폭과 픽셀 크기별 가독성은 실제 렌더링에서 별도로 확인한다.
