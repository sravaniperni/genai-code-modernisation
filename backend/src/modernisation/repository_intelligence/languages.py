"""Language, test-file and configuration-file classification by path."""

from __future__ import annotations

import fnmatch
from pathlib import PurePosixPath

EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".sh": "shell",
    ".toml": "toml",
    ".cfg": "ini",
    ".ini": "ini",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".json": "json",
    ".md": "markdown",
    ".rst": "rst",
    ".txt": "text",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
}

SPECIAL_NAMES: dict[str, str] = {
    "Dockerfile": "dockerfile",
    "Makefile": "make",
    "requirements.txt": "requirements",
}

CONFIG_PATTERNS = [
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "tox.ini",
    "noxfile.py",
    "pytest.ini",
    "mypy.ini",
    ".flake8",
    ".ruff.toml",
    "ruff.toml",
    "requirements*.txt",
    "constraints*.txt",
    "Pipfile",
    "Pipfile.lock",
    "poetry.lock",
    "uv.lock",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "tsconfig*.json",
    "Dockerfile",
    "docker-compose*.yml",
    ".pre-commit-config.yaml",
    "conftest.py",
    "Makefile",
]

DEPENDENCY_MANIFESTS = [
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements*.txt",
    "constraints*.txt",
    "Pipfile",
    "package.json",
]


def detect_language(path: str) -> str | None:
    p = PurePosixPath(path)
    if p.name in SPECIAL_NAMES:
        return SPECIAL_NAMES[p.name]
    if p.name.startswith("requirements") and p.suffix == ".txt":
        return "requirements"
    return EXTENSIONS.get(p.suffix.lower())


def is_test_path(path: str) -> bool:
    p = PurePosixPath(path)
    name = p.name
    parts = {part.lower() for part in p.parts[:-1]}
    if name == "conftest.py":
        return True
    if name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py")):
        return True
    if name.endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx", ".test.js", ".spec.js")):
        return True
    return bool(parts & {"tests", "test", "__tests__", "testing"}) and p.suffix in {".py", ".ts", ".js"}


def is_config_path(path: str) -> bool:
    p = PurePosixPath(path)
    if len(p.parts) >= 3 and p.parts[0] == ".github" and p.parts[1] == "workflows":
        return True
    return any(fnmatch.fnmatch(p.name, pattern) for pattern in CONFIG_PATTERNS)


def is_dependency_manifest(path: str) -> bool:
    name = PurePosixPath(path).name
    return any(fnmatch.fnmatch(name, pattern) for pattern in DEPENDENCY_MANIFESTS)


def module_name_for_path(path: str) -> str | None:
    """Map a Python source path to its importable module name (handles ``src/`` layouts)."""
    p = PurePosixPath(path)
    if p.suffix not in {".py", ".pyi"}:
        return None
    parts = list(p.with_suffix("").parts)
    if parts and parts[0] in {"src", "lib"} and len(parts) > 1:
        parts = parts[1:]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts or not all(part.isidentifier() for part in parts):
        return None
    return ".".join(parts)
