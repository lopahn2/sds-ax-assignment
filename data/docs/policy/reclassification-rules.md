---
doc_id: policy/reclassification-rules.md
title: 재판정 규정
tags: [재판정, 스코프변경, G3]
---

# 재판정 규정

## 재판정이 의무인 경우

이미 판정을 받은 작업이라도 아래 상황에서는 `classify_complexity`를 다시 실행해 재판정해야 한다.

- 요구사항 범위가 확장되거나 변경된 경우 (예: 단일 사용자 기능 → 다중 사용자 동시 접근 기능으로 확대)
- 커밋 승인과 실제 커밋 실행 사이에 시간 간격이 발생해 재검증이 필요한 경우(`commit_pipeline` 내부 로직, 정책 [price-event-response.md](price-event-response.md) 참고)
- 사용자가 이전 판정 근거에 이의를 제기한 경우

## 재판정 절차

1. 변경된 내용을 반영해 6축 루브릭을 다시 적용한다.
2. 축 개수·판정 라벨(SIMPLE/COMPLEX)이 바뀌었는지 확인한다.
3. 라벨이 바뀌었으면 새 예상 비용과 함께 재승인을 요구한다. 라벨이 유지되면 변경 사유만 기록하고 기존 승인은 유효하게 본다.

## 편향 원칙

축 판정이 애매하거나 확신도(confidence)가 낮을 때는 항상 **COMPLEX 쪽으로 판정을 기울인다.** 실측 근거는 [round4-router-rubric.md](../research/round4-router-rubric.md)의 오분류 비용 비대칭 분석을 따른다 — 간단한 작업을 COMPLEX로 잘못 보내는 손해(+16~87%)보다 복잡한 작업을 SIMPLE로 잘못 보내는 손해(+72~119%)가 훨씬 크다.
