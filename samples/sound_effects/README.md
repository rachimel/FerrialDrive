# 이동·전투 효과음

## 검 금속 피격음

로컬 `hit_metal`은 사용자 지정 `data/source/audio/sources/hit/metal/floraphonic-metal-hit-10-193281.mp3`를 직접 재생한다. 사건 음량 0.8·최소 간격 0.06초·`replaces_hit: true`를 사용한다. 원본의 구간·피치·음량을 가공하지 않으며 일반 명중 `hit`와 중첩하지 않는다. 별도의 총 피탄·도탄 사건은 기존 연결을 사용한다. 실행 시 bank를 읽으므로 실행 중인 프로그램에는 다시 시작한 뒤 적용한다.

준비: `python automate/run.py sound-import --source data/source/audio/sources/hit/metal/floraphonic-metal-hit-10-193281.mp3 --kind hit_metal --preserve-source --event-volume 0.8`. 출처·해시는 로컬 `data/runtime/audio/user_audio/hit_metal_source.json`에 보존한다. 개별 출처·라이선스는 파일명만으로 확정하지 않는다. 이전 bank는 `data/source/audio/revisions/20261117_194755_metal_hit/bank_before.json`에 보존했다.

`python automate/run.py sound-preview --only contact --channels 48 --output output/audio/metal_hit_mp3_20261117`로 단발·반복 금속 명중의 실제 믹서를 확인했다. 클리핑·레이어 누락은 없었으며 실제 장치 청취·사용자 음색 승인은 별도다.

## Overdrive 국소 폭발음

`data/source/audio/sources/smg/energy_explosion(GEN_3).mp3`의 앞 0.05초를 제외한 WAV를 `gun_explosion`으로 재생한다. 원본은 보존하며 기존 import의 peak 0.58 정규화·앞 3ms/끝 15ms 페이드를 적용한다. 출력은 약 1.938초다. 실제 탄환의 폭발 속성에 따라 폭발 VFX 생성 직후 재생하므로 Overdrive 종료 뒤 도착한 탄환도 소리를 낸다. 폭발하는 명중은 기본 피탄음·금속음을 겹치지 않고 폭발음만 사용한다. 발사음과 일반 탄환의 명중음은 유지한다. 일반 탄환·빗나감·빈 탄창에는 폭발음이 없다. 소리는 최소 0.06초 간격, 사건 음량 0.4를 사용한다.

준비: `python automate/run.py sound-import --source "data/source/audio/sources/smg/energy_explosion(GEN_3).mp3" --kind gun_explosion --start-seconds 0.05 --event-volume 0.4`. 원본 해시·구간·가공 방식은 로컬 `data/runtime/audio/user_audio/gun_explosion_source.json`에 저장한다. `gun_explosion.follow_rate_multiplier=false`로 Overdrive의 전역 피치 배율을 제외해 원래 피치·속도로 재생한다. 앞부분 자르기·정규화·페이드는 적용된 준비 음원이며 무가공 원본 직접 재생과 구분한다.

혼합 확인: `python automate/run.py sound-preview --only gun-explosion --channels 48 --output output/audio/energy_explosion_review/explosion_only`. 단발 폭발음과 초당 30발 발사+폭발 WAV/보고서를 기록한다. 전역 Overdrive Pitch 배율은 켜되 폭발음에는 적용하지 않는다. 녹음은 실제 장치 청취·최종 사용자 음색 승인을 대신하지 않는다.

## 피탄음 묶음 구간 추출

`sound-effects`의 `processor: "extract_region"`은 `source`·`start_seconds`·`end_seconds`로 원본 구간을 추출한다. 피치·길이를 보간하지 않으며 `peak`(기본 0.58)·`fade_in_seconds`(기본 0.0005)·`fade_out_seconds`(기본 0.008)만 적용한다. 구간·피크·페이드는 유한값이어야 하며 페이드 합계가 구간 길이를 넘으면 거절한다. 원본 폴더의 `source.json` 출처 검사는 기존 제작과 같다.

