"""CLI 제공자와 무관하게 사용하는 실행 결과 자료형을 정의합니다."""


from __future__ import annotations


from dataclasses import asdict, dataclass

from typing import Any


@dataclass(frozen=True)
class AgentResult:
    """CLI 한 번의 실행 결과를 제공자 중립적으로 보관합니다.

    이 객체는 subprocess 경계 바로 뒤에서 만들어집니다. workflow는 이 객체에서
    Session ID와 요약만 골라 Shared State에 저장합니다.
    """


    agent: str

    command: tuple[str, ...]

    exit_code: int

    stdout: str

    stderr: str

    parsed_output: Any | None

    session_id: str | None = None

    timed_out: bool = False

    def to_dict(self) -> dict[str, Any]:
        """CLI 디버그 도구가 출력할 수 있도록 dataclass를 일반 dict로 변환합니다."""
        return asdict(self)


@dataclass(frozen=True)
class AgentCapabilities:
    """현재 설치된 CLI에서 확인한 기능만 표현합니다.

    제공자 전체의 영구 보장이 아니라, 이 Adapter 구현이 의존하는 명령행 기능 계약입니다.
    """


    structured_output: bool

    resumable_sessions: bool

    auto_approves_writes: bool

    supports_sandbox: bool

    def to_dict(self) -> dict[str, bool]:
        """probe 결과에 포함할 수 있도록 기능 정보를 일반 dict로 변환합니다."""
        return asdict(self)
