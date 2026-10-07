"""Vigilia - supervision reseau en lecture seule.

Lancer :  python server.py [--port 8090]
Premier lancement : le compte admin est cree avec un mot de passe aleatoire affiche une seule fois.
Mode demonstration (defaut) : reseau fictif. Mode reel : --live --hosts <IP ou plages> (SSH lecture seule ; SW_USER, SW_PASS ou identifiant systemd).
"""
import argparse
import ssl
import json
import os
import re
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import auth
from auth import ROLES
from db import Db

WEB = Path(__file__).parent / "web"

STATIC = {
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/login.js": ("login.js", "text/javascript; charset=utf-8"),
    "/views.js": ("views.js", "text/javascript; charset=utf-8"),
    "/theme.js": ("theme.js", "text/javascript; charset=utf-8"),
    "/topo.js": ("topo.js", "text/javascript; charset=utf-8"),
    "/devices.js": ("devices.js", "text/javascript; charset=utf-8"),
    "/journal.js": ("journal.js", "text/javascript; charset=utf-8"),
    "/account.js": ("account.js", "text/javascript; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
}

from hints import HINTS  # noqa: E402


SIM = None
DB = None
SESSIONS = {}
RATE = {}
LOCK = threading.Lock()
SECURE = False
COOKIE = "vig_session"
IDLE_TTL = 2 * 3600    # deconnexion apres 2 h d'inactivite
ABS_TTL = 12 * 3600    # et au plus 12 h apres la connexion
MAX_SESSIONS_PER_USER = 5
NOAUTH = ("/login.js", "/favicon.svg", "/app.css", "/theme.js")
FONTS = ("space-grotesk.woff2", "jetbrains-mono.woff2")


def log_event(msg):
    """Evenements de securite : visibles avec `journalctl -u vigilia`."""
    print(f"[securite] {time.strftime('%Y-%m-%d %H:%M:%S')} {msg}", file=sys.stderr, flush=True)


def recent(key, per):
    now = time.time()
    with LOCK:
        q = [t for t in RATE.get(key, []) if now - t < per]
        RATE[key] = q
        return len(q)


def hit(key):
    with LOCK:
        RATE.setdefault(key, []).append(time.time())
        if len(RATE) > 5000:  # purge des cles anciennes
            now = time.time()
            for k in [k for k, v in RATE.items() if not v or now - v[-1] > 3600]:
                RATE.pop(k, None)


def rate_ok(key, limit, per=60.0):
    """Limiteur a fenetre glissante : True si l'action est permise (et la compte)."""
    if recent(key, per) >= limit:
        return False
    hit(key)
    return True


class Handler(BaseHTTPRequestHandler):
    server_version = "Vigilia"
    sys_version = ""
    timeout = 20  # coupe les connexions lentes ou inactives (slowloris)

    def log_message(self, fmt, *args):
        pass

    # ---------------------------------------------------------------- helpers
    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                                                    "base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'")
        if SECURE:
            self.send_header("Strict-Transport-Security", "max-age=31536000")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj, code=200, extra=None):
        self._send(code, json.dumps(obj), extra=extra)

    def _cookie(self, tok):
        return {"Set-Cookie": f"{COOKIE}={tok}; Path=/; Max-Age={ABS_TTL if tok else 0}; HttpOnly; SameSite=Strict" + ("; Secure" if SECURE else "")}

    def _ip(self):
        return self.client_address[0]

    def _token(self):
        for part in self.headers.get("Cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE:
                return v
        return None

    def _session(self):
        tok, now = self._token(), time.time()
        with LOCK:
            s = SESSIONS.get(tok)
            if s and (now > s["abs"] or now - s["last"] > IDLE_TTL):
                SESSIONS.pop(tok, None)
                return None
            if s:
                u = auth.get_users().get(s["user"])
                if not u or u["role"] != s["role"]:  # compte supprime ou role modifie : la session tombe
                    SESSIONS.pop(tok, None)
                    return None
                s["last"] = now
            return s

    def _new_session(self, user, role):
        tok, now = secrets.token_urlsafe(32), time.time()
        with LOCK:
            mine = sorted((v["last"], k) for k, v in SESSIONS.items() if v["user"] == user)
            for _, k in mine[:max(0, len(mine) - MAX_SESSIONS_PER_USER + 1)]:
                SESSIONS.pop(k, None)
            SESSIONS[tok] = {"tok": tok, "user": user, "role": role, "abs": now + ABS_TTL, "last": now}
        return tok

    def _revoke_user(self, user):
        with LOCK:
            for k in [k for k, v in SESSIONS.items() if v["user"] == user]:
                SESSIONS.pop(k, None)

    def _need(self, role):
        """Renvoie la session si elle a au moins ce role, sinon repond 401/403 et renvoie None."""
        s = self._session()
        if not s:
            self._json({"error": "auth"}, 401)
            return None
        if ROLES[s["role"]] < ROLES[role]:
            log_event(f"acces refuse ({s['user']}/{s['role']} -> {self.path.split('?')[0]}) depuis {self._ip()}")
            self._json({"error": "droits insuffisants"}, 403)
            return None
        return s

    def _body(self):
        try:
            n = max(0, min(int(self.headers.get("Content-Length") or 0), 8192))
            d = json.loads(self.rfile.read(n) or b"{}")
            return d if isinstance(d, dict) else {}
        except ValueError:
            return {}

    def _live(self, name):
        return getattr(SIM, name, None)

    def _origin_ok(self):
        """Anti-CSRF : une requete d'ecriture doit venir de notre propre page."""
        origin, host = self.headers.get("Origin"), self.headers.get("Host", "")
        if origin:
            return urlparse(origin).netloc == host
        return self.headers.get("Sec-Fetch-Site") in (None, "same-origin", "none")

    @staticmethod
    def _int(v, default=0):
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    # ----------------------------------------------------------------- routes
    def do_GET(self):
        u = urlparse(self.path)
        path, q = u.path, {k: v[0] for k, v in parse_qs(u.query).items()}
        if path == "/":
            page = "app.html" if self._session() else "login.html"
            return self._send(200, (WEB / page).read_bytes(), "text/html; charset=utf-8")
        if path in STATIC:
            if path not in NOAUTH and not self._session():
                return self._send(401, "{}")
            f, ct = STATIC[path]
            return self._send(200, (WEB / f).read_bytes(), ct)
        if path.startswith("/fonts/") and path[7:] in FONTS:
            return self._send(200, (WEB / "fonts" / path[7:]).read_bytes(), "font/woff2")
        if not path.startswith("/api/"):
            return self._json({"error": "not found"}, 404)
        s = self._need("viewer")
        if not s:
            return
        if path == "/api/state":
            snap = SIM.snapshot()
            if s["role"] == "viewer":
                snap.pop("ssh_user", None)  # le compte d'administration des switches n'a pas a etre connu d'un simple lecteur
            return self._json(snap)
        if path == "/api/me":
            prev = DB.query("SELECT t, ip FROM audit WHERE user=? AND action='login' ORDER BY id DESC LIMIT 2", (s["user"],))
            tt = auth.get_totp(s["user"])
            return self._json({"user": s["user"], "role": s["role"], "totp": bool(tt and tt.get("enabled")),
                               "last_login": prev[1] if len(prev) > 1 else None})
        if path == "/api/port":
            if not rate_ok("port:" + s["tok"], 60):  # chaque appel peut interroger un switch
                return self._json({"error": "trop de requetes"}, 429)
            fn = self._live("port_detail")
            return self._json(fn(q.get("ip", ""), q.get("port", "")) if fn else {"demo": True})
        if path in ("/api/history", "/api/report"):
            if not rate_ok("rep:" + s["tok"], 30):
                return self._json({"error": "trop de requetes"}, 429)
            fn = self._live("history" if path == "/api/history" else "report")
            if not fn:
                return self._json({"demo": True})
            return self._json(fn(q.get("range", "1h")) if path == "/api/history" else fn(self._int(q.get("days"), 7)))
        if path in ("/api/events", "/api/event"):
            if not rate_ok("ev:" + s["tok"], 120):
                return self._json({"error": "trop de requetes"}, 429)
            fn = self._live("events_query" if path == "/api/events" else "event_detail")
            if not fn:
                return self._json({"demo": True})
            if path == "/api/events":
                return self._json(fn(limit=self._int(q.get("limit"), 200), before=self._int(q.get("before")), sev=q.get("sev", "")[:8], sw=q.get("sw", "")[:60],
                                     kind=q.get("kind", "")[:30], q=q.get("q", "")[:80], days=self._int(q.get("days"))))
            r = fn(self._int(q.get("id")))
            return self._json(r or {"error": "introuvable"}, 200 if r else 404)
        if path == "/api/logs.zip":
            if not self._need("tech"):
                return
            fn = self._live("logs_zip")
            if not fn:
                return self._json({"demo": True})
            if not rate_ok("zip:" + s["user"], 6, 3600):
                return self._json({"error": "trop d'exports, reessayez plus tard"}, 429)
            days = max(1, min(self._int(q.get("days"), 30), 365))
            data, name = fn(days, s["role"] == "admin", s["user"])  # l'audit n'est inclus que pour un administrateur
            DB.audit(s["user"], "logs_export", f"{days} jours, {len(data)} octets", self._ip())
            return self._send(200, data, "application/zip", {"Content-Disposition": f'attachment; filename="{name}"'})
        if path in ("/api/configs", "/api/config", "/api/diff"):
            if not self._need("tech"):
                return
            if not self._live("configs"):
                return self._json({"demo": True})
            mask = s["role"] != "admin"  # les secrets (hash SNMP, mots de passe) ne sont visibles que par un admin
            if path == "/api/configs":
                return self._json(SIM.configs(q.get("ip", "")))
            if path == "/api/config":
                r = SIM.config_text(self._int(q.get("id")))
                DB.audit(s["user"], "config_view", q.get("id", "")[:20], self._ip())
                if r and mask:
                    r["text"] = auth.mask_secrets(r["text"])
                return self._json(r or {"error": "introuvable"})
            r = SIM.config_diff(self._int(q.get("a")), self._int(q.get("b")))
            if r and mask:
                r["diff"] = auth.mask_secrets(r["diff"])
            return self._json(r or {"error": "introuvable"})
        if path == "/api/audit":
            if not self._need("admin"):
                return
            return self._json({"audit": DB.query("SELECT t, user, action, detail, ip FROM audit ORDER BY id DESC LIMIT 300"),
                               "users": [{"user": k, "role": v["role"]} for k, v in auth.get_users().items()]})
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        path, ip = urlparse(self.path).path, self._ip()
        if not self._origin_ok():
            log_event(f"POST refuse (origine) {path} depuis {ip}")
            return self._json({"error": "origine refusee"}, 403)
        if path != "/logout" and not self.headers.get("Content-Type", "").startswith("application/json"):
            return self._json({"error": "JSON attendu"}, 415)
        if path == "/logout":
            s = self._session()
            if s:
                with LOCK:
                    SESSIONS.pop(s["tok"], None)
                DB.audit(s["user"], "logout", "", ip)
            return self._json({}, extra=self._cookie(""))
        if path == "/login":
            return self._login(ip)
        if path == "/api/password":
            return self._password(ip)
        if path in ("/api/totp/start", "/api/totp/enable", "/api/totp/disable"):
            return self._totp(path, ip)
        if path == "/api/users":
            s = self._need("admin")
            if not s:
                return
            if not rate_ok("mkuser:" + s["user"], 10, 3600):
                return self._json({"error": "trop de creations de comptes, reessayez plus tard"}, 429)
            b = self._body()
            name, role, pw = str(b.get("user", "")).strip(), str(b.get("role", "")), str(b.get("password", ""))[:256]
            if not re.fullmatch(r"[A-Za-z0-9._-]{3,32}", name):
                return self._json({"error": "nom invalide (3 a 32 caracteres : lettres, chiffres, point, tiret, souligne)"}, 400)
            if role not in ROLES:
                return self._json({"error": "role invalide"}, 400)
            generated = not pw
            if generated:
                pw = auth.random_password()
            elif auth.policy_error(pw, name):
                return self._json({"error": auth.policy_error(pw, name)}, 400)
            if not auth.create_user(name, role, pw):
                return self._json({"error": "ce compte existe deja"}, 409)
            DB.audit(s["user"], "user_create", f"{name} ({role})", ip)
            log_event(f"compte cree par {s['user']} : {name} ({role}) depuis {ip}")
            return self._json({"ok": True, "user": name, "role": role, "password": pw if generated else None})
        if path == "/api/note":
            s = self._need("tech")
            if not s:
                return
            b = self._body()
            fn = self._live("set_note")
            ok = fn(str(b.get("key", ""))[:80], str(b.get("text", "")), s["user"]) if fn else False
            if ok:
                DB.audit(s["user"], "note", f"{str(b.get('key'))[:60]}: {str(b.get('text', ''))[:80]}", ip)
            return self._json({"ok": bool(ok)}, 200 if ok else 400)
        if path == "/api/backup":
            s = self._need("tech")
            if not s:
                return
            fn = self._live("backup_config")
            ipsw = str(self._body().get("ip", ""))[:40]
            r = fn(ipsw, s["user"]) if fn else {"error": "mode simulation"}
            DB.audit(s["user"], "backup", f"{ipsw}: {r}", ip)
            return self._json(r)
        self._json({"error": "not found"}, 404)

    def _login(self, ip):
        d = self._body()
        user, pw = str(d.get("user", ""))[:64], str(d.get("password", ""))[:256]
        ukey = user.lower()
        if recent("ipfail:" + ip, 60) >= 5 or recent("ufail:" + ukey, 900) >= 10:
            log_event(f"connexion bloquee (trop d'echecs) compte={user[:30]!r} ip={ip}")
            return self._send(429, '{"error":"trop de tentatives"}', extra={"Retry-After": "60"})
        role = auth.verify(user, pw)
        if not role:
            hit("ipfail:" + ip)
            hit("ufail:" + ukey)
            DB.audit(user[:40], "login_echec", "", ip)
            log_event(f"echec de connexion compte={user[:30]!r} ip={ip}")
            time.sleep(0.5)  # ralentit une attaque par force brute
            return self._json({"error": "invalid"}, 401)
        tt = auth.get_totp(user)
        if tt and tt.get("enabled"):  # double authentification : le mot de passe est bon, il faut maintenant le code
            code = re.sub(r"\s", "", str(d.get("code", "")))[:8]
            if not code:
                return self._json({"need_totp": True})
            step = auth.totp_verify(tt["secret"], code, tt.get("last", 0))
            if step is None:
                hit("ipfail:" + ip)
                hit("ufail:" + ukey)
                DB.audit(user[:40], "login_echec_totp", "", ip)
                log_event(f"code de double authentification incorrect compte={user[:30]!r} ip={ip}")
                time.sleep(0.5)
                return self._json({"error": "invalid"}, 401)
            auth.set_totp(user, dict(tt, last=step))  # un code ne sert qu'une fois
        with LOCK:
            RATE.pop("ufail:" + ukey, None)
        tok = self._new_session(user, role)
        DB.audit(user, "login", role, ip)
        self._json({}, extra=self._cookie(tok))

    def _totp(self, path, ip):
        s = self._need("viewer")
        if not s:
            return
        if not rate_ok("totp:" + s["user"], 8, 900):
            return self._json({"error": "trop de tentatives, reessayez plus tard"}, 429)
        b, user = self._body(), s["user"]
        t = auth.get_totp(user) or {}
        if path == "/api/totp/start":
            if t.get("enabled"):
                return self._json({"error": "deja activee"}, 409)
            secret = auth.totp_new()
            auth.set_totp(user, {"secret": secret, "enabled": False, "last": 0})
            return self._json({"secret": secret, "uri": f"otpauth://totp/Vigilia:{quote(user)}?secret={secret}&issuer=Vigilia&digits=6&period=30"})
        code = re.sub(r"\s", "", str(b.get("code", "")))[:8]
        if path == "/api/totp/enable":
            step = auth.totp_verify(t["secret"], code, 0) if t.get("secret") and not t.get("enabled") else None
            if step is None:
                log_event(f"activation double authentification refusee compte={user} ip={ip}")
                return self._json({"error": "code incorrect"}, 400)
            auth.set_totp(user, {"secret": t["secret"], "enabled": True, "last": step})
            DB.audit(user, "totp_on", "double authentification activee", ip)
            return self._json({"ok": True})
        # desactivation : mot de passe ET code actuel
        step = auth.totp_verify(t["secret"], code, t.get("last", 0)) if t.get("enabled") else None
        if auth.verify(user, str(b.get("password", ""))[:256]) is None or step is None:
            log_event(f"desactivation double authentification refusee compte={user} ip={ip}")
            return self._json({"error": "mot de passe ou code incorrect"}, 403)
        auth.set_totp(user, None)
        DB.audit(user, "totp_off", "double authentification desactivee", ip)
        return self._json({"ok": True})

    def _password(self, ip):
        s = self._need("viewer")
        if not s:
            return
        if not rate_ok("pw:" + s["user"], 5, 900):
            return self._json({"error": "trop de tentatives, reessayez plus tard"}, 429)
        b = self._body()
        old, new = str(b.get("old", ""))[:256], str(b.get("new", ""))[:256]
        if auth.verify(s["user"], old) is None:
            DB.audit(s["user"], "password_echec", "", ip)
            log_event(f"changement de mot de passe refuse (ancien incorrect) compte={s['user']} ip={ip}")
            return self._json({"error": "mot de passe actuel incorrect"}, 403)
        err = auth.policy_error(new, s["user"]) or ("identique a l'ancien" if new == old else None)
        if err:
            return self._json({"error": err}, 400)
        auth.set_password(s["user"], new)
        self._revoke_user(s["user"])  # toutes les sessions de ce compte tombent, une nouvelle est ouverte
        tok = self._new_session(s["user"], s["role"])
        DB.audit(s["user"], "password", "mot de passe change", ip)
        self._json({"ok": True}, extra=self._cookie(tok))


class LimitedServer(ThreadingHTTPServer):
    """Plafonne les connexions simultanees (au total et par adresse) pour eviter l'epuisement des threads."""
    MAX_TOTAL, MAX_PER_IP = 120, 25

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._lk, self._n, self._per = threading.Lock(), 0, {}

    def process_request(self, request, client_address):
        ip = client_address[0]
        with self._lk:
            refuse = self._n >= self.MAX_TOTAL or self._per.get(ip, 0) >= self.MAX_PER_IP
            if not refuse:
                self._n += 1
                self._per[ip] = self._per.get(ip, 0) + 1
        if refuse:
            self.shutdown_request(request)
            return
        super().process_request(request, client_address)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self._lk:
                self._n -= 1
                ip = client_address[0]
                self._per[ip] = self._per.get(ip, 1) - 1
                if self._per[ip] <= 0:
                    self._per.pop(ip, None)

    def handle_error(self, request, client_address):  # poignee TLS ratee, client coupe... : une ligne, pas de trace
        log_event(f"connexion interrompue depuis {client_address[0]} : {sys.exc_info()[1]!r}")


def switch_password(args):
    """Mot de passe SSH des switches : fichier, puis identifiant systemd (LoadCredential), puis variable SW_PASS."""
    if args.pass_file:
        return Path(args.pass_file).read_text(encoding="utf-8").strip()
    cd = os.environ.get("CREDENTIALS_DIRECTORY")
    if cd and (Path(cd) / "sw_pass").exists():
        return (Path(cd) / "sw_pass").read_text(encoding="utf-8").strip()
    if os.environ.get("SW_PASS"):
        return os.environ["SW_PASS"]
    sys.exit("Mot de passe des switches absent : --pass-file, identifiant systemd 'sw_pass' ou variable SW_PASS.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--host", default="127.0.0.1", help="adresse d'ecoute (0.0.0.0 pour ouvrir au reseau : necessite --cert/--key)")
    ap.add_argument("--cert", help="certificat TLS (HTTPS)")
    ap.add_argument("--key", help="cle privee TLS")
    ap.add_argument("--allow-http", action="store_true", help="autorise l'ecoute reseau sans HTTPS (deconseille)")
    ap.add_argument("--live", action="store_true", help="collecte reelle en SSH au lieu de la simulation")
    ap.add_argument("--pass-file", help="fichier contenant le mot de passe SSH des switches")
    ap.add_argument("--hosts", default=os.environ.get("SW_HOSTS", ""), help="IP ou plage a.b.c.X-Y, separees par des virgules")
    args = ap.parse_args()
    if args.host not in ("127.0.0.1", "localhost", "::1") and not (args.cert and args.key) and not args.allow_http:
        sys.exit("Refus : ecoute reseau sans HTTPS (mots de passe en clair). Utilisez --cert et --key, ou --allow-http a vos risques.")
    os.umask(0o077)  # fichiers crees (base, sauvegardes de config, cles) lisibles par le seul compte du service
    auth.DATA.mkdir(mode=0o700, exist_ok=True)
    DB = Db(auth.DATA / "switchmon.db")
    auth.get_users()
    if args.live:
        if not args.hosts:
            sys.exit("Mode reel : indiquez les switches avec --hosts (ex : 192.0.2.10,192.0.2.11-14) ou la variable SW_HOSTS.")
        from live import Live
        hosts = []
        for part in args.hosts.split(","):
            part = part.strip()
            if "-" in part:
                base, _, last = part.rpartition(".")
                lo, _, hi = last.partition("-")
                hosts += [f"{base}.{i}" for i in range(int(lo), int(hi) + 1)]
            elif part:
                hosts.append(part)
        SIM = Live(hosts, os.environ.get("SW_USER", "admin"), switch_password(args), DB)
        print(f"Mode REEL : {len(hosts)} switches ({hosts[0]} ... {hosts[-1]}), lecture seule")
    else:
        from demo import DemoLive
        SIM = DemoLive(DB)
        print("Mode DEMONSTRATION : reseau fictif, aucune connexion reseau.")
    srv = LimitedServer((args.host, args.port), Handler)
    scheme = "http"
    if args.cert and args.key:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(args.cert, args.key)
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True, do_handshake_on_connect=False)  # la poignee de main TLS se fait dans le thread du client
        SECURE, scheme = True, "https"
        COOKIE = "__Host-vig_session"  # le prefixe __Host- impose Secure + Path=/ et interdit le partage entre sous-domaines
    print(f"Vigilia sur {scheme}://{args.host}:{args.port}/  ({len(auth.get_users())} utilisateur(s), voir adduser.py)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
