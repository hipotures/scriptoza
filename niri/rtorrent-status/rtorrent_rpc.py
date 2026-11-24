#!/usr/bin/env python3
"""Query rTorrent over SCGI and print torrent rows as one JSON object."""

import argparse
import json
import socket
import sys
import xmlrpc.client

MODERN_FIELDS = [
    "d.hash=",
    "d.name=",
    "d.state=",
    "d.is_active=",
    "d.complete=",
    "d.hashing=",
    "d.size_bytes=",
    "d.completed_bytes=",
    "d.down.rate=",
    "d.up.rate=",
    "d.message=",
    "d.peers_connected=",
    "d.peers_complete=",
    "d.peers_accounted=",
    "d.up.total=",
    "d.ratio=",
]

LEGACY_FIELDS = [
    "d.get_hash=",
    "d.get_name=",
    "d.get_state=",
    "d.is_active=",
    "d.get_complete=",
    "d.get_hashing=",
    "d.get_size_bytes=",
    "d.get_completed_bytes=",
    "d.get_down_rate=",
    "d.get_up_rate=",
    "d.get_message=",
    "d.get_peers_connected=",
    "d.get_peers_complete=",
    "d.get_peers_accounted=",
    "d.get_up_total=",
    "d.get_ratio=",
]

MODES = ["jsonrpc", "xmlrpc-v2", "xmlrpc-v1"]


class RpcProtocolError(Exception):
    pass


def send_scgi(host: str, port: int, body: bytes, timeout: float) -> bytes:
    headers = b"CONTENT_LENGTH\x00" + str(len(body)).encode() + b"\x00SCGI\x001\x00"
    request = str(len(headers)).encode() + b":" + headers + b"," + body
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(request)
        chunks = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    return b"".join(chunks)


def split_body(raw: bytes) -> bytes:
    for separator in (b"\r\n\r\n", b"\n\n"):
        index = raw.find(separator)
        if index != -1:
            return raw[index + len(separator):]
    return raw


def query_jsonrpc(host: str, port: int, timeout: float) -> list:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "d.multicall2",
        "params": ["", "main", *MODERN_FIELDS],
    }
    raw = send_scgi(host, port, json.dumps(payload).encode(), timeout)
    try:
        parsed = json.loads(split_body(raw))
    except ValueError as error:
        raise RpcProtocolError(f"Invalid JSON-RPC response: {error}") from error
    if not isinstance(parsed, dict):
        raise RpcProtocolError("Unexpected rTorrent JSON-RPC response")
    if parsed.get("error"):
        error = parsed["error"]
        message = error.get("message") if isinstance(error, dict) else None
        raise RpcProtocolError(message or json.dumps(error))
    if not isinstance(parsed.get("result"), list):
        raise RpcProtocolError("Unexpected rTorrent JSON-RPC response")
    return parsed["result"]


def query_xmlrpc(host: str, port: int, timeout: float, method: str, params: list) -> list:
    body = xmlrpc.client.dumps(tuple(params), method).encode()
    raw = send_scgi(host, port, body, timeout)
    try:
        (result,), _ = xmlrpc.client.loads(split_body(raw).decode("utf-8", "replace"))
    except xmlrpc.client.Fault as fault:
        raise RpcProtocolError(fault.faultString or f"XML-RPC fault {fault.faultCode}") from fault
    except Exception as error:
        raise RpcProtocolError(f"Invalid XML-RPC response: {error}") from error
    if not isinstance(result, list):
        raise RpcProtocolError("Unexpected XML-RPC multicall result")
    return result


def query(host: str, port: int, mode: str, timeout: float) -> list:
    if mode == "jsonrpc":
        return query_jsonrpc(host, port, timeout)
    if mode == "xmlrpc-v2":
        return query_xmlrpc(host, port, timeout, "d.multicall2", ["", "main", *MODERN_FIELDS])
    return query_xmlrpc(host, port, timeout, "d.multicall", ["main", *LEGACY_FIELDS])


def fetch(host: str, port: int, preferred: str | None, timeout: float) -> dict:
    candidates = [preferred, *[mode for mode in MODES if mode != preferred]] if preferred in MODES else MODES
    last_error: Exception | None = None
    for mode in candidates:
        try:
            return {"mode": mode, "rows": query(host, port, mode, timeout)}
        except RpcProtocolError as error:
            last_error = error
    raise last_error or RpcProtocolError(f"Unsupported rTorrent RPC on {host}:{port}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--mode", choices=MODES, help="RPC mode to try first")
    parser.add_argument("--timeout", type=float, default=3.0)
    args = parser.parse_args()
    try:
        result = fetch(args.host, args.port, args.mode, args.timeout)
    except socket.timeout:
        result = {"error": f"Timed out connecting to {args.host}:{args.port}"}
    except (OSError, RpcProtocolError) as error:
        result = {"error": str(error) or type(error).__name__}
    json.dump(result, sys.stdout, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
