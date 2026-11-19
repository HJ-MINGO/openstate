# 보안 모델

## 인증 정보 경계

Codex와 Antigravity는 각 제공자가 지원하는 로그인 및 운영체제 keyring 흐름으로 인증합니다.
Python 오케스트레이터는 CLI의 subprocess 실행 결과만 받습니다. 제공자의 인증 정보 폴더,
브라우저 프로필, cookie, token, key 파일은 읽거나 복사하거나 분석하지 않습니다.

## Shared State 경계

SQLite에는 `thread_id`, 길이를 제한한 요약, 산출물 참조, 실행 상태, 제공자 Session ID만
저장합니다. 인증 정보, 제공자의 전체 대화 기록, 길이 제한이 없는 CLI 출력은 저장하지
않습니다. 큰 출력은 산출물 파일로 보관하고, State에는 경로·hash·요약만 남깁니다.

## 실행 경계

Codex는 기본적으로 `read-only`로 실행합니다. Antigravity는 `--mode plan --sandbox`로
실행합니다. 파일 변경이 필요한 작업은 사용자가 명시적으로 요청한 뒤에만 쓰기 가능한
실행 방식을 검토합니다. 모든 CLI 호출에는 timeout을 둡니다.

`src/cli_collab/preflight.py`는 CLI 호출 직전에 명령의 timeout, sandbox, 실행 mode,
우회 옵션을 검사합니다. 검증에 실패하면 subprocess를 시작하지 않습니다. Codex Session
재개는 상위 `exec` 옵션을 `resume` 앞에 배치해 `read-only sandbox`를 명시합니다.

```text
codex exec --json --skip-git-repo-check --sandbox read-only resume <SESSION_ID> <PROMPT>
```

## 도구 경계

중앙에서 순서를 통제해야 하는 작업은 LangGraph 함수로 구현합니다. 여러 에이전트가
자율적으로 같은 도구에 접근해야 할 때만 MCP를 추가합니다. MCP 도구마다 좁은 입력 schema,
allowlist, timeout, 최소 권한, 성공·거부 테스트가 필요합니다. 외부 서비스 인증 정보는
제공자의 keyring 또는 secret manager에 보관하며 Shared State에는 저장하지 않습니다.

## 실제 실행 검증 기준

실제 실행 검증은 프로세스가 종료되고, 같은 `thread_id`로 영속화된 checkpoint를 다시 읽을
수 있을 때 완료입니다. 각 결과는 실제 제공자 실행인지, Fake Adapter 테스트인지, 제공자를
사용할 수 없는 상태인지 구분해 기록합니다.
