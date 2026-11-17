# Heavy Whoosh 출처

[Heavy_whoosh_sound_122762022](https://freesound.org/people/Artninja/sounds/730774/) by [Artninja](https://freesound.org/people/Artninja/), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

- 게임에 사용하거나 배포할 때 위 제목·작성자·작품 링크·라이선스 링크와 가공 사실을 크레딧/동봉 고지에 포함한다.
- 가공: 앞부분 구간 선택, 길이·대역·시작/끝 포락선, 타수별 선택과 실행 중 재생률 변주.
- 원본은 공개 HQ MP3 표현이다. 원본 MP3·출처 페이지·해시는 로컬 `data/source/audio/sources/heavy_whoosh/`에 보존한다.
- 가공 WAV·로컬 선택 bank는 `data/runtime/audio/user_audio/heavy_whoosh/`와 상위 선택 bank에서 관리한다. 기본 CC0 샘플에 포함하거나 CC0로 재표기하지 않는다.

```text
python automate/run.py sound-sources --manifest samples/sound_effects/heavy_whoosh_sources.json --download
python automate/run.py sound-effects --recipe samples/sound_effects/heavy_whoosh_processing.json --output data/runtime/audio/user_audio/heavy_whoosh
```
