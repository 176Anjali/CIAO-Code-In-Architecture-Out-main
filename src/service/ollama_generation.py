from __future__ import annotations

import hashlib
import json
import os
import re
import time
import zipfile
from textwrap import wrap
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


def build_architecture_spec_from_graph(
    graph: Dict[str, Any], *, repository_path: Path, project_name: str
) -> Dict[str, Any]:
    """Build a deterministic file-level architecture from verified graph edges."""
    root = Path(repository_path).resolve()
    nodes = {str(node.get("id")): node for node in graph.get("nodes", []) if isinstance(node, dict) and node.get("id")}
    file_paths: Dict[str, str] = {}
    owner: Dict[str, str] = {}
    symbols: Dict[str, Dict[str, List[str]]] = {}
    for node_id, node in nodes.items():
        raw_path = node.get("path") if node.get("type") == "file" else node.get("file")
        if not raw_path:
            continue
        try:
            relative = Path(raw_path).resolve().relative_to(root).as_posix()
        except (OSError, ValueError):
            continue
        owner[node_id] = relative
        if node.get("type") == "file":
            file_paths[relative] = node_id
        kind = str(node.get("type", "symbol"))
        name = str(node.get("qualified_name") or node.get("name") or "")
        if name and kind not in {"file", "module", "variable"}:
            symbols.setdefault(relative, {}).setdefault(kind, []).append(name)
    scores = {path: 0 for path in file_paths}
    raw_edges = [edge for edge in graph.get("edges", []) if isinstance(edge, dict)]
    for edge in raw_edges:
        relation = str(edge.get("relationship", edge.get("type", ""))).upper()
        if relation == "SIBLING_FILE":
            continue
        source_path, target_path = owner.get(str(edge.get("source"))), owner.get(str(edge.get("target")))
        if source_path and target_path and source_path != target_path:
            scores[source_path] = scores.get(source_path, 0) + 1
            scores[target_path] = scores.get(target_path, 0) + 1
        elif source_path and nodes.get(str(edge.get("target")), {}).get("external"):
            scores[source_path] = scores.get(source_path, 0) + 1
    selected = sorted(file_paths, key=lambda path: (-scores.get(path, 0), path.casefold()))[:12]
    component_ids = {
        path: "file-" + hashlib.sha1(path.encode("utf-8")).hexdigest()[:10]
        for path in selected
    }
    components = []
    for path in selected:
        kinds = symbols.get(path, {})
        details = [f"{len(names)} {kind}{'s' if len(names) != 1 else ''}" for kind, names in sorted(kinds.items()) if names]
        responsibility = "Defines " + ", ".join(details[:3]) if details else "Source file detected by static analysis"
        components.append({
            "id": component_ids[path],
            "name": path,
            "responsibility": responsibility[:180],
            "evidence": [path],
        })
    external_nodes = {}
    relationships: Dict[tuple[str, str, str], Dict[str, Any]] = {}
    selected_set = set(selected)
    for edge in raw_edges:
        relation = str(edge.get("relationship", edge.get("type", ""))).upper()
        if relation in {"SIBLING_FILE", "MODULE", "DEFINES"}:
            continue
        source_id, target_id = str(edge.get("source", "")), str(edge.get("target", ""))
        source_path, target_path = owner.get(source_id), owner.get(target_id)
        source_component = component_ids.get(source_path or "")
        target_component = component_ids.get(target_path or "")
        if source_component and target_component and source_path != target_path:
            label = relation.lower().replace("_", " ") or "connects to"
        elif source_component and nodes.get(target_id, {}).get("external"):
            external_name = str(nodes[target_id].get("name") or target_id)
            external_id = "external-" + hashlib.sha1(external_name.encode("utf-8")).hexdigest()[:10]
            external_nodes[external_id] = {"id": external_id, "name": external_name, "evidence": [source_path or ""]}
            target_component = external_id
            label = relation.lower().replace("_", " ") or "uses"
        else:
            continue
        key = (source_component, target_component, label)
        relationships.setdefault(key, {
            "source_id": source_component,
            "target_id": target_component,
            "direction": "forward",
            "label": label,
            "evidence": [source_path or target_path or ""],
        })
    chosen_relationships = list(relationships.values())[:16]
    referenced_external = {edge["target_id"] for edge in chosen_relationships if edge["target_id"].startswith("external-")}
    return {
        "title": f"{project_name} architecture",
        "system_boundary": {"id": "system", "name": project_name},
        "external_actors_or_services": [external_nodes[key] for key in sorted(referenced_external)],
        "components": components,
        "relationships": chosen_relationships,
        "principal_flow": [],
        "unknowns": ["Static analysis identifies source structure and explicit links; it cannot establish runtime deployment or unobserved behavior."],
    }


