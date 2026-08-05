"""Server dev anti-cache untuk Kertas Fenomena.

Jalankan: python dev_server.py
Buka:     http://127.0.0.1:8000/frontend/index.html

Bind ke 127.0.0.1 saja (HP tidak bisa akses). Untuk uji HP satu WiFi,
pakai server LAN terpisah yang bind 0.0.0.0 (lihat kertas-cuaca/scratchpad).
"""
import http.server
import socketserver
import os

PORT = 8000
ROOT = os.path.dirname(os.path.abspath(__file__))


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    os.chdir(ROOT)
    with socketserver.TCPServer(("127.0.0.1", PORT), NoCacheHandler) as httpd:
        print(f"Kertas Fenomena dev server: http://127.0.0.1:{PORT}/frontend/index.html")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")
