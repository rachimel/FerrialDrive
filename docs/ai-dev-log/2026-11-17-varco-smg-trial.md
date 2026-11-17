# VARCO AI 기관단총 음원 시험 연결

- **기록 ID:** `FDLOG-20261117-varco-smg-trial`
- 기록·검증 확인: 2026-11-17 12:55 KST. 개별 발언 시각은 미제공이다. [[FDLOG_MISSING_TIME:FDLOG-20261117-varco-smg-trial:scope]] 검색 단서: `varco ai`, `data/source/smg`, `이거 한번 써볼래`.
- 상태: GEN_3 시험 연결·원본 보존·자동 검사·SDL 녹음 완료. 실제 장치 청취·사용자 음색 승인·커밋·업로드는 미수행.

## 1. 사용자가 제안한 것

- **사용자 제안 1 (U1):** VARCO AI로 만든 smg 폴더의 음원을 시험 사용한다. VARCO 생성 사실은 사용자 설명에 근거하며 세부 생성 조건은 미제공이다. 시각·출처는 scope를 따른다.

## 2. 사용자 제안 중 AI가 수용한 것

- U1을 수용했다. 지시한 `data/source/smg`는 없었으며 실제 파일은 `data/source/audio/sources/smg/`에서 찾았다. GEN_1·2·3은 각각 약 1.517·2.548·1.179초였다.

## 3. AI가 제안한 것

- **구현상 판단:** 세 후보 중 가장 짧은 GEN_3를 우선 발사당 1회 재생한다. 긴 잔향의 중첩을 줄이는 시작 후보로 골랐으며 청취에 따른 음색 우열 판단은 아니다. 원본 MP3는 구간·피치·파형을 가공하지 않았다.
- **구현상 판단:** 기존 총성의 사건 배율 0.9로 연결했을 때 900 RPM 녹음 피크가 약 94%여서 배율을 0.45로 조정했다. 마스터 음량·다른 사건·빈 탄창 소리는 유지한다.

## 4. AI가 제안한 것 중 사용자가 수용한 것

- VARCO 음원의 시험 사용은 U1의 요구다. GEN_3 선택·사건 음량 0.45·최종 음색의 별도 사용자 수용은 아직 받지 않았다.

## 5. 반영 후 발견한 문제

- 기존 배율 0.9의 GEN_3 연사는 클리핑 0이었지만 16비트 피크가 30,783으로 혼합 여유가 작았다. 음색이 나쁘다고 판정한 근거는 아니다.

## 6. 사용자 해결 제안과 실제 해결 과정

- U1에 따라 시험 연결했다. 사용자가 추가 가공·다중 후보 무작위 재생·빈 탄창 소리 교체를 요청한 것으로 해석하지 않았다.

## 7. AI 해결 제안과 실제 해결 과정

- `sound-import`에 단일 사건용 `--event-volume`을 추가하고 0~1 유한값과 휘두르기 교체 오용을 검사한다. 기존 `--preserve-source` 경로로 GEN_3 원본을 연결했다. `sound-preview --only gun`은 실제 SDL 믹서의 단발·900 RPM 15발·빈 탄창 2회의 결과를 WAV로 기록한다. 필요한 두 사건이 없으면 오류로 안내한다.
- 재현 명령: `python automate/run.py sound-import --source "data/source/audio/sources/smg/futuristic_gun(GEN_3).mp3" --kind gun_fire --preserve-source --event-volume 0.45`, `python automate/run.py sound-preview --only gun --output output/audio/varco_smg_20261117/final`.
- 기존 연결은 `data/source/audio/revisions/20261117_varco_smg_v1/`의 `bank_before.json`·`gun_fire_source_before.json`에 보존했다. 기존 MP3·GEN_1·GEN_2를 삭제하거나 옮기지 않았다. 로컬 bank의 총성 별칭과 사건 배율만 교체했다.
- 원본과 적재 파일의 바이트 동일, 빈 탄창/다른 사건/교체 파일/다른 파일 별칭 보존을 확인했다. `nan`·음수·1 초과 사건 음량이 저장 전에 거부됨을 확인했다. 관련 총/음원 자동 검사 **57개 통과**. 전체 검사는 미수행이다.

| 실제 SDL 더미 녹음 | 단발 피크 | 900 RPM+빈 탄창 피크 | 클리핑 표본 | 채널 누락 |
| --- | ---: | ---: | ---: | ---: |
| 기존 총성·배율 0.9 | 9,959 | 10,374 | 0 | 0 |
| GEN_3·배율 0.9 | 10,806 | 30,783 | 0 | 0 |
| GEN_3·배율 0.45 | 5,403 | 15,389 | 0 | 0 |

- 각 조건은 단발 3초·연사/빈 탄창 4초, 기본 마스터 0.4, 44.1kHz stereo 16bit PCM이다. 총 재생은 발사 16회·빈 탄창 2회였다. 녹음 수치로 실제 장치 청취·전투 전체 혼합·Overdrive 청취 검증을 완료했다고 하지 않는다.
- 근거: `output/audio/varco_smg_20261117/{before,after,final}/`의 WAV·`report.json`, 로컬 `gun_fire_source.json`. 설정과 사용법은 사운드 README·이동 명세에 반영했다. AI 생성 음원은 Git 제외 경로에 유지했으며 커밋·업로드하지 않았다.
