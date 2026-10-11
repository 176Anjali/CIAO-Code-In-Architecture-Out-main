import json
import re
from pathlib import Path


class ArtifactVerifier:

    def __init__(
        self,
        verified_architecture_path,
        uml_path,
        arc42_path,
        output_path=None,
    ):
        self.verified_architecture_path = Path(
            verified_architecture_path
        )

        self.uml_path = Path(uml_path)
        self.arc42_path = Path(arc42_path)

        if output_path is None:
            output_path = (
                self.verified_architecture_path.parent
                / "final_verification.json"
            )

        self.output_path = Path(output_path)

        self.architecture = {}
        self.uml_text = ""
        self.arc42_text = ""

        self.uml_aliases = {}
        self.uml_relationships = set()

        self.results = []

    # =========================================================
    # LOAD
    # =========================================================

    def load(self):

        if not self.verified_architecture_path.exists():
            raise FileNotFoundError(
                f"Verified architecture not found: "
                f"{self.verified_architecture_path}"
            )

        if not self.uml_path.exists():
            raise FileNotFoundError(
                f"UML file not found: {self.uml_path}"
            )

        if not self.arc42_path.exists():
            raise FileNotFoundError(
                f"arc42 document not found: {self.arc42_path}"
            )

        with open(
            self.verified_architecture_path,
            "r",
            encoding="utf-8",
        ) as f:
            self.architecture = json.load(f)

        with open(
            self.uml_path,
            "r",
            encoding="utf-8",
        ) as f:
            self.uml_text = f.read()

        with open(
            self.arc42_path,
            "r",
            encoding="utf-8",
        ) as f:
            self.arc42_text = f.read()

    # =========================================================
    # VERIFIED ARCHITECTURE HELPERS
    # =========================================================

    def get_components(self):

        return self.architecture.get(
            "components",
            {},
        )

    def get_relationships(self):

        return self.architecture.get(
            "relationships",
            [],
        )

    def get_review_items(self):

        return self.architecture.get(
            "review_items",
            [],
        )

    def clean_name(self, node_id):

        if not isinstance(node_id, str):
            return str(node_id)

        if ":" not in node_id:
            return node_id

        node_type, value = node_id.split(
            ":",
            1,
        )

        if node_type == "file":

            return Path(value).name

        if node_type == "class":

            return value

        if node_type == "method":

            return value

        if node_type == "module":

            return value

        if node_type == "variable":

            return value.rsplit(
                ":",
                1,
            )[-1]

        return value

    def verified_nodes(self):

        nodes = set()

        for values in self.get_components().values():

            if not isinstance(values, list):
                continue

            for value in values:

                nodes.add(
                    str(value)
                )

        return nodes

    def verified_readable_names(self):

        names = set()

        for node in self.verified_nodes():

            names.add(
                self.clean_name(node)
            )

        return names

    def add_result(
        self,
        category,
        status,
        item,
        reason,
    ):

        self.results.append(
            {
                "category": category,
                "status": status,
                "item": item,
                "reason": reason,
            }
        )

    # =========================================================
    # UML ALIAS PARSING
    # =========================================================

    def parse_uml_aliases(self):

        self.uml_aliases = {}

        for line in self.uml_text.splitlines():

            stripped = line.strip()

            # -------------------------------------------------
            # component "app.py" as N1
            # -------------------------------------------------

            match = re.match(
                r'^component\s+"([^"]+)"\s+as\s+'
                r'([A-Za-z0-9_]+)',
                stripped,
                re.IGNORECASE,
            )

            if match:

                label = match.group(1)
                alias = match.group(2)

                self.uml_aliases[
                    alias
                ] = label

                continue

            # -------------------------------------------------
            # class "Service" as N3
            # -------------------------------------------------

            match = re.match(
                r'^class\s+"([^"]+)"\s+as\s+'
                r'([A-Za-z0-9_]+)',
                stripped,
                re.IGNORECASE,
            )

            if match:

                label = match.group(1)
                alias = match.group(2)

                self.uml_aliases[
                    alias
                ] = label

                continue

            # -------------------------------------------------
            # object "service" as V4
            # -------------------------------------------------

            match = re.match(
                r'^object\s+"([^"]+)"\s+as\s+'
                r'([A-Za-z0-9_]+)',
                stripped,
                re.IGNORECASE,
            )

            if match:

                label = match.group(1)
                alias = match.group(2)

                self.uml_aliases[
                    alias
                ] = label

                continue

    # =========================================================
    # UML RELATIONSHIP PARSING
    # =========================================================

    def normalize_uml_relationship(
        self,
        source,
        target,
        label,
    ):

        source_name = self.uml_aliases.get(
            source,
            source,
        )

        target_name = self.uml_aliases.get(
            target,
            target,
        )

        original_label = label.strip()
        label_lower = original_label.lower()

        # -----------------------------------------------------
        # CALLS METHOD
        # -----------------------------------------------------

        match = re.search(
            r'calls\s+([A-Za-z_][A-Za-z0-9_]*)\(\)',
            label_lower,
        )

        if match:

            method_name = match.group(1)

            return (
                source_name,
                "CALLS",
                f"{target_name}.{method_name}",
            )

        # -----------------------------------------------------
        # VARIABLE METHOD CALL
        #
        # Example:
        # V4 --> N3 : service.process()
        # -----------------------------------------------------

        match = re.search(
            r'([A-Za-z_][A-Za-z0-9_]*)\.'
            r'([A-Za-z_][A-Za-z0-9_]*)\(\)',
            original_label,
        )

        if match:

            method_name = match.group(2)

            return (
                source_name,
                "CALLS",
                f"{target_name}.{method_name}",
            )

        # -----------------------------------------------------
        # CALLS CLASS
        # -----------------------------------------------------

        if label_lower == "calls":

            return (
                source_name,
                "CALLS",
                target_name,
            )

        # -----------------------------------------------------
        # INSTANCE OF
        # -----------------------------------------------------

        if "instance of" in label_lower:

            return (
                source_name,
                "INSTANCE_OF",
                target_name,
            )

        # -----------------------------------------------------
        # DEFINES METHOD
        # -----------------------------------------------------

        match = re.search(
            r'defines\s*->\s*'
            r'([A-Za-z_][A-Za-z0-9_]*)'
            r'\(\)',
            original_label,
            re.IGNORECASE,
        )

        if match:

            method_name = match.group(1)

            return (
                source_name,
                "DEFINES",
                f"{target_name}.{method_name}",
            )

        # -----------------------------------------------------
        # DEFINES CLASS
        # -----------------------------------------------------

        if label_lower == "defines":

            return (
                source_name,
                "DEFINES",
                target_name,
            )

        # -----------------------------------------------------
        # IMPORTS
        # -----------------------------------------------------
        #
        # We intentionally use the ORIGINAL label here.
        #
        # This means:
        #
        # IMPORTS -> Service
        #
        # remains:
        #
        # Service
        #
        # instead of becoming:
        #
        # service
        # -----------------------------------------------------

        match = re.search(
            r'import[s]?\s*->\s*(.+)',
            original_label,
            re.IGNORECASE,
        )

        if match:

            module_name = match.group(1).strip()

            return (
                source_name,
                "IMPORTS",
                module_name,
            )

        # -----------------------------------------------------
        # FALLBACK
        # -----------------------------------------------------

        return (
            source_name,
            original_label.upper(),
            target_name,
        )

    def parse_uml_relationships(self):

        self.uml_relationships = set()

        for line in self.uml_text.splitlines():

            stripped = line.strip()

            # -------------------------------------------------
            # Arrow relationship
            #
            # Examples:
            #
            # V4 ..> N3 : instance of
            # V4 --> N3 : calls process()
            # N1 --> N3 : calls
            # -------------------------------------------------

            arrow_match = re.match(
                r'^([A-Za-z0-9_]+)'
                r'\s+'
                r'(?:-->|\.{2}>|--\|>)'
                r'\s+'
                r'([A-Za-z0-9_]+)'
                r'\s*:\s*(.+)$',
                stripped,
            )

            if arrow_match:

                source = arrow_match.group(1)
                target = arrow_match.group(2)
                label = arrow_match.group(3)

                normalized = (
                    self.normalize_uml_relationship(
                        source,
                        target,
                        label,
                    )
                )

                self.uml_relationships.add(
                    normalized
                )

                continue

            # -------------------------------------------------
            # Note relationship
            #
            # Example:
            #
            # note right of N1 : IMPORTS -> Service
            # -------------------------------------------------

            note_match = re.match(
                r'^note\s+right\s+of\s+'
                r'([A-Za-z0-9_]+)'
                r'\s*:\s*(.+)$',
                stripped,
                re.IGNORECASE,
            )

            if not note_match:
                continue

            source = note_match.group(1)
            content = note_match.group(2).strip()

            source_name = (
                self.uml_aliases.get(
                    source,
                    source,
                )
            )

            # -------------------------------------------------
            # IMPORTS
            #
            # IMPORTANT:
            # Use original content to preserve case.
            # -------------------------------------------------

            import_match = re.search(
                r'import[s]?\s*->\s*(.+)',
                content,
                re.IGNORECASE,
            )

            if import_match:

                target = (
                    import_match.group(1)
                    .strip()
                )

                self.uml_relationships.add(
                    (
                        source_name,
                        "IMPORTS",
                        target,
                    )
                )

                continue

            # -------------------------------------------------
            # DEFINES -> method()
            # -------------------------------------------------

            defines_match = re.search(
                r'defines\s*->\s*'
                r'([A-Za-z_][A-Za-z0-9_]*)'
                r'\(\)',
                content,
                re.IGNORECASE,
            )

            if defines_match:

                method_name = (
                    defines_match.group(1)
                )

                self.uml_relationships.add(
                    (
                        source_name,
                        "DEFINES",
                        f"{source_name}."
                        f"{method_name}",
                    )
                )

                continue

    # =========================================================
    # UML COMPONENT CHECK
    # =========================================================

    def verify_uml_components(self):

        verified_names = (
            self.verified_readable_names()
        )

        for alias, name in sorted(
            self.uml_aliases.items()
        ):

            if name in verified_names:

                self.add_result(
                    "UML_COMPONENT",
                    "PASS",
                    name,
                    "Component exists in verified architecture.",
                )

            else:

                self.add_result(
                    "UML_COMPONENT",
                    "FAIL",
                    name,
                    "UML component is not present in verified architecture.",
                )

        if not self.uml_aliases:

            self.add_result(
                "UML_COMPONENT",
                "FAIL",
                "No UML components detected",
                "No component/class/object aliases could be parsed from the PlantUML source.",
            )

    # =========================================================
    # UML RELATIONSHIP CHECK
    # =========================================================

    def expected_relationship(
        self,
        relationship,
    ):

        source = self.clean_name(
            relationship.get(
                "source",
                "",
            )
        )

        target = self.clean_name(
            relationship.get(
                "target",
                "",
            )
        )

        relation = relationship.get(
            "relation",
            relationship.get(
                "relationship",
                "",
            ),
        )

        return (
            source,
            relation,
            target,
        )

    def verify_uml_relationships(self):

        for relationship in (
            self.get_relationships()
        ):

            expected = (
                self.expected_relationship(
                    relationship
                )
            )

            if expected in self.uml_relationships:

                self.add_result(
                    "UML_RELATIONSHIP",
                    "PASS",
                    (
                        f"{expected[0]} "
                        f"--{expected[1]}--> "
                        f"{expected[2]}"
                    ),
                    "Exact relationship is represented in the parsed UML model.",
                )

            else:

                self.add_result(
                    "UML_RELATIONSHIP",
                    "FAIL",
                    (
                        f"{expected[0]} "
                        f"--{expected[1]}--> "
                        f"{expected[2]}"
                    ),
                    "Verified relationship is not represented exactly in the parsed UML model.",
                )

    # =========================================================
    # ARC42 COMPONENT CHECK
    # =========================================================

    def verify_arc42_components(self):

        verified_names = (
            self.verified_readable_names()
        )

        for name in sorted(
            verified_names
        ):

            if name in self.arc42_text:

                self.add_result(
                    "ARC42_COMPONENT",
                    "PASS",
                    name,
                    "Verified component is documented in arc42.",
                )

            else:

                self.add_result(
                    "ARC42_COMPONENT",
                    "FAIL",
                    name,
                    "Verified component is missing from arc42 documentation.",
                )

    # =========================================================
    # ARC42 RELATIONSHIP CHECK
    # =========================================================

    def verify_arc42_relationships(self):

        for relationship in (
            self.get_relationships()
        ):

            expected = (
                self.expected_relationship(
                    relationship
                )
            )

            source = expected[0]
            target = expected[2]

            if (
                source in self.arc42_text
                and target in self.arc42_text
            ):

                self.add_result(
                    "ARC42_RELATIONSHIP",
                    "PASS",
                    (
                        f"{source} "
                        f"--{expected[1]}--> "
                        f"{target}"
                    ),
                    "Relationship endpoints are documented in arc42.",
                )

            else:

                self.add_result(
                    "ARC42_RELATIONSHIP",
                    "FAIL",
                    (
                        f"{source} "
                        f"--{expected[1]}--> "
                        f"{target}"
                    ),
                    "One or both relationship endpoints are missing from arc42.",
                )

    # =========================================================
    # UNSUPPORTED CLAIM CHECK
    # =========================================================

    def verify_arc42_unknown_architecture_terms(self):

        dangerous_terms = [
            "database",
            "postgresql",
            "mysql",
            "mongodb",
            "redis",
            "rest api",
            "api gateway",
            "microservice",
            "microservices",
            "docker",
            "kubernetes",
            "aws",
            "azure",
            "gcp",
            "cloud",
            "load balancer",
            "message queue",
            "kafka",
            "rabbitmq",
        ]

        verified_text = " ".join(
            self.verified_readable_names()
        ).lower()

        for term in dangerous_terms:

            if term in self.arc42_text.lower():

                if term not in verified_text:

                    self.add_result(
                        "ARC42_UNSUPPORTED_CLAIM",
                        "FAIL",
                        term,
                        "Architecture technology or infrastructure term appears in documentation but is not represented in verified architecture.",
                    )

    # =========================================================
    # REVIEW ITEM PRESERVATION
    # =========================================================

    def verify_review_items(self):

        for item in self.get_review_items():

            claim = item.get(
                "claim",
                "",
            )

            if not claim:
                continue

            if claim.lower() in (
                self.arc42_text.lower()
            ):

                self.add_result(
                    "REVIEW_ITEM",
                    "PASS",
                    claim,
                    "Review item is preserved in the documentation.",
                )

            else:

                self.add_result(
                    "REVIEW_ITEM",
                    "FAIL",
                    claim,
                    "Review item was not preserved in the documentation.",
                )

    # =========================================================
    # FINAL STATUS
    # =========================================================

    def calculate_status(self):

        failures = [
            result
            for result in self.results
            if result["status"] == "FAIL"
        ]

        reviews = [
            result
            for result in self.results
            if result["status"] == "REVIEW"
        ]

        passes = [
            result
            for result in self.results
            if result["status"] == "PASS"
        ]

        if failures:

            status = (
                "CORRECTION_REQUIRED"
            )

        elif reviews:

            status = (
                "VERIFIED_WITH_REVIEW"
            )

        else:

            status = "APPROVED"

        return {
            "status": status,
            "passes": len(passes),
            "failures": len(failures),
            "reviews": len(reviews),
            "total_checks": len(
                self.results
            ),
        }

    # =========================================================
    # VERIFY
    # =========================================================

    def verify(self):

        self.load()

        self.results = []

        self.parse_uml_aliases()

        self.parse_uml_relationships()

        self.verify_uml_components()

        self.verify_uml_relationships()

        self.verify_arc42_components()

        self.verify_arc42_relationships()

        self.verify_arc42_unknown_architecture_terms()

        self.verify_review_items()

        summary = self.calculate_status()

        return {
            "metadata": {
                "generator": (
                    "CIAO - Code In Architecture Out"
                ),
                "artifact": (
                    "Final Artifact Verification"
                ),
                "version": "2.1",
            },
            "status": summary["status"],
            "summary": {
                "passes": summary["passes"],
                "failures": summary["failures"],
                "reviews": summary["reviews"],
                "total_checks": summary[
                    "total_checks"
                ],
            },
            "results": self.results,
            "parsed_uml": {
                "aliases": self.uml_aliases,
                "relationships": [
                    {
                        "source": item[0],
                        "relation": item[1],
                        "target": item[2],
                    }
                    for item in sorted(
                        self.uml_relationships
                    )
                ],
            },
            "source_artifacts": {
                "verified_architecture": str(
                    self.verified_architecture_path
                ),
                "uml": str(
                    self.uml_path
                ),
                "arc42": str(
                    self.arc42_path
                ),
            },
        }

    # =========================================================
    # SAVE
    # =========================================================

    def save(
        self,
        report,
    ):

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
                report,
                f,
                indent=4,
                ensure_ascii=False,
            )

        return self.output_path

    # =========================================================
    # PRINT
    # =========================================================

    def print_report(
        self,
        report,
    ):

        summary = report[
            "summary"
        ]

        print("=" * 70)

        print(
            "STEP 9.4 - FINAL ARTIFACT VERIFIER"
        )

        print("=" * 70)

        print()

        print(
            f"Final status: "
            f"{report['status']}"
        )

        print(
            f"Total checks: "
            f"{summary['total_checks']}"
        )

        print(
            f"Passed: "
            f"{summary['passes']}"
        )

        print(
            f"Failed: "
            f"{summary['failures']}"
        )

        print(
            f"Review: "
            f"{summary['reviews']}"
        )

        print()

        print(
            "-" * 70
        )

        print(
            "VERIFICATION RESULTS"
        )

        print(
            "-" * 70
        )

        for result in report[
            "results"
        ]:

            print(
                f"[{result['status']}] "
                f"{result['category']}: "
                f"{result['item']}"
            )

            print(
                f"       "
                f"{result['reason']}"
            )

        print()

        print(
            "Parsed UML aliases:"
        )

        for alias, name in sorted(
            report["parsed_uml"][
                "aliases"
            ].items()
        ):

            print(
                f"  {alias} -> {name}"
            )

        print()

        print(
            "Parsed UML relationships:"
        )

        for relationship in report[
            "parsed_uml"
        ]["relationships"]:

            print(
                f"  {relationship['source']} "
                f"--{relationship['relation']}--> "
                f"{relationship['target']}"
            )

        print()

        print(
            "Verification report saved to:"
        )

        print(
            self.output_path
        )

        print()

        print("=" * 70)

        print(
            "STEP 9.4 STATUS"
        )

        print("=" * 70)

        if report["status"] == "APPROVED":

            print(
                "APPROVED: "
                "All artifact checks passed."
            )

        elif (
            report["status"]
            == "VERIFIED_WITH_REVIEW"
        ):

            print(
                "COMPLETED: "
                "Artifacts require review."
            )

        else:

            print(
                "CORRECTION REQUIRED: "
                "Artifact inconsistencies detected."
            )


# =============================================================
# MAIN
# =============================================================

if __name__ == "__main__":

    base = (
        Path(__file__)
        .resolve()
        .parents[2]
    )

    verified_architecture_path = (
        base
        / "output"
        / "docs"
        / "verified_architecture.json"
    )

    uml_path = (
        base
        / "output"
        / "uml"
        / "architecture.puml"
    )

    arc42_path = (
        base
        / "output"
        / "docs"
        / "arc42_document.md"
    )

    output_path = (
        base
        / "output"
        / "docs"
        / "final_verification.json"
    )

    verifier = ArtifactVerifier(
        verified_architecture_path=(
            verified_architecture_path
        ),
        uml_path=uml_path,
        arc42_path=arc42_path,
        output_path=output_path,
    )

    report = verifier.verify()

    verifier.save(
        report
    )

    verifier.print_report(
        report
    )