# TestCopy

Single-pane copy-mode playground for `terminalist`.

`terminalist` 본체에 바로 넣기 전에, copy-mode 상태머신과 viewport/selection/search
동작을 독립적으로 검증하는 실험장이다.

## 범위

- `LIVE` / `COPY` / `SEARCH` 모드 전환
- 화살표 / PageUp / PageDown / Home / End 이동
- selection anchor + 확장
- `/` search + `n` / `N`
- internal copied text + overwrite snapshot 파일

## 실행

```bash
python -m pytest -q Test/TestCopy/tests
python -m Test.TestCopy.main
```

## 입력

- `[` : COPY 모드 진입
- `Esc` : LIVE 복귀
- `Space` : selection anchor 설정
- `Enter` : selection copy + LIVE 복귀
- `/` : SEARCH prompt
- `n` / `N` : next / prev match
- `q` : 종료
- 휠 업 : LIVE면 COPY 진입 + 위로 스크롤
- 휠 다운 : COPY에서 아래로 스크롤, tail 도달 시 LIVE 복귀

## 스냅샷

매 입력마다 아래 파일을 overwrite 한다.

- `latest_meta.txt`
- `latest_frame.txt`
- `latest_copy.txt`

