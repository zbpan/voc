import atexit
import logging
import os
import socket
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
host, port = "127.0.0.1", int(os.environ.get("VOC_PORT", "8765"))
with socket.socket() as probe:
    if probe.connect_ex((host, port)) == 0:
        raise SystemExit(f"ERROR: port {port} is already in use")

from voc.config import load_settings

settings = load_settings()
settings.root.mkdir(parents=True, exist_ok=True)
pid_file = settings.root / "server.pid"
pid_file.write_text(str(os.getpid()), encoding="ascii")
atexit.register(lambda: pid_file.unlink(missing_ok=True))
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
print(f"VOC ready to start: http://{host}:{port}", flush=True)
uvicorn.run("voc.main:app", host=host, port=port, log_level="info", access_log=False)
