# Architecture References

> 2026-03-23 pymux/ptterm/tmux/prompt-toolkit/cmux 리서치 결과 중
> Terminalist 구현에 직접 적용 가능한 패턴만 정리.

---

## 1. 클래스 분해: PTY / Screen / Pane 분리

### ptterm의 3레이어 (가장 가까운 레퍼런스)

```
Process (orchestrator, 조합)
  ├── Backend (ABC) — PTY lifecycle
  │     start, kill, closed, read_text, write_text,
  │     set_size, connect_reader, disconnect_reader
  └── BetterScreen — 가상 터미널 버퍼
        pyte 대체, 1264줄. 직접 렌더러블 Cell로 쓰기.
```

- Backend ABC가 PTY 추상화의 계약. PosixBackend / Win32Backend / AsyncSSHBackend.
- Process는 둘을 조합(compose)할 뿐, 상속하지 않음.
- Terminalist 적용: TerminalSession에서 PTY 부분을 PtyBackend ABC로 추출.

### pymux의 Pane ≠ Session

```
Pane (뷰 래퍼)
  ├── copy mode, scroll buffer, display name
  └── Terminal (ptterm)
        └── Process → Backend + BetterScreen
```

- Pane은 "어디에 보여줄지" (위치, 크기, 포커스)
- Session은 "뭘 실행할지" (PTY, 상태머신)
- Terminalist 적용: Pane 클래스를 별도로 만들고, TerminalSession을 참조.

### tmux의 계층

```
Session → Window(winlink) → Pane
- Pane이 PTY fd + screen 둘 다 소유 (분리 안 함)
- Window는 레이아웃 컨테이너
- Session은 Window들의 명명된 그룹
```

---

## 2. Split Tree 구현

### pymux: list 서브클래스 (가장 단순)

```python
class HSplit(list):
    weights: WeakKeyDictionary  # child → float (기본 1.0)

class VSplit(list):
    weights: WeakKeyDictionary

# 중첩: HSplit([Pane("a"), VSplit([Pane("b"), Pane("c")])])
# 추가: split.insert(i, pane)
# 제거: split.remove(pane) + 재귀 정리
```

### cmux/bonsplit: 재귀 enum (Swift)

```
SplitNode = .pane(PaneState) | .split(SplitState)
SplitState { direction, ratio, first: SplitNode, second: SplitNode }
```

---

## 3. 화면 렌더링 최적화

### Char 캐시 (ptterm)

```python
# FastDictCache[(char, style)] -> Char, 1M 슬롯 FIFO
# 동일 (문자, 스타일) 조합은 같은 객체 재사용
_CHAR_CACHE = FastDictCache(get_value=lambda k: Char(k[0], k[1]), size=1_000_000)
```

### Style string interning (ptterm)

```python
# 동일 스타일 문자열이 같은 파이썬 객체를 가리키게 함
# 메모리 절감 + `is` 비교 가능
class _UnicodeInternDict(dict): ...
```

### Attribute batching (prompt-toolkit)

```python
# SGR은 스타일이 바뀔 때만 출력
if last_style == char.style:
    write(char.char)          # SGR 생략
else:
    _output_set_attributes(new_attrs, color_depth)
    write(char.char)
    last_style = char.style
```

### 출력 버퍼링 (prompt-toolkit)

```python
# list에 누적 → join → 1회 write (syscall 최소화)
self._buffer: list[str] = []
def flush(self):
    data = "".join(self._buffer)
    self._buffer.clear()
    os.write(self._stdout_fd, data.encode())
```

### Cursor 이동 최적화 (prompt-toolkit)

- CR+forward vs backward vs absolute 중 가장 짧은 시퀀스 선택
- 줄바꿈 전 속성 리셋 (배경색 번짐 방지)

### CJK wide character (ptterm)

```python
# 2칸 문자: [실제문자][빈문자열 placeholder]
row[x] = Char("한", style)
row[x+1] = Char("", style)    # pyte stub cell

# 0폭 결합문자: 이전 셀에 병합
prev = row[x-1]
row[x-1] = Char(prev.char + combining, prev.style)
```

---

## 4. Dirty-Region 추적

### tmux: 쓰기 시점에 추적 (diff보다 효율적)

```
screen.write_list[y] = TAILQ of screen_write_citem
  { x, width, cell_attrs, char_data }

VT100 파서가 셀을 쓸 때마다 write_list에 추가.
겹치는 영역은 자동 병합/분할.
flush 시 dirty 영역만 클라이언트에 전송.
```

### pyte 활용 (Terminalist)

```python
# pyte.Screen.dirty가 이미 변경된 행 번호를 추적
# reader_loop에서:
self._dirty_rows.update(self._screen.dirty)
self._screen.dirty.clear()
# → 프롬프트 감지는 dirty 행이 마지막 N줄에 포함될 때만 실행
```

---

## 5. 이벤트 큐 관리

### tmux 전략들

| 전략 | 적용 대상 | 방식 |
|------|-----------|------|
| 즉시 제거 | command queue | 실행 완료 → `cmdq_remove()` |
| Bounded + batch prune | grid history | `hlimit` 초과 시 10%씩 정리 |
| Discard + timer | TTY output | 임계치 초과 → 버림 → timer로 복구 |
| Per-client cursor | control mode | 모든 클라이언트 최소 커서 기준 정리 |

### Terminalist TES 적용 (결정: cursor-based GC + file logging)

```python
# Control/State: 즉시 디스패치 후 보관 불필요
# Data: 모든 구독자의 최소 커서 아래 이벤트 정리
# 과거 이벤트 필요 시: 파일 로그에서 탐색
```

---

## 6. 입력 파싱

### prompt-toolkit: coroutine 기반 VT100 파서

```
os.read(stdin, 1024)
  → Vt100Parser.feed(data)  # 1문자씩 coroutine에 전달
  → prefix 누적 + longest match
  → flush timeout으로 bare ESC vs ESC-sequence 모호성 해결
  → KeyPress 객체 방출
```

- `_IS_PREFIX_OF_LONGER_MATCH_CACHE`: 현재 prefix가 더 긴 시퀀스의 시작인지 캐시
- Bracketed paste: `\x1b[200~` ~ `\x1b[201~` 사이는 한꺼번에 수집
- Windows: `ENABLE_VIRTUAL_TERMINAL_INPUT` 설정 시 같은 VT100 파서 사용 가능

### SGR 마우스 파싱

```
포맷: ESC[<button;x;y M (press) / ESC[<button;x;y m (release)
button bitmask: LEFT=0, MIDDLE=1, RIGHT=2
  +4=SHIFT, +8=ALT, +16=CTRL
  64=SCROLL_UP, 65=SCROLL_DOWN
좌표: 1-indexed → 0-indexed 변환
```

---

## 7. 포커스 기반 우선순위 (ptterm)

```python
# 포커스 pane: 즉시 처리
# 비포커스 pane: reader 분리 + call_soon_threadsafe, max 1초 지연
def _read(self):
    if self.has_priority():
        self.stream.feed(data)
        self.invalidate()
    else:
        # deferred processing
        ...
```

---

## 8. Resize 패턴

### ptterm: pull model (렌더 시점에 동기화)

```python
# 렌더링될 때 create_content(width, height) 호출됨
# 여기서 사이즈 변경 감지 → PTY + screen 동시 resize
def set_size(self, width, height):
    if (self.sx, self.sy) != (width, height):
        self.backend.set_size(width, height)
        self.screen.resize(lines=height, columns=width)
```

- 별도 resize 이벤트 전파 불필요
- resize 전파 버그 종류 제거
