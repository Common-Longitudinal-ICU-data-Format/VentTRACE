"""Raw CLIF sources cross the clifpy timezone boundary before analysis."""

import ast
from pathlib import Path


ROOT = Path(__file__).parent.parent
CODE_FILES = sorted((ROOT / "code").glob("*.py"))
POLARS_READERS = {"read_csv", "read_parquet", "scan_csv", "scan_parquet"}


def _calls(tree, attribute):
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == attribute
    ]


def _keyword(call, name):
    return next((item.value for item in call.keywords if item.arg == name), None)


def test_raw_clif_sources_do_not_use_polars_io():
    violations = []
    for path in CODE_FILES:
        tree = ast.parse(path.read_text())
        for function in [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]:
            raw_path_names = set()
            for assignment in [
                node
                for node in ast.walk(function)
                if isinstance(node, (ast.Assign, ast.AnnAssign))
            ]:
                value = assignment.value
                expression = ast.unparse(value)
                if "clif_" not in expression or not (
                    "DATA_DIR" in expression or "data_directory" in expression
                ):
                    continue
                targets = (
                    assignment.targets
                    if isinstance(assignment, ast.Assign)
                    else [assignment.target]
                )
                raw_path_names.update(
                    target.id for target in targets if isinstance(target, ast.Name)
                )

            for call in [node for node in ast.walk(function) if isinstance(node, ast.Call)]:
                if not (
                    isinstance(call.func, ast.Attribute)
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id == "pl"
                    and call.func.attr in POLARS_READERS
                    and call.args
                ):
                    continue
                argument = call.args[0]
                argument_text = ast.unparse(argument)
                argument_names = {
                    node.id for node in ast.walk(argument) if isinstance(node, ast.Name)
                }
                if (
                    "clif_" in argument_text
                    and ("DATA_DIR" in argument_text or "data_directory" in argument_text)
                ) or raw_path_names.intersection(argument_names):
                    violations.append(f"{path.name}:{call.lineno}:{call.func.attr}")

    assert violations == []


def test_from_file_loaders_receive_configured_timezone():
    violations = []
    for path in CODE_FILES:
        tree = ast.parse(path.read_text())
        for call in _calls(tree, "from_file"):
            timezone = _keyword(call, "timezone")
            if isinstance(timezone, ast.Name) and timezone.id in {"TIMEZONE", "timezone"}:
                continue
            if any(keyword.arg is None for keyword in call.keywords):
                continue  # load_optional forwards caller-supplied timezone through **kwargs.
            violations.append(f"{path.name}:{call.lineno}")

        for call in [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "load_optional"
        ]:
            timezone = _keyword(call, "timezone")
            if not (isinstance(timezone, ast.Name) and timezone.id == "TIMEZONE"):
                violations.append(f"{path.name}:{call.lineno}:load_optional")

    assert violations == []


def test_lazy_clifpy_load_is_fetched_with_site_timezone():
    violations = []
    for path in CODE_FILES:
        tree = ast.parse(path.read_text())
        for function in [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]:
            lazy_loads = [
                call
                for call in ast.walk(function)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "load_data"
                and isinstance(_keyword(call, "lazy"), ast.Constant)
                and _keyword(call, "lazy").value is True
            ]
            if not lazy_loads:
                continue
            fetches = [
                call
                for call in ast.walk(function)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "fetch_lazy_result"
            ]
            if not any(
                isinstance(_keyword(call, "site_tz"), ast.Name)
                and _keyword(call, "site_tz").id == "TIMEZONE"
                for call in fetches
            ):
                violations.append(f"{path.name}:{function.lineno}")

    assert violations == []
