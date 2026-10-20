from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from typing import Any, Dict, List
from xml.etree import ElementTree


ARCHITECTURE_KEYS = {
    "title",
    "system_boundary",
    "external_actors_or_services",
    "components",
    "relationships",
    "principal_flow",
    "unknowns",
}


def generate_architecture_spec(
    graph: Dict[str, Any],
    *,
    readme: str,
    context: Dict[str, Any],
    evidence: str,
) -> Dict[str, Any]:
    """Ask Ollama for a validated, evidence-constrained architecture specification."""
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    model = os.getenv("OLLAMA_MODEL", os.getenv("CIAO_OLLAMA_MODEL", "llama3.2:3b"))
    target = {
        "submitted_source": context.get("submitted_source"),
        "project_name": context.get("project_name"),
        "repository_path": context.get("repository_path"),
        "branch": context.get("branch"),
        "commit_sha": context.get("commit_sha"),
        "commit_message": context.get("commit_message"),
        "generated_at": context.get("generated_at"),
        "document_format": context.get("document_format"),
        "image_format": context.get("image_format"),
    }
    max_evidence = max(2_000, int(os.getenv("CIAO_ARCHITECTURE_CONTEXT_CHARS", "12000")))
    timeout = max(10.0, float(os.getenv("CIAO_OLLAMA_TIMEOUT_SECONDS", "120")))
    # Never pass a broken, character-truncated JSON object as model context.
    serialized = json.dumps({
        "analysis_context": target,
        "readme": readme[:2_000],
        "nodes": graph.get("nodes", [])[:35],
        "edges": graph.get("edges", [])[:50],
        "target_evidence": evidence[:max_evidence],
    }, ensure_ascii=False)
    chunk_results = []
    from ollama import Client

    client = Client(host=host, timeout=timeout)
    system_prompt = """You are CIAO, a source-grounded software documentation and architecture analyst. The target project is the repository identified in the analysis context. CIAO is only the analyzer; do not document CIAO unless CIAO is explicitly the submitted target. Base every project claim on the supplied target-repository evidence. Cite claims with relative file paths and line ranges where available. Do not infer capabilities from filenames or common conventions. Do not invent frameworks, APIs, models, datasets, metrics, databases, pipelines, deployment, security properties, or users. Label interpretations as inferences and state “Not established by the provided repository evidence” when evidence is missing.

First identify the target project’s purpose and scope from its documentation and implementation. Then trace its actual entry points, components, APIs or interfaces, data flow, processing pipeline, integrations, configuration, tests, and deployment/CI behavior from source evidence. Distinguish documented claims from behavior verified in code.

Return only JSON for architecture_spec with these keys:
title, system_boundary, external_actors_or_services, components, relationships,
principal_flow, unknowns. Each component must have id, name, responsibility, and
evidence, plus technology, inputs, and outputs when established by the supplied source.
Use the exact text "Not established by the provided repository evidence" for missing
component technology, inputs, or outputs. Each relationship must have source_id,
target_id, direction, label, and evidence. Use empty lists and explain limitations
in unknowns when evidence is insufficient.

Use the provenance values from the analysis context: submitted source, target project name, branch, full commit SHA when available, and generation date/time with timezone. Do not substitute CIAO’s own repository metadata. Return valid output matching the application schema; do not add commentary outside it."""
    for chunk in [serialized]:
        prompt = f"""Describe the submitted target using only this repository evidence. Do not infer details from names alone. Keep the result concise and include only components and relationships directly supported by evidence. Use the analysis_context values for provenance; do not describe CIAO unless it is the submitted target. If evidence is insufficient, use empty lists and explain the limitation in unknowns.

Return exactly one JSON object with this shape:
{{"title":"short title","system_boundary":{{"id":"system","name":"target"}},"external_actors_or_services":[],"components":[{{"id":"stable-id","name":"name","responsibility":"one sentence","technology":"technology or Not established by the provided repository evidence","inputs":["evidenced input or Not established by the provided repository evidence"],"outputs":["evidenced output or Not established by the provided repository evidence"],"evidence":["path:line or graph evidence"]}}],"relationships":[{{"source_id":"stable-id","target_id":"stable-id","direction":"forward","label":"protocol and verb phrase when evidenced","evidence":["path:line or graph evidence"]}}],"principal_flow":[],"unknowns":[]}}
Use [] for every collection with no supported items. All relationship IDs must match an included component or external actor.

Repository context:
{chunk}
"""
        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ]
            response = _request_architecture_json(client, model=model, messages=messages)
            chunk_results.append(response)
        except Exception as exc:
            if isinstance(exc, RuntimeError) and str(exc).startswith("Ollama returned"):
                raise
            raise RuntimeError(
                f"Ollama generation failed at {host} using model {model}. "
                "Configure OLLAMA_HOST/OLLAMA_MODEL and ensure the model is reachable. "
                f"Details: {exc}"
            ) from exc
    return _merge_architecture_specs(chunk_results, target)