현재 로컬 SMG 음원은 `data/runtime/audio/user_audio/smg_impacts_v1/`의 금속 피탄 6개·도탄 4개다. 실제 총탄 명중마다 `gun_hit`에서 피탄 6종 중 하나를 선택하고, `metal`·`steel` 표적에는 `gun_hit_metal`에서 도탄 4종 중 하나를 추가한다. 각 레이어의 직전 후보를 제외하며 새 음원의 재생률 변주는 사용하지 않는다. 로컬 bank의 기본 피탄 음량은 1.4, 도탄은 0.16이며 도탄에는 0.06초 cooldown을 적용한다. 금속 깡소리는 검 금속 레이어 0.8의 20% 배율로 작게 깔며 실제 체감 비율과 구분한다. 기존 검 명중음과 총 발사음은 보존한다.

구간·원본 해시·연결 전 bank는 `data/source/audio/revisions/20261117_smg_impacts_v1/`에 보존한다. GEN_3 도탄 두 구간은 원본부터 잔향이 겹치며 완전한 소스 분리 결과가 아니다. 실제 장치 청취·사용자 음색 승인은 아직 수행하지 않았다.

`python automate/run.py sound-preview --only gun-contact --channels 48 --output output/audio/smg_impacts_game_link`는 게임 재생기로 일반/금속 명중과 900 RPM·Overdrive 1,800 RPM 혼합 WAV를 기록한다. 0.03초의 발사→명중 간격은 비교 파일용 고정값이며 게임에서는 실제 충돌 시점에 재생한다. 창 없는 실제 믹서 검증과 전투 전체의 실제 장치 청취는 구분한다.

재생성: `python automate/run.py sound-effects --recipe data/source/audio/revisions/20261117_smg_impacts_v1/processing.json --output data/runtime/audio/user_audio/smg_impacts_v1 --preview output/audio/smg_impacts_v1/all_variations.wav`. 공개 시연에서 이 사용자 제공 원본을 필수 입력으로 사용하지 않는다.

현재 발사음은 `data/source/audio/sources/smg/futuristic_gun(GEN_3).mp3` 버스트의 짧은 구간 네 개다. `python automate/run.py sound-import --source "data/source/audio/sources/smg/futuristic_gun(GEN_3).mp3" --kind gun_fire --regions data/source/audio/revisions/20261117_varco_smg_split_v2/regions.json --event-volume 0.85`로 샘플을 준비한다. 이후 로컬 `bank.json`의 `events.gun_fire.layers[0].volume`을 현재 믹싱 배율 **2.5**로 설정한다. import의 음량 입력 범위는 0~1이며, 런타임 레이어 배율과 전체 음량 0.4의 곱으로 실제 채널 음량 1.0을 사용한다. SDL 채널 음량의 상한은 1.0이다. 재준비하면 이 로컬 조정을 다시 적용해야 한다. 구간은 `[0.022, 0.066]`·`[0.102, 0.138]`·`[0.175, 0.207]`·`[0.249, 0.280]`초다. 기존 샘플 준비의 peak 0.58 정규화와 앞 3ms·끝 15ms 페이드를 적용한다. 실제 발사마다 후보 하나를 선택하고 직전 후보는 제외한다. 원본 버스트와 빈 탄창 소리는 보존한다.

`--regions`에는 원본 범위 안의 겹치지 않는 오름차순 `[시작, 끝]` 목록 JSON을 전달한다. `--event-volume`은 단일 사건의 재생 음량이며 휘두르기 교체에는 사용하지 않는다. 원본 직접 연결과 구간 목록을 함께 사용할 수 없다.

