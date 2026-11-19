# CLI 멀티에이전트 협업 실습

<!-- 문서 언어: 한국어. 기술 제품명·명령어·식별자는 공식 영어 표기를 유지합니다. -->

## 디렉터리 구조와 책임

```text
openstate/
├── AGENTS.md                         # 에이전트가 작업 중 항상 참조할 짧은 공통 지침
├── README.md                         # 프로젝트 개요, 실행, 단계별 계획
├── docs/
│   └── security-model.md              # 인증·State·실행 경계의 상세 보안 설명
├── issues/                            # 설계·보안·호환성 이슈의 로컬 등록 문서
├── .agents/
│   └── skills/
│       ├── live-agent-run/SKILL.md    # 실제 CLI 실행 전 안전 점검 절차
│       └── mcp-security/SKILL.md      # MCP 추가·변경 전 보안 점검 절차
├── src/cli_collab/
│   ├── agents.py                      # Codex·Antigravity CLI Adapter
│   ├── workflow.py                    # LangGraph Node와 Shared State 흐름
│   ├── run_workflow.py                # 실행 진입점과 checkpoint 연결
│   ├── preflight.py                   # CLI 실행 전 강제하는 공통 안전 정책
│   └── security.py                    # State 저장 전 민감정보 축약·마스킹
├── tests/                             # Fake Adapter 기반 자동 테스트
├── .data/                             # 실행 중 생성되는 SQLite checkpoint DB, Git 제외
└── framework-architecture.*           # Mermaid 원본과 생성된 구조도
```

- `AGENTS.md`는 모든 작업에서 지켜야 할 짧은 규칙만 둡니다.
- `docs/`는 필요할 때 읽는 상세 문서입니다.
- `.agents/skills/`의 `SKILL.md`는 특정 상황에서 사용할 절차서입니다. 현재 Python
  오케스트레이터가 이 파일을 자동 실행하지는 않습니다. 명시적으로 Skill을 호출하거나,
  Python preflight 코드에서 검증 규칙을 실행해야 실제 통제가 됩니다.
- `.data/`는 로컬 런타임 데이터이므로 커밋하지 않습니다.

Codex CLI와 Google Antigravity CLI를 Python에서 실행하고, 이후 LangGraph
Shared State를 통해 협업시키기 위한 단계적 실습 프로젝트입니다.

현재 1단계의 목표는 두 CLI를 하나의 타입이 있는 인터페이스로 감싸고,
실행 결과·오류·CLI 내부 세션 ID를 일관되게 기록하는 것입니다. 아직
LangGraph, 공통 State 저장소, 영속 세션은 포함하지 않습니다.

## 현재 구조

```text
call_cli.py
  -> CodexCliAgent / AntigravityCliAgent
  -> subprocess
  -> 설치된 CLI
  -> AgentResult + AgentCapabilities
```

- `AgentResult`: 한 번의 CLI 실행 결과입니다. 종료 코드, 표준 출력·오류,
  파싱된 JSON/JSONL, 각 CLI의 세션 ID를 보관합니다.
- `AgentCapabilities`: 설치된 CLI가 실제로 지원하는 구조화 출력, 세션 재개,
  샌드박스 및 자동 파일 수정 승인 여부를 나타냅니다.

2단계에서 LangGraph Node는 각 어댑터의 `run()`을 호출하고 그 결과를
Shared State에 저장합니다. 그래프가 CLI의 사설 대화 기록 형식에 의존하지
않도록 하는 것이 핵심입니다.

## 안전한 사전 점검

```powershell
$env:PYTHONPATH = 'src'
python -m cli_collab.call_cli codex --probe
python -m cli_collab.call_cli antigravity --probe
python -m unittest discover -s tests -v
```

`--probe`는 각 CLI의 `--help`만 실행하며 모델 프롬프트를 보내지 않습니다.
실제 프롬프트 실행은 해당 서비스의 구독 사용량 또는 별도 과금 경로를
사용할 수 있으므로, 인증 및 사용량 상태를 확인한 뒤 실행합니다.

## Codex와 Antigravity의 세션 경계

```text
LangGraph thread_id           공통 작업·대화 단위
Codex thread ID               Codex 내부 대화 단위
Antigravity conversation_id   Antigravity 내부 대화 단위
```

이 값들은 같은 값으로 합치지 않습니다. 나중에 Shared State에
`agent_sessions = {"codex": "...", "antigravity": "..."}` 형태로 매핑해
논리적으로 협업 문맥을 공유합니다.

개인 Google 계정용 기존 `gemini` CLI는 2026년 6월 18일부터 요청 처리를
중단했습니다. Google 측 에이전트는 후속 도구인 Antigravity CLI(`agy`)를
사용하며, 대화형으로 설치·로그인한 뒤 사용해야 합니다.

## 확장 원칙

초기에는 도구 없이 에이전트 간 State 전달과 재작업 루프부터 검증합니다.

