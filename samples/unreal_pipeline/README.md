# Unreal 프리렌더와 파츠 조립 시연

실제 메시 접촉 제어의 에셋 없는 기본 도형 검사는 [접촉 반응 시연](contact_response/README.md)을 사용한다.

게임 에셋 없이 기본 상자 두 개를 Unreal에서 렌더하고 기존 Asset Tool의 메카 묶음으로 패킹한다. 기존 골격 왕복 샘플은 아래에 호환 기록으로 보존한다.

## 현재 시연 실행

환경: Unreal 5.8, Python 3.11+, Pillow(이미지 패킹). 프로젝트 루트에서 실행한다. `--unreal`에는 실제 UnrealEditor.exe 경로를 지정한다.

```powershell
python -m pip install --target automate/runtime/image/python -r automate/requirements-image.txt
python automate/run.py unreal-render --unreal "C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor.exe" --project automate/workspace/prerender_host/PrerenderLab.uproject --request samples/unreal_pipeline/prerender_request.json --demo
```

`--demo`는 프로젝트가 없을 때 새 빈 automate/workspace 폴더에 제공 템플릿과 설정을 복사한다. 시연은 일반 Unreal 프로세스와 MRQ를 사용한다. `-RenderOffscreen`은 현재 확인한 5.8 펜 입력 플러그인 충돌 때문에 사용하지 않는다. 이미 있는 출력 폴더는 거부하므로 재실행할 때 요청의 output을 새 경로로 바꾼다.

성공 결과는 `output/unreal_prerender_demo/validated/manifest.json`이다. 파츠 PNG와 전체 참조 PNG가 별도로 남는다. 다음 JSON을 automate/workspace의 요청 파일로 저장하고 실행한다.

```json
{"version":1,"operation":"unreal.import","source":"../../output/unreal_prerender_demo/validated/manifest.json","output":"../../output/unreal_prerender_demo/new_bundle"}
powershell
python automate/run.py asset --request automate/workspace/import_demo.json
```

결과 `new_bundle/mech.json`을 기존 Asset Tool에서 열어 메카 설정의 파츠·순서·프레임을 편집한다. GUI를 새로 만들지 않는다. 자동화는 `plan.create`로 작업본을 만든 뒤 `plan.update/validate/export`를 사용한다. 자동 검사와 직접 GUI 조작 확인을 구분한다.

이 도형은 파츠별 색·알파·가림·기준점·시트 좌표와 기존 로더 연결 확인용이다. 실제 메카의 애니메이션·파지·장갑 간섭·접지 품질의 완료 증거가 아니다. 그림자 전용 패스는 아래 별도 샘플로 확인한다. 현재 샘플 두 프레임은 정지 도형이다.

## 지면 그림자 독립 시연

```powershell
python automate/run.py unreal-render --unreal "C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor.exe" --project automate/workspace/prerender_host/PrerenderLab.uproject --request samples/unreal_pipeline/shadow_request.json --demo
```

게임 에셋 없이 기본 상자·중성 바닥·조명을 생성한다. `output/unreal_shadow_demo/manifest.json`은 body·weapon·shadow 3개 파츠다. `shadow/*.png`의 RGB는 검정이고 알파만 그림자 농도를 가진다. `shadow_reference`와 수신면은 진단 입력이다. 고정된 동일 캔버스와 계산한 월드 원점 기준점을 사용한다. 두 프레임의 도형은 정지 상태다. 기존 출력 폴더는 거부하므로 재실행 시 요청 사본에서 output을 바꾼다. 같은 `unreal.import` 경로로 패킹한다. GUI 직접 조작은 사용자가 확인한다.

---

## 보관된 형상/기존 골격 교환 시연

# Unreal 왕복 경로의 기본 도형 샘플

> 현행 방향은 리그 없는 Blender 형상 → Unreal 새 리그·애니메이션이다. 프리렌더는 Unreal에서 수행하고 PNG 파츠+JSON을 툴의 2D 조립·패킹으로 인계한다.  아래 기존 골격 교환 샘플과 새 리그 샘플의 범위를 구분한다. [인계 조건](../../docs/ai-asset-pipeline/unreal_pipeline.md)을 따른다.

## 새 리그용 최소 형상

`fresh_rig_geometry_request.json`은 기본 상자 3개를 만들고 본·웨이트·Constraint가 없는 FBX와 부품 정보를 `automate/workspace/fresh_rig_sample/geometry/`에 출력한다. Blender를 프로젝트 루트에서 다음 인자로 실행한다.

```powershell
blender --background --python automate/unreal/model_source.py -- --request samples/unreal_pipeline/fresh_rig_geometry_request.json
```

기존 결과를 덮어쓰지 않는다. 같은 요청을 다시 실행하려면 새 출력 경로를 사용한다. 새 골격·웨이트·FK 장면은 `automate/unreal/rig_workspace.py`의 작업 요청으로 Unreal 안에서 생성한다. 샘플 형상 생성·새 Skeleton/Skeletal Mesh 생성·제어점 API 선택을 확인했으며, 화면 직접 조작과 전체 출력 경로 검증은 구분한다.

## 기존 골격 교환 샘플

게임 에셋 없이 세 본과 상자 세 개를 만들고 공통 FBX 출력 경로를 실행한다. `Chest`의 하위 본 `Arm.L`로 점이 포함된 이름의 가중치 변환과 부모 회전 전달을 확인한다.
직접 작성한 도형·수치만 사용하며 외부 이미지·모델이 필요하지 않다.

- 환경: Blender 5.2 계열. Unreal 단계는 Unreal 5.8과 로컬 MCP 연결이 필요하다.
- 프로젝트 루트에서 실행한다. `blender` 대신 설치된 Blender 실행 파일의 절대 경로를 사용할 수 있다.

```powershell
blender --background --factory-startup --python-exit-code 1 --python Tools/unreal_pipeline/blender_transfer.py -- --request samples/unreal_pipeline/sample_request.json
```

- 결과: `output/unreal_pipeline_sample/sample.blend`, `transfer/mech.fbx`, `transfer/transfer_map.json`.
- 확인: 메시 3개, 원래 본 3개와 이동 기준 본 1개가 출력된다. 샘플 요청 원본은 변경하지 않는다.
- 이미 결과 폴더가 있으면 다른 output 경로를 지정한 요청 사본을 사용한다.
- 현재 독립 시연 확인 범위는 기본 도형 생성과 FBX 출력이다. 샘플을 별도 Unreal 프로젝트에 가져와 수동 편집하고 반환하는 시연은 미검증이다. 실제 메카 실험의 확인 결과와 구분한다.


## 독립 객체 제어 샘플

같은 명령에서 요청을 `object_control_request.json`으로 바꾸면 팔에 붙은 기본 상자 소품을 추가한다. 게임 에셋·개인 경로를 요구하지 않는다.

- 출력: `output/unreal_object_control_sample/`. 원본 요청은 유지하며 재실행할 때 새 출력 경로의 요청 사본을 사용한다.
- 확인할 결과: 메시 4개, 원래 본 3개 + 교환 루트 1개 + `FD_Prop` 1개. `transfer_map.json`의 `object_controls`가 `SampleProp`과 `FD_Prop`을 연결한다.
- 확인 상태: 실제 Blender 5.2.3에서 기본 도형·교환 blend·FBX 출력을 확인했다. 이 샘플의 독립 Unreal 수동 편집·반환 시연은 미검증이다.
