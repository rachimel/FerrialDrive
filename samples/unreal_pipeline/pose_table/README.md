# 상·하체 자세 표의 독립 수치 시연

게임 에셋·Unreal·창 없이 Python 표준 라이브러리로 실행한다. 직접 작성한 다섯 본의 수치 자료를 실제 제작 준비와 같은 `turn_pose` 함수로 변환한다.

프로젝트 루트에서 `python automate/run.py unreal-pose-table transform --request samples/unreal_pipeline/pose_table/sample.json`을 실행한다. 결과는 표준 출력이며 원본을 수정하지 않는다.

상체 +90°·하체 -90°에서 허리는 `[0, -1, 5]`, 오른손은 `[0, 1, 5]`, 무기는 `[0, 2, 5]`, 발은 `[0, -1, 0]` 근처가 된다. 손과 무기의 거리는 1cm다. 모델·파지 외관·실제 Unreal 저장/렌더 검증을 대체하지 않는다.
