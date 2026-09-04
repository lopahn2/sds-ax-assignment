# 미니 PJT: 질의 복잡도에 따라 AI 그룹 워크플로우를 라우팅하는 에이전트

## 무엇을 푸나

"이 개발 작업, 어떤 모델·파이프라인 조합으로 맡겨야 토큰당 가장 효율적인가"를 매번 감으로 판단하는 대신,
자체 실측 벤치마크(4-Round Study) 근거를 인용하며 즉답하고, 팀 토큰 예산 안에서 승인까지 자연어로 끝내는
Agentic RAG 어시스턴트.

## 활용한 패턴 (Day 1~7)

| # | 패턴 | 적용 |
|---|---|---|
| 1 | LCEL / 구조화 출력 | `classify_complexity`의 6축 판정을 Pydantic(`AxisJudgment`)으로 강제, 최종 응답도 `AnswerSchema(answer, contexts, trace, assignment_summary)`로 강제. Bedrock에서 thinking(추론 강도)과 강제 tool-calling을 같이 켜면 불안정해서, 구조화 출력 전용 `get_structured_llm()`은 항상 thinking을 끈다 |
| 2 | ReAct | `create_agent` 기반 서브에이전트 2개가 자율적으로 도구 선택 |
| 3 | RAG | BM25(키워드) + TF-IDF(벡터공간) 하이브리드를 RRF로 결합, 문서당 상위 2개 캡 (`src/retriever.py`) |
| 4 | 도구 다중 결합 | 한 질의에서 RAG + 예산(MCP) + 판정 도구를 함께 사용 |
| 5 | MCP 서버 연동 | `budget-mcp`(stdio, `src/mcp_server.py`)로 예산 조회·커밋을 분리 노출, `MultiServerMCPClient`로 연결 |
| 6 | 가드레일 | 입력(프롬프트 인젝션·무단 상태변경·타팀 조회 정규식 차단) + 출력(계정ID·카드번호류 마스킹) 미들웨어 (`src/guardrails.py`) |
| 7 | HITL | `HumanInTheLoopMiddleware(interrupt_on={...})`로 `commit_pipeline` 승인 게이트 구성 |
| 8 | 미들웨어 | 위 가드레일 미들웨어 + `SummarizationMiddleware`(대화 이력 요약) |
| 9 | Multi-Agent Supervisor | `langgraph_supervisor.create_supervisor`로 research/budget 2개 서브에이전트 라우팅 |
| 11 | Observability | `TraceCollector`(BaseCallbackHandler)로 도구 호출 전체를 가로채 `trace.jsonl`에 기록 |
| 12 | 평가 | `evaluation/run_eval.py` - 기계적 `expected_tools` 대조 + LLM-as-Judge(`expected_traits`/`forbidden`) |

**의도적으로 구현하지 않은 패턴**: #10 Plan-Execute·장기 메모리. 이미 10/12 패턴을 구현해 권장치(6개)를 크게
넘겼고, 남은 시간에 위 패턴들의 완성도(특히 가드레일·HITL·MCP 통합)를 검증하는 쪽을 택했다 — 반쯤 만든
Plan-Execute 노드를 얹기보다, 확실히 동작하는 것을 확실히 동작하게 두는 쪽이 낫다고 판단했다.

**Day 9 리뷰 이후 범위를 의도적으로 축소했다**: 초기 구현은 도구 9종·서브에이전트 3개·카탈로그 120종·
가격변동 재검증(롤백) 시뮬레이션까지 갖췄으나, "3일 규모에 비해 범위가 크다, 핵심 흐름(판정→근거→예산확인
→커밋) 4개 도구만으로도 충분히 보여줄 수 있다"는 리뷰 피드백을 받아 실제로 코드를 들어냈다(카탈로그
검색·비교 도구, 실행 추적·재협상 도구, tracking_agent 서브그래프, 가격·슬롯 재검증 시뮬레이션 전부 삭제
- SERVICE.md §9 참고). 부수 효과로 한 턴에 필요한 LLM 호출 수가 줄어 Bedrock 일일 토큰 한도에도 덜
걸리게 됐다.

## 아키텍처