부스트는 `jet_boost.ogg`를 `sound-import --source data/source/audio/sources/jet_boost.ogg --kind boost --start-seconds 0.29 --trim-only --event-volume 0.85`로 추출한다. `--trim-only`는 정규화·끝 페이드 없이 앞 3ms만 페이드한다. 현재 로컬 bank는 부스트 cooldown 0.12초·레이어 재생률 변주 0.015를 유지한다. 기본 import가 사건 설정을 새로 생성하므로 재준비할 때도 로컬 bank의 이 두 값을 유지한다. `sound-preview --only boost`로 3초의 `jet_boost_preview.wav`를 기록한다.

대시 지속 마찰음은 `sound_bank.json`의 `motion.dash_scrape_gain=0.85`를 사용한다. 원래 두 레이어의 비율과 대시 밖의 마찰음·부스트·지속 분사음·자갈은 유지한다.

`python automate/run.py sound-preview --only gun --output output/audio/gun_review`는 실제 SDL 믹서로 단발과 900 RPM 연사·빈 탄창 소리를 WAV에 기록한다. 이 선택 경로는 `gun_fire`·`gun_empty`의 로컬 선택 bank 연결이 필요하다. 더미 장치의 재생·클리핑 검사는 실제 장치의 음색·음량 청취와 구분한다.

기관단총 사용자 음원은 `sound-import --kind gun_fire`와 `--kind gun_empty`로 연결한다. 원본의 구간·음량을 유지하려면 `--preserve-source`를 사용한다. 예: `python automate/run.py sound-import --source data/source/audio/sources/moniker_subriquet-gunshot_smg_shot_1-203471.mp3 --kind gun_fire --preserve-source`. 빈 탄창은 `moniker_subriquet-gunshot_smg_loop_end-203470.mp3`와 `--kind gun_empty`를 사용한다. 두 파일은 로컬 사용자 제공 입력이며 공개 CC0 시연의 필수 입력이 아니다. 원본 직접 연결에서는 bank의 파일 별칭이 보존한 MP3를 가리키며 실시간 발사마다 파일을 읽거나 변환하지 않는다.

Pico2D와 SDL_mixer로 공통 음원을 실시간 혼합한다. 기본 샘플은 CC0 명시 원본을 사용하며, 사용자가 선택한 음원은 개별 출처와 선택 교체 파일로 관리한다. 원본·가공 WAV·개인 경로가 포함된 결과는 `data/runtime/audio/`에 보존하고 Git에 포함하지 않는다.

## 준비와 실행

Pico2D 1.5.1이 설치된 Python 환경에서 프로젝트 루트 기준으로 실행한다. 원본 다운로드는 인터넷 연결이 필요하다.

```text
python automate/run.py sound-sources --download
python automate/run.py sound-effects
python automate/run.py sound-effects --demo
python automate/run.py sound-effects --only boost_jet
python automate/run.py sound-effects --demo --only boost_jet
python automate/run.py sound-preview --only boost
python automate/run.py sound-preview --only attacks
python tests/sword_movement_test.py --demo
```

`--demo` 음원은 `samples/sound_effects/generated/`에 별도 생성한다. 게임 이미지·모델·사용자 선택 음원이 없어도 CC0 샘플로 실행할 수 있다. `python tests/sword_movement_test.py --mute`로 효과음을 끈다.

사용자가 타수별로 편집한 파일은 `--attack-index`로 1~4타에 직접 지정한다. 편집 원본을 그대로 복사·보존하고 OGG를 직접 적재한다. 구간·음량·시작/끝은 다시 가공하지 않는다. 카운터·필살기의 일반 가져오기는 WAV 변환·짧은 시작/끝 페이드·최대 진폭 정규화를 적용한다.

