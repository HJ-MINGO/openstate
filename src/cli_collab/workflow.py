"""LangGraph Shared State와 Codex·Antigravity 협업 루프를 정의합니다."""


from __future__ import annotations


import operator

import re

from typing import Annotated, Any, Literal, TypedDict


from langchain_core.messages import AIMessage, BaseMessage

from langgraph.graph import END, START, StateGraph, add_messages


from .agents import AntigravityCliAgent, CliAgent, CodexCliAgent
from .security import redact_for_state


class AgentRun(TypedDict):
    """한 Node가 Agent를 한 번 호출한 뒤 남기는 짧은 실행 이력입니다."""
    agent: str
    exit_code: int
    session_id: str | None
    summary: str
    preflight: str


class ArtifactRef(TypedDict):
    """긴 산출물 본문 대신 State에 저장하는 참조 정보입니다."""

    path: str
    sha256: str
    summary: str


class Review(TypedDict):
    """검토 에이전트가 만든 재작업 판단입니다."""

    decision: Literal["approve", "rework", "unknown"]
    feedback: str


class SharedState(TypedDict, total=False):
    """Application-owned collaboration state, persisted by LangGraph."""


    user_request: str

    messages: Annotated[list[BaseMessage], add_messages]

    agent_sessions: dict[str, str]

    agent_runs: Annotated[list[AgentRun], operator.add]

    modified_files: list[str]

    artifact_refs: Annotated[list[ArtifactRef], operator.add]

    review: Review

    rework_count: int

    max_rework: int
    current_agent: str
    status: Literal["running", "completed", "failed", "needs_approval"]


def _summary(result: Any, limit: int = 2_000) -> str:
    """제공자 출력에서 사람이 읽을 최종 응답만 골라 State용 요약으로 만듭니다."""

    if isinstance(result.parsed_output, dict):
        text = result.parsed_output.get("response") or result.parsed_output.get("result")
        if isinstance(text, str):
            return redact_for_state(text, limit)

    if isinstance(result.parsed_output, list):
        for record in reversed(result.parsed_output):
            item = record.get("item") if isinstance(record, dict) else None
            if isinstance(item, dict) and item.get("type") == "agent_message":
                text = item.get("text")
                if isinstance(text, str):
                    return redact_for_state(text, limit)

    return redact_for_state(result.stdout or result.stderr, limit)


def _node(agent: CliAgent):
    """이전 단순 순차 Graph에서 쓰던 공통 Node 구현입니다.

    현재 Graph는 역할별 prompt가 필요한 _implementation_node와 _review_node를 사용합니다.
    """
    def run(state: SharedState) -> dict[str, Any]:

        sessions = state.get("agent_sessions", {})
        prior = "\n\n".join(run["summary"] for run in state.get("agent_runs", [])[-2:])
        prompt = state["user_request"]
        if prior:
            prompt += f"\n\nPrevious agent hand-off:\n{prior}"
        preflight_reason = "Fake Adapter 테스트: preflight를 생략했습니다."
        if isinstance(agent, CliAgent):
            preflight = agent.preflight(prompt, session_id=sessions.get(agent.name))
            preflight_reason = preflight.reason
            if not preflight.allowed:
                run_record: AgentRun = {
                    "agent": agent.name,
                    "exit_code": 126,
                    "session_id": sessions.get(agent.name),
                    "summary": preflight.reason,
                    "preflight": preflight_reason,
                }
                return {
                    "messages": [AIMessage(content=preflight.reason, name=agent.name)],
                    "agent_runs": [run_record],
                    "current_agent": agent.name,
                    "status": "failed",
                }
        result = agent.run(prompt, session_id=sessions.get(agent.name))
        summary = _summary(result)
        updated_sessions = dict(sessions)
        if result.session_id:
            updated_sessions[agent.name] = result.session_id
        run_record: AgentRun = {
            "agent": agent.name,
            "exit_code": result.exit_code,
            "session_id": result.session_id,
            "summary": summary,
            "preflight": preflight_reason,
        }
        return {
            "messages": [AIMessage(content=summary, name=agent.name)],
            "agent_sessions": updated_sessions,
            "agent_runs": [run_record],
            "current_agent": agent.name,
            "status": "completed" if result.exit_code == 0 else "failed",
        }

    return run


def _implementation_node(agent: CliAgent, *, rework: bool = False):
    """Codex가 분석·수정 제안을 만들고, 필요하면 검토 피드백을 반영합니다."""

    def run(state: SharedState) -> dict[str, Any]:

        sessions = state.get("agent_sessions", {})

        prior = "\n\n".join(item["summary"] for item in state.get("agent_runs", [])[-2:])
        prompt = state["user_request"]
        if prior:
            prompt += f"\n\nPrevious agent hand-off:\n{prior}"

        if rework:
            feedback = state.get("review", {}).get("feedback", "")
            prompt += f"\n\nReviewer feedback to address:\n{feedback}"
        prompt += (
            "\n\nYou are the implementation agent. Work in analysis mode only: do not modify files "
            "or execute commands. State proposed changes and affected file paths."
        )

        preflight_reason = "Fake Adapter test: preflight skipped."
        if isinstance(agent, CliAgent):
            preflight = agent.preflight(prompt, session_id=sessions.get(agent.name))
            preflight_reason = preflight.reason
            if not preflight.allowed:
                return {
                    "messages": [AIMessage(content=preflight.reason, name=agent.name)],
                    "agent_runs": [{
                        "agent": agent.name,
                        "exit_code": 126,
                        "session_id": sessions.get(agent.name),
                        "summary": preflight.reason,
                        "preflight": preflight_reason,
                    }],
                    "current_agent": agent.name,
                    "status": "failed",
                }

        result = agent.run(prompt, session_id=sessions.get(agent.name))
        summary = _summary(result)

        updated_sessions = dict(sessions)
        if result.session_id:
            updated_sessions[agent.name] = result.session_id
        return {
            "messages": [AIMessage(content=summary, name=agent.name)],
            "agent_sessions": updated_sessions,
            "agent_runs": [{
                "agent": agent.name,
                "exit_code": result.exit_code,
                "session_id": result.session_id,
                "summary": summary,
                "preflight": preflight_reason,
            }],
            "current_agent": agent.name,
            "status": "completed" if result.exit_code == 0 else "failed",
        }

    return run


