# 프로젝트 공통 규칙

- 제공자 인증 정보는 이 저장소와 SQLite 밖에서 관리합니다. 토큰, 쿠키, keyring 데이터,
  계정 식별자, 결제 정보를 출력·복사·영속화하지 않습니다.
- 기본 실행 정책은 Codex `read-only`, Antigravity `--mode plan --sandbox`입니다.
  권한 또는 sandbox 우회 옵션을 사용하지 않습니다.
- Shared State에는 길이가 제한된 결과 요약, 산출물 경로·해시, `thread_id`,
  제공자별 세션 ID만 저장합니다. `.data/`는 Git에 커밋하지 않습니다.
- 실패하거나 timeout된 에이전트 실행은 실패로 처리합니다. 성공 결과처럼 다음
  에이전트에 인계하지 않습니다.

인증, State 영속화, CLI 권한, MCP, scraping, 외부 도구를 변경할 때는
`docs/security-model.md`를 읽습니다. MCP 서버를 추가하거나 수정할 때는
`.agents/skills/mcp-security/SKILL.md`를 읽습니다. 실제 제공자 실행으로
사용량이 발생하거나 파일 변경 가능성이 있을 때는
`.agents/skills/live-agent-run/SKILL.md`를 읽습니다.
