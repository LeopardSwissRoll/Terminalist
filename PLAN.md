# Plan: Phase 5 — 구조 정비 + UX 기능

## Context

Phase 4(multi-pane app.py)까지 완료. 터미널 멀티플렉서로서 기본 동작 확인됨
(split, focus, close, zoom, Claude/Codex 실행).

Codex 아키텍처 리뷰에서 3가지 구조적 문제 지적:
1. focus contract 불완전
2. 레이어 간 private 속성 직접 접근
3. 단일 트리 앱 → 탭/윈도우 확장 시 비대화 위험

Phase 5는 이 구조를 정비하면서 UX 기능을 추가하는 단계.

## Part A: 구조 정비 — ✅ 완료

### A-1. Focus contract 완전 통일 ✅

`_set_focus(pane)` 헬퍼 추가. 모든 포커스 변경이 이 함수를 거쳐
`blur()`/`focus()` → `exit_manual()`/`enter_manual()` 계약을 보장.

적용: 초기화, close_pane, focus_direction, new_session_split.

### A-2. Public API 추출 ✅

TerminalSession에 public 메서드 추가:
- `is_alive()`, `get_cursor_position()`, `get_screen_snapshot()`, `add_raw_output_listener()`

`get_screen_snapshot()`은 **core 안에서 직접 grid 추출** (frontend import 없음).
`frontend → core → events` 의존 방향 유지.

compositor, app, interactive, pane 전부 public API로 교체 완료.

## Part B: UX 기능 — 남은 작업

### B-1. 활성 pane border 하이라이트

**현재**: 모든 border가 같은 색 (white).
**목표**: focused pane 인접 border를 bright_white + bold.

**설계 (Codex 피드백 반영)**:
- **compositor가 판정하지 않음.** `split_tree.borders()`가 판정.
- `BorderSegment`에 `active: bool` 필드 추가.
- `borders(root, rect, focused_pane_id)` 시그니처로 변경.
- split_tree 레벨에서 "이 border의 양쪽 자식 중 focused pane이 있는가?"를 판정.
- compositor는 `seg.active`만 보고 BORDER_V_ACTIVE/BORDER_H_ACTIVE 선택.

**파일**: `terminalist/frontend/split_tree.py`, `terminalist/frontend/compositor.py`
**테스트**: `test_split_tree.py`에 active border 테스트 추가

### B-2. 마우스 클릭 → pane 포커스

**현재**: 마우스 이벤트 로깅만.
**목표**: 좌클릭 → 히트테스트 → 해당 pane으로 포커스.

**수정**:
- `split_tree.py`에 `hit_test(root, x, y) -> Pane | None` 추가
- `app.py` 마우스 처리에서 클릭 시 `_set_focus(hit_test(...))`

**파일**: `terminalist/frontend/split_tree.py`, `terminalist/app.py`
**테스트**: `test_split_tree.py`에 hit_test 테스트 추가

### B-3. 상태바 (Layer 1 최소 버전)

**현재**: 화면 전체가 pane + border.
**목표**: 맨 아래 1줄에 상태바.

**설계 (Codex 피드백 반영)**:
- **compositor가 줄을 예약하지 않음.** app이 geometry를 소유.
- app이 layout에 `Rect(0, 0, cols, rows - 1)` 넘김 (pane 영역).
- app이 상태바 내용(Char 리스트)을 만들어서 compositor에 별도 전달.
- compositor는 `render_status_line(chars, y)` 메서드로 마지막 줄만 그림.

**상태바 내용**: `[*pane_1: powershell] [pane_2: claude]` — `*`가 focused.

**파일**: `terminalist/frontend/compositor.py`, `terminalist/app.py`
**테스트**: compositor render_status_line 단위 테스트

### B-4. Pane 리사이즈 (Ctrl+B Ctrl+방향키)

**현재**: split ratio 고정 (0.5).
**목표**: prefix + Ctrl+방향키로 경계선 이동.

**UX 규칙 (Codex 피드백 반영)**:
> "해당 방향과 축이 맞는 가장 가까운 조상 Split의 ratio를 조정한다."

예: 2x2 grid에서 pane C에서 Ctrl+B Ctrl+→ 누르면:
1. C에서 path를 올라가며 VERTICAL Split을 찾음
2. 해당 Split의 ratio를 +0.05 (오른쪽으로 밀기)
3. relayout → full_redraw

**수정**:
- `split_tree.py`에 `adjust_ratio(root, pane_id, direction, delta=0.05)` 추가
- `keymap.py`에 resize 액션 추가
- `app.py` dispatcher에 resize 핸들러
- ratio clamp: 양쪽 모두 `can_split` 최소 크기 이상 유지

**파일**: `terminalist/keymap.py`, `terminalist/frontend/split_tree.py`, `terminalist/app.py`
**테스트**: `test_split_tree.py`에 adjust_ratio 테스트 추가

## 구현 순서

1. ~~**A-1**: `_set_focus()`~~ ✅
2. ~~**A-2**: public API~~ ✅
3. **B-1**: border 하이라이트 — `BorderSegment.active` + compositor 색 분기
4. **B-2**: 마우스 클릭 포커스 — `hit_test` + app 마우스 처리
5. **B-3**: 상태바 — app이 geometry 소유, compositor는 그리기만
6. **B-4**: pane 리사이즈 — `adjust_ratio` + keymap + dispatcher

## 검증

**자동 테스트 (각 단계별)**:
- `test_split_tree.py`: active border, hit_test, adjust_ratio
- `test_compositor.py`: render_status_line
- `test_roundtrip.py`: compositor 변경 후 round-trip 통과
- `python -m pytest -q tests` 전체 통과

**수동 확인**:
- focus 전환 시 border 색 변경
- 마우스 클릭으로 pane 전환
- 상태바에 pane 정보 표시
- Ctrl+B Ctrl+방향키로 경계선 이동

## 안 하는 것

- Tab/Window 계층 (Phase 5+, Arrangement 구조)
- Copy mode / 텍스트 선택
- 마우스 스크롤 (copy mode 필요)
- 마우스 드래그 리사이즈
- Flow / Remote
