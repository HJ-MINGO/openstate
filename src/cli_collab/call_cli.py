"""LangGraph 없이 개별 CLI Adapter를 probe하거나 한 turn 실행하는 진단 도구입니다."""

from __future__ import annotations


import argparse

import json

import sys


from .agents import AntigravityCliAgent, CodexCliAgent



AGENTS = {"codex": CodexCliAgent, "antigravity": AntigravityCliAgent}


def main() -> int:
    """선택한 Adapter를 만들고 probe 또는 한 번의 안전한 run을 수행합니다."""

    parser = argparse.ArgumentParser()
    parser.add_argument("agent", choices=AGENTS)

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--probe", action="store_true")
    mode.add_argument("--prompt")
    parser.add_argument("--session-id")

    args = parser.parse_args()


    agent = AGENTS[args.agent]()
    if not agent.available():
        print(json.dumps({"agent": args.agent, "error": "executable not found"}))
        return 127


    result = (
        agent.probe()
        if args.probe
        else agent.run(args.prompt, session_id=args.session_id)
    )

    payload = result.to_dict() | {"capabilities": agent.capabilities.to_dict()}
    print(json.dumps(payload, ensure_ascii=True, default=str))

    return 0 if result.exit_code == 0 else result.exit_code


if __name__ == "__main__":

    sys.exit(main())
