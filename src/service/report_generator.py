from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List

from src.service.repository_files import iter_repository_files


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
    file_count = sum(1 for node in nodes if node.get("type") == "file")
    manifest = context.get("file_manifest") or []
    if not manifest:
        manifest = sorted(
            Path(str(node.get("path", ""))).as_posix()
            for node in nodes if node.get("type") == "file" and node.get("path")
        )
    def value(key: str, fallback: str = "Unavailable") -> str:
        return metadata.get(key) or fallback
    project = context.get("project_name") or value("source_name")
    report_body = (ollama_description or "").strip()
    report_body = re.sub(r"^#\s+Project Documentation\s*", "", report_body, count=1)
    if report_body and not report_body.startswith("## "):
        report_body = re.sub(r"^#\s+.*\n", "", report_body, count=1)
    submitted = context.get("submitted_source") or value("source_repository", project)
    lines = [
        f"# {project} — Technical Project Documentation",
        "",
        f"**Output file:** {value('output_filename')} ({value('output_format')})  ",
        f"**Generated at:** {value('generated_at')}  ",
        f"**Submitted source:** {submitted}  ",
        f"**Branch:** {value('branch')}  ",
        f"**Source commit ID:** {value('commit_sha', commit_sha)}  ",
        f"**Source commit message:** {value('commit_message')}  ",
        f"**GitHub sync time:** {value('sync_at', 'Not a GitHub sync run')}  ",
        f"**Files analyzed:** {len(manifest) or file_count}",
        "",
        report_body or "## Report generation unavailable\n\nNo report content was produced.",
        "",
        "## Evidence reviewed",
        "The report is based on the submitted revision. The paths below identify repository files available to the analyzer.",
        "",
    ]
    lines.extend(f"- {chr(96)}{path}{chr(96)}" for path in manifest[:60])
    if len(manifest) > 60:
        lines.append(f"- … and {len(manifest) - 60} additional files")
    if context.get("sync_at"):
        lines.extend(["", f"**Synchronized at:** {value('sync_at')}"])
    return "\n".join(lines).strip() + "\n"


def _repository_evidence(repository_path: Path, readme: str) -> Dict[str, str]:
    root = repository_path if repository_path.is_dir() else repository_path.parent
    files = iter_repository_files(root, max_file_bytes=1_000_000)[:250]
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

    paragraphs = []
    for line in text.splitlines():
        if not line.strip():
            continue
        clean = line.strip()
        style = "Normal"
        if clean.startswith("# "):
            style, clean = "Title", clean[2:]
        elif clean.startswith("## "):
            style, clean = "Heading1", clean[3:]
        elif clean.startswith("### "):
            style, clean = "Heading2", clean[4:]
        elif clean.startswith("- "):
            style, clean = "ListParagraph", "• " + clean[2:]
        clean = re.sub(r"\*\*(.*?)\*\*", r"\1", clean).replace(chr(96), "")
        paragraphs.append(
            f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr>'
            f'<w:r><w:t xml:space="preserve">{html.escape(clean)}</w:t></w:r></w:p>'
        )
    document = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{''.join(paragraphs)}<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr></w:body></w:document>"""
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>"""
    document_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>"""
    styles = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:rFonts w:ascii="Aptos" w:hAnsi="Aptos"/><w:sz w:val="21"/><w:color w:val="26352B"/></w:rPr><w:pPr><w:spacing w:after="140" w:line="300"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:rPr><w:rFonts w:ascii="Aptos Display" w:hAnsi="Aptos Display"/><w:b/><w:sz w:val="36"/><w:color w:val="263B2B"/></w:rPr><w:pPr><w:spacing w:before="120" w:after="280"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:sz w:val="27"/><w:color w:val="385C37"/></w:rPr><w:pPr><w:keepNext/><w:spacing w:before="300" w:after="130"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:sz w:val="23"/><w:color w:val="526B4A"/></w:rPr><w:pPr><w:keepNext/><w:spacing w:before="220" w:after="100"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="ListParagraph"><w:name w:val="List Paragraph"/><w:basedOn w:val="Normal"/><w:pPr><w:ind w:left="360"/></w:pPr></w:style>
</w:styles>"""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document)
        archive.writestr("word/_rels/document.xml.rels", document_rels)
        archive.writestr("word/styles.xml", styles)


