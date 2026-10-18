"""Share this laptop's webcam on the local network, so another laptop's backend can use it.

On the laptop WITH the webcam (needs only opencv-python):
    python -m vision.stream_webcam              # webcam 0 on port 8081
    python -m vision.stream_webcam --camera 1 --port 8082

It prints the line to paste as the camera source on the laptop running the backend, e.g.
    url:http://192.168.1.23:8081/video

Endpoints: /video (MJPEG stream), /snapshot.jpg (one frame), / (a preview page).
One reader thread grabs frames; every connected viewer gets the newest one, so several
viewers (the backend plus a browser preview) don't slow each other down.
Both laptops must be on the same network. Venue Wi-Fi often blocks device-to-device
traffic; a phone hotspot avoids that. Windows asks once to allow Python through the
firewall: allow it on private networks.
"""

import argparse
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2

from vision.capture import Capture

BOUNDARY = b"frame"


def lan_addresses() -> list[str]:
    """This machine's IPv4 addresses that other devices can use (no packets are sent)."""
    found = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))  # UDP connect picks the outgoing interface without sending
        found.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in found:
                found.append(ip)
    except OSError:
        pass
    return found


class FrameHub:
    """Newest JPEG from one camera, shared by all viewers."""

    def __init__(self, source: str, width: int, fps: float, quality: int):
        self.capture = Capture(source, width=width)
        self.interval = 1.0 / fps
        self.quality = quality
        self.jpeg: bytes | None = None
        self.seq = 0
        self.cond = threading.Condition()
        self.stopped = False
        threading.Thread(target=self._run, name="stream-reader", daemon=True).start()

    def _run(self) -> None:
        next_at = 0.0
        while not self.stopped:
            frame = self.capture.read(timeout=1.0)
            if frame is None:
                continue  # camera offline: Capture retries every 2 s
            now = time.monotonic()
            if now < next_at:
                continue  # cap the stream rate; the backend can't use more than ~10-15 fps anyway
            next_at = now + self.interval
            ok, buf = cv2.imencode(".jpg", frame.image, [cv2.IMWRITE_JPEG_QUALITY, self.quality])
            if ok:
                with self.cond:
                    self.jpeg, self.seq = buf.tobytes(), self.seq + 1
                    self.cond.notify_all()

    def wait_new(self, last_seq: int, timeout: float = 2.0) -> tuple[bytes | None, int]:
        with self.cond:
            self.cond.wait_for(lambda: self.seq != last_seq or self.stopped, timeout)
            return self.jpeg, self.seq

    def stop(self) -> None:
        self.stopped = True
        self.capture.release()
        with self.cond:
            self.cond.notify_all()


PAGE = b"""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Webcam stream</title><style>body{margin:0;background:#111;color:#ddd;font:15px system-ui;text-align:center}
img{max-width:100%;height:auto}</style></head><body><p>Live webcam stream. Use <b>/video</b> as the camera source.</p>
<img src='/video'></body></html>"""


def make_handler(hub: FrameHub):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # keep the console for the connect/disconnect lines below
            pass

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/":
                self._send(200, "text/html; charset=utf-8", PAGE)
            elif path == "/snapshot.jpg":
                jpeg, _ = hub.wait_new(-1, timeout=3.0)
                if jpeg is None:
                    self._send(503, "text/plain", b"camera not ready")
                else:
                    self._send(200, "image/jpeg", jpeg)
            elif path == "/video":
                self._stream()
            else:
                self._send(404, "text/plain", b"not found")

        def _send(self, code, ctype, body: bytes):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _stream(self):
            client = self.client_address[0]
            print(f"[stream] viewer connected: {client}", flush=True)
            self.send_response(200)
            self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY.decode()}")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            seq = -1
            try:
                while not hub.stopped:
                    jpeg, seq = hub.wait_new(seq)
                    if jpeg is None:
                        continue
                    self.wfile.write(b"--" + BOUNDARY + b"\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                     + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            print(f"[stream] viewer left: {client}", flush=True)

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Share a webcam on the local network as an MJPEG stream.")
    parser.add_argument("--camera", type=int, default=0, help="webcam index (default 0)")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--width", type=int, default=1280, help="frame width sent (default 1280)")
    parser.add_argument("--fps", type=float, default=15, help="max frames per second sent (default 15)")
    parser.add_argument("--quality", type=int, default=80, help="JPEG quality 1-100 (default 80)")
    args = parser.parse_args()

    hub = FrameHub(f"webcam:{args.camera}", args.width, args.fps, args.quality)
    try:
        server = ThreadingHTTPServer(("0.0.0.0", args.port), make_handler(hub))
    except OSError as exc:
        hub.stop()
        sys.exit(f"cannot listen on port {args.port}: {exc}. Try --port {args.port + 1}.")
    server.daemon_threads = True

    ips = lan_addresses()
    print(f"Sharing webcam {args.camera} on port {args.port}. Press Ctrl+C to stop.")
    if ips:
        print("Paste this as the camera source on the laptop running the backend:")
        print(f"    url:http://{ips[0]}:{args.port}/video")
        if len(ips) > 1:  # often virtual adapters (WSL, Hyper-V, VPN) that other devices can't reach
            print("  if that address doesn't work, try: " + ", ".join(f"url:http://{ip}:{args.port}/video" for ip in ips[1:]))
        print(f"Preview in any browser on the network: http://{ips[0]}:{args.port}/")
    else:
        print(f"No network address found. This machine only: url:http://127.0.0.1:{args.port}/video")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        hub.stop()


if __name__ == "__main__":
    main()
