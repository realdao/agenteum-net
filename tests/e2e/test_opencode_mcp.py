"""E2E test: verify opencode can connect to agenteum-net MCP and execute tools."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

SERVER_START_TIMEOUT = 10.0
OPENCODE_TIMEOUT = 120.0
PROJECT_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.e2e


@dataclass(frozen=True)
class ServerHandle:
    proc: subprocess.Popen
    port: int
    opencode_env: dict[str, str]


def _free_port() -> int:
    """Return an ephemeral TCP port that is currently free."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _find_uv() -> str:
    """Return the uv executable path."""
    import shutil

    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv not found in PATH")
    return uv


def _find_opencode() -> str:
    """Return the opencode executable path."""
    import shutil

    opencode = shutil.which("opencode")
    if opencode is None:
        pytest.skip("opencode not found in PATH")
    return opencode


def _opencode_config_content(port: int) -> str:
    """Return an inline OpenCode config for the test server."""
    return json.dumps(
        {
            "mcp": {
                "agenteum-net": {
                    "type": "remote",
                    "url": f"http://127.0.0.1:{port}/mcp/full",
                    "enabled": True,
                    "oauth": False,
                }
            }
        }
    )


def _wait_for_server(
    proc: subprocess.Popen,
    port: int,
    timeout: float = SERVER_START_TIMEOUT,
) -> None:
    """Wait until the server accepts TCP connections."""
    end_time = time.monotonic() + timeout
    while time.monotonic() < end_time:
        if proc.poll() is not None:
            raise RuntimeError(f"Server exited early (code={proc.returncode}).")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError(f"Server did not accept connections on port {port} within {timeout}s.")


def _run_opencode(
    cmd_args: list[str],
    *,
    env: dict[str, str] | None = None,
    timeout: float = OPENCODE_TIMEOUT,
) -> tuple[str, str, int]:
    """Run an opencode sub-command and return (stdout, stderr, returncode)."""
    full_cmd = [_find_opencode(), "--pure"] + cmd_args
    result = subprocess.run(
        full_cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(PROJECT_ROOT),
        env={**dict(os.environ), **(env or {})},
    )
    return result.stdout, result.stderr, result.returncode


def _parse_opencode_json_events(raw: str) -> list[dict[str, Any]]:
    """Parse newline-delimited JSON events from opencode --format json output."""
    events: list[dict[str, Any]] = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _find_tool_use_event(
    events: list[dict[str, Any]],
    tool_name_substring: str,
) -> dict[str, Any] | None:
    """Find the first tool_use event whose tool name contains *tool_name_substring*."""
    for ev in events:
        if ev.get("type") == "tool_use":
            part = ev.get("part", {})
            tool = part.get("tool", "")
            if tool_name_substring in tool:
                return ev
    return None


def _server_logs(log_paths: tuple[Path, Path]) -> str:
    """Return server logs for failure diagnostics."""
    stdout_path, stderr_path = log_paths
    stdout = stdout_path.read_text(encoding="utf-8", errors="replace")
    stderr = stderr_path.read_text(encoding="utf-8", errors="replace")
    return f"stdout:\n{stdout}\nstderr:\n{stderr}"


