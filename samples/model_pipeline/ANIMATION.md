# 포즈 표본으로 애니메이션 저장

`Tools/blender_pipeline/animation_pipeline.py`는 에셋 JSON의 본 로컬 행렬·장착 앵커 로컬 행렬·장치 속성을 프레임마다 키로 저장한다. 원본 해시를 확인하고 새 폴더에만 출력한다. 일반 모델 생성 연산과 별개이며 메시·UV를 수정하지 않는다.

입력은 version=1, asset_id, source, source_sha256, fps, rig, root, clips다. 각 clip은 name, label, loop, samples, events를 갖는다. sample은 frame, bones(본 이름→4×4 matrix_basis), objects(객체 이름→4×4 matrix_basis), properties(객체 이름→속성 값)다. 이벤트 입력 frame은 클립 안의 0 기반 표본 번호다. 출력 clips.json에는 실제 Blender frame과 clip_frame을 함께 남긴다.

선택적인 setup_operations는 키를 저장하기 전에 공통 model_operations 연산을 적용한다. 반대손 장착 등 후보의 부모 변경과 지정된 운반 제약의 mute 상태를 재현할 때 사용한다. set_constraint_mute는 object, 선택적인 bone, constraint 이름, muted를 받는다. 없는 제약은 오류이며 다른 제약은 변경하지 않는다. 원본은 수정하지 않는다.

Blender 실행 인자는 `--background --factory-startup --python-exit-code 1 --python Tools/blender_pipeline/animation_pipeline.py -- --manifest <작업본 JSON> --output <새 폴더>`다. 저장 후 모든 표본의 본·앵커 행렬과 장치 속성을 재로딩해서 비교한다. 행렬 일치는 미술 품질·접지·전체 간섭의 증거가 아니다.

출력은 animations.blend, clips.json, export_configs/*.json이다. 표본 프레임은 CONSTANT 보간으로 저장하며 클립 사이 빈 프레임은 내보내지 않는다. 기존 Asset Loader의 **3D 렌더 → 출력 설정 불러오기**에서 모션별 설정을 선택한다. source_blend는 설정 파일 기준 상대 경로다. 기존 asset_build → render_asset_sample → pack_sprites → SpriteBundle 경로를 사용한다. 설정만 저장한 상태와 실제 전체 방향 출력 완료를 구분한다.

독립 시연은 Blender에서 `--background --factory-startup --python-exit-code 1 --python samples/model_pipeline/create_animation_sample.py -- <새 작업 폴더>`로 실행한다. 플레이어 에셋 없이 본 하나와 상자의 8fps 동작을 생성하고 재로딩을 검사한다. result/export_configs/sway.json을 툴에서 불러올 수 있다.

## 중간 이미지 확인

포즈 생성과 보정의 의미 있는 단계가 끝나면 model_pipeline.py에 생성된 animations.blend를 source로, operations=[]와 review를 지정해 검토 후보를 만든다. review.frames에는 준비/공격/회수 등 의도를 확인할 주요 표본 프레임을 명시한다. 고정 6면·확대/실제 표시 크기에서 AI가 손목·파지·몸통 회전·장갑 간섭을 직접 확인한 뒤 사용자에게 제시한다. 사용자 OK 이후 검토 후보를 다음 작업의 source/scene으로 사용한다. 정지 포즈 확인과 전체 재생·연속 궤적 검증은 구별한다.

팔 보정의 allow_shift 기본값은 false이며 해결되지 않은 표본은 requires_strategy_change로 기록한다. 목표 위치 이동은 명시적 true에서만 허용한다. 동작 생성의 weight_repair는 enabled=true가 있어야 실행한다. 최종 형상을 생략하는 simplified_preview는 기본 false이며, 간이 화면을 최종 외형 판정의 근거로 사용하지 않는다. 판단 기록과 중간 OK는 [모델 제작 흐름](../../docs/ai-asset-pipeline/model_workflow.md#이미지-검토와-중간-확인)을 따른다.
