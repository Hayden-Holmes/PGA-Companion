"""
explore.py
----------
Fetch and pretty-print any payload by pasting the query directly.
No need to pre-register queries — just paste from DevTools.

Usage:
    python tools/explore.py <QueryName> [key=value ...]

The script looks for a matching .graphql file in tools/queries/
If not found, opens a prompt to paste the query.

Examples:
    python tools/explore.py CourseStatsDetails tourCode=R year=2026
    python tools/explore.py PlayerProfileCourseResults playerId=59095 tourCode=R
"""

import base64
import gzip
import json
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

QUERIES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "queries")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "payload_output")


def parse_args(raw_args):
    variables = {}
    for arg in raw_args:
        if "=" not in arg:
            continue
        key, value = arg.split("=", 1)
        if value.lstrip("-").isdigit():
            value = int(value)
        elif "," in value:
            value = value.split(",")
        elif value.lower() == "null":
            value = None
        variables[key] = value
    return variables


def try_decode(payload_str):
    try:
        raw = base64.b64decode(payload_str)
        return json.loads(gzip.decompress(raw))
    except Exception:
        return None


def deep_decode(obj):
    if isinstance(obj, dict):
        return {
            k: (try_decode(v) or v)
            if k == "payload" and isinstance(v, str) and len(v) > 100
            else deep_decode(v)
            for k, v in obj.items()
        }
    elif isinstance(obj, list):
        return [deep_decode(i) for i in obj]
    return obj


def print_sample(obj, depth=0, max_depth=4, max_list=2):
    """Print a sample of the data showing real values."""
    indent = "  " * depth
    if depth > max_depth:
        print(f"{indent}...")
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, dict):
                print(f"{indent}{k}:")
                print_sample(v, depth + 1, max_depth, max_list)
            elif isinstance(v, list):
                print(f"{indent}{k}: [{len(v)} items]")
                for item in v[:max_list]:
                    print_sample(item, depth + 1, max_depth, max_list)
                if len(v) > max_list:
                    print(f"{indent}  ... and {len(v) - max_list} more")
            else:
                print(f"{indent}{k}: {repr(v)[:80]}")
    elif isinstance(obj, list):
        for item in obj[:max_list]:
            print_sample(item, depth, max_depth, max_list)
    else:
        print(f"{indent}{repr(obj)[:80]}")


def get_query(query_name):
    """
    Look for query in tools/queries/{QueryName}.graphql
    If not found, prompt user to paste it.
    """
    os.makedirs(QUERIES_DIR, exist_ok=True)
    query_file = os.path.join(QUERIES_DIR, f"{query_name}.graphql")

    if os.path.exists(query_file):
        with open(query_file, encoding="utf-8") as f:
            return f.read()

    print(f"No saved query found for '{query_name}'.")
    print(f"Paste your query below (from DevTools), then press Enter twice:\n")
    lines = []
    while True:
        line = input()
        if line == "" and lines and lines[-1] == "":
            break
        lines.append(line)
    query = "\n".join(lines).strip()

    # Save for next time
    with open(query_file, "w", encoding="utf-8") as f:
        f.write(query)
    print(f"Query saved to {query_file} — won't need to paste next time.\n")

    return query


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    query_name = sys.argv[1]
    variables = parse_args(sys.argv[2:])

    query = get_query(query_name)

    print(f"Fetching {query_name} with {variables}...")
    body = {"operationName": query_name, "variables": variables, "query": query}
    resp = requests.post(ENDPOINT, json=body, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    parsed = resp.json()

    errors = parsed.get("errors")
    if errors:
        print(f"GraphQL errors:")
        for e in errors:
            print(f"  {e['message']}")
        sys.exit(1)

    data = deep_decode(parsed.get("data", {}))

    # Save full response
    os.makedirs(OUT_DIR, exist_ok=True)
    arg_str = "_".join(f"{k}{v}" for k, v in variables.items())
    out_path = os.path.join(OUT_DIR, f"{query_name}_{arg_str}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"\nSaved full response to: {out_path}")
    print(f"\n--- Sample of actual data ---\n")
    print_sample(data, max_depth=4, max_list=2)