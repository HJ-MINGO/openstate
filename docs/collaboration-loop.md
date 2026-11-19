# Codex·Antigravity 협업 루프

## 목표

LangGraph가 Codex의 작업 결과를 Antigravity에 전달하고, 검토 결과가 재작업을 요구할 때만
제한된 횟수로 Codex를 다시 실행합니다. 현재 기본 실행 정책은 Codex `read-only`,
Antigravity `--mode plan --sandbox`이므로 실제 파일 수정이 아니라 분석·수정 제안과 검토를
반복합니다.

## 흐름

```text
사용자 요청
  → Codex: 분석·수정 제안
  → Antigravity: 검토
      ├─ REVIEW_DECISION: APPROVE → 완료
      ├─ REVIEW_DECISION: REWORK  → Codex 재작업 → Antigravity 재검토
      └─ 형식 누락 또는 한도 초과 → needs_approval으로 중단
```

Antigravity 검토 프롬프트는 마지막 줄에 아래 둘 중 하나를 요구합니다.

```text
REVIEW_DECISION: APPROVE
REVIEW_DECISION: REWORK
```

형식이 없으면 프레임워크는 임의로 승인하지 않습니다. `needs_approval` 상태로 멈추어 사용자가
검토하거나 후속 지시를 내리게 합니다.

## Shared State 추가 필드

| 필드 | 역할 |
| --- | --- |
| `review` | 최신 검토의 결정과 피드백 |
| `rework_count` | 수행한 재작업 횟수 |
| `max_rework` | 허용할 최대 재작업 횟수, 기본값 1 |
| `modified_files` | 실제 변경이 확인된 파일 경로. 현재 read-only 단계에서는 비어 있음 |
| `artifact_refs` | 긴 산출물의 파일 경로·SHA-256·요약 참조 |

## 재작업 한도

기본 `max_rework`는 1입니다. 첫 `REWORK`는 Codex 재작업을 한 번 허용합니다. 재검토 뒤에도
`REWORK`가 나오면 자동 반복하지 않고 `needs_approval`으로 종료합니다. 무한 루프와 예상 밖의
CLI 사용량을 막기 위한 제한입니다.

## 검증

`tests/test_workflow.py`는 다음을 Fake Adapter로 검증합니다.

- `REWORK` 뒤 Codex가 검토 피드백을 받아 재작업하는 흐름
- 최종 `APPROVE`에서 정상 완료하는 흐름
- 검토 형식이 누락됐을 때 사용자 승인을 기다리는 흐름
