import hashlib
import hmac
import json
import os
import uuid
import io
import zipfile
import subprocess
from subprocess import CompletedProcess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api import app
from src.service.analysis_service import AnalysisService
from src.service.ollama_generation import generate_architecture_spec


client = TestClient(app)


def _architecture_json(title="Target architecture"):
    return {
        "title": title,
        "system_boundary": {"id": "system", "name": "Target"},
        "external_actors_or_services": [],
        "components": [
            {
                "id": "api",
                "name": "API",
                "responsibility": "Accepts requests",
                "evidence": ["app.py:1-2"],
            }
        ],
        "relationships": [],
        "principal_flow": ["Client -> API"],
        "unknowns": [],
    }


def test_ollama_requests_constrained_json_and_accepts_valid_response(monkeypatch):
    import ollama

    calls = []

    class FakeClient:
        def __init__(self, host):
            self.host = host

        def chat(self, **kwargs):
            calls.append(kwargs)
            return {"message": {"content": json.dumps(_architecture_json())}}

    monkeypatch.setattr(ollama, "Client", FakeClient)
    result = generate_architecture_spec(
        {"nodes": [], "edges": []},
        readme="# Target",
        context={"project_name": "Target", "submitted_source": "target"},
        evidence="app.py:1: route",
    )
    assert result["components"][0]["id"] == "api"
    assert calls[0]["format"] == "json"
    assert calls[0]["options"]["temperature"] == 0
    assert calls[0]["options"]["num_predict"] == 2048


def test_ollama_normalizes_string_external_actors(monkeypatch):
    import ollama

    spec = _architecture_json()
    spec["external_actors_or_services"] = ["GitHub Actions", "Ollama"]

    class FakeClient:
        def __init__(self, host):
            pass

        def chat(self, **kwargs):
            return {"message": {"content": json.dumps(spec)}}

    monkeypatch.setattr(ollama, "Client", FakeClient)
    result = generate_architecture_spec(
        {"nodes": [], "edges": []},
        readme="",
        context={"project_name": "Target", "submitted_source": "target"},
        evidence=".github/workflows/ci.yml:1-4",
    )
    assert [item["name"] for item in result["external_actors_or_services"]] == ["GitHub Actions", "Ollama"]
    assert result["external_actors_or_services"][0]["id"] == "external-github-actions"

def test_ollama_normalizes_relationship_field_aliases(monkeypatch):
    import ollama

    spec = _architecture_json()
    spec["components"].append({"id": "model", "name": "Model", "responsibility": "Runs inference"})
    spec["relationships"] = [{"source": "API", "target": "Model", "type": "calls model", "evidence": ["app.py:3-5"]}]

    class FakeClient:
        def __init__(self, host):
            pass

        def chat(self, **kwargs):
            return {"message": {"content": json.dumps(spec)}}

    monkeypatch.setattr(ollama, "Client", FakeClient)
    result = generate_architecture_spec(
        {"nodes": [], "edges": []}, readme="",
        context={"project_name": "Target", "submitted_source": "target"},
        evidence="app.py:1-5",
    )
    assert result["relationships"][0]["source_id"] == "api"
    assert result["relationships"][0]["target_id"] == "model"
    assert result["relationships"][0]["label"] == "calls model"

def test_ollama_retries_invalid_json_once_then_accepts(monkeypatch):
    import ollama

    responses = [
        {"message": {"content": "not JSON at all"}},
        {"message": {"content": json.dumps(_architecture_json("Corrected"))}},
    ]

    class FakeClient:
        def __init__(self, host):
            self.calls = []

        def chat(self, **kwargs):
            self.calls.append(kwargs)
            return responses.pop(0)

    monkeypatch.setattr(ollama, "Client", FakeClient)
    result = generate_architecture_spec(
        {"nodes": [], "edges": []},
        readme="",
        context={"project_name": "Target", "submitted_source": "target"},
        evidence="app.py:1: route",
    )
    assert result["title"] == "Corrected"


