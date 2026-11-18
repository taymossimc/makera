"""Record a Carvera job as a timelapse and serve the camera page.

The controller writes ``job-state.json``. While ``playing`` is true this
process stores a JPEG every few seconds under the host jobs directory, then
encodes an H.264 movie next to the other job files when playback stops.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

CAM = os.environ.get("CARVERA_CAM", "/dev/video0")
STATE_PATH = Path(os.environ.get("CARVERA_JOB_STATE", "/config/job-state.json"))
JOBS = Path(os.environ.get("CARVERA_JOBS_DIR", "/jobs"))
OUTPUT = JOBS / "timelapses"
INTERVAL = float(os.environ.get("TIMELAPSE_INTERVAL", "2"))
QUIET_SEC = float(os.environ.get("TIMELAPSE_QUIET_SEC", "180"))
MAX_BYTES = int(os.environ.get("TIMELAPSE_MAX_BYTES", str(8 * 1024 * 1024 * 1024)))
WIDTH = os.environ.get("TIMELAPSE_WIDTH", "1280")
HEIGHT = os.environ.get("TIMELAPSE_HEIGHT", "720")
PORT = int(os.environ.get("TIMELAPSE_PORT", "8081"))
STALE_SEC = 20.0

LATEST = Path("/tmp/carvera-latest.jpg")
_lock = threading.Lock()
_status = {
    "mode": "auto",
    "recording": False,
    "file": "",
    "error": "",
    "frames": 0,
    "camera": False,
}


def _now() -> float:
    return time.time()


def _safe_stem(name: str) -> str:
    base = os.path.splitext(os.path.basename(name or ""))[0]
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
    return (cleaned or "job")[:80]


def _read_state() -> dict | None:
    try:
        payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    updated = payload.get("updated") or ""
    try:
        stamp = datetime.strptime(updated, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        age = _now() - stamp.timestamp()
    except ValueError:
        age = STALE_SEC + 1
    if age > STALE_SEC:
        payload = dict(payload)
        payload["playing"] = False
        payload["stale"] = True
    return payload


def _fingerprint(path: Path) -> bytes:
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-vf",
            "scale=16:9",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-frames:v",
            "1",
            "pipe:1",
        ],
        check=False,
        capture_output=True,
    )
    return result.stdout


def _changed(previous: bytes, current: bytes) -> bool:
    if not previous or not current or len(previous) != len(current):
        return bool(current) and previous != current
    total = sum(abs(a - b) for a, b in zip(previous, current))
    return (total / len(current)) > 12


class Recorder:
    def __init__(self) -> None:
        self.mode = "auto"
        self.recording = False
        self.error = ""
        self.frames = 0
        self.file = ""
        self.session: Path | None = None
        self.previous = b""
        self.quiet_since: float | None = None
        self._tuned = False

    def snapshot(self) -> dict:
        with _lock:
            return {
                "mode": self.mode,
                "recording": self.recording,
                "file": self.file,
                "error": self.error,
                "frames": self.frames,
                "camera": Path(CAM).exists(),
            }

    def set_mode(self, mode: str) -> None:
        if mode not in {"auto", "on", "off"}:
            return
        with _lock:
            self.mode = mode

    def _tune(self) -> None:
        if self._tuned or not Path(CAM).exists():
            return
        # 2 is 60 Hz. The camera ships with a 50 Hz default.
        subprocess.run(
            ["v4l2-ctl", "-d", CAM, "-c", "power_line_frequency=2"],
            check=False,
            capture_output=True,
        )
        self._tuned = True

    def _grab(self, dest: Path) -> bool:
        dest.parent.mkdir(parents=True, exist_ok=True)
        temporary = dest.with_suffix(".part")
        result = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "v4l2",
                "-input_format",
                "mjpeg",
                "-video_size",
                f"{WIDTH}x{HEIGHT}",
                "-i",
                CAM,
                "-frames:v",
                "1",
                "-y",
                str(temporary),
            ],
            check=False,
            capture_output=True,
        )
        if result.returncode != 0 or not temporary.exists():
            temporary.unlink(missing_ok=True)
            self.error = "The camera did not return a frame."
            return False
        temporary.replace(dest)
        self.error = ""
        return True

    def _want(self, state: dict | None, frame: Path | None) -> bool:
        with _lock:
            mode = self.mode
        if mode == "off":
            return False
        if mode == "on":
            return True
        if state is not None:
            return bool(state.get("playing"))
        if frame is None:
            return False
        current = _fingerprint(frame)
        if not self.previous:
            self.previous = current
            return False
        moving = _changed(self.previous, current)
        self.previous = current
        if moving:
            self.quiet_since = None
            return True
        if self.quiet_since is None:
            self.quiet_since = _now()
        return self.recording and (_now() - self.quiet_since) < QUIET_SEC

    def _start(self, state: dict | None) -> None:
        name = _safe_stem((state or {}).get("file") or "job")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        session = OUTPUT / f".{name}-{stamp}"
        session.mkdir(parents=True, exist_ok=True)
        meta = {
            "file": (state or {}).get("file") or "",
            "remote_path": (state or {}).get("remote_path") or "",
            "local_path": (state or {}).get("local_path") or "",
            "started": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        (session / "job.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        with _lock:
            self.recording = True
            self.frames = 0
            self.file = name
            self.session = session

    def _finish(self) -> None:
        with _lock:
            session = self.session
            self.recording = False
            self.frames = 0
            self.session = None
            self.file = ""
        if session is None or not session.exists():
            return
        frames = sorted(session.glob("frame-*.jpg"))
        meta_path = session / "job.json"
        meta = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                meta = {}
        movie = OUTPUT / f"{session.name[1:]}.mp4"
        if len(frames) >= 2:
            encoded = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-framerate",
                    "30",
                    "-start_number",
                    "1",
                    "-i",
                    str(session / "frame-%06d.jpg"),
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-y",
                    str(movie),
                ],
                check=False,
            )
            if encoded.returncode == 0:
                meta["finished"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                movie.with_suffix(".json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
                shutil.rmtree(session, ignore_errors=True)
                _prune()
                return
            self.error = "Encoding the timelapse failed. Frames were kept."
            return
        shutil.rmtree(session, ignore_errors=True)

    def loop(self) -> None:
        while True:
            started = _now()
            self._tune()
            state = _read_state() if STATE_PATH.exists() else None
            camera = Path(CAM).exists()
            frame = LATEST if camera and self._grab(LATEST) else None
            want = self._want(state, frame if state is None else None)
            with _lock:
                recording = self.recording
            if want and not recording:
                self._start(state)
            elif recording and not want:
                self._finish()
            with _lock:
                session = self.session
                recording = self.recording
                count = self.frames + 1
            if recording and session is not None and frame is not None:
                target = session / f"frame-{count:06d}.jpg"
                shutil.copyfile(LATEST, target)
                with _lock:
                    self.frames = count
            elif not camera:
                self.error = "Camera is not attached."
            remaining = INTERVAL - (_now() - started)
            if remaining > 0:
                time.sleep(remaining)


def _prune() -> None:
    movies = sorted(OUTPUT.glob("*.mp4"), key=lambda path: path.stat().st_mtime)
    total = sum(path.stat().st_size for path in movies)
    for path in movies:
        if total <= MAX_BYTES:
            break
        total -= path.stat().st_size
        path.unlink(missing_ok=True)
        path.with_suffix(".json").unlink(missing_ok=True)


def _page(recorder: Recorder) -> bytes:
    status = recorder.snapshot()
    movies = []
    if OUTPUT.exists():
        movies = sorted(OUTPUT.glob("*.mp4"), key=lambda path: path.stat().st_mtime, reverse=True)
    items = "\n".join(
        f'<li><a href="/videos/{path.name}">{path.name}</a></li>' for path in movies[:50]
    ) or "<li>No timelapses yet.</li>"
    state = "Recording" if status["recording"] else "Idle"
    camera = "connected" if status["camera"] else "not attached"
    error = f"<p>{status['error']}</p>" if status["error"] else ""
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Carvera camera</title>
<meta http-equiv="refresh" content="5">
<style>
body {{ font-family: sans-serif; margin: 2rem; background: #111; color: #eee; }}
img {{ max-width: 100%; background: #000; }}
a {{ color: #9cf; }}
button {{ font-size: 1rem; margin-right: 0.5rem; }}
</style>
</head>
<body>
<h1>Carvera camera</h1>
<p>{state}. Camera {camera}. Mode {status["mode"]}. Frames this clip: {status["frames"]}.</p>
{error}
<p><img src="/latest.jpg" alt="Latest camera frame"></p>
<form method="post" action="/override">
<button name="mode" value="auto">Follow the job</button>
<button name="mode" value="on">Record now</button>
<button name="mode" value="off">Stop</button>
</form>
<h2>Timelapses</h2>
<ul>
{items}
</ul>
</body>
</html>
"""
    return html.encode("utf-8")


