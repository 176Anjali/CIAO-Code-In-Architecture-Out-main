from __future__ import annotations

import fnmatch
import os
import subprocess
from pathlib import Path
from typing import Iterable, List, Set


EXCLUDED_DIRS = {
    ".git", ".history", "tests", "test", "node_modules", "data",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".venv", "venv",
    "env", "dist", "build", ".ciao-cache",
}
EXCLUDED_SUFFIXES = {
    ".ipynb", ".pt", ".pth", ".onnx", ".h5", ".hdf5", ".keras",
    ".pkl", ".pickle", ".joblib", ".bin", ".safetensors", ".model",
    ".weights", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif",
    ".tiff", ".webp", ".ico", ".pdf", ".docx", ".zip", ".gz",
    ".tar", ".7z", ".mp4", ".mp3", ".wav",
}
EXCLUDED_NAMES = {
    "full_code.txt", "documentation.pdf", "documentation.docx",
    "architecture.png", "architecture.svg", "ciao-generation.json",
    "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml",
    "poetry.lock", "pdm.lock", "uv.lock", "pipfile.lock", "cargo.lock",
    "composer.lock", "gemfile.lock", "bun.lockb", "bun.lock",
}


def iter_repository_files(root: Path, *, max_file_bytes: int | None = 2_000_000) -> List[Path]:
    """Return sorted, bounded repository files after CIAO and .gitignore exclusions."""
    root = Path(root).resolve()
    if not root.is_dir():
        return [root] if root.is_file() and _included_name(root.name) else []

    candidates: List[Path] = []
    for current, directories, filenames in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        directories[:] = [
            name for name in directories
            if name.lower() not in EXCLUDED_DIRS
            and not (current_path / name).is_symlink()
        ]
        for filename in filenames:
            path = current_path / filename
            if path.is_symlink() or not _included_name(filename):
                continue
            try:
                if max_file_bytes is not None and path.stat().st_size > max_file_bytes:
                    continue
            except OSError:
                continue
            candidates.append(path)

    relative = [path.relative_to(root).as_posix() for path in candidates]
    ignored = _gitignored_paths(root, relative)
    return sorted(
        (path for path, rel in zip(candidates, relative) if rel not in ignored),
        key=lambda path: path.relative_to(root).as_posix().casefold(),
    )


def _included_name(name: str) -> bool:
    lowered = name.lower()
    if lowered in EXCLUDED_NAMES or lowered.endswith(".lock"):
        return False
    if Path(lowered).suffix in EXCLUDED_SUFFIXES:
        return False
    if lowered.startswith(("documentation.", "architecture.")):
        return False
    return True


def _gitignored_paths(root: Path, paths: Iterable[str]) -> Set[str]:
    paths = list(paths)
    if not paths:
        return set()
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "check-ignore", "--no-index", "-z", "--stdin"],
            input="\0".join(paths) + "\0",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode in (0, 1):
            return {item for item in result.stdout.split("\0") if item}
    except (OSError, subprocess.SubprocessError):
        pass
    return {path for path in paths if _matches_gitignore(root, path)}


def _matches_gitignore(root: Path, relative_path: str) -> bool:
    """Small fallback matcher for uploaded ZIPs that are not Git worktrees."""
    ignored = False
    parts = Path(relative_path).parts
    directories = [root]
    for part in parts[:-1]:
        directories.append(directories[-1] / part)
    for base in directories:
        ignore_file = base / ".gitignore"
        try:
            lines = ignore_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        try:
            scoped = Path(relative_path).relative_to(base.relative_to(root)).as_posix()
        except ValueError:
            scoped = relative_path
        for raw in lines:
            pattern = raw.strip()
            if not pattern or pattern.startswith("#"):
                continue
            negate = pattern.startswith("!")
            if negate:
                pattern = pattern[1:]
            pattern = pattern.lstrip("/")
            directory_rule = pattern.endswith("/")
            pattern = pattern.rstrip("/")
            if not pattern:
                continue
            if "/" in pattern:
                match = fnmatch.fnmatchcase(scoped, pattern) or any(
                    fnmatch.fnmatchcase("/".join(Path(scoped).parts[:index]), pattern)
                    for index in range(1, len(Path(scoped).parts))
                )
            else:
                match = any(fnmatch.fnmatchcase(part, pattern) for part in Path(scoped).parts)
            if directory_rule and not match:
                match = any(fnmatch.fnmatchcase(part, pattern) for part in Path(scoped).parts[:-1])
            if match:
                ignored = not negate
    return ignored