def test_ollama_invalid_architecture_fails_with_safe_excerpt(monkeypatch):
    import ollama

    class FakeClient:
        def __init__(self, host):
            pass

        def chat(self, **kwargs):
            return {"message": {"content": "plain text " + ("x" * 400)}}

    monkeypatch.setattr(ollama, "Client", FakeClient)
    with pytest.raises(RuntimeError, match="one correction retry"):
        generate_architecture_spec(
            {"nodes": [], "edges": []},
            readme="",
            context={"project_name": "Target", "submitted_source": "target"},
            evidence="app.py:1: route",
        )


def test_healthcheck():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_web_application_and_project_listing():
    page = client.get("/")
    assert page.status_code == 200
    assert "Code In, Architecture Out" in page.text

    projects = client.get("/api/projects")
    assert projects.status_code == 200
    assert isinstance(projects.json()["projects"], list)


def test_generate_uploaded_source_in_selected_formats():
    response = client.post(
        "/api/generate",
        files={"source_file": ("hello.py", b"def hello():\n    return 1\n", "text/x-python")},
        data={"document_format": "docx", "image_format": "svg"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["documentation"]["filename"] == "documentation.docx"
    assert body["diagram"]["filename"] == "architecture.svg"
    assert body["metadata"]["output_filename"] == "documentation.docx"
    assert body["metadata"]["generated_at"]
    assert body["metadata"]["commit_sha"] == "unavailable"
    assert client.get(body["documentation"]["url"]).headers["content-type"].startswith(
        "application/vnd.openxmlformats"
    )
    assert client.get(body["diagram"]["url"]).headers["content-type"].startswith("image/svg")
    diagram = client.get(body["diagram"]["url"]).content
    assert b"<svg" in diagram
    assert b"Test architecture" in diagram
    assert b"Test component" in diagram
    assert b"SIBLING_FILE" not in diagram


def test_generate_uploaded_zip_in_selected_formats():
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("project/main.py", "class Example:\n    pass\n")
        zipped.writestr("project/README.md", "# Example\n")
    response = client.post(
        "/api/generate",
        files={"source_file": ("project.zip", archive.getvalue(), "application/zip")},
        data={"document_format": "pdf", "image_format": "png"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["documentation"]["filename"] == "documentation.pdf"
    assert body["diagram"]["filename"] == "architecture.png"
    diagram_response = client.get(body["diagram"]["url"])
    assert diagram_response.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(diagram_response.content) > 100


def test_architecture_spec_renderer_uses_components_and_relationships(tmp_path):
    from src.service.report_generator import write_diagram

    spec = {
        "title": "Service architecture",
        "system_boundary": {"id": "system", "name": "Target"},
        "external_actors_or_services": [
            {"id": "client", "name": "Client", "responsibility": "Sends requests"}
        ],
        "components": [
            {"id": "api", "name": "API", "responsibility": "Accepts requests"},
            {"id": "store", "name": "Store", "responsibility": "Persists data"},
        ],
        "relationships": [
            {
                "source_id": "client",
                "target_id": "api",
                "direction": "forward",
                "label": "HTTP request",
                "evidence": ["app.py:1-4"],
            },
            {
                "source_id": "api",
                "target_id": "store",
                "direction": "forward",
                "label": "writes",
                "evidence": ["app.py:5-8"],
            },
        ],
        "principal_flow": ["Client -> API -> Store"],
        "unknowns": [],
    }
    output = tmp_path / "architecture.svg"
    write_diagram(spec, output, "svg")
    rendered = output.read_text(encoding="utf-8")
    assert "Service architecture" in rendered
    assert "HTTP request" in rendered
    assert "API" in rendered and "Store" in rendered
    assert "SIBLING_FILE" not in rendered


def test_generate_github_url_input(monkeypatch, tmp_path):
    (tmp_path / "main.py").write_text("def from_repo():\n    return True\n", encoding="utf-8")
    monkeypatch.setattr(
        AnalysisService,
        "_resolve_repository",
        lambda self, repository_url, branch, commit_sha: (tmp_path, "abc123", "main"),
    )
    response = client.post(
        "/api/generate",
        data={"repository_url": "https://github.com/example/project", "document_format": "pdf", "image_format": "svg"},
    )
    assert response.status_code == 200
    assert response.json()["commit_sha"] == "abc123"


def test_github_target_context_reaches_ollama_and_report(monkeypatch, tmp_path):
    target = tmp_path / "Cancer-Detection-API"
    target.mkdir()
    (target / "README.md").write_text("# Cancer Detection API\n", encoding="utf-8")
    (target / "app.py").write_text("def predict():\n    return {'ok': True}\n", encoding="utf-8")
    captured = {}

    monkeypatch.setattr(
        AnalysisService,
        "_resolve_repository",
        lambda self, repository_url, branch, commit_sha: (
            target,
            "219e1a2578db6d9dc07e992e5560b644a3b2d573",
            "main",
            "Initial API",
            "Cancer-Detection-API",
        ),
    )

    def capture(graph, readme, context, evidence):
        captured["context"] = context
        captured["evidence"] = evidence
        return {
            "title": "Target architecture",
            "system_boundary": {"id": "system", "name": "Cancer-Detection-API"},
            "external_actors_or_services": [],
            "components": [
                {
                    "id": "api",
                    "name": "Cancer API",
                    "responsibility": "Exposes the target API",
                    "evidence": ["app.py:1-2"],
                }
            ],
            "relationships": [],
            "principal_flow": [],
            "unknowns": [],
        }

    monkeypatch.setattr("src.service.analysis_service.generate_architecture_spec", capture)
    response = client.post(
        "/api/generate",
        data={
            "repository_url": "https://github.com/176Anjali/Cancer-Detection-API",
            "document_format": "pdf",
            "image_format": "svg",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["project_name"] == "Cancer-Detection-API"
    assert body["source_repository"].endswith("/Cancer-Detection-API")
    assert body["metadata"]["commit_sha"] == "219e1a2578db6d9dc07e992e5560b644a3b2d573"
    assert captured["context"]["project_name"] == "Cancer-Detection-API"
    assert captured["context"]["submitted_source"].endswith("/Cancer-Detection-API")
    assert captured["context"]["repository_path"] == str(target.resolve())
    assert "app.py:1:" in captured["evidence"]
    assert "README.md:1:" in captured["evidence"]
    report = client.get(body["documentation"]["url"]).content
    assert b"Cancer-Detection-API" in report
    assert b"219e1a2578db6d9dc07e992e5560b644a3b2d573" in report


def test_ollama_failure_returns_clear_error_without_success(monkeypatch):
    monkeypatch.setattr(
        "src.service.analysis_service.generate_architecture_spec",
        lambda graph, readme, context, evidence: (_ for _ in ()).throw(
            RuntimeError("Ollama generation failed at http://unavailable")
        ),
    )
    response = client.post(
        "/api/generate",
        files={"source_file": ("broken.py", b"def broken():\n    pass\n", "text/x-python")},
        data={"document_format": "pdf", "image_format": "png"},
    )
    assert response.status_code == 400
    assert "Ollama generation failed" in response.json()["detail"]
    assert response.json().get("status") is None


def test_report_contains_metadata_and_fallback_diagram_for_non_python_upload():
    response = client.post(
        "/api/generate",
        files={"source_file": ("main.js", b"export function start() { return 1; }\n", "text/javascript")},
        data={"document_format": "pdf", "image_format": "png"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["file_count"] >= 1
    report = client.get(body["documentation"]["url"])
    assert b"documentation.pdf" in report.content
    assert b"Generated at:" in report.content
    assert b"C4 and arc42 architecture views" in report.content
    assert b"REST APIs, data flow, and storage" in report.content
    assert b"Limitations" in report.content
    assert client.get(body["diagram"]["url"]).content.startswith(b"\x89PNG\r\n\x1a\n")


def test_github_sync_report_records_triggering_commit_metadata(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("def synced():\n    return True\n", encoding="utf-8")
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "Trigger CIAO sync"], check=True, capture_output=True)
    source_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    output = tmp_path / "output"
    service = AnalysisService(base_dir=tmp_path)
    summary, document, diagram = service.generate_repository_outputs(
        repo,
        source_sha,
        "pdf",
        "png",
        output,
        metadata={
            "output_filename": "documentation.pdf",
            "output_format": "pdf",
            "generated_at": "2026-01-01T00:00:00+00:00",
            "source_name": "repo",
            "branch": "main",
            "commit_message": "Trigger CIAO sync",
            "commit_sha": source_sha,
            "sync_at": "2026-01-01T00:00:00+00:00",
        },
    )
    assert summary["file_count"] >= 1
    assert document.exists() and diagram.exists()
    report = document.read_bytes()
    assert b"Trigger CIAO sync" in report
    assert source_sha.encode() in report


def test_analyze_project_endpoint():
    repo_root = str(Path(__file__).resolve().parents[1])
    response = client.post(
        "/api/projects/analyze",
        json={"source_path": repo_root, "branch": "main", "pipeline": "graph_validation"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["repository_path"] == repo_root
    assert body["pipeline"] == "graph_validation"
    assert body["summary"]["node_count"] > 0


def test_webhook_accepts_valid_signature():
    payload = b'{"repository": {"full_name": "octocat/demo"}, "after": "abc123"}'
    secret = "test-secret"
    os.environ["CIAO_GITHUB_WEBHOOK_SECRET"] = secret
    signature = "sha256=" + hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()

    response = client.post(
        "/api/github/webhook",
        content=payload,
        headers={
            "X-Hub-Signature-256": signature,
            "X-GitHub-Event": "push",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert body["repository"] == "octocat/demo"


def test_project_status_endpoint():
    repo_root = str(Path(__file__).resolve().parents[1])
    project = client.post(
        "/api/projects/analyze",
        json={"source_path": repo_root, "branch": "main", "pipeline": "graph_validation"},
    ).json()

    response = client.get(f"/api/projects/{project['project_id']}/status")
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    job_response = client.get(f"/api/jobs/{project['job_id']}")
    assert job_response.status_code == 200
    assert job_response.json()["status"] == "completed"
    download = client.get(f"/api/projects/{project['project_id']}/download")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/zip")
    assert b"analysis-manifest.json" in download.content
    documentation = client.get(
        f"/api/projects/{project['project_id']}/documentation/file"
    )
    diagram = client.get(f"/api/projects/{project['project_id']}/diagrams/source")
    assert documentation.status_code == 200
    assert b"Architecture overview" in documentation.content
    assert diagram.status_code == 200
    assert b"@startuml" in diagram.content


def test_project_graph_artifacts_are_revision_scoped():
    repo_root = str(Path(__file__).resolve().parents[1])
    first = client.post(
        "/api/projects/analyze",
        json={
            "source_path": repo_root,
            "project_id": "project-one",
            "commit_sha": "abc123",
            "pipeline": "graph_validation",
        },
    )
    second = client.post(
        "/api/projects/analyze",
        json={
            "source_path": repo_root,
            "project_id": "project-two",
            "commit_sha": "def456",
            "pipeline": "graph_validation",
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    first_path = first.json()["graph_path"]
    second_path = second.json()["graph_path"]
    assert first_path != second_path
    assert "project-one" in first_path
    assert "abc123" in first_path
    assert "project-two" in second_path
    assert "def456" in second_path
    artifact = first.json()["artifacts"][0]
    assert artifact["checksum"]
    assert artifact["size_bytes"] > 0
    artifact_names = {item["name"] for item in first.json()["artifacts"]}
    assert "architecture-overview.md" in artifact_names
    assert "architecture.puml" in artifact_names
    assert first.json()["documentation"]["status"] == "ready"
    assert first.json()["diagrams"]["status"] == "source_ready"


def test_webhook_rejects_invalid_signature():
    response = client.post(
        "/api/github/webhook",
        content=b"{}",
        headers={"X-Hub-Signature-256": "sha256=invalid"},
    )

    assert response.status_code == 401


def test_webhook_rejects_signature_without_configured_secret(monkeypatch):
    monkeypatch.delenv("CIAO_GITHUB_WEBHOOK_SECRET", raising=False)
    response = client.post(
        "/api/github/webhook",
        content=b"{}",
        headers={"X-Hub-Signature-256": "sha256=anything"},
    )

    assert response.status_code == 401


def test_webhook_delivery_is_idempotent():
    payload = (
        b'{"repository": {"full_name": "octocat/demo"}, '
        b'"after": "abc123", "ref": "refs/heads/main"}'
    )
    secret = os.environ.get("CIAO_GITHUB_WEBHOOK_SECRET", "dev-secret")
    signature = "sha256=" + hmac.new(
        secret.encode("utf-8"), payload, hashlib.sha256
    ).hexdigest()
    headers = {
        "X-Hub-Signature-256": signature,
        "X-GitHub-Event": "push",
        "X-GitHub-Delivery": f"delivery-{uuid.uuid4().hex}",
    }

    first = client.post("/api/github/webhook", content=payload, headers=headers)
    second = client.post("/api/github/webhook", content=payload, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["status"] == "accepted"
    assert second.json()["status"] == "duplicate"


def test_repomix_ollama_pipeline_generates_scoped_artifacts(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "example.py").write_text("print('hello')\n", encoding="utf-8")
    base_dir = Path(__file__).resolve().parents[1]
    service = AnalysisService(base_dir=tmp_path)
    (tmp_path / "repomix.config.json").write_text(
        (base_dir / "repomix.config.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / "main.py").write_text("", encoding="utf-8")

    def fake_run(command, *, cwd, env, capture_output, text, encoding, errors, timeout, check):
        source = Path(env["CIAO_FULL_CODE_PATH"])
        documentation = Path(env["CIAO_DOCUMENTATION_PATH"])
        source.parent.mkdir(parents=True, exist_ok=True)
        documentation.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("flattened source", encoding="utf-8")
        documentation.write_text("# Generated docs", encoding="utf-8")
        return CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr("src.service.analysis_service.subprocess.run", fake_run)
    record = service.analyze_repository(
        str(repository),
        project_id="docs-project",
        commit_sha="docs123",
        pipeline="repomix_ollama",
    )

    assert record["status"] == "completed"
    assert record["summary"]["source_bytes"] > 0
    assert all(item["status"] == "generated" for item in record["artifacts"])
    assert "docs-project\\docs123" in record["artifacts"][0]["path"]


def test_repomix_ollama_subprocess_uses_utf8_environment(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    repository.mkdir()
    base_dir = Path(__file__).resolve().parents[1]
    service = AnalysisService(base_dir=tmp_path)
    (tmp_path / "repomix.config.json").write_text(
        (base_dir / "repomix.config.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / "main.py").write_text("", encoding="utf-8")
    captured = {}

    def fake_run(command, *, cwd, env, capture_output, text, encoding, errors, timeout, check):
        captured.update(env)
        source = Path(env["CIAO_FULL_CODE_PATH"])
        documentation = Path(env["CIAO_DOCUMENTATION_PATH"])
        source.parent.mkdir(parents=True, exist_ok=True)
        documentation.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("source", encoding="utf-8")
        documentation.write_text("docs", encoding="utf-8")
        return CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("src.service.analysis_service.subprocess.run", fake_run)
    service.analyze_repository(
        str(repository),
        pipeline="repomix_ollama",
    )
    assert captured["PYTHONIOENCODING"] == "utf-8"
    assert captured["PYTHONUTF8"] == "1"
