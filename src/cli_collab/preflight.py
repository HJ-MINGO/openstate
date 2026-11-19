"""CLI 실행 전에 적용하는 코드 수준의 안전 정책입니다.

Skill 문서는 사람이 읽는 절차서이고, 이 모듈은 그중 반드시 지켜야 하는
실행 규칙을 코드로 강제합니다. 검증에 실패하면 subprocess를 실행하지 않습니다.
"""

from __future__ import annotations

# dataclass는 검사 결과를 변경 불가능한 작은 값 객체로 표현합니다.
from dataclasses import dataclass


# 한 번의 CLI 실행이 점유할 수 있는 최대 시간(초)입니다.
MAX_TIMEOUT_SECONDS = 600
# 이 인자는 제공자 sandbox 또는 승인 절차를 우회하므로 어떤 Adapter에도 허용하지 않습니다.
_FORBIDDEN_ARGUMENTS = frozenset(
    {"--dangerously-bypass-approvals-and-sandbox", "--yolo", "--no-sandbox"}
)


@dataclass(frozen=True)
class PreflightResult:
    """한 번의 CLI 호출에 대한 사전 검증 결과입니다."""

    # 실행을 계속해도 되는지 나타냅니다.
    allowed: bool
    # 허용 또는 거부한 이유이며 workflow의 agent_runs에도 기록됩니다.
    reason: str


def allow(reason: str = "안전 정책을 통과했습니다.") -> PreflightResult:
    return PreflightResult(allowed=True, reason=reason)


def deny(reason: str) -> PreflightResult:
    return PreflightResult(allowed=False, reason=reason)


def validate_cli_command(
    agent_name: str, command: list[str], *, timeout_seconds: int
) -> PreflightResult:
    """기본 실행 정책을 만족하는 CLI 명령만 허용합니다.

    이 함수는 허용 경로·사용자 승인처럼 작업별로 달라지는 정책보다 먼저,
    어떤 작업에도 적용되는 sandbox·plan mode·timeout 규칙을 검사합니다.
    """

    if not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS:
        return deny(f"timeout은 1~{MAX_TIMEOUT_SECONDS}초 범위여야 합니다.")
    if any(argument in _FORBIDDEN_ARGUMENTS for argument in command):
        return deny("sandbox 또는 승인 절차를 우회하는 옵션은 허용하지 않습니다.")

    if agent_name == "codex":
        try:
            sandbox_index = command.index("--sandbox")
            if command[sandbox_index + 1] != "read-only":
                return deny("Codex는 read-only sandbox에서만 실행할 수 있습니다.")
        except (ValueError, IndexError):
            return deny("Codex 호출에 read-only sandbox가 없습니다.")

    if agent_name == "antigravity":
        if "--sandbox" not in command:
            return deny("Antigravity 호출에는 --sandbox가 필요합니다.")
        try:
            mode_index = command.index("--mode")
            if command[mode_index + 1] != "plan":
                return deny("Antigravity는 plan mode에서만 실행할 수 있습니다.")
        except (ValueError, IndexError):
            return deny("Antigravity 호출에는 --mode plan이 필요합니다.")

    return allow()
