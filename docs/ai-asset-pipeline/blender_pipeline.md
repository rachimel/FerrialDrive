# Blender 모델링·검사

## 역할과 제작 순서

**Blender 모델링 → 리그 없는 형상 → Unreal 새 리깅·애니메이션·프리렌더 → PNG 파츠+JSON → 툴 2D 조립·패킹 → Pico2D** 흐름을 사용한다. 프리렌더는 Unreal에서 수행하고 PNG 파츠+JSON을 툴의 2D 조립·패킹으로 인계한다.  [Unreal 제작·인계 흐름](unreal_pipeline.md)과 [동작 재생 검수](animation_workflow.md)를 따른다.

Blender는 모델링·UV·재질, 교환/반환 파일의 변환·검사·렌더를 담당한다. Pose Tool과 Blender의 키포즈·모션 생성/보정은 현행 제작에서 제외한다. 기존 코드와 기록은 보존하며 새 제작의 진입점으로 안내하지 않는다.

## 모델 제작

- 메카 조형은 [디자인·제작 규칙](mech_design_rules.md), 실행은 [모델 제작 흐름](model_workflow.md)을 따른다. 큰 실루엣·장갑 비율·연결·무기 장착 영향을 먼저 확인한다.
- 플레이어 기준은 로컬 `data/source/models/player_mech/release_v1.json`의 **1차 최종 플레이어 모델 v078**이다. 경로·해시·승인 범위를 확인하고 별도 후보에서 작업한다. 기존 골격·기존 실험 소스가 새 Unreal 리그의 확정 규격은 아니다.
- `automate/run.py model`에서 `Tools/blender_pipeline/model_pipeline.py`와 에셋별 JSON을 재사용한다. 모델 버전마다 Python을 복제하지 않는다. 형상·UV·이미지·간섭 검사는 독립 실행한다.
- `model_design.py`·`model_design_schema.py`·`export_model_registry.py`는 부위 형상·프로파일·재질·장착 형상과 부품 매핑에 사용한다. 기존 본 편집 기능을 새 리깅 경로로 사용하지 않는다.
- 실제 게임 에셋 없이 [모델 샘플](../../samples/model_pipeline/README.md)과 [부위 편집 샘플](../../samples/mech_design/README.md)로 해당 기능을 확인한다.

## 2D 파츠 인계

- Unreal에서 프리렌더한 PNG 파츠+JSON을 기존 툴로 인계한다. 3D 부착·파지·가림은 Unreal의 책임이다.
- `unreal.import`로 시트·메카 묶음을 만들고 기존 파츠·레이어·상태·프레임 편집·패킹·Pico2D 로더를 재사용한다.
- Unreal 렌더 규약은 [제작·인계](unreal_pipeline.md)를 따른다.

## 공통 렌더 기준

- 캐릭터·맵의 고정 정사영 3/4 카메라, 전방/상방 축·단위, 월드 단위당 출력 픽셀, 광원·색 관리·렌더 엔진을 설정으로 관리한다. 기체마다 출력 배율을 임의 변경하지 않는다.
- 움직이는 엔티티는 동작별 프레임·FPS·반복·8방향 대응·지면 기준점을 지정한다. 본체·그림자와 색상·에너지 마스크는 같은 프레임·방향·카메라·크기·기준점을 사용한다.
- 대표 방향을 실제 게임 표시 크기에서 확인하고 같은 설정으로 전체 출력한다. 승인 뒤 설정이 바뀌면 영향을 받는 결과를 다시 확인한다.
- 프레임 크롭 여부와 관계없이 기준점·크롭 오프셋을 보존한다. 모델·그림자 잘림, 투명 경계와 방향별 위치 흔들림을 검사한다.
- 최종 카메라 수치·이미지 크기·맵 구역 크기·세부 형식처럼 미정인 항목을 임의 확정하지 않는다.


## 기존 표정 리그 전용 경로

`host.py`·`mcp_client.py`·`build_portrait.py`는 기존 표정 스튜디오의 눈·입 리그 생성 경로다. 메카의 현행 Unreal 리깅과 구분한다. 생성 입력은 `data/source/portrait_editor/inputs/`, 리깅 원본·텍스처는 `data/source/portrait_editor/rig/`를 사용한다.

```powershell
.\.venv-capability-test\Scripts\python.exe Tools\blender_pipeline\mcp_client.py --script Tools\blender_pipeline\build_portrait.py
```

연결된 장면을 비우므로 사용자 편집 장면과 분리된 Blender 인스턴스를 사용한다. 미리보기·로그는 `output/blender_pipeline/`에 둔다.

과거 프리렌더 설계·검사 시점은 [개발 기록](../ai-dev-log/README.md)에 보존한다. 현행 역할은 이 문서와 Unreal 제작·반환 명세를 우선한다.
