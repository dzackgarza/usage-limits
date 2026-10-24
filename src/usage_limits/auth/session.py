"""Connect headless collection to the login user's credential service."""

from __future__ import annotations

import os
import sys


def configure_session_bus() -> None:
    """Use systemd's per-user bus when the shell did not export its address.

    Runtime directory reference:
    https://www.freedesktop.org/software/systemd/man/latest/pam_systemd.html
    """
    if sys.platform != "linux" or "DBUS_SESSION_BUS_ADDRESS" in os.environ:
        return
    os.environ["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path=/run/user/{os.getuid()}/bus"
