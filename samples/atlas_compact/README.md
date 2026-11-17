# 아틀라스 채널 단축 독립 시연

게임 에셋·Unreal·개인 경로 없이 직접 작성한 수치 패턴으로 RGB가 0인 그림자와 여러 RGB 채널의 에너지 보존을 확인한다. Python·NumPy가 필요하며 CPU 제작·검증은 Pico2D 창을 열지 않는다.

```text
python samples/atlas_compact/make_sample.py --output output/atlas_compact_demo/source
python automate/run.py atlas-compact prepare --catalog output/atlas_compact_demo/source/catalog.json --output output/atlas_compact_demo/candidate
python automate/run.py atlas-compact verify --catalog output/atlas_compact_demo/candidate/catalog.json --report output/atlas_compact_demo/verification.json
```

원본과 후보 폴더는 분리한다. 기존 폴더에는 덮어쓰지 않는다. 후보 색상 페이지에 `rgba_zlib`·`a8_zlib`, 에너지에 `rgb8_zlib`가 생기고 검증 결과가 `pixels_equal=true`인지 확인한다. 해상도·피봇·클립·프레임 수는 유지한다. 실제 GPU R8/RGB8 저장과 렌더링 비교는 `FDRIVE_GPU_TESTS=1`의 `tests/automated/test_atlas_compact.py`로 별도 검사한다.
