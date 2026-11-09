# JSON 모델 제작 샘플

에셋별 Python 파일 없이 두 기본 도형을 만들고 저장·재로딩·정면/후면/사선 512px·192px 검토 렌더를 출력한다. Blender 내장 Python만 필요하며 실제 메카/Pico2D는 필요 없다.

프로젝트 루트에서 `$blender_exe`를 설치된 Blender 실행 파일로 지정한다. 출력 폴더/검사 JSON은 기존 파일을 덮어쓰지 않으므로 매 실행 새 이름을 사용한다.

```powershell
& $blender_exe -b --factory-startup --python-exit-code 1 --python Tools/blender_pipeline/model_pipeline.py -- --manifest samples/model_pipeline/manifest.json --output output/model_pipeline/demo_run
```

`candidate.blend`, `request.json`, `report.json`과 검토 PNG 6장이 생긴다. 보고서의 `candidate_unchecked`는 제작 후보이며 품질 검사/사용자 승인은 아직 수행하지 않았다는 뜻이다.

필요한 검사를 각각 실행한다. 한 파일이 나머지 검사를 호출하지 않는다.

```powershell
& $blender_exe -b --factory-startup --python-exit-code 1 --python Tools/blender_pipeline/check_model_geometry.py -- --source output/model_pipeline/demo_run/candidate.blend --settings samples/model_pipeline/checks_geometry.json --output output/model_pipeline/demo_run/geometry.json
& $blender_exe -b --factory-startup --python-exit-code 1 --python Tools/blender_pipeline/check_model_uv.py -- --source output/model_pipeline/demo_run/candidate.blend --settings samples/model_pipeline/checks_uv.json --output output/model_pipeline/demo_run/uv.json
& $blender_exe -b --factory-startup --python-exit-code 1 --python Tools/blender_pipeline/check_model_images.py -- --source output/model_pipeline/demo_run/candidate.blend --settings samples/model_pipeline/checks_images.json --output output/model_pipeline/demo_run/images.json
& $blender_exe -b --factory-startup --python-exit-code 1 --python Tools/blender_pipeline/check_model_collisions.py -- --source output/model_pipeline/demo_run/candidate.blend --settings samples/model_pipeline/checks_collisions.json --output output/model_pipeline/demo_run/collisions.json
```

도형은 기본 UVMap을 사용하며 텍스처 이미지는 없다. 검사 실패 예시는 테스트에서 겹치는 도형·잘못된 UV·과대/미패킹 이미지를 만들어 확인한다.

```powershell
& $blender_exe -b --factory-startup --python-exit-code 1 --python tests/blender/test_model_pipeline.py
```

이 마지막 명령은 도구 개발용 회귀 테스트다. 실제 에셋 제작에서 품질 검사를 한 파일로 묶어 실행하는 경로가 아니다. 새 에셋에는 manifest의 source/해시/역할별 객체명/operations와 별도 검사 설정만 바꾼다.

## PBR 표면과 UV 패널

실제 게임 에셋이나 외부 다운로드 없이 기본 상자와 직접 생성한 명도 맵으로 실행한다. Blender 내장 NumPy를 사용한다. 새 출력 폴더를 지정한다.

```powershell
& $blender_exe -b --factory-startup --disable-autoexec --python-exit-code 1 --python samples/model_pipeline/pbr_surface_demo.py -- --output output/model_pipeline/pbr_demo
```

PBR 맵·UV 패널 도안과 `sample.blend`를 출력한다. 형상/UV 보존, 발광 연결 보존, 반복 적용 시 노드 중복 방지, 저장·재로딩을 확인한다. 시각적 품질 승인이나 실제 메카의 패널 왜곡 검증을 대신하지 않는다.
