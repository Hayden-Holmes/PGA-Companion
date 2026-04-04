"""
pga_pipeline/api_client.py

Handles all HTTP communication with the PGA Tour GraphQL endpoint
and compressed payload decoding.

No business logic here — only transport and decode.
"""

import base64
import gzip
import json
import logging

import requests

logger = logging.getLogger(__name__)

ENDPOINT = "https://orchestrator.pgatour.com/graphql"

# Headers
# x-api-key: public key observed in browser traffic.
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


def gql_post(operation_name: str, variables: dict, query: str) -> dict:
    """
    POST a GraphQL operation. Raises on HTTP error or GraphQL errors.
    Returns the full parsed response dict (includes 'data' key).

    Note: GraphQL always uses POST for read operations — the query
    and variables must be sent in the request body.
    """
    body = {
        "operationName": operation_name,
        "variables": variables,
        "query": query,
    }

    logger.debug("POST %s variables=%s", operation_name, variables)

    resp = requests.post(ENDPOINT, json=body, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    parsed = resp.json()

    if parsed is None:
        raise ValueError(f"Response body is None for operation '{operation_name}'")

    errors = parsed.get("errors")
    if errors:
        messages = [e.get("message", "") for e in errors]
        raise ValueError(
            f"GraphQL errors for '{operation_name}': {messages}"
        )

    return parsed


def decode_compressed(payload_str: str) -> dict:
    """
    Decode a leaderboard compressed payload: base64 → gzip → JSON.
    Raises ValueError if any step fails.
    """
    try:
        raw_bytes = base64.b64decode(payload_str)
    except Exception as e:
        raise ValueError(f"base64 decode failed: {e}") from e

    try:
        decompressed = gzip.decompress(raw_bytes)
    except Exception as e:
        raise ValueError(f"gzip decompress failed: {e}") from e

    try:
        return json.loads(decompressed)
    except Exception as e:
        raise ValueError(f"JSON parse of decompressed payload failed: {e}") from e