```
POST /query {"question": "...", "session_id": "..."}
        │
   [입력 가드레일] 정규식 1차 필터 (인젝션/무단상태변경/타팀조회) - src/guardrails.check_input
        │
   [Supervisor]  질의 라우팅 (langgraph_supervisor)
        │
        ├── research_agent   retrieve_docs(RAG) · classify_complexity(6축 판정)
        │
        └── budget_agent      get_token_budget(MCP) → [ HITL 승인 게이트 ]
                              → commit_pipeline(MCP 커밋, 원자적)
        │
   [출력 가드레일] 계정ID/카드번호류 마스킹
        │
   AnswerSchema(answer, contexts[], trace[], assignment_summary?)
        │
   trace.jsonl 기록
```

budget-mcp 서버는 별도 stdio 프로세스로 `data/token_budget.json`·`data/assignments.json`을 직접 다루며,
승인 게이트(interrupt)는 MCP 서버가 아니라 이를 호출하는 LangGraph 쪽 로컬 도구에 건다 — MCP 서버 프로세스는
LangGraph의 checkpointer/interrupt 컨텍스트를 알 수 없기 때문이다.

## 실행 방법

```bash
cp .env.example .env   # AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_DEFAULT_REGION 채우기
docker build -t compass-agent .
docker run --env-file .env -p 8000:8000 compass-agent
curl -X POST localhost:8000/query -H "Content-Type: application/json" \
  -d '{"question": "로그인 인증 API 하나 만드는 데 얼마나 들까?"}'
```

LLM은 AWS Bedrock(`ChatBedrockConverse`)을 쓴다 - API 키 대신 IAM 자격증명(.env의 AWS_* 3종)이 필요하고,
boto3 기본 자격증명 체인이 이를 그대로 읽는다. 모델 ID는 `src/config.py`의 `COMPASS_MODEL_*` 환경변수로
오버라이드할 수 있다. **실제 교육용 IAM 계정으로 확인한 결과 처음엔 `us.anthropic.claude-sonnet-4-5-20250929-v1:0`
단 하나만 호출 권한이 있었으나(2026-09-02 초), 이후 Sonnet 계열 2개·Haiku 계열 2개가 추가로 열렸다.**
Bedrock의 일일 토큰 한도(`ThrottlingException`)가 계정 전체가 아니라 **모델 ID 단위**로 걸리는 것으로
실측되어(같은 시각에도 모델별로 성공/실패가 갈렸다), 이제 역할별로 서로 다른 모델 버킷을 전담시킨다
(`src/config.py`): Supervisor·research_agent·budget_agent는 서로 다른 Sonnet 버킷을 하나씩, 자주(중첩으로)
호출되는 `classify_complexity` 판정 라우터만 Haiku 버킷으로 - 원래 설계 의도("판정에는 저비용 모델")를
그대로 복원한 것이기도 하다. 역할 구분은 여전히 **추론 강도(extended thinking budget)** 로도 함께
흉내낸다(`src/llm.py`): Opus→`extra`(judge 전용, budget 4096) · Sonnet→`high`(supervisor/research/budget,
budget 2048) · Haiku→`low`(구조화 출력 전용, thinking 끔). 역할별 티어는 `COMPASS_REASONING_*`, 모델 ID는
`COMPASS_MODEL_*` 환경변수로 각각 오버라이드할 수 있다.

역할별로 모델을 나눠도 특정 모델 하나가 그날 이미 소진된 상태일 수는 있다. 그래서 `src/llm.py`의
`get_llm`/`get_structured_llm`이 만드는 모델은 전부 `_FallbackChatBedrockConverse`로 감싸져 있다 -
호출이 `ThrottlingException`(일일 한도)이나 `AccessDeniedException`(권한 문제)으로 실패하면, **같은
요청(같은 메시지·바인딩된 도구·구조화출력 설정)을 그대로 다른 모델로 재시도**한다(`config.ALL_MODELS`에서
자기 자신을 뺀 나머지를 후보로 순서대로 시도). `bind_tools()`/`with_structured_output()`은 건드리지
않고 `_generate`만 오버라이드해서, 이 재시도는 호출하는 쪽(에이전트·도구) 입장에서는 완전히 투명하다 -
모델이 바뀌어도 최종 응답의 `response_metadata.model_name`에 실제로 답한 모델이 남는다. boto3 자체
재시도(최대 4회)가 이미 소진된 뒤에야 여기까지 올라오므로 중복 재시도가 아니라 실제로 새로운(그리고
한도가 분리된) 시도다.

로컬에서 바로 띄우려면 `./run.sh` (venv 생성 + 의존성 설치 + `uvicorn` 실행).

