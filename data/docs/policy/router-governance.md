---
doc_id: policy/router-governance.md
title: 라우터 판정 거버넌스
tags: [G4, 근거인용, 판정거버넌스]
---

# 라우터 판정 거버넌스

## 근거 인용 의무

복잡도 판정(`classify_complexity`)과 비용 추정(`compare_pipelines`)은 반드시 [round4-router-rubric.md](../research/round4-router-rubric.md)의 6축 정의·결정 규칙, 또는 관련 라운드 문서의 실측 카탈로그를 `doc_id`로 인용해야 한다.

## 확인 불가 시 원칙

코퍼스에 없는 질문(예: 벤치마크에서 테스트하지 않은 모델, 아직 발생하지 않은 미래 가격 변동)에는 추측하지 않고 "확인 불가"로 답한 뒤, 필요하면 재판정이나 담당자 확인을 권한다. 근거 없는 숫자·결론을 만들어내는 것보다 정직한 거절이 항상 우선한다.

## 편향 규칙의 조직적 근거

"판정이 애매하면 COMPLEX로 기울인다"는 개별 도구의 임의 선택이 아니라, [round4-router-rubric.md](../research/round4-router-rubric.md)에서 실측으로 확인된 조직 정책이다 — 오분류 시 손해가 비대칭적이기 때문에(SIMPLE 오분류가 COMPLEX 오분류보다 최대 4배 더 비쌈), 이 편향은 어떤 판정 도구에도 예외 없이 적용한다.

## 판정 정확도 모니터링

라우터의 판정 정확도는 정기적으로 라벨링된 샘플 작업 세트로 검증한다(방법론은 [round4-router-rubric.md](../research/round4-router-rubric.md)의 84판정 실험 참고). 정확도가 목표치 아래로 떨어지면 축 정의나 프롬프트를 재검토한다.
