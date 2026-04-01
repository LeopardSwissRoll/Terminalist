# TestVS — pyte Escape Sequence Fuzzer

PTY 자식 프로세스(Claude, Codex, PowerShell)가 보내는 escape 시퀀스 중
pyte가 잘못 해석하는 것을 찾아내고, `filter_private_modes` 필터가
정상적으로 차단하는지 검증하는 도구.

## 배경

pyte는 표준 VT100/xterm 시퀀스만 지원한다. 하지만 실제 터미널 앱들은
kitty keyboard protocol, xterm progressive enhancement 같은 확장 시퀀스를 보낸다.
pyte가 이걸 받으면:

- **유령 문자**: `\x1b[<u` → pyte가 "u"를 화면에 찍음
- **속성 오염**: `\x1b[>4;2m` → pyte가 SGR 4(underscore)로 해석

`terminalist/pyte_patch.py`의 `filter_private_modes()`가 이런 시퀀스를
PTY 출력에서 strip하는데, 이 필터에 구멍이 없는지 체계적으로 검증한다.

## 구조

```
Test/TestVS/
├── sequences.py   # 시퀀스 카탈로그 (SHOULD_IGNORE + NORMAL)
├── fuzzer.py      # 4단계 fuzzer
├── run.py         # 검증 진입점 (한 줄 실행)
├── tests/         # 최소 pytest 회귀
└── README.md
```

카탈로그 형식:

- `SHOULD_IGNORE`: `(sequence, source, description)`
- `NORMAL`: `(sequence, description)`

## 실행

```bash
# 기본: 카탈로그된 시퀀스만 테스트
python Test/TestVS/run.py

# 디버그 로그에서 시퀀스 추출 + 테스트
python Test/TestVS/run.py --log terminalist_debug_external.log
```

## 4단계 검증

| Phase | 대상 | 판정 기준 |
|-------|------|-----------|
| 1 | SHOULD_IGNORE (필터 없이) | pyte에서 유령 문자/속성 오염 발생하는지 확인 (expected fail) |
| 2 | SHOULD_IGNORE (필터 적용) | `filter_private_modes` 후 전부 PASS여야 함 |
| 3 | NORMAL (필터 적용) | 정상 시퀀스가 필터에 잘못 잡히지 않는지 확인 |
| 4 | 로그 추출 (필터 적용) | 실제 세션의 모든 시퀀스를 필터 후 검증 |

## 새 문제 시퀀스 추가 방법

1. `--debug`로 Terminalist 실행, 문제 재현
2. `python Test/TestVS/run.py --log terminalist_debug_external.log` 실행
3. Phase 4에서 FAIL이 나오면 → 해당 시퀀스를 `sequences.py`의 `SHOULD_IGNORE`에 추가
4. `pyte_patch.py`의 `_PRIVATE_CSI_RE` 패턴이 잡는지 확인
5. 안 잡히면 패턴 확장 후 다시 실행 → Phase 2 전부 PASS 확인

## 현재 필터 패턴

```python
_PRIVATE_CSI_RE = re.compile(r"\x1b\[[><=!][0-9;]*[A-Za-z~]")
```

private CSI prefix (`>`, `<`, `=`, `!`) + params + final byte를 모두 strip.

## 발견된 문제 시퀀스 이력

| 시퀀스 | 출처 | 증상 | 해결 |
|--------|------|------|------|
| `\x1b[>4;2m` | Claude CLI | SGR 4(underscore) 오염 | `_PRIVATE_CSI_RE` 최초 도입 |
| `\x1b[<u` | Claude CLI | 유령 "u" 문자 | `_PRIVATE_CSI_RE` 확장 (`<` prefix 추가) |
