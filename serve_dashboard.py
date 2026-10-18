"""
Partage le dashboard live sur votre réseau Wi-Fi pour le voir depuis un téléphone.

    python serve_dashboard.py            (laissez cette 2e fenêtre ouverte)

Sécurité : ce serveur ne sert QUE les fichiers dashboard_live_*.html.
Le reste du dossier (.env, journaux, code) n'est JAMAIS accessible.
Un mot de passe (paramètre ?key=...) est exigé, affiché au démarrage.
À utiliser sur un Wi-Fi de confiance (maison), pas sur un réseau public.
"""
import glob
import os
import secrets
import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

PORT = int(os.environ.get("DASHBOARD_PORT", "8765"))
KEY_FILE = ".dashboard_key"


def load_key() -> str:
    if os.environ.get("DASHBOARD_KEY"):
        return os.environ["DASHBOARD_KEY"]
    if os.path.exists(KEY_FILE):
        return open(KEY_FILE, encoding="utf-8").read().strip()
    key = secrets.token_urlsafe(8)
    with open(KEY_FILE, "w", encoding="utf-8") as f:
        f.write(key)
    return key


KEY = load_key()


def local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/plain; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if not secrets.compare_digest(q.get("key", [""])[0], KEY):
            return self._send(403, "Accès refusé")
        pages = sorted(glob.glob("dashboard_live_*.html"))
        if not pages:
            return self._send(404, "Dashboard pas encore créé : lancez d'abord le bot (live_trading.py).")
        name = os.path.basename(u.path.strip("/"))
        page = name if name in pages else pages[0]      # liste blanche stricte
        with open(page, "rb") as f:
            html = f.read()
        # le meta-refresh recharge l'URL courante (clé comprise) : rien à adapter
        self._send(200, html, "text/html; charset=utf-8")


if __name__ == "__main__":
    ip = local_ip()
    print("\n  📱 Dashboard partagé sur votre Wi-Fi")
    print(f"  Sur le téléphone (même Wi-Fi), ouvrez dans Chrome :")
    print(f"      http://{ip}:{PORT}/?key={KEY}\n")
    print("  Laissez cette fenêtre ouverte. Ctrl+C pour arrêter.")
    print("  (Si Windows demande d'autoriser Python sur le réseau : Réseau privé → Autoriser)\n")
    try:
        ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)