```text
python automate/run.py sound-import --source data/runtime/audio/sword_combo_1.ogg --kind swing --attack-index 1
python automate/run.py sound-import --source data/runtime/audio/sword_combo_2.ogg --kind swing --attack-index 2
python automate/run.py sound-import --source data/runtime/audio/sword_combo_3.ogg --kind swing --attack-index 3
python automate/run.py sound-import --source data/runtime/audio/sword_combo_4.ogg --kind swing --attack-index 4
python automate/run.py sound-import --source data/source/audio/sources/sword_counter.mp3 --kind counter
python automate/run.py sound-import --source data/source/audio/sources/sword_special.mp3 --kind ultimate
python automate/run.py sound-import --source data/runtime/audio/boost.ogg --kind boost --processing samples/sound_effects/boost_processing.json
python automate/run.py sound-preview
```

`sound-import --source 경로 --inspect`는 원본 길이·해시·0.1초 구간 RMS를 표시한다. 묶음 휘두르기 입력에는 `--kind swing --split`의 무음 분리도 지원한다. `--start-seconds`·`--end-seconds`로 단일 구간을 지정할 수 있다. 타수 지정·무음 분리·구간 지정은 서로 함께 사용하지 않는다.

`sound-preview`는 실제 재생기를 통해 다음 청취 파일과 진폭·누락·변환 시간 보고서를 `output/audio/cc0_review/`에 기록한다. 게임 재생에 필요한 입력이 아니다.

- `levels_1_2_3.wav`: 레벨 1→2→3 순서로 휘두르기·명중.
- `combos_1_2_3_4.wav`: 레벨 1에서 1→2→3→4타 원음 확인.
- `run_scrape_boost.wav`: 발걸음→지속 마찰과 자갈→부스트.
- `counter_ultimate.wav`: 선택 음원이 있을 때 카운터→필살기.

`sound-preview --only mobility --output 출력폴더`는 부스트 한 번과 마찰 지속 재생 13초를 따로 기록한다. 6초 마찰 재료의 반복 경계를 두 번 넘겨 확인한다.

`sound-effects --only 음원명`은 해당 음원만 재생성한다. `sound-preview --only boost --output 출력폴더`는 실제 재생기로 `boost.wav` 단발과 `boost_repeated.wav` 0.28초 간격 4회 연속 재생을 기록한다. 레퍼런스 분석용 게임 음원은 공통 제작 입력으로 사용하지 않는다.

`sound-preview --only attacks --output 출력폴더`는 발 디딤과 검 1~4타의 음량 비교용 `attack_steps.wav`를 기록한다. 고정 간격으로 소리를 조합하는 청취 자료이며 실제 발 접지 프레임 검증을 대신하지 않는다.

## 현재 소리 기준

