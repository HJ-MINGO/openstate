"""LangGraph 없이 개별 CLI Adapter를 probe하거나 한 turn 실행하는 진단 도구입니다."""

from __future__ import annotations

# argparse는 agent·prompt·session-id 옵션을 파싱합니다.
import argparse
# json은 AgentResult를 터미널과 자동화 도구가 읽을 수 있게 출력합니다.
import json
# sys.exit는 subprocess 실패와 같은 종료 코드를 이 프로그램에도 전달합니다.
import sys

# 두 구현체는 같은 CliAgent 인터페이스를 따르므로 이름으로 선택할 수 있습니다.
from .agents import AntigravityCliAgent, CodexCliAgent


# 사용자가 입력한 이름과 실제 Adapter class를 연결하는 registry입니다.
AGENTS = {"codex": CodexCliAgent, "antigravity": AntigravityCliAgent}


def main() -> int:
    """선택한 Adapter를 만들고 probe 또는 한 번의 안전한 run을 수행합니다."""
    # parser는 사용자가 지원하지 않는 Agent 이름이나 실행 모드를 주지 않게 합니다.
    parser = argparse.ArgumentParser()
    parser.add_argument("agent", choices=AGENTS)
    # probe와 prompt 실행은 동시에 의미가 없으므로 하나만 받습니다.
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--probe", action="store_true")
    mode.add_argument("--prompt")
    parser.add_argument("--session-id")
    # 터미널 문자열을 검증된 argparse Namespace로 변환합니다.
    args = parser.parse_args()

    # registry에서 선택한 class의 Adapter 인스턴스를 만듭니다.
    agent = AGENTS[args.agent]()
    if not agent.available():
        print(json.dumps({"agent": args.agent, "error": "executable not found"}))
        return 127

    # probe는 --help만 실행하고, prompt mode는 Adapter.run의 preflight를 거칩니다.
    result = (
        agent.probe()
        if args.probe
        else agent.run(args.prompt, session_id=args.session_id)
    )
    # 실행 결과와 Adapter 기능 정보를 하나의 JSON 응답으로 합칩니다.
    payload = result.to_dict() | {"capabilities": agent.capabilities.to_dict()}
    print(json.dumps(payload, ensure_ascii=True, default=str))
    # 호출한 shell이 Agent 실패를 감지할 수 있도록 종료 코드를 그대로 반환합니다.
    return 0 if result.exit_code == 0 else result.exit_code


if __name__ == "__main__":
    # `python -m cli_collab.call_cli`로 실행할 때만 process 종료 코드를 설정합니다.
    sys.exit(main())
