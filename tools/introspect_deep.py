"""
introspect_deep.py
------------------
Recursively expands all nested types from a starting type.
Stops at scalars, enums, and already-visited types.

Usage:
    python tools/introspect_deep.py StatDetails
    python tools/introspect_deep.py PlayerProfileCourseResults
    python tools/introspect_deep.py Tournament

Output saved to tools/introspect_output/{TypeName}_deep.txt
"""

import io
import os
import sys
import requests

ENDPOINT = "https://orchestrator.pgatour.com/graphql"
HEADERS = {
    "Content-Type": "application/json",
    "x-api-key": "da2-gsrx5bibzbb4njvhl7t37wqyl4",
    "origin": "https://www.pgatour.com",
    "referer": "https://www.pgatour.com/",
    "x-pgat-platform": "web",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "introspect_output")

# Never expand these — they're either primitives or noisy UI types
SKIP_TYPES = {
    "String", "Int", "Float", "Boolean", "ID",
    "AWSTimestamp", "AWSDateTime", "AWSDate",
    "ImageAsset", "ImageOrg",  # UI only
}


def post(query, variables={}):
    body = {"variables": variables, "query": query}
    resp = requests.post(ENDPOINT, json=body, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    parsed = resp.json()
    if parsed.get("errors"):
        raise ValueError([e["message"] for e in parsed["errors"]])
    return parsed["data"]


def get_type(type_name):
    data = post("""
    query IntrospectType($name: String!) {
      __type(name: $name) {
        name
        kind
        fields {
          name
          type { name kind ofType { name kind ofType { name kind ofType { name kind } } } }
        }
        inputFields {
          name
          type { name kind ofType { name kind } }
        }
        enumValues { name }
        possibleTypes { name kind }
      }
    }
    """, {"name": type_name})
    return data.get("__type")


def base_type(typ):
    """Unwrap NON_NULL/LIST to get the base type name and kind."""
    while typ:
        if typ.get("name") and typ.get("kind") not in ("NON_NULL", "LIST"):
            return typ["name"], typ["kind"]
        typ = typ.get("ofType")
    return None, None


def format_type(typ):
    name, kind, wrappers = None, None, []
    t = typ
    while t:
        if t.get("kind") in ("NON_NULL", "LIST"):
            wrappers.append(t["kind"])
        if t.get("name"):
            name = t["name"]
            break
        t = t.get("ofType")
    result = name or "?"
    for w in reversed(wrappers):
        result = f"{result}!" if w == "NON_NULL" else f"[{result}]"
    return result


def explore(type_name, visited=None, depth=0, output=None):
    if visited is None:
        visited = set()
    if output is None:
        output = []

    if type_name in visited or type_name in SKIP_TYPES:
        return

    visited.add(type_name)
    indent = "  " * depth

    t = get_type(type_name)
    if not t:
        output.append(f"{indent}[{type_name}] — not found")
        return

    kind = t.get("kind")
    output.append(f"\n{indent}{'=' * (60 - depth*2)}")
    output.append(f"{indent}Type: {type_name}  ({kind})")
    output.append(f"{indent}{'=' * (60 - depth*2)}")

    # UNION — show possible types and recurse into each
    if kind == "UNION":
        possible = t.get("possibleTypes") or []
        output.append(f"{indent}  Union of: {[p['name'] for p in possible]}")
        for p in possible:
            explore(p["name"], visited, depth + 1, output)
        return

    # ENUM
    if kind == "ENUM":
        values = t.get("enumValues") or []
        output.append(f"{indent}  Values: {[v['name'] for v in values]}")
        return

    # OBJECT or INPUT_OBJECT
    fields = t.get("fields") or t.get("inputFields") or []
    if not fields:
        output.append(f"{indent}  (no fields)")
        return

    nested = []
    for f in fields:
        type_str = format_type(f["type"])
        output.append(f"{indent}  {f['name']:<45} {type_str}")
        base_name, base_kind = base_type(f["type"])
        if base_name and base_name not in SKIP_TYPES and base_name not in visited:
            if base_kind in ("OBJECT", "INPUT_OBJECT", "UNION", "INTERFACE", "ENUM"):
                nested.append(base_name)

    # Recurse into nested types
    for name in nested:
        explore(name, visited, depth + 1, output)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    type_name = sys.argv[1]
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f"{type_name}_deep.txt")

    print(f"Exploring {type_name} recursively...")
    lines = []
    explore(type_name, output=lines)

    content = "\n".join(lines)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"Saved to: {out_path}")