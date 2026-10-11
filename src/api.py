from __future__ import annotations

import hashlib
import hmac
import os
from typing import Optional

from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.pipeline_contract import PipelineName
from src.service.analysis_service import AnalysisService


class ProjectAnalyzeRequest(BaseModel):
    repo_url: Optional[str] = None
    source_path: Optional[str] = None
    project_id: Optional[str] = None
    branch: Optional[str] = None
    commit_sha: Optional[str] = None
    pipeline: Optional[str] = "graph_validation"


class GitHubWebhookResponse(BaseModel):
    status: str
    event: str
    repository: str
    commit_sha: Optional[str] = None
    job_id: Optional[str] = None


service = AnalysisService()
app = FastAPI(title="CIAO API", version="0.1.0")
WEB_INDEX = Path(__file__).resolve().parents[1] / "web" / "index.html"


@app.get("/", include_in_schema=False)
def web_application() -> FileResponse:
    return FileResponse(WEB_INDEX)


@app.post("/api/generate")
async def generate_outputs(
    repository_url: Optional[str] = Form(default=None),
    document_format: str = Form(default="pdf"),
    image_format: str = Form(default="svg"),
    source_file: Optional[UploadFile] = File(default=None),
) -> dict:
    upload_bytes = await source_file.read() if source_file else None
    try:
        return service.generate_outputs(
            repository_url=repository_url,
            upload_name=source_file.filename if source_file else None,
            upload_bytes=upload_bytes,
            document_format=document_format,
            image_format=image_format,
        )
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        detail = str(exc)
        if "not found" in detail.lower() or "repository does not exist" in detail.lower():
            detail = f"GitHub repository could not be fetched. Check that the URL is public and valid, or provide access for a private repository. Details: {detail}"
        raise HTTPException(status_code=400, detail=detail) from exc


@app.get("/api/generate/{project_id}/documentation")
def generated_documentation(project_id: str) -> FileResponse:
    paths = list((service.output_dir / project_id).glob("documentation.*"))
    if not paths:
        raise HTTPException(status_code=404, detail="Generated documentation not found")
    path = paths[0]
    media_type = "application/pdf" if path.suffix == ".pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return FileResponse(path, media_type=media_type, filename=path.name)


@app.get("/api/generate/{project_id}/diagram")
def generated_diagram(project_id: str) -> FileResponse:
    paths = list((service.output_dir / project_id).glob("architecture.*"))
    if not paths:
        raise HTTPException(status_code=404, detail="Generated diagram not found")
    path = paths[0]
    media_type = "image/png" if path.suffix == ".png" else "image/svg+xml"
    return FileResponse(path, media_type=media_type, filename=path.name)


def _verify_github_signature(payload: bytes, signature: str) -> bool:
    secret = os.getenv("CIAO_GITHUB_WEBHOOK_SECRET")
    if not secret:
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@app.get("/health")
def healthcheck() -> dict:
    return {"status": "ok"}


@app.get("/api/pipelines")
def list_pipelines() -> dict:
    return {"pipelines": service.available_pipelines()}


@app.get("/api/projects")
def list_projects() -> dict:
    return {"projects": list(service.projects.values())}


@app.post("/api/projects/analyze")
def analyze_project(payload: ProjectAnalyzeRequest) -> dict:
    repository_reference = payload.repo_url or payload.source_path
    if not repository_reference:
        raise HTTPException(status_code=400, detail="Either repo_url or source_path is required")

    try:
        record = service.analyze_repository(
            repository_reference,
            project_id=payload.project_id,
            branch=payload.branch,
            commit_sha=payload.commit_sha,
            pipeline=payload.pipeline,
        )
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return record


@app.get("/api/projects/{project_id}")
def get_project(project_id: str) -> dict:
    try:
        return service.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/status")
def get_project_status(project_id: str) -> dict:
    try:
        project = service.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"project_id": project_id, "status": project["status"], "summary": project["summary"]}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    try:
        return service.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/documentation")
def get_project_documentation(project_id: str) -> dict:
    try:
        project = service.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"project_id": project_id, "documentation": project["documentation"]}


@app.get("/api/projects/{project_id}/documentation/file")
def get_documentation_file(project_id: str) -> FileResponse:
    project = service.get_project(project_id)
    artifact = next(
        (item for item in project["artifacts"] if item["kind"] == "architecture_documentation"),
        None,
    )
    if not artifact:
        raise HTTPException(status_code=404, detail="Architecture documentation is not available")
    return FileResponse(artifact["path"], media_type="text/markdown", filename=artifact["name"])


@app.get("/api/projects/{project_id}/diagrams")
def get_project_diagrams(project_id: str) -> dict:
    try:
        project = service.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"project_id": project_id, "diagrams": project["diagrams"]}


@app.get("/api/projects/{project_id}/diagrams/source")
def get_diagram_source(project_id: str) -> FileResponse:
    project = service.get_project(project_id)
    artifact = next(
        (item for item in project["artifacts"] if item["kind"] == "plantuml_source"),
        None,
    )
    if not artifact:
        raise HTTPException(status_code=404, detail="Diagram source is not available")
    return FileResponse(artifact["path"], media_type="text/plain", filename=artifact["name"])


@app.get("/api/projects/{project_id}/graph")
def get_project_graph(project_id: str) -> dict:
    try:
        return service.graph_for_project(project_id)
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/download")
def download_project(project_id: str) -> FileResponse:
    try:
        package_path = service.package_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        package_path,
        media_type="application/zip",
        filename=package_path.name,
    )


@app.get("/api/projects/{project_id}/changes")
def get_project_changes(project_id: str) -> dict:
    try:
        project = service.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"project_id": project_id, "changes": project.get("changes", [])}


@app.post("/api/github/webhook", response_model=GitHubWebhookResponse)
async def github_webhook(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(default=None, alias="X-Hub-Signature-256"),
    x_github_event: Optional[str] = Header(default=None, alias="X-GitHub-Event"),
) -> dict:
    payload = await request.body()
    if not x_hub_signature_256:
        raise HTTPException(status_code=401, detail="Missing X-Hub-Signature-256 header")

    if not _verify_github_signature(payload, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid GitHub signature")

    body = await request.json()
    event = x_github_event or "unknown"
    delivery_id = request.headers.get("X-GitHub-Delivery")
    if delivery_id and not service.register_delivery(delivery_id, event):
        return {
            "status": "duplicate",
            "event": event,
            "repository": body.get("repository", {}).get("full_name", "unknown"),
            "commit_sha": body.get("after") or body.get("head_sha"),
        }
    repository = body.get("repository", {})
    repository_name = repository.get("full_name", "unknown")
    commit_sha = body.get("after") or body.get("head_sha")
    if event != "push" or not repository.get("clone_url") or not commit_sha:
        return {
            "status": "accepted",
            "event": event,
            "repository": repository_name,
            "commit_sha": commit_sha,
        }
    project_id = "github-" + repository_name.replace("/", "-")
    try:
        record = service.analyze_repository(
            repository["clone_url"],
            project_id=project_id,
            branch=(body.get("ref") or "").removeprefix("refs/heads/") or None,
            commit_sha=commit_sha,
            pipeline=PipelineName.GRAPH_VALIDATION.value,
        )
    except (RuntimeError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "status": "accepted",
        "event": event,
        "repository": repository_name,
        "commit_sha": commit_sha,
        "job_id": record["job_id"],
    }


@app.post("/api/projects/{project_id}/sync")
def sync_project(project_id: str) -> dict:
    try:
        record = service.sync_project(project_id)
    except (KeyError, FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return record
