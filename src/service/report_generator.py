from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List


def architecture_text(
    repository_path: Path,
    commit_sha: str,
    graph: Dict[str, Any],
    readme: str,
    metadata: Dict[str, str],
    ollama_description: str,
    context: Dict[str, Any] | None = None,
) -> str:
    context = context or {}
    nodes = [node for node in graph.get("nodes", []) if isinstance(node, dict)]
    edges = [edge for edge in graph.get("edges", []) if isinstance(edge, dict)]
    counts: Dict[str, int] = {}
    for node in nodes:
        kind = str(node.get("type", "unknown"))
        counts[kind] = counts.get(kind, 0) + 1
    relationships: Dict[str, int] = {}
    for edge in edges:
        kind = str(edge.get("relationship", "unknown"))
        relationships[kind] = relationships.get(kind, 0) + 1
    file_names = sorted(
        Path(str(node.get("path", node.get("name", node.get("id", ""))))).name
        for node in nodes
        if node.get("type") == "file"
    )
    readme_excerpt = readme.strip()[:4000] if readme.strip() else "No README was found."
    evidence = _repository_evidence(repository_path, readme)
    def value(key: str, fallback: str = "Unavailable") -> str:
        return metadata.get(key) or fallback

    return f"""CIAO Architecture Report

Report metadata
- Output filename: {value("output_filename")}
- Output format: {value("output_format")}
- Generated at: {value("generated_at")}
- Submitted source: {context.get("submitted_source") or value("source_name")}
- Target project: {context.get("project_name") or value("source_name")}
- Resolved target repository: {context.get("repository_path") or repository_path}
- Branch: {value("branch")}
- Source commit message: {value("commit_message")}
- Source commit ID: {value("commit_sha")}
- GitHub sync time: {value("sync_at", "Not a GitHub sync run")}

Analyzed revision
- Repository: {context.get("project_name") or value("source_name")}
- Commit: {commit_sha}
- Source files represented in graph: {counts.get("file", 0)}
- Graph nodes: {len(nodes)}
- Relationships: {len(edges)}

Abstract
{evidence["summary"]}

Introduction
{evidence["introduction"]}

Problem, goals, and scope
{evidence["problem"]}

Repository overview
The analyzed input contains {counts.get("file", 0)} detected files, {counts.get("module", 0)}
modules, {counts.get("class", 0)} classes, {counts.get("function", 0)} functions, and
{counts.get("method", 0)} methods.

Technologies, frameworks, dependencies, and resources
{evidence["technologies"]}

Repository structure and important files
Detected file names:
{chr(10).join(f"- {name}" for name in file_names[:80]) or "- No file names were available."}

How the project works and its pipelines
{evidence["pipelines"]}

C4 and arc42 architecture views
Context: {evidence["context"]}
Containers and components are represented only by detected graph nodes and relationships.
The arc42 sections for context, building blocks, runtime/data flow, deployment, and risks are
limited to repository evidence listed in this report.

Ollama architecture analysis
{ollama_description or "Unavailable because Ollama generation was not completed."}

REST APIs, data flow, and storage
APIs: {evidence["apis"]}
Storage/resources: {evidence["storage"]}
Data flow: detected relationships are summarized below.
{chr(10).join(f"- {kind}: {value}" for kind, value in sorted(relationships.items())) or "- No relationships were detected."}

Build, testing, CI/CD, and deployment
{evidence["delivery"]}

Setup and usage
{evidence["setup"]}

Repository README evidence
{readme_excerpt}

Architecture view
The accompanying architecture image shows the supported graph nodes and relationships. It is a
structural view of evidence found in source code, not a claim about runtime deployment.

Limitations
- A single source file cannot establish the complete project purpose, deployment model, or
  relationships outside that file.
- APIs, storage, CI/CD, and security properties are reported only when supported by source or
  repository files.
- Dynamic behavior and external services may not be visible to static analysis.

Source reference
- Generated from commit: {commit_sha}
- Repository input: {repository_path}
- Evidence files inspected: {evidence["inspected"]}
"""


