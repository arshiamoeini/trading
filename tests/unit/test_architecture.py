from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def test_domain_has_no_framework_dependencies() -> None:
    forbidden = {"fastapi", "pydantic", "sqlalchemy", "asyncpg"}
    root = Path("src/option_platform/domain")
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        assert imports.isdisjoint(forbidden), f"{path} imports a forbidden framework"
