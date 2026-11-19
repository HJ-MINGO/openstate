"""구독형 CLI를 LangGraph Node에서 호출할 수 있게 만드는 Adapter 계층입니다."""

# 최신 타입 표기를 Python 3.11에서도 안전하게 사용합니다.
from __future__ import annotations

# json은 Codex JSONL과 Antigravity JSON 출력을 Python 자료형으로 바꿉니다.
import json
# os는 Windows의 LOCALAPPDATA 같은 운영체제 환경 변수를 읽습니다.
import os
# shutil.which는 PATH에서 CLI 실행 파일을 찾습니다.
import shutil
# subprocess는 Python에서 실제 Codex·Antigravity 프로세스를 실행합니다.
import subprocess
# ABC와 abstractmethod는 모든 제공자 Adapter가 지켜야 할 공통 인터페이스를 정의합니다.
from abc import ABC, abstractmethod
# Path는 Windows·Linux 경로를 운영체제 독립적으로 다룹니다.
from pathlib import Path
# Any는 제공자마다 다른 JSON 출력 모양을 표현할 때만 사용합니다.
from typing import Any

# AgentResult와 AgentCapabilities는 이 프로젝트가 정의한 제공자 중립 자료형입니다.
from .models import AgentCapabilities, AgentResult
# preflight는 실제 프로세스 시작 전에 안전한 CLI 옵션인지 검사합니다.
from .preflight import PreflightResult, validate_cli_command


class CliAgent(ABC):
    """모든 CLI Agent가 구현하는 공통 실행 흐름입니다.

    하위 클래스는 명령 인자만 제공하고, 이 클래스는 실행 파일 탐색·preflight·timeout·출력
    파싱을 공통 처리합니다.
    """

    # Shared State의 agent_sessions에서 사용할 Agent 이름입니다.
    name: str
    # PATH에서 찾을 기본 실행 파일 이름입니다.
    executable: str
    # 현재 설치 CLI에서 확인한 기능 계약입니다.
    capabilities: AgentCapabilities

    def available(self) -> bool:
        """CLI 실행 파일을 찾을 수 있는지 반환합니다. 제공자 호출은 하지 않습니다."""
        return self._resolve_executable() is not None

    def _resolve_executable(self) -> str | None:
        """Return a program Python can execute, not a PowerShell-only shim."""
        # Windows는 .exe와 .cmd shim을 모두 고려해야 합니다.
        if os.name == "nt":
            candidates = [f"{self.executable}.exe", f"{self.executable}.cmd", self.executable]
            # Antigravity는 PATH가 갱신되지 않은 경우 기본 설치 경로도 확인합니다.
            if self.executable == "agy" and (local_app_data := os.getenv("LOCALAPPDATA")):
                candidates.append(str(Path(local_app_data) / "agy" / "bin" / "agy.exe"))
        else:
            candidates = [self.executable]

        # 후보를 순서대로 확인해 Python subprocess가 실행 가능한 실제 경로를 반환합니다.
        for candidate in candidates:
            if Path(candidate).is_file():
                return candidate
            if path := shutil.which(candidate):
                return path
        return None

    def probe(self, *, timeout_seconds: int = 20) -> AgentResult:
        """`--help`만 호출해 설치 여부와 기본 명령 접근성을 확인합니다."""
        executable = self._resolve_executable()
        if executable is None:
            return self._missing_executable_result()
        return self._execute([executable, "--help"], timeout_seconds)

    @abstractmethod
    def build_run_command(self, prompt: str, session_id: str | None) -> list[str]:
        """Build a bounded, non-interactive command for one agent turn."""

    def run(
        self, prompt: str, *, session_id: str | None = None, timeout_seconds: int = 600
    ) -> AgentResult:
        """안전 검사 뒤 CLI 한 turn을 동기 실행하고 구조화된 결과를 반환합니다."""
        # 빈 프롬프트는 제공자 호출 전에 즉시 개발자 오류로 처리합니다.
        if not prompt.strip():
            raise ValueError("prompt must not be empty")
        # Session ID가 있어도 제공자가 재개를 지원하지 않으면 잘못된 호출입니다.
        if session_id and not self.capabilities.resumable_sessions:
            raise ValueError(f"{self.name} does not support session resume in this CLI version")
        # 현재 운영체제에서 실행 가능한 CLI 경로를 찾습니다.
        executable = self._resolve_executable()
        if executable is None:
            return self._missing_executable_result()
        # 하위 Adapter가 제공자별 명령 인자 목록을 만듭니다.
        command = self.build_run_command(prompt, session_id, executable)
        # Node를 우회해 직접 run()을 불러도 안전 정책이 적용되도록 재검사합니다.
        preflight = validate_cli_command(self.name, command, timeout_seconds=timeout_seconds)
        if not preflight.allowed:
            return AgentResult(
                agent=self.name,
                command=tuple(command),
                exit_code=126,
                stdout="",
                stderr=f"preflight rejected: {preflight.reason}",
                parsed_output=None,
            )
        # 검사를 통과한 경우에만 실제 subprocess를 시작합니다.
        return self._execute(command, timeout_seconds)

    def preflight(
        self, prompt: str, *, session_id: str | None = None, timeout_seconds: int = 600
    ) -> PreflightResult:
        """Node가 subprocess 직전에 정책 결과를 State에 기록할 수 있게 합니다."""
        # 실행 파일 탐색 전에도 옵션 자체는 검증할 수 있으므로 기본 실행 파일 이름으로 명령을 만듭니다.
        command = self.build_run_command(prompt, session_id)
        return validate_cli_command(self.name, command, timeout_seconds=timeout_seconds)

    def _missing_executable_result(self) -> AgentResult:
        """설치되지 않은 CLI를 예외 대신 일관된 실패 결과로 변환합니다."""
        return AgentResult(
            agent=self.name,
            command=(self.executable,),
            exit_code=127,
            stdout="",
            stderr=f"{self.executable} executable not found",
            parsed_output=None,
        )

    def _execute(self, command: list[str], timeout_seconds: int) -> AgentResult:
        """shell을 거치지 않고 인자 목록 그대로 CLI를 실행합니다."""
        try:
            # shell=False가 기본값이므로 prompt는 shell 코드로 해석되지 않습니다.
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                check=False,
            )
        # timeout은 Graph가 다음 Agent에 성공 결과를 넘기지 않도록 명시적 실패로 바꿉니다.
        except subprocess.TimeoutExpired as exc:
            return AgentResult(
                agent=self.name,
                command=tuple(command),
                exit_code=-1,
                stdout=exc.stdout or "",
                stderr=exc.stderr or "",
                parsed_output=None,
                timed_out=True,
            )
        # 실행 권한·경로·운영체제 오류도 구조화된 실패로 보존합니다.
        except OSError as exc:
            return AgentResult(
                agent=self.name,
                command=tuple(command),
                exit_code=127,
                stdout="",
                stderr=str(exc),
                parsed_output=None,
            )

        # 정상 종료 여부와 관계없이 stdout을 파싱하고 Session ID를 추출합니다.
        return AgentResult(
            agent=self.name,
            command=tuple(command),
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            parsed_output=self.parse_output(completed.stdout),
            session_id=self.extract_session_id(completed.stdout),
        )

    @staticmethod
    def parse_output(stdout: str) -> Any | None:
        """단일 JSON 또는 줄마다 JSON인 JSONL을 파싱합니다."""
        # Antigravity처럼 전체 출력이 하나의 JSON인 경우를 먼저 처리합니다.
        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            # Codex처럼 이벤트가 한 줄씩 오는 JSONL을 차례로 읽습니다.
            records: list[dict[str, Any]] = []
            for line in stdout.splitlines():
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    return None
                if not isinstance(value, dict):
                    return None
                records.append(value)
            return records or None

    @staticmethod
    def extract_session_id(stdout: str) -> str | None:
        """제공자 출력의 알려진 Session ID 키를 찾아 공통 문자열로 반환합니다."""
        parsed = CliAgent.parse_output(stdout)
        # JSONL은 여러 record, 단일 JSON은 하나의 record로 통일합니다.
        records = parsed if isinstance(parsed, list) else [parsed]
        for record in records:
            if not isinstance(record, dict):
                continue
            # 제공자별 키 이름 차이를 여기에서만 흡수합니다.
            for key in ("session_id", "thread_id", "conversation_id"):
                value = record.get(key)
                if isinstance(value, str):
                    return value
        return None