def _review_decision(summary: str) -> Review:
    """Antigravity 응답의 REVIEW_DECISION 표식을 State용 enum으로 바꿉니다."""
    match = re.search(r"REVIEW_DECISION\s*:\s*(APPROVE|REWORK)\b", summary, re.IGNORECASE)

    if match is None:
        return {"decision": "unknown", "feedback": summary}
    return {
        "decision": "approve" if match.group(1).upper() == "APPROVE" else "rework",
        "feedback": summary,
    }


def _review_node(agent: CliAgent):
    """Antigravity가 Codex 결과를 검토하고 재작업·승인을 결정하는 Node입니다."""
    def run(state: SharedState) -> dict[str, Any]:

        sessions = state.get("agent_sessions", {})
        prior = "\n\n".join(item["summary"] for item in state.get("agent_runs", [])[-2:])
        prompt = (
            f"Original request:\n{state['user_request']}\n\n"
            f"Implementation hand-off:\n{prior}\n\n"
            "You are the review agent. Review correctness, safety, and missing constraints. "
            "Do not modify files or execute commands. End with exactly one line: "
            "REVIEW_DECISION: APPROVE or REVIEW_DECISION: REWORK."
        )
        preflight_reason = "Fake Adapter test: preflight skipped."
        if isinstance(agent, CliAgent):
            preflight = agent.preflight(prompt, session_id=sessions.get(agent.name))
            preflight_reason = preflight.reason
            if not preflight.allowed:
                return {
                    "messages": [AIMessage(content=preflight.reason, name=agent.name)],
                    "agent_runs": [{
                        "agent": agent.name,
                        "exit_code": 126,
                        "session_id": sessions.get(agent.name),
                        "summary": preflight.reason,
                        "preflight": preflight_reason,
                    }],
                    "current_agent": agent.name,
                    "status": "failed",
                }
        result = agent.run(prompt, session_id=sessions.get(agent.name))
        summary = _summary(result)
        updated_sessions = dict(sessions)
        if result.session_id:
            updated_sessions[agent.name] = result.session_id
        if result.exit_code != 0:
            return {
                "messages": [AIMessage(content=summary, name=agent.name)],
                "agent_sessions": updated_sessions,
                "agent_runs": [{"agent": agent.name, "exit_code": result.exit_code, "session_id": result.session_id, "summary": summary, "preflight": preflight_reason}],
                "current_agent": agent.name,
                "status": "failed",
            }

        review = _review_decision(summary)
        update: dict[str, Any] = {
            "messages": [AIMessage(content=summary, name=agent.name)],
            "agent_sessions": updated_sessions,
            "agent_runs": [{"agent": agent.name, "exit_code": 0, "session_id": result.session_id, "summary": summary, "preflight": preflight_reason}],
            "current_agent": agent.name,
            "review": review,
            "status": "completed",
        }

        if review["decision"] == "rework":
            count = state.get("rework_count", 0) + 1
            update["rework_count"] = count
            if count > state.get("max_rework", 1):
                update["status"] = "needs_approval"
        elif review["decision"] == "unknown":
            update["status"] = "needs_approval"
        return update

    return run


def build_workflow(checkpointer: Any, *, codex: CliAgent | None = None, antigravity: CliAgent | None = None):
    """Codex 분석 → Antigravity 검토 → 제한된 Codex 재작업 Graph를 만듭니다.

    checkpointer는 SQLite 또는 InMemorySaver가 될 수 있습니다. 선택 인자는 테스트가 실제
    구독형 CLI 대신 Fake Adapter를 주입할 수 있게 합니다.
    """


    graph = StateGraph(SharedState)
    codex_agent = codex or CodexCliAgent()
    antigravity_agent = antigravity or AntigravityCliAgent()
    graph.add_node("codex", _implementation_node(codex_agent))
    graph.add_node("codex_rework", _implementation_node(codex_agent, rework=True))
    graph.add_node("antigravity", _review_node(antigravity_agent))

    graph.add_edge(START, "codex")

    def after_codex(state: SharedState) -> str:
        """Codex 실패 시 검토하지 않고 종료하고, 성공 시에만 Antigravity로 전달합니다."""
        return "antigravity" if state["status"] == "completed" else END

    graph.add_conditional_edges("codex", after_codex, {"antigravity": "antigravity", END: END})

    def after_review(state: SharedState) -> str:
        """유효한 REWORK만 재작업 Node로 보내고, 승인·모호함·한도 초과는 종료합니다."""
        if state["status"] == "completed" and state.get("review", {}).get("decision") == "rework":
            return "codex_rework"
        return END

    graph.add_conditional_edges(
        "antigravity", after_review, {"codex_rework": "codex_rework", END: END}
    )
    graph.add_conditional_edges(
        "codex_rework", after_codex, {"antigravity": "antigravity", END: END}
    )

    return graph.compile(checkpointer=checkpointer)
