from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List


class PipelineName(str, Enum):
    GRAPH_VALIDATION = "graph_validation"
    REPOMIX_OLLAMA = "repomix_ollama"


@dataclass
class ArtifactMetadata:
    name: str
    kind: str
    path: str
    stage: str = "analysis"
    status: str = "generated"
    checksum: str | None = None
    size_bytes: int | None = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PipelineResult:
    project_id: str
    pipeline: PipelineName
    repository_path: str
    branch: str
    commit_sha: str
    status: str = "completed"
    generated_at: str = ""
    summary: Dict[str, Any] = field(default_factory=dict)
    artifacts: List[ArtifactMetadata] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "pipeline": self.pipeline.value,
            "repository_path": self.repository_path,
            "branch": self.branch,
            "commit_sha": self.commit_sha,
            "status": self.status,
            "generated_at": self.generated_at,
            "summary": self.summary,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "warnings": self.warnings,
            "errors": self.errors,
            "metadata": self.metadata,
        }
