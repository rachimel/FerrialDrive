# CPU 추적 데이터 패킹 시연

Python 3.13과 프로젝트 소스를 사용한다. 샘플의 추적 좌표는 직접 작성한 값이다. 게임 창, 실제 에셋, Unreal은 필요 없다.

```powershell
python automate/run.py part-metadata-cache --track samples/part_metadata_cache/muzzle_tracks.json --output output/part_metadata_demo/muzzle.zip
$env:FDRIVE_PACKED_PART_METADATA = (Resolve-Path 'output/part_metadata_demo/muzzle.zip').Path
python -c "from ferrial_drive.rendering.part_metadata_archive import read_track_metadata; rows = read_track_metadata('samples/part_metadata_cache/muzzle_tracks.json')['tracks']['sample']; assert type(rows).__name__ == 'PackedTrackRows'; assert rows[1] == (0.125, 1.25, -2.5); print(rows[1])"
Remove-Item Env:FDRIVE_PACKED_PART_METADATA
```

첫 명령은 레코드 1개를 저장한다. 읽은 두 번째 표본은 `(0.125, 1.25, -2.5)`다. 다시 생성할 때는 새 출력 파일명을 지정한다.