- 대시: `dash_ignite.wav`의 약 0.34초 상승 가속을 진입 때 한 번 재생한다. 마찰음 위에 `dash_jet.wav`를 독립 루프로 겹치며 재생률 1.8로 높은 분사음을 낸다. 피치와 속도가 함께 변한다. 부스트·준비 중에는 지속 분사를 끄고, 대시 복귀에는 다시 진입음을 재생한다.
- 현재 로컬 명중: `data/source/audio/sources/hit/`의 sword hit·thud·knock·clang을 각각 독립 채널로 재생한다. **sword hit → 0.03초 뒤 thud+knock → 0.08초 뒤 clang** 순서다. 0.03초·0.08초는 명중 시점 기준이며, 각 파일의 앞 무음으로 시작을 나눈다. 합쳐진 금속 파일을 사용하지 않는다. clang 음량은 knock 대비 **90%**다. 일반 표적은 sword hit과 0.03초 뒤 thud만 사용한다.
- 현재 파일은 `hit_v1/sword_hit.wav`와 `hit_layers_v3/thud.wav`·`knock.wav`·`clang.wav`이며 `data/runtime/audio/user_audio/bank.json`에서 연결한다. thud의 사건별 음량은 0.85의 시험값이고 sword hit 0.9·knock 0.8·clang 0.72다. 뒤쪽 세 층의 재생률 변주는 0으로 맞춘다. 독립 채널 상한은 기본 24개이며 훈련장 `audio.channels`에서 조정한다.
- 로컬 선택 bank에서 이전 `cut_puff.wav`·`blade_stop.wav`·`blade_pipe.wav`·`blade_metal_scrape.wav`는 재생하지 않는다. 원본은 보존한다. 독립 CC0 시연용 기본 bank와 실제 로컬 선택 bank를 구분한다. 헛스윙에는 명중음을 재생하지 않으며 애니메이션의 hit stop을 추가한 것은 아니다.
- 로컬 명중 준비: `python automate/run.py sound-effects --recipe data/runtime/audio/user_audio/hit_processing_v1.json --output data/runtime/audio/user_audio/hit_v1 --only sword_hit`, `python automate/run.py sound-effects --recipe data/runtime/audio/user_audio/hit_layers_processing_v3.json --output data/runtime/audio/user_audio/hit_layers_v3`. 실제 재생기 청취 자료는 `python automate/run.py sound-preview --only contact --output output/audio/hit_layers_thud_20261116`으로 만든다. 녹음 WAV는 청취용 출력이며 게임에서는 네 원음을 별도 재생한다. 별도 사용자 제공 원본이 필요한 로컬 작업이며 기본 CC0 시연의 필수 입력은 아니다.
- 달리기: 낮은 금속 충격의 무게와 흙 발걸음을 혼합한다. 달리기 모션 한 주기에 두 번 발생한다. 실제 발 접지 프레임의 정밀 조정은 남아 있다.
- 일반 검 공격: 각 타격마다 발 디딤을 한 번 재생한다. 달리기와 같은 재료에 음량 배율 0.3을 적용해 희미하게 재생한다. `sound_bank.json`의 `motion.attack_step_phases`는 1~4타의 임시 위상 `[0.18, 0.18, 0.2, 0.18]`이며 원본 모션의 진행률을 사용한다. 활주 대시·부스트 구간은 제외하고 해당 타격이 끝나기 전에 보행으로 돌아와도 뒤늦게 발 소리를 추가하지 않는다. 실제 접지 프레임의 정밀 조정은 남아 있다.
- 쓸림: 눈 밟기 재료를 짧게 겹쳐 만든 고른 스키 마찰과, 고역 공기 재료의 치이익 증기음을 독립 채널에서 동시에 혼합한다. 각각 6초의 연속 재료이며 에너지 공진층은 사용하지 않는다. 시작 0.05초·종료 0.1초만 페이드하며 재료 반복마다 다시 시작하지 않는다. 자갈은 작은 음량의 별도 사건이다. 눈 재료는 마찰 질감용이며 훈련장의 지형을 눈으로 바꾸지 않는다. 여러 지형 재질의 자동 판별은 미연결이다.
- 검: 현재 로컬 선택 bank는 사용자 제공 VARCO AI GEN 1~3을 조합한 0.28~0.41초 후보 8개를 사용한다. 타수마다 서로 다른 두 후보를 선택하고 같은 타수의 직전 선택을 반복하지 않는다. 재생률 변주는 ±2%, 레벨 3 배율은 1.16이다. 3타에는 0.42초 바람층을 유지한다. 원본·이전 Heavy Whoosh·이전 선택 bank는 보존한다. 기본 CC0 도형 시연은 변경하지 않는다.
- 검 휘두르기의 레벨 1은 기본음, 레벨 2는 작은 고역 바람층, 레벨 3은 더 뚜렷한 바람층과 빠른 피치·속도를 사용한다. 수치는 잠정 청취용이다.
- 레벨은 사건 발생 시점에 적용한다. 각 레이어는 독립 채널에서 혼합하며 SDL의 메모리 변환으로 피치와 재생속도를 함께 바꾼다. 레벨별 완성 파일이나 런타임 AI 생성은 사용하지 않는다.
- 공개 CC0 시연의 부스트는 준비 종료 시 제트 가속에 저역 충격과 짧은 공기 폭발을 겹친 `boost_jet.wav`를 재생한다. 전체 약 0.8초·peak 0.82의 시험값이다. 실제 로컬 훈련장은 위의 `jet_boost.ogg` 추출 후보를 사용한다. 대시의 높은 지속 분사음과 구분하며 원본·종전 출력은 보존한다.
- `C`는 현재 카운터 표시 시연이 켜질 때, `V`는 에너지 레벨 3에서 필살기 쿨다운이 시작될 때 재생한다. 쿨다운 중 재입력에는 필살기 소리가 나지 않는다. 본편 카운터 판정·필살기 공격 구현을 뜻하지 않는다.
- 일시정지·포커스 상실·메뉴 진입은 소리를 정지한다. 초기화는 사건 중복 상태를 지운다. 오디오 장치·필수 음원 실패 시 경고와 함께 효과음만 비활성화한다.

