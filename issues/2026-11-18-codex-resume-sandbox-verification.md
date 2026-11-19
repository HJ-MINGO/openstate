# [ISSUE] Codex Session 재개 시 sandbox 적용 검증 방식 결정

- 등록일: 2026-11-18
- 상태: Resolved (실제 재개 smoke test 통과)
- 우선순위: High
- 범위: Codex CLI Adapter, `preflight.py`, Shared State 세션 복구

## 문제 요약

새 Codex 작업은 아래처럼 Codex CLI가 제공하는 sandbox 정책을 명령 인자에 명시할 수 있습니다.

```text
codex exec --sandbox read-only ...
```

이때 `--sandbox read-only`는 이 프로젝트가 만든 기능이 아니라 OpenAI Codex CLI에 내장된
실행 정책입니다. 에이전트가 생성하는 shell command의 권한을 `read-only`로 제한하도록
Codex CLI에 요청합니다.

반면 현재 확인한 Session 재개 명령은 다음 형식입니다.

```text
codex exec resume <SESSION_ID> <PROMPT>
```

`codex exec resume --help`에는 새 작업에 있는 `--sandbox` 또는 `-s` 옵션이 직접 노출되지
않습니다. 그러나 `--sandbox`는 `resume`의 옵션이 아니라 상위 `codex exec`의 공통 옵션입니다.
따라서 아래처럼 `resume` 앞에 배치하면 명령 인자에 `read-only` 정책을 명시할 수 있습니다.

```text
codex exec --json --skip-git-repo-check --sandbox read-only resume <SESSION_ID> <PROMPT>
```

## 이것이 아닌 것

- Codex와 Antigravity를 함께 사용하는 멀티에이전트 구조를 금지하는 제공자 정책 문제가 아닙니다.
- Codex CLI의 Session 재개 기능이 금지된 것도 아닙니다.
- 이 프로젝트가 별도의 sandbox를 만들었는데 재개 시 그것이 사라지는 문제도 아닙니다.

이 프로젝트의 `preflight.py`는 sandbox 자체가 아니라, Codex 또는 Antigravity CLI를 실행하기
전에 안전한 옵션이 포함됐는지 확인하는 정책 검사기입니다.

## 현재 구현과 영향

`src/cli_collab/preflight.py`는 다음을 수행합니다.

1. Codex 새 작업에는 `--sandbox read-only`가 있는지 검사합니다.
2. Antigravity 작업에는 `--sandbox --mode plan`이 있는지 검사합니다.
3. `--no-sandbox`, `--yolo` 등 우회 옵션과 범위를 벗어난 timeout을 차단합니다.
4. Codex 재개 명령에도 상위 `exec`의 `--sandbox read-only`가 포함됐는지 검사합니다.

따라서 동일한 LangGraph `thread_id`로 후속 요청을 실행할 때, 저장된 Codex Session ID를 그대로
`codex exec resume`에 전달하면 `exit_code=126`으로 중단됩니다. 이것은 제공자 오류가 아니라
현재 프로젝트의 보수적인 안전 정책 결과입니다.

## 확인 근거

2026-11-18 로컬 설치 Codex CLI의 도움말에서 확인한 내용입니다.

```text
codex exec --help
  -s, --sandbox <SANDBOX_MODE>
  가능한 값: read-only, workspace-write, danger-full-access

codex exec --sandbox not-a-mode resume <SESSION_ID> <PROMPT>
  error: invalid value 'not-a-mode' for '--sandbox <SANDBOX_MODE>'
```

2026-11-18 확인에서 현재 설치 CLI는 `resume` 앞의 상위 `--sandbox` 옵션을 파싱하고,
허용 가능한 sandbox 값을 검증했습니다. OpenAI의 공식 `openai/codex` 소스도 `exec`의
공통 `sandbox_mode`를 Session 재개 흐름에 전달하는 구조임을 확인했습니다.

