"""터미널에서 LangGraph 협업 Graph를 한 번 실행하는 진입점입니다."""


from __future__ import annotations


import argparse

import json

from pathlib import Path


from langchain_core.messages import HumanMessage

from langgraph.checkpoint.sqlite import SqliteSaver


from .workflow import build_workflow


def main() -> None:
    """명령행 인자를 읽고, SQLite checkpoint가 연결된 workflow를 한 번 실행합니다."""

    parser = argparse.ArgumentParser()

    parser.add_argument("request")

    parser.add_argument("--thread-id", required=True)

    parser.add_argument("--database", default=".data/langgraph-checkpoints.sqlite")

    args = parser.parse_args()

    Path(args.database).parent.mkdir(parents=True, exist_ok=True)

    with SqliteSaver.from_conn_string(args.database) as checkpointer:

        app = build_workflow(checkpointer)

        result = app.invoke(

            {"user_request": args.request, "messages": [HumanMessage(content=args.request)]},

            {"configurable": {"thread_id": args.thread_id}},
        )

    print(json.dumps({"status": result["status"], "sessions": result.get("agent_sessions", {}), "runs": result.get("agent_runs", [])}, ensure_ascii=True))


if __name__ == "__main__":

    main()
