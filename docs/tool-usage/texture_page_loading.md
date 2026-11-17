# 페이지별 병렬 압축 해제

`TexturePageWork` 한 개가 아틀라스 한 페이지의 파일 읽기·SHA-256 검사·압축 해제를 소유한다. `texture_page_work.py`는 SDL·OpenGL·창을 호출하지 않는다. 기존 Pico2D 로더의 GPU 생성·전송·캐시는 렌더러 소유 스레드에 유지한다.

## 소유권과 동기화

- Work 상태는 `pending → running → ready → consumed`이며 실패하면 `failed`가 된다. `Lock`은 실행 선점·상태·결과 소유권 교환에만 사용한다. 파일 읽기·해제 전체를 lock 안에 넣어 직렬화하지 않는다.
- `Future`가 완료·예외 대기를 담당한다. 완료된 페이로드는 `take_result()`로 한 번만 가져오고 Work의 버퍼 참조를 지운다. 같은 Work의 중복 실행·중복 결과 소비는 오류다.
- 기본 작업자 수는 4다. 실행 중인 Work와 완료 후 대기하는 Work를 합해 최대 4개를 준비한다. 다음 작업은 현재 페이지를 소비한 뒤 추가한다. 모든 페이지를 한 번에 풀어 보관하지 않는다.
- 각 Work는 별도의 압축 해제 상태를 사용한다. KTX 후보의 변환 객체도 Work별로 생성한다. 현재 게임 프로필은 `bc7_zlib`·`rgba_zlib`이고 일반 zlib 1.3.2를 사용한다. zlib-ng·zlib-rs는 연결하지 않았다.

## 캐시와 종료

`PicoMotionAtlas`는 이미 적재한 페이지와 같은 요청 내 중복 페이지를 CPU 준비 목록에서 제외한다. 기존 경로·해시 기반 공유와 참조 수 규칙을 유지한다. 결과는 요청 순서로 소비하므로 페이지 인덱스·프레임 참조를 바꾸지 않는다.

`AtlasTextureCache.acquire()`·`release()`는 렌더러 소유 스레드를 검사한다. Work 결과의 경로·해시·크기·코덱이 요청과 일치해야 전송한다. 압축 해제·전송·로딩 취소에 실패하면 대기 작업을 취소하고 실행 중 작업의 종료를 기다린 뒤, 이미 획득한 텍스처를 렌더 스레드에서 정리한다. zlib 내부의 한 페이지 해제를 중간에 강제로 끊지는 않는다.

기존 직접 `cache.acquire()` 호출도 같은 Work를 동기 실행해 사용할 수 있다. 비교 검증에서는 `PicoMotionAtlas`·`PicoAtlasSprite`의 `decode_workers=1`과 기본 4를 비교한다. 프로그램 import만으로 스레드·창을 만들지 않는다.

## 계측

공통 `TimingRecorder`의 `load.file_read`, `load.integrity`, `load.decode`는 각 Work의 경과 시간을 합산한다. 여러 스레드에서 겹치므로 이를 더해 로딩 시간으로 해석하지 않는다. `load.wait_prepared`는 소비 스레드가 다음 결과를 기다린 시간이고, `load.upload_complete`는 기존 GPU 전송 완료 대기를 포함한다. 실제 단축은 전체 아틀라스 준비·시작→첫 present 구간으로 확인한다.

`tests/automated/test_texture_page_work.py`는 독립 실행·동시 해제·단일 소유권·제한된 준비 수·손상 파일·실패 정리를 확인한다. 기존 `test_texture_comparison.SharedGpuCacheTests`는 실제 OpenGL에서 페이지 공유·보간 표시를 검증한다. 실제 성능·화면·미검증 범위는 [구현 기록](../ai-dev-log/2026-11-15-parallel-page-loading-target-spec.md)을 따른다.

페이지 단위 요청/상주 관리와 타일 단위 Page Table VT는 이번 구현에 포함하지 않는다. 현재는 모든 페이지를 시작 시 준비한다.
