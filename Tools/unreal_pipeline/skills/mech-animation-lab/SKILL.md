---
name: mech-animation-lab
description: Unreal 메카의 FK 애니메이션 초안 작성과 FBX 왕복 실험.
license: MIT-0
metadata:
  dcc-mcp:
    dcc: unreal
    layer: domain
    version: "0.3.0"
    tools: tools.yaml
    tags: "unreal, animation, control-rig, fbx"
    search-hint: "mech animation lab FK Control Rig roundtrip export"
---

# 메카 애니메이션 실험

실험 프로젝트의 `/Game/MechLab`과 프로젝트 내 작업본만 사용한다.
`animation_lab`의 inspect로 호스트 API와 현재 상태를 확인한 뒤 새 초안을 만든다.
사용자의 키 편집 뒤에는 create_clip을 반복하지 않고 export_clip을 사용한다.
원본 Blender 파일과 기존 Unreal 에셋을 덮어쓰지 않는다.
새 리그 작업은 `rig_workspace`와 `automate/unreal/rig_workspace.py`를 사용한다.
입력은 리그 없는 형상이며 기존 Blender 본·웨이트·Constraint를 새 리그로 재사용하지 않는다.
프리렌더는 Unreal에서 수행하고 PNG 파츠+JSON을 기존 Asset Tool의 2D 조립·패킹에 인계한다. automate/unreal/prerender.py와 unreal.import를 사용한다. 기존 FBX 왕복은 호환용이다.
여러 동작은 새 메시·Actor·맵을 사용하는 batch 요청으로 분리한다.
create_batch_clip → inspect_batch → key_batch_clip → export_batch_clip 순서이며,
키 작성의 재시도는 거부한다. 반환 FBX와 편집 Sequence는 별개로 보존한다.
