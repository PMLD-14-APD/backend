"""Jembatan uji lokal: webcam USB / file video -> stream MJPEG over HTTP yang bisa didaftarkan sebagai CCTV.

BE_V2 sengaja hanya menerima stream_url rtsp/rtsps/http/https (server tidak boleh membuka device/file
lokal atas permintaan user). Untuk uji di laptop, jalankan jembatan ini lalu daftarkan
http://127.0.0.1:8554/cam.mjpg lewat "Tambah Kamera" di FE.

    python scripts/cctv_bridge.py 0                     # webcam /dev/video0
    python scripts/cctv_bridge.py video.mp4             # file, diputar ulang terus dengan kecepatan asli
    python scripts/cctv_bridge.py 0 --port 8555 --stamp # beberapa jembatan sekaligus, + cap waktu untuk ukur delay

--stamp menulis waktu kirim (ms) sebagai teks + 32 kotak hitam/putih di pojok kiri atas, sehingga
delay end-to-end bisa dibaca dari frame hasil (lihat decode_stamp).
"""
import argparse
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np

BOUNDARY = b"cctvframe"
STAMP_BITS, STAMP_BLOCK = 32, 12


def draw_stamp(frame, now_ms: int) -> None:
    value = now_ms & 0xFFFFFFFF
    for i in range(STAMP_BITS):
        bit = (value >> (STAMP_BITS - 1 - i)) & 1
        x = i * STAMP_BLOCK
        frame[0:STAMP_BLOCK, x:x + STAMP_BLOCK] = 255 if bit else 0
    cv2.putText(frame, str(now_ms % 100000), (4, STAMP_BLOCK + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)


def decode_stamp(frame, scale: float = 1.0) -> int:
    """Kebalikan draw_stamp (32 bit terbawah epoch ms). `scale` = lebar frame hasil / lebar frame asli."""
    gray = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    value = 0
    for i in range(STAMP_BITS):
        cx, cy = int((i * STAMP_BLOCK + STAMP_BLOCK / 2) * scale), int(STAMP_BLOCK / 2 * scale)
        value = (value << 1) | int(gray[cy, cx] > 127)
    return value


class Source(threading.Thread):
    def __init__(self, source: str, width: int, stamp: bool):
        super().__init__(daemon=True)
        self.source, self.width, self.stamp = source, width, stamp
        self.is_device = source.isdigit()
        self.cond = threading.Condition()
        self.seq, self.jpeg = 0, None

    def _open(self):
        if self.is_device:
            cap = cv2.VideoCapture(int(self.source), cv2.CAP_V4L2)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            return cap
        return cv2.VideoCapture(self.source)

    def run(self):
        while True:
            cap = self._open()
            if not cap.isOpened():
                print(f"[bridge] gagal membuka {self.source}, coba lagi 2 detik", flush=True)
                time.sleep(2)
                continue
            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            start, n = time.monotonic(), 0
            while True:
                ok, frame = cap.read()
                if not ok:
                    break                       # file habis -> putar ulang; webcam putus -> buka ulang
                h, w = frame.shape[:2]
                if w > self.width:
                    frame = cv2.resize(frame, (self.width, round(h * self.width / w)), interpolation=cv2.INTER_AREA)
                if self.stamp:
                    draw_stamp(frame, int(time.time() * 1000))
                ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                with self.cond:
                    self.seq, self.jpeg = self.seq + 1, buf.tobytes()
                    self.cond.notify_all()
                if not self.is_device:          # webcam sudah dibatasi kecepatannya sendiri
                    n += 1
                    delay = start + n / fps - time.monotonic()
                    if delay > 0:
                        time.sleep(delay)
            cap.release()
            if self.is_device:
                time.sleep(1)


def make_handler(source: Source):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.split("?")[0] != "/cam.mjpg":
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY.decode()}")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            last = -1
            try:
                while True:
                    with source.cond:
                        source.cond.wait_for(lambda: source.seq != last, timeout=5)
                        last, data = source.seq, source.jpeg
                    if data is None:
                        continue
                    self.wfile.write(b"--" + BOUNDARY + b"\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                     + str(len(data)).encode() + b"\r\n\r\n" + data + b"\r\n")
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, fmt, *args):
            print(f"[bridge] {self.client_address[0]} {fmt % args}", flush=True)

    return Handler


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="index webcam (0, 1, ...), path file video, atau URL yang bisa dibuka OpenCV")
    ap.add_argument("--host", default="127.0.0.1", help="default hanya localhost; 0.0.0.0 untuk dibuka dari mesin lain")
    ap.add_argument("--port", type=int, default=8554)
    ap.add_argument("--width", type=int, default=1280, help="perkecil frame yang lebih lebar dari ini")
    ap.add_argument("--stamp", action="store_true", help="tulis cap waktu di frame untuk mengukur delay")
    args = ap.parse_args()
    src = Source(args.source, args.width, args.stamp)
    src.start()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(src))
    server.daemon_threads = True
    print(f"[bridge] http://{args.host}:{args.port}/cam.mjpg <- {args.source}", flush=True)
    server.serve_forever()
