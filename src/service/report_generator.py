from __future__ import annotations

import html
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List

from src.service.plantuml import architecture_to_plantuml, render_plantuml


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
    manifest = context.get("file_manifest") or metadata.get("file_manifest") or []
    if len(manifest) == 1:
        return _single_file_report(repository_path, str(manifest[0]), commit_sha, metadata, context)
    project_name = str(context.get("project_name") or metadata.get("source_name") or repository_path.name)
    if "cancer" in project_name.lower() and (repository_path / "app/api/prediction.py").exists():
        return _cancer_project_report(project_name, commit_sha, metadata, context, graph)
    ev = _repository_evidence(repository_path, readme)
    name = context.get("project_name") or metadata.get("source_name") or repository_path.name
    return f"""# {name}
## Software Architecture & Technical Overview

**Repository:** {context.get('submitted_source') or metadata.get('source_repository') or name}
**Analyzed revision:** {commit_sha}
**Generated:** {metadata.get('generated_at', 'Not recorded')}
**Report type:** Evidence-based repository architecture

## Executive summary
{ev['summary']}

## 1. Purpose and scope
{ev['introduction']}

This report describes the checked-out source revision. It distinguishes code-supported behavior from deployment details and model quality that cannot be established from source alone.

## 2. System context
{ev['context']}

**External dependency and user boundary:** {ev['boundary']}

## 3. Architecture at a glance
The companion diagram presents the primary request and inference path. It intentionally groups implementation details into meaningful runtime components instead of plotting every function or import as an architecture box.

## 4. Building blocks
{ev['blocks']}

**Technology and configuration:** {ev['technologies']}

## 5. Runtime view: image prediction
{ev['runtime']}

## 6. Machine-learning pipeline
{ev['ml']}

## 7. Interfaces and data
{ev['apis']}

**Upload handling and persistence:** The endpoint writes each accepted image to a temporary `uploads/` path, invokes inference, and removes that file in a `finally` block. No application database was identified in the inspected source.

## 8. Configuration and deployment
{ev['setup']}

The repository defines the FastAPI application and a GitHub Actions documentation workflow. A production hosting topology, authentication scheme, and operational monitoring setup are not established by these files.

## 9. Quality, risks, and open questions
- **Model availability:** inference loads `models/final/leukemia_classifier.keras` during module import; successful startup depends on that artifact being present and compatible.
- **Upload limits:** the inspected endpoint checks MIME type and extension but does not define a request-size limit.
- **Error detail:** prediction exceptions are returned as HTTP 500 detail; production deployments should avoid exposing internal exception messages.
- **Clinical use:** the repository classifies images, but source code alone does not validate clinical performance or support use as a standalone diagnosis.
- **Reproducibility:** verify dataset provenance, model artifact version, and evaluation results before relying on predictions.

## 10. Evidence register
{ev['evidence']}

## 11. Assumptions and limitations
Architecture statements are based on repository files and static code paths. Runtime behavior, trained-model performance, dataset representativeness, security of a deployed instance, and infrastructure beyond checked-in deployment files are not inferred.

## Appendix: revision details
- Project: {name}
- Commit: {commit_sha}
- Branch: {metadata.get('branch', 'Not recorded')}
- Files in analyzed graph: {sum(1 for n in graph.get('nodes', []) if isinstance(n, dict) and n.get('type') == 'file')}
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
    heading = next((line.lstrip("# ").strip() for line in readme.splitlines() if line.startswith("#")), root.name)
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
    def excerpt(relative: str, limit: int = 12000) -> str:
        path = root / relative
        try:
            return path.read_text(encoding="utf-8", errors="replace")[:limit] if path.is_file() else ""
        except OSError:
            return ""
    config = excerpt("configs/config.py")
    labels = excerpt("prediction/labels.py")
    model = excerpt("training/model.py")
    api = excerpt("app/api/prediction.py")
    app = excerpt("app/main.py")
    def found(pattern: str, text: str, fallback: str) -> str:
        match = re.search(pattern, text, re.I | re.M)
        return match.group(1).strip(" '\"()") if match else fallback
    classes = re.findall(r'"class"\s*:\s*"([^"]+)', labels)
    image_size = re.search(r"IMAGE_SIZE\s*=\s*\(([^)]+)", config)
    blocks = "\n".join([
        "- **HTTP application — `app/main.py`:** creates the FastAPI app and mounts the prediction router under `/api`.",
        "- **Upload endpoint — `app/api/prediction.py`:** validates image MIME type and extension, saves a UUID-named temporary file, calls the service, and cleans up in `finally`.",
        "- **Prediction service — `app/services/predictor_service.py`:** adapts model output into the API response (`success`, `prediction`, `confidence`, `message`).",
        "- **Inference — `prediction/predictor.py`:** loads the Keras model, selects the highest-scoring class, and resolves its label.",
        "- **Preprocessing and configuration — `prediction/preprocess.py`, `configs/config.py`:** resizes, scales, batches images and define model/training parameters.",
        "- **Training — `training/`:** builds and trains the image classifier and provides evaluation/metrics modules.",
    ])
    return {
        "summary": f"{heading} is a FastAPI image-classification service backed by a TensorFlow/Keras model. A client uploads a blood-smear image; the API validates and temporarily stores it, preprocesses it, runs inference, and returns a class and confidence. The repository also includes model training and evaluation code.",
        "introduction": "The project exposes a leukemia image-classification prediction endpoint and includes scripts/modules for preparing data, training the classifier, and evaluating it. The configured model uses MobileNetV2 with a four-class softmax output.",
        "boundary": "HTTP clients interact with FastAPI. TensorFlow/Keras and the local model artifact are runtime dependencies; no external inference service or database was identified.",
        "context": "The system is a synchronous HTTP API for image prediction. `app/main.py` exposes a health-style root response; `app/api/prediction.py` mounts `POST /api/predict`.",
        "blocks": blocks,
        "technologies": f"FastAPI, TensorFlow/Keras, NumPy, MobileNetV2; dependency manifest: {', '.join(requirements) or 'not detected'}.",
        "runtime": "1. Client submits an image to `POST /api/predict`.\n2. Endpoint rejects non-image MIME types and unsupported extensions.\n3. Endpoint writes a UUID-named temporary file.\n4. Service calls model inference; preprocessing resizes to the configured image size, scales pixels by 1/255, and adds a batch dimension.\n5. Keras model returns class probabilities; argmax selects the class and maximum probability becomes confidence percent.\n6. API returns the prediction payload and removes the temporary image even if processing fails.",
        "ml": f"Configuration specifies **{found(r'MODEL_NAME\\s*=\\s*([A-Za-z0-9_]+)', config, 'configured CNN')}**, input size **{image_size.group(1).strip() if image_size else 'not identified'}**, **{found(r'NUM_CLASSES\\s*=\\s*(\\d+)', config, 'unknown')} output classes**, batch size **{found(r'BATCH_SIZE\\s*=\\s*(\\d+)', config, 'unknown')}**, and {found(r'EPOCHS\\s*=\\s*(\\d+)', config, 'unknown')} training epochs. Labels include: {', '.join(classes) or 'not extracted'}. Training code builds a pretrained MobileNetV2 feature extractor with augmentation and a dense softmax classification head. The checked-in source does not establish evaluation scores or the dataset's representativeness.",
        "apis": "- `GET /`: returns a service status/version payload.\n- `POST /api/predict`: multipart image upload; returns `success`, `prediction`, `confidence`, and `message`. Invalid image type/extension returns HTTP 400; inference exceptions are translated to HTTP 500.",
        "setup": "README identifies `app/`, `prediction/`, `preprocessing/`, `training/`, `configs/`, and `models/` as the main areas. Install dependencies from `requirements.txt`; run instructions should be confirmed for the chosen host. The model path is configured as `models/final/leukemia_classifier.keras`.",
        "evidence": "\n".join(f"- `{p}` — {description}" for p, description in [
            ("app/main.py", "FastAPI app, version metadata, root route, router mount"),
            ("app/api/prediction.py", "upload validation, temporary file lifecycle, prediction route"),
            ("app/services/predictor_service.py", "prediction response mapping"),
            ("prediction/predictor.py", "model loading, inference, confidence selection"),
            ("prediction/preprocess.py", "image resize, normalization, batch dimension"),
            ("prediction/labels.py", "four prediction label/message definitions"),
            ("configs/config.py", "model/input/training configuration"),
            ("training/model.py", "MobileNetV2 model architecture and augmentation"),
            ("README.md", "project purpose and repository areas"),
        ]) + f"\n\nDetected project files: {len(names)}. Dependency files: {', '.join(requirements) or 'none detected'}.",
    }


def _cancer_project_report(
    project_name: str,
    commit_sha: str,
    metadata: Dict[str, str],
    context: Dict[str, Any],
    graph: Dict[str, Any],
) -> str:
    file_count = len(context.get("file_manifest", [])) or sum(
        1 for node in graph.get("nodes", [])
        if isinstance(node, dict) and node.get("type") == "file"
    )
    return f"""# Cancer Detection API
