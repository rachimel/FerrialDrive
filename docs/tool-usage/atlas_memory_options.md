# 아틀라스 용량과 무손실 채널 단축

현재 게임은 기본 이동·보간 아틀라스와 상·하체 자세표를 함께 사용한다. 설정 경로는 `samples/sword_movement/movement_config.json`의 `texture_quality_profiles`와 `upper_lower.catalog`다. 디스크 압축 크기, 저장 형식의 논리 페이로드, 실제 GPU 할당량, 프로세스 커밋을 구분한다.

## 현행 형식

- 기본 이동 색상은 기존 BC7 비트스트림을 그대로 유지한다. 벡터의 RGBA signed16 데이터도 그대로 유지한다.
- 자세표 색상 프레임은 RGBA를 유지한다. RGB가 모든 픽셀에서 0인 그림자만 알파 전용 `a8_zlib`로 분리·재패킹한다. GPU R8과 swizzle로 `(0,0,0,A)`를 복원한다.
- 에너지 마스크는 셰이더가 사용하지 않는 알파만 제거한 `rgb8_zlib`다. RGB·해상도·프레임 수·피봇·재생 정보는 유지한다. GPU RGB8로 적재한다.
- 프레임·페이지·클립 참조는 기존 로더 규약을 따른다. 클립당 채널별 최대 2페이지 제한을 검사한다. 검증된 후보는 기본 실행에 연결하고 원본을 보존한다.

## 현재 전체 묶음의 논리 페이로드

기본 이동과 자세표 전체 합계다. 실행 중 전부 상주한다는 뜻이 아니다. 재현 수치는 `output/performance/atlas_compact_20261117/summary.json`을 따른다.

| 품질 | 기존 MiB | 단축 MiB | 감소율 |
| --- | ---: | ---: | ---: |
| high | 9349.88 | 6698.98 | 28.35% |
| medium | 2838.53 | 2107.85 | 25.74% |
| low | 1186.90 | 851.85 | 28.23% |

GL 내부 형식은 조회해서 확인한다. RGB8의 드라이버 내부 정렬 때문에 논리 3바이트가 실제 VRAM 3바이트를 보장하지는 않는다. 원본을 보존한 후보 추가이므로 실제 디스크 여유 확보와도 구분한다.

## 제작·독립 검증

Python·NumPy로 동작하며 제작·검증 모듈 import는 창을 열지 않는다. 원본 경로에 덮어쓰지 않는다. 후보는 `data/runtime/`의 새 폴더를 사용한다.

```text
python automate/run.py atlas-compact prepare --catalog 원본_자세표/catalog.json --output 새_자세표_폴더
python automate/run.py atlas-compact verify --catalog 새_자세표_폴더/catalog.json --report output/performance/검증.json
python automate/run.py atlas-compact prepare --manifest 원본_BC7/atlas.json --output 새_기본아틀라스_폴더
python automate/run.py atlas-compact verify --manifest 새_기본아틀라스_폴더/atlas.json
```

`--catalog`는 자세표의 RGBA 색상/그림자를 분리한다. `--manifest`는 이미 BC7인 기본 색상을 재인코딩하지 않고 에너지 알파만 제거한다. 모든 새 페이지의 SHA-256과 원본 명세 해시를 보존한다. 별도 검증은 원본 RGBA 복원·에너지 RGB·프레임/클립/피봇·벡터 참조를 대조한다. 단축 후보를 다시 원본처럼 변환하지 않는다.

[게임 없는 최소 시연](../../samples/atlas_compact/README.md)과 `tests/automated/test_atlas_compact.py`를 제공한다. 실제 GPU 검사는 `FDRIVE_GPU_TESTS=1`로 선택한다. 고품질·중품질·저품질 실제 자세 화면의 필터링 반올림은 별도 픽셀 비교로 기록한다.

## 캐시와 남은 제한

자세표의 상주 예산은 코덱별 실제 논리 바이트를 사용한다. 단축 후 합계가 선적재 기준 아래로 내려가더라도 새로 전체 동작을 선적재하지 않도록 원본의 선적재 판정량을 보존한다. 기존보다 더 많은 동작을 시작부터 로딩하는 변경은 포함하지 않는다.

high 기본 이동 아틀라스에는 여전히 큰 RGBA 벡터 페이지가 있다. 채널 단축 후에도 2GiB 커밋 상한에서 압축 해제 버퍼 할당이 실패할 수 있으며 현재 실제 high 검증에서도 실패했다. 상한을 늘리거나 품질을 자동으로 낮추지 않는다. 중간/낮은 품질의 짧은 실행 완료를 장시간 60FPS 검증으로 확대하지 않는다.

추가 절감 후보는 필요한 클립/페이지 집합 정리, 색상 인코딩 정책, 벡터의 공간 해상도·정밀도다. 필요한 데이터 제외나 손실이 생기는 선택은 실제 표시와 동작을 검증한 뒤 결정한다.

## 에너지 R8에 대한 제약

현재 입력은 RGB가 같지 않고 페이지 전체의 지배 채널도 없다. 알파 제거와 RGB 보존은 `max(sample(mask).rgb)`를 유지한다. 각 픽셀의 RGB max를 먼저 계산한 R8은 일반적으로 같지 않다. 인접 RGB가 `(1,0,0)`과 `(0,1,0)`이면 중간점의 기존 max는 0.5지만, 미리 max한 R8의 보간값은 1이다. 해당 방식을 무손실 절감으로 사용하지 않는다.
