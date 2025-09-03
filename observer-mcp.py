#!/usr/bin/env python3
"""
Observations MCP server (FastMCP version, no `schema=` arguments)

- Append-only NDJSON log with file locking
- Private, no-arg bootstrap_session that loads {user_id, ourn, ...} from a local file
- start_thread / append_event / list_events tools
- Active-session defaulting so the LLM doesn't need to pass session_id

Env vars:
  OBS_CONTEXT_PATH  -> path to private_context.json (default: ./private_context.json)
  OBS_LOG_PATH      -> path to observations.ndjson (default: ./observations.ndjson)

CLI args:
  --log-dir   directory to place the log file (default: current directory)
  --log-file  log filename (default: observations.ndjson)
"""
import os
import json
import uuid
import secrets
import datetime
import pathlib
import argparse
from typing import Any, Dict, Iterable, List, Optional, Literal

from filelock import FileLock
from mcp.server.fastmcp import FastMCP

# --------------------
# Config
# --------------------
APP_NAME = "observations"
LOG_PATH = pathlib.Path(os.environ.get("OBS_LOG_PATH", "./observations.ndjson"))
LOCK_PATH = pathlib.Path(str(LOG_PATH) + ".lock")
CONTEXT_PATH = pathlib.Path(
    os.environ.get("OBS_CONTEXT_PATH", "./private_context.json")
)

# --------------------
# In-memory state (private; not written to NDJSON)
# --------------------
_PRIVATE_CTX: Dict[str, Dict[str, Any]] = {}  # session_id -> {user_id, ourn, ...}
_ACTIVE_SESSION_ID: Optional[str] = None


# --------------------
# Helpers
# --------------------
def now_iso() -> str:
    return datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _append_line(obj: Dict[str, Any]) -> Dict[str, Any]:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(LOCK_PATH)):
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    return obj


def _iter_events() -> Iterable[Dict[str, Any]]:
    if not LOG_PATH.exists():
        return
    with LOG_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def _load_private_context() -> Dict[str, Any]:
    """Load private fields (e.g., user_id, ourn) from a local file. Replace with your real loader."""
    try:
        if CONTEXT_PATH.exists():
            return json.loads(CONTEXT_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    # Fallback demo values
    return {"user_id": "user_demo", "ourn": "sql_10min_intro", "cohort": "pilot"}


KINDS: set = {
    "submission",
    "verify",
    "feedback",
    "hint",
    "note",
    "reflection",
    "state",
    "metric",
}

# --------------------
# FastMCP app
# --------------------
mcp = FastMCP(APP_NAME)


@mcp.tool(name="bootstrap_session")
def bootstrap_session(expose: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Begin a tutorial session using private system context.

    Loads user_id and ourn from the server's environment/files.
    Returns a new session_id and sets it as active for this process.
    Optionally expose a small allowlist of non-sensitive fields via `expose`.
    """
    global _ACTIVE_SESSION_ID
    private_ctx = _load_private_context()  # {user_id, ourn, ...}
    session_id = f"sess_{secrets.token_hex(4)}"
    _PRIVATE_CTX[session_id] = {**private_ctx, "ts": now_iso()}
    _ACTIVE_SESSION_ID = session_id

    # Log session start WITHOUT leaking private fields
    ev = {
        "id": f"evt_{uuid.uuid4().hex}",
        "ts": now_iso(),
        "actor": "system",
        "session_id": session_id,
        "activity_id": None,
        "thread_id": None,
        "kind": "state",
        "tags": ["session_start"],
        "data": {"meta": "started"},
    }
    _append_line(ev)

    exposed_payload: Dict[str, Any] = {"session_id": session_id}
    for k in expose or []:
        if k in _PRIVATE_CTX[session_id]:
            exposed_payload[k] = _PRIVATE_CTX[session_id][k]
    return exposed_payload


@mcp.tool(name="start_thread")
def start_thread(
    activity_id: str,
    session_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Start a new attempt thread within an activity.
    Uses active session if `session_id` is omitted.
    """
    sid = session_id or _ACTIVE_SESSION_ID
    if not sid:
        return {
            "error": "No active session. Call bootstrap_session first or pass session_id."
        }
    thread_id = f"thr_{uuid.uuid4().hex[:8]}"
    ev = {
        "id": f"evt_{uuid.uuid4().hex}",
        "ts": now_iso(),
        "actor": "system",
        "session_id": sid,
        "activity_id": activity_id,
        "thread_id": thread_id,
        "kind": "state",
        "tags": ["thread_start"],
        "data": {"metadata": metadata or {}},
    }
    _append_line(ev)
    return {"session_id": sid, "thread_id": thread_id, "event": ev}


@mcp.tool(name="append_event")
def append_event(
    activity_id: str,
    thread_id: str,
    kind: Literal[
        "submission",
        "verify",
        "feedback",
        "hint",
        "note",
        "reflection",
        "state",
        "metric",
    ],
    data: Dict[str, Any],
    tags: Optional[List[str]] = None,
    actor: Optional[str] = None,
    confidence: Optional[float] = None,
    supersedes: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Append an observation event to the append-only log.
    Uses active session if `session_id` is omitted.
    """
    sid = session_id or _ACTIVE_SESSION_ID
    if not sid:
        return {
            "error": "No active session. Call bootstrap_session first or pass session_id."
        }
    if kind not in KINDS:
        return {"error": f"Invalid kind '{kind}'. Must be one of {sorted(KINDS)}."}

    ev = {
        "id": f"evt_{uuid.uuid4().hex}",
        "ts": now_iso(),
        "actor": actor or "llm",
        "session_id": sid,
        "activity_id": activity_id,
        "thread_id": thread_id,
        "kind": kind,
        "tags": tags or [],
        "data": data,
        "confidence": confidence,
        "supersedes": supersedes,
    }
    _append_line(ev)
    return ev


@mcp.tool(name="list_events")
def list_events(
    session_id: Optional[str] = None,
    activity_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    kinds: Optional[List[str]] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    """
    List events with optional filters (`session_id`, `activity_id`, `thread_id`, `kinds`)
    and time window (`since`, `until`). Timestamps are ISO8601.
    """

    def parse_ts(s: Optional[str]) -> Optional[datetime.datetime]:
        if not s:
            return None
        return datetime.datetime.fromisoformat(s.replace("Z", ""))

    ts_since = parse_ts(since)
    ts_until = parse_ts(until)
    kinds_set = set(kinds or [])
    out: List[Dict[str, Any]] = []
    count = 0

    for ev in _iter_events() or []:
        if session_id and ev.get("session_id") != session_id:
            continue
        if activity_id and ev.get("activity_id") != activity_id:
            continue
        if thread_id and ev.get("thread_id") != thread_id:
            continue
        if kinds_set and ev.get("kind") not in kinds_set:
            continue
        ts = datetime.datetime.fromisoformat(ev["ts"].replace("Z", ""))
        if ts_since and ts < ts_since:
            continue
        if ts_until and ts > ts_until:
            continue
        out.append(ev)
        count += 1
        if count >= max(1, min(limit, 2000)):
            break
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--log-dir",
        default=".",
        help="directory to place the log file (default: current directory)",
    )
    parser.add_argument(
        "--log-file",
        default="observations.ndjson",
        help="log filename (default: observations.ndjson)",
    )
    args = parser.parse_args()

    LOG_PATH = pathlib.Path(args.log_dir) / args.log_file
    LOCK_PATH = pathlib.Path(str(LOG_PATH) + ".lock")

    mcp.run()
