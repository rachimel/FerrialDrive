# 자동 검사

이 폴더의 `test_*.py`는 실행기·드롭 처리·UI 부품의 자동 검사다. 직접 조작용 샘플은 상위 폴더의 `basic_flow.py`다.

프로젝트 루트에서 실행한다.

```text
python -m unittest discover -s tests/automated -v
```

검사 경로는 이동한 위치에 맞게 수정했다. 폴더 분리 후 검사는 실행하지 않았다.
