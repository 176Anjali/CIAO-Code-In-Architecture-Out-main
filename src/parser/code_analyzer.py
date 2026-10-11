import ast
import os
import json
import builtins


class CodeAnalyzer:

    def __init__(self, repository_path):
        self.repository_path = repository_path
        self.symbol_index = {}
        self.builtin_names = set(dir(builtins))

        self.ignored_calls = {
            "print", "open", "len", "range", "str", "list", "dict",
            "set", "sum", "cast", "isinstance", "getattr", "setattr",
            "staticmethod", "classmethod", "super", "append", "extend",
            "items", "keys", "get", "join", "strip", "startswith",
            "endswith", "encode", "decode", "sleep",
        }

    # ==========================================================
    # FILE ANALYSIS
    # ==========================================================

    def analyze_file(self, file_path):
        with open(file_path, "r", encoding="utf-8", errors="ignore") as file:
            source_code = file.read()

        try:
            tree = ast.parse(source_code)
        except SyntaxError:
            return None

        result = {
            "file": file_path,
            "classes": [],
            "functions": [],
            "methods": [],
            "imports": [],
            "import_aliases": {},
            "calls": [],
            "resolved_calls": [],
            "variables": [],
            "resolved_variables": [],
            "inheritance": [],
            "nested_functions": [],
            "function_relationships": [],
            "call_details": [],
            "assigned_from": [],
        }

        parent_map = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parent_map[child] = parent

        # ------------------------------------------------------
        # Import information
        # ------------------------------------------------------

        import_aliases = {}
        imported_functions = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    result["imports"].append(alias.name)

                    # Python semantics:
                    # import networkx as nx -> nx == networkx
                    # import networkx       -> networkx == networkx
                    local_name = (
                        alias.asname
                        if alias.asname
                        else alias.name.split(".")[0]
                    )

                    import_aliases[local_name] = alias.name

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    result["imports"].append(node.module)

                for alias in node.names:
                    result["imports"].append(alias.name)

                    local_name = alias.asname if alias.asname else alias.name
                    imported_functions.add(local_name)

                    if node.module:
                        import_aliases[local_name] = (
                            f"{node.module}.{alias.name}"
                        )

        result["imports"] = sorted(set(result["imports"]))
        result["import_aliases"] = dict(sorted(import_aliases.items()))

        # ------------------------------------------------------
        # Classes
        # ------------------------------------------------------

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue

            class_info = {
                "name": node.name,
                "bases": [self._get_name(base) for base in node.bases],
            }
            result["classes"].append(class_info)

            for base in node.bases:
                parent_name = self._get_name(base)
                if parent_name:
                    result["inheritance"].append({
                        "child": node.name,
                        "parent": parent_name,
                    })

            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    result["methods"].append({
                        "class": node.name,
                        "name": child.name,
                    })

        # ------------------------------------------------------
        # Function / nested-function metadata
        # ------------------------------------------------------

        function_scopes = self._build_function_scopes(tree, parent_map)
        result["_function_scopes"] = function_scopes

        for scope in function_scopes.values():
            if scope["class_name"]:
                continue

            if scope["parent_function"]:
                result["nested_functions"].append({
                    "name": scope["name"],
                    "qualified_name": scope["qualified_name"],
                    "parent_function": scope["parent_function"],
                    "parent_qualified_name": scope["parent_qualified_name"],
                    "class": scope["class_name"],
                })

                result["function_relationships"].append({
                    "source": scope["parent_qualified_name"],
                    "target": scope["qualified_name"],
                    "relationship": "DEFINES",
                })
            else:
                result["functions"].append(scope["name"])

        result["nested_functions"].sort(
            key=lambda item: item["qualified_name"]
        )
        result["functions"] = sorted(set(result["functions"]))

        # ------------------------------------------------------
        # Variables / assignments
        # ------------------------------------------------------

        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            if not isinstance(node.value, ast.Call):
                continue

            call_name = self._get_call_name(node.value.func)
            if not call_name:
                continue

            targets = [
                target.id
                for target in node.targets
                if isinstance(target, ast.Name)
            ]

            for target_name in targets:
                if "." not in call_name:
                    result["variables"].append({
                        "name": target_name,
                        "type": call_name,
                    })
                    result["assigned_from"].append({
                        "variable": target_name,
                        "source": call_name,
                        "assignment_type": "direct_call",
                    })
                else:
                    result["assigned_from"].append({
                        "variable": target_name,
                        "source": call_name,
                        "assignment_type": "attribute_call",
                    })

        # ------------------------------------------------------
        # Call-site extraction
        # ------------------------------------------------------

        seen_calls = set()
        seen_details = set()

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            raw_callee = self._get_call_name(node.func)
            if not raw_callee:
                continue

            caller = self._get_enclosing_scope(
                node, parent_map, function_scopes
            )

            callee = self._resolve_callee(
                raw_callee,
                caller,
                function_scopes,
                import_aliases,
            )

            short_name = raw_callee.split(".")[-1]

            if short_name in self.ignored_calls:
                continue

            if callee not in seen_calls:
                result["calls"].append(callee)
                seen_calls.add(callee)

            call_detail = {
                "caller": caller,
                "callee": callee,
                "raw_callee": raw_callee,
                "type": "unclassified",
            }

            # Preserve explicit import evidence.
            if short_name in imported_functions:
                call_detail["imported_as"] = import_aliases.get(
                    short_name, short_name
                )
            elif "." in raw_callee:
                root = raw_callee.split(".", 1)[0]
                if root in import_aliases:
                    call_detail["imported_as"] = import_aliases[root]

            detail_key = (caller, callee)
            if detail_key not in seen_details:
                result["call_details"].append(call_detail)
                seen_details.add(detail_key)

        result["calls"] = sorted(set(result["calls"]))

        # Internal helper metadata is removed before returning.
        result.pop("_function_scopes", None)

        return result

    # ==========================================================
    # FUNCTION SCOPE INDEX
    # ==========================================================

    def _build_function_scopes(self, tree, parent_map):
        scopes = {}

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            class_name = None
            parent_function_node = None

            current = parent_map.get(node)
            while current is not None:
                if isinstance(current, ast.ClassDef):
                    class_name = current.name
                    break

                if isinstance(
                    current, (ast.FunctionDef, ast.AsyncFunctionDef)
                ):
                    parent_function_node = current
                    break

                current = parent_map.get(current)

            if parent_function_node is None:
                qualified_name = node.name
                parent_function = None
                parent_qualified_name = None
            else:
                parent_scope = scopes.get(id(parent_function_node))

                if parent_scope:
                    parent_qualified_name = parent_scope["qualified_name"]
                else:
                    parent_qualified_name = self._build_qualified_function_name(
                        parent_function_node, parent_map
                    )

                qualified_name = (
                    f"{parent_qualified_name}.{node.name}"
                )
                parent_function = parent_function_node.name

            scopes[id(node)] = {
                "name": node.name,
                "qualified_name": qualified_name,
                "parent_function": parent_function,
                "parent_qualified_name": parent_qualified_name,
                "class_name": class_name,
                "node": node,
            }

        return scopes

    def _build_qualified_function_name(self, node, parent_map):
        parts = [node.name]
        current = parent_map.get(node)

        while current is not None:
            if isinstance(
                current, (ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                parts.append(current.name)
            elif isinstance(current, ast.ClassDef):
                return current.name + "." + ".".join(reversed(parts))
            current = parent_map.get(current)

        return ".".join(reversed(parts))

    # ==========================================================
    # FUNCTION CONTEXT
    # ==========================================================

    def _get_function_context(self, node, parent_map):
        parent_function = None
        class_name = None

        current = parent_map.get(node)

        while current is not None:
            if isinstance(current, ast.ClassDef):
                class_name = current.name
                break

            if isinstance(
                current, (ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                parent_function = current.name
                break

            current = parent_map.get(current)

        return {
            "class_name": class_name,
            "parent_function": parent_function,
        }

    # ==========================================================
    # ENCLOSING SCOPE
    # ==========================================================

    def _get_enclosing_scope(
        self,
        node,
        parent_map,
        function_scopes=None,
    ):
        current = parent_map.get(node)

        while current is not None:
            if isinstance(
                current, (ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                if function_scopes:
                    scope = function_scopes.get(id(current))
                    if scope:
                        return scope["qualified_name"]
                return current.name

            if isinstance(current, ast.ClassDef):
                return current.name

            current = parent_map.get(current)

        return "<module>"

    # ==========================================================
    # NAME HELPERS
    # ==========================================================

    def _get_name(self, node):
        if isinstance(node, ast.Name):
            return node.id

        if isinstance(node, ast.Attribute):
            parent = self._get_name(node.value)
            if parent:
                return f"{parent}.{node.attr}"
            return node.attr

        if isinstance(node, ast.Constant):
            return str(node.value)

        return "Unknown"

    def _get_call_name(self, node):
        if isinstance(node, ast.Name):
            return node.id

        if isinstance(node, ast.Attribute):
            parent = self._get_call_name(node.value)
            if parent:
                return f"{parent}.{node.attr}"
            return node.attr

        return None

    # ==========================================================
    # NESTED FUNCTION LOOKUP
    # ==========================================================

    def _nested_function_symbols(self, analysis):
        symbols = {}

        for nested in analysis["nested_functions"]:
            symbols[nested["qualified_name"]] = nested

        return symbols

    def _find_nested_function(
        self,
        function_name,
        caller,
        analysis,
    ):
        symbols = self._nested_function_symbols(analysis)

        # If caller is kruskal.union, search:
        # kruskal.union.find -> kruskal.find -> top-level find.
        if caller != "<module>":
            parts = caller.split(".")

            # Remove the final function name from the caller scope.
            prefixes = [".".join(parts[:i]) for i in range(len(parts), 0, -1)]

            for prefix in prefixes:
                candidate = f"{prefix}.{function_name}"
                if candidate in symbols:
                    return candidate

        # Directly support a top-level qualified name if supplied.
        if function_name in symbols:
            return function_name

        return None

    def _resolve_callee(
        self,
        raw_callee,
        caller,
        function_scopes,
        import_aliases,
    ):
        # Qualified imported module calls such as nx.Graph are
        # intentionally kept as nx.Graph. Import evidence is stored
        # separately in imported_as.
        if "." in raw_callee:
            return raw_callee

        # Resolve a bare nested function name against lexical scope.
        # We cannot use function_scopes directly here because nested
        # scopes are indexed by AST node; caller scope is enough to
        # construct the lexical candidates.
        return raw_callee

    # ==========================================================
    # OBJECT METHOD DETECTION
    # ==========================================================

    def _is_object_method_call(self, function_name, analysis):
        if "." not in function_name:
            return False

        receiver = function_name.split(".", 1)[0]

        # Imported aliases/modules are external calls.
        import_aliases = analysis.get("import_aliases", {})
        if receiver in import_aliases:
            return False

        for assignment in analysis["assigned_from"]:
            if assignment["variable"] == receiver:
                return True

        if receiver in {
            "self", "cls", "G", "G_mst", "G_orig", "ax", "fig",
            "path", "edges", "seen", "visited",
        }:
            return True

        return False

    # ==========================================================
    # CALL CLASSIFICATION
    # ==========================================================

    def _classify_call(self, call_detail, analysis):
        caller = call_detail["caller"]
        callee = call_detail["callee"]
        raw_callee = call_detail.get("raw_callee", callee)

        # ------------------------------------------------------
        # Nested function
        # ------------------------------------------------------

        nested_symbol = self._find_nested_function(
            raw_callee,
            caller,
            analysis,
        )

        if nested_symbol and nested_symbol == callee:
            return "nested_function"

        # ------------------------------------------------------
        # Project function/class/method/nested function
        # ------------------------------------------------------

        if callee in self.symbol_index:
            return "project"

        # ------------------------------------------------------
        # Imported function
        # ------------------------------------------------------

        import_aliases = analysis.get("import_aliases", {})

        if raw_callee in import_aliases:
            return "external"

        short_name = raw_callee.split(".")[-1]

        # from heapq import heappop
        for imported in analysis["imports"]:
            if short_name == imported:
                return "external"

        # ------------------------------------------------------
        # Built-in
        # ------------------------------------------------------

        if "." not in raw_callee and raw_callee in self.builtin_names:
            return "builtin"

        # ------------------------------------------------------
        # Imported module / alias call
        # ------------------------------------------------------

        if "." in raw_callee:
            root = raw_callee.split(".", 1)[0]

            if root in import_aliases:
                return "external"

            # Also support unaliased dotted imports.
            for imported in analysis["imports"]:
                imported_root = imported.split(".")[0]
                if root == imported_root:
                    return "external"

        # ------------------------------------------------------
        # Object/collection method
        # ------------------------------------------------------

        if self._is_object_method_call(raw_callee, analysis):
            return "object_method"

        return "unknown"

    # ==========================================================
    # BUILD CALL DETAILS
    # ==========================================================

    def _build_call_details(self, results):
        for analysis in results:
            # Resolve bare nested calls now that the analysis has
            # its nested-function metadata.
            for detail in analysis["call_details"]:
                raw_callee = detail.get(
                    "raw_callee",
                    detail["callee"],
                )

                nested_symbol = self._find_nested_function(
                    raw_callee,
                    detail["caller"],
                    analysis,
                )

                if nested_symbol:
                    detail["callee"] = nested_symbol

                detail["type"] = self._classify_call(
                    detail,
                    analysis,
                )

            analysis["calls"] = sorted(
                set(detail["callee"] for detail in analysis["call_details"])
            )

        return results

    # ==========================================================
    # VARIABLE RESOLUTION
    # ==========================================================

    def _resolve_variables(self, results):
        for analysis in results:
            for variable in analysis["variables"]:
                variable_type = variable["type"]

                if variable_type not in self.symbol_index:
                    continue

                if not self._is_class_symbol(
                    results,
                    variable_type,
                ):
                    continue

                analysis["resolved_variables"].append({
                    "variable": variable["name"],
                    "class": variable_type,
                    "defined_in": self.symbol_index[variable_type],
                })

        return results

    # ==========================================================
    # CLASS SYMBOL CHECK
    # ==========================================================

    def _is_class_symbol(self, results, symbol_name):
        for analysis in results:
            for class_info in analysis["classes"]:
                if class_info["name"] == symbol_name:
                    return True

        return False

    # ==========================================================
    # CALL RESOLUTION
    # ==========================================================

    def _resolve_calls(self, results):
        for analysis in results:
            seen = set()

            for detail in analysis["call_details"]:
                call = detail["callee"]

                if call in self.symbol_index:
                    key = (
                        detail["caller"],
                        call,
                    )

                    if key in seen:
                        continue

                    analysis["resolved_calls"].append({
                        "caller": detail["caller"],
                        "caller_file": analysis["file"],
                        "called_symbol": call,
                        "defined_in": self.symbol_index[call],
                    })

                    seen.add(key)

        return results

    # ==========================================================
    # ASSIGNMENT RESOLUTION
    # ==========================================================

    def _resolve_assignments(self, results):
        for analysis in results:
            for assignment in analysis["assigned_from"]:
                source = assignment["source"]

                if source in self.symbol_index:
                    assignment["resolved_source"] = source
                    assignment["defined_in"] = self.symbol_index[source]

                    if self._is_class_symbol(results, source):
                        assignment["assignment_type"] = "instance_creation"
                    else:
                        assignment["assignment_type"] = "function_result"
                else:
                    assignment["resolved_source"] = None

        return results

    # ==========================================================
    # SYMBOL INDEX HELPERS
    # ==========================================================

    def _add_function_symbols(self, analysis, file_path):
        # Top-level functions.
        for function_name in analysis["functions"]:
            self.symbol_index[function_name] = file_path

        # Qualified nested functions.
        for nested in analysis["nested_functions"]:
            self.symbol_index[
                nested["qualified_name"]
            ] = file_path

    # ==========================================================
    # REPOSITORY ANALYSIS
    # ==========================================================

    def analyze_repository(self):
        results = []
        self.symbol_index = {}

        # ------------------------------------------------------
        # PASS 1: Parse all Python files and build symbols.
        # ------------------------------------------------------

        for root, _, files in os.walk(self.repository_path):
            normalized_root = root.replace("\\", "/")

            ignored_folders = [
                "/.git",
                "/.history",
                "/__pycache__",
                "/venv",
                "/.venv",
                "/node_modules",
            ]

            if any(
                ignored in normalized_root
                for ignored in ignored_folders
            ):
                continue

            for file in files:
                if not file.endswith(".py"):
                    continue

                file_path = os.path.join(root, file)
                analysis = self.analyze_file(file_path)

                if not analysis:
                    continue

                results.append(analysis)

                for class_info in analysis["classes"]:
                    self.symbol_index[
                        class_info["name"]
                    ] = file_path

                for method in analysis["methods"]:
                    method_name = (
                        f"{method['class']}."
                        f"{method['name']}"
                    )
                    self.symbol_index[method_name] = file_path

                self._add_function_symbols(
                    analysis,
                    file_path,
                )

        # ------------------------------------------------------
        # PASS 2: Class instance resolution.
        # ------------------------------------------------------

        self._resolve_variables(results)

        # ------------------------------------------------------
        # PASS 3: Assignment resolution.
        # ------------------------------------------------------

        self._resolve_assignments(results)

        # ------------------------------------------------------
        # PASS 4: Call classification and lexical resolution.
        # ------------------------------------------------------

        self._build_call_details(results)

        # ------------------------------------------------------
        # PASS 5: Project call resolution.
        # ------------------------------------------------------

        self._resolve_calls(results)

        return results

    # ==========================================================
    # SAVE RESULTS
    # ==========================================================

    def save_results(self, output_path):
        results = self.analyze_repository()

        output_directory = os.path.dirname(output_path)
        if output_directory:
            os.makedirs(output_directory, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as file:
            json.dump(results, file, indent=4)

        return results