다만 존재하지 않는 Session ID를 사용한 실제 재개 검증은 Windows의 Codex 임시 경로 권한
오류로 app-server 초기화 전에 실패했습니다. 따라서 실제 제공자 Session을 재개한 통합
검증은 별도 완료 조건으로 남깁니다.

## 구현 결과

`CodexCliAgent`는 재개 시 아래 명령을 생성하도록 변경됐고, `preflight.py`는 이 명시적
`read-only` 설정을 검사해 허용합니다.

```text
codex exec --json --skip-git-repo-check --sandbox read-only resume <SESSION_ID> <PROMPT>
```

## 해결 과정

### 1. 최초 원인 분석

초기에는 `codex exec resume --help`에 `--sandbox` 또는 `-s`가 보이지 않아, 재개 명령에는
`read-only` sandbox를 명시할 수 없다고 판단했습니다. 이 판단에 따라 `preflight.py`는
Codex 재개 호출을 차단했고, 같은 LangGraph `thread_id`의 후속 요청은 Session 재개 대신
Shared State 요약을 새 Session에 전달하는 fallback만 사용할 예정이었습니다.

### 2. CLI 옵션의 소속 재확인

추가 확인 결과 `--sandbox`는 `resume` 전용 옵션이 아니라 상위 `codex exec`의 공통 옵션임을
확인했습니다. 따라서 옵션은 `resume` 뒤가 아니라 `exec` 뒤, `resume` 앞에 둬야 합니다.

```text
# 잘못된 기대: resume 하위 명령의 옵션으로 사용
codex exec resume <SESSION_ID> --sandbox read-only <PROMPT>

# 해결: exec 공통 옵션으로 하위 명령 앞에 사용
codex exec --sandbox read-only resume <SESSION_ID> <PROMPT>
```

### 3. 검증 근거

2026-11-18에 다음 세 가지를 확인했습니다.

1. 현재 설치된 `codex exec --help`는 `--sandbox`와 `read-only` 값을 공식 지원합니다.
2. 현재 설치 CLI에서 `codex exec --sandbox not-a-mode resume ...`를 실행했을 때, CLI가
   `not-a-mode`를 `--sandbox`의 잘못된 값으로 인식하고 허용 값 목록을 반환했습니다.
   즉 옵션이 `resume` 앞의 공통 위치에서 파싱됨을 확인했습니다.
3. OpenAI 공식 `openai/codex` 소스의 `exec` 구현은 공통 `sandbox_mode`를 처리한 뒤
   Session 재개 흐름을 시작합니다.

### 4. 코드 반영

1. `src/cli_collab/agents.py`의 `CodexCliAgent.build_run_command()`을 수정했습니다.
2. Session ID가 있을 때 아래 명령을 생성하도록 변경했습니다.

   ```text
   codex exec --json --skip-git-repo-check --sandbox read-only resume <SESSION_ID> <PROMPT>
   ```

3. `src/cli_collab/preflight.py`에서 Codex 재개 자체를 차단하던 규칙을 제거했습니다.
4. 대신 새 작업과 재개 작업 모두에 `--sandbox read-only`가 있는지 동일하게 검사합니다.
5. 테스트를 갱신해 재개 명령에서 sandbox가 `resume`보다 앞에 위치하고, preflight가 이를
   허용하는지 검증했습니다.

### 5. 검증 결과

```text
python -m unittest discover -s tests -v
12 tests: OK
```

명령 생성, sandbox 위치, preflight 허용·차단, LangGraph Node 중단 규칙을 자동 테스트로
검증했습니다. 실제 Codex 모델 작업은 실행하지 않았습니다.

## 실제 재개 smoke test 결과

2026-11-18에 기존 LangGraph Thread `shared-state-smoke-001`을 사용해 실제 구독형 CLI
재개를 검증했습니다. 이 실행은 사용량이 발생하는 제공자 호출이었으며, Codex에는
`read-only`, Antigravity에는 `plan + sandbox` 정책을 적용했습니다. 파일 생성·수정·삭제와
명령 실행을 하지 말라는 검증 요청을 전달했습니다.

확인된 사실은 다음과 같습니다.

