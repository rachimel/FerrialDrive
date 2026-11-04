# Asset Load Test 명세

상태: **저장 장면 입력·엔티티 최소 경로 구현·실제 Blender 출력·자동 검사 8개·SDL dummy 재생 확인 / 직접 창 조작 미확인**

후속 요청으로 플레이어 기체의 로컬 저장 장면도 같은 경로에서 렌더했다. `--scene`은 입력 `.blend`를 읽고 별도 작업본을 저장/재로딩한 뒤 본체/그림자를 추출한다. 원본 장면은 수정하지 않는다. 입력 장면 해시로 캐시를 구분하고 `animation_name`을 동작명에 보존한다. 본체 조형·레퍼런스·전용 프리셋은 로컬에 보관하며 기본 샘플의 필수 데이터로 만들지 않는다.

사용자가 그림자의 스프레이 같은 노이즈를 지적해 기본 렌더를 본체 64 / 그림자 128 samples·denoise·광원 크기 0.6으로 조정했다. 실제 기체 초안은 본체 128 / 그림자 256·광원 0.45로 렌더하고 분리 그림자와 Pico2D 출력을 확인했다. 아래 8 samples는 최초 검사 시안의 이력이다.

2026-11-05 사용자 요청으로 `tests/asset_load_test.py`를 추가한다. 기존 UI·본편과 독립적으로, 합의한 3D→2D 파이프라인의 실제 생성·저장·로딩 여부를 확인한다. 실행 안내와 샘플은 [별도 샘플](../../samples/asset_load_test/README.md)에 둔다. 철회된 `combat_test.py`를 대신 구현하거나 전투를 연결하는 작업이 아니다.

## 첫 검증 범위

1. 기본 도형 메카와 짧은 다리 동작을 Blender에서 만든다.
2. 카메라·광원·애니메이션을 `.blend`로 저장한 뒤 다시 불러온다.
3. 정사영 3/4 시점과 같은 출력 배율로 8방향의 본체·그림자를 투명 PNG로 렌더한다.
4. 프레임을 고정 크기 격자 시트로 패킹한다. 크롭하지 않고 발 기준점을 보존한다.
5. 실제 PNG와 JSON을 Pico2D에서 불러와 8방향 재생·정지·프레임 이동·레이어 분리를 확인한다.

160px·4프레임·8 FPS·Cycles 8 samples는 AI가 첫 검사에 선택한 샘플 설정이다. 사용자가 확정한 게임 규격으로 취급하지 않는다. 렌더 자체는 Cycles CPU를 사용하며 그림자는 shadow catcher와 본체의 카메라 가시성 분리로 출력한다. 본체를 숨길 때 그림자 투영은 유지한다. 저해상도 노이즈를 최종 미술 품질로 승인하지 않는다.

## 책임과 데이터

| 위치 | 책임 |
| --- | --- |
| `samples/asset_load_test/` | 공개 가능한 기본 설정·설명. 실제 게임 이미지/모델과 분리 |
| `Tools/blender_pipeline/render_asset_sample.py` | 별도 Blender 안의 도형·동작·작업본 저장/재로딩·렌더 |
| `Tools/blender_pipeline/pack_sprites.py` | 프레임 RGBA 검사·패킹·기존 시트 도구 호환 JSON·번들 작성 |
| `Tools/SSheetCutil.py --pack-prerender` | 실제 시트 도구에서 같은 패킹 기능에 진입 |
| `Tools/blender_pipeline/asset_build.py` | Blender 탐색·별도 프로세스·로그·성공 결과 게시·취소 |
| `Tools/blender_pipeline/child_scope.py` | Windows에서 Runner가 테스트를 강제 종료해도 소유 렌더 자식을 정리 |
| `ferrial_drive/assets/sprites.py` | Blender/창과 무관한 JSON 검증·초 단위 재생 상태 |
| `ferrial_drive/assets/pico_sprites.py` | PNG 실측 크기 검사·텍스처 수명·그림자→본체 합성 |
| `tests/asset_load_test.py` | 자체 창·입력·렌더 진행·미리보기 연결. Runner를 import하지 않음 |

게임은 `SpriteBundle.load(bundle.json)`·`SpritePlayback`·`PicoSprite`를 직접 사용한다. `Tools`·테스트 실행부·Blender 연결은 런타임 필수가 아니다. import만으로 창·Blender 프로세스를 시작하지 않는다.

시트 JSON은 SSheetCutil v1의 `coordinates=bottom-left`, 이미지 경로/크기, 동작별 FPS, 프레임 `rect=[x,y,w,h]`, 영역 내부 `pivot=[x,y]`를 사용한다. 본체·그림자는 같은 FPS·프레임 영역·피봇을 가져야 한다. 번들의 방향은 `e/ne/n/nw/w/sw/s/se`이며 `walk/<방향>` 동작 이름으로 대응한다. 방향은 모델의 월드 XY 회전이다. 고정 카메라 투영으로 보이는 화면 각도까지 정확히 45도라는 뜻은 아니다.

새 프로세스에서 작성한 시트·JSON은 완성 번들로 읽고 실제 이미지 크기까지 검증한다. 실패한 렌더·패킹을 성공 결과로 게시하지 않는다. 실행마다 결과 폴더와 작업본을 분리한다. 최근 결과는 설정과 렌더/패킹 코드가 일치할 때만 재사용한다. 재생 전용 `--bundle`은 Blender를 찾지 않는다.

## 검사와 남은 일

- 자동 8개: 실제 RGBA 복사와 알파 보존·bottom-left 행 대응, 시간/FPS·방향·정지·프레임 반복, 이미지 누락/잘못된 영역/그림자 불일치 거부, 현재 설정·코드·입력 장면과 캐시 대응, 실패 시 마지막 성공 포인터 보존, 기존 SSheetCutil 읽기, 외부 작업 폴더 import 비실행, 사용자 지정 동작명 보존.
- 실제 Blender 5.2.3 LTS: 저장 작업본 재로딩 후 본체/그림자 총 64장·시트 2장 생성, 프레임별 비어 있지 않은 알파·투명 배경·유효 경계 검사 통과.
- Pico2D SDL dummy: 시트 로딩·8방향 전체/선택 확대/분리 그림자 화면, 다른 작업 디렉터리와 Blender가 없는 재생 경로 확인. 합성 키 이벤트로 방향 전환·정지·프레임 이동·레이어 토글을 확인했다.
- Windows 수명 관리: 별도 부모 프로세스를 강제 종료했을 때 소유한 대기 자식도 종료되는 것을 확인했다. 실제 Blender 생성 직후 취소 시 소유 프로세스 종료와 이전 성공 포인터 보존도 확인했다. Runner의 직접 조작과는 별도 검사다.
- 소스 검토와 자동 검사는 직접 조작·시각 승인과 구분한다. 실제 창의 클릭·키보드 반응·렌더 중 취소·다른 운영체제·다른 Blender 버전·GPU 성능은 추가 확인 대상이다.
- 첫 경로 밖의 범용 모델/리그 연결·여러 동작·고정/파괴물·맵 구역 합성/가림/통행 데이터는 미구현이다. [파이프라인 명세](../ai-asset-pipeline/blender_pipeline.md)의 후속 요구를 유지한다.