```text
Codex 분석
  -> Shared State 기록
  -> Antigravity 검토
  -> Shared State 기록
  -> Codex 재작업
```

이 흐름이 안정화된 뒤 도구를 추가합니다.

- LangGraph 직접 도구: YAML 검사, Git diff, 제한된 웹 수집처럼
  오케스트레이터가 순서를 통제해야 하는 작업
- Skill: 특정 업무를 처리하는 절차·지침·보조 스크립트
- MCP: 여러 CLI 에이전트가 공통으로 자율 호출해야 하는 전문 도구

MCP 도구의 호출 결과와 산출물 경로·해시는 Shared State에 남기되, 인증
토큰·브라우저 쿠키·CLI의 사설 대화 DB는 저장하지 않습니다.

Claude Code와 Grok Build는 향후 동일한 `CliAgent` 계약을 구현하는 선택적
어댑터로 추가합니다. 추가 시에는 해당 버전의 JSON 출력, 세션 재개,
인증·권한 정책을 먼저 프로브로 확인합니다.

## 다음 단계

1. Antigravity CLI 설치 및 대화형 인증 후 실제 JSON 응답·세션 재개 검증
2. LangGraph `StateGraph`, `SharedState`, SQLite Checkpointer 추가
3. 동일 `thread_id`에서 Codex 분석 → Antigravity 검토 → Codex 재작업 구현
4. 프로그램 재시작 후 State 복구 및 CLI 세션 재개/문맥 재주입 검증
5. Kubernetes YAML 검사 도구 하나를 LangGraph 직접 도구로 추가
6. 반복 검토 절차는 Skill로, 공통 자율 도구는 MCP로 분리

## SQLite 체크포인트 운영 가이드

### 선택 이유

현재 단계에서는 SQLite를 LangGraph checkpointer로 사용합니다.

- 별도 DB 서버, 계정, Docker가 필요 없습니다.
- 하나의 파일에 작업 상태를 저장하므로 로컬에서 백업·복구·디버깅하기 쉽습니다.
- Codex와 Antigravity를 순차 실행하는 초기 실습에서는 동시 쓰기 병목이 거의 없습니다.
- 이후 PostgreSQL로 옮길 때 그래프와 Shared State 계약은 유지하고 checkpointer만 교체할 수 있습니다.

SQLite는 최종 운영 DB가 아니라, 협업 흐름과 재시작 복구를 검증하기 위한
로컬 영속 계층입니다.

### DB 위치와 생성 방식

```text
openstate/
├─ .data/
│  └─ langgraph-checkpoints.sqlite
├─ src/
├─ tests/
└─ README.md
```

기본 DB 경로는 `.data/langgraph-checkpoints.sqlite`입니다.
`run_workflow.py`가 처음 실행될 때 `.data/` 폴더와 SQLite 파일을 자동으로
생성합니다. SQLite는 별도 서버가 아니라 이 파일 자체가 데이터베이스입니다.

### 저장 범위

```text
thread_id별 체크포인트
  ├─ user_request
  ├─ messages
  ├─ agent_sessions
│   ├─ codex: thread ID
│   └─ antigravity: conversation_id
  ├─ agent_runs
  ├─ current_agent
  └─ status
```

다음 값은 저장하지 않습니다.

- OpenAI·Google 로그인 토큰, API 키, 브라우저 쿠키
- 각 CLI가 자체 관리하는 사설 대화 DB 전체
- 대형 원문 응답과 바이너리 파일

큰 산출물은 파일로 보관하고, Shared State에는 파일 경로·해시·짧은 요약만
저장합니다.

### 실행과 복구

```powershell
.\.venv\Scripts\python.exe -m cli_collab.run_workflow `
  "Deployment YAML을 검토해 줘" `
  --thread-id k8s-review-001 `
  --database .data/langgraph-checkpoints.sqlite
```

같은 `thread_id`를 다시 사용하면 이전 작업의 Shared State를 이어받습니다.
새로운 독립 작업에는 새 `thread_id`를 사용합니다.

백업은 프로그램을 종료한 뒤 `.data/langgraph-checkpoints.sqlite` 파일을
복사하면 됩니다. 개발 환경에서 상태를 초기화하려면 해당 DB 파일을 삭제한
뒤 다시 실행합니다.

### Git과 보안

작업 요청과 에이전트 결과 요약이 저장될 수 있으므로 `.data/`는 Git에
커밋하지 않습니다.

```gitignore
.data/
```

### PostgreSQL 전환 기준

아래 중 하나가 필요해지면 PostgreSQL checkpointer로 전환합니다.

- FastAPI를 여러 프로세스 또는 컨테이너로 실행
- 여러 사용자가 동시에 작업
- Kubernetes replica 확장
- 장기 보존, 검색, 감사 로그, 접근 제어 필요
- 고가용성 백업과 복구 체계 필요