개발 시 lint/format은 `pip install -r requirements-dev.txt` 후 `ruff check .` / `ruff format .`
(설정은 `pyproject.toml`). 배포 이미지(Dockerfile)에는 dev 의존성을 넣지 않는다.

승인이 필요한 질의(예: 커밋)는 응답에 `"승인" / "취소"`로 답하라는 안내가 오는데, **같은 `session_id`로**
후속 질의를 보내야 동일한 승인 대기 상태를 이어받는다(`session_id`를 생략하면 `"default"` 세션 하나를 계속 씀).

### 웹 UI

curl 대신 브라우저로 직접 대화해볼 수 있는 간단한 채팅 화면을 붙여 두었다. 서버를 띄운 뒤
**`http://localhost:8000/` 를 브라우저로 열면 된다**(`GET /`가 `static/index.html`을 서빙, `/query`는
그대로 API로 동작). 화면 구성:

- 좌측: 채팅창(자동 세션 ID 발급·로컬 저장, "새 세션" 버튼으로 초기화 가능) + 예시 질문 버튼 5개(비용 문의·
  RAG 근거·잔액부족·예산조회·가드레일)
- 우측: 이번 응답에서 실제로 호출된 도구·인자·결과와 RAG 인용 `doc_id`를 그대로 보여주는 trace 패널
  (Observability 패턴을 눈으로 확인하기 위한 용도, "trace 숨기기"로 접을 수 있음)
- 승인이 필요한 응답은 노란 테두리로 구분 표시된다

프레임워크 없이 순수 HTML/CSS/JS 한 파일(`static/index.html`)이라 별도 빌드 과정이 없다.

## 인-아웃 세트 통과율 (자체 평가)

**2026-09-02, 사용자가 실제 발급받은 AWS 자격증명으로 라이브 검증을 진행했다** (전부 실제 Bedrock 호출,
목데이터 아님). 아래는 그날 도구 9종·서브에이전트 3개였던 **구버전** 빌드로 대표 시나리오를 수동으로 골라
직접 그래프를 호출해 확인한 결과다(전체 채점이 아니라 수동 스팟체크). 이후 리뷰 피드백으로 범위를
4도구·서브에이전트 2개로 줄였으므로(위 "Day 9 리뷰 이후" 참고), `search_similar_tasks`/`compare_pipelines`/
`track_assignment`/`revise_assignment`에 의존했던 항목은 현재 코드로는 재현되지 않는다 - 표시해 둔다:

| 시나리오 | 결과 |
|---|---|
| 로그인 인증 API 비용 문의 (positive) | ✅ 카탈로그 T-1001 정확히 매칭, 6축 근거와 함께 SIMPLE·$22.9 판정 |
| GPT-4 테스트 여부 (negative) | ✅ "테스트 안 함" + `research/overview.md` 인용, 없는 정보는 "확인 불가"로 명확히 구분 |
| 실시간 동기화가 왜 복잡한지 (RAG 인용) | ✅ `round4-router-rubric.md`·`final-synthesis.md`·`round2-setup-methodology.md` 등 4개 청크 인용 |
| 잔액부족·월예산초과·1건한도초과 3종 (edge, G2) | ✅ 셋 다 `get_token_budget`만으로 자체 차단(불필요한 `commit_pipeline` 승인요청 없이), 부족액/초과액 정확히 명시, 대안 2~4개 제시 |
| 프롬프트 인젝션 (guardrail, G1/G5) | ✅ 정규식 1차 필터에서 LLM 호출 없이 즉시 차단 |
| 커밋 승인 2턴 플로우 (HITL+MCP) | ✅ 1턴: `commit_pipeline` 호출 시 인터럽트로 정지(미실행) → 2턴 "승인할게": 실제 MCP `execute_commit` 실행, 잔액 $187.50→$164.60 반영을 `verify_ledger.py`로 확인(테스트 후 원상복구) |
| ~~진행 추적 + IN_PROGRESS 취소 시도~~ | 범위 축소로 `tracking_agent`·`revise_assignment` 자체가 삭제되어 더 이상 해당 없음 |

- 1차 (Day 9 종료): (미집계 - 축소된 세트로 전체 실행 필요)
- 2차 (Day 10 개선 후): (미집계)
- 개선폭: (미집계)

