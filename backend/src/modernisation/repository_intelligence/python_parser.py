"""Tree-sitter based structural extraction for Python sources.

Produces symbols (classes, functions, methods, module-level assignments), import edges and call/attribute
references with 1-based line numbers. Parsing is error-tolerant: tree-sitter yields a tree even for files
with syntax errors, and those files are flagged rather than skipped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser


@dataclass
class Symbol:
    name: str
    qualified_name: str
    kind: str
    start_line: int
    end_line: int
    signature: str | None = None
    docstring: str | None = None
    parent: str | None = None


@dataclass
class ImportEdge:
    module: str
    name: str | None
    alias: str | None
    level: int
    line: int


@dataclass
class Reference:
    name: str
    qualifier: str | None
    kind: str
    line: int
    column: int


@dataclass
class ParsedFile:
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[ImportEdge] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)
    has_errors: bool = False


@lru_cache(maxsize=1)
def _parser() -> Parser:
    return Parser(Language(tspython.language()))


def _text(node: Node | None) -> str:
    if node is None or node.text is None:
        return ""
    return node.text.decode("utf-8", "replace")


def _docstring(block: Node | None) -> str | None:
    if block is None:
        return None
    for child in block.named_children:
        if child.type == "expression_statement" and child.named_children:
            first = child.named_children[0]
            if first.type == "string":
                raw = _text(first)
                stripped = raw.strip("rRbBuUfF")
                for quote in ('"""', "'''", '"', "'"):
                    if stripped.startswith(quote) and stripped.endswith(quote) and len(stripped) >= 2 * len(quote):
                        stripped = stripped[len(quote) : -len(quote)]
                        break
                doc = stripped.strip()
                return doc[:500] if doc else None
        break
    return None


def _dotted(node: Node) -> str:
    return "".join(_text(c) for c in node.children if c.type in {"identifier", "."})


