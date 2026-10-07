"""Tests de securite et de fonctionnalites de Vigilia. Aucun reseau, aucun switch requis.

Usage :  python tests/test_vigilia.py        (code de sortie 0 = tout est vert)
Les tests demarrent un serveur local sur un port libre, avec des comptes et une base temporaires.
"""
import http.client
import io
import json
import os
import socket
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = tempfile.mkdtemp(prefix="vigilia_tests_")
ADMIN_PW = "Admin-Test-Pass-2026!"
os.environ["VIGILIA_DATA"] = TMP
os.environ["SWITCHMON_PASS"] = ADMIN_PW
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import auth  # noqa: E402
import live  # noqa: E402
import server  # noqa: E402
from db import Db  # noqa: E402

server.DB = Db(os.path.join(TMP, "switchmon.db"))
auth.get_users()
L = live.Live([], "admin", "x", server.DB)  # aucun switch : on teste l'API, l'historique et les exports
server.SIM = L
srv = server.LimitedServer(("127.0.0.1", 0), server.Handler)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
auth.create_user("technicien", "tech", "Tech-Test-Pass-2026!")
auth.create_user("lecteur", "viewer", "Viewer-Test-Pass-2026!")

RES = []


def check(name, ok, info=""):
    ok = bool(ok)
    RES.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f"  [{info}]" if info else ""), flush=True)


def group(title):
    print(f"\n== {title}", flush=True)
    server.RATE.clear()  # chaque groupe repart sans limitation de debit


def req(method, path, body=None, cookie=None, headers=None, raw=False):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=20)
    h = dict(headers or {})
    if cookie:
        h["Cookie"] = cookie
    data = json.dumps(body) if body is not None else None
    if data:
        h["Content-Type"] = "application/json"
    c.request(method, path, body=data, headers=h)
    r = c.getresponse()
    b = r.read()
    out = b if raw else (json.loads(b) if b[:1] in (b"{", b"[") else b)
    return r.status, {k.lower(): v for k, v in r.getheaders()}, out


def login(user, pw, code=None):
    body = {"user": user, "password": pw}
    if code:
        body["code"] = code
    s, h, j = req("POST", "/login", body)
    return s, h.get("set-cookie", "").split(";")[0], j


