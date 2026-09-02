---
doc_id: research/round2-results-verdicts.md
title: 라운드2 — 종합 결과와 케이스별 LLM 판정 하이라이트
round: 2
tags: [종합결과, LLM판정, 코드품질, UX, 감사조정]
---

# 11. 종합 결과 — 자동 만점, 변별은 비용에서

세 케이스 모두 봉인 하니스 자동 채점 86/86 만점을 받았다. 규범 PRD의 기능·실시간·동시성·권한·견고성·성능·무결성을 셋 다 완전 준수했다는 뜻이다. 총점 차이(98.33 vs 99.0)는 오직 LLM 판정 14점의 소수 감점에서 나왔고 — 실질적 변별은 비용과 시간이다.

| 케이스 | 파이프라인 | 점수 | 자동 | CQ /8 | UX /6 | 순수개발 | $/점 | wall-clock | 에이전트 |
|---|---|---|---|---|---|---|---|---|---|
| case2_1 (최고 효율) | Sonnet설계→Opus풀스택 | 98.33 | 86 | 7.33 | 5.00 | $6.47 | $0.0658 | 26.9분 | 2 |
| case3_1 | Sonnet설계→Opus FE/BE | 99.0 | 86 | 7.33 | 5.67 | $9.01 | $0.0910 | 30.4분 | 3 |
| case3 | Opus설계→Sonnet FE/BE | 99.0 | 86 | 7.50 | 5.50 | $11.12 | $0.1123 | 34.1분 | 3 |

점수 = 자동 86 + CQ + UX(감사 확정). 순수개발 = productive 버킷 정가 비용(세션 한도·재실행 낭비 제외). $/점 = 순수개발 ÷ 점수. Sonnet 프로모션가($2/$10) 적용 시 case3는 $7.65 / $0.0773로 내려오지만 순위는 불변.

## 왜 case3(R1 우승자)가 R2 최고가가 됐나 — Sonnet 개발자의 시행착오

case3의 BE 개발자(Sonnet)는 복잡한 규범을 만족시키느라 반복이 폭증했다: 완주 BE 한 에이전트가 output 87k 토큰, 입력측(캐시 재읽기 포함) 18.3M 토큰, API 호출 120회로 홀로 $7.67를 태웠다. case3의 productive 입력측 합계는 23.6M 토큰 — Opus를 개발자로 쓴 두 케이스(7.2M·9.0M)의 약 3배다. **강한 개발 모델(Opus)은 같은 명세를 절반 이하의 컨텍스트 재읽기로 소화했다.**

| 케이스 (productive) | output 토큰 | 입력측 토큰* | API 호출 | 개발자 모델 |
|---|---|---|---|---|
| case2_1 | 78,776 | 7.20M | 68 | Opus |
| case3_1 | 119,211 | 8.98M | 104 | Opus |
| case3 | 138,632 | 23.64M | 168 | Sonnet |

\* 입력측 = uncached input + cache write + cache read 합(productive 버킷). R1과 마찬가지로 비용의 지배 항목은 output이 아니라 cache read(컨텍스트 재읽기)다.

# 12. 케이스별 LLM 판정 하이라이트

자동 86점이 동률이라 승부는 CQ(8)+UX(6) 14점에서 갈렸다. 세 구현 모두 감사가 "near-reference(준거 수준)"로 평가했고 감점은 하나같이 사소했다. 각 판정관은 file:line 인용과 함께 감점을 적용하거나 기각했다.

## case2_1 — Sonnet설계→Opus풀스택 (98.33)

CQ 7.33/8 · UX 5.00/6 · 감점 총 −1.67
- CQ −0.5: 검증 로직 중복 — name 1~64자 검사가 workspaces.js·boards.js 6곳에 손복사, expectedVersion 충돌 블록이 patchCard/moveCard에 반복.
- CQ −0.17: `el()`의 html/innerHTML 분기가 호출부 없이 방치(데드코드 + 잠재 XSS 소지).
- UX −0.5×2: 담당자를 불투명 userId 텍스트 입력으로 지정(피커·검색 없음 → 사실상 사용 불가), 댓글·알림·검색이 username 대신 내부 id를 그대로 노출.
- **강점**: 30줄 server.js가 lib 8모듈 + 핸들러 10파일을 배선, 단일 변경 관문 `recordAndBroadcast`가 seq+영속+활동+SSE를 한 곳에서. 원자적 temp+rename + 손상파일 격리, scrypt+16B 솔트+timingSafeEqual, 256bit 토큰. 프런트는 textContent 전용 DOM 빌더로 XSS 안전, 라이브 SSE·재접속·409 충돌 UX 모두 구현.

## case3_1 — Sonnet설계→Opus FE/BE (99.0)

CQ 7.33/8 · UX 5.67/6 · 감점 총 −1.00
- CQ −0.34: 전역 카드/컬럼 인덱스 부재 → 카드 연산마다 O(보드×카드) 선형 스캔(검색 인덱스는 있으나 카드→보드 조회 없음).
- CQ −0.33: 라우터에 인증 검사 누출, 무제한 in-memory 활동 미러, 사용되지 않는 identity 헬퍼 등 구조적 잔티.
- UX −0.33: 미읽음 배지가 SSE 푸시가 아니라 15초 폴링 기반 → 멘션/담당 배지가 최대 15초 지연.
- **강점**: 38줄 server.js + 19개 단일책임 모듈, 중앙 AppError/CODE_STATUS 에러층. 원자적 temp+fsync+rename+dir-fsync + JSONL 잘림 복구 + 손상 격리. 보드별 async 뮤텍스 + 단일 activity.append 관문이 seq 할당·SSE 팬아웃을 원자적으로. 클라이언트 innerHTML 0(구성상 XSS 안전).

## case3 — Opus설계→Sonnet FE/BE (99.0, 판정 최고점)

CQ 7.50/8 · UX 5.50/6 · 감점 총 −1.00
- CQ −0.5: 데드코드 — `log()` 헬퍼가 정의만 되고 호출부 없음(`warn()`만 11곳 사용). 그 외 감점 후보(갓파일·비원자 영속·약한 해싱·중복 권한검사)는 모두 인용과 함께 기각.
- UX −0.5: 버전 충돌 배너가 카드 모달 뒤 보드 뷰에 렌더 → 모달 내 저장 충돌 시 편집값이 조용히 서버값으로 교체되고 설명이 안 보임(상태는 갱신되므로 재시도는 가능 = 부분 감점).
- **강점**: temp+fsync+rename + 파일별 쓰기 체이닝 + 손상 격리 + 부팅 시 dangling 참조 정리. scrypt+16B 솔트, 256bit 토큰/id. server.js는 순수 배선. 모든 사용자 필드에 escapeHtml, 멘션 하이라이터가 이스케이프 후 래핑(주입 무력화). EventSource 자동 재접속 + Last-Event-ID + sync.required + 이벤트별 라이브 패치.

## 감사 확정 사항

세 판정 모두 조정 0건. 특기 사항 — case2_1의 영속성은 rename만 있고 fsync가 없어(피어 둘은 fsync 보유) 감사가 정밀 검토했으나, 원자성은 존재하고 IN-01 크래시 복구가 실증 통과해 판정관의 기각을 유지했다.
