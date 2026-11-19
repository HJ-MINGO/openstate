import unittest

from cli_collab.agents import AntigravityCliAgent, CodexCliAgent
from cli_collab.preflight import validate_cli_command


class CommandContractTests(unittest.TestCase):
    def test_codex_new_turn_is_json_and_read_only(self) -> None:
        command = CodexCliAgent().build_run_command("inspect", None)
        self.assertEqual(command[:2], ["codex", "exec"])
        self.assertIn("--json", command)
        self.assertEqual(command[command.index("--sandbox") + 1], "read-only")

    def test_codex_resume_keeps_read_only_sandbox_before_subcommand(self) -> None:
        command = CodexCliAgent().build_run_command("continue", "thread-1")
        self.assertEqual(command[:2], ["codex", "exec"])
        self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
        self.assertLess(command.index("--sandbox"), command.index("resume"))
        self.assertEqual(command[command.index("resume") + 1], "thread-1")

    def test_antigravity_uses_json_sandboxed_print_mode(self) -> None:
        command = AntigravityCliAgent().build_run_command("review", None)
        self.assertEqual(command[:3], ["agy", "--print", "review"])
        self.assertIn("--output-format", command)
        self.assertIn("json", command)
        self.assertIn("--sandbox", command)
        self.assertEqual(command[command.index("--mode") + 1], "plan")

    def test_antigravity_resumes_an_explicit_conversation(self) -> None:
        command = AntigravityCliAgent().build_run_command("continue", "conversation-1")
        self.assertIn("--conversation", command)
        self.assertEqual(command[command.index("--conversation") + 1], "conversation-1")

    def test_codex_jsonl_output_is_retained_as_records(self) -> None:
        output = '{"type":"thread.started","thread_id":"t-1"}\n{"type":"item.completed"}'
        self.assertEqual(CodexCliAgent.parse_output(output)[0]["thread_id"], "t-1")
        self.assertEqual(CodexCliAgent.extract_session_id(output), "t-1")

    def test_antigravity_conversation_id_becomes_the_cli_session_id(self) -> None:
        output = '{"status":"SUCCESS","conversation_id":"c-1","response":"READY"}'
        self.assertEqual(AntigravityCliAgent.extract_session_id(output), "c-1")

    def test_preflight_allows_codex_resume_with_explicit_read_only_sandbox(self) -> None:
        command = CodexCliAgent().build_run_command("continue", "thread-1")
        result = validate_cli_command("codex", command, timeout_seconds=600)
        self.assertTrue(result.allowed)

    def test_preflight_rejects_sandbox_bypass(self) -> None:
        result = validate_cli_command(
            "antigravity", ["agy", "--sandbox", "--mode", "plan", "--no-sandbox"], timeout_seconds=60
        )
        self.assertFalse(result.allowed)


if __name__ == "__main__":
    unittest.main()
