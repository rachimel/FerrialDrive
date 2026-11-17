# Heavy Whoosh 변주와 후반 급속 소멸 베임선

- **기록 ID:** `FDLOG-20261116-heavy-whoosh-exponential-slash`
- 대화 범위: 2026-11-15~16 KST의 같은 채팅 후속. 원본 확보는 11월 15일, 보간 선택과 최종 재확인은 날짜 전환을 포함한다.
- 개별 발언·수용과 이 요약 작성의 정확한 시각은 미확인 — [[FDLOG_MISSING_TIME:FDLOG-20261116-heavy-whoosh-exponential-slash:scope]]. 검색 단서: `Heavy Whoosh에 Variation`, `정확히는 exponential fade out`, `축소는 Smoothstep`, `크기는 끝에서 확`.
- 근거: 현재 사용자 발언·선택 응답, 출처 페이지/해시와 별도 가공 명세, 실제 믹서·기체 검증 보고서.
- 상태: 변주 6개 연결·선택 보간 구현·관련 검사·실제 기체 확인. 최종 청감·외관 사용자 수용 전, 커밋·업로드 미수행.

## 1. 사용자가 제안한 것

- **사용자 제안 1 (U1):** 앞서 제시한 Artninja Heavy Whoosh를 기반으로 여러 변주를 만드는 방향을 제안했다. 동일 음원의 반복을 줄이려는 요구로 수용했으며 별도 세부 동기는 직접 제시하지 않았다.
- **사용자 제안 2 (U2):** 베임선 smoothstep·exponential 보간을 검토했다. 처음 선택 질문에서는 확대 exponential ease-out을 골랐으나, 곧 `정확히는 exponential fade out`, `끝에서 점점 빨라지는`이라고 적용 대상을 정정했다.
- **사용자 제안 3 (U3):** 꼬리부터 사라질 때 시간에 따라 크기도 줄이며 보간 함수를 고려하자고 요구했다. 축소 Smoothstep·지움 Exponential 조합을 선택했다.
- **사용자 제안 4 (U4), 최종 정정:** `크기는 끝에서 확 하고 지워지게`를 요구했다. 축소도 후반에 집중되는 곡선으로 변경했다. U3의 Smoothstep 축소를 현행 최종 선택으로 남기지 않는다.

## 2. 사용자 제안 중 AI가 수용한 것

- U1: 원본을 별도 CC BY 4.0 경로로 보존하고 6개 변주를 1~4타의 타수별 두 후보로 연결했다. 3타의 긴 바람층·기존 OGG 원본·이전 선택 bank는 보존한다.
- U2~U4: 확대는 Smoothstep, 꼬리 지움은 exponential ease-in, 축소도 더 강한 exponential ease-in으로 분리했다. 성장 중 투명도·방향성 블러·노란 림·크기/각도 변주는 유지한다.

## 3. AI가 제안한 것

- **AI 제안 1 (A1):** 길이·대역·구간·포락선이 다른 0.23~0.33초 변주 6개와 실행 중 ±2.5% 재생률 변주를 시험한다. 이유는 무게를 유지하며 빠른 콤보의 반복감을 줄이기 위해서다. 6개와 구체적인 값은 AI 시험값이다.
- **AI 제안 2 (A2):** 성장·지움·축소를 별도 곡선으로 조절한다. 처음에는 확대/축소 Smoothstep과 지움 exponential을 제시했고 사용자가 선택했다. U4 후에는 축소 exponent 10을 적용한다. 이유는 이중 소멸이 한 번에 몰리는 정도를 개별 조절하기 위해서다.
- **구현상 판단 A3:** 전체 0.34초 중 성장 0.09초, 소멸 0.25초를 유지한다. 지움 exponent 6, 축소 exponent 10을 사용한다. 축소는 소멸 시간 50%에서 약 97%, 75%에서 약 82%의 크기를 남기고 마지막에 빠르게 줄어든다. 지수 계수는 사용자 확정값이 아니다.

## 4. AI가 제안한 것 중 사용자가 수용한 것