def _request_architecture_json(
    client: Any,
    *,
    model: str,
    messages: List[Dict[str, str]],
) -> Dict[str, Any]:
    last_error: Exception | None = None
    last_excerpt = ""
    for attempt in range(2):
        request_messages = messages
        if attempt == 1:
            request_messages = [
                *messages,
                {
                    "role": "user",
                    "content": (
                        "Your previous response failed validation for this reason: "
                        f"{last_error}. Fix that specific issue. Return only one JSON object "
                        "with all required top-level keys and list-valued collections. "
                        "Every retained component and relationship needs non-empty evidence; "
                        "relationship endpoints must be IDs in components or external actors. "
                        "Do not invent evidence or use Markdown fences."
                    ),
                },
            ]
        response = client.chat(
            model=model,
            messages=request_messages,
            format="json",
            options={"num_ctx": 4096, "num_predict": 1024, "temperature": 0},
        )
        content = _response_content(response)
        last_excerpt = _safe_excerpt(content)
        try:
            return _extract_json_object(content)
        except RuntimeError as exc:
            last_error = exc
    raise RuntimeError(
        "Ollama returned an invalid architecture_spec after one correction retry. "
        f"Validation: {last_error}. Response excerpt: {last_excerpt or '[empty]'}"
    ) from last_error


def _response_content(response: Any) -> str:
    if hasattr(response, "message"):
        message = response.message
        if hasattr(message, "content"):
            return str(message.content or "")
    if isinstance(response, dict):
        return str(response.get("message", {}).get("content", "") or "")
    return ""


def _safe_excerpt(content: str, limit: int = 240) -> str:
    excerpt = " ".join(str(content or "").split())
    return excerpt[:limit] + ("..." if len(excerpt) > limit else "")


def generate_architecture_description(
    graph: Dict[str, Any],
    *,
    readme: str,
    context: Dict[str, Any],
    evidence: str,
) -> str:
    """Compatibility wrapper returning the structured spec as JSON text."""
    return json.dumps(
        generate_architecture_spec(graph, readme=readme, context=context, evidence=evidence),
        indent=2,
        ensure_ascii=False,
    )


def _extract_json_object(content: str) -> Dict[str, Any]:
    value = content.strip()
    if "```" in value:
        parts = [part.strip() for part in value.split("```") if part.strip()]
        value = next((part[4:].strip() for part in parts if part.startswith("json")), parts[0])
    start, end = value.find("{"), value.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError("Ollama returned architecture text instead of JSON architecture_spec")
    try:
        parsed = json.loads(value[start:end + 1])
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Ollama returned invalid architecture_spec JSON: {exc}") from exc
    return _validate_architecture_spec(parsed)


def _validate_architecture_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(spec, dict):
        raise RuntimeError("Architecture specification must be a JSON object")
    # Some local Ollama models wrap the requested object or omit empty arrays.
    # Recover those harmless shape differences instead of failing the whole
    # documentation request; malformed individual records are omitted below.
    nested = spec.get("architecture_spec")
    if isinstance(nested, dict):
        spec = nested
    required_collections = ("components", "relationships", "principal_flow", "unknowns")
    missing = [key for key in required_collections if key not in spec]
    components = spec.get("components", [])
    relationships = spec.get("relationships", [])
    unknowns = _string_list(spec.get("unknowns"))
    if missing:
        unknowns.append("Ollama omitted optional empty fields: " + ", ".join(missing) + ".")
    if not isinstance(components, list):
        components = []
        unknowns.append("Ollama returned components in an unsupported shape; they were omitted.")
    if not isinstance(relationships, list):
        relationships = []
        unknowns.append("Ollama returned relationships in an unsupported shape; they were omitted.")
    normalized_components = []
    ids = set()
    for item in components:
        if not isinstance(item, dict) or not item.get("id") or not item.get("name") or not item.get("responsibility"):
            unknowns.append("Ollama returned a component without an ID, name, or responsibility; it was omitted.")
            continue
        item = dict(item)
        item["evidence"] = _evidence_list(item.get("evidence"))
        if not item["evidence"]:
            unknowns.append(f"Component {item['name']} had no evidence and was omitted.")
            continue
        ids.add(str(item["id"]))
        normalized_components.append(item)
    normalized_external = []
    external_items = spec.get("external_actors_or_services", []) or []
    if not isinstance(external_items, list):
        external_items = []
        unknowns.append("External actors were not a list and were omitted.")
    for item in external_items:
        if not isinstance(item, dict) or not item.get("id") or not item.get("name"):
            unknowns.append("An external actor without an ID or name was omitted.")
            continue
        item = dict(item)
        item["evidence"] = _evidence_list(item.get("evidence"))
        if not item["evidence"]:
            unknowns.append(f"External actor {item['name']} had no evidence and was omitted.")
            continue
        ids.add(str(item["id"]))
        normalized_external.append(item)
    normalized_relationships = []
    for item in relationships:
        if not isinstance(item, dict) or not item.get("source_id") or not item.get("target_id") or not item.get("label"):
            unknowns.append("A relationship without source, target, and label was omitted.")
            continue
        if str(item["source_id"]) not in ids or str(item["target_id"]) not in ids:
            unknowns.append(f"Relationship {item.get('label')} referenced a missing component and was omitted.")
            continue
        item = dict(item)
        item["direction"] = item.get("direction", "forward")
        item["evidence"] = _evidence_list(item.get("evidence"))
        if not item["evidence"]:
            unknowns.append(f"Relationship {item['label']} had no evidence and was omitted.")
            continue
        normalized_relationships.append(item)
    return {
        "title": str(spec.get("title") or "Evidence-backed system architecture"),
        "system_boundary": _normalize_boundary(spec.get("system_boundary")),
        "external_actors_or_services": normalized_external,
        "components": normalized_components,
        "relationships": normalized_relationships,
        "principal_flow": _string_list(spec.get("principal_flow")),
        "unknowns": list(dict.fromkeys(unknowns)),
    }


