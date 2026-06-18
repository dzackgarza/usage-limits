import os
import pty
import time

pid, fd = pty.fork()
if pid == 0:
    # Child process
    os.execlp("gum", "gum", "choose", "antigravity", "codex", "gemini")
else:
    # Parent process
    time.sleep(0.5)
    os.write(fd, b"\x1b[B\r")  # Down arrow, Enter
    output = b""
    try:
        while True:
            chunk = os.read(fd, 1024)
            if not chunk:
                break
            output += chunk
    except OSError:
        pass
    os.waitpid(pid, 0)
    print("OUTPUT:", output.decode("utf-8", errors="ignore"))