def main():
    now = time.time()
    for i in range(250):
        L._event(now - i, "warn" if i % 2 else "info", "SW-TEST", f"evenement {i}", kind="errors" if i % 2 else "device_new", port="1/1/5", detail={"mac": "aa:bb:cc:dd:ee:ff", "cause": "test"})
    L._event(now, "crit", "SW-TEST", "port coupe", kind="port_down", port="1/1/9", detail={"titre": "Port 1/1/9 down"})
    L._event(now, "warn", "=EVIL-SW", "formule dans le nom du switch", kind="errors", port="@1/1/1")

    # ------------------------------------------------------------------ authentification et en-tetes
    group("Authentification, en-tetes, acces aux fichiers")
    s, h, b = req("GET", "/api/state")
    check("API sans session -> 401", s == 401)
    s, h, b = req("GET", "/")
    check("en-tetes de securite presents", all(k in h for k in ("content-security-policy", "x-frame-options", "x-content-type-options", "referrer-policy", "permissions-policy", "cross-origin-opener-policy")))
    check("CSP stricte", all(x in h["content-security-policy"] for x in ("base-uri 'none'", "form-action 'self'", "object-src 'none'", "frame-ancestors 'none'")))
    check("pas de version dans l'en-tete Server", h.get("server", "").strip() == "Vigilia")
    for p in ("/fonts/../server.py", "/..%2fserver.py", "/web/app.js", "/../auth.py", "/data/users.json", "/%2e%2e/%2e%2e/etc/passwd"):
        s, h, b = req("GET", p)
        check(f"fichier interne inaccessible {p}", s in (401, 404) and b"def " not in b and b"pbkdf2" not in b)
    for m in ("PUT", "DELETE", "OPTIONS", "TRACE", "PATCH"):
        s, h, b = req(m, "/")
        check(f"methode {m} refusee", s == 501)
    s, ck, j = login("admin", "mauvais")
    check("mauvais mot de passe -> 401", s == 401)
    s, ck, j = login("inconnu", "x")
    check("compte inconnu -> 401 (meme reponse)", s == 401)
    s, adm, j = login("admin", ADMIN_PW)
    check("connexion admin", s == 200 and adm.startswith("vig_session="))
    s, h, b = req("POST", "/login", {"user": "admin", "password": ADMIN_PW})
    check("cookie HttpOnly + SameSite=Strict", "HttpOnly" in h["set-cookie"] and "SameSite=Strict" in h["set-cookie"])
    s, tech, _ = login("technicien", "Tech-Test-Pass-2026!")
    s, view, _ = login("lecteur", "Viewer-Test-Pass-2026!")
    s, h, b = req("GET", "/api/me", cookie=adm)
    check("/api/me", s == 200 and b["role"] == "admin")

    # ------------------------------------------------------------------ CSRF et entrees
    group("CSRF et entrees malformees")
    s, h, b = req("POST", "/api/note", {"key": "x", "text": "y"}, headers={"Origin": "http://evil.example"}, cookie=adm)
    check("origine etrangere refusee (403)", s == 403)
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    c.request("POST", "/api/note", body="key=x", headers={"Content-Type": "text/plain", "Cookie": adm})
    check("type de contenu non JSON refuse (415)", c.getresponse().status == 415)
    s, h, b = req("POST", "/api/note", {"key": "x", "text": "y"}, headers={"Sec-Fetch-Site": "cross-site"}, cookie=adm)
    check("Sec-Fetch-Site: cross-site refuse (403)", s == 403)
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    c.request("POST", "/login", body="{" * 100000, headers={"Content-Type": "application/json"})
    check("corps volumineux / JSON invalide sans effet", c.getresponse().status in (400, 401, 429))

    # ------------------------------------------------------------------ roles et creation de comptes
    group("Roles et creation de comptes")
    for path in ("/api/audit", "/api/configs?ip=x", "/api/config?id=1", "/api/diff?a=1&b=2"):
        s, h, b = req("GET", path, cookie=view)
        check(f"lecteur interdit sur {path}", s == 403)
    s, h, b = req("POST", "/api/note", {"key": "a", "text": "b"}, cookie=view)
    check("lecteur ne peut pas ecrire une note", s == 403)
    s, h, b = req("POST", "/api/backup", {"ip": "192.0.2.99"}, cookie=view)
    check("lecteur ne peut pas lancer une sauvegarde", s == 403)
    s, h, b = req("POST", "/api/users", {"user": "intrus", "role": "admin"}, cookie=tech)
    check("technicien ne peut PAS creer de compte (403)", s == 403)
    s, h, b = req("POST", "/api/users", {"user": "intrus", "role": "admin"}, cookie=view)
    check("lecteur ne peut PAS creer de compte (403)", s == 403)
    s, h, b = req("POST", "/api/users", {"user": "marie.dupont", "role": "tech"}, cookie=adm)
    check("creation avec mot de passe aleatoire", s == 200 and b["ok"] and len(b["password"]) >= 16)
    s, mk, _ = login("marie.dupont", b["password"])
    check("le nouveau compte se connecte immediatement", s == 200)
    s, h, b = req("POST", "/api/users", {"user": "paul", "role": "viewer", "password": "Court1!"}, cookie=adm)
    check("mot de passe saisi trop faible refuse (400)", s == 400)
    s, h, b = req("POST", "/api/users", {"user": "PAUL.D", "role": "viewer", "password": "Un-Bon-Mdp-2026x"}, cookie=adm)
    check("creation avec mot de passe saisi valide", s == 200 and b["password"] is None)
    s, h, b = req("POST", "/api/users", {"user": "paul.d", "role": "viewer"}, cookie=adm)
    check("doublon insensible a la casse refuse (409)", s == 409)
    for bad in ("a b", "../etc", "x"):
        s, h, b = req("POST", "/api/users", {"user": bad, "role": "viewer"}, cookie=adm)
        check(f"nom invalide refuse ({bad!r})", s == 400)
    s, h, b = req("POST", "/api/users", {"user": "zoe", "role": "superuser"}, cookie=adm)
    check("role inconnu refuse (400)", s == 400)
    s, h, b = req("GET", "/api/audit", cookie=adm)
    acts = [r["action"] for r in b["audit"]]
    check("creations de compte enregistrees dans l'audit", acts.count("user_create") == 2)
    check("users.json sans mot de passe en clair", "Un-Bon-Mdp-2026x" not in open(os.path.join(TMP, "users.json"), encoding="utf-8").read())
    codes = [req("POST", "/api/users", {"user": f"zz{i}", "role": "viewer"}, cookie=adm)[0] for i in range(12)]
    check("limitation du nombre de creations (429)", 429 in codes)

    # ------------------------------------------------------------------ mot de passe
    group("Changement de mot de passe et sessions")
    s, h, b = req("POST", "/api/password", {"old": "Tech-Test-Pass-2026!", "new": "court"}, cookie=tech)
    check("mot de passe trop court refuse", s == 400)
    s, h, b = req("POST", "/api/password", {"old": "Tech-Test-Pass-2026!", "new": "Password-Test-2026!"}, cookie=tech)
    check("mot courant refuse par la politique", s == 400)
    s, h, b = req("POST", "/api/password", {"old": "faux", "new": "Nouveau-Mdp-2026!xYz"}, cookie=tech)
    check("ancien mot de passe faux refuse", s == 403)
    s, h, b = req("POST", "/api/password", {"old": "Tech-Test-Pass-2026!", "new": "Nouveau-Mdp-2026!xYz"}, cookie=tech)
    ck2 = h.get("set-cookie", "").split(";")[0]
    check("changement OK + nouvelle session", s == 200 and ck2 and ck2 != tech)
    check("ancienne session revoquee", req("GET", "/api/me", cookie=tech)[0] == 401)
    check("ancien mot de passe refuse", login("technicien", "Tech-Test-Pass-2026!")[0] == 401)
    s, tech, _ = login("technicien", "Nouveau-Mdp-2026!xYz")
    check("nouveau mot de passe valide", s == 200)
    auth.create_user("ephemere", "viewer", "Eph-Test-Pass-2026!x")
    s, eph, _ = login("ephemere", "Eph-Test-Pass-2026!x")
    users = auth.load_users()
    del users["ephemere"]
    auth.save_users(users)
    check("compte supprime -> session invalide", req("GET", "/api/me", cookie=eph)[0] == 401)

    # ------------------------------------------------------------------ journal detaille
    group("Journal detaille")
    s, h, j = req("GET", "/api/events?limit=200", cookie=view)
    check("200 evenements par page + suite disponible", s == 200 and len(j["events"]) == 200 and j["more"])
    s, h, j2 = req("GET", f"/api/events?limit=200&before={j['events'][-1]['id']}", cookie=view)
    check("pagination", len(j2["events"]) >= 50 and j2["events"][0]["id"] < j["events"][-1]["id"])
    s, h, j = req("GET", "/api/events?sev=crit", cookie=view)
    check("filtre par niveau", len(j["events"]) == 1 and j["events"][0]["sev"] == "crit")
    s, h, j = req("GET", "/api/events?kind=device_new&limit=500", cookie=view)
    check("filtre par type", len(j["events"]) == 125)
    s, h, j = req("GET", "/api/events?q=evenement%2017&limit=50", cookie=view)
    check("recherche texte", 1 <= len(j["events"]) <= 12)
    s, h, j = req("GET", "/api/events?q=%27%20OR%201%3D1%20--", cookie=view)
    check("injection SQL sans effet", s == 200 and len(j["events"]) == 0)
    s, h, j = req("GET", "/api/events?q=%25", cookie=view)
    check("le caractere % est cherche litteralement", s == 200 and len(j["events"]) == 0)
    s, h, j = req("GET", "/api/events?limit=99999&days=abc&before=xyz", cookie=view)
    check("parametres invalides toleres, plafond 500", s == 200 and len(j["events"]) <= 500)
    eid = req("GET", "/api/events?sev=crit", cookie=view)[2]["events"][0]["id"]
    s, h, d = req("GET", f"/api/event?id={eid}", cookie=view)
    check("detail d'un evenement", s == 200 and d["event"]["id"] == eid and isinstance(d["related"], list))
    check("evenement inconnu -> 404", req("GET", "/api/event?id=99999999", cookie=view)[0] == 404)
    check("journal sans session -> 401", req("GET", "/api/events")[0] == 401)

    # ------------------------------------------------------------------ export zip
    group("Export des journaux (.zip)")
    check("interdit a un lecteur (403)", req("GET", "/api/logs.zip?days=30", cookie=view, raw=True)[0] == 403)
    s, h, b = req("GET", "/api/logs.zip?days=30", cookie=tech, raw=True)
    z = zipfile.ZipFile(io.BytesIO(b))
    check("technicien : 4 fichiers, sans audit", s == 200 and set(z.namelist()) == {"LISEZMOI.txt", "evenements.csv", "alertes.csv", "coupures_ports.csv"})
    check("en-tete de telechargement", "attachment" in h.get("content-disposition", "") and h["content-type"] == "application/zip")
    ev = z.read("evenements.csv").decode("utf-8-sig")
    check("formules Excel neutralisees ('=' et '@')", ";'=EVIL-SW;" in ev and ";'@1/1/1;" in ev and "\n=" not in ev)
    s, h, b = req("GET", "/api/logs.zip?days=30", cookie=adm, raw=True)
    check("administrateur : audit.csv inclus", "audit.csv" in zipfile.ZipFile(io.BytesIO(b)).namelist())
    codes = [req("GET", "/api/logs.zip?days=7", cookie=tech, raw=True)[0] for _ in range(8)]
    check("limite de 6 exports par heure (429)", 429 in codes)

    # ------------------------------------------------------------------ fuites d'information
    group("Fuites d'information")
    check("ssh_user masque pour un lecteur", "ssh_user" not in req("GET", "/api/state", cookie=view)[2])
    check("ssh_user visible pour un technicien", req("GET", "/api/state", cookie=tech)[2].get("ssh_user") == "admin")
    s, adm2, _ = login("admin", ADMIN_PW)
    me = req("GET", "/api/me", cookie=adm2)[2]
    check("derniere connexion renvoyee", me.get("last_login") and "ip" in me["last_login"])
    mk = auth.mask_secrets('snmp community-map hash-key 0a1b2c3d4e5f user "x" enable\nsnmp station 192.0.2.1 162\nuser admin password $2a$abc\nlinkagg actor admin-key 1')
    check("secrets de configuration masques, reste intact", "0a1b2c3d4e5f" not in mk and "$2a$abc" not in mk and "snmp station 192.0.2.1" in mk and "admin-key 1" in mk)

    # ------------------------------------------------------------------ double authentification
    group("Double authentification (TOTP)")
    s, h, j = req("POST", "/api/totp/start", {}, cookie=tech)
    sec = j["secret"]
    check("demarrage : cle + URI otpauth", s == 200 and len(sec) >= 32 and j["uri"].startswith("otpauth://totp/Vigilia:"))
    check("en attente : connexion sans code", login("technicien", "Nouveau-Mdp-2026!xYz")[2].get("need_totp") is None)
    check("activation avec un faux code refusee", req("POST", "/api/totp/enable", {"code": "000000"}, cookie=tech)[0] == 400)
    step = int(time.time() // 30)
    s, h, j = req("POST", "/api/totp/enable", {"code": auth._hotp(sec, step)}, cookie=tech)
    check("activation avec le bon code", s == 200 and j.get("ok"))
    s, ck, j = login("technicien", "Nouveau-Mdp-2026!xYz")
    check("mot de passe seul : code demande, pas de session", j.get("need_totp") and not ck)
    check("faux code refuse", login("technicien", "Nouveau-Mdp-2026!xYz", "123456")[0] == 401)
    check("code deja utilise refuse (rejeu)", login("technicien", "Nouveau-Mdp-2026!xYz", auth._hotp(sec, step))[0] == 401)
    s, ck, j = login("technicien", "Nouveau-Mdp-2026!xYz", auth._hotp(sec, step + 1))
    check("nouveau code valide : connexion", s == 200 and ck.startswith("vig_session="))
    check("desactivation sans bon mot de passe refusee", req("POST", "/api/totp/disable", {"password": "mauvais", "code": auth._hotp(sec, step + 1)}, cookie=ck)[0] == 403)
    check("secret jamais renvoye par /api/me", "secret" not in json.dumps(req("GET", "/api/me", cookie=ck)[2]))
    check("politique : mot courant refuse", auth.policy_error("Password-Test-2026!") is not None)
    check("politique : mot de passe solide accepte", auth.policy_error("Xk7#mQ2-vLp9@Rt4") is None)

    # ------------------------------------------------------------------ mode demonstration
    group("Mode demonstration (reseau fictif)")
    from demo import DemoLive
    d = DemoLive(Db(os.path.join(TMP, "demo.db")))
    snap = d.snapshot()
    check("5 switches fictifs, adresses de documentation", len(snap["switches"]) == 5 and all(s["ip"].startswith("192.0.2.") for s in snap["switches"]))
    check("alertes de demonstration presentes", len(snap["alerts"]) >= 4 and any(a["sev"] == "crit" for a in snap["alerts"]))
    check("voisins LLDP entre switches", sum(1 for s in snap["switches"] for p in s["ports"] if p["nb"] and p["nb"].get("owner")) >= 6)
    check("rapport et historique disponibles", d.report(7)["total"] > 10 and any(len(v) > 100 for v in d.history("7d")["series"].values()))
    check("export zip du mode demo", len(d.logs_zip(30, True, "test")[0]) > 1000)
    check("detail de port synthetique", d.port_detail("192.0.2.11", "1/1/17")["oper"] == "up")

    # ------------------------------------------------------------------ force brute, saturation, connexions lentes
    group("Force brute, plafond de connexions, connexions lentes")
    codes = [login("admin", f"x{i}")[0] for i in range(8)]
    check("blocage apres 5 echecs (429)", 429 in codes)
    check("meme avec le bon mot de passe, l'adresse reste bloquee", login("admin", ADMIN_PW)[0] == 429)
    server.RATE.clear()
    socks = []
    for _ in range(40):
        c = socket.socket()
        c.settimeout(0.3)
        c.connect(("127.0.0.1", PORT))
        socks.append(c)
    time.sleep(0.5)
    closed = 0
    for c in socks:
        try:
            if c.recv(1) == b"":
                closed += 1
        except socket.timeout:
            pass
    check("plafond de 25 connexions par adresse : excedent refuse", closed >= 10, f"{closed} refusees sur 40")
    for c in socks:
        c.close()
    time.sleep(0.5)
    check("service disponible apres la saturation", req("GET", "/api/me", cookie=adm2)[0] == 200)
    if os.environ.get("SKIP_SLOW") != "1":
        c = socket.socket()
        c.connect(("127.0.0.1", PORT))
        c.send(b"GET / HTTP/1.1\r\nHost: x\r\n")
        t0, c_t = time.time(), None
        c.settimeout(30)
        try:
            c.recv(100)
            c_t = time.time() - t0
        except socket.timeout:
            pass
        check("connexion lente coupee par le serveur (delai 20 s)", c_t is not None and 15 < c_t < 28, f"{c_t:.0f} s" if c_t else "non coupee")


try:
    main()
finally:
    print(f"\n{sum(RES)}/{len(RES)} tests reussis", flush=True)
    srv.shutdown()
    os._exit(0 if RES and all(RES) else 1)