## 파일 책임

| 경로 | 책임 |
| --- | --- |
| `sources.json` | CC0 원본 페이지·작성자·다운로드 선택 기준 |
| `processing.json` | CC0 공통 음원의 구간·대역·길이·루프·부스트 충격/분사 조립 값 |
| `sound_bank.json` | 사건별 레이어·음량·재생률·변주·재생 간격 |
| `boost_processing.json` | 보존한 종전 선택 부스트 원음의 중심 대역·잡음 억제·시간 포락선 |
| `user_selected_sources.json` | 사용자가 고른 Pixabay 음원의 출처 정보 |
| `data/source/audio/sources/` | 다운로드 원본·출처 페이지·원본 묶음 해시 |
| `data/runtime/audio/training_cc0_v1/` | 가공한 공통 음원. 레벨 구분 없음 |
| `data/runtime/audio/user_audio/` | 선택 원본·해시·분리 구간·가공 음원·선택 교체 bank |
| `ferrial_drive/audio/effects.py` | 원본 적재·SDL 변환·채널 혼합·루프·수명 |
| `ferrial_drive/combat/movement_audio.py` | 공격 구간·명중·달리기 위상·마찰·부스트 사건 연결 |

## 출처

CC0 여부는 각 원본 페이지에서 확인한다. 원본 페이지와 해시를 함께 보존한다.

