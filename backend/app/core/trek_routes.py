"""Native TREK OAuth and Streamable HTTP MCP for the configured Endurain owner."""

import json
import os
from contextlib import suppress
from pathlib import Path

import requests

import core.exceptions as errors


def call_trek(owner: int, tool: str, arguments: dict) -> dict:
    """Run one TREK tool. Keep OAuth credentials and upstream error bodies on the server."""
    try:
        config = json.loads(Path(os.environ["WORKBENCH_TREK_CONFIG"]).read_text())
    except (KeyError, OSError, ValueError):
        raise errors.ServiceUnavailableError("TREK connection is not configured.") from None
    if config.get("owner_id") != owner:
        raise errors.AccessConcealedError()
    try:
        return _exchange(config, tool, arguments)
    except (requests.RequestException, ValueError, IndexError, KeyError, TypeError, StopIteration):
        raise errors.UpstreamError("TREK did not confirm the request. Try again.") from None


def _exchange(config: dict, tool: str, arguments: dict) -> dict:
    base = config["url"].rstrip("/")
    with requests.Session() as session:
        token = session.post(
            base + "/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
            },
            timeout=12,
        )
        token.raise_for_status()
        session.headers.update(
            {"Authorization": "Bearer " + token.json()["access_token"], "Accept": "application/json, text/event-stream"}
        )

        def rpc(method: str, params: dict, message_id: int | None) -> dict:
            payload = {"jsonrpc": "2.0", "method": method, "params": params}
            if message_id is not None:
                payload["id"] = message_id
            response = session.post(base + "/mcp", json=payload, timeout=(8, 75))
            response.raise_for_status()
            if sid := response.headers.get("mcp-session-id"):
                session.headers["mcp-session-id"] = sid
            if message_id is None:
                return {}
            if "text/event-stream" in response.headers.get("Content-Type", ""):
                messages = (
                    json.loads(line[5:]) for line in response.content.decode().splitlines() if line.startswith("data:")
                )
                reply = next(value for value in messages if value.get("id") == message_id)
            else:
                reply = response.json()
            return reply["result"]

        try:
            protocol = rpc(
                "initialize",
                {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "Endurain saved routes", "version": "1"},
                },
                1,
            )
            session.headers["mcp-protocol-version"] = protocol["protocolVersion"]
            rpc("notifications/initialized", {}, None)
            result = rpc("tools/call", {"name": tool, "arguments": arguments}, 2)
            if result.get("isError"):
                raise errors.UpstreamError(
                    "TREK declined this operation. Check trip editing access and Tours settings."
                )
            return json.loads(result["content"][0]["text"])
        finally:
            if "mcp-session-id" in session.headers:
                with suppress(requests.RequestException):
                    session.delete(base + "/mcp", timeout=5)
