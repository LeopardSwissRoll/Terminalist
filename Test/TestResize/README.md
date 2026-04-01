# TestResize — PreservingScreen resize bug investigation

## Bug

h-split 시 화면의 모든 텍스트가 사라지고, 커서만 남는 현상.

## Root Cause

`pyte.Screen.resize()` → `delete_lines()` 버그:

1. pyte buffer는 defaultdict — `buffer[y]` 접근만으로 empty row entry 생성
2. ConPTY/PSReadLine 출력, 또는 `get_screen_snapshot()`의 `buffer[y]` 순회가
   **빈 행 포함 모든 행에 buffer entry를 materialize**
3. `delete_lines(n)` 가 빈 rows [n..old_lines-1]을 rows [0..lines-1]에 shift
4. 내용 있던 행이 빈 행으로 덮어써짐 → **전체 텍스트 소실**

`-NoProfile` PowerShell에서는 빈 행에 buffer entry가 안 생겨서 재현 안 됨.
Full profile (PSReadLine) 에서 100% 재현.

## Fix

`PreservingScreen._resize_shrink()`: `pyte.Screen.resize()` 호출을 우회.
커서 위치 기준 viewport window를 계산해 새 buffer를 직접 구축.

## Test files

| File | Purpose | PTY? |
|------|---------|------|
| `test_unit.py` | 핵심 검증: shrink/expand/round-trip/real-PTY | Yes |
| `test_investigation.py` | 버그 원인 추적 과정 (참고용) | Partial |

## Run

```bash
# 핵심 테스트 (빠름, PTY 포함)
python Test/TestResize/test_unit.py

# 조사 과정 재현 (느림, 참고용)
python Test/TestResize/test_investigation.py
```
