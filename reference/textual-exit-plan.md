# Textual Exit Plan

> 목표: `PTY/session/TES/keymap`은 유지하고, `Textual`만 frontend에서 제거한다.
> 1차 목표는 "더 예쁜 UI"가 아니라 "입력 제어가 확실하고 구조가 작은 터미널 멀티플렉서"다.

---

## 1. 결정

Terminalist는 당분간 아래 원칙으로 간다.

1. `terminalist/core`, `terminalist/events`는 유지한다.
2. `pyte`는 유지한다.
3. `Textual`만 frontend에서 제거한다.
4. `libvterm` 도입은 Textual 제거 이후 별도 단계로 미룬다.
5. 키 정의의 단일 소스는 계속 [terminalist/tui/keymap.py](/c:/Users/jsy/Desktop/MultiTerm/terminalist/tui/keymap.py) 로 둔다.

즉 이번 리라이트의 범위는:

- 유지: PTY, session lifecycle, TES, provider sessions, key definitions
- 교체: Textual App, Widget tree, Screen stack, CSS/layout/compositor
- 보류: libvterm, flow editor, remote transport, full mouse/copy-mode 완성

---

## 2. 왜 이 절단면인가

현재 병목은 `PTY`가 아니라 `frontend abstraction`이다.

- VS Code 내부에서의 `Ctrl+D`, `Ctrl+Q`, IME, `ReadConsoleInputW`/`stdin` 경로 문제는 Textual의 위젯 트리보다 아래쪽 문제다.
- 반대로 Textual은 focus, binding, widget lifecycle, rendering cache, message pump까지 한 번에 끌고 와서 터미널 멀티플렉서 입장에서는 관성 질량이 크다.
- 하지만 PTY/session/TES 쪽은 이미 Terminalist 도메인에 맞게 분리되어 있다.

그러므로 가장 안전한 리라이트 순서는:

1. Textual 제거
2. direct VT frontend 도입
3. pyte 유지 상태로 안정화
4. 그 다음에만 `pyte -> libvterm` 검토

`Textual 제거`와 `libvterm 도입`을 동시에 하지 않는다. 원인 추적이 불가능해지기 때문이다.

---

## 3. 유지할 것

다음 파일/개념은 가능한 그대로 살린다.

- [terminalist/core/session.py](/c:/Users/jsy/Desktop/MultiTerm/terminalist/core/session.py)
- [terminalist/core/manager.py](/c:/Users/jsy/Desktop/MultiTerm/terminalist/core/manager.py)
- [terminalist/core/claude_session.py](/c:/Users/jsy/Desktop/MultiTerm/terminalist/core/claude_session.py)
- [terminalist/core/codex_session.py](/c:/Users/jsy/Desktop/MultiTerm/terminalist/core/codex_session.py)
- [terminalist/core/shell_session.py](/c:/Users/jsy/Desktop/MultiTerm/terminalist/core/shell_session.py)
- [terminalist/events/stream.py](/c:/Users/jsy/Desktop/MultiTerm/terminalist/events/stream.py)
- [terminalist/tui/keymap.py](/c:/Users/jsy/Desktop/MultiTerm/terminalist/tui/keymap.py)
- [terminalist/tui/vt100.py](/c:/Users/jsy/Desktop/MultiTerm/terminalist/tui/vt100.py)

유지 이유:

- `SessionManager`: provider/session 생성 책임이 이미 분리돼 있다.
- `TerminalSession`: PTY spawn/read/write/resize/state/TES 연결이 이미 있다.
- `keymap.py`: prefix/global key/action 정의의 단일 소스다.
- `vt100.py`: PTY로 실제로 보낼 바이트 매핑이 이미 있다.

---

## 4. 제거할 것

다음은 점진적으로 치운다.

- [terminalist/app.py](/c:/Users/jsy/Desktop/MultiTerm/terminalist/app.py) 의 Textual App 중심 구조
- [terminalist/tui/terminal_pane.py](/c:/Users/jsy/Desktop/MultiTerm/terminalist/tui/terminal_pane.py)
- `terminalist/drivers/*` 중 Textual 전용 드라이버 래핑
- Textual 의존 디버그 가정

여기서 중요한 점:

- `keymap.py`는 `tui/` 아래에 있더라도 당장은 유지한다.
- 나중에 이름을 옮기고 싶으면 `terminalist/keymap.py` 로 옮긴 뒤 `tui/keymap.py` 는 re-export shim으로 남기면 된다.
- 지금은 파일 이동보다 frontend 교체가 우선이다.

---

## 5. 새 구조

추천 디렉터리 구조:

