# 메카 디자인 편집기 기본 도형 시연

실제 메카 파일 없이 상자1개와 본1개로 부위 배율·단면 프로파일·재질 편집을 확인한다. Blender5.2에서 검증했다. 아래 경로는 FerrialDrive 프로젝트 루트 기준이다. `BLENDER`는 Blender 실행 파일로 바꾼다.

```text
BLENDER -b --factory-startup --python-exit-code 1 --python samples/mech_design/create_sample.py -- --output-dir output/mech_design_sample
BLENDER -b --factory-startup --python-exit-code 1 --python Tools/blender_pipeline/model_design.py -- --registry output/mech_design_sample/sample_registry.json --config output/mech_design_sample/sample_config.json --output output/mech_design_sample/sample_edited.blend
```

`sample_baseline.blend`는 원본 상자다. `sample_edited.blend`는 전후 폭10% 확대, 높이별 좌우 단면 변화, 거칠기0.65가 적용된 별도 결과다. 같은 이름의 출력이 있으면 덮어쓰지 않는다. 재시연할 때 새 출력 폴더를 지정한다. 두 결과의 실제 창 확인은 별도다.
