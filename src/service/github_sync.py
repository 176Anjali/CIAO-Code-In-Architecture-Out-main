from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse


@dataclass(frozen=True)
class SyncResult:
    repository_path: Path
    commit_sha: str
    branch: str
    commit_message: str
    repository_name: str


class GitHubSync:
    """Materialize a remote Git repository at an immutable detached revision."""

    def __init__(self, cache_dir: str | Path, *, command_timeout: int = 300):
        self.cache_dir = Path(cache_dir).resolve()
        self.command_timeout = command_timeout

    def sync(
        self,
        repository_url: str,
        *,
        branch: Optional[str] = None,
        commit_sha: Optional[str] = None,
    ) -> SyncResult:
        repository_url = self._normalize_url(repository_url)
        self._validate_url(repository_url)
        repository_key = hashlib.sha256(repository_url.encode("utf-8")).hexdigest()[:16]
        repository_dir = self.cache_dir / repository_key
        requested_revision = commit_sha or branch or "default"
        checkout_dir = repository_dir / self._safe_revision(requested_revision)

        if not checkout_dir.exists():
            checkout_dir.parent.mkdir(parents=True, exist_ok=True)
            self._run(["git", "clone", "--no-checkout", repository_url, str(checkout_dir)])

        if commit_sha:
            self._run(["git", "-C", str(checkout_dir), "fetch", "origin", commit_sha])
            self._run(["git", "-C", str(checkout_dir), "checkout", "--detach", commit_sha])
        elif branch:
            self._run(["git", "-C", str(checkout_dir), "fetch", "origin", branch])
            self._run(
                [
                    "git",
                    "-C",
                    str(checkout_dir),
                    "checkout",
                    "--detach",
                    f"origin/{branch}",
                ]
            )
        else:
            self._run(["git", "-C", str(checkout_dir), "fetch", "origin"])
            self._run(["git", "-C", str(checkout_dir), "checkout", "--detach", "FETCH_HEAD"])

        resolved_sha = self._run(
            ["git", "-C", str(checkout_dir), "rev-parse", "HEAD"]
        ).stdout.strip()
        resolved_branch = branch or "default"
        commit_message = self._run(
            ["git", "-C", str(checkout_dir), "log", "-1", "--format=%B"]
        ).stdout.strip()
        repository_name = urlparse(repository_url).path.rstrip("/").split("/")[-1]
        if repository_name.lower().endswith(".git"):
            repository_name = repository_name[:-4]
        return SyncResult(checkout_dir, resolved_sha, resolved_branch, commit_message, repository_name)

    def _run(self, command: List[str]) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=self.command_timeout,
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()
            raise RuntimeError(
                f"Git command failed ({' '.join(command[:3])}): {detail}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Git command timed out after {self.command_timeout}s"
            ) from exc

    def _validate_url(self, repository_url: str) -> None:
        parsed = urlparse(repository_url)
        if parsed.scheme not in {"http", "https", "ssh", "git"}:
            if not repository_url.startswith("git@"):
                raise ValueError("Repository URL must use HTTPS, SSH, or Git")
        if parsed.scheme in {"http", "https"} and parsed.netloc.lower() == "github.com":
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) != 2:
                raise ValueError("GitHub URL must look like https://github.com/owner/repository")

    def _normalize_url(self, repository_url: str) -> str:
        value = repository_url.strip()
        parsed = urlparse(value)
        if parsed.scheme in {"http", "https"} and parsed.netloc.lower() == "github.com":
            path = parsed.path.rstrip("/")
            if path.lower().endswith(".git"):
                path = path[:-4]
            return f"{parsed.scheme}://{parsed.netloc}{path}"
        return value

    def _safe_revision(self, revision: str) -> str:
        safe = "".join(
            character if character.isalnum() or character in "._-" else "_"
            for character in revision
        )
        return safe[:80] or "default"
