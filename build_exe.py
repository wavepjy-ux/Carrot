#!/usr/bin/env python3
"""PyInstaller로 nationwide_search.exe를 생성합니다."""

from __future__ import annotations

import importlib.util
import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRIPT_NAME = "nationwide_search.py"
OUTPUT_NAME = "nationwide_search"


def main() -> int:
    if platform.system().lower() != "windows":
        print("[경고] EXE는 Windows에서만 실행됩니다. 현재 OS:", platform.system())

    if importlib.util.find_spec("PyInstaller") is None:
        print("[오류] PyInstaller가 설치되어 있지 않습니다.")
        print("       먼저 `python -m pip install -r requirements.txt`를 실행해 주세요.")
        return 1

    script_path = ROOT / SCRIPT_NAME
    if not script_path.exists():
        print(f"[오류] 대상 스크립트를 찾을 수 없습니다: {script_path}")
        return 1

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        OUTPUT_NAME,
        "--add-data",
        f"regions.txt{os.pathsep}.",
        str(script_path),
    ]

    print("실행:", " ".join(cmd))
    try:
        subprocess.run(cmd, check=True, cwd=ROOT)
    except subprocess.CalledProcessError as exc:
        print(f"[오류] EXE 빌드 실패 (exit code: {exc.returncode})")
        return exc.returncode

    print("\n완료: dist/nationwide_search.exe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
