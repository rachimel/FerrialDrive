# 사용자 추가 metal-hit MP3 교체 시험

- **기록 ID:** `FDLOG-20261117-metal-hit-mp3`
- 대화 범위: 2026-11-17 현재 세션. 개별 발언 시각은 미제공이다. [[FDLOG_MISSING_TIME:FDLOG-20261117-metal-hit-mp3:scope]] 검색 단서: `metal-hit mp3 추가`, `기존 금속 피격음 대신`.
- 기록 작성 기준: 2026-11-17 19:48:36 KST.
- 상태: 로컬 음원 연결·자동 검사·창 없는 실제 믹서 기록 완료. 실제 장치 청취·사용자 음색 승인은 미수행. 커밋·업로드 미수행.

## 1. 사용자가 제안한 것

- **사용자 제안 1 (U1):** 추가한 metal-hit MP3를 기존 금속 피격음 대신 사용해보도록 요청했다. 이유는 새 음원으로 교체 시험하려는 의도이며 원문 근거는 위 검색 단서다. 정확한 시각은 scope 누락 항목을 따른다. 추가 편집·음량 변경은 요청하지 않았다.

## 2. 사용자 제안 중 AI가 수용한 것

- U1: 새 파일 `data/source/audio/sources/hit/metal/floraphonic-metal-hit-10-193281.mp3`를 확인해 로컬 검 금속 명중 사건 `hit_metal`에 연결했다. 같은 디렉터리의 다른 MP3와 구분했고 실제 파일명과 적용 사건을 진행 보고로 설명했다.

## 3. AI가 제안한 것

- **AI 제안 1 (A1), 구현상 판단:** 새 원본을 직접 적재하고 사건 음량 0.8·최소 간격 0.06초·기본 `hit` 중첩 제외를 유지한다. 근거는 기존 로컬 `hit_metal` 설정이다. 재가공을 요청받지 않았으므로 정규화·자르기·새 피치 변주는 추가하지 않았다. 적용 범위와 음량은 현재 세션 진행 보고로 설명했다.
- 기존 자동화 `sound-import`에 `hit_metal` 선택을 추가해 동일 진입점으로 원본 복사·해시·출처 상태·bank 연결을 관리했다.

## 4. AI가 제안한 것 중 사용자가 수용한 것

- A1의 별도 명시 수용은 현재 세션에 없다. 사용자 음색 승인으로 기록하지 않으며 U1의 교체 시험을 구현한 상태다.

## 5. 반영 후 발견한 문제

- 원본 해시 `1a77d85c9277bf38a859763df2c7e5d6b8d67a9f95b8bd8ea31e3a2686fe0545`, 44.1kHz 모노 검사 시 길이 약 1.175초를 확인했다. 실제 음색의 문제는 청취하지 않아 판단하지 않는다.
- 검사 중 연결 실패·클리핑·누락은 발견되지 않았다. 파일명만으로 작성자·개별 작품 페이지·라이선스를 확정하지 않았다.

## 6. 사용자 해결 제안과 실제 해결 과정

- U1: 기존 `user_hit_metal_mix.ogg`의 활성 연결을 새 MP3로 교체했다. 이전 bank는 `data/source/audio/revisions/20261117_194755_metal_hit/bank_before.json`에 보존했다. 기존 음원과 원본 파일은 삭제하지 않았다.

## 7. AI 해결 제안과 실제 해결 과정

- A1: `automate/run.py sound-import --kind hit_metal --preserve-source --event-volume 0.8`로 준비했다. 원본 복사본은 `data/runtime/audio/user_audio/originals/`, 활성 파일 식별자는 `user_hit_metal.mp3`다. provenance는 같은 폴더의 `hit_metal_source.json`에 기록했다. 사용자 bank에서는 `hit_metal` 사건만 변경됐음을 비교했다. 총 피탄·도탄·폭발 사건은 기존 값과 같았다.
- 자동 검사: `tests.automated.test_sound_effects` 31개 통과. 실제 믹서 `sound-preview --only contact --channels 48`에서 새 MP3 6회 재생·누락 레이어 0개를 확인했다. 4초 비교와 2.6초 반복 명중 기록 모두 클리핑 0샘플이며 최대 진폭은 각각 13,005/11,704다.
- 근거: `output/audio/metal_hit_mp3_20261117/report.json`과 WAV 두 개. 재생성 가능한 진단 출력으로 Git에서 제외한다. 사용자 직접 청취·실제 전투 모션 동기화 확인을 대신하지 않는다.
- 실행 중 음원 bank 자동 재로딩은 추가하지 않았다. Combat Test를 다시 실행하면 적용된다. 로컬 음원·이전 bank는 공개 업로드하지 않았다.
