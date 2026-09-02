---
doc_id: policy/cancellation-policy.md
title: 취소·재협상 정책
tags: [취소, 재협상, revise_assignment]
---

# 취소·재협상 정책

## 취소 가능 단계

assignment는 `RECOMMENDED`, `APPROVED` 단계에서만 취소할 수 있다. 이 단계에서는 아직 실제 개발 착수 전이므로 커밋된 예산을 즉시 전액 반환한다.

## 취소 불가 단계

`IN_PROGRESS` 이후(즉 `IN_PROGRESS`, `DONE`)에는 취소를 허용하지 않는다. 이미 개발 에이전트가 컨텍스트를 구성하고 작업을 시작했기 때문에, 여기서 되돌리는 것은 이미 소모된 토큰을 낭비하는 것과 같다.

`IN_PROGRESS` 단계에서 취소 요청이 들어오면:

1. 현재 단계가 `IN_PROGRESS`임을 명시한다.
2. 취소 대신 아래 대안을 안내한다.
   - **스코프 축소**: 남은 작업 범위를 줄여 조기 종료
   - **재협상**: 요구사항을 조정해 남은 작업을 재정의
3. 이미 커밋된 예산은 환급하지 않는다 — 임의로 환급액을 안내하지 않는다.

## 근거

실측 근거: [round1-orchestration-ops.md](../research/round1-orchestration-ops.md) — 부분 산출물을 남긴 채 되돌리는 재실행은 토큰 측정을 오염시키고, 이미 투입된 컨텍스트 비용은 회수되지 않는다는 것이 벤치마크 전 라운드의 공통 교훈이다.