def make_handler(recorder: Recorder):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path in {"/", "/index.html"}:
                body = _page(recorder)
                self._send(200, "text/html; charset=utf-8", body)
                return
            if path == "/latest.jpg":
                if LATEST.exists():
                    self._send(200, "image/jpeg", LATEST.read_bytes())
                else:
                    self._send(404, "text/plain", b"No frame yet.\n")
                return
            if path.startswith("/videos/"):
                name = os.path.basename(path[len("/videos/") :])
                movie = OUTPUT / name
                if movie.is_file() and movie.suffix == ".mp4":
                    self._send_file(movie, "video/mp4")
                    return
            self._send(404, "text/plain", b"Not found.\n")

        def do_POST(self) -> None:  # noqa: N802
            if self.path.split("?", 1)[0] != "/override":
                self._send(404, "text/plain", b"Not found.\n")
                return
            length = int(self.headers.get("Content-Length", "0"))
            form = parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
            mode = (form.get("mode") or ["auto"])[0]
            recorder.set_mode(mode)
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()

        def _send_file(self, path: Path, content_type: str) -> None:
            size = path.stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            with path.open("rb") as handle:
                while True:
                    chunk = handle.read(1024 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)

        def _send(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    recorder = Recorder()
    threading.Thread(target=recorder.loop, name="capture", daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), make_handler(recorder))
    server.serve_forever()


if __name__ == "__main__":
    main()
