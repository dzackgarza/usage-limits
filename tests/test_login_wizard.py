"""Tests for the interactive login wizard boundary."""

from __future__ import annotations

import os
import pty
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
    
    # Wait a bit for gum to initialize and draw the UI
    time.sleep(0.5)
    
    # Send "j" (down arrow in gum/vim-mode) then Enter to select the second option (codex)
    os.write(fd, b"j\r")

    # Read output until the process exits or we find the URL
    try:
        while True:
            chunk = os.read(fd, 1024)
            if not chunk:
                break
            output += chunk
            out_str = output.decode("utf-8", errors="ignore")
            
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
                    # Try to use the discovered callback path if possible, else default to /oauth2callback
                    try:
                        callback_path = urllib.parse.urlparse(redirect_uri).path
                    except Exception:
                        callback_path = "/oauth2callback"
                    
                    requests.get(f"http://127.0.0.1:{port}{callback_path}?error=access_denied")
    except OSError:
        pass

    os.waitpid(pid, 0)
    
    full_output = output.decode("utf-8", errors="ignore")
    assert port is not None, f"Failed to find localhost port in output: {full_output}"
    assert port == 1455, f"Codex redirect_uri must use port 1455, got {port}"
    assert "redirect_uri=http%3A%2F%2F127.0.0.1%3A1455%2Fauth%2Fcallback" in full_output, "redirect_uri must exactly match what OpenAI authorized"
    
    assert "Logging in to OpenAI Codex..." in full_output
    assert "RuntimeError: OAuth error: access_denied" in full_output


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