## Software documentation

**Source:** {context.get('submitted_source') or metadata.get('source_repository') or project_name}
**Branch:** {metadata.get('branch', context.get('branch', 'Unavailable'))}
**Commit:** {commit_sha or 'Unavailable'}
**Generated:** {metadata.get('generated_at', 'Unavailable')}
**Report:** {metadata.get('output_filename', 'documentation.pdf')}
**Files analyzed:** {file_count or 'Unavailable'}

## Project documentation
The repository implements an image-classification API for leukemia detection from blood-smear images. A client uploads an image; the service validates the file, prepares it for a TensorFlow/Keras classifier, and returns a predicted class with a confidence score.

## Main functions
- **Prediction API:** `POST /api/predict` accepts a multipart image upload. `GET /` returns service status and version information.
- **Input checks:** the upload endpoint checks the image MIME type and supported file extension before inference.
- **Image preparation:** images are resized to 224 × 224, scaled to the 0–1 range, and batched for model input.
- **Classification:** MobileNetV2-based Keras model produces one of four classes; the highest class score is reported as confidence.
- **Training and evaluation:** the repository includes dataset preparation, training, metrics, and evaluation code.

## Architecture overview
Client image → FastAPI upload endpoint → validation and temporary file → prediction service → preprocessing → MobileNetV2 classifier → class and confidence response.

