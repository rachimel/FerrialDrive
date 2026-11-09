# Blender 에셋 파이프라인

메카 작업은 먼저 [디자인·제작 규칙](../../docs/ai-asset-pipeline/mech_design_rules.md)을 읽고 수정 범위·장착 영향·검증 대상을 정한다.

새 작업은 [모델 제작 흐름](../../docs/ai-asset-pipeline/model_workflow.md)을 따른다. [기본 도형 샘플](../../samples/model_pipeline/README.md)은 실제 메카나 게임 없이 JSON만으로 실행한다.

애니메이션은 [애니메이션 제작 흐름](../../docs/ai-asset-pipeline/animation_workflow.md)에 따라 AI 키포즈 후보 제시·사용자 검수·AI 수정으로 키포즈를 확정한 뒤 사이 동작을 연결한다. 연결된 동작의 타이밍과 중간 자세는 별도로 검수한다.

- 제작: `model_pipeline.py`, `model_operations.py`, `model_primitives.py`, `model_geometry.py`.
- 부위/본/재질/장착 편집: `model_design.py`, `model_design_schema.py`, `export_model_registry.py`.
- 독립 검사: `check_model_geometry.py`, `check_model_uv.py`, `check_model_images.py`, `check_model_collisions.py`.
- 동작 초안·보정·출력·미리보기: `motion_blocking.py`, `pose_refinement.py`, `animation_pipeline.py`, `build_motion_preview.py`.
- 출처/파일 관리: `catalog_history.py`, `inspect_model_dependencies.py`.
- 기존 게임 출력: `asset_build.py`, `render_asset_sample.py`, `pack_sprites.py`.
- 기존 표정 리그: `host.py`, `mcp_client.py`, `build_portrait.py`.

새 모델/버전마다 `.py`를 만들지 않는다. 에셋별 데이터는 `workspace/<asset_id>/`의 JSON에 두고, 필요한 일반 기능만 공통 모듈에 추가한다. 검사는 제작에 묶지 않고 각각 실행한다. `workspace/`의 특정 메카 버전을 공통 코드에서 import하지 않는다.
