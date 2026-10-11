import json
from pathlib import Path


class VerifiedArchitectureBuilder:

    def __init__(
        self,
        graph_path,
        analysis_path,
        validation_path,
        output_path=None,
    ):
        self.graph_path = Path(graph_path)
        self.analysis_path = Path(analysis_path)
        self.validation_path = Path(validation_path)

        if output_path is None:
            output_path = (
                self.validation_path.parent
                / "verified_architecture.json"
            )

        self.output_path = Path(output_path)

        self.graph = {}
        self.analysis = ""
        self.validation = {}

    # =========================================================
    # LOAD INPUTS
    # =========================================================

    def load(self):

        if not self.graph_path.exists():
            raise FileNotFoundError(
                f"Knowledge graph not found: "
                f"{self.graph_path}"
            )

        if not self.analysis_path.exists():
            raise FileNotFoundError(
                f"Architecture analysis not found: "
                f"{self.analysis_path}"
            )

        if not self.validation_path.exists():
            raise FileNotFoundError(
                f"Validation report not found: "
                f"{self.validation_path}"
            )

        with open(
            self.graph_path,
            "r",
            encoding="utf-8",
        ) as f:
            self.graph = json.load(f)

        with open(
            self.analysis_path,
            "r",
            encoding="utf-8",
        ) as f:
            self.analysis = f.read()

        with open(
            self.validation_path,
            "r",
            encoding="utf-8",
        ) as f:
            self.validation = json.load(f)

    # =========================================================
    # GRAPH HELPERS
    # =========================================================

    def get_nodes(self):

        nodes = self.graph.get(
            "nodes",
            [],
        )

        if isinstance(nodes, list):
            return nodes

        if isinstance(nodes, dict):
            result = []

            for node_id, attributes in nodes.items():

                if isinstance(attributes, dict):
                    node = dict(attributes)
                else:
                    node = {}

                node["id"] = str(node_id)

                result.append(node)

            return result

        return []

    def get_edges(self):

        edges = self.graph.get(
            "edges",
            [],
        )

        if not isinstance(edges, list):
            return []

        return edges

    # =========================================================
    # VERIFIED RESULTS
    # =========================================================

    def get_results(self):

        return self.validation.get(
            "results",
            [],
        )

    def get_passed_claims(self):

        return [
            result
            for result in self.get_results()
            if result.get("status") == "PASS"
        ]

    def get_review_claims(self):

        return [
            result
            for result in self.get_results()
            if result.get("status") == "REVIEW"
        ]

    def get_failed_claims(self):

        return [
            result
            for result in self.get_results()
            if result.get("status") == "FAIL"
        ]

    # =========================================================
    # COMPONENTS
    # =========================================================

    def build_components(self):

        components = {
            "files": [],
            "modules": [],
            "classes": [],
            "methods": [],
            "variables": [],
        }

        for node in self.get_nodes():

            node_id = str(
                node.get("id", "")
            )

            if ":" not in node_id:
                continue

            node_type, value = node_id.split(
                ":",
                1,
            )

            if node_type == "file":
                components["files"].append(node_id)

            elif node_type == "module":
                components["modules"].append(node_id)

            elif node_type == "class":
                components["classes"].append(node_id)

            elif node_type == "method":
                components["methods"].append(node_id)

            elif node_type == "variable":
                components["variables"].append(node_id)

        for key in components:
            components[key] = sorted(
                components[key]
            )

        return components

    # =========================================================
    # RELATIONSHIPS
    # =========================================================

    def build_relationships(self):

        relationships = []

        for edge in self.get_edges():

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

            if not source or not target or not relation:
                continue

            relationships.append(
                {
                    "source": str(source),
                    "relation": str(relation),
                    "target": str(target),
                }
            )

        relationships.sort(
            key=lambda item: (
                item["source"],
                item["relation"],
                item["target"],
            )
        )

        return relationships

    # =========================================================
    # VERIFIED CLAIMS
    # =========================================================

    def build_verified_claims(self):

        verified = []

        for result in self.get_passed_claims():

            verified.append(
                {
                    "section": result.get(
                        "section"
                    ),
                    "claim": result.get(
                        "claim"
                    ),
                    "evidence": result.get(
                        "evidence"
                    ),
                }
            )

        return verified

    # =========================================================
    # REVIEW ITEMS
    # =========================================================

    def build_review_items(self):

        reviews = []

        for result in self.get_review_claims():

            reviews.append(
                {
                    "section": result.get(
                        "section"
                    ),
                    "claim": result.get(
                        "claim"
                    ),
                    "reason": result.get(
                        "reason"
                    ),
                }
            )

        return reviews

    # =========================================================
    # BUILD VERIFIED ARCHITECTURE
    # =========================================================

    def build(self):

        self.load()

        validation_info = self.validation.get(
            "validation",
            {},
        )

        hard_supported = validation_info.get(
            "hard_claims_supported",
            0,
        )

        hard_unsupported = validation_info.get(
            "hard_claims_unsupported",
            0,
        )

        requires_review = validation_info.get(
            "requires_review",
            0,
        )

        consistency_score = validation_info.get(
            "consistency_score",
            0.0,
        )

        if hard_unsupported == 0:

            if requires_review > 0:
                verification_status = (
                    "VERIFIED_WITH_REVIEW"
                )
            else:
                verification_status = "VERIFIED"

        else:

            verification_status = (
                "NOT_VERIFIED"
            )

        architecture = {
            "metadata": {
                "generator": (
                    "CIAO - Code In Architecture Out"
                ),
                "artifact": (
                    "Verified Architecture"
                ),
                "version": "1.0",
            },

            "verification": {
                "status": verification_status,
                "consistency_score": (
                    consistency_score
                ),
                "hard_claims_supported": (
                    hard_supported
                ),
                "hard_claims_unsupported": (
                    hard_unsupported
                ),
                "requires_review": (
                    requires_review
                ),
            },

            "components": (
                self.build_components()
            ),

            "relationships": (
                self.build_relationships()
            ),

            "verified_claims": (
                self.build_verified_claims()
            ),

            "review_items": (
                self.build_review_items()
            ),

            "source_artifacts": {
                "knowledge_graph": str(
                    self.graph_path
                ),
                "architecture_analysis": str(
                    self.analysis_path
                ),
                "validation_report": str(
                    self.validation_path
                ),
            },
        }

        return architecture

    # =========================================================
    # SAVE
    # =========================================================

    def save(self, architecture):

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
                architecture,
                f,
                indent=4,
                ensure_ascii=False,
            )

        return self.output_path