- Heavy Whoosh 기반 변주는 U1의 직접 제안이다. 모든 변주와 실제 음량의 개별 청취 승인은 아직 없다.
- U2의 확대 ease-out 선택은 즉시 소멸 대상 정정으로 대체됐다. 성장에 exponential ease-out을 적용한 상태로 보고하지 않는다.
- U3에서 선택한 Smoothstep 축소는 U4로 다시 정정했다. 최종은 Smoothstep 확대·가속되는 꼬리 지움·후반 급속 축소다. 구체적인 지수 6/10과 최종 외관 승인은 별도다.

## 5. 반영 후 발견한 문제

- **I1:** Heavy Whoosh는 CC0가 아닌 [Artninja의 CC BY 4.0 원본](https://freesound.org/people/Artninja/sounds/730774/)이다. 기존 CC0 전용 다운로드/가공 경로가 거절하므로 출처 고지를 포함한 별도 명세를 지원해야 했다.
- **I2:** exponential의 적용 대상과 방향을 먼저 확대 곡선으로 해석할 가능성이 있었다. 사용자가 fade-out과 후반 가속이라고 정정했다. 실제 최종 구현은 이 정정에 따른다.
- 새 재생 실패·클리핑·레이어 누락은 이번 검사에서 확인하지 않았다. 자동 검사 통과는 청감·외관 승인이 아니다.

## 6. 사용자 해결 제안과 실제 해결 과정

- I1 ↔ U1: 사용자가 해당 음원을 선택했다. AI는 출처 고지와 변환 내용을 기록하고 CC0 기본 샘플과 분리했다.
- I2 ↔ U2/U3/U4: 적용 대상을 소멸로 정정하고, 크기 축소까지 추가한 뒤 끝에서 급격히 줄어드는 형태로 다시 조정했다. 각 선택의 순서를 보존한다.

## 7. AI 해결 제안과 실제 해결 과정

- `sound-sources --manifest`·`sound-effects --recipe`로 별도 선택 명세를 지원한다. CC BY 4.0은 작품 페이지의 해당 라이선스 표시와 attribution 필드를 확인하며 CC0로 재표기하지 않는다.
- 출처: `Heavy_whoosh_sound_122762022` by Artninja, 작품 `https://freesound.org/s/730774/`, CC BY 4.0. 공개 HQ MP3 표현을 사용한다. SHA-256은 `761d07f443985864f464839766c9c3feefb59ff7a22a6959af373f4a897c216f`다. [동봉 출처·가공 고지](../../samples/sound_effects/heavy_whoosh_attribution.md)를 작성했다.
- 변주 명세는 `samples/sound_effects/heavy_whoosh_processing.json`, 실제 출력은 `data/audio/user_audio/heavy_whoosh/`다. 기본 CC0 bank·도형 시연은 변경하지 않는다. 이전 로컬 선택은 `data/audio/revisions/20261115_heavy_whoosh/bank_before.json`에 보존한다.
- **자동 검사:** 효과음 27개·검 표현 21개, 합계 48개 통과. 최종 급속 축소 후 검 표현 21개를 다시 통과했다. 이번 변경 후 전체 자동 검사를 재실행했다고 확대하지 않는다.
- **파이프라인:** 별도 CC BY 4.0 6개 가공과 기본 CC0 `swing_air` 가공을 각각 실행했다. 두 명세의 원본과 출력을 분리했다. 원본·가공물이 Git 제외 대상임을 확인했다.
- **실제 믹서:** 6개 변주를 모두 각각 1회 재생한 4.4초 `variations_mixer.wav`는 peak 7889/32767·클리핑 0개·누락 0개다. 타수별 조합/발 디딤의 `attacks/attack_steps.wav`는 peak 8366/32767·클리핑 0개·누락 0개다.
- **실제 기체:** 280프레임에서 Heavy Whoosh 기반 검 7회·3타 바람 2회를 연결했다. 레이어 누락 0개, 최종 입자 0개다. 화면과 연속 캡처에서 성장·늦은 축소·소멸을 확인했다. 호출 CPU 포함 시간 평균 약 3.02ms·최대 약 5.92ms이며 GPU 시간·실제 FPS나 다수 적 성능으로 확대하지 않는다.
- **검토 자료:** `output/audio/heavy_whoosh_20261115/variations_mixer.wav`, `attacks/attack_steps.wav`, `output/verification/heavy_whoosh_20261115/slash_exponential_review.gif`(약 3배 느린 재생). 실제 스피커 청취·전체 8방향/타격의 사용감·최종 사용자 승인·커밋·업로드는 남아 있다.