def _repository_evidence(repository_path: Path, readme: str) -> Dict[str, str]:
    root = repository_path if repository_path.is_dir() else repository_path.parent
    files = [
        path for path in root.rglob("*")
        if path.is_file() and ".git" not in path.parts and path.stat().st_size <= 1_000_000
    ][:250]
    names = [path.relative_to(root).as_posix() for path in files]
    lower_names = [name.lower() for name in names]
    text_parts: List[str] = []
    for path in files:
        if path.suffix.lower() in {".py", ".js", ".ts", ".java", ".go", ".rs", ".cs", ".json", ".yml", ".yaml", ".toml", ".md", ".txt"}:
            try:
                text_parts.append(path.read_text(encoding="utf-8", errors="replace")[:100_000])
            except OSError:
                continue
    corpus = "\n".join(text_parts)
    heading = next((line.lstrip("# ").strip() for line in readme.splitlines() if line.startswith("#")), "")
    requirements = [name for name in names if any(token in name.lower() for token in ("requirements", "pyproject", "package.json", "pom.xml", "cargo.toml", "go.mod"))]
    technologies = []
    for token, label in (
        ("fastapi", "FastAPI"), ("flask", "Flask"), ("django", "Django"),
        ("react", "React"), ("vue", "Vue"), ("express", "Express"),
        ("networkx", "NetworkX"), ("ollama", "Ollama"), ("pytest", "pytest"),
    ):
        if token in corpus.lower():
            technologies.append(label)
    api_hits = re.findall(r"(?im)^\s*[@\w.()'\"]*(?:get|post|put|patch|delete)\s*\(\s*[\"']([^\"']+)", corpus)
    api_text = ", ".join(sorted(set(api_hits))[:20]) if api_hits else "No REST route evidence was detected."
    storage_tokens = [label for token, label in (("sqlite", "SQLite"), ("postgres", "PostgreSQL"), ("mysql", "MySQL"), ("redis", "Redis"), ("mongodb", "MongoDB"), ("open(", "filesystem files")) if token in corpus.lower()]
    delivery_files = [name for name in names if any(token in name.lower() for token in (".github/workflows", "dockerfile", "docker-compose", "makefile", "pytest", "test", "tox.ini"))]
    setup_lines = [line.strip() for line in readme.splitlines() if re.search(r"(install|setup|usage|run|start|pip |npm |docker)", line, re.I)]
    return {
        "summary": f"The report describes {heading or 'the submitted source revision'} using static-analysis and README evidence. Unsupported runtime behavior is not inferred.",
        "introduction": heading or "The project purpose cannot be determined from the available README and source evidence.",
        "problem": "The repository does not state a problem, goal, or scope clearly enough to report." if not readme else "Goals and scope are reported only where stated in the README; the available README excerpt is included below.",
        "technologies": f"Detected technologies: {', '.join(technologies) or 'No named framework or library could be confirmed.'}. Dependency/resource manifests: {', '.join(requirements) or 'No dependency manifest was detected.'}",
        "pipelines": "Detected source relationships and pipeline-like files are represented in the graph. No runtime pipeline can be confirmed beyond those relationships.",
        "context": "A user or external system context is not evidenced by the submitted source." if not any(token in corpus.lower() for token in ("http", "api", "client", "server", "web")) else "Web/API/client evidence is present in repository text; exact runtime actors remain implementation-dependent.",
        "apis": api_text,
        "storage": ", ".join(sorted(set(storage_tokens))) or "No database, queue, or object-storage evidence was detected.",
        "delivery": f"Relevant build/test/CI/deployment files: {', '.join(delivery_files) or 'None detected.'}",
        "setup": "\n".join(f"- {line}" for line in setup_lines[:20]) or "No supported setup or usage instructions were detected.",
        "inspected": ", ".join(names[:80]) or "No files were available.",
    }


