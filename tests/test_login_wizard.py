"""Tests for the interactive login wizard boundary."""

from __future__ import annotations

import os
import pty
import re
import select
import signal
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

import requests


def test_login_wizard_invokes_real_gum_and_routes_correctly() -> None:
    """Test the login wizard by driving the real gum executable via a PTY."""
    env = os.environ.copy()
    env["BROWSER"] = "true"  # Prevent real browser popups

    pid, fd = pty.fork()
    if pid == 0:
        # Child process: run the real CLI
        os.execvpe(sys.executable, [sys.executable, "-u", "-m", "usage_limits", "login"], env)

    # Parent process: read from the PTY and drive the interaction
    output = b""
    port = None

    # Read output until the process exits or we find the URL
    deadline = time.monotonic() + 20.0
    child_exited = False
    sent_selection = False
    timed_out = False
    try:
        while True:
            if time.monotonic() >= deadline:
                timed_out = True
                break

            ready, _, _ = select.select([fd], [], [], 0.1)
            if ready:
                chunk = os.read(fd, 1024)
                if not chunk:
                    break
                output += chunk
                out_str = output.decode("utf-8", errors="ignore")

                if (
                    not sent_selection
                    and "Select a provider to login:" in out_str
                    and "codex" in out_str
                ):
                    # Send down arrow then Enter to select the second option (codex).
                    os.write(fd, b"\x1b[B\r")
                    sent_selection = True

                # Look for the dynamically generated localhost URL
                if "http" in out_str and "redirect_uri=" in out_str and port is None:
                    # Find the URL in the output
                    for line in out_str.splitlines():
                        if "http" in line and "redirect_uri=" in line:
                            try:
                                parsed = urllib.parse.urlparse(line.strip())
                                query = urllib.parse.parse_qs(parsed.query)
                                if "redirect_uri" in query:
                                    redirect_uri = query["redirect_uri"][0]
                                    redirect_parts = urllib.parse.urlparse(redirect_uri)
                                    if redirect_parts.port:
                                        port = redirect_parts.port
                                        break
                            except Exception:
                                pass

                    if port is not None:
                        # Unblock the server
                        # Try to use the discovered callback path if possible.
                        try:
                            callback_path = urllib.parse.urlparse(redirect_uri).path
                        except Exception:
                            callback_path = "/oauth2callback"

                        requests.get(
                            f"http://127.0.0.1:{port}{callback_path}?error=access_denied",
                            timeout=5,
                        )

            waited_pid, _ = os.waitpid(pid, os.WNOHANG)
            if waited_pid:
                child_exited = True
                break
    except OSError:
        pass
    finally:
        if not child_exited:
            try:
                waited_pid, _ = os.waitpid(pid, os.WNOHANG)
                if waited_pid == 0:
                    os.kill(pid, signal.SIGTERM)
                    os.waitpid(pid, 0)
            except ChildProcessError:
                pass

    full_output = output.decode("utf-8", errors="ignore")
    assert not timed_out, f"Timed out waiting for login wizard output: {full_output}"
    ansi_stripped_output = re.sub(r"\x1b\[[0-9;]*m", "", full_output)
    assert port is not None, f"Failed to find localhost port in output: {full_output}"
    assert port == 1455, f"Codex redirect_uri must use port 1455, got {port}"
    parsed_redirect = None
    for line in full_output.splitlines():
        if "redirect_uri=" not in line:
            continue
        parsed = urllib.parse.urlparse(line.strip())
        query = urllib.parse.parse_qs(parsed.query)
        if "redirect_uri" not in query:
            continue
        parsed_redirect = urllib.parse.urlparse(query["redirect_uri"][0])
        break

    assert parsed_redirect is not None
    assert parsed_redirect.hostname in ("localhost", "127.0.0.1"), (
        f"Unexpected redirect host: {parsed_redirect.hostname}"
    )
    assert parsed_redirect.port == 1455
    assert parsed_redirect.path == "/auth/callback"

    assert "Logging in to OpenAI Codex..." in full_output
    assert "RuntimeError: OAuth error: access_denied" in ansi_stripped_output


def test_login_wizard_fails_loudly_when_gum_missing(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["PATH"] = str(tmp_path)

    result = subprocess.run(
        [sys.executable, "-m", "usage_limits", "login"],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "Traceback (most recent call last)" in result.stderr
    assert "FileNotFoundError" in result.stderr
