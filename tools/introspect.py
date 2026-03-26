"""
introspect.py
-------------
Inspect any type or query field on the PGA Tour GraphQL API.

SINGLE TYPE:
    python tools/introspect.py Tournament
    python tools/introspect.py ScheduleTournament
    python tools/introspect.py Query

BATCH MODE — pass multiple type names:
    python tools/introspect.py Tournament Course Player Round

BATCH FROM FILE — one type name per line in a .txt file:
    python tools/introspect.py --file tools/types.txt

    Example types.txt:
        Query
        Tournament
        ScheduleTournament
        StatDetailsPlayer
        PlayerProfileCourseResults
        ScorecardCompressedV3

Output is saved to tools/introspect_output/{TypeName}.txt
Batch mode saves one file per type.
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
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/146.0.0.0 Safari/537.36"
    ),
}

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "introspect_output")


def post(query, variables={}):
    body = {"variables": variables, "query": query}
    resp = requests.post(ENDPOINT, json=body, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    parsed = resp.json()
    errors = parsed.get("errors")
    if errors:
        raise ValueError([e["message"] for e in errors])
    return parsed["data"]


def resolve_type(typ):
    wrappers = []
    while typ:
        if typ.get("kind") in ("NON_NULL", "LIST"):
            wrappers.append(typ["kind"])
        if typ.get("name"):
            return typ["name"], typ["kind"], wrappers
        typ = typ.get("ofType")
    return "?", "?", wrappers


def format_type(typ):
    name, kind, wrappers = resolve_type(typ)
    result = name
    for w in reversed(wrappers):
        if w == "NON_NULL":
            result = result + "!"
        elif w == "LIST":
            result = f"[{result}]"
    return result


def introspect_type(type_name):
    data = post("""
    query IntrospectType($name: String!) {
      __type(name: $name) {
        name
        kind
        description
        fields {
          name
          type { name kind ofType { name kind ofType { name kind ofType { name kind } } } }
          args {
            name
            type { name kind ofType { name kind } }
          }
        }
        inputFields {
          name
          type { name kind ofType { name kind } }
        }
        enumValues {
          name
        }
      }
    }
    """, {"name": type_name})

    t = data.get("__type")
    if not t:
        print(f"Type '{type_name}' not found.")
        return

    kind = t.get("kind")
    print(f"\n{'=' * 60}")
    print(f"Type: {t['name']}  ({kind})")
    if t.get("description"):
        print(f"Description: {t['description']}")
    print(f"{'=' * 60}")

    if kind in ("OBJECT", "INTERFACE"):
        fields = t.get("fields") or []
        if not fields:
            print("  No fields found.")
            return
        print(f"  {'FIELD':<45} {'TYPE':<35} {'ARGS'}")
        print(f"  {'-'*44} {'-'*34} {'-'*20}")
        for f in fields:
            type_str = format_type(f["type"])
            args = f.get("args") or []
            arg_str = ", ".join(
                f"{a['name']}: {format_type(a['type'])}" for a in args
            ) if args else ""
            print(f"  {f['name']:<45} {type_str:<35} {arg_str}")

    elif kind == "INPUT_OBJECT":
        fields = t.get("inputFields") or []
        print(f"  {'FIELD':<45} {'TYPE'}")
        print(f"  {'-'*44} {'-'*34}")
        for f in fields:
            print(f"  {f['name']:<45} {format_type(f['type'])}")

    elif kind == "ENUM":
        values = t.get("enumValues") or []
        print(f"  Enum values ({len(values)}):")
        for v in values:
            print(f"    {v['name']}")

    else:
        print(f"  Kind '{kind}' — no display implemented for this kind.")


def introspect_query():
    data = post("""
    query {
      __type(name: "Query") {
        fields {
          name
          type { name kind ofType { name kind } }
          args {
            name
            type { name kind ofType { name kind } }
          }
        }
      }
    }
    """)

    fields = data["__type"]["fields"]
    print(f"\n{'=' * 60}")
    print(f"Root Query fields ({len(fields)} total)")
    print(f"{'=' * 60}")
    print(f"  {'FIELD':<45} {'RETURN TYPE':<30} ARGS")
    print(f"  {'-'*44} {'-'*29} {'-'*30}")

    for f in sorted(fields, key=lambda x: x["name"]):
        type_str = format_type(f["type"])
        args = f.get("args") or []
        arg_str = ", ".join(
            f"{a['name']}: {format_type(a['type'])}" for a in args
        ) if args else ""
        print(f"  {f['name']:<45} {type_str:<30} {arg_str}")


def run_one(type_name):
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f"{type_name}.txt")

    buffer = io.StringIO()
    original_stdout = sys.stdout
    sys.stdout = buffer

    try:
        if type_name == "Query":
            introspect_query()
        else:
            introspect_type(type_name)
    except Exception as e:
        print(f"ERROR: {e}")
    finally:
        sys.stdout = original_stdout

    output = buffer.getvalue()
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(output)

    print(f"  [{type_name}] -> {out_path}")
    return out_path


def load_types_from_file(file_path):
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        sys.exit(1)
    with open(file_path, encoding="utf-8") as f:
        lines = f.readlines()
    return [
        line.strip()
        for line in lines
        if line.strip() and not line.strip().startswith("#")
    ]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    if sys.argv[1] == "--file":
        if len(sys.argv) < 3:
            print("Usage: python introspect.py --file types.txt")
            sys.exit(1)
        type_names = load_types_from_file(sys.argv[2])
    else:
        type_names = sys.argv[1:]

    print(f"Running introspection for {len(type_names)} type(s)...")
    for name in type_names:
        run_one(name)

    print(f"\nAll output saved to: {OUT_DIR}")