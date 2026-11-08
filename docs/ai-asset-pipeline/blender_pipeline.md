# Blender 에셋 제작 경로

## 현재 모델 제작 진입점

메카 제작은 [디자인·제작 규칙](mech_design_rules.md)의 실용적 구조, 승인 실루엣 보존, 장착 호환성 및 변경 전후 검증 기준을 따른다. 기준 플레이어의 외형을 다른 기체의 의무 양식으로 복제하지 않는다.

새 모델/수정은 [모델 제작 파이프라인 1차](model_workflow.md)를 따른다. 공통 모듈과 에셋별 JSON을 재사용하며 버전별 Python 복제를 피한다. 형상·UV·이미지·간섭 검사는 독립 실행 파일로 분리한다. [기본 도형 샘플](../../samples/model_pipeline/README.md)에서 실제 모델 없이 실행한다.

플레이어 기준은 **1차 최종 플레이어 모델 v078**이며 현재 파일은 `data/models/player_mech/player_mech.blend`다. 구버전 모델/출력물은 승인받아 정리했다. 아래 초기 계획/구현 기록은 당시 범위의 참고 정보이며 현재 구현/미구현 구분은 위 1차 안내를 우선한다.

소스 위치: `Tools/blender_pipeline/`. 실행 명령은 프로젝트 루트 기준이다.

현재 캐릭터 리깅을 다시 생성할 때 사용하는 세 모듈이다. 에디터 실행에는 필요하지 않다.

- `host.py`: 별도 Blender 인스턴스에서 Blender MCP 애드온을 실행한다.
- `mcp_client.py`: 실제 MCP stdio 서버를 통해 연결된 Blender에 명령을 보낸다.
- `build_portrait.py`: 현재 눈·입 리그와 `blender-keyforms.json`을 생성한다.

Blender의 테스트용 인스턴스에서 `--factory-startup --python Tools/blender_pipeline/host.py`로 호스트를 시작한 후 실행한다.

```powershell
.\.venv-capability-test\Scripts\python.exe Tools\blender_pipeline\mcp_client.py --script Tools\blender_pipeline\build_portrait.py
```

생성기는 연결된 장면을 비우므로 편집 중인 사용자 장면과 분리된 인스턴스를 사용한다.
생성 입력은 `data/portrait_editor/inputs/`, 리깅 원본·텍스처·Blender 파일은 `data/portrait_editor/rig/`에 보관한다. 원본 위치는 현재 프로젝트 기준으로 계산하며, MCP 실행에서도 스크립트의 `__file__`을 명시한다.

미리보기 이미지는 `output/blender_pipeline/previews/`, 호출 기록은 `output/blender_pipeline/`에 저장한다. 과거 데모·성능 진단·이전 리그 생성기는 삭제했다.
