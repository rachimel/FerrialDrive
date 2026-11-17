# Blender 모델링·검사·렌더 파이프라인

현행 흐름은 **Blender 모델링 → Unreal 리깅·애니메이션 → `.blend` 반환 → 기존 파츠·레이어 분리·프리렌더·패킹**이다. [전체 역할·반환 계약](../../docs/ai-asset-pipeline/unreal_pipeline.md)을 먼저 확인한다.

형상·UV·재질 제작은 [디자인·제작 규칙](../../docs/ai-asset-pipeline/mech_design_rules.md)과 [모델 제작 흐름](../../docs/ai-asset-pipeline/model_workflow.md)을 따른다. [기본 도형 샘플](../../samples/model_pipeline/README.md)은 실제 메카나 게임 없이 실행한다.

## 현행 역할

- 모델링·UV·재질: `model_pipeline.py`, `model_operations.py`, `model_primitives.py`, `model_geometry.py`.
- 부위 형상·재질·장착 형상·식별 매핑: `model_design.py`, `model_design_schema.py`, `export_model_registry.py`. 기존 본 편집 기능은 호환 구현이며 새 리깅 경로로 사용하지 않는다.
- 독립 검사: `check_model_geometry.py`, `check_model_uv.py`, `check_model_images.py`, `check_model_collisions.py`.
- 반환 모델 이미지 확인: `model_pipeline.py`의 `review`, `model_review.py`. 동작의 별도 키포즈 승인 게이트로 사용하지 않는다.
- 출처/파일 관리: `catalog_history.py`, `inspect_model_dependencies.py`.
- 기존 게임 출력: `asset_build.py`, `render_asset_sample.py`, `pack_sprites.py`.
- 기존 표정 리그 전용: `host.py`, `mcp_client.py`, `build_portrait.py`. 메카의 현행 리깅과 구분한다.
