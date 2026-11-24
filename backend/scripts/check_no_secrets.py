"""扫描仓库中可能泄露的 DeepSeek Key / 前端注入变量。

用于 CI 与提交前自检：
    python scripts/check_no_secrets.py
退出码 1 表示发现疑似 Key。
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {".git", "node_modules", "dist", ".venv", "__pycache__", ".storage", ".pytest_cache"}
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".docx", ".pptx", ".mp4", ".zip", ".db"}

PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"DEEPSEEK_API_KEY\s*=\s*(?!请填入|your-|replace|$)[A-Za-z0-9_-]{16,}"),
    re.compile(r"VITE_[A-Z0-9_]*DEEPSEEK[A-Z0-9_]*"),
    re.compile(r"DEEPSEEK_API_KEY:\s*(?!请填入|your-|replace|$)[A-Za-z0-9_-]{16,}"),
]


def tracked_files() -> list[Path]:
    try:
        output = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return [ROOT / name for name in output.decode("utf-8", "ignore").split("\0") if name]


def iter_candidates() -> list[Path]:
    files = tracked_files()
    if not files:
        files = [path for path in ROOT.rglob("*") if path.is_file() and ".git" not in path.parts]
    return [
        path
        for path in files
        if path.is_file()
        and not any(part in SKIP_DIRS for part in path.parts)
        and path.suffix.lower() not in SKIP_SUFFIXES
        and path.name != ".env"
    ]


def main() -> int:
    findings: list[str] = []
    for path in iter_candidates():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern in PATTERNS:
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                findings.append(f"{path.relative_to(ROOT)}:{line}: {match.group(0)[:40]}")

    if findings:
        print("发现疑似密钥或前端注入变量：", file=sys.stderr)
        for finding in findings:
            print(f"  - {finding}", file=sys.stderr)
        return 1
    print("no secret leakage detected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())