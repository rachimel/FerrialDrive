# 텍스처·공유 아틀라스 비교 시연

게임 에셋 없는 기본 도형 2클립을 실제 아틀라스 제작·인코딩·Pico2D 경로로 시연한다. `scene.json`이 보존 입력이며 제작 결과와 측정 JSON/PNG는 원본과 분리한다. 별도 프로세스에서 실행하며 Runner를 import하지 않는다.

## 환경

- 기존 Pico2D Python 3.11 환경과 OpenGL BC7 지원 GPU가 필요하다.
- `automate/requirements-texture-compare.txt`의 이미지 처리 패키지를 해당 환경 또는 `automate/runtime/texture_compare/python/`에 설치한다.
- 공식 KTX-Software의 실행 파일·DLL·라이선스는 `automate/bin/`에 보존한다. Oodle Texture는 보유한 SDK의 DLL을 참조하며 배포 파일에 복사하지 않는다.
- `config.example.json`의 필드를 실제 경로로 채워 Git 제외 대상 `automate/texture_compare.local.json`에 저장한다. 개발자 개인 경로는 샘플의 필수 입력이 아니다.

```text
python automate/run.py texture-compare --demo --output output/texture_comparison/demo_bundle
python tests/texture_compression_test.py --bundle output/texture_comparison/demo_bundle/comparison.json --benchmark
python tests/texture_compression_test.py --bundle output/texture_comparison/demo_bundle/comparison.json
```

독립 진입점은 `tests/texture_compression_test.py`, `UNIT_TEST_ENTRYPOINT="standalone"`이다. Runner에서 선택하거나 드롭해 실행할 수 있다. 기본 로컬 기체 후보가 없거나 `--demo`를 지정하면 기본 도형의 기존·공유 RGBA를 비교한다. NumPy와 Pillow가 필요하며 시연 데이터는 `output/texture_comparison/demo_runs/`에 생성한다. 압축 후보까지 비교하려면 위에서 준비한 `--bundle`을 지정한다. import만으로 창을 열지 않는다.

## 확인할 결과

- 기존 클립별 RGBA, 공유 원해상도 RGBA, 공유 반해상도 RGBA, 반해상도 KTX2→BC7, 반해상도 Oodle BC7, 원해상도 Oodle BC7, 75% Oodle BC7의 일곱 경우를 비교한다.
- 같은 기본 도형을 참조하는 두 클립은 색상·벡터 아틀라스를 공유한다. 같은 후보를 다시 acquire해도 추가 GPU 저장량이 0인지 보고서에 기록한다.
- `Tab`으로 측정표와 화면 비교를 전환한다. `1~6`로 후보, 좌우 화살표로 클립, `Space`로 재생/정지, `B`로 블러, `Z`로 실제 크기/2배, `C`로 1/8/32개 인스턴스를 선택한다. `,`/`.`는 위상을 이동하고 `Esc`로 종료한다.
- 측정과 해석의 범위는 [텍스처 비교 명세](../../docs/unit-tests/texture_compression.md)를 따른다. 기본 도형 통과는 실제 게임 에셋·전체 모션의 품질 승인과 구분한다.
