#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.service.analysis_service import AnalysisService
from src.service.ollama_generation import validate_output


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the CIAO static analysis pipeline on a repository.")
    parser.add_argument("--repo", required=True, help="Local repository path to analyze")
    parser.add_argument("--project-id", default=None, help="Optional project identifier")
    parser.add_argument("--branch", default="main", help="Repository branch to record")
    parser.add_argument("--commit-sha", default="unknown", help="Commit SHA to record")
    parser.add_argument("--document-format", choices=["pdf", "docx"], default="pdf")
    parser.add_argument("--image-format", choices=["png", "svg"], default="png")
    parser.add_argument("--output-dir", default=".", help="Root directory for generated files")
    parser.add_argument(
        "--pipeline",
        default="graph_validation",
        choices=["graph_validation", "repomix_ollama"],
        help="CIAO pipeline to execute for this repository revision",
    )
    args = parser.parse_args()

    service = AnalysisService()
    source = Path(args.repo).resolve()
    output_dir = Path(args.output_dir).resolve()
    commit_message = subprocess.run(
        ["git", "-C", str(source), "log", "-1", "--format=%B"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    remote = subprocess.run(
        ["git", "-C", str(source), "config", "--get", "remote.origin.url"],
        check=False,
        capture_output=True,
        text=True,
    ).stdout.strip() or str(source)
    generated_at = datetime.now().astimezone().isoformat()
    staging_root = Path(tempfile.mkdtemp(prefix="ciao-sync-"))
    try:
        summary, document_path, diagram_path = service.generate_repository_outputs(
            source,
            args.commit_sha,
            args.document_format,
            args.image_format,
            staging_root,
            require_ollama=True,
            metadata={
                "output_filename": f"documentation.{args.document_format}",
                "output_format": args.document_format,
                "generated_at": generated_at,
                "source_name": source.name,
                "source_repository": remote,
                "branch": args.branch,
                "commit_message": commit_message,
                "commit_sha": args.commit_sha,
                "sync_at": generated_at,
            },
        )
        validate_output(document_path, args.document_format)
        validate_output(diagram_path, args.image_format)
        root_document = output_dir / f"documentation.{args.document_format}"
        root_diagram = output_dir / f"architecture.{args.image_format}"
        staged_document = output_dir / f".ciao-staging-{document_path.name}"
        staged_diagram = output_dir / f".ciao-staging-{diagram_path.name}"
        staged_document.write_bytes(document_path.read_bytes())
        staged_diagram.write_bytes(diagram_path.read_bytes())
    except Exception:
        shutil.rmtree(staging_root, ignore_errors=True)
        raise
    manifest = {
        "tool": "CIAO",
        "commit_sha": args.commit_sha,
        "commit_message": commit_message,
        "branch": args.branch,
        "generated_at": generated_at,
        "sync_at": generated_at,
        "document": root_document.name,
        "diagram": root_diagram.name,
        "summary": summary,
    }
    (output_dir / "ciao-generation.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    shutil.move(str(staged_document), str(root_document))
    shutil.move(str(staged_diagram), str(root_diagram))
    shutil.rmtree(staging_root, ignore_errors=True)
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
