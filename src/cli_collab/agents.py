from __future__ import annotations


import json

import os

import shutil

import subprocess

from abc import ABC, abstractmethod

from pathlib import Path

from typing import Any


from .models import AgentCapabilities, AgentResult

from .preflight import PreflightResult, validate_cli_command


class CliAgent(ABC):

    name: str

    executable: str

    capabilities: AgentCapabilities

    def available(self) -> bool:
        """CLI 실행 파일을 찾을 수 있는지 반환합니다. 제공자 호출은 하지 않습니다."""
        return self._resolve_executable() is not None

    def _resolve_executable(self) -> str | None:
        """Return a program Python can execute, not a PowerShell-only shim."""

        if os.name == "nt":
            candidates = [f"{self.executable}.exe", f"{self.executable}.cmd", self.executable]

            if self.executable == "agy" and (local_app_data := os.getenv("LOCALAPPDATA")):
                candidates.append(str(Path(local_app_data) / "agy" / "bin" / "agy.exe"))
        else:
            candidates = [self.executable]


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

        if not prompt.strip():
            raise ValueError("prompt must not be empty")

        if session_id and not self.capabilities.resumable_sessions:
            raise ValueError(f"{self.name} does not support session resume in this CLI version")

        executable = self._resolve_executable()
        if executable is None:
            return self._missing_executable_result()

        command = self.build_run_command(prompt, session_id, executable)

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

        return self._execute(command, timeout_seconds)

    def preflight(
        self, prompt: str, *, session_id: str | None = None, timeout_seconds: int = 600
    ) -> PreflightResult:
        """Node가 subprocess 직전에 정책 결과를 State에 기록할 수 있게 합니다."""

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

            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                check=False,
            )

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

        except OSError as exc:
            return AgentResult(
                agent=self.name,
                command=tuple(command),
                exit_code=127,
                stdout="",
                stderr=str(exc),
                parsed_output=None,
            )


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

        try:
            return json.loads(stdout)
        except json.JSONDecodeError:

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

        records = parsed if isinstance(parsed, list) else [parsed]
        for record in records:
            if not isinstance(record, dict):
                continue

            for key in ("session_id", "thread_id", "conversation_id"):
                value = record.get(key)
                if isinstance(value, str):
                    return value
        return None


class CodexCliAgent(CliAgent):
    """OpenAI Codex CLI의 비대화형 `codex exec` Adapter입니다."""


    name = "codex"

    executable = "codex"

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

        if session_id:
            command.extend(["--conversation", session_id])
        return command
