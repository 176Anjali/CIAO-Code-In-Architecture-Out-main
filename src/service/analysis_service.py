from __future__ import annotations

import json
import io
import hashlib
import os
import subprocess
import sys
import uuid
import zipfile
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from src.graph.knowledge_graph import RepositoryKnowledgeGraph
from src.generator.uml_generator import UMLGenerator
from src.pipeline_contract import ArtifactMetadata, PipelineName
from src.service.github_sync import GitHubSync
from src.service.state_store import StateStore
from src.service.report_generator import architecture_text, write_diagram, write_document
from src.service.ollama_generation import generate_architecture_spec, validate_output


@dataclass(frozen=True)
class AnalysisContext:
    submitted_source: str
    project_name: str
    repository_path: str
    branch: str
    commit_sha: str
    commit_message: str
    file_manifest: List[str]
    document_format: str
    image_format: str
    generated_at: str
    sync_at: Optional[str] = None


class AnalysisService:
    """Coordinate repo analyses and keep the existing CIAO pipelines available to APIs."""

    def __init__(self, base_dir: str | Path | None = None):
        self.base_dir = Path(base_dir).resolve() if base_dir else Path(__file__).resolve().parents[2]
        self.output_dir = self.base_dir / "output"
        self.github_sync = GitHubSync(self.output_dir / ".github-cache")
        self.state = StateStore(self.output_dir / "ciao-state.json")
        self.projects: Dict[str, Dict[str, Any]] = {}
        persisted = self.state.read()
        self.projects.update(persisted.get("projects", {}))

    def available_pipelines(self) -> List[str]:
        return [item.value for item in PipelineName]

    def generate_outputs(
        self,
        *,
        repository_url: Optional[str],
        upload_name: Optional[str],
        upload_bytes: Optional[bytes],
        document_format: str,
        image_format: str,
    ) -> Dict[str, Any]:
        if bool(repository_url) == bool(upload_bytes):
            raise ValueError("Provide exactly one GitHub URL or uploaded source file/archive")
        if document_format not in {"pdf", "docx"}:
            raise ValueError("document_format must be pdf or docx")
        if image_format not in {"png", "svg"}:
            raise ValueError("image_format must be png or svg")

        temporary_root = Path(tempfile.mkdtemp(prefix="ciao-input-"))
        try:
            if repository_url:
                resolved = self._resolve_repository(repository_url, branch=None, commit_sha=None)
                if len(resolved) == 3:
                    source_path, commit_sha, branch = resolved
                    commit_message, repository_name = "", repository_url.rstrip("/").split("/")[-1]
                else:
                    source_path, commit_sha, branch, commit_message, repository_name = resolved
            else:
                source_path = self._materialize_upload(temporary_root, upload_name or "source", upload_bytes or b"")
                commit_sha, branch, commit_message, repository_name = "unavailable", "unavailable", "", upload_name or "uploaded source"
            project_id = f"analysis-{uuid.uuid4().hex[:10]}"
            output_dir = self.output_dir / project_id
            generated_at = datetime.now().astimezone().isoformat()
            context = self._build_analysis_context(
                submitted_source=repository_url or upload_name or "uploaded source",
                source_path=source_path,
                project_name=repository_name,
                branch=branch,
                commit_sha=commit_sha,
                commit_message=commit_message,
                document_format=document_format,
                image_format=image_format,
                generated_at=generated_at,
            )
            summary, document_path, diagram_path = self.generate_repository_outputs(
                source_path, commit_sha, document_format, image_format, output_dir,
                metadata={
                    "output_filename": f"documentation.{document_format}",
                    "output_format": document_format,
                    "generated_at": generated_at,
                    "source_name": repository_name,
                    "branch": branch,
                    "commit_message": commit_message,
                    "commit_sha": commit_sha,
                },
                context=context,
            )
            validate_output(document_path, document_format)
            validate_output(diagram_path, image_format)
            if document_path.stat().st_size == 0 or diagram_path.stat().st_size == 0:
                raise RuntimeError("CIAO generated an empty output; analysis did not complete")
            return {
                "status": "completed",
                "project_id": project_id,
                "commit_sha": commit_sha,
                "branch": branch,
                "input": repository_url or upload_name,
                "source_repository": context.submitted_source,
                "project_name": context.project_name,
                "metadata": {
                    "output_filename": document_path.name,
                    "output_format": document_format,
                    "generated_at": generated_at,
                    "source_name": repository_name,
                    "branch": branch,
                    "commit_message": commit_message or "Unavailable for uploaded input",
                    "commit_sha": commit_sha,
                    "source_repository": context.submitted_source,
                    "project_name": context.project_name,
                    "file_count": len(context.file_manifest),
                },
                "summary": summary,
                "limitations": [
                    "A single source file cannot establish the whole project architecture.",
                    "Only relationships evidenced by the submitted source are included.",
                ],
                "documentation": {
                    "format": document_format,
                    "filename": document_path.name,
                    "url": f"/api/generate/{project_id}/documentation",
                },
                "diagram": {
                    "format": image_format,
                    "filename": diagram_path.name,
                    "url": f"/api/generate/{project_id}/diagram",
                },
            }
        finally:
            shutil.rmtree(temporary_root, ignore_errors=True)

    def generate_repository_outputs(
        self,
        source_path: Path,
        commit_sha: str,
        document_format: str,
        image_format: str,
        output_dir: Path,
        metadata: Optional[Dict[str, str]] = None,
        require_ollama: bool = True,
        context: Optional[AnalysisContext] = None,
    ) -> tuple[Dict[str, Any], Path, Path]:
        if context is None:
            metadata = metadata or {}
            context = self._build_analysis_context(
                submitted_source=metadata.get("source_repository", str(source_path)),
                source_path=source_path,
                project_name=metadata.get("source_name", source_path.name),
                branch=metadata.get("branch", "Unavailable"),
                commit_sha=commit_sha,
                commit_message=metadata.get("commit_message", "Unavailable"),
                document_format=document_format,
                image_format=image_format,
                generated_at=metadata.get("generated_at", datetime.now().astimezone().isoformat()),
                sync_at=metadata.get("sync_at"),
            )
        self._validate_analysis_context(context, source_path)
        graph_builder = RepositoryKnowledgeGraph(str(source_path))
        graph_builder.build()
        graph = graph_builder.to_dict()
        if not graph.get("nodes"):
            graph = self._fallback_file_graph(source_path)
        graph_path = output_dir / "graph" / "repository_graph.json"
        graph_path.parent.mkdir(parents=True, exist_ok=True)
        graph_path.write_text(json.dumps(graph, indent=2, ensure_ascii=False), encoding="utf-8")
        summary = self._summarize_graph(graph)
        try:
            evidence = self._collect_target_evidence(source_path, context.file_manifest)
            architecture_spec = generate_architecture_spec(
                graph,
                readme=self._read_readme(source_path),
                context=asdict(context),
                evidence=evidence,
            )
            ollama_description = json.dumps(architecture_spec, indent=2, ensure_ascii=False)
        except RuntimeError:
            if require_ollama:
                raise
            architecture_spec = {
                "title": "Architecture unavailable",
                "system_boundary": {"id": "system", "name": context.project_name},
                "external_actors_or_services": [],
                "components": [],
                "relationships": [],
                "principal_flow": [],
                "unknowns": ["Ollama architecture specification was unavailable."],
            }
            ollama_description = "Ollama generation was skipped for this legacy pipeline."
        document_path = output_dir / f"documentation.{document_format}"
        diagram_path = output_dir / f"architecture.{image_format}"
        report_metadata = dict(metadata or {})
        report_metadata.setdefault("output_filename", document_path.name)
        report_metadata.setdefault("output_format", document_format)
        report_metadata.setdefault("generated_at", datetime.now().astimezone().isoformat())
        report_metadata.setdefault("source_name", source_path.name)
        report_metadata.setdefault("branch", "Unavailable")
        report_metadata.setdefault("commit_message", "Unavailable")
        report_metadata.setdefault("commit_sha", commit_sha)
        report_metadata.update({
            "source_repository": context.submitted_source,
            "project_name": context.project_name,
            "repository_path": context.repository_path,
            "file_manifest": context.file_manifest,
        })
        report_text = architecture_text(
            source_path,
            commit_sha,
            graph,
            self._read_readme(source_path),
            report_metadata,
            ollama_description,
            context=asdict(context),
        )
        write_document(report_text, document_path, document_format)
        write_diagram(architecture_spec, diagram_path, image_format)
        return summary, document_path, diagram_path

    def _build_analysis_context(
        self,
        *,
        submitted_source: str,
        source_path: Path,
        project_name: str,
        branch: str,
        commit_sha: str,
        commit_message: str,
        document_format: str,
        image_format: str,
        generated_at: str,
        sync_at: Optional[str] = None,
    ) -> AnalysisContext:
        manifest = self._target_file_manifest(source_path)
        if not manifest:
            raise RuntimeError("The submitted target produced an empty evidence manifest")
        return AnalysisContext(
            submitted_source=submitted_source,
            project_name=project_name or source_path.name,
            repository_path=str(source_path.resolve()),
            branch=branch or "Unavailable",
            commit_sha=commit_sha or "Unavailable",
            commit_message=commit_message or "Unavailable",
            file_manifest=manifest,
            document_format=document_format,
            image_format=image_format,
            generated_at=generated_at,
            sync_at=sync_at,
        )

    def _target_file_manifest(self, source_path: Path) -> List[str]:
        root = source_path if source_path.is_dir() else source_path.parent
        if not root.exists():
            return []
        if source_path.is_file():
            return [source_path.name]
        return sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file()
            and ".git" not in path.parts
            and not path.is_symlink()
            and path.stat().st_size <= 2_000_000
        )[:500]

    def _collect_target_evidence(self, source_path: Path, manifest: List[str]) -> str:
        root = source_path if source_path.is_dir() else source_path.parent
        evidence_suffixes = {
            ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs", ".cs",
            ".json", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".md", ".txt",
            ".xml",
        }
        sections: List[str] = []
        for relative in manifest:
            path = root / relative
            if path.suffix.lower() not in evidence_suffixes and path.name.lower() != "dockerfile":
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            if not lines:
                continue
            limit = min(len(lines), 240)
            sections.append(
                f"FILE {relative} LINES 1-{limit}\n"
                + "\n".join(
                    f"{relative}:{index}: {lines[index - 1]}"
                    for index in range(1, limit + 1)
                )
            )
        if not sections:
            raise RuntimeError("The submitted target produced no readable evidence files")
        return "\n\n".join(sections)[:120_000]

    def _validate_analysis_context(self, context: AnalysisContext, source_path: Path) -> None:
        resolved = source_path.resolve()
        if resolved != Path(context.repository_path).resolve():
            raise RuntimeError("Analysis context does not match the resolved target repository")
        if not context.file_manifest or not resolved.exists():
            raise RuntimeError("Resolved target repository is unavailable or has no evidence")

    def _fallback_file_graph(self, source_path: Path) -> Dict[str, Any]:
        root = source_path if source_path.is_dir() else source_path.parent
        files = [
            path for path in root.rglob("*")
            if path.is_file() and ".git" not in path.parts and path.stat().st_size <= 2_000_000
        ][:120]
        nodes = []
        for path in files:
            nodes.append({
                "id": f"file:{path.resolve()}",
                "type": "file",
                "name": path.name,
                "path": str(path.resolve()),
            })
        edges = []
        for left, right in zip(nodes, nodes[1:]):
            edges.append({"source": left["id"], "target": right["id"], "relationship": "SIBLING_FILE"})
        return {"nodes": nodes, "edges": edges}

    def generated_file(self, project_id: str, kind: str) -> Path:
        base = self.output_dir / project_id
        matches = list(base.glob(f"*.{kind}"))
        if not matches:
            raise FileNotFoundError(f"Generated {kind} output not found")
        return matches[0]

    def _materialize_upload(self, root: Path, name: str, data: bytes) -> Path:
        safe_name = Path(name).name or "source"
        if safe_name.lower().endswith(".zip"):
            extract_root = root / "source"
            extract_root.mkdir()
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for member in archive.infolist():
                    target = (extract_root / member.filename).resolve()
                    if not str(target).startswith(str(extract_root.resolve())):
                        raise ValueError("ZIP archive contains an unsafe path")
                archive.extractall(extract_root)
            return extract_root
        path = root / safe_name
        path.write_bytes(data)
        return root

    def _read_readme(self, source_path: Path) -> str:
        if source_path.is_file():
            return ""
        for name in ("README.md", "README", "README.txt"):
            candidate = source_path / name
            if candidate.exists():
                return candidate.read_text(encoding="utf-8", errors="replace")
        return ""

    def analyze_repository(
        self,
        repository_reference: str,
        *,
        project_id: Optional[str] = None,
        commit_sha: Optional[str] = None,
        branch: Optional[str] = None,
        pipeline: Optional[str] = None,
    ) -> Dict[str, Any]:
        job_id = f"job-{uuid.uuid4().hex}"
        self._save_job(job_id, "running", project_id=project_id, pipeline=pipeline)
        pipeline_name = PipelineName(pipeline or PipelineName.GRAPH_VALIDATION.value)
        try:
            resolved = self._resolve_repository(
                repository_reference, branch=branch, commit_sha=commit_sha
            )
            if len(resolved) == 3:
                repository_path, resolved_commit_sha, resolved_branch = resolved
            else:
                repository_path, resolved_commit_sha, resolved_branch, _, _ = resolved
            project_key = project_id or f"project-{uuid.uuid4().hex[:8]}"
            revision_key = self._revision_key(resolved_commit_sha)
            project_output_dir = self.output_dir / project_key / revision_key

            if pipeline_name == PipelineName.GRAPH_VALIDATION:
                graph_builder = RepositoryKnowledgeGraph(str(repository_path))
                graph = graph_builder.build()
                graph_path = project_output_dir / "graph" / "repository_graph.json"
                graph_builder.save_json(graph_path)
                summary = self._summarize_graph(graph)
                artifacts = [
                    ArtifactMetadata(
                        name="repository_graph.json",
                        kind="graph",
                        path=str(graph_path),
                        stage="analysis",
                        status="generated",
                    )
                ]
                architecture_dir = project_output_dir / "architecture"
                architecture_dir.mkdir(parents=True, exist_ok=True)
                puml_path = architecture_dir / "architecture.puml"
                puml = UMLGenerator(
                    graph_path=graph_path,
                    output_dir=architecture_dir,
                )
                puml_path = puml.save(puml.generate())
                documentation_path = architecture_dir / "architecture-overview.md"
                documentation_path.write_text(
                    self._architecture_document(
                        repository_path,
                        resolved_commit_sha,
                        summary,
                        graph,
                    ),
                    encoding="utf-8",
                )
                artifacts.extend(
                    [
                        ArtifactMetadata(
                            name=documentation_path.name,
                            kind="architecture_documentation",
                            path=str(documentation_path),
                            stage="documentation",
                        ),
                        ArtifactMetadata(
                            name=puml_path.name,
                            kind="plantuml_source",
                            path=str(puml_path),
                            stage="diagram_source",
                        ),
                    ]
                )
                for generated_artifact in artifacts[1:]:
                    artifact_path = Path(generated_artifact.path)
                    generated_artifact.checksum = self._file_checksum(artifact_path)
                    generated_artifact.size_bytes = artifact_path.stat().st_size
                artifact = artifacts[0]
                artifact.checksum = self._file_checksum(graph_path)
                artifact.size_bytes = graph_path.stat().st_size
            else:
                summary, artifacts = self._run_repomix_ollama(
                    repository_path,
                    project_output_dir,
                )

            timestamp = datetime.now(timezone.utc).isoformat()
            record = {
                "project_id": project_key,
                "job_id": job_id,
                "repository_reference": repository_reference,
                "repository_path": str(repository_path),
                "pipeline": pipeline_name.value,
                "status": "completed",
                "branch": resolved_branch,
                "commit_sha": resolved_commit_sha,
                "generated_at": timestamp,
                "summary": summary,
                "graph_path": str(project_output_dir / "graph" / "repository_graph.json"),
                "documentation": {
                    "status": "ready",
                    "path": str(project_output_dir / "architecture"),
                },
                "diagrams": {
                    "status": "source_ready" if pipeline_name == PipelineName.GRAPH_VALIDATION else "pending",
                    "count": 1 if pipeline_name == PipelineName.GRAPH_VALIDATION else 0,
                    "items": [
                        {
                            "name": "architecture.puml",
                            "path": str(project_output_dir / "architecture" / "architecture.puml"),
                            "rendered": False,
                            "reason": "PNG/SVG rendering requires PlantUML.",
                        }
                    ] if pipeline_name == PipelineName.GRAPH_VALIDATION else [],
                },
                "changes": [],
                "artifacts": [artifact.to_dict() for artifact in artifacts],
            }
            self.projects[project_key] = record
            self._persist_projects()
            self._save_job(job_id, "completed", project_id=project_key, pipeline=pipeline_name.value)
            return record
        except Exception as exc:
            self._save_job(job_id, "failed", project_id=project_id, pipeline=pipeline, error=str(exc))
            raise

    def get_project(self, project_id: str) -> Dict[str, Any]:
        if project_id not in self.projects:
            raise KeyError(f"Project {project_id} not found")
        return self.projects[project_id]

    def get_job(self, job_id: str) -> Dict[str, Any]:
        job = self.state.get_job(job_id)
        if job is None:
            raise KeyError(f"Job {job_id} not found")
        return job

    def register_delivery(self, delivery_id: str, event: str) -> bool:
        state = self.state.read()
        deliveries = state.setdefault("deliveries", {})
        if delivery_id in deliveries:
            return False
        deliveries[delivery_id] = {
            "event": event,
            "received_at": datetime.now(timezone.utc).isoformat(),
        }
        self.state.write(state)
        return True

    def _persist_projects(self) -> None:
        state = self.state.read()
        state["projects"] = self.projects
        self.state.write(state)

    def _save_job(
        self,
        job_id: str,
        status: str,
        *,
        project_id: Optional[str],
        pipeline: Optional[str],
        error: Optional[str] = None,
    ) -> None:
        state = self.state.read()
        jobs = state.setdefault("jobs", {})
        job = jobs.get(job_id, {"job_id": job_id, "created_at": datetime.now(timezone.utc).isoformat()})
        job.update({"status": status, "project_id": project_id, "pipeline": pipeline})
        if error:
            job["error"] = error
        if status in {"completed", "failed"}:
            job["finished_at"] = datetime.now(timezone.utc).isoformat()
        jobs[job_id] = job
        self.state.write(state)

    def sync_project(self, project_id: str) -> Dict[str, Any]:
        project = self.get_project(project_id)
        return self.analyze_repository(
            project["repository_path"],
            project_id=project_id,
            branch=project.get("branch"),
            commit_sha=project.get("commit_sha"),
            pipeline=project.get("pipeline", PipelineName.GRAPH_VALIDATION.value),
        )

    def _resolve_repository(
        self,
        repository_reference: str,
        *,
        branch: Optional[str],
        commit_sha: Optional[str],
    ) -> tuple[Path, str, str, str, str]:
        if not repository_reference or not str(repository_reference).strip():
            raise ValueError("A repository path or URL is required")

        if repository_reference.startswith(("http://", "https://", "git@")):
            result = self.github_sync.sync(
                repository_reference,
                branch=branch,
                commit_sha=commit_sha,
            )
            return (
                result.repository_path,
                result.commit_sha,
                result.branch,
                result.commit_message,
                result.repository_name,
            )

        candidate = Path(repository_reference).expanduser().resolve()
        if not candidate.exists():
            raise FileNotFoundError(f"Repository path does not exist: {candidate}")
        return candidate, commit_sha or "working-tree", branch or "main", "", candidate.name

    def _revision_key(self, commit_sha: Optional[str]) -> str:
        value = (commit_sha or "working-tree").strip()
        safe_value = "".join(
            character if character.isalnum() or character in "._-" else "_"
            for character in value
        )
        return safe_value[:80] or "working-tree"

    def _file_checksum(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _run_repomix_ollama(
        self,
        repository_path: Path,
        project_output_dir: Path,
    ) -> tuple[Dict[str, Any], List[ArtifactMetadata]]:
        source_path = project_output_dir / "source" / "full_code.txt"
        documentation_path = project_output_dir / "docs" / "arc42_documentation.txt"
        config_path = project_output_dir / "repomix.config.json"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        documentation_path.parent.mkdir(parents=True, exist_ok=True)

        config = json.loads(
            (self.base_dir / "repomix.config.json").read_text(encoding="utf-8")
        )
        config["output"]["filePath"] = str(source_path)
        config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

        environment = os.environ.copy()
        environment.update(
            {
                "CIAO_REPOMIX_CONFIG_PATH": str(config_path),
                "CIAO_FULL_CODE_PATH": str(source_path),
                "CIAO_DOCUMENTATION_PATH": str(documentation_path),
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUTF8": "1",
            }
        )
        try:
            completed = subprocess.run(
                [sys.executable, str(self.base_dir / "main.py"), str(repository_path)],
                cwd=str(self.base_dir),
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=1800,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Repomix/Ollama pipeline timed out after 1800 seconds") from exc

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(
                f"Repomix/Ollama pipeline failed with exit code "
                f"{completed.returncode}: {detail}"
            )

        missing = [
            str(path)
            for path in (source_path, documentation_path)
            if not path.exists()
        ]
        if missing:
            raise RuntimeError(
                "Repomix/Ollama pipeline completed without generating: "
                + ", ".join(missing)
            )

        artifacts = [
            ArtifactMetadata(
                name=source_path.name,
                kind="repository_snapshot",
                path=str(source_path),
                stage="source_capture",
            ),
            ArtifactMetadata(
                name=documentation_path.name,
                kind="documentation",
                path=str(documentation_path),
                stage="documentation",
            ),
        ]
        for artifact in artifacts:
            artifact_path = Path(artifact.path)
            artifact.checksum = self._file_checksum(artifact_path)
            artifact.size_bytes = artifact_path.stat().st_size

        return {
            "source_bytes": source_path.stat().st_size,
            "documentation_bytes": documentation_path.stat().st_size,
        }, artifacts

    def _summarize_graph(self, graph: Dict[str, Any]) -> Dict[str, Any]:
        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])

        type_counts: Dict[str, int] = {}
        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_type = str(node.get("type", "unknown"))
            type_counts[node_type] = type_counts.get(node_type, 0) + 1

        return {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "file_count": type_counts.get("file", 0),
            "class_count": type_counts.get("class", 0),
            "function_count": type_counts.get("function", 0),
            "method_count": type_counts.get("method", 0),
            "module_count": type_counts.get("module", 0),
            "variable_count": type_counts.get("variable", 0),
        }

    def _architecture_document(
        self,
        repository_path: Path,
        commit_sha: str,
        summary: Dict[str, Any],
        graph: Dict[str, Any],
    ) -> str:
        node_types: Dict[str, int] = {}
        for node in graph.get("nodes", []):
            if isinstance(node, dict):
                kind = str(node.get("type", "unknown"))
                node_types[kind] = node_types.get(kind, 0) + 1
        relationships: Dict[str, int] = {}
        for edge in graph.get("edges", []):
            if isinstance(edge, dict):
                kind = str(edge.get("relationship", "unknown"))
                relationships[kind] = relationships.get(kind, 0) + 1
        node_lines = "\n".join(
            f"- `{kind}`: {count}" for kind, count in sorted(node_types.items())
        )
        relationship_lines = "\n".join(
            f"- `{kind}`: {count}" for kind, count in sorted(relationships.items())
        )
        return (
            "# Architecture overview\n\n"
            f"- **Repository:** `{repository_path}`\n"
            f"- **Analyzed revision:** `{commit_sha}`\n"
            f"- **Files analyzed:** {summary['file_count']}\n"
            f"- **Graph nodes:** {summary['node_count']}\n"
            f"- **Relationships:** {summary['edge_count']}\n\n"
            "## Detected components\n\n"
            f"{node_lines or '- No components detected.'}\n\n"
            "## Relationships\n\n"
            f"{relationship_lines or '- No relationships detected.'}\n\n"
            "## Evidence and limitations\n\n"
            "This document is generated from static analysis of the submitted revision. "
            "PlantUML source is included alongside this document; rendered images require "
            "a PlantUML runtime and are not claimed when unavailable.\n"
        )

    def graph_for_project(self, project_id: str) -> Dict[str, Any]:
        project = self.get_project(project_id)
        graph_path = Path(project["graph_path"])
        if not graph_path.exists():
            raise FileNotFoundError(f"Graph file does not exist: {graph_path}")
        with graph_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def package_project(self, project_id: str) -> Path:
        project = self.get_project(project_id)
        package_dir = self.output_dir / project_id / self._revision_key(project["commit_sha"])
        package_path = package_dir / f"CIAO-{project_id}-report.zip"
        manifest = {
            "project_id": project_id,
            "pipeline": project["pipeline"],
            "repository_reference": project["repository_reference"],
            "commit_sha": project["commit_sha"],
            "generated_at": project["generated_at"],
            "status": project["status"],
            "artifacts": project["artifacts"],
            "skipped_outputs": [
                {
                    "path": "diagrams/*.png",
                    "reason": "Rendered image output requires PlantUML and is not available in this run.",
                },
                {
                    "path": "documentation/api-reference.md",
                    "reason": "API documentation is only included when endpoint evidence is detected.",
                },
            ],
        }
        package_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = package_dir / "analysis-manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        readme = package_dir / "README.md"
        readme.write_text(
            "# CIAO Analysis Report\n\n"
            f"- Project: `{project_id}`\n"
            f"- Pipeline: `{project['pipeline']}`\n"
            f"- Commit: `{project['commit_sha']}`\n\n"
            "This package contains traceable outputs from the CIAO analysis run. "
            "Skipped outputs and their reasons are recorded in `analysis-manifest.json`.\n",
            encoding="utf-8",
        )
        with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(readme, "README.md")
            archive.write(manifest_path, "analysis-manifest.json")
            for artifact in project["artifacts"]:
                artifact_path = Path(artifact["path"])
                if artifact_path.exists():
                    archive.write(artifact_path, f"artifacts/{artifact_path.name}")
        return package_path
