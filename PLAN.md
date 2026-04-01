# Plan: Post-Phase 5 Roadmap

## Context

Phase 5 수준의 구조 정비와 UX 기본선은 완료됐다.

**이미 완료된 것:**
- `_set_focus()` 기반 focus contract 통일
- `TerminalSession` public snapshot API
- `Pane.frame_rect / content_rect`
- `WindowState` 기반 multi-window / tab-style 구조
- shared-boundary layout + geometry 기반 `find_neighbor()` / `hit_test()`
- `mask/owner` border renderer
- active border 하이라이트
- mouse click → pane focus
- wheel 기반 pane-local scrollback viewport
- status line
- `Ctrl+B` + `Ctrl+방향키` pane resize
- `Ctrl+B w/n/p/1-5` window 생성 / 전환
- 테스트 자산을 `Test/` 워크스페이스로 재구성

현재 코드는 이미 multi-pane terminal multiplexer로서 기본 사용이 가능하다.

## Current Baseline

**제품 테스트**
- `python -m pytest -q`

**standalone 실험장**
- `python -m pytest -q Test/TestPane/tests Test/TestVS/tests`
- `python Test/TestResize/test_unit.py`

## Remaining Work

### 1. 문서 / 운영 정리

- `CLAUDE.md`와 실제 구조를 계속 동기화
- 실행/디버그 경로를 `Test/` 기준으로 유지
- 필요시 `README` 추가

### 2. Copy Mode / Selection

현재는 wheel scrollback viewport만 있다.

다음 단계 목표:
- copy mode 진입/탈출
- 키보드 기반 viewport 이동
- 텍스트 선택 / 복사
- 상태바에 copy mode 표시

### 3. Flow

LLM 특화 기능의 핵심.

목표:
- 세션 A의 출력 스트림을 가공
- 세션 B 입력으로 라우팅
- 수동/자동 연결 규칙
- TES와의 결합 최소화

### 4. Remote

브라우저/타 기기 연결.

목표:
- VT frame / input event를 WebSocket으로 송수신
- 로컬 콘솔 입력/출력 계층과 분리된 transport 도입
- `frontend → core → events` 방향 유지

## Nice-to-Have Cleanup

- `Compositor(show_root_border=...)`를 실제 옵션으로 노출할지 결정
- `TestPane`과 본체 사이의 canonical prototype 관계 문서화
- `Test/terminalist/unit` 내부의 유사 테스트를 추가 정리

## Not In Scope Right Now

- Textual 같은 외부 TUI 프레임워크 도입
- 마우스 드래그 pane resize
- 즉시 full remote protocol 설계
- LLM 세션 내부 상태머신의 대규모 재설계

## Landing Strategy

1. 현재 제품 기능은 유지한 채 문서와 테스트 자산을 안정화한다.
2. 다음 큰 기능은 `Copy Mode`를 독립 커밋으로 진행한다.
3. `Flow`와 `Remote`는 그 이후 별도 설계 문서와 함께 들어간다.