def write_document(text: str, path: Path, fmt: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "docx":
        _write_docx(text, path)
    elif fmt == "pdf":
        _write_pdf(text, path)
    else:
        raise ValueError("document_format must be pdf or docx")


def write_diagram(architecture_spec: Dict[str, Any], path: Path, fmt: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "svg":
        path.write_text(_architecture_svg(architecture_spec), encoding="utf-8")
    elif fmt == "png":
        path.write_bytes(_architecture_png(architecture_spec))
    else:
        raise ValueError("image_format must be png or svg")


def _write_docx(text: str, path: Path) -> None:
    import zipfile

    paragraphs = "".join(
        f"<w:p><w:r><w:t xml:space=\"preserve\">{html.escape(line)}</w:t></w:r></w:p>"
        for line in text.splitlines()
    )
    document = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{paragraphs}</w:body></w:document>"""
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>"""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document)


def _write_pdf(text: str, path: Path) -> None:
    lines = [line[:110] for line in text.splitlines()]
    content = ["BT", "/F1 9 Tf", "50 760 Td"]
    for line in lines[:140]:
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        content.append(f"({escaped}) Tj")
        content.append("0 -12 Td")
    content.append("ET")
    stream = "\n".join(content).encode("latin-1", "replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode())
    output.extend("".join(f"{offset:010d} 00000 n \n" for offset in offsets[1:]).encode())
    output.extend(f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    path.write_bytes(output)


def _svg(graph: Dict[str, Any]) -> str:
    nodes = [node for node in graph.get("nodes", []) if isinstance(node, dict) and node.get("id")][:60]
    edges = [edge for edge in graph.get("edges", []) if isinstance(edge, dict)]
    width, height = 1200, max(260, ((len(nodes) + 5) // 6) * 70)
    positions = {node["id"]: (80 + (i % 6) * 190, 45 + (i // 6) * 70) for i, node in enumerate(nodes)}
    lines = []
    edge_labels = []
    for edge in edges:
        start, end = positions.get(edge.get("source")), positions.get(edge.get("target"))
        if start and end:
            lines.append(f'<line x1="{start[0]}" y1="{start[1]}" x2="{end[0]}" y2="{end[1]}" stroke="#64748b" stroke-width="1" marker-end="url(#arrow)"/>')
            edge_labels.append(f'<text x="{(start[0] + end[0]) // 2}" y="{(start[1] + end[1]) // 2 - 4}" fill="#9fb4d2" font-size="8" text-anchor="middle">{html.escape(str(edge.get("relationship", ""))[:18])}</text>')
    labels = []
    for node in nodes:
        x, y = positions[node["id"]]
        label = html.escape(str(node.get("name") or node["id"]).replace("\\", "/").split("/")[-1][:22])
        kind = html.escape(str(node.get("type", "component"))[:14])
        labels.append(f'<g><rect x="{x-58}" y="{y-18}" width="116" height="36" rx="8" fill="#172a4d" stroke="#5b9cff"/><text x="{x}" y="{y-2}" text-anchor="middle" fill="#eef5ff" font-size="10">{label}</text><text x="{x}" y="{y+11}" text-anchor="middle" fill="#9fb4d2" font-size="7">{kind}</text></g>')
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3 z" fill="#64748b"/></marker></defs><rect width="100%" height="100%" fill="#0b1220"/>{"".join(lines)}{"".join(edge_labels)}{"".join(labels)}</svg>'


def _png(graph: Dict[str, Any]) -> bytes:
    from PIL import Image, ImageDraw

    width, height = 1200, max(260, ((min(len(graph.get("nodes", [])), 60) + 5) // 6) * 70)
    image = Image.new("RGB", (width, height), (11, 18, 32))
    draw = ImageDraw.Draw(image)
    nodes = [node for node in graph.get("nodes", []) if isinstance(node, dict) and node.get("id")][:60]
    positions = {node["id"]: (80 + (i % 6) * 190, 45 + (i // 6) * 70) for i, node in enumerate(nodes)}
    for edge in graph.get("edges", []):
        start, end = positions.get(edge.get("source")), positions.get(edge.get("target"))
        if start and end:
            x1, y1, x2, y2 = start[0], start[1], end[0], end[1]
            steps = max(abs(x2 - x1), abs(y2 - y1), 1)
            for i in range(steps + 1):
                x, y = round(x1 + (x2 - x1) * i / steps), round(y1 + (y2 - y1) * i / steps)
                if 0 <= x < width and 0 <= y < height:
                    draw.point((x, y), fill=(100, 148, 210))
            relationship = str(edge.get("relationship", ""))[:14]
            draw.text(((x1 + x2) // 2, (y1 + y2) // 2 - 8), relationship, fill=(159, 180, 210), anchor="mm")
    for node in nodes:
        x, y = positions[node["id"]]
        draw.rounded_rectangle((x - 58, y - 18, x + 58, y + 18), radius=8, fill=(38, 74, 125), outline=(91, 156, 255))
        label = str(node.get("name") or node["id"]).replace("\\", "/").split("/")[-1][:18]
        kind = str(node.get("type", "component"))[:12]
        draw.text((x, y - 5), label, fill=(238, 245, 255), anchor="mm")
        draw.text((x, y + 8), kind, fill=(159, 180, 210), anchor="mm")
    import io
    result = io.BytesIO()
    image.save(result, format="PNG")
    return result.getvalue()


def _architecture_svg(spec: Dict[str, Any]) -> str:
    components = [item for item in spec.get("components", []) if item.get("id")][:40]
    external = [item for item in spec.get("external_actors_or_services", []) if item.get("id")][:20]
    nodes = external + components
    ids = {item["id"] for item in nodes}
    width, height = 1400, max(360, ((len(nodes) + 4) // 5) * 120)
    positions = {item["id"]: (150 + (i % 5) * 270, 110 + (i // 5) * 120) for i, item in enumerate(nodes)}
    lines, labels = [], []
    for relationship in spec.get("relationships", []):
        start = positions.get(relationship.get("source_id"))
        end = positions.get(relationship.get("target_id"))
        if not start or not end or relationship.get("source_id") not in ids or relationship.get("target_id") not in ids:
            continue
        lines.append(f'<line x1="{start[0]}" y1="{start[1]}" x2="{end[0]}" y2="{end[1]}" stroke="#7aa2d8" stroke-width="2" marker-end="url(#arrow)"/>')
        labels.append(f'<text x="{(start[0] + end[0]) // 2}" y="{(start[1] + end[1]) // 2 - 8}" fill="#c5d7ef" font-size="12" text-anchor="middle">{html.escape(str(relationship.get("label", ""))[:34])}</text>')
    boxes = []
    for item in nodes:
        x, y = positions[item["id"]]
        name = html.escape(str(item.get("name") or item["id"])[:28])
        responsibility = html.escape(str(item.get("responsibility", ""))[:42])
        fill = "#244b73" if item in components else "#3e526b"
        boxes.append(f'<g><rect x="{x-105}" y="{y-38}" width="210" height="76" rx="12" fill="{fill}" stroke="#8bb8f2"/><text x="{x}" y="{y-12}" text-anchor="middle" fill="#f3f7ff" font-size="14">{name}</text><text x="{x}" y="{y+12}" text-anchor="middle" fill="#c5d7ef" font-size="10">{responsibility}</text></g>')
    title = html.escape(str(spec.get("title", "Evidence-backed architecture")))
    unknowns = spec.get("unknowns", [])
    note = html.escape(("Unknowns: " + "; ".join(str(item) for item in unknowns[:2]))[:180])
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto"><path d="M0,0 L0,6 L9,3 z" fill="#7aa2d8"/></marker></defs><rect width="100%" height="100%" fill="#0b1220"/><text x="40" y="42" fill="#f3f7ff" font-size="22">{title}</text><text x="40" y="{height-28}" fill="#9fb4d2" font-size="11">{note}</text>{"".join(lines)}{"".join(labels)}{"".join(boxes)}</svg>'


def _architecture_png(spec: Dict[str, Any]) -> bytes:
    from PIL import Image, ImageDraw
    import io

    components = [item for item in spec.get("components", []) if item.get("id")][:40]
    external = [item for item in spec.get("external_actors_or_services", []) if item.get("id")][:20]
    nodes = external + components
    width, height = 1400, max(360, ((len(nodes) + 4) // 5) * 120)
    image = Image.new("RGB", (width, height), (11, 18, 32))
    draw = ImageDraw.Draw(image)
    positions = {item["id"]: (150 + (i % 5) * 270, 110 + (i // 5) * 120) for i, item in enumerate(nodes)}
    for relationship in spec.get("relationships", []):
        start = positions.get(relationship.get("source_id"))
        end = positions.get(relationship.get("target_id"))
        if not start or not end:
            continue
        draw.line((start[0], start[1], end[0], end[1]), fill=(122, 162, 216), width=3)
        draw.text(((start[0] + end[0]) // 2, (start[1] + end[1]) // 2 - 12), str(relationship.get("label", ""))[:28], fill=(197, 215, 239), anchor="mm")
    draw.text((40, 30), str(spec.get("title", "Evidence-backed architecture"))[:90], fill=(243, 247, 255))
    for item in nodes:
        x, y = positions[item["id"]]
        draw.rounded_rectangle((x - 105, y - 38, x + 105, y + 38), radius=12, fill=(36, 75, 115), outline=(139, 184, 242), width=2)
        draw.text((x, y - 10), str(item.get("name") or item["id"])[:26], fill=(243, 247, 255), anchor="mm")
        draw.text((x, y + 12), str(item.get("responsibility", ""))[:38], fill=(197, 215, 239), anchor="mm")
    result = io.BytesIO()
    image.save(result, format="PNG")
    return result.getvalue()
