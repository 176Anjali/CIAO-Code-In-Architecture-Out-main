import json
from pathlib import Path


class Arc42Generator:

    def __init__(self, verified_architecture_path, output_path=None):
        self.verified_architecture_path = Path(
            verified_architecture_path
        )

        if output_path is None:
            output_path = (
                self.verified_architecture_path.parent
                / "arc42_document.md"
            )

        self.output_path = Path(output_path)

        self.architecture = {}

    def load(self):
        if not self.verified_architecture_path.exists():
            raise FileNotFoundError(
                f"Verified architecture not found: "
                f"{self.verified_architecture_path}"
            )

        with open(
            self.verified_architecture_path,
            "r",
            encoding="utf-8",
        ) as f:
            self.architecture = json.load(f)

    def get_verification(self):
        return self.architecture.get("verification", {})

    def get_components(self):
        return self.architecture.get("components", {})

    def get_relationships(self):
        return self.architecture.get("relationships", [])

    def get_verified_claims(self):
        return self.architecture.get("verified_claims", [])

    def get_review_items(self):
        return self.architecture.get("review_items", [])

    def get_component_names(self, component_type):
        components = self.get_components()
        values = components.get(component_type, [])

        if not isinstance(values, list):
            return []

        return values

    def clean_node_name(self, node_id):
        """
        Convert internal graph node identifiers into readable names.
        """
        if not isinstance(node_id, str):
            return str(node_id)

        if ":" not in node_id:
            return node_id

        node_type, value = node_id.split(":", 1)

        if node_type == "file":
            return Path(value).name

        if node_type == "class":
            return value

        if node_type == "method":
            if "." in value:
                class_name, method_name = value.rsplit(".", 1)
                return f"{class_name}.{method_name}"
            return value

        if node_type == "module":
            return value

        if node_type == "variable":
            return value.split(":")[-1]

        return value

    def relationship_text(self, relationship):
        source = self.clean_node_name(
            relationship.get("source", "")
        )
        relation = relationship.get("relation", "")
        target = self.clean_node_name(
            relationship.get("target", "")
        )

        relation_map = {
            "CALLS": "calls",
            "IMPORTS": "imports",
            "DEFINES": "defines",
            "INSTANCE_OF": "is an instance of",
            "INHERITS": "inherits from",
            "USES": "uses",
        }

        readable_relation = relation_map.get(
            relation,
            relation.lower(),
        )

        return f"{source} {readable_relation} {target}."

    def build_overview(self):
        verification = self.get_verification()

        status = verification.get(
            "status",
            "UNKNOWN",
        )

        score = verification.get(
            "consistency_score",
            0.0,
        )

        supported = verification.get(
            "hard_claims_supported",
            0,
        )

        unsupported = verification.get(
            "hard_claims_unsupported",
            0,
        )

        review = verification.get(
            "requires_review",
            0,
        )

        lines = []

        lines.append(
            "CIAO-generated architecture documentation "
            "based on the verified repository architecture."
        )

        lines.append("")

        lines.append(
            f"**Verification status:** `{status}`"
        )

        lines.append(
            f"**Consistency score:** `{score:.2f}%`"
        )

        lines.append(
            f"**Verified claims:** `{supported}`"
        )

        lines.append(
            f"**Unsupported hard claims:** `{unsupported}`"
        )

        lines.append(
            f"**Items requiring review:** `{review}`"
        )

        return "\n".join(lines)

    def build_context_and_scope(self):
        files = self.get_component_names("files")

        lines = []

        lines.append(
            "The documented architecture is derived from "
            "the verified architecture artifact."
        )

        lines.append("")

        lines.append("### Analyzed Files")

        if files:
            for file_node in files:
                lines.append(
                    f"- `{self.clean_node_name(file_node)}`"
                )
        else:
            lines.append(
                "- No file components were verified."
            )

        return "\n".join(lines)

    def build_building_blocks(self):
        components = self.get_components()

        lines = []

        lines.append("### Files")

        files = components.get("files", [])

        if files:
            for node in files:
                lines.append(
                    f"- `{self.clean_node_name(node)}`"
                )
        else:
            lines.append("- None verified.")

        lines.append("")

        lines.append("### Modules")

        modules = components.get("modules", [])

        # A knowledge graph can contain module-named import aliases such
        # as ``module:Service`` even when ``Service`` is actually a class.
        # Do not duplicate verified classes in the Modules section.
        class_names = {
            self.clean_node_name(node)
            for node in components.get("classes", [])
        }

        filtered_modules = [
            node
            for node in modules
            if self.clean_node_name(node) not in class_names
        ]

        if filtered_modules:
            for node in filtered_modules:
                lines.append(
                    f"- `{self.clean_node_name(node)}`"
                )
        else:
            lines.append("- None verified.")

        lines.append("")

        lines.append("### Classes")

        classes = components.get("classes", [])

        if classes:
            for node in classes:
                lines.append(
                    f"- `{self.clean_node_name(node)}`"
                )
        else:
            lines.append("- None verified.")

        lines.append("")

        lines.append("### Methods")

        methods = components.get("methods", [])

        if methods:
            for node in methods:
                lines.append(
                    f"- `{self.clean_node_name(node)}`"
                )
        else:
            lines.append("- None verified.")

        lines.append("")

        lines.append("### Variables")

        variables = components.get("variables", [])

        if variables:
            for node in variables:
                lines.append(
                    f"- `{self.clean_node_name(node)}`"
                )
        else:
            lines.append("- None verified.")

        return "\n".join(lines)

    def build_relationships(self):
        relationships = self.get_relationships()

        lines = []

        if not relationships:
            return "No verified relationships were found."

        for relationship in relationships:
            lines.append(
                f"- {self.relationship_text(relationship)}"
            )

        return "\n".join(lines)

    def build_architecture_observations(self):
        """
        Do not promote architectural interpretations to verified facts.

        Architectural observations are interpretation-heavy and are
        therefore documented as review items. Direct code relationships
        remain documented in the Runtime View.
        """
        review_items = self.get_review_items()

        lines = []

        observations = [
            item
            for item in review_items
            if item.get("section")
            == "ARCHITECTURAL OBSERVATIONS"
        ]

        if not observations:
            return (
                "No architectural observations require review."
            )

        lines.append(
            "The following architectural observations are "
            "interpretations and require review rather than being "
            "treated as verified facts:"
        )
        lines.append("")

        for item in observations:
            claim = item.get("claim", "")
            reason = item.get("reason", "")

            lines.append(f"- **Review:** {claim}")

            if reason:
                lines.append(
                    f"  - Reason: {reason}"
                )

        return "\n".join(lines)

    def build_constraints_and_uncertainties(self):
        review_items = self.get_review_items()

        lines = []

        lines.append(
            "CIAO does not treat architectural interpretations "
            "that are not explicitly supported by the knowledge "
            "graph as verified facts."
        )

        lines.append("")

        if review_items:
            lines.append(
                "The following items require architectural review:"
            )

            for item in review_items:
                claim = item.get("claim", "")
                reason = item.get("reason", "")

                lines.append(
                    f"- **Review:** {claim}"
                )

                if reason:
                    lines.append(
                        f"  - Reason: {reason}"
                    )
        else:
            lines.append(
                "No architectural review items were recorded."
            )

        return "\n".join(lines)

    def build_document(self):
        self.load()

        document = []

        document.append(
            "# arc42 Architecture Documentation"
        )

        document.append("")

        document.append(
            "> Generated by CIAO — Code In Architecture Out"
        )

        document.append("")

        document.append(
            "## 1. Introduction and Goals"
        )

        document.append("")

        document.append(
            self.build_overview()
        )

        document.append("")

        document.append(
            "## 2. Architecture Constraints"
        )

        document.append("")

        document.append(
            "The architecture documentation is constrained "
            "by the verified repository knowledge graph."
        )

        document.append("")

        document.append(
            "Only components and relationships supported by "
            "the verified architecture are documented as "
            "verified facts."
        )

        document.append("")

        document.append(
            "## 3. Context and Scope"
        )

        document.append("")

        document.append(
            self.build_context_and_scope()
        )

        document.append("")

        document.append(
            "## 4. Solution Strategy"
        )

        document.append("")

        document.append(
            "The repository architecture is represented through "
            "verified files, modules, classes, methods, variables, "
            "and their statically extracted relationships."
        )

        document.append("")

        document.append(
            "Architectural interpretations are not promoted to "
            "verified facts unless they are explicitly supported "
            "by the verified architecture evidence."
        )

        document.append("")

        document.append(
            "## 5. Building Block View"
        )

        document.append("")

        document.append(
            self.build_building_blocks()
        )

        document.append("")

        document.append(
            "## 6. Runtime View"
        )

        document.append("")

        document.append(
            "The following interactions are directly supported "
            "by the verified architecture:"
        )

        document.append("")

        document.append(
            self.build_relationships()
        )

        document.append("")

        document.append(
            "## 7. Deployment View"
        )

        document.append("")

        document.append(
            "No deployment topology is inferred unless it is "
            "explicitly represented in the verified architecture."
        )

        document.append("")

        document.append(
            "## 8. Cross-Cutting Concepts"
        )

        document.append("")

        document.append(
            self.build_architecture_observations()
        )

        document.append("")

        document.append(
            "## 9. Architecture Decisions"
        )

        document.append("")

        document.append(
            "The documented architecture follows the relationships "
            "verified from the repository knowledge graph."
        )

        document.append("")

        document.append(
            "No additional architectural technology or design "
            "decision is invented by this generator."
        )

        document.append("")

        document.append(
            "## 10. Quality Requirements"
        )

        document.append("")

        document.append(
            "Architecture consistency is measured by the CIAO "
            "architecture validator."
        )

        document.append("")

        verification = self.get_verification()

        document.append(
            f"- Consistency score: "
            f"`{verification.get('consistency_score', 0.0):.2f}%`"
        )

        document.append(
            f"- Unsupported hard claims: "
            f"`{verification.get('hard_claims_unsupported', 0)}`"
        )

        document.append(
            f"- Review items: "
            f"`{verification.get('requires_review', 0)}`"
        )

        document.append("")

        document.append(
            "## 11. Risks and Technical Debt"
        )

        document.append("")

        document.append(
            "The current architecture model is limited to "
            "relationships that can be extracted and verified "
            "by the CIAO static analysis pipeline."
        )

        document.append("")

        document.append(
            "Dynamic behavior, reflection, runtime dependency "
            "resolution, or other behavior not represented in "
            "the extracted knowledge graph must not be treated "
            "as verified architecture."
        )

        document.append("")

        document.append(
            "## 12. Glossary"
        )

        document.append("")

        document.append(
            "- **Knowledge Graph:** Structured representation "
            "of repository components and relationships."
        )

        document.append(
            "- **Verified Architecture:** Architecture accepted "
            "after consistency validation against the knowledge graph."
        )

        document.append(
            "- **Review Item:** An architectural statement that "
            "cannot be established directly from the current "
            "verified evidence."
        )

        document.append("")

        document.append(
            "## Verification Notes"
        )

        document.append("")

        document.append(
            self.build_constraints_and_uncertainties()
        )

        return "\n".join(document)

    def save(self, document):
        self.output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with open(
            self.output_path,
            "w",
            encoding="utf-8",
        ) as f:
            f.write(document)

        return self.output_path


if __name__ == "__main__":
    base = Path(__file__).resolve().parents[2]

    verified_architecture_path = (
        base
        / "output"
        / "docs"
        / "verified_architecture.json"
    )

    output_path = (
        base
        / "output"
        / "docs"
        / "arc42_document.md"
    )

    generator = Arc42Generator(
        verified_architecture_path=verified_architecture_path,
        output_path=output_path,
    )

    document = generator.build_document()
    saved_path = generator.save(document)

    print("=" * 70)
    print("STEP 9.3 - ARC42 DOCUMENTATION GENERATOR")
    print("=" * 70)

    print()
    print("Source:")
    print(verified_architecture_path)

    print()
    print("Generated:")
    print(saved_path)

    print()
    print("=" * 70)
    print("STEP 9.3 STATUS")
    print("=" * 70)
    print("COMPLETED")