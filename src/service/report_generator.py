from __future__ import annotations

import html
import json
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
    return _evidence_based_report(repository_path, commit_sha, graph, readme, metadata, context, ollama_description)


def _evidence_based_report(
    repository_path: Path, commit_sha: str, graph: Dict[str, Any], readme: str,
    metadata: Dict[str, Any], context: Dict[str, Any], ollama_description: str,
) -> str:
    """Render the same architecture-documentation contract for every input type."""
    root = repository_path if repository_path.is_dir() else repository_path.parent
    project = str(context.get("project_name") or metadata.get("source_name") or root.name)
    manifest = context.get("file_manifest") or metadata.get("file_manifest") or []
    files = [str(p).replace("\\", "/") for p in manifest]
    if not files:
        files = [str(n.get("path") or n.get("id")) for n in graph.get("nodes", []) if isinstance(n, dict) and n.get("type") == "file"]
    files = list(dict.fromkeys(files))
    if not files and repository_path.is_file():
        files = [repository_path.name]
    corpus_parts = []
    for relative in files[:120]:
        try:
            p = Path(relative)
            if not p.is_absolute():
                p = root / p
            if p.is_file() and p.stat().st_size <= 250_000:
                corpus_parts.append(p.read_text(encoding="utf-8", errors="replace")[:40_000])
        except OSError:
            continue
    corpus = "\n".join(corpus_parts)
    spec: Dict[str, Any] = {}
    if isinstance(ollama_description, str):
        decoder = json.JSONDecoder()
        for start in (i for i, char in enumerate(ollama_description) if char == "{"):
            try:
                candidate, _ = decoder.raw_decode(ollama_description[start:])
                if isinstance(candidate, dict) and "relationships" in candidate:
                    spec = candidate
                    break
            except json.JSONDecodeError:
                continue
    readme = readme or ""
    heading = next((line.lstrip("# ").strip() for line in readme.splitlines() if line.startswith("#")), project)
    description_lines = [line.strip() for line in readme.splitlines() if line.strip() and not line.startswith("#")]
    purpose = " ".join(description_lines[:3])[:900] if description_lines else "Purpose is not established by the provided repository evidence."
    evidence_paths = [p for p in files if p and p != "None"]
    source = context.get("submitted_source") or metadata.get("source_repository") or metadata.get("source_name") or project
    component_paths = [p for p in evidence_paths if Path(p).suffix.lower() in {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs", ".cs", ".cpp", ".c", ".rb", ".php", ".swift", ".kt"}]
    # Collapse a large repository into a readable list of logical source areas.
    groups: Dict[str, List[str]] = {}
    for path in component_paths:
        parts = Path(path).parts
        group = parts[0] if len(parts) > 1 else Path(path).name
        groups.setdefault(group, []).append(path)
    component_lines = []
    analyzed_components = [x for x in spec.get("components", []) if isinstance(x, dict) and x.get("id")][:12]
    for component in analyzed_components:
        evidence = component.get("evidence", [])
        cited = ", ".join(f"`{p}`" for p in evidence[:3]) if isinstance(evidence, list) else str(evidence)
        component_lines.append(f"- **{component.get('name', component['id'])}:** {component.get('responsibility', 'Responsibility not established')}. Evidence: {cited or 'not cited'}.")
    if not analyzed_components:
        for group, members in list(groups.items())[:12]:
            examples = ", ".join(f"`{p}`" for p in members[:3])
            component_lines.append(f"- **{group}:** source files {examples}{f' and {len(members)-3} more' if len(members)>3 else ''}. Responsibility and runtime role are not inferred from folder names alone.")
    if not component_lines:
        component_lines = ["- **Submitted source:** the provided files are the complete inspected scope; no separate runtime components are established."]
    route_hits = sorted(set(re.findall(r"(?im)(?:@(?:app|router)\.(?:get|post|put|patch|delete)\s*\(\s*|(?:app|router)\.(?:get|post|put|patch|delete)\s*\(\s*)['\"]([^'\"]+)", corpus)))[:30]
    endpoints = "\n".join(f"- `{route}` — route declaration found in submitted source; handler semantics depend on its implementation." for route in route_hits) or "No HTTP endpoint declaration was detected. Other interfaces may still be present."
    dep_files = [p for p in evidence_paths if Path(p).name.lower() in {"requirements.txt", "pyproject.toml", "package.json", "pom.xml", "build.gradle", "cargo.toml", "go.mod", "gemfile", "composer.json"}]
    tech_patterns = [(r"\bfastapi\b", "FastAPI"), (r"\bflask\b", "Flask"), (r"\bdjango\b", "Django"), (r"\bexpress\b", "Express"), (r"\breact\b", "React"), (r"\bvue\b", "Vue"), (r"\bnext(?:\.js)?\b", "Next.js"), (r"\bsqlalchemy\b", "SQLAlchemy"), (r"\bpostgres(?:ql)?\b", "PostgreSQL"), (r"\bredis\b", "Redis"), (r"\bmongodb\b", "MongoDB"), (r"\bpytest\b", "pytest"), (r"\btensorflow\b", "TensorFlow"), (r"\bpytorch|torch\b", "PyTorch")]
    technologies = [label for pattern, label in tech_patterns if re.search(pattern, corpus, re.I)]
    tech_text = ", ".join(technologies) if technologies else "No framework or database could be confirmed from inspected source."
    deploy_files = [p for p in evidence_paths if any(t in p.lower() for t in ("dockerfile", "docker-compose", ".github/workflows/", "kubernetes", "helm", "terraform", "serverless", "procfile"))]
    stores = [p for p in evidence_paths if any(t in p.lower() for t in ("migration", "schema", "model", "entity"))]
    auth_evidence = [p for p in evidence_paths if re.search(r"auth|security|permission|credential", p, re.I)]
    test_files = [p for p in evidence_paths if re.search(r"(^|/)(tests?|spec)(/|$)|(^|/)test_", p, re.I)]
    flow = spec.get("principal_flow", []) if isinstance(spec.get("principal_flow", []), list) else []
    flow = [str(s).strip() for s in flow if str(s).strip()][:10]
    relationships = spec.get("relationships", []) if isinstance(spec.get("relationships", []), list) else []
    displayed_ids = {str(x.get("id")) for x in (spec.get("external_actors_or_services", [])[:3] + spec.get("components", [])[:12]) if isinstance(x, dict) and x.get("id")}
    relationships = [r for r in relationships if isinstance(r, dict) and str(r.get("source_id")) in displayed_ids and str(r.get("target_id")) in displayed_ids and r.get("label")][:14]
    name_by_id = {str(x.get("id")): str(x.get("name") or x.get("id")) for x in (spec.get("external_actors_or_services", []) + spec.get("components", [])) if isinstance(x, dict) and x.get("id")}
    if relationships:
        flow_text = "\n".join(f"{i}. **{name_by_id.get(str(r['source_id']), r['source_id'])} → {name_by_id.get(str(r['target_id']), r['target_id'])}:** {r['label']}" for i, r in enumerate(relationships, 1))
        flow_caveat = ("The numbered items correspond exactly to numbered diagram arrows. " + ("They are repository-analyzed relationships, not guaranteed runtime order." if not flow else "The analyzer also identified this main-flow sequence: " + " → ".join(flow[:8])))
    elif flow:
        flow_text = "\n".join(f"{i}. {step}" for i, step in enumerate(flow, 1))
        flow_caveat = "The steps are generated from repository analysis; the diagram does not invent arrows where relationship evidence is missing."
    else:
        flow_text = "The main request, event, or command flow could not be established from the supplied evidence. The diagram therefore shows detected source areas and documented dependencies only; these do not imply runtime order."
        flow_caveat = "No runtime sequence is asserted because one was not established from the input."
    store_text = ", ".join(f"`{p}`" for p in stores[:10]) if stores else "No persistence schema, database, cache, or queue was positively identified."
    deploy_text = ", ".join(f"`{p}`" for p in deploy_files[:12]) if deploy_files else "No deployment manifests or CI/CD workflow files were detected in the analyzed manifest. Hosting, environments, networking, and release process are not established."
    open_questions = [
        "What are the intended production environments, hosting platform, network boundaries, and deployment process?",
        "Which users or services call the system, and what authentication and authorization requirements apply?",
        "What persistent data, retention rules, backups, and privacy requirements apply?",
        "What traffic, latency, availability, and recovery targets should the design meet?",
        "Which monitoring, alerting, compliance, and operational ownership requirements are expected?",
    ]
    component_table_rows = []
    if analyzed_components:
        for component in analyzed_components:
            component_id = str(component["id"])
            related_ids = []
            for relation in relationships:
                if str(relation.get("source_id")) == component_id:
                    related_ids.append(str(relation.get("target_id")))
                elif str(relation.get("target_id")) == component_id:
                    related_ids.append(str(relation.get("source_id")))
            dependencies = ", ".join(name_by_id.get(item, item) for item in dict.fromkeys(related_ids)) or "Not established"
            ev = component.get("evidence", [])
            ev_text = ", ".join(f"`{item}`" for item in ev[:3]) if isinstance(ev, list) else str(ev or "Not cited")
            def field_text(value: Any) -> str:
                if isinstance(value, list):
                    return ", ".join(str(part) for part in value) or "Not established"
                return str(value) if value else "Not established"
            technology = field_text(component.get("technology"))
            inputs = field_text(component.get("inputs"))
            outputs = field_text(component.get("outputs"))
            cells = [str(component.get("name") or component_id), str(component.get("responsibility") or "Not established"), technology, f"Input: {inputs}; output: {outputs}", dependencies + f" (evidence: {ev_text})"]
            component_table_rows.append("| " + " | ".join(value.replace("|", "\\|").replace("\n", " ") for value in cells) + " |")
    else:
        for line in component_lines:
            label = line[2:].replace("**", "").replace("|", "\\|")
            component_table_rows.append(f"| {label} | Not established from directory names alone | {tech_text} | Not established | See source imports and dependency manifests |")
    return f"""# {heading or project}

**Source:** {source}<br>
**Branch:** {metadata.get('branch', context.get('branch', 'Unavailable'))}<br>
**Commit:** {commit_sha or 'Unavailable'}<br>
**Generated:** {metadata.get('generated_at', 'Unavailable')}<br>
**Files analyzed:** {len(evidence_paths) or 'Unavailable'}

## 1. Overview

{purpose}

**Scope:** {('the submitted source file and its visible declarations' if len(evidence_paths) == 1 else 'the files present in the analyzed repository or archive manifest')}. **Goals:** document evidenced purpose, structure, interfaces, and operational unknowns. **Non-goals:** infer unstated production behavior or claim runtime properties that source inspection cannot establish.

## 2. Architecture summary

**Observed style:** {('single source module' if len(evidence_paths) == 1 else 'repository structure is organized into source areas; a monolith, service, or serverless deployment style is not established unless documented in the source')}. Technology evidence: {tech_text}. The deployment rationale is not recorded in the inspected files.

## 3. Components

| Component / evidence area | Responsibility | Technology | Inputs / outputs | Dependencies |
|---|---|---|---|---|
{chr(10).join(component_table_rows)}

The component-level responsibilities come from source analysis where available; input/output contracts and component-specific technology are marked unknown when they cannot be established from the inspected evidence.

Dependency manifests found: {', '.join(f'`{p}`' for p in dep_files) if dep_files else 'none detected in the analyzed manifest'}.

## 4. Data flow

{flow_text}

{flow_caveat}

## 5. Data model

Persistence/model evidence files: {store_text} No entity relationships, storage engine, or schema are asserted unless shown by those files. Data retention and lifecycle are not established by repository structure alone.

## 6. APIs and integrations

{endpoints}

Protocols, authentication, authorization, and external service behavior must be confirmed from handler and integration code. No API route was detected where route evidence is absent.

## 7. Infrastructure and deployment

Detected deployment/automation evidence: {deploy_text}

Environments, CI/CD behavior, hosting, load balancers, private networks, and VPC boundaries are only described when the listed source files establish them; otherwise they are not specified.

## 8. Security

Security-related paths detected: {', '.join(f'`{p}`' for p in auth_evidence[:12]) if auth_evidence else 'No security-specific path names were detected'}. This filename scan does not prove the presence or absence of controls. Authentication, authorization, secret storage, encryption, and threat controls are **not established** unless supported by implementation evidence.

## 9. Scalability and reliability

No traffic, latency, availability, failover, backup, cache, or queue characteristics are inferred from static source structure. Scaling limits and recovery behavior require deployment and runtime evidence.

## 10. Monitoring and observability

Tests or quality files detected: {', '.join(f'`{p}`' for p in test_files[:12]) if test_files else 'none detected in the analyzed manifest'}. Logging, metrics, tracing, alert thresholds, health checks, and retention are not specified unless evidenced in the source.

## 11. Key decisions and trade-offs (ADR style)

- **Observed structure:** {('one submitted source file' if len(evidence_paths) == 1 else 'the source areas listed in Section 3')} is present in the analyzed input. The reason for this structure is not recorded.
- **Technology choices:** {tech_text}. Their selection rationale and measured trade-offs are not established by dependency declarations alone.
- **Assumption:** source imports and declared routes represent intended code relationships; actual runtime behavior may differ and must be verified.

## 12. Risks, limitations, and future improvements

- The purpose statement is taken from README prose where available; otherwise it remains unknown.
- Static inspection cannot establish runtime behavior, deployment topology, system capacity, or security posture.
- Add or maintain deployment, data lifecycle, security, monitoring, and performance evidence if those operational properties are required.
- Review generated component groupings against actual entry points before treating them as a production architecture.

## 13. Glossary

- **Evidence:** repository content directly observed during this analysis.
- **Assumption:** an interpretation that is useful for describing structure but is not confirmed as runtime behavior.
- **Not established:** the supplied files do not provide enough evidence to make the claim.

## Open questions

{chr(10).join(f'{i}. {question}' for i, question in enumerate(open_questions, 1))}
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


def _architecture_svg(spec: Dict[str, Any]) -> str:
    """Render a compact evidence-based layered view with explicit unknown boundaries."""
    esc = lambda value: html.escape(str(value))
    components = [x for x in spec.get("components", []) if isinstance(x, dict) and x.get("id")][:12]
    external = [x for x in spec.get("external_actors_or_services", []) if isinstance(x, dict) and x.get("id")][:3]
    groups: Dict[str, List[Dict[str, Any]]] = {"API / Gateway": [], "Services": [], "Data": [], "Infrastructure": []}
    for item in components:
        probe = f"{item.get('name', '')} {item.get('responsibility', '')}".lower()
        if any(w in probe for w in ("database", "storage", "cache", "queue", "model artifact", "file store")):
            layer = "Data"
        elif any(w in probe for w in ("api", "route", "controller", "gateway", "endpoint", "server")):
            layer = "API / Gateway"
        elif any(w in probe for w in ("deploy", "worker", "runtime", "infrastructure", "configuration", "config")):
            layer = "Infrastructure"
        else:
            layer = "Services"
        groups[layer].append(item)
    colors = {"API / Gateway": ("#eaf1ed", "#66836f"), "Services": ("#f0f3eb", "#849276"), "Data": ("#f5f0e6", "#a18a63"), "Infrastructure": ("#edf0f4", "#75899e")}
    rows = [(layer, items) for layer, items in groups.items() if items]
    positions: Dict[str, tuple[int, int]] = {}
    row_y = 315
    for layer, items in rows:
        for i, item in enumerate(items):
            positions[str(item["id"])] = (185 + (i % 4) * 360, row_y + (i // 4) * 100)
        row_y += 90 + ((len(items) + 3) // 4) * 100
    for i, item in enumerate(external):
        positions[str(item["id"])] = (210 + i * 470, 160)
    height = max(1020, row_y + 210)
    nodes = {str(x["id"]): x for x in external + components}
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1500" height="{height}" viewBox="0 0 1500 {height}">',
        '<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto"><path d="M0,0 L0,6 L9,3 z" fill="#66836f"/></marker></defs>',
        '<g font-family="Arial, sans-serif"><rect width="100%" height="100%" fill="#fafbf8"/>',
        f'<text x="55" y="52" font-size="28" font-weight="700" fill="#26382b">{esc(spec.get("title", "System architecture"))}</text>',
        '<text x="55" y="82" font-size="14" fill="#657568">Repository evidence view · layer grouping inferred from component names and paths</text>',
        '<rect x="60" y="220" width="1380" height="' + str(height - 410) + '" rx="18" fill="#fff" stroke="#748575" stroke-width="2" stroke-dasharray="9 6"/>',
        f'<text x="82" y="250" font-size="15" font-weight="700" fill="#526653">SYSTEM BOUNDARY · {esc((spec.get("system_boundary") or {}).get("name", "submitted project"))} · VPC / hosting boundary not established</text>',
    ]
    if external:
        parts.append('<text x="82" y="119" font-size="13" font-weight="700" fill="#526653">ACTORS / EXTERNAL SERVICES</text>')
        for item in external:
            x, y = positions[str(item["id"])]
            parts.append(f'<ellipse cx="{x}" cy="{y}" rx="125" ry="35" fill="#f0f2f5" stroke="#8190a0" stroke-width="2"/><text x="{x}" y="{y+5}" text-anchor="middle" font-size="14" fill="#384755">{esc(item.get("name") or item["id"])[:38]}</text>')
    relationships = [r for r in spec.get("relationships", []) if isinstance(r, dict) and str(r.get("source_id")) in positions and str(r.get("target_id")) in positions][:14]
    for i, relation in enumerate(relationships, 1):
        sx, sy = positions[str(relation["source_id"])]
        tx, ty = positions[str(relation["target_id"])]
        cy = (sy + ty) // 2
        parts.append(f'<path d="M {sx} {sy+42} C {sx} {cy}, {tx} {cy}, {tx} {ty-42}" fill="none" stroke="#66836f" stroke-width="2" marker-end="url(#arrow)"/><text x="{(sx+tx)//2}" y="{cy-6}" text-anchor="middle" font-size="11" fill="#455b4b">{i} · {esc(relation.get("label", "interacts"))[:32]}</text>')
    for layer, items in rows:
        fill, border = colors[layer]
        y0 = min(positions[str(item["id"])][1] for item in items)
        parts.append(f'<text x="82" y="{y0-67}" font-size="13" font-weight="700" fill="#566a58">{esc(layer.upper())}</text>')
        for item in items:
            x, y = positions[str(item["id"])]
            name = esc(item.get("name") or item["id"])
            desc = esc(item.get("responsibility") or "Responsibility not established")
            if layer == "Data":
                parts.append(f'<path d="M{x-138} {y-32} q138 -24 276 0 v58 q-138 24 -276 0 z" fill="{fill}" stroke="{border}" stroke-width="2"/><ellipse cx="{x}" cy="{y-32}" rx="138" ry="14" fill="{fill}" stroke="{border}" stroke-width="2"/>')
            else:
                parts.append(f'<rect x="{x-138}" y="{y-42}" width="276" height="84" rx="12" fill="{fill}" stroke="{border}" stroke-width="2"/>')
            parts.append(f'<text x="{x}" y="{y-7}" text-anchor="middle" font-size="14" font-weight="700" fill="#304536">{name[:38]}</text><text x="{x}" y="{y+17}" text-anchor="middle" font-size="10" fill="#536653">{desc[:44]}</text>')
    legend_y = height - 150
    parts.extend([
        f'<text x="60" y="{legend_y}" font-size="14" font-weight="700" fill="#526653">LEGEND</text>',
        f'<ellipse cx="148" cy="{legend_y+40}" rx="24" ry="15" fill="#f0f2f5" stroke="#8190a0"/><text x="182" y="{legend_y+45}" font-size="12" fill="#536653">actor / external system</text>',
        f'<rect x="350" y="{legend_y+26}" width="48" height="28" rx="6" fill="#eaf1ed" stroke="#66836f"/><text x="408" y="{legend_y+45}" font-size="12" fill="#536653">application component</text>',
        f'<path d="M620 {legend_y+30} q25 -10 50 0 v22 q-25 10 -50 0 z" fill="#f5f0e6" stroke="#a18a63"/><text x="680" y="{legend_y+45}" font-size="12" fill="#536653">database / file / storage</text>',
        f'<line x1="925" y1="{legend_y+40}" x2="985" y2="{legend_y+40}" stroke="#66836f" stroke-width="2" marker-end="url(#arrow)"/><text x="997" y="{legend_y+45}" font-size="12" fill="#536653">directed relationship · numbered in Section 4</text>',
        f'<line x1="60" y1="{legend_y+78}" x2="110" y2="{legend_y+78}" stroke="#748575" stroke-width="2" stroke-dasharray="7 5"/><text x="120" y="{legend_y+83}" font-size="12" fill="#536653">dashed = system scope boundary; colors distinguish API, services, data, and infrastructure layers</text>',
        f'<text x="60" y="{height-32}" font-size="12" fill="#657568">Hosting and public/private network boundaries are not established. Arrows show evidence-backed relationships; labels specify protocol only when source evidence provides one.</text>',
        '</g></svg>',
    ])
    return "".join(parts)

def _architecture_png(spec: Dict[str, Any]) -> bytes:
    """Render the same compact layered architecture view as the SVG option."""
    from PIL import Image, ImageDraw, ImageFont
    import io

    components = [x for x in spec.get("components", []) if isinstance(x, dict) and x.get("id")][:12]
    external = [x for x in spec.get("external_actors_or_services", []) if isinstance(x, dict) and x.get("id")][:3]
    layers: Dict[str, List[Dict[str, Any]]] = {"API / Gateway": [], "Services": [], "Data": [], "Infrastructure": []}
    for item in components:
        probe = f"{item.get('name', '')} {item.get('responsibility', '')}".lower()
        layer = ("Data" if any(w in probe for w in ("database", "storage", "cache", "queue", "model artifact", "file store")) else
                 "API / Gateway" if any(w in probe for w in ("api", "route", "controller", "gateway", "endpoint", "server")) else
                 "Infrastructure" if any(w in probe for w in ("deploy", "worker", "runtime", "infrastructure", "configuration", "config")) else "Services")
        layers[layer].append(item)
    layer_colors = {"API / Gateway": ((234,241,237),(102,131,111)), "Services": ((240,243,235),(132,146,118)), "Data": ((245,240,230),(161,138,99)), "Infrastructure": ((237,240,244),(117,137,158))}
    rows = [(layer, items) for layer, items in layers.items() if items]
    row_y = 315
    positions = {}
    for layer, items in rows:
        for i, item in enumerate(items):
            positions[str(item["id"])] = (185 + (i % 4) * 360, row_y + (i // 4) * 100)
        row_y += 90 + ((len(items) + 3) // 4) * 100
    for i, item in enumerate(external):
        positions[str(item["id"])] = (210 + i * 470, 160)
    height = max(1020, row_y + 210)
    image = Image.new("RGB", (1500, height), (250,251,248))
    d = ImageDraw.Draw(image)
    fonts = Path(os.getenv("WINDIR", "C:/Windows")) / "Fonts"
    def font(size, bold=False):
        for f in (fonts / ("arialbd.ttf" if bold else "arial.ttf"), "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"):
            try: return ImageFont.truetype(str(f), size)
            except OSError: pass
        return ImageFont.load_default()
    title, header, body, small = font(28,True), font(15,True), font(14,True), font(11)
    ink, muted = (38,56,43), (83,102,83)
    d.text((55,35), str(spec.get("title", "System architecture"))[:78], fill=ink, font=title)
    d.text((55,75), "Repository evidence view · layer grouping inferred from component names and paths", fill=muted, font=small)
    d.rounded_rectangle((60,220,1440,height-190),18,fill="white",outline=None)
    # Dashed strokes distinguish the analysis scope from an asserted network perimeter.
    for x in range(80,1440,18):
        d.line((x,220,min(x+9,1440),220),fill=(116,133,117),width=2)
        d.line((x,height-190,min(x+9,1440),height-190),fill=(116,133,117),width=2)
    for y in range(240,height-190,18):
        d.line((60,y,60,min(y+9,height-190)),fill=(116,133,117),width=2)
        d.line((1440,y,1440,min(y+9,height-190)),fill=(116,133,117),width=2)
    boundary=(spec.get("system_boundary") or {})
    d.text((82,232),f"SYSTEM BOUNDARY · {boundary.get('name','submitted project')} · VPC / hosting boundary not established",fill=(82,102,83),font=header)
    for item in external:
        x,y=positions[str(item["id"])]; d.ellipse((x-125,y-35,x+125,y+35),fill=(240,242,245),outline=(129,144,160),width=2)
        d.text((x,y),str(item.get("name") or item["id"])[:35],fill=(56,71,85),font=body,anchor="mm")
    rels=[r for r in spec.get("relationships",[]) if isinstance(r,dict) and str(r.get("source_id")) in positions and str(r.get("target_id")) in positions][:14]
    for n,r in enumerate(rels,1):
        sx,sy=positions[str(r["source_id"])]; tx,ty=positions[str(r["target_id"])]
        x1,y1=sx,sy+42; x2,y2=tx,ty-42
        d.line((x1,y1,x2,y2),fill=(102,131,111),width=3)
        import math
        angle=math.atan2(y2-y1,x2-x1); tip=(x2,y2); base=(x2-12*math.cos(angle),y2-12*math.sin(angle))
        d.polygon([tip,(base[0]+5*math.sin(angle),base[1]-5*math.cos(angle)),(base[0]-5*math.sin(angle),base[1]+5*math.cos(angle))],fill=(102,131,111))
        d.text(((sx+tx)//2,(sy+ty)//2-8),f"{n} · {str(r.get('label','interacts'))[:28]}",fill=muted,font=small,anchor="mm")
    for layer,items in rows:
        fill,border=layer_colors[layer]; y0=min(positions[str(it["id"])][1] for it in items)
        d.text((82,y0-65),layer.upper(),fill=(86,106,88),font=header)
        for it in items:
            x,y=positions[str(it["id"])]; name=str(it.get("name") or it["id"])[:38]; desc=str(it.get("responsibility") or "Responsibility not established")[:44]
            if layer=="Data":
                d.rounded_rectangle((x-138,y-38,x+138,y+38),12,fill=fill,outline=border,width=2); d.arc((x-138,y-48,x+138,y-25),180,360,fill=border,width=2)
            else: d.rounded_rectangle((x-138,y-42,x+138,y+42),12,fill=fill,outline=border,width=2)
            d.text((x,y-7),name,fill=ink,font=body,anchor="mm"); d.text((x,y+17),desc,fill=muted,font=small,anchor="mm")
    ly=height-150
    d.text((60,ly),"LEGEND",fill=(82,102,83),font=header)
    d.ellipse((130,ly+25,176,ly+55),fill=(240,242,245),outline=(129,144,160)); d.text((185,ly+40),"actor / external system",fill=muted,font=small,anchor="lm")
    d.rounded_rectangle((345,ly+27,393,ly+53),6,fill=layer_colors["API / Gateway"][0],outline=layer_colors["API / Gateway"][1]); d.text((402,ly+40),"component",fill=muted,font=small,anchor="lm")
    d.rounded_rectangle((510,ly+27,558,ly+53),8,fill=layer_colors["Data"][0],outline=layer_colors["Data"][1]); d.text((567,ly+40),"database / file / storage",fill=muted,font=small,anchor="lm")
    d.line((790,ly+40,840,ly+40),fill=(102,131,111),width=2); d.polygon([(840,ly+40),(830,ly+35),(830,ly+45)],fill=(102,131,111)); d.text((850,ly+40),"directed; arrows numbered in Section 4",fill=muted,font=small,anchor="lm")
    d.line((60,ly+77,110,ly+77),fill=(116,133,117),width=2); d.text((120,ly+77),"dashed = system boundary · colors distinguish API, services, data, and infrastructure",fill=muted,font=small,anchor="lm")
    d.text((60,height-35),"Hosting and public/private network boundaries are not established. Arrow labels specify protocol only when source evidence provides it.",fill=muted,font=small)
    out=io.BytesIO(); image.save(out,format="PNG"); return out.getvalue()