```text
terminalist/
  app.py                    # 얇은 entrypoint
  core/                     # 유지
  events/                   # 유지
  tui/
    keymap.py               # 유지
    vt100.py                # 유지
  frontend/
    vt_app.py               # 메인 루프, 입력/렌더/출력 orchestration
    layout.py               # Split tree, Rect, pane geometry
    cells.py                # Cell, Layer, Frame
    compositor.py           # layer 합성 + prev_frame diff
    chrome.py               # 탭바/상태바 렌더링
    overlays.py             # 팝업/메뉴/flow overlay
    input_backend.py        # win32/stdin 입력 백엔드
    input_router.py         # key -> action or PTY bytes
    output.py               # stdout VT writer
    screen_sync.py          # pyte.Screen -> Layer 0 복사
```

핵심 포인트:

- `core`는 terminal domain
- `frontend`는 화면/입력 domain
- Textual이 하던 일을 전부 `frontend`의 작은 모듈들로 쪼갠다

---

## 6. 새 frontend의 책임 분리

### 6.1 `vt_app.py`

역할:

- 메인 루프
- frontend 상태 보유
- 주기적 렌더 트리거
- 입력 백엔드 시작/종료
- SessionManager / TES와 연결

이 객체는 Textual `App` 대체품이지만 훨씬 작아야 한다.

예상 책임:

- 현재 탭/활성 pane 추적
- split tree 보유
- layer stack 보유
- invalidate / redraw scheduling
- prefix 상태 추적

### 6.2 `layout.py`

역할:

- split tree
- pane별 `Rect(x, y, w, h)` 계산
- resize 시 모든 leaf geometry 재계산

초기 자료구조:

```python
@dataclass
class Rect:
    x: int
    y: int
    w: int
    h: int


class LayoutNode: ...


class Leaf(LayoutNode):
    pane_id: str


class Split(LayoutNode):
    direction: Literal["h", "v"]
    ratio: float
    a: LayoutNode
    b: LayoutNode
```

### 6.3 `cells.py`

역할:

- 렌더의 최소 단위 정의
- 프레임/레이어 표현

초기 자료구조:

```python
@dataclass(frozen=True)
class Cell:
    char: str = " "
    fg: str | None = None
    bg: str | None = None
    bold: bool = False
    italic: bool = False
    underline: bool = False
    reverse: bool = False


TRANSPARENT: Cell | None = None
```

### 6.4 `compositor.py`

역할:

- layer stack 합성
- `prev_frame` 비교
- 변경된 셀만 VT100 SGR + cursor move로 출력

이 모듈은 반드시 독립적으로 테스트 가능해야 한다.

입력:

- `list[Layer]`
- `prev_frame`

출력:

- `str` 또는 `bytes` VT sequence

### 6.5 `screen_sync.py`

역할:

- `pyte.Screen` 또는 `HistoryScreen` 내용을 Layer 0의 해당 Rect에 복사
- 경계선/패딩/unused cells 채우기
- cursor 위치 반영

여기서만 `pyte` 를 안다. 나머지 frontend는 `Cell`만 알게 만든다.

### 6.6 `input_backend.py`

역할:

- 현재 `terminalist/drivers/input_backends.py` 의 핵심만 가져온다
- Textual `Message` 대신 Terminalist 내부 `InputEvent` 를 뱉는다

즉 현재 구조의 장점은 유지하되, Textual 결합만 제거한다.

```python
@dataclass
class InputEvent:
    kind: Literal["key", "resize", "mouse", "paste", "focus"]
    key: str | None = None
    text: str | None = None
    width: int | None = None
    height: int | None = None
```

### 6.7 `input_router.py`

역할:

- [terminalist/tui/keymap.py](/c:/Users/jsy/Desktop/MultiTerm/terminalist/tui/keymap.py) 기반 action dispatch
- prefix 상태 처리
- overlay 우선 라우팅
- 활성 pane으로 PTY bytes 전달

중요:

- action 이름은 계속 `keymap.py` 기준으로 움직인다
- frontend가 바뀌어도 key semantics는 바뀌지 않는다

---

## 7. keymap 호환 원칙

`keymap.py` 는 단순 상수 파일이 아니라 "사용자 의도 계층"이다.

새 frontend는 아래 규칙을 지킨다.

1. action 이름은 계속 `keymap.py` 기준
2. global key / prefix key / detach key 구분 유지
3. PTY 전달용 바이트는 계속 `vt100.py` 기준
4. 입력 backend는 "어떤 key가 들어왔는지"까지만 책임지고, action 해석은 하지 않는다

즉 계층은 이렇게 나뉜다.

