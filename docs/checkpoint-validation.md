# SQLite checkpoint 복구 검증

## 목표

이 문서는 LangGraph `thread_id`가 SQLite checkpoint와 어떻게 연결되는지 검증한다.
목표는 CLI 제공자 계정이나 실제 모델 호출 없이도, 프로그램을 다시 시작한 뒤 이전 Shared State를
복구할 수 있음을 자동 테스트로 확인하는 것이다.

## 검증 흐름

```text
첫 번째 SqliteSaver
  → thread_id = persisted-thread로 Codex·Antigravity Fake Adapter 실행
  → user_request, agent_sessions, agent_runs를 SQLite에 저장
  → checkpointer 닫기

새로운 SqliteSaver
  → 같은 SQLite 파일 열기
  → 같은 thread_id의 State 읽기
  → 이전 State와 Session ID, 실행 기록 확인
```

`SqliteSaver`는 LangGraph State를 저장하는 저장소 구현체다. 이 테스트에서 새
`SqliteSaver`와 새 Graph를 만드는 것은 Python 프로그램을 재시작한 상황을 모사한다.

## 실행 명령

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 기대 결과

`test_sqlite_checkpoint_survives_checkpointer_reopen`이 통과해야 한다. 이 테스트는 다음만
보장한다.

- 같은 `thread_id`로 `user_request`를 복구한다.
- Codex의 CLI Session ID를 포함한 `agent_sessions`를 복구한다.
- 이전 `agent_runs`를 보존한다.

후속 요청을 실행해 이전 실행 이력 뒤에 새 이력을 추가하는 동작은 실제 제공자 smoke test에서
별도로 확인한다. 이 단위 테스트는 외부 CLI와 무관한 SQLite 복구 계약만 검증한다.

이 테스트는 Fake Adapter를 사용한다. 실제 Codex·Antigravity 인증, 제공자 Session 재개,
파일 시스템 권한은 별도의 live smoke test에서 검증한다.
