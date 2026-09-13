"""Conservative syntax-only reference extraction. Never import upstream code."""
from __future__ import annotations

import ast
import re

from evaluation.modular.canonical_lineage import KINDS, empty_references, normalize_reference
from evaluation.modular.fresh_airs_custodian import _check
from research_loop.ontology import digest

SLOTS = ("prepare.py", "evaluate_prepare.py")
APIS = ("datasets.load_dataset", "sklearn.datasets.fetch_openml", "kagglehub.dataset_download")
BUILDERS = {"json", "csv", "parquet", "arrow", "text", "xml", "webdataset", "imagefolder", "audiofolder", "videofolder"}
PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
COUNTERS = ("slot_present_count", "slot_missing_count", "slot_invalid_type_count", "syntax_error_count",
            "blocked_dynamic_namespace_count", "recognized_call_count", "resolved_call_count",
            "unresolved_call_count", "literal_revision_count", "missing_revision_count",
            "literal_data_url_count", "unresolved_data_file_count")


def _chain(node):
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        root = _chain(node.value)
        return [*root, node.attr] if root else []
    return []


def _literal(node):
    # No eval, constant propagation, f-string expansion, or local-name lookup.
    if isinstance(node, ast.Constant) and type(node.value) in (str, int, type(None)):
        return node.value
    raise ValueError()


def _files(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.List, ast.Tuple)):
        return [value for item in node.elts for value in _files(item)]
    if isinstance(node, ast.Dict) and all(isinstance(k, ast.Constant) and isinstance(k.value, str) for k in node.keys):
        return [value for item in node.values for value in _files(item)]
    raise ValueError()


def _imports(tree):
    bindings, counts, blocked = {}, {}, set()
    def bind(name):
        counts[name] = counts.get(name, 0) + 1
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                bind(name)
                if node in tree.body:
                    bindings[name] = alias.name if alias.asname else alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bind(alias.asname or alias.name)
                if node in tree.body and node.level == 0 and alias.name != "*":
                    bindings[alias.asname or alias.name] = (node.module or "") + "." + alias.name
                if alias.name == "*":
                    blocked.add("*")
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bind(node.id)
        elif isinstance(node, ast.arg):
            bind(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bind(node.name)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bind(node.name)
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            bind(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            bind(node.rest)
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del)):
            chain = _chain(node)
            if chain:
                blocked.add(chain[0])
    # If an import alias escapes the receiver/callee chain, arbitrary helpers
    # could mutate it. Reject it globally, including shadowing in child scopes.
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in bindings and isinstance(node.ctx, ast.Load):
            top = node
            while isinstance(parents.get(top), ast.Attribute) and parents[top].value is top:
                top = parents[top]
            parent = parents.get(top)
            if not isinstance(parent, ast.Call) or parent.func is not top:
                blocked.add(node.id)
    return {key: value for key, value in bindings.items() if counts[key] == 1 and key not in blocked}, bindings, bool("*" in blocked)