```text
host input
  -> input_backend.py
  -> InputEvent(key="ctrl+b")
  -> input_router.py
  -> keymap.py action 해석
  -> app action 또는 PTY write_raw()
```

이 분리가 있어야 VS Code / 외부 콘솔 / 나중의 remote client가 같은 key semantics를 공유할 수 있다.

---

## 8. 1차 MVP 범위

Textual 제거 1차 목표는 아래까지만 한다.

1. 단일 탭
2. 다중 pane split
3. 활성 pane 포커스
4. prefix 명령
5. 상태바 1줄
6. pyte 기반 pane 렌더
7. win32/stdin 입력 백엔드
8. resize

이번 단계에서 하지 않을 것:

- 마우스 selection 완성
- copy mode
- overlay editor
- remote transport UI
- libvterm
- full-screen app perfect fidelity

---

## 9. 단계별 마이그레이션

### Phase A. frontend interface 추출

목표:

- 현재 Textual에서 재사용할 개념만 분리

할 일:

- `InputEvent`
- `Cell`, `Rect`, `Frame`
- `LayoutNode`
- `FrontendAction` 또는 action dispatch 규약 정리

완료 조건:

- Textual 없이도 frontend core 타입이 import 가능

### Phase B. 단일 pane VT frontend

목표:

- Textual 없이도 하나의 session 화면을 직접 그릴 수 있음

할 일:

- alt screen 진입
- 단일 pane 렌더
- pyte -> Cell frame 변환
- `prev_frame` diff 출력
- `ctrl+c`, 문자 입력, enter 정도 전달

완료 조건:

- `terminalist --frontend vt` 로 단일 shell 사용 가능

### Phase C. split tree

목표:

- pane split / focus 이동 / close

할 일:

- binary split tree
- pane geometry -> session resize
- border drawing
- active pane 강조

완료 조건:

- 현재 Textual MVP의 split UX를 대체 가능

### Phase D. chrome

목표:

- 탭바/상태바/알림 1줄

할 일:

- Layer 1 도입
- chrome redraw
- 상태 표시

완료 조건:

- 운영 가능한 기본 UI 확보

### Phase E. Textual 제거

목표:

- entrypoint가 더 이상 Textual을 import하지 않음

할 일:

- `terminalist/app.py` 정리
- `terminalist/frontend/*` 를 기본 경로로 승격
- Textual 관련 테스트 정리

완료 조건:

- 기본 실행 경로에서 Textual 비의존

---

## 10. transitional strategy

한 번에 갈아엎지 않는다.

권장 전략:

```text
terminalist --frontend textual
terminalist --frontend vt
```

초기에는 둘 다 유지한다.

- `textual`: 기존 UI
- `vt`: 새 direct frontend

이렇게 해야 regression 비교가 가능하다.

환경변수 형태도 가능하다.

```text
TERMINALIST_FRONTEND=textual
TERMINALIST_FRONTEND=vt
```

---

## 11. 리스크

Textual 제거로 사라지지 않는 문제들도 있다.

### 11.1 그대로 남는 문제

- VS Code가 아예 전달하지 않는 `Ctrl+D`, `Ctrl+Q`
- IME 개입
- wide char / combining char
- ConPTY quirks

이건 frontend를 직접 써도 여전히 다뤄야 한다.

### 11.2 새로 생기는 책임

- alt screen lifecycle
- cursor hide/show
- focus in/out
- bracketed paste
- mouse protocol
- damage coalescing
- flicker 없는 redraw

즉 Textual을 치우는 대신 우리가 직접 owner가 된다.

---

## 12. 지금 당장 구현 순서

가장 작은 안전 순서는 아래다.

1. `frontend/input_backend.py` 로 현재 입력 백엔드 로직 복사/정리
2. `frontend/cells.py`, `frontend/layout.py`, `frontend/compositor.py` 추가
3. `frontend/vt_app.py` 에서 단일 pane shell 렌더
4. split tree 추가
5. `--frontend vt` 도입
6. 기존 Textual과 비교

여기서 멈춘 뒤에만 다음을 검토한다.

- `pyte` 성능/정확도 평가
- `libvterm` 프로토타입

---

## 13. 결론

현재 Terminalist의 다음 큰 구조 변화는:

- `Textual 유지 + 내부 패치`를 더 깊게 파는 것
- `libvterm` 을 곧바로 붙이는 것

이 아니라,

- `PTY/session/TES/keymap 유지`
- `Textual frontend 제거`
- `pyte 유지`
- `direct VT frontend 도입`

이다.

이 경로가 가장 작은 위험으로 "입력 제어"와 "구조 단순화"를 동시에 가져간다.
