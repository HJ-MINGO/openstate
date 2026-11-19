"""LangGraph Shared State와 Codex·Antigravity 협업 루프를 정의합니다."""

# 최신 타입 표기법을 Python 3.11에서도 안전하게 사용합니다.
from __future__ import annotations

# operator.add는 agent_runs·artifact_refs처럼 실행 이력을 누적하는 Reducer에 사용합니다.
import operator
# re는 검토 Agent가 마지막에 남긴 REVIEW_DECISION 표식을 찾습니다.
import re
# TypedDict는 State의 저장 필드를, Annotated는 LangGraph Reducer를 표현합니다.
from typing import Annotated, Any, Literal, TypedDict

# AIMessage와 BaseMessage는 LangGraph checkpoint에 저장되는 공통 대화 형식입니다.
from langchain_core.messages import AIMessage, BaseMessage
# StateGraph는 Node와 조건부 Edge를, START/END는 Graph 시작·종료 지점을 제공합니다.
from langgraph.graph import END, START, StateGraph, add_messages

# Agent Adapter는 실제 CLI 호출을, security 함수는 저장 전 결과 정리를 담당합니다.
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

    # 사용자가 처음 입력한 작업 요청입니다.
    user_request: str
    # 각 에이전트가 남긴 대화 메시지를 누적합니다.
    messages: Annotated[list[BaseMessage], add_messages]
    # "에이전트 이름 -> 해당 CLI 내부 세션 ID" 매핑입니다.
    agent_sessions: dict[str, str]
    # 실행 순서와 결과 요약을 누적해 다음 에이전트에게 전달합니다.
    agent_runs: Annotated[list[AgentRun], operator.add]
    # 실제 쓰기 단계에서 Git diff 등으로 확인한 변경 파일을 저장할 예정입니다.
    modified_files: list[str]
    # 큰 산출물은 본문 대신 참조를 누적해 checkpoint 크기를 제한합니다.
    artifact_refs: Annotated[list[ArtifactRef], operator.add]
    # 가장 최근 Antigravity 검토의 결론과 피드백입니다.
    review: Review
    # 현재 작업에서 수행한 Codex 재작업 횟수입니다.
    rework_count: int
    # 무한 반복과 예상 밖 CLI 사용량을 막는 재작업 상한입니다.
    max_rework: int
    current_agent: str
    status: Literal["running", "completed", "failed", "needs_approval"]


def _summary(result: Any, limit: int = 2_000) -> str:
    """제공자 출력에서 사람이 읽을 최종 응답만 골라 State용 요약으로 만듭니다."""
    # Antigravity처럼 하나의 JSON 객체를 반환하는 제공자를 먼저 처리합니다.
    if isinstance(result.parsed_output, dict):
        text = result.parsed_output.get("response") or result.parsed_output.get("result")
        if isinstance(text, str):
            return redact_for_state(text, limit)
    # Codex JSONL은 여러 이벤트이므로 뒤에서부터 최종 agent_message를 찾습니다.
    if isinstance(result.parsed_output, list):
        for record in reversed(result.parsed_output):
            item = record.get("item") if isinstance(record, dict) else None
            if isinstance(item, dict) and item.get("type") == "agent_message":
                text = item.get("text")
                if isinstance(text, str):
                    return redact_for_state(text, limit)
    # 구조화된 응답을 찾지 못하면 stdout, 없으면 stderr를 제한된 텍스트로 저장합니다.
    return redact_for_state(result.stdout or result.stderr, limit)


def _node(agent: CliAgent):
    """이전 단순 순차 Graph에서 쓰던 공통 Node 구현입니다.

    현재 Graph는 역할별 prompt가 필요한 _implementation_node와 _review_node를 사용합니다.
    """
    def run(state: SharedState) -> dict[str, Any]:
        # 이전 두 결과만 프롬프트에 넣어 컨텍스트가 무한히 커지지 않게 합니다.
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
        # State에 저장된 제공자별 Session ID를 읽어 새 turn 또는 재개 turn을 결정합니다.
        sessions = state.get("agent_sessions", {})
        # 최근 두 실행 요약만 전달해 프롬프트와 State 문맥이 무한히 커지는 것을 줄입니다.
        prior = "\n\n".join(item["summary"] for item in state.get("agent_runs", [])[-2:])
        prompt = state["user_request"]
        if prior:
            prompt += f"\n\nPrevious agent hand-off:\n{prior}"
        # 재작업 Node에서는 최신 검토 피드백을 Codex에게 명시적으로 전달합니다.
        if rework:
            feedback = state.get("review", {}).get("feedback", "")
            prompt += f"\n\nReviewer feedback to address:\n{feedback}"
        prompt += (
            "\n\nYou are the implementation agent. Work in analysis mode only: do not modify files "
            "or execute commands. State proposed changes and affected file paths."
        )
        # Fake Adapter는 실제 CLI 명령이 없으므로 테스트용 설명만 기록합니다.
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
        # Adapter.run()은 내부에서 다시 preflight를 수행한 뒤 subprocess를 실행합니다.
        result = agent.run(prompt, session_id=sessions.get(agent.name))
        summary = _summary(result)
        # 이전 State dict를 직접 변경하지 않도록 복사한 뒤 최신 Session ID만 갱신합니다.
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
    # 표식이 없으면 자동 승인하지 않고 사용자 승인 대기 상태로 보내기 위해 unknown을 반환합니다.
    if match is None:
        return {"decision": "unknown", "feedback": summary}
    return {
        "decision": "approve" if match.group(1).upper() == "APPROVE" else "rework",
        "feedback": summary,
    }


def _review_node(agent: CliAgent):
    """Antigravity가 Codex 결과를 검토하고 재작업·승인을 결정하는 Node입니다."""
    def run(state: SharedState) -> dict[str, Any]:
        # Antigravity conversation 재개용 Session ID를 State에서 읽습니다.
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
        # 성공 응답에서만 검토 결정을 읽습니다. CLI 실패는 위에서 failed로 종료했습니다.
        review = _review_decision(summary)
        update: dict[str, Any] = {
            "messages": [AIMessage(content=summary, name=agent.name)],
            "agent_sessions": updated_sessions,
            "agent_runs": [{"agent": agent.name, "exit_code": 0, "session_id": result.session_id, "summary": summary, "preflight": preflight_reason}],
            "current_agent": agent.name,
            "review": review,
            "status": "completed",
        }
        # 재작업 요청은 횟수를 올리고, 상한을 넘으면 다음 Codex 호출 대신 사용자 승인을 기다립니다.
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
    # 노드는 상태를 읽고, 바뀐 값만 dict로 돌려주는 일반 Python 함수입니다.
    # SharedState schema와 Reducer를 기준으로 Node 반환 dict를 병합할 Graph를 만듭니다.
    graph = StateGraph(SharedState)
    codex_agent = codex or CodexCliAgent()
    antigravity_agent = antigravity or AntigravityCliAgent()
    graph.add_node("codex", _implementation_node(codex_agent))
    graph.add_node("codex_rework", _implementation_node(codex_agent, rework=True))
    graph.add_node("antigravity", _review_node(antigravity_agent))
    # 모든 새 요청은 먼저 Codex 분석 Node에서 시작합니다.
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
    # compile 결과는 run_workflow 또는 테스트가 invoke()할 실행 가능한 LangGraph 객체입니다.
    return graph.compile(checkpointer=checkpointer)