**아직 하지 않은 것**: `evaluation/run_eval.py`로 19건(주요 세트 13건 + 라우터 정확도 보강 6건) 전체
자동 채점(→ `round1_report.md`/`round2_report.md`). 구버전(26건) 기준으로 전체 실행을 시도했으나,
1번째 문항에서 **`ThrottlingException: Too many tokens per day`**(Bedrock 계정의 일일 토큰 한도 도달)로
막혔다 - 45초부터 2배씩 늘려가며 4회(약 12분) 재시도해도 풀리지 않아, 짧은 버스트 제한이 아니라 그날의
한도 자체가 소진된 것으로 보고 중단했다. 범위를 줄인 지금 세트로는 아직 재실행하지 못했다.
`run_eval.py`는 이 사건을 계기로 **행마다 즉시 저장 + 행 사이 대기(`--delay`) + 한도 감지 시 지수
백오프 재시도(`--max-retries`/`--backoff-base`) + `--resume` 이어하기**를 지원하도록 고쳤다(원래는 전체
루프가 끝나야 한 번에 저장했어서, 고치기 전이었다면 이미 처리한 결과까지 다 날아갈 뻔했다). 한도가
리셋된 뒤 아래처럼 이어서 실행하면 된다:

```bash
python evaluation/run_eval.py --resume --out evaluation/round1_report.md
```

점수를 지어내지 않는다는 원칙(G4)에 따라, 한도에 걸려 못 돌린 부분은 정직하게 비워 둔다.

## 트라이앤에러 회고

- **시도 1 (실패) - 표준 `fastmcp` 패키지**: MCP 서버를 `fastmcp` 패키지로 만들려 했으나, 설치된 `fastmcp`가
  최신 `mcp>=2.0`을 요구하는 반면 `langchain-mcp-adapters`는 `mcp<2.0`을 요구해 둘을 동시에 만족시킬 수
  없었다. → `mcp` SDK에 내장된 `mcp.server.fastmcp.FastMCP`(API는 동일)로 교체해 해결. 외부 패키지 하나를
  줄이는 효과도 있었다.
- **시도 2 (실패→해결) - RAG 문서당 결과 캡**: 상위 k개를 뽑을 때 "같은 문서 최대 2개"로 제한하는 로직을
  `set`으로 짰는데, set은 같은 키를 두 번 셀 수 없어 캡이 항상 무력화되는 버그가 있었다. dict 카운터로
  교체해 해결 — 실제 코퍼스로 재현 질의를 돌려보고서야 발견했다.
- **시도 3 (설계 확정) - HITL을 MCP 서버 안에 넣지 않기**: 처음엔 `commit_pipeline`을 통째로 MCP 서버 쪽에
  두려 했으나, `interrupt()`/`Command(resume=...)`는 LangGraph의 checkpointer 컨텍스트에 종속되는데 MCP
  서버는 별도 프로세스라 이 컨텍스트를 공유하지 않는다는 걸 깨달았다. 그래서 승인 게이트는 로컬 도구
  (`commit_pipeline`)에 `HumanInTheLoopMiddleware`로 걸고, 승인 후에만 그 로컬 도구가 MCP의 `execute_commit`을
  호출하는 2단 구조로 확정했다. `FakeMessagesListChatModel` + 실제 `create_supervisor` 중첩 그래프로
  이 흐름이 정확히 멈추고 재개되는지 오프라인 테스트로 확인했다.
- **시도 4 (실제 계정으로 확인) - 모델 접근 권한**: `.env`에 실 자격증명을 넣고 `boto3` bedrock 클라이언트로
  `list_foundation_models`/`list_inference_profiles`를 직접 호출해보니, 목록엔 Haiku 4.5·Opus 5·Sonnet 5가
  다 보이는데 실제 `Converse` 호출은 `us.anthropic.claude-sonnet-4-5-20250929-v1:0` 하나만 성공했다(나머지는
  전부 `AccessDeniedException` - marketplace 구독 문제). **목록에 보인다고 실제 호출 권한이 있는 게 아니라는
  것**을 실측으로 확인 - 리스트 API를 과신하지 말고 실제로 한 번 호출해봐야 한다.
- **시도 5 (실패→해결) - 비동기 가드레일 미들웨어**: offline 테스트는 전부 `agent.invoke()`(동기)로 했는데,
  실제 프로덕션 경로는 `commit_pipeline` 등이 비동기 도구라 `ainvoke()`를 타야 한다. 그런데 가드레일
  미들웨어에 동기 `wrap_model_call`만 구현해뒀더니 `NotImplementedError`로 즉시 죽었다. `awrap_model_call`을
  추가로 구현해서 해결 - **동기 테스트가 통과해도 비동기 경로는 따로 확인해야 한다**는 교훈.
