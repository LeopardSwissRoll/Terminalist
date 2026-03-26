# Terminalist

LLM CLI 멀티터미널 관리자. PTY + pyte + VT100 직접 제어.

## 비전

```
Terminalist = tmux (터미널 멀티플렉서)
            + 마우스 입력
            + Flow (LLM 입출력 파이프라인)
            + Remote (브라우저/타 기기 연결)
```

tmux의 키바인딩/UX를 기본으로 하되, Terminalist의 기능은 superset.
키보드만으로 충분히 쓸 수 있으면서, 마우스가 있으면 더 유용한 UX.

## 아키텍처

```
입력: ReadConsoleInputW  →  배치 읽기 (win32.py)
      → paste/DA/IME 처리 (handler.py)  →  prefix → 앱 액션 (keymap.py)
                                          →  나머지 → 활성 PTY에 전달

출력: PTY → PtyProcess.read()  →  pyte Screen (가상 화면)
      → screen_sync (Char 그리드 추출)
      → Compositor (diff 렌더) → VT100 시퀀스 → stdout
```

**TUI 프레임워크를 사용하지 않는다.** 입력과 출력을 직접 제어한다.

## 현재 상태

**완료 (검증됨, 100개 테스트 통과):**
- `core/` — PtyBackend ABC, WinPtyBackend, TerminalSession, Pane+Rect, LLM/Claude/Codex/Shell 세션, SessionManager
- `events/` — TES 3채널 (Data/Control/State) + cursor-based GC + JSONL 파일 로그
- `input/` — ReadConsoleInputW 백엔드, 한글 IME, paste 감지, DA 필터, prefix FSM
- `frontend/` — Split tree (layout/mutation/neighbor), screen_sync, vt100_writer, Compositor (diff 렌더)
- `keymap.py` — 액션 바인딩 단일 진실
- `interactive.py` — 단일 세션 인터랙티브 셸 (Claude/Codex/PowerShell 검증됨)
- `dualrun.py` — VSCode + 외부 PowerShell 동시 실행
- `debug.py` — 환경 감지 + 분리 로그
- `app.py` — 메인 루프 (multi-pane 입력→디스패치→렌더)
- `pyte_patch.py` — pyte 색 이름 패치 + PreservingScreen (resize 시 내용 보존)

**구현 필요 (Phase 5+):**
- 상태바/탭바 (Layer 1)
- 마우스 입력 (ENABLE_MOUSE_INPUT 기반, 클릭→포커스, 스크롤)
- Flow (LLM 입출력 파이프라인)
- Remote (WebSocket)

## 아키텍처 원칙 (반드시 지킬 것)

