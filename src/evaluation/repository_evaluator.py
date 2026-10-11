import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Set

PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.parser.code_analyzer import CodeAnalyzer
from src.graph.knowledge_graph import RepositoryKnowledgeGraph


class RepositoryEvaluator:
    """
    Generic evaluator for CIAO.

    Compares static analyzer information with the repository
    knowledge graph.

    This evaluator contains no repository-specific names.
    """

    def __init__(self, repository_path: str | Path):
        self.repository_path = Path(repository_path).resolve()

        if not self.repository_path.exists():
            raise FileNotFoundError(
                f"Repository path does not exist: {self.repository_path}"
            )

        if not self.repository_path.is_dir():
            raise NotADirectoryError(
                f"Repository path is not a directory: {self.repository_path}"
            )

        self.analyzer = CodeAnalyzer(self.repository_path)
        self.graph_builder = RepositoryKnowledgeGraph(
            self.repository_path
        )

        self.file_results: List[Dict[str, Any]] = []
        self.graph_data: Dict[str, Any] = {
            "nodes": [],
            "edges": [],
        }

    # ==============================================================
    # STATIC ANALYZER
    # ==============================================================

    def run_analyzer(self) -> List[Dict[str, Any]]:
        results = self.analyzer.analyze_repository()

        if not isinstance(results, list):
            raise TypeError(
                "CodeAnalyzer.analyze_repository() must return "
                "a list of file-analysis dictionaries."
            )

        self.file_results = [
            result
            for result in results
            if isinstance(result, dict)
        ]

        return self.file_results

    # ==============================================================
    # KNOWLEDGE GRAPH
    # ==============================================================

    def run_graph_builder(self) -> Dict[str, Any]:
        result = self.graph_builder.build()

        if not isinstance(result, dict):
            raise TypeError(
                "RepositoryKnowledgeGraph.build() must return "
                "a dictionary."
            )

        nodes = result.get("nodes", [])
        edges = result.get("edges", [])

        if not isinstance(nodes, list):
            raise TypeError(
                "Knowledge graph 'nodes' must be a list."
            )

        if not isinstance(edges, list):
            raise TypeError(
                "Knowledge graph 'edges' must be a list."
            )

        self.graph_data = {
            "nodes": nodes,
            "edges": edges,
        }

        return self.graph_data

    # ==============================================================
    # ANALYZER HELPERS
    # ==============================================================

    def _collect_lists(
        self,
        field_name: str,
    ) -> List[Any]:

        values: List[Any] = []

        for result in self.file_results:
            value = result.get(field_name, [])

            if isinstance(value, list):
                values.extend(value)

        return values

    def _collect_unique_imports(self) -> Set[str]:
        imports: Set[str] = set()

        for item in self._collect_lists("imports"):

            if isinstance(item, str):
                imports.add(item)

            elif isinstance(item, dict):

                for key in (
                    "module",
                    "name",
                    "imported_as",
                ):
                    value = item.get(key)

                    if isinstance(value, str):
                        imports.add(value)
                        break

        return imports

    # ==============================================================
    # ANALYZER METRICS
    # ==============================================================

    def analyzer_metrics(self) -> Dict[str, int]:

        return {
            "files": len(self.file_results),

            "classes": len(
                self._collect_lists("classes")
            ),

            "methods": len(
                self._collect_lists("methods")
            ),

            "functions": len(
                self._collect_lists("functions")
            ),

            "nested_functions": len(
                self._collect_lists("nested_functions")
            ),

            "variables": len(
                self._collect_lists("variables")
            ),

            "imports": len(
                self._collect_unique_imports()
            ),

            "calls": len(
                self._collect_lists("calls")
            ),

            "call_details": len(
                self._collect_lists("call_details")
            ),

            "resolved_calls": len(
                self._collect_lists("resolved_calls")
            ),

            "function_relationships": len(
                self._collect_lists(
                    "function_relationships"
                )
            ),

            "assigned_from": len(
                self._collect_lists("assigned_from")
            ),
        }

    # ==============================================================
    # ANALYZER CALL TYPES
    # ==============================================================

    def call_type_metrics(self) -> Dict[str, int]:

        counts: Dict[str, int] = {}

        for call in self._collect_lists(
            "call_details"
        ):

            if not isinstance(call, dict):
                continue

            call_type = call.get("type", "unknown")

            if not isinstance(call_type, str):
                call_type = "unknown"

            counts[call_type] = (
                counts.get(call_type, 0) + 1
            )

        return dict(
            sorted(
                counts.items()
            )
        )

    # ==============================================================
    # GRAPH NODE METRICS
    # ==============================================================

    def graph_metrics(self) -> Dict[str, int]:

        nodes = self.graph_data["nodes"]
        edges = self.graph_data["edges"]

        node_counts: Dict[str, int] = {}

        for node in nodes:

            if not isinstance(node, dict):
                continue

            node_type = node.get(
                "type",
                "unknown",
            )

            if not isinstance(node_type, str):
                node_type = "unknown"

            node_counts[node_type] = (
                node_counts.get(
                    node_type,
                    0,
                ) + 1
            )

        relationship_count = 0

        for edge in edges:

            if not isinstance(edge, dict):
                continue

            if edge.get("relationship") is not None:
                relationship_count += 1

        return {
            "nodes": len(nodes),
            "edges": len(edges),

            "files": node_counts.get(
                "file",
                0,
            ),

            "modules": node_counts.get(
                "module",
                0,
            ),

            "classes": node_counts.get(
                "class",
                0,
            ),

            "methods": node_counts.get(
                "method",
                0,
            ),

            "functions": node_counts.get(
                "function",
                0,
            ),

            "nested_functions": sum(
                1
                for node in nodes
                if (
                    isinstance(node, dict)
                    and node.get("type") == "function"
                    and node.get("nested") is True
                )
            ),

            "variables": node_counts.get(
                "variable",
                0,
            ),

            "unknown_nodes": node_counts.get(
                "unknown",
                0,
            ),

            "relationships": relationship_count,
        }

    # ==============================================================
    # GRAPH RELATIONSHIP TYPES
    # ==============================================================

    def graph_relationship_metrics(
        self,
    ) -> Dict[str, int]:

        counts: Dict[str, int] = {}

        for edge in self.graph_data["edges"]:

            if not isinstance(edge, dict):
                continue

            relationship = edge.get(
                "relationship"
            )

            if not isinstance(
                relationship,
                str,
            ):
                continue

            counts[relationship] = (
                counts.get(
                    relationship,
                    0,
                ) + 1
            )

        return dict(
            sorted(
                counts.items()
            )
        )

    # ==============================================================
    # EXTERNAL DEPENDENCIES
    # ==============================================================

    def external_dependency_metrics(
        self,
    ) -> Dict[str, Any]:

        modules: Set[str] = set()

        for node in self.graph_data["nodes"]:

            if not isinstance(node, dict):
                continue

            if (
                node.get("type") == "module"
                and node.get("external") is True
            ):

                name = node.get("name")

                if isinstance(name, str):
                    modules.add(name)

        return {
            "count": len(modules),
            "modules": sorted(modules),
        }

    # ==============================================================
    # CALL RESOLUTION
    # ==============================================================

    def resolution_metrics(
        self,
    ) -> Dict[str, Any]:

        call_details = self._collect_lists(
            "call_details"
        )

        resolved_calls = self._collect_lists(
            "resolved_calls"
        )

        project_relationships: Set[tuple[str, str]] = set()
        resolved_relationships: Set[tuple[str, str]] = set()

        for call in call_details:
            if not isinstance(call, dict) or call.get("type") != "project":
                continue

            caller = call.get("caller")
            callee = call.get("callee")

            if isinstance(caller, str) and isinstance(callee, str):
                project_relationships.add(
                    (caller.strip(), callee.strip())
                )

        for call in resolved_calls:
            if not isinstance(call, dict):
                continue

            caller = call.get("caller")
            callee = call.get("called_symbol") or call.get("resolved_symbol")

            if isinstance(caller, str) and isinstance(callee, str):
                resolved_relationships.add(
                    (caller.strip(), callee.strip())
                )

        # Match by caller and callee. A nested symbol such as outer.inner
        # also matches a locally recorded inner call from outer.
        matched_relationships: Set[tuple[str, str]] = set()

        for caller, callee in project_relationships:
            for resolved_caller, resolved_callee in resolved_relationships:
                if caller == resolved_caller and (
                    callee == resolved_callee
                    or resolved_callee.endswith("." + callee)
                ):
                    matched_relationships.add((caller, callee))
                    break

        project_call_count = len(project_relationships)
        resolved_project_call_count = len(matched_relationships)

        rate = (
            1.0
            if project_call_count == 0
            else resolved_project_call_count / project_call_count
        )

        return {
            "project_calls": project_call_count,
            "resolved_project_calls": resolved_project_call_count,
            "resolution_rate": rate,
        }

    # ==============================================================
    # ENTITY COVERAGE
    # ==============================================================

    def entity_coverage(
        self,
    ) -> Dict[str, float]:

        analyzer = self.analyzer_metrics()
        graph = self.graph_metrics()

        pairs = {
            "files": (
                analyzer["files"],
                graph["files"],
            ),

            "classes": (
                analyzer["classes"],
                graph["classes"],
            ),

            "methods": (
                analyzer["methods"],
                graph["methods"],
            ),

            "functions": (
                analyzer["functions"],
                graph["functions"]
                - graph["nested_functions"],
            ),

            "nested_functions": (
                analyzer["nested_functions"],
                graph["nested_functions"],
            ),

            "variables": (
                analyzer["variables"],
                graph["variables"],
            ),
        }

        coverage: Dict[str, float] = {}

        for name, (
            analyzer_count,
            graph_count,
        ) in pairs.items():

            if analyzer_count == 0:
                coverage[name] = 1.0
            else:
                coverage[name] = min(
                    graph_count
                    / analyzer_count,
                    1.0,
                )

        return coverage

    # ==============================================================
    # RELATIONSHIP COVERAGE
    # ==============================================================

    def relationship_coverage(
        self,
    ) -> Dict[str, Any]:

        analyzer = self.analyzer_metrics()
        graph_relationships = (
            self.graph_relationship_metrics()
        )

        # Compare imports where both sources provide a comparable count.
        analyzer_imports = analyzer[
            "imports"
        ]

        analyzer_call_details = analyzer[
            "call_details"
        ]

        graph_imports = (
            graph_relationships.get(
                "IMPORTS",
                0,
            )
        )

        graph_calls = (
            graph_relationships.get(
                "CALLS",
                0,
            )
        )

        import_coverage = (
            1.0
            if analyzer_imports == 0
            else min(
                graph_imports
                / analyzer_imports,
                1.0,
            )
        )

        return {
            "analyzer_imports": analyzer_imports,
            "graph_imports": graph_imports,
            "import_coverage": import_coverage,

            # These counts describe different observations and are not
            # directly comparable as a coverage ratio.
            "analyzer_call_details": analyzer_call_details,
            "graph_calls": graph_calls,

            "overall_coverage": import_coverage,
        }

    # ==============================================================
    # FULL EVALUATION
    # ==============================================================

    def evaluate(
        self,
    ) -> Dict[str, Any]:

        self.run_analyzer()
        self.run_graph_builder()

        return {
            "repository": str(
                self.repository_path
            ),

            "analyzer": (
                self.analyzer_metrics()
            ),

            "analyzer_call_types": (
                self.call_type_metrics()
            ),

            "graph": (
                self.graph_metrics()
            ),

            "graph_relationship_types": (
                self.graph_relationship_metrics()
            ),

            "external_dependencies": (
                self.external_dependency_metrics()
            ),

            "resolution": (
                self.resolution_metrics()
            ),

            "entity_coverage": (
                self.entity_coverage()
            ),

            "relationship_coverage": (
                self.relationship_coverage()
            ),
        }

    # ==============================================================
    # REPORT
    # ==============================================================

    def print_report(
        self,
        result: Dict[str, Any],
    ) -> None:

        print("=" * 72)
        print(
            "CIAO GENERIC REPOSITORY EVALUATION"
        )
        print("=" * 72)

        print(
            f"Repository: "
            f"{self.repository_path.name}"
        )

        print(
            f"Path:       "
            f"{self.repository_path}"
        )

        print()
        print("STATIC ANALYZER")
        print("-" * 72)

        for key, value in result[
            "analyzer"
        ].items():

            print(
                f"{key:26}: {value}"
            )

        print()
        print("CALL TYPES")
        print("-" * 72)

        for key, value in result[
            "analyzer_call_types"
        ].items():

            print(
                f"{key:26}: {value}"
            )

        print()
        print("KNOWLEDGE GRAPH")
        print("-" * 72)

        for key, value in result[
            "graph"
        ].items():

            print(
                f"{key:26}: {value}"
            )

        print()
        print(
            "GRAPH RELATIONSHIP TYPES"
        )
        print("-" * 72)

        for key, value in result[
            "graph_relationship_types"
        ].items():

            print(
                f"{key:26}: {value}"
            )

        print()
        print("EXTERNAL DEPENDENCIES")
        print("-" * 72)

        dependencies = result[
            "external_dependencies"
        ]

        print(
            f"count                     : "
            f"{dependencies['count']}"
        )

        for module in dependencies[
            "modules"
        ]:

            print(
                f"  - {module}"
            )

        print()
        print("CALL RESOLUTION")
        print("-" * 72)

        resolution = result[
            "resolution"
        ]

        print(
            f"project calls             : "
            f"{resolution['project_calls']}"
        )

        print(
            f"resolved project calls    : "
            f"{resolution['resolved_project_calls']}"
        )

        print(
            f"resolution rate           : "
            f"{resolution['resolution_rate'] * 100:.2f}%"
        )

        print()
        print("ENTITY COVERAGE")
        print("-" * 72)

        for key, value in result[
            "entity_coverage"
        ].items():

            print(
                f"{key:26}: "
                f"{value * 100:.2f}%"
            )

        print()
        print("RELATIONSHIP COVERAGE")
        print("-" * 72)

        relationship = result[
            "relationship_coverage"
        ]

        print(
            f"imports analyzer         : "
            f"{relationship['analyzer_imports']}"
        )

        print(
            f"imports graph            : "
            f"{relationship['graph_imports']}"
        )

        print(
            f"import coverage          : "
            f"{relationship['import_coverage'] * 100:.2f}%"
        )

        print(
            f"call details analyzer   : "
            f"{relationship['analyzer_call_details']}"
        )

        print(
            f"CALLS graph edges       : "
            f"{relationship['graph_calls']}"
        )

        print(
            f"overall relationship    : "
            f"{relationship['overall_coverage'] * 100:.2f}%"
        )

        print()
        print("STATUS")
        print("-" * 72)

        entity_pass = all(
            value >= 1.0
            for value in result[
                "entity_coverage"
            ].values()
        )

        relationship_pass = (
            relationship[
                "overall_coverage"
            ] >= 1.0
        )

        resolution_pass = (
            resolution[
                "resolution_rate"
            ] >= 1.0
        )

        print(
            "Entity coverage        : "
            + (
                "PASS"
                if entity_pass
                else "REVIEW"
            )
        )

        print(
            "Relationship coverage  : "
            + (
                "PASS"
                if relationship_pass
                else "REVIEW"
            )
        )

        print(
            "Call resolution        : "
            + (
                "PASS"
                if resolution_pass
                else "REVIEW"
            )
        )

        print("=" * 72)

    # ==============================================================
    # JSON EXPORT
    # ==============================================================

    @staticmethod
    def save_json(
        result: Dict[str, Any],
        output_path: str | Path,
    ) -> Path:

        output_path = Path(
            output_path
        )

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with output_path.open(
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                result,
                file,
                indent=2,
            )

        return output_path


def evaluate_repository(
    repository_path: str | Path,
    output_path: str | Path | None = None,
) -> Dict[str, Any]:

    evaluator = RepositoryEvaluator(
        repository_path
    )

    result = evaluator.evaluate()

    evaluator.print_report(
        result
    )

    if output_path is not None:

        saved_path = (
            evaluator.save_json(
                result,
                output_path
            )
        )

        print()
        print(
            f"Evaluation JSON: "
            f"{saved_path}"
        )

    return result


if __name__ == "__main__":

    if len(sys.argv) < 2:

        print(
            "Usage:"
        )

        print(
            "python -u "
            "src\\evaluation\\repository_evaluator.py "
            "<repository_path> "
            "[output_json]"
        )

        sys.exit(1)

    repository = sys.argv[1]

    output = (
        sys.argv[2]
        if len(sys.argv) >= 3
        else None
    )

    evaluate_repository(
        repository,
        output
    )