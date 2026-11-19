"""LangGraph Shared State에 저장하기 전 적용하는 작은 로컬 보안 처리입니다."""

# re는 token·Authorization 값처럼 정규적인 민감정보 패턴을 찾는 표준 라이브러리입니다.
import re

# 한 Agent 실행 결과가 SQLite checkpoint를 과도하게 키우지 않도록 요약 길이를 제한합니다.
MAX_STATE_SUMMARY_CHARS = 2_000
# 각 정규식은 인식 가능한 비밀값만 최소한으로 마스킹합니다.
_SECRET_PATTERNS = (
    # OpenAI API key에서 흔히 보이는 sk- 접두어를 마스킹합니다.
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    # xAI API key에서 흔히 보이는 xai- 접두어를 마스킹합니다.
    re.compile(r"\bxai-[A-Za-z0-9_-]{16,}\b"),
    # HTTP Authorization: Bearer 값은 접두어만 남기고 token 본문을 마스킹합니다.
    re.compile(r"(?i)(authorization:\s*bearer\s+)[^\s]+"),
)


def redact_for_state(text: str, limit: int = MAX_STATE_SUMMARY_CHARS) -> str:
    """인식 가능한 비밀값을 가리고, 저장할 텍스트 길이를 제한합니다.

    반환값은 workflow가 SQLite Shared State에 넣을 수 있는 요약입니다. 원문 로그 전체를
    안전하다고 보장하지 않으므로, 새로운 제공자 token 형식은 별도 패턴과 테스트를 추가해야 합니다.
    """
    # 등록된 모든 패턴을 순서대로 적용합니다.
    for pattern in _SECRET_PATTERNS:
        # 캡처 그룹이 있는 Authorization 패턴은 접두어를 보존하고, 나머지는 전부 가립니다.
        text = pattern.sub(r"\1[REDACTED]" if pattern.groups else "[REDACTED]", text)
    # 마스킹 후 앞부분만 남겨 checkpoint와 다음 Agent 프롬프트의 크기를 제한합니다.
    return text[:limit]