def summarize_graph_modules(graph: Dict[str, Any], repository_path: Path) -> List[Dict[str, Any]]:
    """Condense graph facts by source file before sending context to Ollama."""
    root = Path(repository_path).resolve()
    nodes = {str(node.get("id")): node for node in graph.get("nodes", []) if isinstance(node, dict) and node.get("id")}
    owner: Dict[str, str] = {}
    modules: Dict[str, Dict[str, Any]] = {}
    for node_id, node in nodes.items():
        raw_path = node.get("path") if node.get("type") == "file" else node.get("file")
        if not raw_path:
            continue
        try:
            relative = Path(raw_path).resolve().relative_to(root).as_posix()
        except (OSError, ValueError):
            continue
        owner[node_id] = relative
        module = modules.setdefault(relative, {"file": relative, "symbols": {}, "connections": set()})
        kind = str(node.get("type", "symbol"))
        name = node.get("qualified_name") or node.get("name")
        if name and kind not in {"file", "module", "variable"}:
            module["symbols"].setdefault(kind, set()).add(str(name))
    for edge in graph.get("edges", []):
        if not isinstance(edge, dict):
            continue
        relation = str(edge.get("relationship", edge.get("type", "unknown")))
        if relation.upper() in {"SIBLING_FILE", "MODULE", "DEFINES"}:
            continue
        source_id, target_id = str(edge.get("source", "")), str(edge.get("target", ""))
        source_path, target_path = owner.get(source_id), owner.get(target_id)
        if source_path and target_path and source_path != target_path:
            modules[source_path]["connections"].add(f"{relation} -> {target_path}")
        elif source_path and nodes.get(target_id, {}).get("external"):
            external_name = nodes[target_id].get("name") or target_id
            modules[source_path]["connections"].add(f"{relation} -> external {external_name}")
    result = []
    for path, module in sorted(modules.items()):
        result.append({
            "file": path,
            "symbols": {kind: sorted(names)[:24] for kind, names in sorted(module["symbols"].items())},
            "connections": sorted(module["connections"])[:32],
        })
    return result


