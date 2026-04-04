# Test

Unified test workspace for this repository.

## Layout

- `terminalist/`
  Product-facing tests for the real `terminalist` codebase.
- `TestPane/`
  Standalone pane playground and its own tests.
- `TestCopy/`
  Standalone copy-mode playground and its own tests.
- `TestResize/`
  Resize bug repro and investigation assets.
- `TestVS/`
  Escape-sequence fuzzer and its own tests.

## Default Pytest Scope

```bash
python -m pytest -q
```

By default, pytest collects `Test/terminalist`.

## Standalone Suites

```bash
python -m pytest -q Test/TestPane/tests Test/TestCopy/tests Test/TestVS/tests
python Test/TestResize/test_unit.py
```