class _Extractor:
    def __init__(self) -> None:
        self.out = ParsedFile()
        self.scope: list[tuple[str, str]] = []  # (name, kind)

    def qualified(self, name: str) -> str:
        return ".".join([s for s, _ in self.scope] + [name])

    def visit(self, node: Node) -> None:
        handler = getattr(self, f"on_{node.type}", None)
        if handler is not None and handler(node) is False:
            return
        for child in node.children:
            self.visit(child)

    # --- definitions ---------------------------------------------------------------------------------
    def on_class_definition(self, node: Node) -> bool:
        name = _text(node.child_by_field_name("name"))
        supers = node.child_by_field_name("superclasses")
        body = node.child_by_field_name("body")
        start = (
            node.parent.start_point.row
            if node.parent and node.parent.type == "decorated_definition"
            else node.start_point.row
        )
        self.out.symbols.append(
            Symbol(
                name=name,
                qualified_name=self.qualified(name),
                kind="class",
                start_line=start + 1,
                end_line=node.end_point.row + 1,
                signature=f"class {name}{_text(supers)}",
                docstring=_docstring(body),
                parent=".".join(s for s, _ in self.scope) or None,
            )
        )
        self._visit_children_with_scope(node, name, "class")
        return False

    def on_function_definition(self, node: Node) -> bool:
        name = _text(node.child_by_field_name("name"))
        params = _text(node.child_by_field_name("parameters"))
        ret = node.child_by_field_name("return_type")
        body = node.child_by_field_name("body")
        in_class = bool(self.scope) and self.scope[-1][1] == "class"
        is_async = any(c.type == "async" for c in node.children)
        start = (
            node.parent.start_point.row
            if node.parent and node.parent.type == "decorated_definition"
            else node.start_point.row
        )
        sig = f"{'async ' if is_async else ''}def {name}{params}" + (f" -> {_text(ret)}" if ret else "")
        self.out.symbols.append(
            Symbol(
                name=name,
                qualified_name=self.qualified(name),
                kind="method" if in_class else "function",
                start_line=start + 1,
                end_line=node.end_point.row + 1,
                signature=sig,
                docstring=_docstring(body),
                parent=".".join(s for s, _ in self.scope) or None,
            )
        )
        self._visit_children_with_scope(node, name, "function")
        return False

    def _visit_children_with_scope(self, node: Node, name: str, kind: str) -> None:
        self.scope.append((name, kind))
        try:
            for child in node.children:
                self.visit(child)
        finally:
            self.scope.pop()

    def on_expression_statement(self, node: Node) -> None:
        # Module- and class-level assignments are useful navigation targets (constants, settings).
        if self.scope and self.scope[-1][1] == "function":
            return
        for child in node.named_children:
            if child.type == "assignment":
                left = child.child_by_field_name("left")
                if left is not None and left.type == "identifier":
                    name = _text(left)
                    self.out.symbols.append(
                        Symbol(
                            name=name,
                            qualified_name=self.qualified(name),
                            kind="variable",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            signature=_text(child)[:200],
                            parent=".".join(s for s, _ in self.scope) or None,
                        )
                    )

    # --- imports ---------------------------------------------------------------------------------------
    def on_import_statement(self, node: Node) -> bool:
        line = node.start_point.row + 1
        for child in node.named_children:
            if child.type == "dotted_name":
                self.out.imports.append(ImportEdge(_dotted(child), None, None, 0, line))
            elif child.type == "aliased_import":
                target = child.child_by_field_name("name")
                alias = child.child_by_field_name("alias")
                self.out.imports.append(ImportEdge(_dotted(target) if target else "", None, _text(alias), 0, line))
        return False

    def on_import_from_statement(self, node: Node) -> bool:
        line = node.start_point.row + 1
        module_node = node.child_by_field_name("module_name")
        level = 0
        module = ""
        if module_node is not None:
            if module_node.type == "relative_import":
                for c in module_node.children:
                    if c.type == "import_prefix":
                        level = _text(c).count(".")
                    elif c.type == "dotted_name":
                        module = _dotted(c)
            else:
                module = _dotted(module_node)
        names: list[tuple[str | None, str | None]] = []
        for child in node.children_by_field_name("name"):
            if child.type == "dotted_name":
                names.append((_dotted(child), None))
            elif child.type == "aliased_import":
                target = child.child_by_field_name("name")
                alias_node = child.child_by_field_name("alias")
                names.append((_dotted(target) if target else "", _text(alias_node) or None))
        if any(c.type == "wildcard_import" for c in node.children):
            names.append(("*", None))
        for imported, imported_alias in names or [(None, None)]:
            self.out.imports.append(ImportEdge(module, imported, imported_alias, level, line))
        return False

    # --- references ------------------------------------------------------------------------------------
    def on_call(self, node: Node) -> None:
        fn = node.child_by_field_name("function")
        if fn is None:
            return
        if fn.type == "identifier":
            self.out.references.append(
                Reference(_text(fn), None, "call", fn.start_point.row + 1, fn.start_point.column + 1)
            )
        elif fn.type == "attribute":
            attr = fn.child_by_field_name("attribute")
            obj = fn.child_by_field_name("object")
            if attr is not None:
                self.out.references.append(
                    Reference(
                        _text(attr),
                        _text(obj)[:200] if obj is not None else None,
                        "call",
                        attr.start_point.row + 1,
                        attr.start_point.column + 1,
                    )
                )

    def on_attribute(self, node: Node) -> None:
        parent = node.parent
        if parent is not None and parent.type == "call" and parent.child_by_field_name("function") == node:
            return  # already recorded as a call
        attr = node.child_by_field_name("attribute")
        obj = node.child_by_field_name("object")
        if attr is not None and obj is not None and obj.type in {"identifier", "attribute"}:
            self.out.references.append(
                Reference(
                    _text(attr), _text(obj)[:200], "attribute", attr.start_point.row + 1, attr.start_point.column + 1
                )
            )


def parse_python(source: bytes) -> ParsedFile:
    tree = _parser().parse(source)
    extractor = _Extractor()
    extractor.visit(tree.root_node)
    extractor.out.has_errors = tree.root_node.has_error
    return extractor.out