def _write_pdf(text: str, path: Path) -> None:
    import textwrap

    page_lines: List[List[tuple[str, int, int]]] = [[]]
    y = 742
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            y -= 7
            continue
        if line.startswith("#"):
            line = line.lstrip("#").strip()
            font_size, leading = (17, 24) if raw.startswith("# ") else (12, 17)
        else:
            font_size, leading = 9, 13
            if line.startswith("- "):
                line = "• " + line[2:]
            line = re.sub(r"\*\*(.*?)\*\*", r"\1", line).replace(chr(96), "")
        width = max(42, int(510 / (font_size * 0.52)))
        wrapped = textwrap.wrap(line, width=width, break_long_words=True, break_on_hyphens=True) or [""]
        if y - leading * len(wrapped) < 54:
            page_lines.append([])
            y = 742
        for part in wrapped:
            page_lines[-1].append((part, font_size, y))
            y -= leading

    objects: List[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>", b""]
    page_refs = []
    font_id = 3 + len(page_lines) * 2
    for index, lines in enumerate(page_lines):
        page_id, stream_id = 3 + index * 2, 4 + index * 2
        page_refs.append(f"{page_id} 0 R")
        commands = ["BT"]
        for line, size, baseline in lines:
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            commands.extend([f"/F1 {size} Tf", f"50 {baseline} Td", f"({escaped}) Tj", f"-50 {-baseline} Td"])
        commands.extend(["ET", "BT", "/F1 8 Tf", "50 28 Td", f"(CIAO Project Documentation - {index+1}/{len(page_lines)}) Tj", "ET"])
        stream = "\n".join(commands).encode("cp1252", "replace")
        page = f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {stream_id} 0 R >>".encode()
        stream_obj = b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        objects.extend([page, stream_obj])
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(page_refs)}] /Count {len(page_lines)} >>".encode()
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
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
    components = [item for item in spec.get("components", []) if item.get("id")][:10]
    external = [dict(item, layer=0) for item in spec.get("external_actors_or_services", []) if item.get("id")][:2]
    nodes = external + components
    positions, width, height, _ = _diagram_layout(nodes)
    boxes, edges, labels = [], [], []
    ids = {item["id"] for item in nodes}
    for relation in spec.get("relationships", [])[:14]:
        source, target = relation.get("source_id"), relation.get("target_id")
        if source not in positions or target not in positions:
            continue
        sx, sy = positions[source]
        tx, ty = positions[target]
        direction = 1 if sx < tx else -1
        x1, x2 = sx + direction * 120, tx - direction * 120
        curve = (x1 + x2) / 2
        edges.append(f'<path d="M{x1},{sy} C{curve},{sy} {curve},{ty} {x2},{ty}" fill="none" stroke="#78956c" stroke-width="2" marker-end="url(#arrow)"/>')
        label_x, label_y = (x1 + x2) / 2, (sy + ty) / 2 - 7
        labels.append(f'<text x="{label_x}" y="{label_y}" text-anchor="middle" fill="#596c55" font-size="10">{html.escape(str(relation.get("label", "depends on")))}</text>')
    for item in nodes:
        x, y = positions[item["id"]]
        name = _svg_lines(str(item.get("name") or item["id"]), 28, 2)
        desc = _svg_lines(str(item.get("responsibility", "")), 38, 2)
        name_markup = "".join(f'<tspan x="{x}" dy="{0 if index == 0 else 16}">{html.escape(line)}</tspan>' for index, line in enumerate(name))
        desc_markup = "".join(f'<tspan x="{x}" dy="{0 if index == 0 else 13}">{html.escape(line)}</tspan>' for index, line in enumerate(desc))
        is_external = item in external
        fill, stripe = ("#eff3e9", "#849a70") if is_external else ("#ffffff", "#95b86d")
        boxes.append(f'<g><rect x="{x-120}" y="{y-52}" width="240" height="104" rx="9" fill="{fill}" stroke="#cfd9c9" stroke-width="1.5"/><rect x="{x-120}" y="{y-52}" width="5" height="104" rx="2" fill="{stripe}"/><text x="{x}" y="{y-12}" text-anchor="middle" fill="#26352b" font-size="13" font-weight="700">{name_markup}</text><text x="{x}" y="{y+20}" text-anchor="middle" fill="#6e7c6c" font-size="10">{desc_markup}</text></g>')
    title = html.escape(str(spec.get("title", "Project architecture")))
    note = "Boxes group project-owned source files. Arrows show detected calls or imports, not guaranteed runtime data flow."
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{title}"><defs><marker id="arrow" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto"><path d="M0,0 L0,6 L8,3 z" fill="#78956c"/></marker></defs><rect width="100%" height="100%" fill="#f5f6ef"/><text x="42" y="42" fill="#26352b" font-size="22" font-weight="700">{title}</text><text x="42" y="66" fill="#778178" font-size="11">Logical project components · static code evidence</text><rect x="25" y="88" width="{width-50}" height="{height-145}" rx="12" fill="#fbfcf8" stroke="#dfe4d9"/>{''.join(edges)}{''.join(labels)}{''.join(boxes)}<text x="42" y="{height-28}" fill="#778178" font-size="10">{html.escape(note)}</text></svg>'


