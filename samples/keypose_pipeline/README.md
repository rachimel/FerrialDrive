# 기본 도형 키포즈 시연

게임 에셋 없이 작은 상자 리그를 만들고 공통 `keypose_pipeline.py`로 두 정지 자세를 저장·재로딩한다. Blender가 필요하다. 원본 도형과 제작 결과는 지정한 새 출력 폴더에서 분리된다.

```powershell
& $blender_exe --background --factory-startup --python-exit-code 1 --python samples/keypose_pipeline/create_sample.py -- --output output/keypose_sample/첫실행
```

결과는 `source.blend`, 숫자 요청 `request.json`, `keyposes/animations.blend`와 `clips.json`이다. 기본 지지 자세와 오른발 통과 자세를 타임라인의 1·2번에서 확인한다. 프레임 번호는 자세 ID이며 사이 동작과 타이밍은 없다. 도달 불가 목표는 자동으로 숨기지 않고 실패한다.

실제 메카의 외관·무기 파지·관절 가동 범위 검증은 이 시연과 별개다.
