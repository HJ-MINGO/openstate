"""터미널에서 LangGraph 협업 Graph를 한 번 실행하는 진입점입니다."""

# 최신 타입 표기법을 Python 3.11에서도 안전하게 사용합니다.
from __future__ import annotations

# argparse는 request·thread-id·database 같은 CLI 인자를 파싱하는 표준 라이브러리입니다.
import argparse
# json은 최종 실행 결과를 다른 프로그램도 읽을 수 있는 JSON으로 출력합니다.
import json
# Path는 SQLite DB의 상위 .data 디렉터리를 안전하게 준비합니다.
from pathlib import Path

# HumanMessage는 사용자의 입력을 LangGraph 공통 메시지 형식으로 저장합니다.
from langchain_core.messages import HumanMessage
# SqliteSaver는 LangGraph checkpoint를 로컬 SQLite 파일에 영속화합니다.
from langgraph.checkpoint.sqlite import SqliteSaver

# build_workflow는 Codex·Antigravity 협업 Graph를 조립하는 프로젝트 함수입니다.
from .workflow import build_workflow


def main() -> None:
    """명령행 인자를 읽고, SQLite checkpoint가 연결된 workflow를 한 번 실행합니다."""
    # argparse parser는 사용자가 터미널에서 제공한 옵션을 검증하고 도움말을 생성합니다.
    parser = argparse.ArgumentParser()
    # 첫 위치 인자는 Agent에게 전달할 자연어 작업 요청입니다.
    parser.add_argument("request")
    # thread_id는 프로그램 재시작 뒤에도 같은 Shared State를 찾는 LangGraph 키입니다.
    parser.add_argument("--thread-id", required=True)
    # database는 개발 단계의 기본 SQLite checkpoint 파일 경로입니다.
    parser.add_argument("--database", default=".data/langgraph-checkpoints.sqlite")
    # parse_args는 잘못된 인자면 사용법을 출력하고 종료합니다.
    args = parser.parse_args()
    # SQLite 파일이 들어갈 상위 폴더가 없으면 먼저 만듭니다.
    Path(args.database).parent.mkdir(parents=True, exist_ok=True)
    # context manager는 Graph 실행이 끝나면 SQLite connection을 닫고 checkpoint를 flush합니다.
    with SqliteSaver.from_conn_string(args.database) as checkpointer:
        # 실제 Agent Adapter가 연결된 실행 Graph를 생성합니다.
        app = build_workflow(checkpointer)
        # invoke는 입력 State와 thread_id를 전달해 START부터 END까지 동기 실행합니다.
        result = app.invoke(
            # user_request는 Node prompt의 원본, messages는 공통 대화 이력입니다.
            {"user_request": args.request, "messages": [HumanMessage(content=args.request)]},
            # configurable.thread_id가 SQLite checkpoint의 논리적 작업 세션 키가 됩니다.
            {"configurable": {"thread_id": args.thread_id}},
        )
    # 전체 내부 State 대신 상태·Session·실행 요약만 JSON으로 사용자에게 반환합니다.
    print(json.dumps({"status": result["status"], "sessions": result.get("agent_sessions", {}), "runs": result.get("agent_runs", [])}, ensure_ascii=True))


if __name__ == "__main__":
    # 이 파일을 module이 아니라 직접 실행했을 때만 main을 호출합니다.
    main()