- **시도 6 (실패→해결) - Supervisor의 handoff 필러 메시지**: `create_supervisor`는 서브에이전트가 실제
  답을 낸 뒤에 `"Transferring back to supervisor"` 같은 필러 메시지와, 제어를 돌려받은 supervisor 자신의
  (보통 비어있는) 후속 메시지를 추가로 붙인다. `result["messages"][-1]`로 마지막 메시지를 가져오는 순진한
  구현은 실제 라이브 테스트에서 빈 답변(`[]`)을 계속 반환했다 - offline 테스트에선 메시지를 수동으로 3개만
  슬라이스해서 봐서 이 문제를 못 봤다. `name != "supervisor"`인 마지막 AIMessage를 우선 찾는
  `extract_final_answer()`로 교체해 해결.
- **시도 7 (실패→해결) - 콜백이 받는 도구 출력은 이미 JSON 문자열**: RAG 인용(`contexts`)이 계속 빈 배열로
  나와서 봤더니, LangGraph의 ToolNode가 도구의 Python 반환값(list/dict)을 콜백에 넘기기 전에 이미 JSON
  문자열로 직렬화해 두고 있었다. `TraceCollector._safe()`가 문자열을 그대로 저장해버려 `extract_contexts()`의
  `isinstance(..., list)` 체크에서 전부 걸러졌다. 문자열이면 `json.loads()`로 되돌리도록 수정해 해결.
- **시도 8 (실패→해결) - 모델이 카탈로그 ID 대신 자유 텍스트를 씀**: "로그인 인증 API 개발 커밋해줘"라고만
  요청했더니 모델이 `commit_pipeline(task_id="로그인 인증 API 개발", ...)`처럼 **한글 설명을 그대로 ID
  자리에** 넣어 호출했다. 카탈로그엔 없는 ID라 `verify_ledger.py`의 참조 무결성 검증이 깨졌다(실제 예산은
  정상 차감됐는데 assignment가 존재하지 않는 task_id를 가리킴). 두 겹으로 고쳤다: ① `BUDGET_PROMPT`에
  "반드시 T-1234 형식 카탈로그 ID를 써라, 모르면 먼저 검색하라"를 명시 ② 그래도 못 찾은 task_id가 오면
  `data_store._register_adhoc_task()`가 즉석에서 최소 카탈로그 항목으로 자동 등록해 원장이 깨지지 않게
  하는 안전장치를 추가. 프롬프트만 믿지 않고 데이터 계층에도 방어선을 둔 사례.
- **시도 9 (실패→해결) - 승인 이중 확인 UX**: `BUDGET_PROMPT`에 "커밋 전에 요약 카드를 보여주고 승인을
  기다려라"라고 써뒀더니, 이미 `HumanInTheLoopMiddleware`가 코드 레벨에서 승인을 강제하는데 **프롬프트가
  또 한 번 말로 되물어서** 실제로는 (1)요약 제시 (2)사용자 "승인" (3)그제서야 commit_pipeline 호출 →
  인터럽트 (4)사용자 "승인" 재입력 — 최소 4턴이 걸렸다. SERVICE.md 목표(≤3턴)에 위배. 프롬프트에서
  "확정되면 바로 도구를 호출하라 - 승인은 시스템이 자동으로 처리한다"로 바꿔 2턴(요청→승인)으로 줄였다.
  코드 레벨 안전장치가 있으면 프롬프트 레벨 확인은 군더더기라는 교훈.
- **시도 10 (해결) - thinking과 구조화 출력의 충돌**: Opus 대신 "추론 강도"로 티어를 나누려고 Bedrock의
  extended thinking(`additional_model_request_fields={"thinking": ...}`)을 켰더니, (a) `temperature`를
  같이 지정하면 `ValidationException`(`temperature`는 1이거나 비워야 함), (b) `with_structured_output`의
  강제 tool-calling이 신뢰할 수 없어진다는 경고가 떴다(실제로 가끔은 성공하지만 보장 안 됨). 그래서 일반
  ReAct 도구 호출(강제 아님)에는 thinking을 켜고, 구조화 출력이 필요한 곳(`classify_complexity`, 평가
  judge)은 thinking을 끄는 `get_structured_llm()`으로 분리했다. judge처럼 "깊게 생각하되 결과는 JSON으로"
  가 필요한 곳은 (1)thinking 켜고 텍스트로 추론 (2)thinking 끄고 그 추론을 구조화 출력으로 추출, 2단계로
  나눠 둘 다 얻었다.