def _terminate_server(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> ServerHandle:
    """Start agenteum-net server, yield the process handle, then terminate it."""
    uv = _find_uv()
    port = _free_port()
    log_dir = tmp_path_factory.mktemp("agenteum-net-e2e")
    stdout_path = log_dir / "server.stdout.log"
    stderr_path = log_dir / "server.stderr.log"
    stdout_file = stdout_path.open("w", encoding="utf-8")
    stderr_file = stderr_path.open("w", encoding="utf-8")
    env = {
        **dict(os.environ),
        "AGENTEUM_HOST": "127.0.0.1",
        "AGENTEUM_PORT": str(port),
        "AGENTEUM_ALLOW_REMOTE": "false",
    }
    proc = subprocess.Popen(
        [uv, "run", "agenteum-net"],
        stdout=stdout_file,
        stderr=stderr_file,
        text=True,
        cwd=str(PROJECT_ROOT),
        env=env,
    )
    try:
        _wait_for_server(proc, port, timeout=SERVER_START_TIMEOUT)
        yield ServerHandle(
            proc=proc,
            port=port,
            opencode_env={"OPENCODE_CONFIG_CONTENT": _opencode_config_content(port)},
        )
    except Exception as exc:
        stdout_file.flush()
        stderr_file.flush()
        raise RuntimeError(f"{exc}\n{_server_logs((stdout_path, stderr_path))}") from exc
    finally:
        _terminate_server(proc)
        stdout_file.close()
        stderr_file.close()


@pytest.fixture(scope="module", autouse=True)
def wait_after_server_start(server: ServerHandle) -> None:
    """Ensure the fixture starts before tests run."""
    assert server.proc.poll() is None


class TestOpencodeMcpConnection:
    """Verify opencode can discover and connect to agenteum-net MCP server."""

    def test_mcp_list_shows_agenteum_net_connected(self, server: ServerHandle) -> None:
        """opencode mcp list should report agenteum-net as connected."""
        stdout, stderr, rc = _run_opencode(["mcp", "list"], env=server.opencode_env)
        combined = stdout + stderr

        assert rc == 0, f"opencode mcp list exited with {rc}. Output:\n{combined}"
        assert "agenteum-net" in combined, (
            f"agenteum-net not found in MCP list. Output:\n{combined}"
        )
        assert "connected" in combined.lower(), (
            f"agenteum-net not marked connected. Output:\n{combined}"
        )


class TestOpencodeMcpTools:
    """Verify opencode non-interactive run can invoke agenteum-net tools."""

    def test_search_tool_is_called_via_agenteum_net(self, server: ServerHandle) -> None:
        """A prompt asking agenteum-net to search should trigger the search tool."""
        prompt = (
            "请通过 agenteum-net 搜索 'Python MCP server tutorial'，只返回工具调用结果"
        )
        stdout, stderr, rc = _run_opencode(
            ["run", "--format", "json", "--dangerously-skip-permissions", prompt],
            env=server.opencode_env,
        )

        # opencode may print ANSI codes to stderr; stdout should be pure JSON.
        events = _parse_opencode_json_events(stdout)

        assert events, f"No JSON events parsed from stdout. stdout:\n{stdout}\nstderr:\n{stderr}"

        tool_event = _find_tool_use_event(events, "search")
        assert tool_event is not None, (
            "No search tool_use event found. Events:\n"
            + json.dumps(events, indent=2, ensure_ascii=False)
        )

        part = tool_event.get("part", {})
        state = part.get("state", {})
        tool_input = state.get("input", {})

        # Verify the search query was passed through.
        assert tool_input.get("query") == "Python MCP server tutorial", (
            f"Unexpected search input: {tool_input}"
        )

    def test_fetch_tool_returns_content(self, server: ServerHandle) -> None:
        """A prompt asking agenteum-net to fetch a URL should return page content."""
        prompt = (
            "请通过 agenteum-net 抓取 https://example.com 的内容，并总结返回了什么"
        )
        stdout, stderr, rc = _run_opencode(
            ["run", "--format", "json", "--dangerously-skip-permissions", prompt],
            env=server.opencode_env,
        )

        events = _parse_opencode_json_events(stdout)
        assert events, f"No JSON events parsed from stdout. stdout:\n{stdout}\nstderr:\n{stderr}"

        tool_event = _find_tool_use_event(events, "fetch")
        assert tool_event is not None, (
            "No fetch tool_use event found. Events:\n"
            + json.dumps(events, indent=2, ensure_ascii=False)
        )

        part = tool_event.get("part", {})
        state = part.get("state", {})
        assert state.get("status") == "completed", (
            f"Fetch tool did not complete. State: {state}"
        )

        output = state.get("output", "")
        assert "Example Domain" in output or "example.com" in output.lower(), (
            f"Fetch output does not contain expected content. Output: {output[:500]}"
        )