def _extract_script(code, refs, revisions, counts):
    try:
        if len(code.encode("utf-8")) > 2 * 1024 * 1024:
            raise ValueError()
        tree = ast.parse(code, filename="<private-fixed-slot>")
    except (SyntaxError, ValueError, RecursionError, UnicodeError):
        counts["syntax_error_count"] += 1
        return
    safe, all_bindings, dynamic = _imports(tree)
    # Dynamic namespace mutation makes even otherwise simple imports uncertain.
    dynamic = dynamic or any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                            and n.func.id in {"exec", "eval", "globals", "locals", "vars", "__import__", "setattr", "delattr"}
                            for n in ast.walk(tree))
    if dynamic:
        counts["blocked_dynamic_namespace_count"] += 1
        safe = {}
    for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
        chain = _chain(call.func)
        if not chain:
            continue
        declared = ".".join([all_bindings.get(chain[0], chain[0]), *chain[1:]])
        if declared not in APIS:
            continue
        counts["recognized_call_count"] += 1
        if chain[0] not in safe:
            counts["unresolved_call_count"] += 1
            continue
        try:
            if any(kw.arg is None for kw in call.keywords) or any(isinstance(x, ast.Starred) for x in call.args):
                raise ValueError()
            kws = {kw.arg: kw.value for kw in call.keywords}
            if len(kws) != len(call.keywords):
                raise ValueError()
            def arg(name, pos=None):
                if pos is not None and len(call.args) > pos:
                    if name in kws:
                        raise ValueError()
                    return _literal(call.args[pos])
                return _literal(kws[name]) if name in kws else None
            identity, revision = None, None
            urls = []
            if declared == "datasets.load_dataset":
                if len(call.args) > 2:
                    raise ValueError()
                path, revision = arg("path", 0), arg("revision")
                if type(path) is not str or not path.isascii():
                    raise ValueError()
                if path.startswith("hf://datasets/"):
                    path = path[len("hf://datasets/"):]
                parts = path.split("/")
                # A bare builder/local/legacy name does not establish a Hub ID.
                if len(parts) == 2 and all(PART.fullmatch(p) for p in parts):
                    identity = normalize_reference(path, "hf_dataset")
                elif path not in BUILDERS:
                    raise ValueError()
                if "data_files" in kws:
                    urls = _files(kws["data_files"])
            elif declared == "sklearn.datasets.fetch_openml":
                if len(call.args) > 1:
                    raise ValueError()
                data_id, name = arg("data_id"), arg("name", 0)
                if type(data_id) is not int or data_id <= 0 or name is not None:
                    raise ValueError()
                identity = normalize_reference(f"https://www.openml.org/d/{data_id}")
                revision = str(data_id)
            elif declared == "kagglehub.dataset_download":
                if len(call.args) > 1:
                    raise ValueError()
                handle = arg("handle", 0)
                if not isinstance(handle, str):
                    raise ValueError()
                parts = handle.split("/")
                if len(parts) not in (2, 4) or not all(PART.fullmatch(p) for p in parts[:2]):
                    raise ValueError()
                if len(parts) == 4:
                    if parts[2] != "versions" or not parts[3].isascii() or not parts[3].isdigit() or int(parts[3]) < 1:
                        raise ValueError()
                    revision = parts[3]
                identity = normalize_reference("https://www.kaggle.com/datasets/" + "/".join(parts[:2]))
            if revision is not None and (not isinstance(revision, str) or not revision or not revision.isascii()):
                raise ValueError()
            parsed_urls = [normalize_reference(url) for url in urls]
            if identity is None and not any(parsed_urls):
                raise ValueError()
        except (TypeError, ValueError, RecursionError):
            counts["unresolved_call_count"] += 1
            continue
        counts["resolved_call_count"] += 1
        if identity is not None:
            refs[identity[0]].add(identity[1])
        for parsed in parsed_urls:
            if parsed is None:
                counts["unresolved_data_file_count"] += 1
            else:
                refs[parsed[0]].add(parsed[1])
                counts["literal_data_url_count"] += 1
        if revision is not None and identity is not None:
            revisions.add(digest({"schema": "static-loader-reference-revision-v1", "identity": identity, "revision": revision}))
            counts["literal_revision_count"] += 1
        else:
            counts["missing_revision_count"] += 1


def extract_fixed_slots(row):
    refs, revisions = empty_references(), set()
    counts = {name: 0 for name in COUNTERS}
    for slot in SLOTS:
        # Exactly the top-level CSV columns authorized for this audit. Do not
        # search dynamic filenames, paths, serialized bundles, or evaluate.py.
        if slot not in row:
            counts["slot_missing_count"] += 1
        elif not isinstance(row[slot], str):
            counts["slot_invalid_type_count"] += 1
        elif not row[slot].strip():
            counts["slot_missing_count"] += 1
        else:
            counts["slot_present_count"] += 1
            _extract_script(row[slot], refs, revisions, counts)
    result = {"schema": "static-loader-factors-v1", "counts": counts,
              "canonical_fingerprints": {kind: sorted(refs[kind]) for kind in KINDS},
              "revision_fingerprints": sorted(revisions), "upstream_code_executed": False,
              "runtime_import_resolution_verified": False, "raw_code_exported": False}
    validate_factors(result)
    return result


def validate_factors(value):
    _check(value, {"schema": "static-loader-factors-v1", "counts": {name: "count" for name in COUNTERS},
                   "canonical_fingerprints": {kind: ["sha"] for kind in KINDS},
                   "revision_fingerprints": ["sha"], "upstream_code_executed": False,
                   "runtime_import_resolution_verified": False, "raw_code_exported": False})
    return value
