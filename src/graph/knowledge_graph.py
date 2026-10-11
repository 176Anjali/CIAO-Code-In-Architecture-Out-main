import json
from pathlib import Path

import networkx as nx

from src.parser.code_analyzer import CodeAnalyzer


class RepositoryKnowledgeGraph:
    """Build a ground-truth repository graph from CodeAnalyzer results."""

    def __init__(self, repository_path):
        self.repository_path = Path(repository_path).resolve()
        self.graph = nx.MultiDiGraph()

    # -----------------------------------------------------------------
    # IDs
    # -----------------------------------------------------------------
    @staticmethod
    def file_id(path):
        return f"file:{Path(path).resolve()}"

    @staticmethod
    def module_id(name):
        return f"module:{name}"

    @staticmethod
    def class_id(name):
        return f"class:{name}"

    @staticmethod
    def method_id(class_name, method_name):
        return f"method:{class_name}.{method_name}"

    @staticmethod
    def function_id(name):
        return f"function:{name}"

    @staticmethod
    def variable_id(file_path, name):
        return f"variable:{Path(file_path).resolve()}:{name}"

    @staticmethod
    def _name(value):
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            for key in ("name", "symbol", "function", "method", "class",
                        "callee", "called_symbol", "variable"):
                if value.get(key):
                    return value[key]
        return None

    def add_node(self, node_id, node_type, **attrs):
        data = {"id": node_id, "type": node_type}
        data.update(attrs)
        if self.graph.has_node(node_id):
            self.graph.nodes[node_id].update(data)
        else:
            self.graph.add_node(node_id, **data)

    def add_relationship(self, source, target, relationship, **attrs):
        if self.graph.has_node(source) and self.graph.has_node(target):
            data = {"relationship": relationship}
            data.update(attrs)
            self.graph.add_edge(source, target, **data)

    # -----------------------------------------------------------------
    # Basic entities
    # -----------------------------------------------------------------
    def add_file_and_module(self, file_path):
        file_node = self.file_id(file_path)
        self.add_node(
            file_node,
            "file",
            name=Path(file_path).name,
            path=str(Path(file_path).resolve()),
        )

        module = Path(file_path).stem
        module_node = self.module_id(module)
        self.add_node(module_node, "module", name=module)
        self.add_relationship(file_node, module_node, "MODULE")
        return file_node

    def add_classes(self, file_path, classes):
        source = self.file_id(file_path)

        for item in classes or []:
            info = item if isinstance(item, dict) else {"name": item}
            name = info.get("name") or info.get("class") or info.get("symbol")
            if not name:
                continue

            class_node = self.class_id(str(name))
            self.add_node(
                class_node, "class", name=str(name),
                file=str(Path(file_path).resolve())
            )
            self.add_relationship(source, class_node, "DEFINES")

            for method in info.get("methods", []) or []:
                minfo = method if isinstance(method, dict) else {"name": method}
                method_name = minfo.get("name") or minfo.get("method") or minfo.get("symbol")
                if method_name:
                    method_node = self.method_id(str(name), str(method_name))
                    self.add_node(
                        method_node, "method", name=str(method_name),
                        class_name=str(name),
                        file=str(Path(file_path).resolve())
                    )
                    self.add_relationship(class_node, method_node, "DEFINES")

    def add_methods(self, file_path, methods):
        for item in methods or []:
            info = item if isinstance(item, dict) else {"name": item}
            method_name = info.get("name") or info.get("method") or info.get("symbol")
            class_name = info.get("class") or info.get("class_name")
            if not method_name or not class_name:
                continue

            class_node = self.class_id(str(class_name))
            method_node = self.method_id(str(class_name), str(method_name))

            self.add_node(
                class_node, "class", name=str(class_name),
                file=str(Path(file_path).resolve())
            )
            self.add_node(
                method_node, "method", name=str(method_name),
                class_name=str(class_name),
                file=str(Path(file_path).resolve())
            )
            self.add_relationship(class_node, method_node, "DEFINES")

    def add_functions(self, file_path, functions):
        source = self.file_id(file_path)
        for item in functions or []:
            info = item if isinstance(item, dict) else {"name": item}
            name = (
                info.get("qualified_name")
                or info.get("full_name")
                or info.get("name")
                or info.get("function")
                or info.get("symbol")
            )
            if not name:
                continue
            name = str(name)
            node = self.function_id(name)
            self.add_node(
                node, "function", name=name.split(".")[-1],
                qualified_name=name,
                file=str(Path(file_path).resolve())
            )
            self.add_relationship(source, node, "DEFINES")

    def add_nested_functions(self, file_path, nested_functions):
        for item in nested_functions or []:
            info = item if isinstance(item, dict) else {"name": item}
            name = info.get("name") or info.get("function") or info.get("symbol")
            parent = info.get("parent_function")
            qualified = info.get("qualified_name") or info.get("full_name")

            if not qualified and parent and name:
                qualified = f"{parent}.{name}"
            if not qualified:
                qualified = name
            if not qualified:
                continue

            child = self.function_id(str(qualified))
            self.add_node(
                child, "function", name=str(name or qualified).split(".")[-1],
                qualified_name=str(qualified),
                parent_function=parent,
                nested=True,
                file=str(Path(file_path).resolve())
            )

            if parent:
                parent_node = self.function_id(str(parent))
                self.add_node(
                    parent_node, "function",
                    name=str(parent).split(".")[-1],
                    qualified_name=str(parent),
                    file=str(Path(file_path).resolve())
                )
                self.add_relationship(parent_node, child, "DEFINES")

    def add_variables(self, file_path, variables):
        for item in variables or []:
            info = item if isinstance(item, dict) else {"name": item}
            name = info.get("name") or info.get("variable") or info.get("symbol")
            if not name:
                continue
            node = self.variable_id(file_path, str(name))
            self.add_node(
                node, "variable", name=str(name),
                file=str(Path(file_path).resolve()),
                class_name=info.get("type") or info.get("class")
            )

    # -----------------------------------------------------------------
    # Imports
    # -----------------------------------------------------------------
    def add_imports(self, file_path, imports):
        source = self.file_id(file_path)
        repo_files = {p.stem: p for p in self.repository_path.rglob("*.py")}

        for item in imports or []:
            name = self._name(item)
            if not name:
                continue
            name = str(name)

            # Keep the original import evidence.
            module_node = self.module_id(name)
            self.add_node(module_node, "module", name=name)
            self.add_relationship(source, module_node, "IMPORTS")

            # from service import Service
            if name in repo_files:
                imported_file = self.file_id(repo_files[name])
                self.add_node(
                    imported_file, "file",
                    name=repo_files[name].name,
                    path=str(repo_files[name].resolve())
                )
                self.add_relationship(source, imported_file, "IMPORTS_FILE")

            class_node = self.class_id(name)
            if self.graph.has_node(class_node):
                self.add_relationship(source, class_node, "IMPORTS_CLASS")

        # Also infer class imports from existing class names when the
        # analyzer returns the module and imported symbol separately.
        for class_node, data in list(self.graph.nodes(data=True)):
            if data.get("type") != "class":
                continue
            class_name = data.get("name")
            if not class_name:
                continue
            for item in imports or []:
                imported = self._name(item)
                if imported == class_name:
                    self.add_relationship(source, class_node, "IMPORTS_CLASS")

    # -----------------------------------------------------------------
    # Variables and inheritance
    # -----------------------------------------------------------------
    def add_resolved_variables(self, file_path, resolved):
        for item in resolved or []:
            if not isinstance(item, dict):
                continue
            variable = item.get("variable")
            class_name = item.get("class") or item.get("type")
            if not variable or not class_name:
                continue

            v = self.variable_id(file_path, variable)
            c = self.class_id(str(class_name))
            self.add_node(v, "variable", name=str(variable), file=str(Path(file_path).resolve()))
            self.add_node(c, "class", name=str(class_name))
            self.add_relationship(v, c, "INSTANCE_OF")

    def add_inheritance(self, inheritance):
        for item in inheritance or []:
            if not isinstance(item, dict):
                continue
            child = item.get("child") or item.get("class") or item.get("derived")
            parent = item.get("parent") or item.get("base") or item.get("base_class")
            if child and parent:
                c = self.class_id(str(child))
                p = self.class_id(str(parent))
                self.add_node(c, "class", name=str(child))
                self.add_node(p, "class", name=str(parent))
                self.add_relationship(c, p, "INHERITS")

    # -----------------------------------------------------------------
    # Resolution helpers
    # -----------------------------------------------------------------
    def available_method(self, class_name, method_name):
        node = self.method_id(class_name, method_name)
        return node if self.graph.has_node(node) else None

    def resolve_function_node(self, callee, caller, functions):
        if not callee:
            return None
        callee = str(callee)

        if callee in functions:
            return self.function_id(callee)

        if caller:
            caller = str(caller)
            parent = caller.rsplit(".", 1)[0] if "." in caller else caller
            candidate = f"{parent}.{callee}"
            if candidate in functions:
                return self.function_id(candidate)

        matches = [f for f in functions if f.endswith("." + callee) or f == callee]
        return self.function_id(matches[0]) if len(matches) == 1 else None

    def resolve_object_method(self, file_path, callee):
        if "." not in str(callee):
            return None
        obj, method = str(callee).rsplit(".", 1)
        variable = self.variable_id(file_path, obj)

        if not self.graph.has_node(variable):
            return None

        for _, target, data in self.graph.out_edges(variable, data=True):
            if data.get("relationship") == "INSTANCE_OF":
                class_name = self.graph.nodes[target].get("name")
                if class_name:
                    return self.available_method(class_name, method)
        return None

    # -----------------------------------------------------------------
    # Calls
    # -----------------------------------------------------------------
    def add_call_details(self, file_path, call_details, functions):
        file_node = self.file_id(file_path)

        for call in call_details or []:
            if not isinstance(call, dict):
                continue

            caller = call.get("caller")
            callee = call.get("callee") or call.get("called_symbol")
            call_type = call.get("type")

            if not callee:
                continue

            source = file_node
            if caller and caller != "<module>":
                resolved_source = self.resolve_function_node(caller, None, functions)
                if resolved_source:
                    source = resolved_source

            target = None

            if call_type in ("project", "nested_function"):
                target = self.resolve_function_node(callee, caller, functions)

            elif call_type == "object_method":
                target = self.resolve_object_method(file_path, callee)

            elif call_type == "unknown":
                # Prefer repository object methods/functions before
                # treating an unknown call as an external dependency.
                target = self.resolve_object_method(file_path, callee)
                if target is None:
                    target = self.resolve_function_node(callee, caller, functions)

            elif call_type == "external":
                # The analyzer can classify an attribute call such as
                # service.process as external when it cannot resolve the
                # receiver at AST-call time. The graph has stronger evidence:
                # service INSTANCE_OF Service + Service.process exists.
                target = self.resolve_object_method(file_path, callee)

                if target:
                    self.add_relationship(source, target, "CALLS")
                    variable_name = str(callee).rsplit(".", 1)[0]
                    variable_node = self.variable_id(
                        file_path,
                        variable_name,
                    )
                    if self.graph.has_node(variable_node):
                        self.add_relationship(
                            variable_node,
                            target,
                            "CALLS",
                        )
                    continue

                imported_as = call.get("imported_as")
                name = str(imported_as or callee)
                module = self.module_id(name)
                self.add_node(module, "module", name=name, external=True)
                self.add_relationship(source, module, "CALLS")

            elif call_type == "builtin":
                imported_as = call.get("imported_as")
                name = str(imported_as or callee)
                module = self.module_id(name)
                self.add_node(module, "module", name=name, external=True)
                self.add_relationship(source, module, "CALLS")

            if target:
                self.add_relationship(source, target, "CALLS")

    def add_resolved_calls(self, file_path, resolved_calls, functions):
        for item in resolved_calls or []:
            if not isinstance(item, dict):
                continue

            caller_file = item.get("caller_file") or file_path
            caller = item.get("caller")
            called = item.get("called_symbol") or item.get("callee")
            resolved = item.get("resolved_symbol")

            source_file_node = self.file_id(caller_file)
            source = source_file_node

            if caller and caller != "<module>":
                caller_node = self.resolve_function_node(caller, None, functions)
                if caller_node:
                    source = caller_node

            target = None

            # Service.process -> method:Service.process
            if resolved and "." in str(resolved):
                parts = str(resolved).split(".")
                if len(parts) >= 2:
                    method = self.available_method(parts[-2], parts[-1])
                    if method:
                        target = method

            if target is None and called:
                target = self.resolve_object_method(caller_file, called)

            if target:
                self.add_relationship(source, target, "CALLS")

                # Preserve the variable-level evidence too:
                # service.process -> service --CALLS--> Service.process
                if called and "." in str(called):
                    obj = str(called).rsplit(".", 1)[0]
                    variable = self.variable_id(caller_file, obj)
                    if self.graph.has_node(variable):
                        self.add_relationship(variable, target, "CALLS")

    # -----------------------------------------------------------------
    # Build
    # -----------------------------------------------------------------
    def build(self):
        analyzer = CodeAnalyzer(str(self.repository_path))
        results = analyzer.analyze_repository()

        functions = set()

        for result in results:
            for item in result.get("functions", []) or []:
                info = item if isinstance(item, dict) else {"name": item}
                name = (
                    info.get("qualified_name")
                    or info.get("full_name")
                    or info.get("name")
                    or info.get("function")
                )
                if name:
                    functions.add(str(name))

            for item in result.get("nested_functions", []) or []:
                info = item if isinstance(item, dict) else {"name": item}
                name = info.get("qualified_name") or info.get("full_name")
                parent = info.get("parent_function")
                child = info.get("name") or info.get("function")
                if name:
                    functions.add(str(name))
                elif parent and child:
                    functions.add(f"{parent}.{child}")

        for result in results:
            file_path = Path(result["file"]).resolve()
            self.add_file_and_module(file_path)
            self.add_imports(file_path, result.get("imports", []))
            self.add_classes(file_path, result.get("classes", []))
            self.add_methods(file_path, result.get("methods", []))
            self.add_functions(file_path, result.get("functions", []))
            self.add_nested_functions(file_path, result.get("nested_functions", []))
            self.add_variables(file_path, result.get("variables", []))
            self.add_resolved_variables(file_path, result.get("resolved_variables", []))
            self.add_inheritance(result.get("inheritance", []))

        # Second pass: imports and calls can now resolve against all nodes.
        for result in results:
            file_path = Path(result["file"]).resolve()
            self.add_imports(file_path, result.get("imports", []))
            self.add_call_details(file_path, result.get("call_details", []), functions)
            self.add_resolved_calls(file_path, result.get("resolved_calls", []), functions)

        return self.to_dict()

    # -----------------------------------------------------------------
    # Export / display
    # -----------------------------------------------------------------
    def to_dict(self):
        nodes = []
        for node_id, data in self.graph.nodes(data=True):
            node = {"id": node_id}
            node.update(data)
            nodes.append(node)

        edges = []
        for source, target, data in self.graph.edges(data=True):
            edge = {"source": source, "target": target}
            edge.update(data)
            edges.append(edge)

        return {"nodes": nodes, "edges": edges}

    def save_json(self, output_path):
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        return output_path

    def print_graph(self):
        print("=" * 70)
        print("REPOSITORY KNOWLEDGE GRAPH")
        print("=" * 70)
        print(f"\nNodes: {self.graph.number_of_nodes()}")
        print(f"Edges: {self.graph.number_of_edges()}")

        print("\nNODES:")
        for node_id, data in self.graph.nodes(data=True):
            print(f"  {node_id} [{data.get('type')}]")

        print("\nRELATIONSHIPS:")
        for source, target, data in self.graph.edges(data=True):
            print(
                f"  {source} --{data.get('relationship')}--> {target}"
            )

    def print_statistics(self):
        print("\n" + "=" * 70)
        print("GRAPH STATISTICS")
        print("=" * 70)
        print(f"Nodes: {self.graph.number_of_nodes()}")
        print(f"Edges: {self.graph.number_of_edges()}")

        node_types = {}
        for _, data in self.graph.nodes(data=True):
            t = data.get("type", "unknown")
            node_types[t] = node_types.get(t, 0) + 1

        print("\nNode Types:")
        for t, count in sorted(node_types.items()):
            print(f"  {t}: {count}")

        rel_types = {}
        for _, _, data in self.graph.edges(data=True):
            r = data.get("relationship", "unknown")
            rel_types[r] = rel_types.get(r, 0) + 1

        print("\nRelationship Types:")
        for r, count in sorted(rel_types.items()):
            print(f"  {r}: {count}")


def build_knowledge_graph(repository_path, output_path=None):
    builder = RepositoryKnowledgeGraph(repository_path)
    builder.build()
    if output_path:
        builder.save_json(output_path)
    return builder


if __name__ == "__main__":
    repository = r"data\test_repo"
    output = r"output\graph\repository_graph.json"

    builder = build_knowledge_graph(repository, output)
    builder.print_graph()
    builder.print_statistics()
    print("\nKnowledge graph saved to:")
    print(Path(output).resolve())