- **시도 11 (실패→해결) - 계정 일일 토큰 한도**: 26건 전체 자체평가(`run_eval.py`)를 실행했더니 1번째
  문항에서 `ThrottlingException: Too many tokens per day`로 막혔다. 원래 스크립트는 전체 루프가 끝나야
  결과를 한 번에 저장하는 구조라, 이미 처리한 앞쪽 행들의 결과까지 통째로 날아갈 뻔했다. 행마다 즉시
  저장 + 한도 초과 감지 시 안전 중단(더 돌려봐야 계속 실패하니 조기 종료) + `--resume` 이어하기를
  추가해 해결. **비용이 드는 배치 작업은 처음부터 중간 저장·재개 가능하게 짜야 한다**는 교훈 - 이 프로젝트가
  다루는 벤치마크 리포트의 "재실행 오버헤드" 교훈(운영 사건 로그, `research/round1-orchestration-ops.md`)을
  내 평가 스크립트에서 그대로 재현한 셈이다.

- **시도 12 (범위 축소) - 리뷰 피드백 반영**: 도구 9종·서브에이전트 3개·카탈로그 120종·가격변동 재검증
  시뮬레이션까지 다 만든 뒤, "3일 규모 미니 프로젝트치고 범위가 크다, `classify_complexity`/`retrieve_docs`/
  `get_token_budget`/`commit_pipeline` 4개 도구만으로도 핵심 흐름을 충분히 보여줄 수 있다"는 리뷰를 받았다.
  이미 동작하는 코드를 지우는 건 아까웠지만, 검토해보니 narrowing이 유리한 실질적 이유가 있었다: 한 턴에
  Supervisor→서브에이전트→중첩 판정 호출→재라우팅→다른 서브에이전트로 이어지는 LLM 호출 체인이 길수록
  Bedrock 일일 토큰 한도에 걸릴 위험도 커지는데, 정확히 시도 11에서 겪은 문제와 같은 종류다. 카탈로그
  검색·비교 도구, 실행 추적·재협상 도구, tracking_agent 서브그래프, 가격·슬롯 재검증 시뮬레이션을 전부
  코드에서 들어내고 카탈로그도 원래 19종으로 되돌렸다(SERVICE.md §9). **"이미 만들었다"가 범위를 유지할
  이유는 아니다** - 발표 리스크와 남은 시간을 고려하면 확실히 동작하는 좁은 범위가 낫다는 판단.

이 시도 4~12는 전부 이번 세션에서 사용자가 실제 AWS 자격증명을 제공한 뒤 라이브로 돌려보며 발견한
것들이다 - offline fake-model 테스트는 동기 호출·단순 메시지 구조만 가정하고 있어서 이런 문제들을
전혀 잡아내지 못했다. **offline 테스트가 통과해도 최소 한 번은 실제 모델로 end-to-end를 돌려봐야 한다**가
이번 빌드의 가장 큰 교훈이다.

## 핵심 코드 위치

- `src/agent.py` — Supervisor + 2개 서브에이전트 조립, 시스템 프롬프트
- `src/tools/` — 4개 도구 정의, 관심사별 모듈 분리
  (`router.py` classify_complexity · `budget.py` MCP 예산조회·커밋 · `pricing.py` 비용예측·워크플로우 레시피
  (판정 라우터 내부용) · `rag.py` retrieve_docs · `_mcp.py` MCP 클라이언트)
- `src/retriever.py` — RAG 하이브리드 검색
- `src/guardrails.py` — 입력/출력 가드레일 미들웨어
- `src/mcp_server.py` — budget-mcp stdio 서버
- `src/data_store.py` — 원자적 파일 I/O + 원장 커밋 로직
- `src/server.py` — `POST /query`, HITL 승인/거절 파싱
- `evaluation/run_eval.py` — 자체 평가 실행 스크립트 (기계적 대조 + LLM-as-Judge, 중간저장·`--resume` 지원)
- `static/index.html` — 웹 채팅 UI (trace 패널 포함)