class CodexCliAgent(CliAgent):
    """OpenAI Codex CLI의 비대화형 `codex exec` Adapter입니다."""

    # Shared State와 preflight에서 식별하는 고정 이름입니다.
    name = "codex"
    # 운영체제 PATH에서 찾을 실행 파일 기본 이름입니다.
    executable = "codex"
    # 현재 Adapter가 사용하는 Codex CLI 기능만 명시합니다.
    capabilities = AgentCapabilities(
        structured_output=True,
        resumable_sessions=True,
        auto_approves_writes=False,
        supports_sandbox=True,
    )

    def build_run_command(
        self, prompt: str, session_id: str | None, executable: str | None = None
    ) -> list[str]:
        """새 turn 또는 기존 Codex Session 재개용 안전 명령을 만듭니다."""
        executable = executable or self.executable
        if session_id:
            # --sandbox는 resume의 하위 옵션이 아니라 exec의 공통 옵션이므로 resume보다 앞에 둡니다.
            return [
                executable,
                "exec",
                "--json",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "resume",
                session_id,
                prompt,
            ]
        # 새 Session도 JSON 출력과 read-only sandbox를 기본값으로 사용합니다.
        return [
            executable,
            "exec",
            "--json",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            prompt,
        ]


class AntigravityCliAgent(CliAgent):
    """Google's supported consumer successor to the legacy Gemini CLI."""

    name = "antigravity"
    executable = "agy"
    capabilities = AgentCapabilities(
        structured_output=True,
        resumable_sessions=True,
        auto_approves_writes=False,
        supports_sandbox=True,
    )

    def build_run_command(
        self, prompt: str, session_id: str | None, executable: str | None = None
    ) -> list[str]:
        """Antigravity print mode의 JSON·sandbox·plan mode 명령을 만듭니다."""
        # --print는 비대화형 응답을 stdout으로 받고, --output-format json은 결과 파싱을 가능하게 합니다.
        command = [
            executable or self.executable,
            "--print",
            prompt,
            "--output-format",
            "json",
            "--sandbox",
            "--mode",
            "plan",
            "--print-timeout",
            "10m",
        ]
        # 이전 conversation ID가 있으면 Antigravity 자체 대화를 재개합니다.
        if session_id:
            command.extend(["--conversation", session_id])
        return command
