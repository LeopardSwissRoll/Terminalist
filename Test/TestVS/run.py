#!/usr/bin/env python
"""TestVS 검증 진입점.

Usage:
    python Test/TestVS/run.py                                    # 카탈로그만
    python Test/TestVS/run.py --log terminalist_debug_external.log  # + 로그 추출
"""

import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from Test.TestVS.fuzzer import main

if __name__ == "__main__":
    main()
