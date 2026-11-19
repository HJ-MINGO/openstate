"""LangGraph Shared State에 저장하기 전 적용하는 작은 로컬 보안 처리입니다."""


import re


MAX_STATE_SUMMARY_CHARS = 2_000

_SECRET_PATTERNS = (

    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),

    re.compile(r"\bxai-[A-Za-z0-9_-]{16,}\b"),

    re.compile(r"(?i)(authorization:\s*bearer\s+)[^\s]+"),
)


def redact_for_state(text: str, limit: int = MAX_STATE_SUMMARY_CHARS) -> str:
    """인식 가능한 비밀값을 가리고, 저장할 텍스트 길이를 제한합니다.

    반환값은 workflow가 SQLite Shared State에 넣을 수 있는 요약입니다. 원문 로그 전체를
    안전하다고 보장하지 않으므로, 새로운 제공자 token 형식은 별도 패턴과 테스트를 추가해야 합니다.
    """

    for pattern in _SECRET_PATTERNS:

        text = pattern.sub(r"\1[REDACTED]" if pattern.groups else "[REDACTED]", text)

    return text[:limit]