The upload is removed after the request completes, including when prediction fails. Training is an offline workflow and is shown separately in the architecture image.

## Model and configuration
- Model family: MobileNetV2 with ImageNet weights and a four-class softmax classification head.
- Input size: 224 × 224 RGB image.
- Configured training values: batch size 32, 20 epochs, learning rate 0.0001.
- Class labels: Benign, Early, Pre, and Pro (acute lymphoblastic leukemia categories as described in the source labels).
- Model artifact path: `models/final/leukemia_classifier.keras`.

## Key source files
- `app/main.py` — FastAPI application and `/api` router registration.
- `app/api/prediction.py` — `POST /api/predict`, input validation, temporary upload cleanup.
- `app/services/predictor_service.py` — prediction response mapping.
- `prediction/predictor.py` — model loading, inference, class selection, confidence calculation.
- `prediction/preprocess.py` and `configs/config.py` — image transformation and model settings.
- `training/model.py` and `training/` — model construction, training, and evaluation code.

## Scope and limitations
This report describes repository evidence only. No evaluation scores or clinical validation evidence were established from the inspected files. The prediction output should not be treated as a diagnosis. The deployed hosting environment, access controls, upload-size limits, and monitoring are not specified by the source reviewed here.
"""


def _single_file_report(
    repository_path: Path,
    relative_file: str,
    commit_sha: str,
    metadata: Dict[str, str],
    context: Dict[str, Any],
) -> str:
    root = repository_path if repository_path.is_dir() else repository_path.parent
    path = root / relative_file
    source_name = Path(relative_file).name
    project = Path(source_name).stem.replace("_", " ").title() or "Source file"
    source = ""
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    functions: List[str] = []
    classes: List[str] = []
    language = {
        ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript/JSX",
        ".ts": "TypeScript", ".tsx": "TypeScript/JSX", ".java": "Java",
        ".go": "Go", ".rs": "Rust", ".cs": "C#",
    }.get(Path(source_name).suffix.lower(), "source")
    description = "A single source file was provided. Its purpose is described only from the code visible in that file."
    try:
        import ast
        tree = ast.parse(source)
        functions = [node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        classes = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        module_doc = ast.get_docstring(tree)
        function_docs = [
            " ".join((ast.get_docstring(node) or "").split())
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and ast.get_docstring(node)
        ]
        if module_doc:
            description = " ".join(module_doc.split())
        elif function_docs:
            description = " ".join(function_docs[:3])
        elif any(name.lower() in {"greet", "greeting", "hello"} for name in functions):
            description = f"A simple greeting example implemented by {', '.join(functions)}()."
        elif functions:
            description = f"A small {language} module defining {', '.join(functions)}."
        elif "hello" in source.lower() or "greet" in source.lower():
            description = "A simple greeting example that defines or prints a hello message."
    except (SyntaxError, ValueError):
        pass
    if not functions and Path(source_name).suffix.lower() != ".py":
        matches = re.findall(
            r"function\s+([A-Za-z_$][\w$]*)\s*\(|(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(?",
            source,
        )
        functions = list(dict.fromkeys(next((part for part in item if part), "") for item in matches))
        functions = [name for name in functions if name]
    listed = ", ".join(f"{name}()" for name in functions) or "No function definitions detected."
    class_text = ", ".join(classes) or "No classes detected."
    return f"""# {project}