def generate_documentation_report(
    graph: Dict[str, Any], *, readme: str, context: Dict[str, Any], cache_dir: Path | None = None
) -> str:
    """Generate cached graph-chunk summaries, then one cached final report."""
    from ollama import Client

    host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    model = os.getenv("OLLAMA_MODEL", os.getenv("CIAO_OLLAMA_MODEL", "llama3.2:3b"))
    cache_root = Path(cache_dir or os.getenv("CIAO_CACHE_DIR", Path(__file__).resolve().parents[2] / ".ciao-cache"))
    modules = summarize_graph_modules(graph, Path(context["repository_path"]))
    chunk_limit = max(2000, int(os.getenv("CIAO_SUMMARY_CHUNK_CHARS", "12000")))
    chunks: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []
    current_size = 0
    for module in modules or [{"file": "No source modules detected", "symbols": {}, "connections": []}]:
        encoded = json.dumps(module, ensure_ascii=False, sort_keys=True)
        if current and current_size + len(encoded) > chunk_limit:
            chunks.append(current)
            current, current_size = [], 0
        current.append(module)
        current_size += len(encoded)
    if current:
        chunks.append(current)

    client = Client(host=host)
    summaries = []
    for index, chunk in enumerate(chunks, 1):
        content = json.dumps({"project_name": context.get("project_name"), "modules": chunk}, ensure_ascii=False, sort_keys=True)
        prompt = (
            "Summarize only these deterministic knowledge-graph facts for a software documentation report. "
            "Keep module responsibility, observed symbols, and explicit cross-module connections. "
            "Do not infer purpose or behavior from names alone; mark unknowns. Cite the given relative paths.\n\n"
            + content
        )
        summary, cache_hit = _cached_ollama_text(
            client, model=model, content=content, prompt=prompt,
            prompt_version="ciao-module-summary-v1", cache_dir=cache_root,
            num_predict=_positive_env("CIAO_OLLAMA_SUMMARY_NUM_PREDICT", 384), kind=f"module_summary_{index}_of_{len(chunks)}",
        )
        summaries.append(summary)

    report_input = json.dumps({
        "project_name": context.get("project_name"),
        "submitted_source": context.get("submitted_source"),
        "README": (readme or "README not present")[:8000],
        "knowledge_graph_module_summaries": summaries,
    }, ensure_ascii=False, sort_keys=True)
    report_prompt = """Write a project-specific research-style software documentation report from the supplied README and knowledge-graph module summaries only. Do not discuss CIAO unless it is the target project. Do not invent runtime behavior, algorithms, APIs, databases, users, deployment, security, metrics, or dependencies. Clearly mark conclusions that cannot be established. Cite repository-relative file paths from the supplied summaries. Return Markdown only, with these headings in order:
# Project Documentation
## Abstract
## 1. Introduction and Project Purpose
## 2. Problem Addressed and Scope
## 3. System Architecture and Components
## 4. How the Project Works
## 5. End-to-End Pipeline
## 6. Technologies, Interfaces, and Resources
## 7. Data Flow and Outputs
## 8. Testing, Configuration, and Deployment
## 9. Limitations and Open Questions
## Conclusion
Keep the report concise, evidence-based, and internally consistent with the supplied graph summaries.\n\n""" + report_input
    report, _ = _cached_ollama_text(
        client, model=model, content=report_input, prompt=report_prompt,
        prompt_version="ciao-final-report-v1", cache_dir=cache_root,
        num_predict=_positive_env("CIAO_OLLAMA_NUM_PREDICT", 1024), kind="final_report",
    )
    return report


def _positive_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a positive integer") from exc
    if value < 1:
        raise RuntimeError(f"{name} must be a positive integer")
    return value


