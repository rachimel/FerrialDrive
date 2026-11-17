# 알파 전용 데이터 독립 시연

게임 에셋·저장 상태 없이 기본 도형 그림자의 알파를 반해상도로 준비한다. 원본 수치·도형 생성기는 기존 `samples/asset_loader/make_sample.py`를 재사용하며 작업 결과는 `output/samples/alpha_textures/`에 둔다.

프로젝트 루트에서 Python과 Pillow가 설치된 환경으로 실행한다. Pillow는 기존 `automate/runtime/texture_compare/python`에서도 찾는다.

```text
python automate/run.py alpha-textures --demo output/samples/alpha_textures
python automate/run.py alpha-textures --demo output/samples/alpha_textures --quality-profiles
```

공개 도형의 PNG·카탈로그와 `shadow.png.alpha8`을 생성한다. 기본 결과는 이미지 1장, 128×256 알파 32,768바이트와 80바이트 헤더다. 원본 256×512 PNG는 유지된다. `--scale 1`로 원해상도 131,072바이트와 비교할 수 있다. 이 명령은 실제 제작 함수를 사용하며 게임 창을 열지 않는다.

두 번째 명령은 같은 입력에 높음 50%·보통 25%·낮음 12.5%의 `.alpha8.x2/.x4/.x8` 파일을 만든다. 배율별 R8 데이터는 32,768/8,192/2,048바이트이며 헤더는 각각 80바이트다. 선택한 등급만 적재한다.

`python -m unittest tests.automated.test_alpha_data -v`로 알파값·원본 보존·변경 감지·손상 거부·저장 실패 보존을 검사한다. OpenGL 표시 비교는 [사용 안내](../../docs/tool-usage/alpha_textures.md)를 따른다.
