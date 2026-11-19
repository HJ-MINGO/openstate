import unittest
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver

from cli_collab.models import AgentCapabilities, AgentResult
from cli_collab.agents import CliAgent
from cli_collab.workflow import build_workflow


class FakeAgent:
    capabilities = AgentCapabilities(True, True, False, True)

    def __init__(self, name: str):
        self.name = name

    def run(self, prompt: str, *, session_id: str | None = None):
        return AgentResult(self.name, (self.name,), 0, '{"response":"' + self.name + ' done"}', "", {"response": self.name + " done"}, self.name + "-session")


class ScriptedAgent(FakeAgent):
    def __init__(self, name: str, responses: list[str]):
        super().__init__(name)
        self.responses = iter(responses)
        self.prompts: list[str] = []

    def run(self, prompt: str, *, session_id: str | None = None):
        self.prompts.append(prompt)
        response = next(self.responses)
        return AgentResult(
            self.name,
            (self.name,),
            0,
            '{"response":"done"}',
            "",
            {"response": response},
            self.name + "-session",
        )


class UnsafeCodexAgent(CliAgent):
    """명령을 실제 실행하지 않아도 Node의 preflight 차단을 검증하기 위한 Adapter입니다."""

    name = "codex"
    executable = "codex"
    capabilities = AgentCapabilities(True, True, False, True)

    def build_run_command(
        self, prompt: str, session_id: str | None, executable: str | None = None
    ) -> list[str]:
        return [executable or self.executable, "exec", prompt]


class WorkflowTests(unittest.TestCase):
    def test_handoff_and_checkpoint_resume(self) -> None:
        app = build_workflow(InMemorySaver(), codex=FakeAgent("codex"), antigravity=FakeAgent("antigravity"))
        config = {"configurable": {"thread_id": "test-thread"}}
        result = app.invoke({"user_request": "review yaml"}, config)
        self.assertEqual([run["agent"] for run in result["agent_runs"]], ["codex", "antigravity"])
        self.assertEqual(result["agent_sessions"]["codex"], "codex-session")
        self.assertEqual(app.get_state(config).values["user_request"], "review yaml")

    def test_preflight_stops_graph_before_unsafe_cli_call(self) -> None:
        app = build_workflow(
            InMemorySaver(), codex=UnsafeCodexAgent(), antigravity=FakeAgent("antigravity")
        )
        result = app.invoke({"user_request": "review yaml"}, {"configurable": {"thread_id": "blocked-thread"}})
        self.assertEqual(result["status"], "failed")
        self.assertEqual([run["agent"] for run in result["agent_runs"]], ["codex"])
        self.assertEqual(result["agent_runs"][0]["exit_code"], 126)

    def test_sqlite_checkpoint_survives_checkpointer_reopen(self) -> None:
        """SQLite 파일을 닫고 다시 열어도 같은 thread의 State를 복구한다."""
        # Windows의 시스템 TEMP가 접근 불가한 위치를 가리킬 수 있으므로,
        # 프로젝트가 관리하고 Git에서 제외하는 .data 아래에 테스트 DB를 둡니다.
        data_directory = Path(__file__).resolve().parents[1] / ".data"
        data_directory.mkdir(exist_ok=True)
        database = data_directory / "test-checkpoints.sqlite"
        config = {"configurable": {"thread_id": "persisted-thread"}}

        # 첫 프로세스 실행을 가정한 checkpointer 인스턴스입니다.
        with SqliteSaver.from_conn_string(str(database)) as first_checkpointer:
            first_checkpointer.delete_thread("persisted-thread")
            first_app = build_workflow(
                first_checkpointer,
                codex=FakeAgent("codex"),
                antigravity=FakeAgent("antigravity"),
            )
            first_app.invoke({"user_request": "첫 요청"}, config)

        # 프로그램을 다시 시작한 것처럼 새로운 checkpointer와 graph를 만듭니다.
        with SqliteSaver.from_conn_string(str(database)) as reopened_checkpointer:
            reopened_app = build_workflow(
                reopened_checkpointer,
                codex=FakeAgent("codex"),
                antigravity=FakeAgent("antigravity"),
            )
            restored = reopened_app.get_state(config).values
            self.assertEqual(restored["user_request"], "첫 요청")
            self.assertEqual(restored["agent_sessions"]["codex"], "codex-session")
            self.assertEqual(
                [run["agent"] for run in restored["agent_runs"]],
                ["codex", "antigravity"],
            )
            reopened_checkpointer.delete_thread("persisted-thread")

    def test_review_rework_loop_is_bounded_and_hands_feedback_to_codex(self) -> None:
        codex = ScriptedAgent("codex", ["initial plan", "revised plan"])
        reviewer = ScriptedAgent(
            "antigravity",
            ["missing resource limits\nREVIEW_DECISION: REWORK", "looks good\nREVIEW_DECISION: APPROVE"],
        )
        app = build_workflow(InMemorySaver(), codex=codex, antigravity=reviewer)
        result = app.invoke(
            {"user_request": "review deployment", "max_rework": 1},
            {"configurable": {"thread_id": "review-thread"}},
        )
        self.assertEqual(
            [run["agent"] for run in result["agent_runs"]],
            ["codex", "antigravity", "codex", "antigravity"],
        )
        self.assertEqual(result["review"]["decision"], "approve")
        self.assertEqual(result["rework_count"], 1)
        self.assertIn("missing resource limits", codex.prompts[1])

    def test_unknown_review_requires_user_approval(self) -> None:
        app = build_workflow(
            InMemorySaver(),
            codex=ScriptedAgent("codex", ["initial plan"]),
            antigravity=ScriptedAgent("antigravity", ["review format missing"]),
        )
        result = app.invoke(
            {"user_request": "review deployment"},
            {"configurable": {"thread_id": "unknown-review-thread"}},
        )
        self.assertEqual(result["status"], "needs_approval")
        self.assertEqual(result["review"]["decision"], "unknown")
