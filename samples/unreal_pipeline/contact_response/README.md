# 메시 접촉 반응 시연

Unreal 5.8의 기본 상자로 접촉 분리·비접촉 0·경계 상자만 겹치는 경우·체적 포함을 확인한다. 게임 모델·이미지·리그는 필요하지 않다. 삼각형 접촉에 필요한 최소 힌지 회전을 계산하며 질량·관성·마찰을 사용하는 Chaos 시뮬레이션은 수행하지 않는다.

프로젝트 루트에서 실행한다. 템플릿을 작업 폴더로 복사하므로 샘플 원본에 Unreal 캐시를 만들지 않는다.

```powershell
New-Item -ItemType Directory -Force automate/workspace/contact_response_demo
Copy-Item samples/unreal_pipeline/contact_response/ContactLab.uproject automate/workspace/contact_response_demo/ContactLab.uproject
python automate/run.py unreal-animation --unreal "C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe" --project automate/workspace/contact_response_demo/ContactLab.uproject --request samples/unreal_pipeline/contact_response/request.json
```

결과는 `automate/workspace/contact_response_demo/result.json`이며 `passed: 4`와 Unreal 버전을 확인한다. 엔진 설치 경로는 환경에 맞춘다. 같은 보고 파일은 덮어쓰지 않으므로 재실행은 새 작업 폴더·보고 경로를 사용한다. 화면 없는 네이티브 API 검사이며 실제 애니메이션의 재생·외관 검수와 구분한다.

실제 독립 시연 확인: 빈 `ContactLab` 프로젝트에서 Unreal 5.8 네이티브 4항목을 통과했다. 메카 에셋이 있는 기존 프로젝트의 검사와 별개다. GUI 조작 시연은 수행하지 않았다.
