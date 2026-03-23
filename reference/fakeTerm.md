# fakeTerm — PTY 가상 터미널 패스스루

Windows에서 PTY 프로세스를 래핑하여 "진짜 터미널처럼" 보이게 만드는 도구.
Claude CLI, Codex CLI, PowerShell 등을 PTY 안에서 실행하고 모든 입출력을 중계.

## 사용법

```
python fakeTerm.py                          # 기본: powershell
python fakeTerm.py "claude --verbose"       # Claude CLI
python fakeTerm.py "codex --no-alt-screen"  # Codex CLI
python fakeTerm.py "python"                 # 아무 CLI
python fakeTerm.py "claude" --cwd ~/myproj  # 작업 디렉토리 지정
```

종료: **Ctrl+B → Ctrl+C** (tmux 방식)
Ctrl+B 두 번 = 리터럴 Ctrl+B 전달

---

## 아키텍처

```
입력: ReadConsoleInputW → 배치 읽기 → paste 감지 / 개별 처리 → PTY write
출력: PTY read(4096) → sys.stdout.write (raw passthrough)
화면: alt screen 진입/복원
```

---

## 해결된 문제들

### 1. ANSI 이스케이프가 깨져 보임

**원인**: Windows 콘솔 기본값이 VT 시퀀스 비해석.
**해결**: `SetConsoleMode`로 `ENABLE_VIRTUAL_TERMINAL_PROCESSING` 활성화.

### 2. 한글 IME 입력

**원인**: `msvcrt.getwch()`는 IME 조합 완료까지 블로킹. 조합 중 커서가 안 움직임.
**해결**: `ReadConsoleInputW`로 교체.
- `VK_PROCESSKEY` (0xE5): IME가 키를 가로챈 이벤트 → skip
- `vk=0x0000`: IME 확정된 한글 → PTY에 전달
- 영문/특수키는 `vk` 코드로 직접 구분

```python
if vk == VK_PROCESSKEY:
    continue  # IME 조합중 — 건너뜀
if ch and vk == 0x0000:
    proc.write(ch)  # 확정된 한글
    continue
```

### 3. 화살표/특수키

**원인**: `msvcrt.getwch()`는 `\x00`/`\xe0` prefix + scan code 방식.
VSCode 터미널에서 VT input mode가 켜지면 ESC 시퀀스로 오는데 타이밍 이슈 발생.

**해결**: `ReadConsoleInputW`의 VK 코드로 직접 매핑. 타이밍 문제 없음.

```python
_SPECIAL_VK = {
    0x26: "\x1b[A",   # VK_UP
    0x28: "\x1b[B",   # VK_DOWN
    0x27: "\x1b[C",   # VK_RIGHT
    0x25: "\x1b[D",   # VK_LEFT
    ...
}
```

**주의**: `uChar`가 `'\x00'` (NUL)인 경우 Python에서 truthy.
반드시 `ch if ch and ch != '\x00' else None`으로 처리.

### 4. DA 응답 오염

**원인**: CLI가 시작 시 DA 쿼리(`\x1b[c`)를 보내면 터미널이 응답.
이 응답이 `ReadConsoleInputW`에 `vk=0x0000`으로 한 글자씩 도착.
PTY에 전달하면 쓰레기 입력이 됨.

**해결**: 시간 기반 drain 대신 **인라인 DA 필터** 사용.
`vk=0x0000` + ESC 시퀀스 패턴을 누적해서 완성되면 버림.

```python
if ch == "\x1b" or da_buf is not None:
    # ESC 시퀀스 누적
    da_buf = ch if ch == "\x1b" else da_buf + ch
    if len(da_buf) >= 3 and da_buf[1] == "[" and "\x40" <= da_buf[-1] <= "\x7e":
        da_buf = None  # 완성 → 버림
    continue
```

시간 기반 drain을 쓰지 않는 이유: 첫 키 입력이 씹힘.

### 5. Backspace — 단어 통째 삭제

**원인**: `\x08` (BS/Ctrl+H)을 보내면 PSReadLine이 "undo group"으로 처리.
IME로 입력한 한글이 한 그룹이라 전부 삭제됨.

**해결**: `\x7f` (DEL) 전송. PSReadLine이 단일 문자 삭제로 처리.

```python
elif ch == "\x08":
    proc.write("\x7f")  # BS → DEL
```

### 6. Shift+Enter — 줄바꿈

**원인**: `dwControlKeyState`의 SHIFT 비트가 콘솔 모드 0에서 불안정.
CSI u 시퀀스(`\x1b[13;2u`)는 Codex CLI에서 리터럴 텍스트로 표시됨.

