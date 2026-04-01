# Terminalist

LLM CLI 멀티터미널 관리자. Windows Console 입력 + PTY + pyte + VT100 직접 제어.

## 비전

```text
Terminalist = tmux (터미널 멀티플렉서)
            + 마우스 입력
            + Flow (LLM 입출력 파이프라인)
            + Remote (브라우저/타 기기 연결)
```

tmux의 키모델과 pane UX를 기본으로 삼되, LLM 세션과 마우스/자동화까지 포함하는 superset을 지향한다.

## 아키텍처

```text
입력:
  ReadConsoleInputW (input/win32.py)
    → KeyEvent / MouseEvent
    → handler.py (paste, DA filter, IME, prefix, SGR mouse)
    → prefix action 은 app.py / keymap.py 로 라우팅
    → 나머지 입력은 활성 PTY로 직접 전달

출력:
  PTY → TerminalSession(pyte Screen)
      → get_screen_snapshot(scroll_offset=...)
      → Compositor(mask/owner border + diff render)
      → VT100Writer
      → stdout
```

**TUI 프레임워크를 사용하지 않는다.** 입력과 출력을 직접 제어한다.

## 현재 상태

**완료:**
- `core/`
  - `PtyBackend` ABC, `WinPtyBackend`
  - `TerminalSession` + `PreservingScreen`
  - `Pane` (`frame_rect / content_rect`, focus, copy-mode style scroll state)
  - `LLMSession`, `ClaudeSession`, `CodexSession`, `ShellSession`
  - `SessionManager`
- `events/`
  - TES 3채널 (`Data / Control / State`)
  - cursor 기반 GC + JSONL 파일 로그
- `input/`
  - `ReadConsoleInputW` 백엔드
  - 한글 IME, paste 감지, DA 필터, prefix FSM
  - 마우스 클릭 / wheel 처리
  - `ENABLE_EXTENDED_FLAGS | ENABLE_MOUSE_INPUT`
- `frontend/`
  - split tree (`layout`, `remove`, `find_neighbor`, `hit_test`, `adjust_ratio`)
  - `screen_sync`, `vt100_writer`
  - `Compositor` (`mask/owner` border 렌더, diff 렌더, status line overlay)
- `app.py`
  - multi-pane 메인 루프
  - split / focus / close / zoom
  - mouse click focus
  - wheel scrollback viewport
  - status line
  - `Ctrl+B` + `Ctrl+방향키` pane resize
- `interactive.py`
  - 단일 세션 회귀용 엔트리포인트
- `dualrun.py`
  - VSCode + 외부 PowerShell 동시 실행
- `debug.py`
  - 환경 감지 + 분리 로그 / render artifact dump
- `pyte_patch.py`
  - pyte 색 이름 패치
  - private CSI filter
  - `PreservingScreen` shrink 보존 패치

**현재 기본 검증:**
- `python -m pytest -q` → `Test/terminalist` 제품 테스트
- `python -m pytest -q Test/TestPane/tests Test/TestVS/tests`
- `python Test/TestResize/test_unit.py`

**남은 큰 기능 (Phase 6+):**
- Tab / Window 계층
- Copy mode / 텍스트 선택
- Flow (세션 A 출력 → 가공 → 세션 B 입력)
- Remote (WebSocket / 브라우저 연결)

## 아키텍처 원칙

1. **TUI 프레임워크(Textual 등)를 사용하지 않는다.**
2. **입력은 `ReadConsoleInputW` 기반이다.**
   - Win32 콘솔 API는 `input/win32.py`
   - 의미 해석은 `input/handler.py`
3. **출력은 VT100 직접 쓰기다.**
4. **키바인딩의 단일 진실 공급원은 `keymap.py`다.**
5. **tmux 키 모델**:
   - `Ctrl+B` prefix만 가로챈다
   - 나머지 입력은 PTY로 직접 전달한다
6. **클래스 분해**:
   - `PtyBackend`: PTY 추상화
   - `TerminalSession`: pyte + 상태머신 + TES
   - `Pane`: 화면 배치와 포커스/scroll 상태
7. **geometry 계약**:
   - `frame_rect`: 시각적 pane box
   - `content_rect`: PTY content 배치 영역
   - PTY resize는 `content_rect`만 기준으로 한다
8. **border 렌더는 `mask/owner` 모델**을 사용한다.
   - glyph: `U/D/L/R` mask로 결정
   - active border: `focused_id in owners`
9. **scrollback viewport는 session snapshot API로 노출한다.**
   - `get_screen_snapshot(scroll_offset=...)`
   - `get_max_scroll_offset()`
10. **의존 방향**:
    - `frontend → core → events`
    - 역방향 import 금지
11. **`PreservingScreen`는 materialized empty row 상태를 전제로 안전하게 shrink 되어야 한다.**
    - `get_screen_snapshot()`의 `buffer[y]` 접근이 empty row key를 만들 수 있음
12. **debug 가능성 유지**:
    - 각 레이어에 `log()` 호출 유지
    - `--debug` 시 render/input artifact 남길 것

## 기술 스택

- Python 3.11+
- `pywinpty` (`PtyProcess`)
- `pyte`
- 패키지명: `terminalist`

## 저장소 구조

```text
terminalist/
├── app.py
├── interactive.py
├── dualrun.py
├── pyte_patch.py
├── debug.py
├── keymap.py
├── input/
│   ├── win32.py
│   ├── handler.py
│   └── keymap_vk.py
├── core/
│   ├── pty_backend.py
│   ├── winpty_backend.py
│   ├── terminal_session.py
│   ├── llm_session.py
│   ├── claude_session.py
│   ├── codex_session.py
│   ├── shell_session.py
│   ├── pane.py
│   └── session_manager.py
├── frontend/
│   ├── split_tree.py
│   ├── screen_sync.py
│   ├── compositor.py
│   └── vt100_writer.py
└── events/
    ├── event.py
    └── tes.py

Test/
├── terminalist/
│   ├── unit/
│   ├── integration/
│   └── roundtrip/
├── TestPane/
├── TestResize/
└── TestVS/
```

## 코딩 규칙

- 새 키바인딩은 `keymap.py`에만 추가
- PTY/Windows 입력 관련 패턴은 `terminalist/input/win32.py`를 우선 재사용
- pyte 관련 보정은 `pyte_patch.py`에서 해결
- `--debug`로 문제 추적 가능하게 각 레이어에 `log()` 호출 유지
- CJK wide character stub cell (`data == ""`)는 렌더 시 skip 필요
- `except Exception: pass` 금지, 최소한 로깅

## 알려진 제약

- VSCode 통합 터미널에서 일부 `Ctrl+키`는 호스트가 가로챌 수 있다
- IME 한국어 상태에서 일부 Ctrl 조합이 자모 입력으로 변형될 수 있다
- 마우스 wheel / SGR mouse 동작은 호스트(Windows Terminal / VSCode / 외부 PowerShell)에 따라 차이가 있을 수 있다

## 핵심 참고 자료

**reference/**
- `architecture-references.md` — pymux / ptterm / tmux / prompt-toolkit 리서치
- `fakeTerm.py` / `fakeTerm.md` — 초기 Windows PTY / 입력 처리 실험

**docs/**
- `ctrl-key-investigation.html` — Ctrl+키 입력 조사
- `archive/` — Textual 시절 리서치와 이전 설계 기록