# =============================================================
# DIRECT EXECUTION
# =============================================================

if __name__ == "__main__":

    base = Path(__file__).resolve().parents[2]

    graph_path = (
        base
        / "output"
        / "graph"
        / "repository_graph.json"
    )

    analysis_path = (
        base
        / "output"
        / "docs"
        / "architecture_analysis.txt"
    )

    validation_path = (
        base
        / "output"
        / "docs"
        / "architecture_validation.json"
    )

    output_path = (
        base
        / "output"
        / "docs"
        / "verified_architecture.json"
    )

    builder = VerifiedArchitectureBuilder(
        graph_path=graph_path,
        analysis_path=analysis_path,
        validation_path=validation_path,
        output_path=output_path,
    )

    architecture = builder.build()

    saved_path = builder.save(
        architecture
    )

    print("=" * 70)
    print("STEP 9.2 - VERIFIED ARCHITECTURE")
    print("=" * 70)

    print()
    print(
        f"Verification status: "
        f"{architecture['verification']['status']}"
    )

    print(
        f"Consistency score: "
        f"{architecture['verification']['consistency_score']:.2f}%"
    )

    print(
        f"Hard claims supported: "
        f"{architecture['verification']['hard_claims_supported']}"
    )

    print(
        f"Hard claims unsupported: "
        f"{architecture['verification']['hard_claims_unsupported']}"
    )

    print(
        f"Requires review: "
        f"{architecture['verification']['requires_review']}"
    )

    print()
    print(
        f"Components: "
        f"{sum(len(v) for v in architecture['components'].values())}"
    )

    print(
        f"Relationships: "
        f"{len(architecture['relationships'])}"
    )

    print(
        f"Verified claims: "
        f"{len(architecture['verified_claims'])}"
    )

    print(
        f"Review items: "
        f"{len(architecture['review_items'])}"
    )

    print()
    print(
        f"Verified architecture saved to:"
    )
    print(saved_path)

    print()
    print("=" * 70)
    print("STEP 9.2 STATUS")
    print("=" * 70)
    print("COMPLETED")