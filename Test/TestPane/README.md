# TestPane

Standalone pane-layout playground for validating split-tree behavior without
PTY, pyte, or Terminalist runtime state.

## What It Covers

- split / close / focus behavior
- geometry-based neighbor movement
- mouse click focus
- mask/owner border rendering

## Structure

- `model.py`: pane tree data types
- `layout.py`: split / close / neighbor / hit-test logic
- `render.py`: mask/owner border rendering
- `console.py`: Windows console input helpers
- `snapshot.py`: latest frame/meta dump helpers
- `main.py`: app loop and state transitions

## Run

```bash
python -m pytest -q Test/TestPane/tests
python -m Test.TestPane.main
```

## Generated Files

`latest_meta.txt` and `latest_frame.txt` are overwritten on each interaction.
They are runtime debug artifacts, not source files.