- TinyWorlds / pdsounds.org, [Different steps](https://opengameart.org/content/different-steps-on-wood-stone-leaves-gravel-and-mud), CC0.
- AntumDeluge, [Scrapes](https://opengameart.org/content/scrapes), CC0.
- IgnasD, [Walking on snow sound](https://opengameart.org/content/walking-on-snow-sound), CC0. 대시 마찰 질감 재료.
- pyranostudios, [Air whoosh](https://opengameart.org/content/air-whoosh), CC0.
- BMacZero / Brian MacIntosh, [Mechanical Sounds](https://opengameart.org/content/mechanical-sounds), CC0.
- qubodup, [Jet Turbine Noise.flac](https://freesound.org/people/qubodup/sounds/205581/), CC0. 제트 엔진 시험 녹음이며 페이지에 공개된 HQ MP3 미리듣기 표현을 사용한다. 로그인 다운로드용 FLAC 원본과 구분한다.
- m_cel, [Jet Engine](https://freesound.org/people/m_cel/sounds/534856/), CC0. 공개 HQ MP3를 보존하며 대시 지속 분사와 진입 가속에 사용한다.

사용자 선택 원본은 CC0로 표시하지 않는다. [Pixabay Content License](https://pixabay.com/service/license-summary/)를 별도로 따른다. 아래 음원 ID·작성자 연결은 사용자가 제공한 출처 문구를 근거로 하며 개별 작품 페이지 주소는 아직 확인하지 않았다.

- 카운터 `241729`: Sound Effect by [u_fe12rqkbth](https://pixabay.com/ko/users/u_fe12rqkbth-46044709/) from Pixabay.
- 필살기 `40520`, 휘두르기 `7174`: Sound Effect by [freesound_community](https://pixabay.com/ko/users/freesound_community-46691455/) from Pixabay.

사용자 부스트 원본 `jet_boost.ogg`는 개별 출처·라이선스 확인을 기다린다. 다른 음원의 Pixabay/CC0 표기를 적용하지 않는다. 현재 원본·해시·구간 설정은 `data/runtime/audio/user_audio/boost_source.json`, 이전 연결은 `data/source/audio/revisions/`에 보존한다.

필터 수식 참고: Robert Bristow-Johnson / W3C, [Audio EQ Cookbook](https://www.w3.org/TR/audio-eq-cookbook/). 게임 실행에 추가 오디오 패키지를 요구하지 않는다.

CC0 샘플의 자동 검사·창 없는 실행·청취 파일 기록과 사용자 음색 승인은 구분한다. 자동 검사 통과로 실제 스피커의 음량·무게감·모션 동기화를 승인하지 않는다.

`sound-preview --only contact --output 출력폴더`는 헛스윙→기본 명중→금속 명중→3타 바람의 `miss_stop_metal_thrust.wav`와 0.28초 간격 4회 금속 명중의 `metal_hits_repeated.wav`를 기록한다. `--only mobility`의 `dash_boost_comparison.wav`는 대시 진입/지속→부스트 비교다.

금속 완성본은 로컬 `hit_metal` 사건에 `replaces_hit: true`를 지정한다. 이 경우 금속 표적은 완성본만 재생하고 기본 `hit`를 겹치지 않는다. 일반 표적과 공개 기본 레이어 방식은 유지한다. `sound-preview`도 같은 시각의 기본 명중을 제외해 실제 게임과 중복 여부를 맞춘다. 사용자 제공 MP3·OGG는 `files`의 상대 경로로 직접 연결할 수 있으며 파일 변환은 필수가 아니다.

- Anthousai, [hit - metallic - metal pipe 01.wav](https://freesound.org/people/Anthousai/sounds/406556/), CC0. 공개 HQ MP3 표현을 파이프 명중의 재료로 사용한다.
- qubodup, [Short Rusty Metal Scrape](https://freesound.org/people/qubodup/sounds/743259/), CC0. 공개 HQ MP3 표현을 금속 마찰의 재료로 사용한다.

Heavy Whoosh는 `heavy_whoosh_sources.json`·`heavy_whoosh_processing.json`을 사용한다. 다운로드는 `sound-sources --manifest`, 가공은 `sound-effects --recipe`로 별도 명세를 지정한다. 출력은 `data/runtime/audio/user_audio/heavy_whoosh/`에 둔다. 기본 CC0 명세/출력과 섞지 않는다.

## 사용자 제공 VARCO 검 음원

- 원본: `data/source/audio/sources/sword_swing/sword_swing(GEN_1).mp3`~`GEN_3`. 사용자 제공 생성 결과로 기록하며 CC0/CC BY로 재표기하지 않는다.
- 출처·원본 해시: 같은 폴더의 `source.json`. 중복 `sources/sword/` 폴더는 별도 보존한다.
- 가공 명세: `varco_swing_processing.json`. 1~3타는 짧은 본체와 시작 질감, 4타는 긴 본체와 낮은 꼬리를 조합한다. 큰 재생률 변주 대신 실제 다른 입력 구간을 사용한다.
- 출력: `data/runtime/audio/user_audio/varco_swing/`. 실행 선택은 상위 `bank.json`에서 타수별 두 파일로 연결한다. 원본은 수정하지 않는다.
- 재생성: `python automate/run.py sound-effects --recipe samples/sound_effects/varco_swing_processing.json --output data/runtime/audio/user_audio/varco_swing`.
- 청취 후보와 자동 검사·실제 믹서 연결 검증은 구분한다. 최종 음색은 사용자 청취 확인 전이다.