1. **TUI 프레임워크(Textual 등)를 사용하지 않는다** — 입력/출력 직접 제어
2. **입력은 ReadConsoleInputW** — IME, paste, 마우스, DA 응답 전부 처리 (win32.py)
3. **출력은 VT100 직접 쓰기** — ESC[ 시퀀스로 커서 이동, 색상 적용, 화면 갱신
4. **화면 관리**: Split 이진 트리 + Layer 합성 + prev_frame diff (변경 셀만 출력)
5. **세션 내부 동작은 상속**, TES 바인딩은 런타임 조합
6. **TES 3채널**: Data(FIFO, cursor) / Control(즉시) / State(브로드캐스트)
7. **MANUAL 모드**: 포커스 시 외부 Data 차단, 이전 상태 저장/복원
8. **PtyProcess 사용** (winpty.PTY가 아닌 — PTY는 1회 읽고 사망하는 버그)
9. **pyte_patch.py**: 앱 시작 시 pyte 색 이름을 Rich 호환으로 수정
10. **keymap.py가 키바인딩의 단일 진실 공급원** — 새 바인딩은 여기에만 추가
11. **tmux 키 모델**: Ctrl+B prefix만 가로채고, 나머지 모든 키는 PTY로 직접 전달
12. **클래스 분해**: PtyBackend(PTY) / TerminalSession(상태머신+pyte) / Pane(뷰) 3단 분리
    - PtyBackend ABC: spawn/kill/read/write/resize (PTY 라이브러리 교체 대비)
    - TerminalSession: pyte Screen + 상태머신 + TES 연결
    - Pane: 위치(Rect) + 포커스 + copy mode (렌더링 관심사)
13. **프롬프트 감지는 마지막 N줄만 검사** — dirty 행이 하단에 포함될 때만 실행
14. **TES 이벤트 GC**: 모든 구독자 최소 커서 기준 정리, 과거 이벤트는 파일 로그로 보존
15. **의존 방향**: frontend → core → events (역방향 import 금지, Remote 분리 대비)

## 기술 스택

- Python 3.11+, pywinpty (PtyProcess), pyte (가상 터미널)
- 패키지명: `terminalist`
- 의존성: pywinpty, pyte (그 외 없음)
- 디버그: `--debug` → `terminalist_debug.log`

## 파일 구조

```
terminalist/
├── app.py              메인 루프 (multi-pane, compositor 렌더)
├── interactive.py      단일 세션 인터랙티브 셸 (얇은 엔트리포인트)
├── dualrun.py          VSCode + 외부 PowerShell 동시 실행
├── pyte_patch.py       pyte 색 패치 + PreservingScreen (resize 보존)
├── debug.py            --debug 로깅 (환경 감지 + 분리 로그)
├── keymap.py           액션 바인딩 정의 (prefix 명령, 단일 진실)
├── input/
│   ├── win32.py             Windows Console API (ReadConsoleInputW, 모드 관리)
│   ├── handler.py           이벤트 처리 (paste, DA 필터, key 변환, prefix FSM)
│   └── keymap_vk.py         VK → ANSI 매핑 + VT100 테이블
├── core/
│   ├── pty_backend.py       PtyBackend ABC (PTY 추상화)
│   ├── winpty_backend.py    WinPtyBackend (pywinpty 구현)
│   ├── terminal_session.py  TerminalSession (pyte + 상태머신)
│   ├── llm_session.py       LLMSession ABC
│   ├── claude_session.py
│   ├── codex_session.py
│   ├── shell_session.py
│   ├── pane.py              Pane + Rect (뷰 래퍼)
│   └── session_manager.py   SessionManager
└── events/
    ├── event.py              Event, Channel
    └── tes.py                EventStreamManager (TES + GC + file log)
```

## 코딩 규칙

- 새 키바인딩 → `keymap.py`에만 추가
- PTY 관련 → `reference/fakeTerm.py`의 검증된 패턴 참고
- pyte 색 → `pyte_patch.py`에서 해결
- API 사용 전 `help()` / `dir()`로 실제 시그니처 확인 — 리서치만 믿지 말 것
- `--debug` 로그로 문제 추적 가능하게 각 레이어에 `log()` 호출 유지
- CJK wide character: pyte stub cell (`data=""`) skip 필요
- `except Exception: pass` 금지 — 최소한 로깅

## 알려진 제약

- VSCode 통합 터미널에서 Ctrl+D/Q는 워크벤치가 가로채서 코드로 해결 불가
- IME 한국어 상태에서 Ctrl+키가 자모로 변환됨
- ConPTY의 ReadConsoleInputW는 vkCode=0으로 Ctrl+키를 보냄 → os.read(stdin)으로 우회

## 핵심 참고 자료

**reference/ 디렉토리:**
- `architecture-references.md` — pymux/ptterm/tmux/prompt-toolkit 리서치 결과 (클래스 분해, 렌더링 최적화, 이벤트 큐, 입력 파싱 패턴)
- `fakeTerm.py` / `fakeTerm.md` — Windows PTY 패턴 (ReadConsoleInputW, IME, paste, DA 필터, 10가지 입력 문제 해결)

**docs/ 디렉토리:**
- `ctrl-key-investigation.html` — Ctrl+키 입력 문제 조사 (삽질 방지용)
- `archive/` — Textual 시대 리서치 HTML, textual-exit-plan.md (전환 완료된 설계문서)
