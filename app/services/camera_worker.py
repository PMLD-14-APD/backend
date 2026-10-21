import threading
import time
import cv2


class CameraWorker(threading.Thread):
    """Satu thread per kamera. Nyimpen frame TERBARU aja (bukan antrean),
    biar nggak ada lag menumpuk kalau processing lebih lambat dari stream."""

    def __init__(self, camera_id: str, stream_url: str, target_fps: int = 5, on_frame=None):
        super().__init__(daemon=True)
        self.camera_id = camera_id
        self.stream_url = stream_url
        self.target_fps = target_fps
        self.interval = 1.0 / target_fps

        # callback opsional: dipanggil tiap ada frame baru, misal buat lempar ke inference
        self.on_frame = on_frame

        self.latest_frame = None
        self.lock = threading.Lock()
        self.running = True
        self.connected = False

    def run(self):
        cap = cv2.VideoCapture(self.stream_url)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        if not cap.isOpened():
            print(f"[camera:{self.camera_id}] GAGAL connect ke {self.stream_url}")
            self.running = False
            return

        self.connected = True
        print(f"[camera:{self.camera_id}] Terhubung: {self.stream_url}")

        last_grab = 0
        while self.running:
            ret, frame = cap.read()
            if not ret:
                print(f"[camera:{self.camera_id}] Stream putus, reconnecting...")
                cap.release()
                time.sleep(1)
                cap = cv2.VideoCapture(self.stream_url)
                continue

            now = time.time()
            if now - last_grab >= self.interval:
                with self.lock:
                    self.latest_frame = frame
                last_grab = now

                if self.on_frame:
                    self.on_frame(self.camera_id, frame)

        cap.release()
        self.connected = False

    def get_frame(self):
        with self.lock:
            return self.latest_frame.copy() if self.latest_frame is not None else None

    def stop(self):
        self.running = False