def _cached_ollama_text(
    client: Any, *, model: str, content: str, prompt: str, prompt_version: str,
    cache_dir: Path, num_predict: int, kind: str,
) -> tuple[str, bool]:
    cache_key = hashlib.sha256(f"{prompt_version}\0{model}\0{content}".encode("utf-8")).hexdigest()
    cache_path = cache_dir / f"{cache_key}.json"
    started = time.perf_counter()
    try:
        entry = json.loads(cache_path.read_text(encoding="utf-8"))
        cached = entry.get("text")
        if entry.get("key") == cache_key and isinstance(cached, str) and cached.strip():
            print(f"CIAO_TIMING stage=ollama.cache kind={kind} result=hit seconds={time.perf_counter()-started:.3f}")
            return cached, True
    except (OSError, ValueError, AttributeError):
        pass

    system = "You are CIAO, an evidence-grounded software documentation analyst. Preserve uncertainty and never fabricate claims."
    call_started = time.perf_counter()
    try:
        response = client.chat(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            keep_alive=os.getenv("CIAO_OLLAMA_KEEP_ALIVE", "10m"),
            options={
                "num_ctx": _positive_env("CIAO_OLLAMA_NUM_CTX", 4096),
                "num_predict": num_predict,
                "temperature": 0,
            },
        )
    except Exception as exc:
        print(f"CIAO_TIMING stage=ollama.call kind={kind} result=error seconds={time.perf_counter()-call_started:.3f}")
        raise RuntimeError(f"Ollama generation failed at {os.getenv('OLLAMA_HOST', 'http://localhost:11434')} using model {model}: {exc}") from exc
    text = _response_content(response).strip()
    print(f"CIAO_TIMING stage=ollama.call kind={kind} result={'ok' if text else 'empty'} seconds={time.perf_counter()-call_started:.3f}")
    if not text:
        raise RuntimeError(f"Ollama returned empty content for {kind} using model {model}")
    cache_dir.mkdir(parents=True, exist_ok=True)
    temporary = cache_path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps({"key": cache_key, "prompt_version": prompt_version, "model": model, "text": text}, ensure_ascii=False), encoding="utf-8")
    temporary.replace(cache_path)
    print(f"CIAO_TIMING stage=ollama.cache kind={kind} result=miss seconds={time.perf_counter()-started:.3f}")
    return text, False

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
    context = {
        "analysis_context": target,
        "readme": readme[:6000],
        "nodes": graph.get("nodes", [])[:100],
        "edges": graph.get("edges", [])[:180],
        "target_evidence": evidence,
    }
    serialized = json.dumps(context, indent=2, ensure_ascii=False)
    max_evidence = int(os.getenv("CIAO_ARCHITECTURE_CONTEXT_CHARS", "24000"))
    serialized = serialized[:max_evidence]
    chunk_width = int(os.getenv("CIAO_ARCHITECTURE_CHUNK_CHARS", "12000"))
    max_chunks = int(os.getenv("CIAO_MAX_ARCHITECTURE_CHUNKS", "1"))
    chunks = wrap(serialized, width=chunk_width, break_long_words=False, break_on_hyphens=False) or ["{}"]
    chunks = chunks[:max_chunks]
    chunk_results = []
    from ollama import Client

    client = Client(host=host)
    system_prompt = """You are CIAO, a source-grounded software documentation and architecture analyst. The target project is the repository identified in the analysis context. CIAO is only the analyzer; do not document CIAO unless CIAO is explicitly the submitted target. Base every project claim on the supplied target-repository evidence. Cite claims with relative file paths and line ranges where available. Do not infer capabilities from filenames or common conventions. Do not invent frameworks, APIs, models, datasets, metrics, databases, pipelines, deployment, security properties, or users. Label interpretations as inferences and state “Not established by the provided repository evidence” when evidence is missing.

First identify the target project’s purpose and scope from its documentation and implementation. Then trace its actual entry points, components, APIs or interfaces, data flow, processing pipeline, integrations, configuration, tests, and deployment/CI behavior from source evidence. Distinguish documented claims from behavior verified in code.

Return only JSON for architecture_spec with these keys:
title, system_boundary, external_actors_or_services, components, relationships,
principal_flow, unknowns. Each component must have id, name, responsibility, and
evidence. Each relationship must have source_id, target_id, direction, label, and
evidence. Use empty lists and explain limitations in unknowns when evidence is insufficient.

Use the provenance values from the analysis context: submitted source, target project name, branch, full commit SHA when available, and generation date/time with timezone. Do not substitute CIAO’s own repository metadata. Return valid output matching the application schema; do not add commentary outside it. Keep the architecture concise: at most 12 components, 5 external actors or services, 16 relationships, 8 principal-flow steps, and 8 unknowns. Group related files into meaningful components instead of listing every file. Keep responsibilities to 15 words or fewer, relationship labels to 6 words or fewer, and evidence entries to one concise relative path and line range."""
    for index, chunk in enumerate(chunks[:12], 1):
        prompt = f"""Analyze chunk {index} of {len(chunks)} from this verified CIAO repository context.
Use only the supplied target-repository evidence and preserve relative paths and line ranges.
Do not document CIAO unless the analysis context explicitly identifies CIAO as the submitted target.
Do not invent users, APIs, databases, queues, deployment, security claims, or dependencies.
Clearly mark unknowns.
Return only the JSON architecture_spec object. This is a partial chunk; include only
components and relationships directly supported by this chunk. Return at most 12 components and 16 relationships. Group related files and keep all descriptions and evidence concise.

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
    return _merge_architecture_specs(chunk_results, context)


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
                        "Correction: return only one valid JSON object matching the required "
                        "architecture_spec keys. Required top-level keys are title, "
                        "system_boundary, external_actors_or_services, components, "
                        "relationships, principal_flow, and unknowns. Do not use Markdown "
                        "fences or explanatory text. Keep the JSON concise: at most 12 components and 16 relationships, with short descriptions and evidence."
                    ),
                },
            ]
        response = client.chat(
            model=model,
            messages=request_messages,
            format="json",
            keep_alive=os.getenv("CIAO_OLLAMA_KEEP_ALIVE", "10m"),
            options={
                "num_ctx": _positive_env("CIAO_OLLAMA_NUM_CTX", 4096),
                "num_predict": _positive_env("CIAO_OLLAMA_NUM_PREDICT", 1024),
                "temperature": 0,
            },
        )
        content = _response_content(response)
        last_excerpt = _safe_excerpt(content)
        try:
            return _extract_json_object(content)
        except RuntimeError as exc:
            last_error = exc
    raise RuntimeError(
        "Ollama returned an invalid architecture_spec after one correction retry. "
        f"Response excerpt: {last_excerpt or '[empty]'}"
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
    required = ARCHITECTURE_KEYS - {"external_actors_or_services"}
    missing = sorted(key for key in required if key not in spec)
    if missing:
        raise RuntimeError(
            "Architecture specification is missing required keys: " + ", ".join(missing)
        )
    components = spec.get("components", [])
    relationships = spec.get("relationships", [])
    if not isinstance(components, list) or not isinstance(relationships, list):
        raise RuntimeError("Architecture specification components and relationships must be lists")
    normalized_components = []
    ids = set()
    for item in components:
        if not isinstance(item, dict) or not item.get("id") or not item.get("name") or not item.get("responsibility"):
            raise RuntimeError("Every architecture component requires id, name, and responsibility")
        item = dict(item)
        item["evidence"] = _evidence_list(item.get("evidence"))
        ids.add(str(item["id"]))
        normalized_components.append(item)
    normalized_external = []
    for index, item in enumerate(spec.get("external_actors_or_services", []) or [], 1):
        if isinstance(item, str):
            name = item.strip()
            if not name:
                continue
            identifier = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
            item = {"id": "external-" + (identifier or str(index)), "name": name}
        if not isinstance(item, dict) or not item.get("id") or not item.get("name"):
            raise RuntimeError("Every external actor or service requires id and name")
        item = dict(item)
        item["evidence"] = _evidence_list(item.get("evidence"))
        ids.add(str(item["id"]))
        normalized_external.append(item)
    normalized_relationships = []
    endpoint_ids = {str(item["id"]): str(item["id"]) for item in [*normalized_components, *normalized_external]}
    endpoint_ids.update({str(item["name"]): str(item["id"]) for item in [*normalized_components, *normalized_external]})
    for item in relationships:
        if not isinstance(item, dict):
            raise RuntimeError("Every architecture relationship must be an object")
        item = dict(item)
        source = item.get("source_id") or item.get("source") or item.get("from") or item.get("source_component")
        target = item.get("target_id") or item.get("target") or item.get("to") or item.get("target_component")
        label = item.get("label") or item.get("type") or item.get("relationship") or item.get("description")
        if not source or not target or not label:
            raise RuntimeError("Every architecture relationship requires source_id, target_id, and label")
        item["source_id"] = endpoint_ids.get(str(source), str(source))
        item["target_id"] = endpoint_ids.get(str(target), str(target))
        if item["source_id"] not in ids or item["target_id"] not in ids:
            raise RuntimeError("Architecture relationship references an unknown component")
        item["label"] = str(label)
        item["direction"] = item.get("direction", "forward")
        item["evidence"] = _evidence_list(item.get("evidence"))
        normalized_relationships.append(item)
    return {
        "title": str(spec.get("title") or "Evidence-backed system architecture"),
        "system_boundary": spec.get("system_boundary") or {"id": "system", "name": "Target system"},
        "external_actors_or_services": normalized_external,
        "components": normalized_components,
        "relationships": normalized_relationships,
        "principal_flow": spec.get("principal_flow") or [],
        "unknowns": spec.get("unknowns") or [],
    }


def _evidence_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if value:
        return [str(value)]
    return ["Evidence reference not supplied by model"]


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