def _architecture_png(spec: Dict[str, Any]) -> bytes:
    from PIL import Image, ImageDraw
    import io

    components = [item for item in spec.get("components", []) if item.get("id")][:10]
    external = [dict(item, layer=0) for item in spec.get("external_actors_or_services", []) if item.get("id")][:2]
    nodes = external + components
    positions, width, height, _ = _diagram_layout(nodes)
    image = Image.new("RGB", (width, height), (245, 246, 239))
    draw = ImageDraw.Draw(image)
    draw.text((42, 35), str(spec.get("title", "Project architecture"))[:90], fill=(38, 53, 43))
    draw.text((42, 62), "Logical project components · static code evidence", fill=(119, 129, 120))
    for relationship in spec.get("relationships", [])[:14]:
        start = positions.get(relationship.get("source_id"))
        end = positions.get(relationship.get("target_id"))
        if not start or not end:
            continue
        sx, sy = start
        tx, ty = end
        sign = 1 if sx < tx else -1
        x1, x2 = sx + sign * 120, tx - sign * 120
        draw.line((x1, sy, x2, ty), fill=(120, 149, 108), width=2)
        draw.polygon([(x2, ty), (x2 - sign * 9, ty - 5), (x2 - sign * 9, ty + 5)], fill=(120, 149, 108))
        draw.text(((x1 + x2) // 2, (sy + ty) // 2 - 13), str(relationship.get("label", "depends on"))[:26], fill=(76, 96, 71), anchor="mm")
    for item in nodes:
        x, y = positions[item["id"]]
        is_external = item in external
        fill = (239, 243, 233) if is_external else (255, 255, 255)
        stripe = (132, 154, 112) if is_external else (149, 184, 109)
        draw.rounded_rectangle((x - 120, y - 52, x + 120, y + 52), radius=9, fill=fill, outline=(207, 217, 201), width=2)
        draw.rounded_rectangle((x - 120, y - 52, x - 114, y + 52), radius=2, fill=stripe)
        _draw_wrapped(draw, str(item.get("name") or item["id"]), (x, y - 22), 28, 2, (38, 53, 43), anchor="mm")
        _draw_wrapped(draw, str(item.get("responsibility", "")), (x, y + 20), 34, 2, (110, 124, 108), anchor="mm")
    draw.text((42, height - 30), "Arrows show detected calls or imports, not guaranteed runtime data flow.", fill=(119, 129, 120))
    result = io.BytesIO()
    image.save(result, format="PNG")
    return result.getvalue()


def _diagram_layout(components: List[Dict[str, Any]]) -> tuple[Dict[str, tuple[int, int]], int, int, int]:
    nodes = components or [{
        "id": "no-components", "name": "No project components found",
        "responsibility": "The submitted source did not provide enough code relationships.",
    }]
    layers: Dict[int, List[Dict[str, Any]]] = {}
    for index, item in enumerate(nodes):
        layer = max(0, min(4, int(item.get("layer", 0))))
        layers.setdefault(layer, []).append(item)
    max_layer = max(layers)
    max_rows = max(len(items) for items in layers.values())
    width = max(1040, 340 + max_layer * 310)
    height = max(470, 190 + max_rows * 155)
    positions = {}
    for layer, items in layers.items():
        offset = (max_rows - len(items)) * 75
        for row, item in enumerate(items):
            positions[item["id"]] = (165 + layer * 310, 160 + offset + row * 155)
    return positions, width, height, max_rows


def _svg_lines(text: str, width: int, max_lines: int) -> List[str]:
    import textwrap

    lines = textwrap.wrap(text, width=width, break_long_words=True) or [""]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][:max(1, width - 1)] + "…"
    return lines


def _draw_wrapped(draw: Any, text: str, xy: tuple[int, int], width: int, max_lines: int, fill: Any, anchor: str) -> None:
    lines = _svg_lines(text, width, max_lines)
    line_height = 13
    start_y = xy[1] - (len(lines) - 1) * line_height / 2
    for index, line in enumerate(lines):
        draw.text((xy[0], start_y + index * line_height), line, fill=fill, anchor=anchor)
