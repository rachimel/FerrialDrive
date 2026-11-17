# 두 관절 목표 포즈 계산 시연

직접 작성한 5cm 막대 두 개의 수치 데이터다. 게임 에셋·Unreal 설치 없이 Python 3 표준 라이브러리만 사용한다.

프로젝트 루트에서 실행한다.

```text
python automate/run.py unreal-plan --request samples/unreal_pipeline/pose_targets/request.json
```

`automate/workspace/pose_targets_demo/create.json`과 별도 목표 기록을 생성한다. 말단이 `[6,0,0]`에서 `[0,6,0]`으로 이동하고 돌아오며 본 길이는 유지된다. 기존 출력은 덮어쓰지 않는다. 재실행하려면 요청의 `output`을 새 작업 경로로 지정한다.

이 시연은 포즈 계산·요청 생성만 확인한다. `source_mesh`는 형식을 보여주는 식별자이며 실제 Unreal 에셋을 포함하지 않는다. 실제 호스트 생성·재생 검증과 구분한다.

`planted_request.json`은 같은 두 막대의 말단 점 `[7,0,0]`을 고정하고 끝 조각을 회전시키는 별도 수치 시연이다. 다음 명령으로 실행한다.

```text
python automate/run.py unreal-plan --request samples/unreal_pipeline/pose_targets/planted_request.json
```

`automate/workspace/pose_targets_planted_demo/create.json`을 생성한다. `hand_r` 이외의 말단에 component 기준 회전과 고정점을 지정하며, 말단 원점은 회전에 맞춰 이동한다. `tests/automated/test_unreal_pose_targets.py`는 같은 접촉점 유지와 막대 길이를 자동 검사한다.