def _evidence_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if value:
        return [str(value)]
    return []


def _string_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _normalize_boundary(value: Any) -> Dict[str, str]:
    if isinstance(value, str) and value.strip():
        return {"id": "system", "name": value.strip()}
    if isinstance(value, dict):
        return {"id": str(value.get("id") or "system"), "name": str(value.get("name") or "Target system")}
    return {"id": "system", "name": "Target system"}


def build_architecture_spec_from_graph(
    graph: Dict[str, Any], *, repository_path: Path, project_name: str
) -> Dict[str, Any]:
    """Create a readable file-level architecture from verified repository edges."""
    root = repository_path.resolve()
    graph_nodes = [node for node in graph.get("nodes", []) if isinstance(node, dict) and node.get("id")]
    node_by_id = {str(node["id"]): node for node in graph_nodes}
    files = []
    for node in graph_nodes:
        if node.get("type") != "file" or not node.get("path"):
            continue
        path = Path(str(node["path"]))
        relative = path.relative_to(root).as_posix() if path.is_absolute() else path.as_posix()
        lowered = relative.lower()
        if path.name == "__init__.py" or "/test/" in f"/{lowered}/" or path.name.startswith("test_"):
            continue
        files.append((node, relative))
    files = files[:24]

    # File-level imports are clearer than drawing every imported symbol and
    # local variable as a separate architecture component.
    components = []
    file_ids = set()
    module_to_file: Dict[str, List[str]] = {}
    for node, relative in files:
        node_id = str(node["id"])
        file_ids.add(node_id)
        module_path = str(Path(relative).with_suffix("")).replace("/", ".").replace("\\", ".")
        module_to_file.setdefault(module_path, []).append(node_id)
        module_to_file.setdefault(Path(relative).stem, []).append(node_id)
        functions = []
        if Path(relative).suffix.lower() == ".py":
            try:
                import ast
                source_text = (root / relative).read_text(encoding="utf-8", errors="replace")
                parsed = ast.parse(source_text)
                functions = [
                    item.name for item in ast.walk(parsed)
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
            except (OSError, SyntaxError, UnicodeError):
                functions = []
        components.append({
            "id": node_id,
            "name": relative,
            "responsibility": (
                "Python module · " + ", ".join(f"{name}()" for name in functions[:4])
                if functions else "Source module"
            ),
            "evidence": [relative],
            "functions": functions[:12],
            "technology": Path(relative).suffix.lstrip(".").upper() or "Not established by the provided repository evidence",
            "inputs": ["Not established by the provided repository evidence"],
            "outputs": ["Not established by the provided repository evidence"],
        })

    relationships = []
    seen = set()
    for edge in graph.get("edges", []):
        if not isinstance(edge, dict):
            continue
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source in file_ids and target in file_ids:
            target_id = target
        elif source in file_ids and target in node_by_id and node_by_id[target].get("type") == "module":
            module_name = str(node_by_id[target].get("name") or target.removeprefix("module:"))
            matches = module_to_file.get(module_name) or module_to_file.get(module_name.rsplit(".", 1)[-1]) or []
            target_id = next((item for item in matches if item != source), "") if len(set(matches)) == 1 else ""
        else:
            continue
        key = (source, target_id)
        if not target_id or key in seen:
            continue
        seen.add(key)
        source_name = next((relative for node, relative in files if str(node["id"]) == source), source)
        target_name = next((relative for node, relative in files if str(node["id"]) == target_id), target_id)
        relationships.append({
            "source_id": source,
            "target_id": target_id,
            "direction": "forward",
            "label": "imports",
            "evidence": [f"{source_name} imports or references {target_name}"],
        })
    return _validate_architecture_spec({
        "title": f"{project_name} architecture",
        "system_boundary": {"id": "system", "name": project_name},
        "external_actors_or_services": [],
        "components": components,
        "relationships": relationships,
        "principal_flow": [],
        "unknowns": ["The diagram shows file-level repository structure and detected imports; runtime behavior is not established."],
    })


def generate_documentation_report(
    graph: Dict[str, Any], *, readme: str, context: Dict[str, Any]
) -> str:
    """Build model context from actual target source, not just graph filenames."""
    root = Path(str(context.get("repository_path") or "."))
    manifest = context.get("file_manifest") or []
    preferred = ("readme", "requirements", "pyproject", "package.json", "setup.py", "main.py", "app.py", "api", "route", "service", "model", "predict", "train", "config", "docker", "workflow")
    candidates = sorted(
        (str(item) for item in manifest),
        key=lambda name: (
            min((index for index, token in enumerate(preferred) if token in Path(name).name.lower() or token in name.lower()), default=len(preferred)),
            name.lower(),
        ),
    )
    evidence_sections: List[str] = []
    evidence_size = 0
    for relative in candidates:
        path = Path(relative)
        full_path = path if path.is_absolute() else root / path
        try:
            if not full_path.is_file() or full_path.stat().st_size > 250_000:
                continue
            source_lines = full_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        excerpt = "\n".join(f"{relative}:{index}: {line}" for index, line in enumerate(source_lines[:180], 1))
        section = f"FILE {relative}\n{excerpt}"
        if evidence_size + len(section) > 16_000:
            continue
        evidence_sections.append(section)
        evidence_size += len(section)
    if not evidence_sections:
        evidence_sections = [
            f"{node.get('path') or node.get('id')}: {node.get('type') or 'component'}"
            for node in graph.get("nodes", [])[:60]
            if isinstance(node, dict)
        ]
    evidence = "\n\n".join(evidence_sections)
    spec = generate_architecture_spec(
        graph, readme=readme, context=context, evidence=evidence
    )
    return json.dumps(spec, indent=2, ensure_ascii=False)


def _merge_architecture_specs(specs: List[Dict[str, Any]], context: Dict[str, Any]) -> Dict[str, Any]:
    if not specs:
        raise RuntimeError("Ollama returned no architecture specification")
    components: Dict[str, Dict[str, Any]] = {}
    relationships: Dict[tuple[str, str, str], Dict[str, Any]] = {}
    external = []
    flows = []
    unknowns = []
    for spec in specs:
        for component in spec["components"]:
            components.setdefault(component["id"], component)
        for relationship in spec["relationships"]:
            key = (relationship["source_id"], relationship["target_id"], relationship["label"])
            relationships.setdefault(key, relationship)
        external.extend(spec["external_actors_or_services"])
        flows.extend(spec["principal_flow"])
        unknowns.extend(spec["unknowns"])
    return _validate_architecture_spec({
        "title": specs[0]["title"],
        "system_boundary": specs[0]["system_boundary"],
        "external_actors_or_services": external,
        "components": list(components.values()),
        "relationships": list(relationships.values()),
        "principal_flow": list(dict.fromkeys(str(item) for item in flows)),
        "unknowns": list(dict.fromkeys(str(item) for item in unknowns)),
    })


def validate_output(path: Path, fmt: str) -> None:
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError(f"Generated {path.name} is missing or empty")
    data = path.read_bytes()
    if fmt == "pdf":
        if not data.startswith(b"%PDF-") or b"stream" not in data:
            raise RuntimeError(f"Generated {path.name} is not a valid visible PDF")
    elif fmt == "docx":
        try:
            with zipfile.ZipFile(path) as archive:
                document = archive.read("word/document.xml")
            if not document.strip() or b"<w:t" not in document:
                raise RuntimeError(f"Generated {path.name} contains no visible document text")
        except (KeyError, zipfile.BadZipFile) as exc:
            raise RuntimeError(f"Generated {path.name} is not a valid DOCX") from exc
    elif fmt == "png":
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError(f"Generated {path.name} is not a valid PNG")
        try:
            from PIL import Image

            with Image.open(path) as image:
                image.verify()
        except Exception as exc:
            raise RuntimeError(f"Generated {path.name} could not be opened as PNG") from exc
    elif fmt == "svg":
        try:
            root = ElementTree.fromstring(data)
            if root.tag.rsplit("}", 1)[-1] != "svg" or len(data) < 100:
                raise ValueError
        except Exception as exc:
            raise RuntimeError(f"Generated {path.name} is not a valid SVG") from exc
    else:
        raise ValueError(f"Unsupported output format: {fmt}")