1. Codex preflight가 안전 정책을 통과했습니다.
2. 저장된 Codex Session ID를 사용한 재개 호출이 `exit_code=0`으로 종료됐습니다.
3. 이전 Codex Session ID와 이번 실행 결과의 Codex Session ID가 일치했습니다.
4. Codex는 파일 읽기·쓰기·명령 실행을 하지 않겠다고 응답했습니다.
5. Antigravity도 `exit_code=0`으로 종료됐고, 계획·sandbox 상태에서 파일 변경과 명령 실행을
   하지 않겠다고 응답했습니다.
6. SQLite checkpoint의 `agent_runs`에는 기존 두 실행 기록 뒤에 이번 Codex·Antigravity 실행
   기록이 추가됐습니다. 같은 `thread_id`의 State가 복구·갱신됐음을 확인했습니다.

이 smoke test는 명령 형식, Session 재개, preflight 통과, checkpoint 갱신을 검증합니다.
의도적인 쓰기 시도를 통해 OS 수준의 거부 동작을 시험하지는 않았습니다. 그러한 검증은
별도 Worktree 또는 테스트 VM에서만 수행합니다.

## 대체 운영 방안

Codex Session ID는 추적 정보로 Shared State에 보관합니다. 다만 안전한 재개 방식이 확정되기
실제 통합 검증에 실패하거나 향후 CLI 호환성이 달라질 때는 다음의 논리적 문맥 복구 방식을
사용합니다.

```text
같은 LangGraph thread_id
  → SQLite Checkpoint에서 이전 Shared State 복구
  → 이전 분석·검토·산출물 참조를 길이 제한된 요약으로 구성
  → 새 Codex Session을 read-only sandbox로 시작
  → 요약을 새 Session의 프롬프트에 전달
```

이 방식은 CLI 내부 Session을 물리적으로 이어 붙이지는 않지만, 멀티에이전트 협업에 필요한
공통 작업 문맥은 LangGraph Shared State로 이어 갑니다.

## 검증 완료 후 선택지

### 선택지 A: 명시적 resume sandbox 설정을 사용

1. 구현 완료: 상위 `exec` 옵션으로 `--sandbox read-only`를 `resume` 앞에 배치합니다.
2. 남은 작업: read-only 상태에서 쓰기 시도가 거부되는 실제 제공자 통합 테스트를 추가합니다.

### 선택지 B: 재개 호출을 계속 차단하고 State 기반 문맥 복구를 표준으로 사용

1. 저장된 CLI Session ID를 참조·감사용으로만 유지합니다.
2. 후속 요청에서는 새 Codex Session을 시작하고 Shared State 요약을 전달합니다.
3. State 요약의 길이 제한, 산출물 경로·hash, 사용자 요청 이력을 강화합니다.

선택지 B는 호환성 문제 또는 실제 통합 검증 실패 시의 fallback으로 유지합니다. 제공자 CLI의
동작이 바뀌어도 LangGraph의 공통 State와 SQLite checkpoint만으로 작업을 이어갈 수 있습니다.

## 완료 조건

- [x] 설치 CLI의 parser와 OpenAI 공식 소스에서 `resume` 앞 상위 `--sandbox` 옵션을 확인했다.
- [x] 선택한 재개 전략을 `agents.py`, `workflow.py`, `preflight.py`에 반영했다.
- [x] 명령 생성·정책 검사·LangGraph 흐름을 자동 테스트로 검증했다.
- [x] 실제 저장된 제공자 Session 재개와 SQLite checkpoint 갱신을 smoke test로 확인했다.
- [ ] 별도 안전 검증: Worktree 또는 테스트 VM에서 의도적인 쓰기 시도가 거부되는지 확인한다.
- [ ] 같은 `thread_id`의 후속 요청이 안전 정책 위반 없이 이전 문맥을 활용한다.
- [ ] subprocess를 실행하지 않는 단위 테스트와 실제 CLI를 사용하는 통합 검증 기준을 추가한다.
- [ ] README와 보안 모델 문서에 최종 동작을 반영한다.
