# Blender 원본 생성 경로

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
