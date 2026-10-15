from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

SENSITIVE_ENV_VALUE = re.compile(
    r"^\s*(?:export\s+)?(?P<name>[A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|API_KEY|PRIVATE_KEY)[A-Z0-9_]*)"
    r"\s*=\s*(?P<value>.+)$",
)
PLACEHOLDER_VALUE = re.compile(
    r"^(?:|\{\}|\[\]|<[^>]+>|\$\{[^}]+\}|replace[-_a-z0-9]*|your[-_a-z0-9]*|change[-_a-z0-9]*)$",
    re.IGNORECASE,
)
TOKEN_PATTERNS = (
    re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{20,}"),
)
SERVER_ONLY_CLIENT_ENV = re.compile(
    r"^\s*VITE_(?:DATABASE_URL|[A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|PRIVATE_KEY|ENCRYPTION_KEY|API_KEY))\s*=",
    re.IGNORECASE,
)
NON_SECRET_NAME_SUFFIXES = (
    "_ALGORITHM",
    "_ITERATIONS",
    "_PATH",
    "_TTL",
    "_TTL_SECONDS",
)
SCANNED_SUFFIXES = {
    ".example",
    ".ini",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".sh",
    ".toml",
    ".yaml",
    ".yml",
}
IGNORED_DIRECTORIES = {
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".venv_clean",
    "__pycache__",
    "runtime",
    "secrets",
}


def _is_ignored_env_template(path: str) -> bool:
    name = Path(path).name
    return name.startswith(".env") and name.endswith(".example")


def _is_sensitive_env_file(path: str) -> bool:
    return Path(path).name.startswith(".env") and not _is_ignored_env_template(path)


def _is_placeholder(value: str) -> bool:
    return bool(PLACEHOLDER_VALUE.fullmatch(value.strip().strip("\"'")))


def _is_non_secret_metadata(name: str, value: str) -> bool:
    return name.endswith(NON_SECRET_NAME_SUFFIXES) or value.lstrip().startswith("(")


def find_violations(path: str, content: str) -> list[str]:
    violations: list[str] = []
    if _is_sensitive_env_file(path):
        return [f"{path}: environment files must not be committed"]

    for line_number, line in enumerate(content.splitlines(), start=1):
        if SERVER_ONLY_CLIENT_ENV.match(line):
            violations.append(
                f"{path}:{line_number}: server-only secret must not use a VITE_ variable"
            )
            continue
        if any(pattern.search(line) for pattern in TOKEN_PATTERNS):
            violations.append(f"{path}:{line_number}: detected a credential pattern")
            continue
        match = SENSITIVE_ENV_VALUE.match(line)
        if (
            match
            and not _is_non_secret_metadata(match.group("name"), match.group("value"))
            and not _is_placeholder(match.group("value"))
        ):
            violations.append(
                f"{path}:{line_number}: detected a non-placeholder secret value"
            )
    return violations


def _staged_files() -> list[tuple[str, str]]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        check=True,
        capture_output=True,
        text=True,
    )
    files = [line for line in result.stdout.splitlines() if line]
    return [
        (path, subprocess.check_output(["git", "show", f":{path}"], text=True))
        for path in files
    ]


def _named_files(paths: list[str]) -> list[tuple[str, str]]:
    return [(path, Path(path).read_text(encoding="utf-8")) for path in paths]


def _all_source_files() -> list[tuple[str, str]]:
    paths = sorted(
        path
        for path in Path.cwd().rglob("*")
        if path.is_file()
        and not any(part in IGNORED_DIRECTORIES for part in path.parts)
        and not _is_sensitive_env_file(str(path))
        and (path.suffix in SCANNED_SUFFIXES or path.name == "Dockerfile")
    )
    return [(str(path), path.read_text(encoding="utf-8")) for path in paths]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reject committed environment files and credentials."
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--files", nargs="+", help="Scan named files instead of the staged Git files."
    )
    source.add_argument(
        "--all",
        action="store_true",
        help="Scan all source files without requiring Git.",
    )
    args = parser.parse_args()

    try:
        files = (
            _all_source_files()
            if args.all
            else _named_files(args.files)
            if args.files
            else _staged_files()
        )
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"Secret scan failed: {error}", file=sys.stderr)
        return 2

    violations = [
        violation
        for path, content in files
        for violation in find_violations(path, content)
    ]
    if not violations:
        print("Secret scan passed.")
        return 0

    print("Secret scan blocked this change:", file=sys.stderr)
    print("\n".join(violations), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
