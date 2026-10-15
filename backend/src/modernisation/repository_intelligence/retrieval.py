"""Keyword and structure-aware code retrieval over an index snapshot.

Retrieval combines:

* ``keyword``      BM25 over code-aware tokens (snake/camel-case split identifiers + path tokens)
* ``symbol``       exact symbol-definition matches for identifiers named in the request
* ``reference``    call sites / attribute uses for dotted names (``yaml.load``) and called identifiers
* ``import_graph`` modules that import a package or module the request names
* ``test_link``    test files that import or reference the retrieved implementation
* ``config``       dependency manifests and configuration files relevant to the request

Every result carries repository, commit SHA, path, symbol (where available), a 1-based inclusive line
range and the retrieval method, so any statement built on it can be traced to source.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from modernisation.db.models import (
    Blob,
    BlobImport,
    BlobReference,
    BlobSymbol,
    IndexSnapshot,
    Repository,
    SnapshotFile,
)
from modernisation.repository_intelligence.languages import is_dependency_manifest, module_name_for_path

IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
DOTTED_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\b")
CAMEL_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")

STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "can",
        "could",
        "do",
        "does",
        "for",
        "from",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "may",
        "must",
        "no",
        "not",
        "of",
        "on",
        "or",
        "our",
        "should",
        "so",
        "such",
        "that",
        "the",
        "their",
        "then",
        "there",
        "these",
        "this",
        "to",
        "update",
        "upgrade",
        "use",
        "used",
        "using",
        "via",
        "was",
        "we",
        "when",
        "which",
        "will",
        "with",
        "without",
        "would",
        "you",
        "your",
        "make",
        "replace",
        "instead",
        "fix",
        "bug",
        "issue",
        "please",
        "ensure",
        "keep",
        "code",
        "function",
        "method",
        "class",
        "file",
        "files",
        "module",
        "self",
        "def",
        "return",
        "none",
        "true",
        "false",
        "import",
        "pass",
        "raise",
        "elif",
        "else",
        "try",
        "except",
        "finally",
        "while",
        "lambda",
        "yield",
        "async",
        "await",
        "global",
        "nonlocal",
        "assert",
        "del",
        "break",
        "continue",
        "new",
        "old",
        "version",
        "versions",
        "test",
        "tests",
        "support",
        "should",
        "all",
        "any",
        "also",
        "add",
        "remove",
        "change",
        "changes",
    ]
)

# Distribution name -> import name for packages whose names differ.
DIST_TO_IMPORT = {
    "pyyaml": "yaml",
    "beautifulsoup4": "bs4",
    "pillow": "PIL",
    "python-dateutil": "dateutil",
    "scikit-learn": "sklearn",
    "opencv-python": "cv2",
    "pyjwt": "jwt",
    "typing-extensions": "typing_extensions",
    "protobuf": "google.protobuf",
    "attrs": "attr",
    "msgpack-python": "msgpack",
    "importlib-metadata": "importlib_metadata",
    "python-multipart": "multipart",
}


@dataclass
class CodeReference:
    repository: str
    commit_sha: str
    path: str
    start_line: int
    end_line: int
    retrieval_method: str
    score: float
    symbol: str | None = None
    symbol_kind: str | None = None
    reason: str = ""
    methods: list[str] = field(default_factory=list)
    is_test: bool = False
    is_config: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def split_identifier(token: str) -> list[str]:
    parts: list[str] = []
    for piece in token.split("_"):
        if not piece:
            continue
        sub = CAMEL_RE.findall(piece)
        parts.extend(s.lower() for s in sub if s)
    return parts


def code_tokens(text: str) -> list[str]:
    out: list[str] = []
    for ident in IDENT_RE.findall(text):
        low = ident.lower()
        out.append(low)
        sub = split_identifier(ident)
        if len(sub) > 1:
            out.extend(sub)
    return out


def query_terms(text: str) -> list[str]:
    return [t for t in dict.fromkeys(code_tokens(text)) if len(t) > 1 and t not in STOPWORDS]


@dataclass(frozen=True)
class SymbolRow:
    name: str
    qualified_name: str
    kind: str
    start_line: int
    end_line: int
    signature: str | None
    docstring: str | None
    parent: str | None


@dataclass(frozen=True)
class ImportRow:
    module: str
    name: str | None
    alias: str | None
    level: int
    line: int


@dataclass(frozen=True)
class RefRow:
    name: str
    qualifier: str | None
    kind: str
    line: int
    column: int


@dataclass
class FileRecord:
    path: str
    blob_sha: str
    language: str | None
    is_test: bool
    is_config: bool
    module: str | None


@dataclass
class SnapshotData:
    repository: str
    commit_sha: str
    snapshot_id: int
    files: dict[str, FileRecord]
    contents: dict[str, str]
    symbols: dict[str, list[SymbolRow]]
    imports: dict[str, list[ImportRow]]
    references: dict[str, list[RefRow]]
    doc_tf: dict[str, Counter[str]]
    doc_len: dict[str, int]
    df: Counter[str]
    module_to_path: dict[str, str]

    def lines(self, path: str) -> list[str]:
        return self.contents.get(path, "").splitlines()


_CACHE: dict[int, SnapshotData] = {}


def load_snapshot(session: Session, snapshot: IndexSnapshot) -> SnapshotData:
    """Load an index snapshot into memory for retrieval (cached per snapshot id)."""
    if snapshot.id in _CACHE:
        return _CACHE[snapshot.id]
    repo = session.get(Repository, snapshot.repository_id)
    assert repo is not None
    rows = session.execute(
        select(
            SnapshotFile.path,
            SnapshotFile.blob_sha,
            SnapshotFile.language,
            SnapshotFile.is_test,
            SnapshotFile.is_config,
            Blob.content,
        )
        .join(Blob, Blob.sha == SnapshotFile.blob_sha)
        .where(SnapshotFile.snapshot_id == snapshot.id)
    ).all()
    files: dict[str, FileRecord] = {}
    contents: dict[str, str] = {}
    by_blob: dict[str, list[str]] = defaultdict(list)
    for path, blob_sha, language, is_test, is_config, content in rows:
        files[path] = FileRecord(
            path, blob_sha, language, is_test, is_config, module_name_for_path(path) if language == "python" else None
        )
        if content is not None:
            contents[path] = content
        by_blob[blob_sha].append(path)

    blob_ids = list(by_blob)
    symbols: dict[str, list[SymbolRow]] = defaultdict(list)
    imports: dict[str, list[ImportRow]] = defaultdict(list)
    references: dict[str, list[RefRow]] = defaultdict(list)
    # Plain immutable rows (not ORM instances): the cache outlives the session and must never
    # interfere with objects the caller's session is tracking.
    for i in range(0, len(blob_ids), 2000):
        chunk = blob_ids[i : i + 2000]
        for row in session.execute(
            select(
                BlobSymbol.blob_sha,
                BlobSymbol.name,
                BlobSymbol.qualified_name,
                BlobSymbol.kind,
                BlobSymbol.start_line,
                BlobSymbol.end_line,
                BlobSymbol.signature,
                BlobSymbol.docstring,
                BlobSymbol.parent,
            ).where(BlobSymbol.blob_sha.in_(chunk))
        ):
            sym = SymbolRow(*row[1:])
            for p in by_blob[row[0]]:
                symbols[p].append(sym)
        for irow in session.execute(
            select(
                BlobImport.blob_sha,
                BlobImport.module,
                BlobImport.name,
                BlobImport.alias,
                BlobImport.level,
                BlobImport.line,
            ).where(BlobImport.blob_sha.in_(chunk))
        ):
            imp = ImportRow(*irow[1:])
            for p in by_blob[irow[0]]:
                imports[p].append(imp)
        for rrow in session.execute(
            select(
                BlobReference.blob_sha,
                BlobReference.name,
                BlobReference.qualifier,
                BlobReference.kind,
                BlobReference.line,
                BlobReference.column,
            ).where(BlobReference.blob_sha.in_(chunk))
        ):
            ref = RefRow(*rrow[1:])
            for p in by_blob[rrow[0]]:
                references[p].append(ref)

    doc_tf: dict[str, Counter[str]] = {}
    doc_len: dict[str, int] = {}
    df: Counter[str] = Counter()
    for path in files:
        tokens = code_tokens(contents.get(path, "")) + code_tokens(path.replace("/", " ").replace(".", " ")) * 3
        tf = Counter(tokens)
        doc_tf[path] = tf
        doc_len[path] = max(1, len(tokens))
        df.update(tf.keys())

    module_to_path: dict[str, str] = {}
    for path, rec in files.items():
        if rec.module and (rec.module not in module_to_path or path.endswith("__init__.py") is False):
            module_to_path.setdefault(rec.module, path)

    data = SnapshotData(
        repo.name,
        snapshot.commit_sha,
        snapshot.id,
        files,
        contents,
        dict(symbols),
        dict(imports),
        dict(references),
        doc_tf,
        doc_len,
        df,
        module_to_path,
    )
    if len(_CACHE) > 16:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[snapshot.id] = data
    return data


def clear_cache() -> None:
    _CACHE.clear()


# --------------------------------------------------------------------------------------------------------
# primitive searches


def bm25(data: SnapshotData, terms: list[str], k1: float = 1.4, b: float = 0.75) -> list[tuple[str, float]]:
    n = len(data.files) or 1
    avgdl = sum(data.doc_len.values()) / n
    scores: dict[str, float] = {}
    for term in terms:
        dfi = data.df.get(term, 0)
        if dfi == 0:
            continue
        idf = math.log(1 + (n - dfi + 0.5) / (dfi + 0.5))
        for path, tf in data.doc_tf.items():
            f = tf.get(term, 0)
            if f:
                denom = f + k1 * (1 - b + b * data.doc_len[path] / avgdl)
                scores[path] = scores.get(path, 0.0) + idf * f * (k1 + 1) / denom
    return sorted(scores.items(), key=lambda kv: -kv[1])


def enclosing_symbol(data: SnapshotData, path: str, line: int) -> SymbolRow | None:
    best: SymbolRow | None = None
    for sym in data.symbols.get(path, []):
        if sym.kind == "variable":
            continue
        if sym.start_line <= line <= sym.end_line and (
            best is None or (sym.end_line - sym.start_line) < (best.end_line - best.start_line)
        ):
            best = sym
    return best


def text_search(
    data: SnapshotData,
    query: str,
    *,
    regex: bool = False,
    case_sensitive: bool = False,
    limit: int = 100,
    path_prefix: str | None = None,
) -> list[dict[str, Any]]:
    flags = 0 if case_sensitive else re.IGNORECASE
    pattern = re.compile(query if regex else re.escape(query), flags)
    hits: list[dict[str, Any]] = []
    for path in sorted(data.contents):
        if path_prefix and not path.startswith(path_prefix):
            continue
        for lineno, line in enumerate(data.contents[path].splitlines(), start=1):
            if pattern.search(line):
                sym = enclosing_symbol(data, path, lineno)
                hits.append(
                    {
                        "repository": data.repository,
                        "commit_sha": data.commit_sha,
                        "path": path,
                        "start_line": lineno,
                        "end_line": lineno,
                        "text": line[:400],
                        "symbol": sym.qualified_name if sym else None,
                        "retrieval_method": "keyword",
                    }
                )
                if len(hits) >= limit:
                    return hits
    return hits


def symbol_search(data: SnapshotData, query: str, *, kind: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    q = query.lower()
    ranked: list[tuple[int, str, SymbolRow]] = []
    for path, syms in data.symbols.items():
        for sym in syms:
            if kind and sym.kind != kind:
                continue
            name, qual = sym.name.lower(), sym.qualified_name.lower()
            if name == q or qual == q:
                rank = 0
            elif name.startswith(q):
                rank = 1
            elif q in qual:
                rank = 2
            else:
                continue
            ranked.append((rank, path, sym))
    ranked.sort(key=lambda t: (t[0], t[1], t[2].start_line))
    return [
        {
            "repository": data.repository,
            "commit_sha": data.commit_sha,
            "path": path,
            "symbol": sym.qualified_name,
            "name": sym.name,
            "kind": sym.kind,
            "start_line": sym.start_line,
            "end_line": sym.end_line,
            "signature": sym.signature,
            "docstring": sym.docstring,
            "retrieval_method": "symbol",
        }
        for _, path, sym in ranked[:limit]
    ]


def resolve_import(data: SnapshotData, importer_path: str, imp: ImportRow) -> list[str]:
    """Return snapshot paths an import statement refers to (best effort, Python semantics)."""
    rec = data.files.get(importer_path)
    candidates: list[str] = []
    if imp.level:
        base = (rec.module or "").split(".") if rec and rec.module else []
        if not importer_path.endswith("__init__.py"):
            base = base[:-1]
        base = base[: len(base) - (imp.level - 1)] if imp.level > 1 else base
        module = ".".join([*base, imp.module] if imp.module else base)
    else:
        module = imp.module
    if module:
        candidates.append(module)
    if imp.name and imp.name != "*":
        candidates.append(f"{module}.{imp.name}" if module else imp.name)
    return [data.module_to_path[c] for c in candidates if c in data.module_to_path]


def import_graph(data: SnapshotData) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """(imports_of[path] -> paths it imports, importers_of[path] -> paths importing it)."""
    imports_of: dict[str, set[str]] = defaultdict(set)
    importers_of: dict[str, set[str]] = defaultdict(set)
    for path, imps in data.imports.items():
        for imp in imps:
            for target in resolve_import(data, path, imp):
                if target != path:
                    imports_of[path].add(target)
                    importers_of[target].add(path)
    return imports_of, importers_of


def find_references(
    data: SnapshotData, name: str, qualifier: str | None = None, limit: int = 200
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path, refs in sorted(data.references.items()):
        for ref in refs:
            if ref.name != name:
                continue
            if qualifier and (ref.qualifier or "").split(".")[-1] != qualifier.split(".")[-1]:
                continue
            sym = enclosing_symbol(data, path, ref.line)
            out.append(
                {
                    "repository": data.repository,
                    "commit_sha": data.commit_sha,
                    "path": path,
                    "start_line": ref.line,
                    "end_line": ref.line,
                    "kind": ref.kind,
                    "expression": f"{ref.qualifier}.{ref.name}" if ref.qualifier else ref.name,
                    "symbol": sym.qualified_name if sym else None,
                    "retrieval_method": "reference",
                    "text": _line(data, path, ref.line),
                }
            )
            if len(out) >= limit:
                return out
    return out


def _line(data: SnapshotData, path: str, line: int) -> str:
    lines = data.lines(path)
    return lines[line - 1][:400] if 0 < line <= len(lines) else ""


# --------------------------------------------------------------------------------------------------------
# hybrid retrieval for maintenance requests


def _ref_for_lines(
    data: SnapshotData, path: str, lines: list[int], method: str, score: float, reason: str
) -> list[CodeReference]:
    rec = data.files[path]
    spans: dict[tuple[int, int], SymbolRow | None] = {}
    windows: list[list[int]] = []
    for line in sorted(lines):
        sym = enclosing_symbol(data, path, line)
        if sym is not None:
            spans[(sym.start_line, sym.end_line)] = sym
        elif windows and line - 3 <= windows[-1][1] + 1:
            windows[-1][1] = line + 3  # coalesce overlapping context windows
        else:
            windows.append([max(1, line - 3), line + 3])
    for start, end in windows:
        spans[(start, end)] = None
    out = []
    for (start, end), sym in spans.items():
        out.append(
            CodeReference(
                data.repository,
                data.commit_sha,
                path,
                start,
                end,
                method,
                score,
                symbol=sym.qualified_name if sym else None,
                symbol_kind=sym.kind if sym else None,
                reason=reason,
                is_test=rec.is_test,
                is_config=rec.is_config,
            )
        )
    return out


def _whole_file(data: SnapshotData, path: str, method: str, score: float, reason: str) -> CodeReference:
    rec = data.files[path]
    n = max(1, len(data.lines(path)))
    return CodeReference(
        data.repository,
        data.commit_sha,
        path,
        1,
        n,
        method,
        score,
        reason=reason,
        is_test=rec.is_test,
        is_config=rec.is_config,
    )


def retrieve(data: SnapshotData, request: str, *, category: str | None = None, limit: int = 25) -> list[CodeReference]:
    terms = query_terms(request)
    raw_idents = [t for t in dict.fromkeys(IDENT_RE.findall(request)) if len(t) > 2 and t.lower() not in STOPWORDS]
    dotted = list(dict.fromkeys(DOTTED_RE.findall(request)))
    results: list[CodeReference] = []

    # 1. keyword (BM25), restricted to the lines that contain query terms
    term_set = set(terms)
    for rank, (path, score) in enumerate(bm25(data, terms)[:12]):
        lines = [i for i, line in enumerate(data.lines(path), start=1) if term_set & set(code_tokens(line))]
        if not lines:
            results.append(_whole_file(data, path, "keyword", score, "path matches request terms"))
            continue
        # keep the most term-dense lines to avoid flooding the result
        dense = sorted(lines, key=lambda i: -len(term_set & set(code_tokens(data.lines(path)[i - 1]))))[:6]
        results.extend(
            _ref_for_lines(
                data,
                path,
                sorted(dense),
                "keyword",
                score / (1 + 0.1 * rank),
                f"BM25 match on {sorted(term_set & set(data.doc_tf[path]))[:6]}",
            )
        )

    # 2. symbol definitions named in the request
    for ident in raw_idents:
        for path, syms in data.symbols.items():
            for sym in syms:
                if sym.name == ident or sym.qualified_name == ident:
                    rec = data.files[path]
                    results.append(
                        CodeReference(
                            data.repository,
                            data.commit_sha,
                            path,
                            sym.start_line,
                            sym.end_line,
                            "symbol",
                            50.0,
                            symbol=sym.qualified_name,
                            symbol_kind=sym.kind,
                            reason=f"defines `{ident}` named in the request",
                            is_test=rec.is_test,
                            is_config=rec.is_config,
                        )
                    )

    # 3. call sites for dotted names (e.g. datetime.utcnow, yaml.load) and for called identifiers
    for expr in dotted:
        qualifier, _, name = expr.rpartition(".")
        by_path: dict[str, list[int]] = defaultdict(list)
        for hit in find_references(data, name, qualifier):
            by_path[hit["path"]].append(hit["start_line"])
        for path, lines in by_path.items():
            results.extend(_ref_for_lines(data, path, lines, "reference", 40.0, f"uses `{expr}`"))
    for ident in raw_idents:
        by_path = defaultdict(list)
        for hit in find_references(data, ident):
            by_path[hit["path"]].append(hit["start_line"])
        for path, lines in by_path.items():
            results.extend(_ref_for_lines(data, path, lines, "reference", 15.0, f"references `{ident}`"))

    # 4. packages named in the request -> modules importing them
    lowered = request.lower()
    packages: set[str] = set()
    for dist, mod in DIST_TO_IMPORT.items():
        if re.search(rf"\b{re.escape(dist)}\b", lowered):
            packages.add(mod)
    for ident in raw_idents:
        packages.add(ident.replace("-", "_"))
    for path, imps in data.imports.items():
        lines = [imp.line for imp in imps if imp.level == 0 and imp.module.split(".")[0] in packages]
        if lines:
            usage = [r.line for r in data.references.get(path, []) if (r.qualifier or "").split(".")[0] in packages]
            results.extend(
                _ref_for_lines(
                    data,
                    path,
                    sorted(set(lines + usage)),
                    "import_graph",
                    30.0,
                    f"imports {sorted(packages & {i.module.split('.')[0] for i in imps})}",
                )
            )

    # 5. configuration / dependency manifests
    for path, rec in data.files.items():
        if not rec.is_config:
            continue
        text = data.contents.get(path, "").lower()
        mentioned = [p for p in packages | {d for d in DIST_TO_IMPORT if d in lowered} if p.lower() in text]
        if is_dependency_manifest(path) and (category == "dependency_upgrade" or mentioned):
            lines = [
                i
                for i, line in enumerate(data.lines(path), start=1)
                if any(m.lower() in line.lower() for m in mentioned)
            ] or [1]
            results.append(
                CodeReference(
                    data.repository,
                    data.commit_sha,
                    path,
                    max(1, min(lines) - 2),
                    max(lines) + 2,
                    "config",
                    35.0 if mentioned else 10.0,
                    reason=f"dependency manifest{' mentioning ' + str(mentioned) if mentioned else ''}",
                    is_config=True,
                )
            )
        elif mentioned or path in {"pyproject.toml", "setup.cfg"}:
            results.append(_whole_file(data, path, "config", 8.0 if mentioned else 4.0, "project configuration"))

    merged = _merge(results)

    # 6. tests linked to the top implementation files
    _, importers_of = import_graph(data)
    impl = [r for r in merged if not r.is_test and not r.is_config][:6]
    impl_paths = list(dict.fromkeys(r.path for r in impl))
    impl_symbols = {r.symbol.split(".")[-1] for r in impl if r.symbol}
    test_refs: list[CodeReference] = []
    for path in impl_paths:
        for importer in importers_of.get(path, set()):
            rec = data.files[importer]
            if not rec.is_test:
                continue
            lines = [r.line for r in data.references.get(importer, []) if r.name in impl_symbols]
            reason = f"test imports {path}"
            if lines:
                test_refs.extend(_ref_for_lines(data, importer, lines, "test_link", 25.0, reason))
            else:
                test_refs.append(_whole_file(data, importer, "test_link", 12.0, reason))
    merged = _merge(merged + test_refs)
    merged.sort(key=lambda r: -r.score)
    # Never surface credential/key files as context: their contents would be sent to the model provider.
    from modernisation.execution.policy import is_sensitive_path

    return [r for r in merged if not is_sensitive_path(r.path)][:limit]


def _merge(refs: list[CodeReference]) -> list[CodeReference]:
    by_key: dict[tuple[str, int, int], CodeReference] = {}
    for ref in refs:
        key = (ref.path, ref.start_line, ref.end_line)
        if key in by_key:
            existing = by_key[key]
            existing.score += ref.score * 0.5
            if ref.retrieval_method not in existing.methods:
                existing.methods.append(ref.retrieval_method)
            if ref.reason and ref.reason not in existing.reason:
                existing.reason = f"{existing.reason}; {ref.reason}"
        else:
            if not ref.methods:
                ref.methods = [ref.retrieval_method]
            by_key[key] = ref
    # collapse ranges fully contained in a stronger range of the same file
    out = sorted(by_key.values(), key=lambda r: -r.score)
    kept: list[CodeReference] = []
    for ref in out:
        container = next(
            (k for k in kept if k.path == ref.path and k.start_line <= ref.start_line and ref.end_line <= k.end_line),
            None,
        )
        if container is not None:
            for m in ref.methods:
                if m not in container.methods:
                    container.methods.append(m)
            continue
        kept.append(ref)
    return kept


def impact_analysis(
    data: SnapshotData, paths: list[str], symbols: list[str] | None = None, depth: int = 2
) -> dict[str, Any]:
    """Files and tests potentially affected by changes to ``paths`` / ``symbols``."""
    _, importers_of = import_graph(data)
    affected: dict[str, int] = {}
    frontier = [p for p in paths if p in data.files]
    for level in range(1, depth + 1):
        nxt = []
        for path in frontier:
            for importer in importers_of.get(path, set()):
                if importer not in affected and importer not in paths:
                    affected[importer] = level
                    nxt.append(importer)
        frontier = nxt
    referencing: dict[str, list[int]] = defaultdict(list)
    for name in symbols or []:
        short = name.split(".")[-1]
        for path, refs in data.references.items():
            for ref in refs:
                if ref.name == short:
                    referencing[path].append(ref.line)
    tests = sorted({p for p in list(affected) + list(referencing) if data.files[p].is_test})
    return {
        "repository": data.repository,
        "commit_sha": data.commit_sha,
        "changed": paths,
        "dependents": [
            {"path": p, "distance": d, "is_test": data.files[p].is_test}
            for p, d in sorted(affected.items(), key=lambda kv: (kv[1], kv[0]))
        ],
        "symbol_references": [{"path": p, "lines": sorted(set(ls))} for p, ls in sorted(referencing.items())],
        "tests": tests,
    }
