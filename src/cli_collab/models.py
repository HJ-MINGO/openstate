"""CLI 제공자와 무관하게 사용하는 실행 결과 자료형을 정의합니다."""

# Python 3.11에서도 최신 타입 표기법을 문자열 지연 평가로 안전하게 사용합니다.
from __future__ import annotations

# dataclass는 반복적인 생성자·비교 메서드를 자동으로 만들고, asdict는 결과를 JSON용 dict로 바꿉니다.
from dataclasses import asdict, dataclass
# Any는 제공자마다 달라지는 JSON 파싱 결과를 표현할 때만 사용합니다.
from typing import Any


@dataclass(frozen=True)
class AgentResult:
    """CLI 한 번의 실행 결과를 제공자 중립적으로 보관합니다.

    이 객체는 subprocess 경계 바로 뒤에서 만들어집니다. workflow는 이 객체에서
    Session ID와 요약만 골라 Shared State에 저장합니다.
    """

    # 실행한 Adapter 이름입니다. 예: "codex", "antigravity".
    agent: str
    # 실제 subprocess에 전달한 인자 목록입니다. 실행 재현과 오류 분석에 사용합니다.
    command: tuple[str, ...]
    # 프로세스 종료 코드입니다. 0은 성공, 음수는 Python timeout 처리, 127은 실행 파일 오류입니다.
    exit_code: int
    # CLI 표준 출력 원문입니다. Shared State에는 직접 저장하지 않고 보안 요약만 저장합니다.
    stdout: str
    # CLI 표준 오류 원문입니다. 실패 원인을 보존합니다.
    stderr: str
    # JSON 또는 JSONL로 파싱한 출력입니다. 형식이 맞지 않으면 None입니다.
    parsed_output: Any | None
    # 제공자 내부 대화 Session ID입니다. LangGraph thread_id와 다른 값입니다.
    session_id: str | None = None
    # subprocess timeout이 발생했는지 나타냅니다.
    timed_out: bool = False

    def to_dict(self) -> dict[str, Any]:
        """CLI 디버그 도구가 출력할 수 있도록 dataclass를 일반 dict로 변환합니다."""
        return asdict(self)


@dataclass(frozen=True)
class AgentCapabilities:
    """현재 설치된 CLI에서 확인한 기능만 표현합니다.

    제공자 전체의 영구 보장이 아니라, 이 Adapter 구현이 의존하는 명령행 기능 계약입니다.
    """

    # JSON 또는 JSONL처럼 기계가 파싱할 수 있는 출력을 요청할 수 있는지 나타냅니다.
    structured_output: bool
    # 이전 CLI 대화를 Session ID로 재개할 수 있는지 나타냅니다.
    resumable_sessions: bool
    # 파일 쓰기를 자동 승인하지 않는 안전 기본값인지 나타냅니다.
    auto_approves_writes: bool
    # 제공자가 제공하는 sandbox 옵션이 있는지 나타냅니다.
    supports_sandbox: bool

    def to_dict(self) -> dict[str, bool]:
        """probe 결과에 포함할 수 있도록 기능 정보를 일반 dict로 변환합니다."""
        return asdict(self)