**해결**: `user32.GetAsyncKeyState(VK_SHIFT)`로 하드웨어 키 상태 직접 확인.
`\n` (LF) 전송 — Claude CLI, Codex CLI 둘 다 호환.

```python
if user32.GetAsyncKeyState(VK_SHIFT) & 0x8000:
    proc.write("\n")   # Shift+Enter → 줄바꿈
else:
    proc.write("\r")   # Enter → 실행
```

**주의**: `GetAsyncKeyState`는 `user32.dll`에 있음. `kernel32`에서 호출하면 `AttributeError`.

### 7. Ctrl+C 충돌

**원인**: "Ctrl+C 2번 = 종료"가 CLI 내부의 Ctrl+C 동작과 충돌.
Claude CLI의 "Press Ctrl-C again to exit"에서 우리 래퍼가 먼저 종료됨.

**해결**: tmux 방식 prefix key.
- Ctrl+C → 항상 PTY에 `\x03` 전달
- Ctrl+B → Ctrl+C = 래퍼 종료
- Ctrl+B → Ctrl+B = 리터럴 Ctrl+B 전달
- Ctrl+B → 2초 타임아웃 = 리터럴 Ctrl+B 전달

### 8. 붙여넣기 느림 + 자동 실행

**원인**: 붙여넣기 텍스트가 `ReadConsoleInputW`에 개별 KEY_EVENT로 도착.
한 글자씩 처리하면 PTY write 100번 → 에코가 보일 정도로 느림.
뉴라인이 `\r`로 전달되면 각 줄이 실행됨.

**해결**: prompt-toolkit 휴리스틱 방식의 배치 감지.
1. `GetNumberOfConsoleInputEvents`로 모든 이벤트 한번에 읽기
2. 배치에 텍스트 + 뉴라인 혼재 → paste 판정
3. 합쳐서 `\r\n` → `\r` 변환 후 1번 write

```python
if has_newline and has_text and is_pure_text and len(text_chars) > 2:
    paste_text = "".join(text_chars)
    paste_text = paste_text.replace("\r\n", "\r").replace("\n", "\r")
    proc.write(paste_text)
```

**주의**: Shift/Ctrl/Alt modifier 키(vk=0x10/0x11/0x12)가 배치에 섞여 들어옴.
이걸 skip하지 않으면 `is_pure_text`가 깨져서 paste 감지 실패.

### 9. VSCode 터미널에서 입력 멈춤

**원인**: VSCode가 focus/mouse 이벤트를 콘솔에 보냄.
`_read_console_input()`이 `KEY_DOWN`만 찾는 내부 루프에서
non-KEY 이벤트에 영원히 블로킹.

**해결**: `_read_one_record()` — 1개 레코드만 읽고 즉시 반환.
KEY_DOWN이 아니면 `None` 반환. 배치 읽기에서 사용.

```python
def _read_one_record(h_in):
    # ReadConsoleInputW 1회 → KEY_DOWN이면 결과, 아니면 None
    ...

# 배치 읽기
while avail > 0:
    result = _read_one_record(h_in)
    if result is not None:
        events.append(result)
```

### 10. Alt Screen

**해결**: 시작 시 대체 화면 버퍼 진입, 종료 시 복원.
기존 터미널 내용을 덮어쓰지 않음.

```python
sys.stdout.write("\x1b[?1049h\x1b[H\x1b[2J")  # 진입
sys.stdout.write("\x1b[?1049l")                  # 복원
```

---

## 핵심 교훈

1. **Windows 입력은 `ReadConsoleInputW`가 정답** — msvcrt는 IME/VT input/paste 어느 것도 제대로 못 함.
2. **non-KEY 이벤트를 항상 고려** — VSCode가 focus/mouse 이벤트를 보내서 블로킹 유발.
3. **DA 응답은 인라인 필터로** — 시간 기반 drain은 키 입력을 삼킴.
4. **Backspace = DEL(0x7F)** — BS(0x08)은 PSReadLine undo group 동작.
5. **Shift+Enter = \n** — CSI u는 Codex 비호환, \n은 양쪽 다 OK.
6. **GetAsyncKeyState는 user32.dll** — kernel32 아님.
7. **배치 읽기 + paste 휴리스틱** — 텍스트+뉴라인 혼재 = paste.
8. **Ctrl+C는 prefix key로 보호** — CLI 내부 Ctrl+C와 충돌 방지.
