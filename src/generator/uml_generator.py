import json
import subprocess
from pathlib import Path


class UMLGenerator:

    def __init__(
        self,
        graph_path,
        output_dir=None,
        plantuml_jar=None,
    ):
        self.graph_path = Path(graph_path)

        base = self.graph_path.resolve().parents[1]

        if output_dir is None:
            output_dir = base / "uml"

        self.output_dir = Path(output_dir)

        if plantuml_jar is None:
            plantuml_jar = Path(
                r"C:\PlantUML\plantuml-1.2026.8.jar"
            )

        self.plantuml_jar = Path(plantuml_jar)

        self.graph = {}
        self.nodes = {}
        self.edges = []

    # =========================================================
    # LOAD GRAPH
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

        self.load_nodes()
        self.load_edges()

    def load_nodes(self):

        self.nodes = {}

        raw_nodes = self.graph.get("nodes", [])

        if not isinstance(raw_nodes, list):
            return

        for node in raw_nodes:

            if not isinstance(node, dict):
                continue

            node_id = node.get("id")

            if node_id:
                self.nodes[str(node_id)] = node

    def load_edges(self):

        self.edges = []

        raw_edges = self.graph.get("edges", [])

        if not isinstance(raw_edges, list):
            return

        for edge in raw_edges:

            if not isinstance(edge, dict):
                continue

            source = edge.get("source")
            target = edge.get("target")
            relationship = edge.get("relationship")

            if not source or not target:
                continue

            if not relationship:
                continue

            self.edges.append(
                {
                    "source": str(source),
                    "target": str(target),
                    "relationship": str(relationship),
                }
            )

    # =========================================================
    # NODE HELPERS
    # =========================================================

    def node_type(self, node_id):

        if ":" not in node_id:
            return ""

        return node_id.split(":", 1)[0]

    def node_value(self, node_id):

        if ":" not in node_id:
            return node_id

        return node_id.split(":", 1)[1]

    def readable_name(self, node_id):

        node = self.nodes.get(node_id, {})

        node_type = self.node_type(node_id)

        if node_type == "file":

            return node.get(
                "name",
                Path(
                    node.get(
                        "path",
                        self.node_value(node_id),
                    )
                ).name,
            )

        if node_type == "class":

            return node.get(
                "name",
                self.node_value(node_id),
            )

        if node_type == "method":

            class_name = node.get("class_name")
            method_name = node.get("name")

            if class_name and method_name:
                return f"{class_name}.{method_name}"

            return self.node_value(node_id)

        if node_type == "variable":

            return node.get(
                "name",
                self.node_value(node_id),
            )

        if node_type == "module":

            return node.get(
                "name",
                self.node_value(node_id),
            )

        return node.get(
            "name",
            self.node_value(node_id),
        )

    # =========================================================
    # ALIASES
    # =========================================================

    def build_aliases(self):

        aliases = {}

        counter = 1

        # Files
        for node_id in self.nodes:

            if self.node_type(node_id) == "file":

                aliases[node_id] = f"N{counter}"
                counter += 1

        # Classes
        for node_id in self.nodes:

            if self.node_type(node_id) == "class":

                aliases[node_id] = f"N{counter}"
                counter += 1

        # Variables
        # IMPORTANT:
        # Variables are represented as explicit UML objects.
        for node_id in self.nodes:

            if self.node_type(node_id) == "variable":

                aliases[node_id] = f"V{counter}"
                counter += 1

        return aliases

    # =========================================================
    # CLASS METHODS
    # =========================================================

    def get_class_methods(self, class_id):

        methods = []

        for edge in self.edges:

            if (
                edge["source"] == class_id
                and edge["relationship"] == "DEFINES"
                and self.node_type(edge["target"]) == "method"
            ):

                methods.append(edge["target"])

        return methods

    # =========================================================
    # METHOD → CLASS
    # =========================================================

    def get_class_for_method(self, method_id):

        for edge in self.edges:

            if (
                edge["relationship"] == "DEFINES"
                and edge["target"] == method_id
                and self.node_type(edge["source"]) == "class"
            ):

                return edge["source"]

        method_node = self.nodes.get(
            method_id,
            {},
        )

        class_name = method_node.get("class_name")

        if class_name:

            candidate = f"class:{class_name}"

            if candidate in self.nodes:
                return candidate

        return None

    # =========================================================
    # NODE GENERATION
    # =========================================================

    def generate_nodes(self, aliases):

        lines = []

        # -----------------------------------------------------
        # FILES
        # -----------------------------------------------------

        for node_id, alias in aliases.items():

            if self.node_type(node_id) != "file":
                continue

            label = self.readable_name(node_id)

            lines.append(
                f'component "{label}" as {alias}'
            )

        lines.append("")

        # -----------------------------------------------------
        # CLASSES
        # -----------------------------------------------------

        for node_id, alias in aliases.items():

            if self.node_type(node_id) != "class":
                continue

            label = self.readable_name(node_id)

            lines.append(
                f'class "{label}" as {alias} {{'
            )

            methods = self.get_class_methods(node_id)

            for method_id in methods:

                method_node = self.nodes.get(
                    method_id,
                    {},
                )

                method_name = method_node.get("name")

                if not method_name:

                    method_name = (
                        self.node_value(method_id)
                        .rsplit(".", 1)[-1]
                    )

                lines.append(
                    f"    +{method_name}()"
                )

            lines.append("}")

        lines.append("")

        # -----------------------------------------------------
        # VARIABLES
        # -----------------------------------------------------

        for node_id, alias in aliases.items():

            if self.node_type(node_id) != "variable":
                continue

            label = self.readable_name(node_id)

            lines.append(
                f'object "{label}" as {alias}'
            )

        return lines

    # =========================================================
    # RELATIONSHIP GENERATION
    # =========================================================

    def generate_relationships(self, aliases):

        lines = []

        rendered = set()

        for edge in self.edges:

            source = edge["source"]
            target = edge["target"]
            relationship = edge["relationship"]

            key = (
                source,
                relationship,
                target,
            )

            if key in rendered:
                continue

            # -------------------------------------------------
            # FILE → MODULE IMPORT
            # -------------------------------------------------

            if (
                relationship == "IMPORTS"
                and self.node_type(source) == "file"
                and self.node_type(target) == "module"
            ):

                if source not in aliases:
                    continue

                source_alias = aliases[source]

                module_name = self.readable_name(target)

                lines.append(
                    f'note right of {source_alias} : '
                    f'IMPORTS -> {module_name}'
                )

                rendered.add(key)

                continue

            # -------------------------------------------------
            # FILE → CLASS CALL
            # -------------------------------------------------

            if (
                relationship == "CALLS"
                and self.node_type(source) == "file"
                and self.node_type(target) == "class"
            ):

                if (
                    source not in aliases
                    or target not in aliases
                ):
                    continue

                lines.append(
                    f'{aliases[source]} --> '
                    f'{aliases[target]} : calls'
                )

                rendered.add(key)

                continue

            # -------------------------------------------------
            # FILE → METHOD CALL
            # -------------------------------------------------

            if (
                relationship == "CALLS"
                and self.node_type(source) == "file"
                and self.node_type(target) == "method"
            ):

                class_id = self.get_class_for_method(target)

                if (
                    source not in aliases
                    or class_id not in aliases
                ):
                    continue

                method_node = self.nodes.get(
                    target,
                    {},
                )

                method_name = method_node.get("name")

                if not method_name:

                    method_name = (
                        self.node_value(target)
                        .rsplit(".", 1)[-1]
                    )

                lines.append(
                    f'{aliases[source]} --> '
                    f'{aliases[class_id]} : '
                    f'calls {method_name}()'
                )

                rendered.add(key)

                continue

            # -------------------------------------------------
            # FILE → CLASS DEFINES
            # -------------------------------------------------

            if (
                relationship == "DEFINES"
                and self.node_type(source) == "file"
                and self.node_type(target) == "class"
            ):

                if (
                    source not in aliases
                    or target not in aliases
                ):
                    continue

                lines.append(
                    f'{aliases[source]} ..> '
                    f'{aliases[target]} : defines'
                )

                rendered.add(key)

                continue

            # -------------------------------------------------
            # CLASS → METHOD DEFINES
            # -------------------------------------------------

            if (
                relationship == "DEFINES"
                and self.node_type(source) == "class"
                and self.node_type(target) == "method"
            ):

                if (
                    source not in aliases
                    or target not in self.nodes
                ):
                    continue

                method_node = self.nodes.get(
                    target,
                    {},
                )

                method_name = method_node.get("name")

                if not method_name:

                    method_name = (
                        self.node_value(target)
                        .rsplit(".", 1)[-1]
                    )

                lines.append(
                    f'note right of {aliases[source]} : '
                    f'DEFINES -> {method_name}()'
                )

                rendered.add(key)

                continue

            # -------------------------------------------------
            # VARIABLE → CLASS INSTANCE_OF
            # -------------------------------------------------
            #
            # IMPORTANT:
            # The variable itself is now the UML source.
            #
            # Graph:
            # service --INSTANCE_OF--> Service
            #
            # UML:
            # V... ..> N... : instance of
            # -------------------------------------------------

            if (
                relationship == "INSTANCE_OF"
                and self.node_type(source) == "variable"
                and self.node_type(target) == "class"
            ):

                if (
                    source not in aliases
                    or target not in aliases
                ):
                    continue

                lines.append(
                    f'{aliases[source]} ..> '
                    f'{aliases[target]} : instance of'
                )

                rendered.add(key)

                continue

            # -------------------------------------------------
            # VARIABLE → METHOD CALL
            # -------------------------------------------------
            #
            # IMPORTANT:
            # The variable itself is now the UML source.
            #
            # Graph:
            # service --CALLS--> Service.process
            #
            # UML:
            # V... --> N... : calls process()
            # -------------------------------------------------

            if (
                relationship == "CALLS"
                and self.node_type(source) == "variable"
                and self.node_type(target) == "method"
            ):

                class_id = self.get_class_for_method(target)

                if (
                    source not in aliases
                    or class_id not in aliases
                ):
                    continue

                method_node = self.nodes.get(
                    target,
                    {},
                )

                method_name = method_node.get("name")

                if not method_name:

                    method_name = (
                        self.node_value(target)
                        .rsplit(".", 1)[-1]
                    )

                lines.append(
                    f'{aliases[source]} --> '
                    f'{aliases[class_id]} : '
                    f'calls {method_name}()'
                )

                rendered.add(key)

                continue

        return lines

    # =========================================================
    # GENERATE PLANTUML
    # =========================================================

    def generate(self):

        self.load_graph()

        aliases = self.build_aliases()

        lines = []

        lines.append("@startuml")

        lines.append(
            "title CIAO Generated Software Architecture"
        )

        lines.append("allowmixing")

        lines.append(
            "skinparam shadowing false"
        )

        lines.append(
            "skinparam componentStyle rectangle"
        )

        lines.append("")

        lines.extend(
            self.generate_nodes(aliases)
        )

        lines.append("")

        lines.extend(
            self.generate_relationships(aliases)
        )

        lines.append("")

        lines.append("@enduml")

        return "\n".join(lines)

    # =========================================================
    # SAVE
    # =========================================================

    def save(self, content):

        self.output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        puml_path = (
            self.output_dir
            / "architecture.puml"
        )

        with open(
            puml_path,
            "w",
            encoding="utf-8",
        ) as f:
            f.write(content)

        return puml_path

    # =========================================================
    # RENDER
    # =========================================================

    def render(self, puml_path):

        if not self.plantuml_jar.exists():

            raise FileNotFoundError(
                f"PlantUML JAR not found: "
                f"{self.plantuml_jar}"
            )

        command = [
            "java",
            "-jar",
            str(self.plantuml_jar),
            "-tpng",
            str(puml_path),
        ]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:

            raise RuntimeError(
                "PlantUML rendering failed:\n"
                + result.stderr
            )

        png_path = (
            puml_path.parent
            / "architecture.png"
        )

        if not png_path.exists():

            raise FileNotFoundError(
                f"PlantUML did not generate: "
                f"{png_path}"
            )

        return png_path


# =============================================================
# MAIN
# =============================================================

if __name__ == "__main__":

    base = Path(
        __file__
    ).resolve().parents[2]

    graph_path = (
        base
        / "output"
        / "graph"
        / "repository_graph.json"
    )

    output_dir = (
        base
        / "output"
        / "uml"
    )

    plantuml_jar = Path(
        r"C:\PlantUML\plantuml-1.2026.8.jar"
    )

    generator = UMLGenerator(
        graph_path=graph_path,
        output_dir=output_dir,
        plantuml_jar=plantuml_jar,
    )

    content = generator.generate()

    puml_path = generator.save(
        content
    )

    png_path = generator.render(
        puml_path
    )

    print("=" * 70)
    print("STEP 9.4A - VERIFIED UML GENERATION")
    print("=" * 70)

    print()
    print("Knowledge graph:")
    print(graph_path)

    print()
    print("PlantUML source:")
    print(puml_path)

    print()
    print("Rendered architecture:")
    print(png_path)

    print()
    print("=" * 70)
    print("STEP 9.4A STATUS")
    print("=" * 70)
    print("COMPLETED")