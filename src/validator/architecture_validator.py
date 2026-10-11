import json
import re
from pathlib import Path


class ArchitectureValidator:

    def __init__(
        self,
        graph_path,
        analysis_path,
        output_path=None,
    ):
        self.graph_path = Path(graph_path)
        self.analysis_path = Path(analysis_path)

        if output_path is None:
            output_path = (
                self.graph_path.parent.parent
                / "docs"
                / "architecture_validation.json"
            )

        self.output_path = Path(output_path)

        self.graph = {}
        self.analysis = ""

        self.nodes = {}
        self.edges = []

        self.results = []

        self.hard_supported = 0
        self.hard_unsupported = 0
        self.review_count = 0

        self.consistency_score = 0.0

    # =========================================================
    # LOAD
    # =========================================================

    def load_graph(self):
        if not self.graph_path.exists():
            raise FileNotFoundError(
                f"Knowledge graph not found: {self.graph_path}"
            )

        with open(
            self.graph_path,
            "r",
            encoding="utf-8",
        ) as f:
            self.graph = json.load(f)

        self._normalize_graph()

    def load_analysis(self):
        if not self.analysis_path.exists():
            raise FileNotFoundError(
                f"Architecture analysis not found: {self.analysis_path}"
            )

        with open(
            self.analysis_path,
            "r",
            encoding="utf-8",
        ) as f:
            self.analysis = f.read()

    def load(self):
        self.load_graph()
        self.load_analysis()

    # =========================================================
    # GRAPH NORMALIZATION
    # =========================================================

    def _normalize_graph(self):

        self.nodes = {}
        self.edges = []

        raw_nodes = self.graph.get("nodes", [])

        if isinstance(raw_nodes, list):

            for node in raw_nodes:

                if isinstance(node, str):
                    self.nodes[node] = {"id": node}
                    continue

                if not isinstance(node, dict):
                    continue

                node_id = (
                    node.get("id")
                    or node.get("node")
                    or node.get("name")
                )

                if node_id:
                    node_id = str(node_id)

                    normalized = dict(node)
                    normalized["id"] = node_id

                    self.nodes[node_id] = normalized

        elif isinstance(raw_nodes, dict):

            for node_id, attributes in raw_nodes.items():

                node_id = str(node_id)

                normalized = {"id": node_id}

                if isinstance(attributes, dict):
                    normalized.update(attributes)

                normalized["id"] = node_id

                self.nodes[node_id] = normalized

        raw_edges = self.graph.get("edges", [])

        if isinstance(raw_edges, list):

            for edge in raw_edges:

                if not isinstance(edge, dict):
                    continue

                source = (
                    edge.get("source")
                    or edge.get("from")
                    or edge.get("u")
                )

                target = (
                    edge.get("target")
                    or edge.get("to")
                    or edge.get("v")
                )

                relation = (
                    edge.get("relation")
                    or edge.get("relationship")
                    or edge.get("type")
                )

                if source and target and relation:

                    self.edges.append(
                        {
                            "source": str(source),
                            "target": str(target),
                            "relation": str(relation),
                        }
                    )

    # =========================================================
    # GRAPH QUERIES
    # =========================================================

    def node_exists(self, node_id):
        return str(node_id) in self.nodes

    def has_edge(self, source, relation, target):

        source = str(source)
        target = str(target)
        relation = str(relation)

        for edge in self.edges:

            if (
                edge["source"] == source
                and edge["relation"] == relation
                and edge["target"] == target
            ):
                return True

        return False

    def edge_evidence(self, source, relation, target):

        if self.has_edge(
            source,
            relation,
            target,
        ):
            return (
                f"{source} --{relation}--> {target}"
            )

        return None

    # =========================================================
    # TEXT CLEANING
    # =========================================================

    @staticmethod
    def clean_markdown(text):

        text = str(text).strip()

        # Remove Markdown code backticks.
        text = text.replace("`", "")

        # Remove bold/italic Markdown markers.
        text = text.replace("**", "")
        text = text.replace("__", "")

        return text.strip()

    @classmethod
    def clean_bullet(cls, line):

        line = cls.clean_markdown(line)

        # Remove bullet markers.
        line = re.sub(
            r"^[-*•]\s*",
            "",
            line,
        )

        # Remove numbered-list markers.
        line = re.sub(
            r"^\d+[.)]\s*",
            "",
            line,
        )

        return cls.clean_markdown(line)

    @classmethod
    def is_heading(cls, line):

        text = cls.clean_markdown(line).strip()

        if not text:
            return False

        text = text.rstrip(":").strip()

        headings = {
            "ARCHITECTURE SUMMARY",
            "COMPONENTS",
            "DEPENDENCIES",
            "ENTRY POINTS",
            "CORE COMPONENTS",
            "ARCHITECTURAL OBSERVATIONS",
            "UNCERTAINTIES",
        }

        return text.upper() in headings

    # =========================================================
    # SECTION PARSER
    # =========================================================

    def sections(self):

        result = {}
        current = None

        valid_sections = {
            "ARCHITECTURE SUMMARY",
            "COMPONENTS",
            "DEPENDENCIES",
            "ENTRY POINTS",
            "CORE COMPONENTS",
            "ARCHITECTURAL OBSERVATIONS",
            "UNCERTAINTIES",
        }

        for raw_line in self.analysis.splitlines():

            line = raw_line.strip()

            if not line:
                continue

            cleaned_line = self.clean_markdown(line)

            heading = cleaned_line.rstrip(":").strip()
            heading_upper = heading.upper()

            if heading_upper in valid_sections:

                current = heading_upper

                result.setdefault(
                    current,
                    [],
                )

                continue

            if current is None:
                continue

            cleaned = self.clean_bullet(line)

            if not cleaned:
                continue

            # Ignore Markdown headings that slipped through.
            if self.is_heading(cleaned):
                continue

            result[current].append(cleaned)

        return result

    # =========================================================
    # RESULT HANDLING
    # =========================================================

    def add_pass(
        self,
        section,
        claim,
        evidence,
    ):

        self.hard_supported += 1

        self.results.append(
            {
                "section": section,
                "status": "PASS",
                "claim": claim,
                "evidence": evidence,
                "reason": (
                    "Claim is supported by the knowledge graph."
                ),
            }
        )

    def add_fail(
        self,
        section,
        claim,
        reason,
    ):

        self.hard_unsupported += 1

        self.results.append(
            {
                "section": section,
                "status": "FAIL",
                "claim": claim,
                "evidence": None,
                "reason": reason,
            }
        )

    def add_review(
        self,
        section,
        claim,
        reason,
    ):

        self.review_count += 1

        self.results.append(
            {
                "section": section,
                "status": "REVIEW",
                "claim": claim,
                "evidence": None,
                "reason": reason,
            }
        )

    # =========================================================
    # COMPONENT VALIDATION
    # =========================================================

    def validate_components(self, claims):

        for raw_claim in claims:

            claim = self.clean_markdown(raw_claim)

            if not claim or claim.endswith(":"):
                continue

            possible_node = self.resolve_component_node(claim)

            if possible_node and self.node_exists(possible_node):
                self.add_pass(
                    "COMPONENTS",
                    claim,
                    f"Node exists: {possible_node}",
                )
            else:
                self.add_fail(
                    "COMPONENTS",
                    claim,
                    "Component could not be mapped to a knowledge-graph node.",
                )

    # =========================================================
    # COMPONENT / ENTITY RESOLUTION
    # =========================================================

    def _strip_entity_words(self, value):
        value = self.clean_markdown(value).strip()
        value = re.sub(r"\b(the|a|an|its|their|this|that)\b", " ", value, flags=re.IGNORECASE)
        value = re.sub(r"\b(class|method|module|file|function)\b", " ", value, flags=re.IGNORECASE)
        value = re.sub(r"\s+", " ", value).strip(" .,:;()")
        return value

    def resolve_component_node(self, claim):
        claim = self.clean_markdown(claim).strip()

        # Natural-language module descriptions such as
        # ``service (module containing the Service class)`` should
        # resolve to the actual module node ``module:service``.
        module_match = re.match(
            r"^([A-Za-z_][\w\.]*)\s*\(\s*module\s+containing\b",
            claim,
            flags=re.IGNORECASE,
        )
        if module_match:
            module_name = module_match.group(1)
            module_node = self.find_node_by_value(
                "module",
                module_name,
            )
            if module_node:
                return module_node

        if self.node_exists(claim):
            return claim

        prefixes = ("file:", "class:", "module:", "method:", "function:", "variable:")
        if claim.startswith(prefixes):
            return claim if self.node_exists(claim) else None

        # Files are intentionally resolved by basename.
        file_node = self.find_file(claim)
        if file_node:
            return file_node

        # Explicit class/method forms.
        for node_type in ("class", "method", "function", "module", "variable"):
            node = self.find_node_by_value(node_type, claim)
            if node:
                return node

        cleaned = self._strip_entity_words(claim)

        if cleaned and cleaned != claim:
            file_node = self.find_file(cleaned)
            if file_node:
                return file_node

            for node_type in ("class", "method", "function", "module", "variable"):
                node = self.find_node_by_value(node_type, cleaned)
                if node:
                    return node

        # Support short method names such as ``process`` when there is
        # exactly one method ending in ``.process``.
        if re.fullmatch(r"[A-Za-z_]\w*", cleaned or ""):
            matches = []
            for node_id in self.nodes:
                if not node_id.startswith("method:"):
                    continue
                method_name = node_id.split(":", 1)[1]
                if method_name.rsplit(".", 1)[-1] == cleaned:
                    matches.append(node_id)
            if len(matches) == 1:
                return matches[0]

        return None

    def resolve_target_node(self, target_text, preferred_types=None):
        target = self.clean_markdown(target_text).strip()
        target = re.sub(r"\b(and its|and the|its|the)\b", " ", target, flags=re.IGNORECASE)
        target = re.sub(r"\b(class|method|module|function)\b", " ", target, flags=re.IGNORECASE)
        target = re.sub(r"\s+", " ", target).strip(" .,:;()")

        # Preserve qualified method names before stripping words.
        candidates = [target, self.clean_markdown(target_text).strip()]

        preferred_types = preferred_types or ("class", "method", "function", "module")
        for candidate in candidates:
            for node_type in preferred_types:
                node = self.find_node_by_value(node_type, candidate)
                if node:
                    return node

        # Natural-language phrase: ``Service class``.
        base = self._strip_entity_words(target_text)
        for node_type in preferred_types:
            node = self.find_node_by_value(node_type, base)
            if node:
                return node

        return self.resolve_component_node(base)

    def split_targets(self, text):
        text = self.clean_markdown(text).strip()

        # Handle ``Service class and its process method`` as two entities.
        text = re.sub(r"\band its\b", " AND ", text, flags=re.IGNORECASE)
        text = re.sub(r"\band the\b", " AND ", text, flags=re.IGNORECASE)

        parts = re.split(r"\s+AND\s+|\s*,\s*", text, flags=re.IGNORECASE)
        return [p.strip(" .,:;") for p in parts if p.strip(" .,:;")]

    # =========================================================
    # DEPENDENCY VALIDATION
    # =========================================================

    def validate_dependencies(self, claims):

        for raw_claim in claims:
            claim = self.clean_markdown(raw_claim)
            if not claim:
                continue

            # -------------------------------------------------
            # IMPORT
            # -------------------------------------------------
            import_match = re.search(
                r"^(.+?)\s+imports\s+(.+?)(?:\.)?$",
                claim,
                re.IGNORECASE,
            )

            if import_match and re.search(r"\bmodules?\b", claim, re.IGNORECASE):
                source_name = import_match.group(1).strip()
                targets_text = re.sub(r"\bmodules?\b", "", import_match.group(2), flags=re.IGNORECASE).strip(" .")
                source_file = self.find_file(source_name)
                targets = self.split_targets(targets_text)
                evidence = []

                for target_name in targets:
                    target_module = self.find_node_by_value("module", self._strip_entity_words(target_name))
                    target_class = self.find_node_by_value("class", self._strip_entity_words(target_name))
                    verified = False

                    if source_file and target_module and self.has_edge(source_file, "IMPORTS", target_module):
                        evidence.append(self.edge_evidence(source_file, "IMPORTS", target_module))
                        verified = True
                    elif source_file and target_class and self.has_edge(source_file, "IMPORTS_CLASS", target_class):
                        evidence.append(self.edge_evidence(source_file, "IMPORTS_CLASS", target_class))
                        verified = True

                    if not verified:
                        evidence = []
                        break

                if evidence:
                    self.add_pass("DEPENDENCIES", claim, " | ".join(evidence))
                else:
                    self.add_fail("DEPENDENCIES", claim, "One or more imported modules/classes could not be verified.")
                continue

            # -------------------------------------------------
            # CALL
            # -------------------------------------------------
            call_match = re.search(
                r"^(.+?)\s+calls\s+(.+?)(?:\.)?$",
                claim,
                re.IGNORECASE,
            )

            if call_match:
                source_name = call_match.group(1).strip()
                targets_text = call_match.group(2).strip()
                source_file = self.find_file(source_name)

                # ``the Service class and its process method`` ->
                # ``Service class`` + ``process method``.
                targets = self.split_targets(targets_text)
                evidence = []

                for target_name in targets:
                    target_node = self.resolve_target_node(
                        target_name,
                        preferred_types=("class", "method", "function"),
                    )

                    # ``process method`` needs the qualified method identity.
                    if target_node is None:
                        short = self._strip_entity_words(target_name)
                        target_node = self.find_node_by_value("method", short)

                    if source_file and target_node and self.has_edge(source_file, "CALLS", target_node):
                        evidence.append(self.edge_evidence(source_file, "CALLS", target_node))
                    else:
                        evidence = []
                        break

                if evidence:
                    self.add_pass("DEPENDENCIES", claim, " | ".join(evidence))
                else:
                    self.add_fail("DEPENDENCIES", claim, "One or more calls could not be verified from the graph.")
                continue

            # -------------------------------------------------
            # DEFINES
            # -------------------------------------------------
            defines_match = re.search(
                r"^(.+?)\s+defines\s+(.+?)(?:\.)?$",
                claim,
                re.IGNORECASE,
            )

            if defines_match:
                source_name = defines_match.group(1).strip()
                definitions_text = defines_match.group(2).strip()
                source_file = self.find_file(source_name)

                class_match = re.search(
                    r"(?:the\s+)?([A-Za-z_]\w*)\s+class",
                    definitions_text,
                    re.IGNORECASE,
                )
                method_match = re.search(
                    r"(?:the\s+)?(?:[A-Za-z_]\w*\s+class\s+and\s+)?(?:its\s+)?([A-Za-z_]\w*)\s+method",
                    definitions_text,
                    re.IGNORECASE,
                )

                # Also support ``defines the Service class and its process``.
                if class_match is None:
                    class_match = re.search(
                        r"(?:the\s+)?([A-Za-z_]\w*)\s+class",
                        definitions_text,
                        re.IGNORECASE,
                    )

                class_name = class_match.group(1) if class_match else None
                method_name = method_match.group(1) if method_match else None

                class_node = self.find_node_by_value("class", class_name) if class_name else None
                method_node = None

                if method_name and class_name:
                    method_node = self.find_node_by_value(
                        "method",
                        f"{class_name}.{method_name}",
                    )

                if method_node is None and method_name:
                    method_node = self.resolve_target_node(
                        method_name,
                        preferred_types=("method",),
                    )

                evidence = []
                if source_file and class_node and self.has_edge(source_file, "DEFINES", class_node):
                    evidence.append(self.edge_evidence(source_file, "DEFINES", class_node))
                else:
                    evidence = []

                if evidence and class_node and method_node and self.has_edge(class_node, "DEFINES", method_node):
                    evidence.append(self.edge_evidence(class_node, "DEFINES", method_node))

                if evidence and len(evidence) == 2:
                    self.add_pass("DEPENDENCIES", claim, " | ".join(evidence))
                else:
                    self.add_fail("DEPENDENCIES", claim, "The file-to-class and/or class-to-method definition relationship could not be verified.")
                continue

            self.add_fail(
                "DEPENDENCIES",
                claim,
                "Dependency statement could not be mapped to a supported graph relationship.",
            )

    # =========================================================
    # ENTRY POINTS
    # =========================================================

    def validate_entry_points(self, claims):

        for claim in claims:

            claim = self.clean_markdown(claim)

            if claim:

                self.add_review(
                    "ENTRY POINTS",
                    claim,
                    (
                        "Entry-point status is an architectural "
                        "interpretation and is not explicitly "
                        "represented by the current "
                        "knowledge graph."
                    ),
                )

    # =========================================================
    # CORE COMPONENTS
    # =========================================================

    def validate_core_components(self, claims):

        for claim in claims:

            claim = self.clean_markdown(claim)

            if claim:

                self.add_review(
                    "CORE COMPONENTS",
                    claim,
                    (
                        "Core-component centrality is an "
                        "architectural interpretation rather "
                        "than an explicit graph relationship."
                    ),
                )

    # =========================================================
    # ARCHITECTURAL OBSERVATIONS
    # =========================================================

    def validate_observations(self, claims):

        for raw_claim in claims:

            claim = self.clean_markdown(raw_claim)

            if not claim:
                continue

            lower = claim.lower()

            # Architectural words such as ``central`` are interpretations,
            # not facts proven merely by a DEFINES relationship. Keep them
            # under human review even when the underlying graph relationship
            # exists.
            if re.search(
                r"\b(central|core|orchestrator|main|entry[- ]point|client[- ]server)\b",
                lower,
            ):
                self.add_review(
                    "ARCHITECTURAL OBSERVATIONS",
                    claim,
                    (
                        "The claim contains an architectural interpretation "
                        "that is not explicitly represented by the current "
                        "knowledge graph."
                    ),
                )
                continue

            # -------------------------------------------------
            # SERVICE CLASS
            # -------------------------------------------------

            if (
                "service class" in lower
                and (
                    "processing method" in lower
                    or "core functionality" in lower
                )
            ):

                class_node = (
                    self.find_node_by_value(
                        "class",
                        "Service",
                    )
                )

                method_node = (
                    self.find_node_by_value(
                        "method",
                        "Service.process",
                    )
                )

                if (
                    class_node
                    and method_node
                    and self.has_edge(
                        class_node,
                        "DEFINES",
                        method_node,
                    )
                ):

                    self.add_pass(
                        "ARCHITECTURAL OBSERVATIONS",
                        claim,
                        self.edge_evidence(
                            class_node,
                            "DEFINES",
                            method_node,
                        ),
                    )

                else:

                    self.add_fail(
                        "ARCHITECTURAL OBSERVATIONS",
                        claim,
                        (
                            "Service.process could not "
                            "be verified as a method "
                            "of Service."
                        ),
                    )

            # -------------------------------------------------
            # APPLICATION UTILIZES SERVICE
            # -------------------------------------------------

            elif (
                "application file" in lower
                and "service" in lower
                and "utilizes" in lower
            ):

                app_file = self.find_file(
                    "app.py"
                )

                class_node = (
                    self.find_node_by_value(
                        "class",
                        "Service",
                    )
                )

                method_node = (
                    self.find_node_by_value(
                        "method",
                        "Service.process",
                    )
                )

                evidence = []

                if (
                    app_file
                    and class_node
                    and self.has_edge(
                        app_file,
                        "CALLS",
                        class_node,
                    )
                ):
                    evidence.append(
                        self.edge_evidence(
                            app_file,
                            "CALLS",
                            class_node,
                        )
                    )

                if (
                    app_file
                    and method_node
                    and self.has_edge(
                        app_file,
                        "CALLS",
                        method_node,
                    )
                ):
                    evidence.append(
                        self.edge_evidence(
                            app_file,
                            "CALLS",
                            method_node,
                        )
                    )

                if evidence:

                    self.add_pass(
                        "ARCHITECTURAL OBSERVATIONS",
                        claim,
                        " | ".join(evidence),
                    )

                else:

                    self.add_fail(
                        "ARCHITECTURAL OBSERVATIONS",
                        claim,
                        (
                            "Application-to-Service "
                            "relationship could not "
                            "be verified."
                        ),
                    )

            # -------------------------------------------------
            # SEPARATION OF CONCERNS
            # -------------------------------------------------

            elif "separation of concerns" in lower:

                app_file = self.find_file(
                    "app.py"
                )

                service_file = self.find_file(
                    "service.py"
                )

                service_class = (
                    self.find_node_by_value(
                        "class",
                        "Service",
                    )
                )

                supported = (
                    app_file
                    and service_file
                    and service_class
                    and self.has_edge(
                        service_file,
                        "DEFINES",
                        service_class,
                    )
                )

                if supported:

                    self.add_pass(
                        "ARCHITECTURAL OBSERVATIONS",
                        claim,
                        self.edge_evidence(
                            service_file,
                            "DEFINES",
                            service_class,
                        ),
                    )

                else:

                    self.add_fail(
                        "ARCHITECTURAL OBSERVATIONS",
                        claim,
                        (
                            "The separation described "
                            "in the observation could "
                            "not be grounded in the "
                            "current graph."
                        ),
                    )

            else:

                self.add_review(
                    "ARCHITECTURAL OBSERVATIONS",
                    claim,
                    (
                        "Observation requires interpretation "
                        "beyond the explicit graph evidence."
                    ),
                )

    # =========================================================
    # NODE SEARCH
    # =========================================================

    def find_file(self, filename):

        filename = self.clean_markdown(filename).strip(" .,:;`\"")
        filename = re.sub(r"\b(the|file)\b", "", filename, flags=re.IGNORECASE).strip()

        filename_normalized = filename.replace("\\", "/").lower().rstrip("/")

        for node_id in self.nodes:
            if not node_id.startswith("file:"):
                continue

            path = node_id.split(":", 1)[1]
            normalized = path.replace("\\", "/").lower().rstrip("/")

            if normalized == filename_normalized or normalized.endswith("/" + filename_normalized):
                return node_id

        return None

    def find_node_by_value(self, node_type, value):

        if value is None:
            return None

        value = self.clean_markdown(value).strip(" .,:;`\"")
        value = re.sub(r"\b(the|a|an|its|their)\b", " ", value, flags=re.IGNORECASE)
        value = re.sub(r"\s+", " ", value).strip()

        prefix = node_type + ":"
        value_lower = value.lower()

        for node_id in self.nodes:
            if not node_id.startswith(prefix):
                continue

            node_value = node_id.split(":", 1)[1]
            if node_value.lower() == value_lower:
                return node_id

        return None

    # =========================================================
    # SCORE
    # =========================================================

    def calculate_score(self):

        total_hard = (
            self.hard_supported
            + self.hard_unsupported
        )

        if total_hard == 0:

            self.consistency_score = 100.0

        else:

            self.consistency_score = round(
                (
                    self.hard_supported
                    / total_hard
                )
                * 100,
                2,
            )

    # =========================================================
    # VALIDATE
    # =========================================================

    def validate(self):

        self.results = []

        self.hard_supported = 0
        self.hard_unsupported = 0
        self.review_count = 0
        self.consistency_score = 0.0

        self.load()

        sections = self.sections()

        self.validate_components(
            sections.get(
                "COMPONENTS",
                [],
            )
        )

        self.validate_dependencies(
            sections.get(
                "DEPENDENCIES",
                [],
            )
        )

        self.validate_entry_points(
            sections.get(
                "ENTRY POINTS",
                [],
            )
        )

        self.validate_core_components(
            sections.get(
                "CORE COMPONENTS",
                [],
            )
        )

        self.validate_observations(
            sections.get(
                "ARCHITECTURAL OBSERVATIONS",
                [],
            )
        )

        self.calculate_score()

        # -----------------------------------------------------
        # RETURN A CONSISTENT REPORT DICTIONARY
        # -----------------------------------------------------

        status = (
            "VERIFIED"
            if self.hard_unsupported == 0
            and self.review_count == 0
            else (
                "VERIFIED_WITH_REVIEW"
                if self.hard_unsupported == 0
                else "UNSUPPORTED_HARD_CLAIMS"
            )
        )

        report = {
            "validation": {
                "hard_claims_supported": self.hard_supported,
                "hard_claims_unsupported": self.hard_unsupported,
                "requires_review": self.review_count,
                "consistency_score": self.consistency_score,
                "status": status,
            },

            "statistics": {

                "supported": self.hard_supported,
                "unsupported": self.hard_unsupported,
                "review": self.review_count,
                "score": self.consistency_score,

                "hard_claims_supported": self.hard_supported,
                "hard_claims_unsupported": self.hard_unsupported,
                "requires_review": self.review_count,
                "consistency_score": self.consistency_score,
            },

            "results": self.results,
        }

        return report

    # =========================================================
    # PRINT REPORT
    # =========================================================

    def print_report(self, results=None):

        if results is None:
            results = {
                "validation": {
                    "hard_claims_supported":
                        self.hard_supported,

                    "hard_claims_unsupported":
                        self.hard_unsupported,

                    "requires_review":
                        self.review_count,

                    "consistency_score":
                        self.consistency_score,
                },

                "results": self.results,
            }

        report_results = results.get(
            "results",
            [],
        )

        validation = results.get(
            "validation",
            {},
        )

        print(
            "\n" + "=" * 70
        )

        print(
            "ARCHITECTURE VALIDATION REPORT"
        )

        print(
            "=" * 70
        )

        current_section = None

        for result in report_results:

            section = result["section"]

            if section != current_section:

                print(
                    "\n" + section
                )

                current_section = section

            status = result["status"]

            print(
                f"[{status}] "
                f"{result['claim']}"
            )

            if result.get("evidence"):

                print(
                    "       Evidence: "
                    f"{result['evidence']}"
                )

            if result.get("reason"):

                print(
                    "       Reason: "
                    f"{result['reason']}"
                )

        print(
            "\n" + "=" * 70
        )

        print(
            "VALIDATION STATISTICS"
        )

        print(
            "=" * 70
        )

        print(
            "Hard claims supported: "
            f"{validation.get('hard_claims_supported', 0)}"
        )

        print(
            "Hard claims unsupported: "
            f"{validation.get('hard_claims_unsupported', 0)}"
        )

        print(
            "Requires review: "
            f"{validation.get('requires_review', 0)}"
        )

        print(
            "Consistency score: "
            f"{validation.get('consistency_score', 0.0):.2f}%"
        )

    # =========================================================
    # SAVE REPORT
    # =========================================================

    def save_report(self, results=None):

        if results is None:

            results = {
                "validation": {
                    "hard_claims_supported":
                        self.hard_supported,

                    "hard_claims_unsupported":
                        self.hard_unsupported,

                    "requires_review":
                        self.review_count,

                    "consistency_score":
                        self.consistency_score,

                    "status": (
                        "VERIFIED"
                        if self.hard_unsupported == 0
                        and self.review_count == 0
                        else (
                            "VERIFIED_WITH_REVIEW"
                            if self.hard_unsupported == 0
                            else "UNSUPPORTED_HARD_CLAIMS"
                        )
                    ),
                },

                "results": self.results,
            }

        self.output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with open(
            self.output_path,
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                results,
                f,
                indent=4,
                ensure_ascii=False,
            )

        return self.output_path