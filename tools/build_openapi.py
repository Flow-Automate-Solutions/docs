#!/usr/bin/env python3
import argparse
import copy
import json
from collections import OrderedDict
from pathlib import Path
from typing import Any


HTTP_METHODS = {"get", "put", "post", "delete", "patch", "options", "head", "trace"}
INTERNAL_FILE = "openapi.json"
PUBLIC_FILE = "openapi.json"
SKIP_INPUT_FILENAMES = {"openapi-internal.json", "openapi-public.json"}


class MergeConflictError(RuntimeError):
    pass


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _load_json(path: Path) -> dict[str, Any] | None:
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        print(f"WARN: Skipping empty input file: {path}")
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as err:
        raise RuntimeError(f"Invalid JSON in {path}: {err}") from err
    if not isinstance(data, dict):
        raise RuntimeError(f"Expected top-level object in {path}")
    required = ["openapi", "paths"]
    missing = [k for k in required if k not in data]
    if missing:
        raise RuntimeError(f"Missing required keys in {path}: {', '.join(missing)}")
    return data


def _dedupe_by_json(items: list[Any]) -> list[Any]:
    seen: set[str] = set()
    out: list[Any] = []
    for item in items:
        key = _stable_json(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _merge_tags(merged_tags: list[dict[str, Any]], incoming_tags: list[dict[str, Any]], source: Path) -> None:
    by_name = {str(tag.get("name", "")): tag for tag in merged_tags if isinstance(tag, dict)}
    for tag in incoming_tags:
        if not isinstance(tag, dict):
            continue
        name = str(tag.get("name", ""))
        if not name:
            continue
        if name in by_name:
            if _stable_json(by_name[name]) != _stable_json(tag):
                raise MergeConflictError(
                    f"Tag conflict for '{name}' between merged set and {source}"
                )
            continue
        merged_tags.append(copy.deepcopy(tag))
        by_name[name] = merged_tags[-1]


def _merge_paths(merged_paths: dict[str, Any], incoming_paths: dict[str, Any], source: Path) -> None:
    for path_key, path_item in incoming_paths.items():
        if not isinstance(path_item, dict):
            raise RuntimeError(f"Invalid path item for '{path_key}' in {source}")
        current_path_item = merged_paths.setdefault(path_key, {})
        if not isinstance(current_path_item, dict):
            raise MergeConflictError(f"Path type conflict for '{path_key}' from {source}")

        for k, v in path_item.items():
            lk = k.lower()
            if lk in HTTP_METHODS:
                if k in current_path_item:
                    if _stable_json(current_path_item[k]) != _stable_json(v):
                        raise MergeConflictError(
                            f"Operation conflict for '{path_key}' method '{k}' from {source}"
                        )
                else:
                    current_path_item[k] = copy.deepcopy(v)
            else:
                if k in current_path_item:
                    if _stable_json(current_path_item[k]) != _stable_json(v):
                        raise MergeConflictError(
                            f"Path-level field conflict for '{path_key}' key '{k}' from {source}"
                        )
                else:
                    current_path_item[k] = copy.deepcopy(v)


def _merge_components(merged_components: dict[str, Any], incoming_components: dict[str, Any], source: Path) -> None:
    for section, section_obj in incoming_components.items():
        if not isinstance(section_obj, dict):
            if section not in merged_components:
                merged_components[section] = copy.deepcopy(section_obj)
                continue
            if _stable_json(merged_components[section]) != _stable_json(section_obj):
                raise MergeConflictError(
                    f"Component section conflict for '{section}' from {source}"
                )
            continue
        merged_section = merged_components.setdefault(section, {})
        if not isinstance(merged_section, dict):
            raise MergeConflictError(
                f"Component section type conflict for '{section}' from {source}"
            )
        for key, value in section_obj.items():
            if key in merged_section:
                if _stable_json(merged_section[key]) != _stable_json(value):
                    raise MergeConflictError(
                        f"Component conflict for '{section}.{key}' from {source}"
                    )
            else:
                merged_section[key] = copy.deepcopy(value)


def _sort_openapi(doc: dict[str, Any]) -> dict[str, Any]:
    sorted_doc = copy.deepcopy(doc)

    if isinstance(sorted_doc.get("tags"), list):
        sorted_doc["tags"] = sorted(
            sorted_doc["tags"],
            key=lambda t: str(t.get("name", "")) if isinstance(t, dict) else "",
        )

    paths = sorted_doc.get("paths")
    if isinstance(paths, dict):
        new_paths: OrderedDict[str, Any] = OrderedDict()
        for path_key in sorted(paths.keys()):
            item = paths[path_key]
            if isinstance(item, dict):
                methods = OrderedDict()
                method_keys = sorted(item.keys(), key=lambda x: (x.lower() not in HTTP_METHODS, x))
                for mk in method_keys:
                    methods[mk] = item[mk]
                new_paths[path_key] = methods
            else:
                new_paths[path_key] = item
        sorted_doc["paths"] = new_paths

    components = sorted_doc.get("components")
    if isinstance(components, dict):
        new_components: OrderedDict[str, Any] = OrderedDict()
        for section in sorted(components.keys()):
            section_obj = components[section]
            if isinstance(section_obj, dict):
                new_components[section] = OrderedDict(
                    (k, section_obj[k]) for k in sorted(section_obj.keys())
                )
            else:
                new_components[section] = section_obj
        sorted_doc["components"] = new_components

    return sorted_doc


def _build_internal(input_files: list[Path]) -> dict[str, Any]:
    valid_docs: list[tuple[Path, dict[str, Any]]] = []
    for path in input_files:
        doc = _load_json(path)
        if doc is None:
            continue
        valid_docs.append((path, doc))

    if not valid_docs:
        raise RuntimeError("No valid non-empty _shared/openapi-* input files found.")

    # deterministic by file name
    valid_docs.sort(key=lambda x: x[0].name)
    first = valid_docs[0][1]
    openapi_versions = {str(doc.get("openapi", "")) for _, doc in valid_docs}
    if len(openapi_versions) > 1:
        raise MergeConflictError(
            f"OpenAPI version mismatch across inputs: {', '.join(sorted(openapi_versions))}"
        )

    all_servers: list[Any] = []
    for _, doc in valid_docs:
        if isinstance(doc.get("servers"), list):
            all_servers.extend(copy.deepcopy(doc["servers"]))

    merged: dict[str, Any] = {
        "openapi": str(first.get("openapi", "3.1.0")),
        "info": {
            "title": "Magic CMS Internal API",
            "version": "1.0.0",
            "description": "Merged internal API generated from per-service OpenAPI specs.",
        },
        "servers": _dedupe_by_json(all_servers),
        "security": [],
        "tags": [],
        "paths": {},
        "components": {},
    }

    all_security: list[Any] = []
    for _, doc in valid_docs:
        if isinstance(doc.get("security"), list):
            all_security.extend(copy.deepcopy(doc["security"]))
    merged["security"] = _dedupe_by_json(all_security)

    for source, doc in valid_docs:
        _merge_tags(
            merged["tags"],
            doc.get("tags", []) if isinstance(doc.get("tags"), list) else [],
            source,
        )
        _merge_paths(
            merged["paths"],
            doc.get("paths", {}) if isinstance(doc.get("paths"), dict) else {},
            source,
        )
        _merge_components(
            merged["components"],
            doc.get("components", {}) if isinstance(doc.get("components"), dict) else {},
            source,
        )

    return _sort_openapi(merged)


def _is_public_operation(op: Any) -> bool:
    if not isinstance(op, dict):
        return False
    tags = op.get("tags", [])
    if not isinstance(tags, list):
        return False
    return any(isinstance(t, str) and t.strip().lower() == "public" for t in tags)


def _build_public(internal_doc: dict[str, Any]) -> dict[str, Any]:
    public_doc = copy.deepcopy(internal_doc)
    paths = public_doc.get("paths", {})
    next_paths: dict[str, Any] = {}

    if isinstance(paths, dict):
        for path_key, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue
            kept: dict[str, Any] = {}
            for k, v in path_item.items():
                if k.lower() in HTTP_METHODS and _is_public_operation(v):
                    # remove marker tag from rendered output
                    op = copy.deepcopy(v)
                    tags = op.get("tags", [])
                    if isinstance(tags, list):
                        op["tags"] = [
                            t
                            for t in tags
                            if not (isinstance(t, str) and t.strip().lower() == "public")
                        ]
                    kept[k] = op
                elif k.lower() not in HTTP_METHODS:
                    kept[k] = copy.deepcopy(v)
            if kept:
                # keep path item only when at least one public operation exists
                has_operation = any(method in HTTP_METHODS for method in (key.lower() for key in kept.keys()))
                if not has_operation:
                    continue
                next_paths[path_key] = kept
    public_doc["paths"] = next_paths

    used_tags: set[str] = set()
    for path_item in next_paths.values():
        for op in path_item.values():
            if isinstance(op, dict):
                for t in op.get("tags", []):
                    if isinstance(t, str) and t.strip():
                        used_tags.add(t.strip())
    tags = public_doc.get("tags", [])
    if isinstance(tags, list):
        public_doc["tags"] = [
            tag
            for tag in tags
            if isinstance(tag, dict) and str(tag.get("name", "")) in used_tags
        ]

    public_doc["info"] = {
        "title": "Magic CMS Public API",
        "version": str(internal_doc.get("info", {}).get("version", "1.0.0")),
        "description": "Public API generated from internal merged spec using operations tagged 'public'.",
    }
    return _sort_openapi(public_doc)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build merged internal/public OpenAPI docs.")
    parser.add_argument(
        "--shared-dir",
        default="_shared",
        help="Directory containing openapi-*-serverless.json files",
    )
    args = parser.parse_args()

    shared_dir = Path(args.shared_dir).resolve()
    if not shared_dir.exists():
        raise RuntimeError(f"Shared directory does not exist: {shared_dir}")

    input_files = sorted(
        p
        for p in shared_dir.glob("openapi-*")
        if p.is_file() and p.name not in SKIP_INPUT_FILENAMES
    )
    repo_root = shared_dir.parent
    internal_out = repo_root / "internal" / INTERNAL_FILE
    public_out = repo_root / "external" / PUBLIC_FILE

    print(f"Discovered {len(input_files)} input file(s).")
    internal_doc = _build_internal(input_files)
    public_doc = _build_public(internal_doc)

    _write_json(internal_out, internal_doc)
    _write_json(public_out, public_doc)

    print(f"Wrote: {internal_out}")
    print(f"Wrote: {public_out}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except MergeConflictError as err:
        print(f"ERROR: {err}")
        raise SystemExit(2)
    except Exception as err:
        print(f"ERROR: {err}")
        raise SystemExit(1)