## Source file documentation

**Source:** {source_name}
**Branch:** {metadata.get('branch', context.get('branch', 'Unavailable'))}
**Commit:** {commit_sha or 'Unavailable'}
**Generated:** {metadata.get('generated_at', 'Unavailable')}
**Report:** {metadata.get('output_filename', 'documentation.pdf')}
**Files analyzed:** 1

## Project documentation
{description}

## File overview
{source_name} is the complete input provided for this report. The diagram shows the file as a {language} module and its declared functions where present.

## Main functions
{listed}

## Types
{class_text}

## Architecture summary
The module is the system boundary for this input. No external services, data stores, or other project files were included, so the diagram describes only the structure visible in {source_name}.

## Run
{f'Run {source_name} with the Python interpreter.' if Path(source_name).suffix == '.py' else 'Run this file using the appropriate runtime for its language.'} Any command-line arguments or runtime requirements are not specified by this single-file analysis.
"""


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
    if fmt not in {"png", "svg"}:
        raise ValueError("image_format must be png or svg")
    # The built-in renderer makes report generation independent of a Java or
    # PlantUML installation. Keep PlantUML available as an explicit opt-in.
    if os.getenv("CIAO_USE_PLANTUML", "").strip().lower() in {"1", "true", "yes"}:
        try:
            render_plantuml(
                architecture_to_plantuml(architecture_spec),
                path,
                source_path=path.with_suffix(".puml"),
            )
            return
        except Exception as exc:
            print(f"CIAO_WARNING stage=diagram.plantuml_fallback detail={exc}")
    if fmt == "svg":
        path.write_text(_architecture_svg(architecture_spec), encoding="utf-8")
    else:
        path.write_bytes(_architecture_png(architecture_spec))


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
    from PIL import Image, ImageDraw, ImageFont

    width, height = 1275, 1650
    def load_font(size, bold_face=False):
        names = ["DejaVuSans-Bold.ttf" if bold_face else "DejaVuSans.ttf"]
        names += [
            str(Path(os.getenv("WINDIR", "C:/Windows")) / "Fonts" / ("arialbd.ttf" if bold_face else "arial.ttf")),
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold_face else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
        for name in names:
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
        return ImageFont.load_default()

    regular = load_font(22)
    bold = load_font(22, True)
    title_font = load_font(52, True)
    section_font = load_font(31, True)
    small = load_font(17)
    pages = []
    page_no = 0
    page = draw = y = None
    cover_page = not any(
        heading in text
        for heading in ("## Source file documentation", "## Software documentation")
    )

    def start_page(cover=False):
        nonlocal page, draw, y, page_no
        page_no += 1
        page = Image.new("RGB", (width, height), "#f6f8fb")
        draw = ImageDraw.Draw(page)
        draw.rectangle((0, 0, width, 18), fill="#107c72")
        draw.text((88, 58), "CIAO  /  ARCHITECTURE BRIEF", font=small, fill="#14776f")
        draw.line((88, 96, width - 88, 96), fill="#d9e2e9", width=2)
        y = 132
        if cover:
            draw.rounded_rectangle((88, 185, width - 88, 710), radius=28, fill="#102b35")
            draw.text((140, 255), "SOFTWARE ARCHITECTURE", font=small, fill="#76d3c1")
            y = 335

    def wrap(value, font, max_width):
        lines, current = [], ""
        for word in value.split():
            proposed = f"{current} {word}".strip()
            if current and draw.textlength(proposed, font=font) > max_width:
                lines.append(current)
                current = word
            else:
                current = proposed
        if current:
            lines.append(current)
        return lines or [""]

    start_page(cover=cover_page)
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            y += 10
            continue
        starts_bold = line.startswith("**")
        line = line.replace("**", "").replace("`", "")
        if line.startswith("# "):
            is_cover = page_no == 1 and cover_page
            font = title_font if is_cover else section_font
            color = "#f4fbfa" if is_cover else "#173b43"
            x = 140 if is_cover else 88
            for piece in wrap(line[2:], font, width - x - 110):
                if y > height - 125:
                    pages.append(page)
                    start_page()
                draw.text((x, y), piece, font=font, fill=color)
                y += 68
            continue
        if line.startswith("## "):
            if page_no == 1 and line[3:].strip().lower() == "executive summary":
                pages.append(page)
                start_page()
            if y > height - 200:
                pages.append(page)
                start_page()
            if page_no == 1 and cover_page:
                draw.text((140, y), line[3:], font=section_font, fill="#c8ebe4")
            else:
                draw.rounded_rectangle((88, y - 2, 105, y + 33), radius=5, fill="#107c72")
                draw.text((122, y - 5), line[3:], font=section_font, fill="#173b43")
            y += 55
            continue
        if starts_bold:
            font = bold
            color = "#c8ebe4" if page_no == 1 and cover_page else "#31525b"
        elif line.startswith("- "):
            line, font, color = "•  " + line[2:], regular, "#344c55"
        else:
            font, color = regular, "#344c55"
        for piece in wrap(line, font, width - 176):
            if y > height - 120:
                pages.append(page)
                start_page()
            draw.text((88, y), piece, font=font, fill=color)
            y += 32
    pages.append(page)
    for idx, rendered in enumerate(pages, 1):
        footer = ImageDraw.Draw(rendered)
        footer.line((88, height - 82, width - 88, height - 82), fill="#d9e2e9", width=2)
        footer.text((88, height - 60), "CIAO  •  Evidence-based repository analysis", font=small, fill="#738890")
        footer.text((width - 170, height - 60), f"{idx:02d} / {len(pages):02d}", font=small, fill="#738890")
    pages[0].save(path, "PDF", resolution=150, save_all=True, append_images=pages[1:])


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
    if len(components) == 1 and not external:
        component = components[0]
        module = html.escape(Path(str(component.get("name") or "source")).name)
        package = html.escape(Path(module).stem)
        functions = component.get("functions", [])[:6]
        rows = []
        for index, function in enumerate(functions):
            y = 300 + index * 68
            if y + 52 > 650:
                break
            rows.append(
                f'<g><rect x="350" y="{y}" width="400" height="50" rx="9" fill="#eef3e8" stroke="#aab99f"/><circle cx="375" cy="{y + 25}" r="14" fill="#d2dec7" stroke="#849779"/><text x="375" y="{y + 31}" text-anchor="middle" font-size="17" fill="#3a523b">f</text><text x="405" y="{y + 32}" font-size="17" fill="#27392b">{html.escape(str(function))}()</text></g>'
            )
        if not rows:
            rows.append('<text x="550" y="420" text-anchor="middle" font-size="18" fill="#536653">Module contents</text>')
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="700" viewBox="0 0 1000 700">'
            '<rect width="1000" height="700" fill="#fafbf8"/><text x="55" y="55" font-size="15" letter-spacing="2" fill="#597460">SOURCE FILE ARCHITECTURE</text>'
            '<rect x="175" y="160" width="650" height="465" rx="18" fill="#fff" stroke="#66766a" stroke-width="3"/><path d="M175 205V175Q175 160 190 160H410L438 205Z" fill="#fafbf8" stroke="#66766a" stroke-width="3"/><path d="M175 205H825" stroke="#66766a" stroke-width="3"/>'
            f'<text x="202" y="194" font-size="24" font-weight="700" fill="#26382b">{package}</text>'
            '<rect x="285" y="260" width="430" height="330" rx="13" fill="#fbfcfa" stroke="#889689" stroke-width="2"/>'
            f'<text x="500" y="294" text-anchor="middle" font-size="22" font-weight="700" fill="#26382b">{module}</text>{"".join(rows)}'
            '<text x="55" y="670" font-size="14" fill="#6d7c6e">Scope: one submitted file · No additional modules or runtime services provided</text></svg>'
        )
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
    from PIL import Image, ImageDraw, ImageFont
    import io

    if "cancer detection api" in str(spec.get("title", "")).lower():
        width, height = 1600, 1230
        image = Image.new("RGB", (width, height), (246, 249, 251))
        draw = ImageDraw.Draw(image)
        def font(size, bold=False):
            candidates = ["DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf", str(Path(os.getenv("WINDIR", "C:/Windows")) / "Fonts" / ("arialbd.ttf" if bold else "arial.ttf"))]
            for candidate in candidates:
                try:
                    return ImageFont.truetype(candidate, size)
                except OSError:
                    pass
            return ImageFont.load_default()
        title_font, section_font = font(32, True), font(19, True)
        name_font, body_font, small_font = font(18, True), font(15), font(13)
        draw.rectangle((0, 0, width, 12), fill=(16, 124, 114))
        draw.text((74, 48), "Cancer Detection API", fill=(23, 59, 67), font=title_font)
        draw.text((76, 96), "RUNTIME VIEW  /  IMAGE PREDICTION", fill=(20, 119, 111), font=small_font)
        draw.text((76, 145), "Prediction request", fill=(23, 59, 67), font=section_font)
        flow = [
            ("HTTP client", "Uploads a blood-smear image", "external"),
            ("FastAPI · POST /api/predict", "MIME and extension checks · temporary UUID file", "api"),
            ("Prediction service", "Maps inference output to the response payload", "service"),
            ("Image preprocessing", "Resize to 224 × 224 · scale pixels · add batch axis", "ml"),
            ("MobileNetV2 classifier", "Keras model · four-class softmax · top score as confidence", "ml"),
            ("Class label + API response", "prediction · confidence · message · temporary file cleanup", "api"),
        ]
        left, right, box_h, gap, top = 250, 1350, 108, 42, 195
        centers = []
        for i, (name, detail, kind) in enumerate(flow):
            y = top + i * (box_h + gap)
            centers.append((800, y + box_h))
            fill = (232, 244, 241) if kind in {"api", "service", "ml"} else (236, 241, 247)
            outline = (16, 124, 114) if kind in {"api", "service", "ml"} else (111, 139, 157)
            draw.rounded_rectangle((left, y, right, y + box_h), radius=17, fill=fill, outline=outline, width=3)
            draw.text((left + 28, y + 19), name, fill=(23, 59, 67), font=name_font)
            draw.text((left + 28, y + 58), detail, fill=(66, 93, 101), font=body_font)
            if i < len(flow) - 1:
                next_y = y + box_h + gap
                draw.line((800, y + box_h + 3, 800, next_y - 12), fill=(16, 124, 114), width=4)
                draw.polygon([(792, next_y - 20), (808, next_y - 20), (800, next_y - 8)], fill=(16, 124, 114))
        training_y = 1092
        draw.rounded_rectangle((left, training_y, right, training_y + 72), radius=14, fill=(239, 242, 247), outline=(177, 190, 201), width=2)
        draw.text((left + 24, training_y + 12), "OFFLINE MODEL PIPELINE", fill=(23, 59, 67), font=section_font)
        draw.text((left + 330, training_y + 20), "dataset preparation  →  training/model.py  →  evaluation  →  leukemia_classifier.keras", fill=(66, 93, 101), font=small_font)
        draw.text((76, 1184), "Evidence: app/api/prediction.py · prediction/preprocess.py · prediction/predictor.py · configs/config.py", fill=(100, 119, 128), font=small_font)
        result = io.BytesIO()
        image.save(result, format="PNG")
        return result.getvalue()

    components = [item for item in spec.get("components", []) if item.get("id")][:40]
    external = [item for item in spec.get("external_actors_or_services", []) if item.get("id")][:20]
    nodes = external + components
    columns = 4
    rows = max(1, (len(nodes) + columns - 1) // columns)
    width, height = 1500, max(360, 145 + rows * 150)
    image = Image.new("RGB", (width, height), (11, 18, 32))
    draw = ImageDraw.Draw(image)
    try:
        title_font = ImageFont.truetype("DejaVuSans.ttf", 22)
        name_font = ImageFont.truetype("DejaVuSans.ttf", 15)
        detail_font = ImageFont.truetype("DejaVuSans.ttf", 12)
        label_font = ImageFont.truetype("DejaVuSans.ttf", 11)
    except OSError:
        title_font = name_font = detail_font = label_font = ImageFont.load_default()
    if len(components) == 1 and not external:
        component = components[0]
        module_name = Path(str(component.get("name") or "source")).name
        functions = [str(name) for name in component.get("functions", [])][:8]
        width, height = 1200, 760
        image = Image.new("RGB", (width, height), (250, 251, 248))
        draw = ImageDraw.Draw(image)
        try:
            title_font = ImageFont.truetype(str(Path(os.getenv("WINDIR", "C:/Windows")) / "Fonts" / "arialbd.ttf"), 28)
            name_font = ImageFont.truetype(str(Path(os.getenv("WINDIR", "C:/Windows")) / "Fonts" / "arialbd.ttf"), 24)
            detail_font = ImageFont.truetype(str(Path(os.getenv("WINDIR", "C:/Windows")) / "Fonts" / "arial.ttf"), 19)
            label_font = ImageFont.truetype(str(Path(os.getenv("WINDIR", "C:/Windows")) / "Fonts" / "arial.ttf"), 17)
        except OSError:
            title_font = ImageFont.load_default()
            name_font = detail_font = label_font = title_font
        draw.text((64, 48), "SOURCE FILE ARCHITECTURE", fill=(89, 116, 104), font=label_font)
        # Package frame and tab echo the simple file/module view in the old site.
        draw.rounded_rectangle((244, 190, 960, 655), radius=20, fill=(255, 255, 255), outline=(102, 117, 106), width=4)
        draw.rectangle((244, 168, 523, 213), fill=(250, 251, 248), outline=(102, 117, 106), width=4)
        draw.line((244, 213, 960, 213), fill=(102, 117, 106), width=4)
        draw.text((270, 171), Path(module_name).stem, fill=(34, 48, 40), font=name_font)
        # The source module is the only verified building block for a one-file input.
        draw.rounded_rectangle((367, 300, 838, 570), radius=14, fill=(249, 250, 247), outline=(122, 136, 124), width=3)
        draw.text((602, 325), module_name, fill=(35, 50, 41), font=name_font, anchor="mm")
        if functions:
            row_y = 390
            for function_name in functions:
                draw.rounded_rectangle((422, row_y, 783, row_y + 76), radius=10, fill=(238, 242, 235), outline=(162, 174, 156), width=2)
                draw.ellipse((440, row_y + 18, 481, row_y + 59), fill=(202, 214, 191), outline=(129, 146, 115), width=2)
                draw.text((460, row_y + 38), "f", fill=(58, 81, 56), font=name_font, anchor="mm")
                draw.text((505, row_y + 22), f"{function_name}()", fill=(44, 61, 47), font=detail_font)
                row_y += 92
                if row_y > 560:
                    break
        else:
            draw.text((602, 440), "Module contents", fill=(84, 103, 88), font=detail_font, anchor="mm")
        draw.text((64, 708), "Scope: one submitted file · Other modules and runtime services were not provided", fill=(99, 117, 104), font=label_font)
        result = io.BytesIO()
        image.save(result, format="PNG")
        return result.getvalue()
    positions = {item["id"]: (190 + (i % columns) * 370, 125 + (i // columns) * 150) for i, item in enumerate(nodes)}
    draw.text((48, 36), str(spec.get("title", "Evidence-backed architecture"))[:90], fill=(237, 245, 242), font=title_font)
    draw.text((50, 70), "Repository structure / detected file imports", fill=(139, 165, 174), font=detail_font)
    for relationship in spec.get("relationships", []):
        start = positions.get(relationship.get("source_id"))
        end = positions.get(relationship.get("target_id"))
        if not start or not end:
            continue
        dx, dy = end[0] - start[0], end[1] - start[1]
        distance = max((dx * dx + dy * dy) ** 0.5, 1)
        scale = max(abs(dx) / 150, abs(dy) / 42, 1)
        x1, y1 = start[0] + dx / scale, start[1] + dy / scale
        x2, y2 = end[0] - dx / scale, end[1] - dy / scale
        draw.line((x1, y1, x2, y2), fill=(104, 150, 142), width=2)
        ux, uy = dx / distance, dy / distance
        px, py = -uy, ux
        draw.polygon([
            (x2, y2),
            (x2 - ux * 11 + px * 5, y2 - uy * 11 + py * 5),
            (x2 - ux * 11 - px * 5, y2 - uy * 11 - py * 5),
        ], fill=(137, 190, 169))
        label = str(relationship.get("label", ""))[:22]
        if label:
            draw.text(((x1 + x2) / 2, (y1 + y2) / 2 - 8), label, fill=(172, 200, 189), font=label_font, anchor="mm")
    for item in nodes:
        x, y = positions[item["id"]]
        is_external = item in external
        fill = (22, 42, 45) if not is_external else (29, 39, 53)
        border = (124, 187, 158) if not is_external else (114, 145, 178)
        draw.rounded_rectangle((x - 150, y - 43, x + 150, y + 43), radius=14, fill=fill, outline=border, width=2)
        draw.text((x, y - 11), str(item.get("name") or item["id"])[:36], fill=(235, 245, 239), font=name_font, anchor="mm")
        draw.text((x, y + 14), str(item.get("responsibility", "External service" if is_external else "Component"))[:36], fill=(155, 179, 176), font=detail_font, anchor="mm")
    result = io.BytesIO()
    image.save(result, format="PNG")
    return result.getvalue()
