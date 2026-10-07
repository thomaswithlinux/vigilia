"""Comptes utilisateurs (users.json, mots de passe hashes PBKDF2-SHA256) et roles : viewer < tech < admin.

Le dossier de donnees peut etre deplace avec la variable VIGILIA_DATA. Le fichier users.json est ecrit de facon
atomique avec les droits 600 ; il est relu automatiquement des qu'il change (adduser.py sans redemarrage).
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import struct
import threading
import time
from pathlib import Path

DATA = Path(os.environ.get("VIGILIA_DATA") or Path(__file__).parent / "data")
USERS_FILE = DATA / "users.json"
ROLES = {"viewer": 0, "tech": 1, "admin": 2}
ITER = 600_000        # recommandation OWASP 2023 pour PBKDF2-HMAC-SHA256
LEGACY_ITER = 200_000  # ancien format "sel$hash", accepte puis converti a la connexion
MIN_LEN = 12
COMMON = ("password", "motdepasse", "azerty", "qwerty", "123456", "abcdef", "vigilia", "switchmon", "letmein", "welcome", "admin123")
_lock = threading.Lock()
_cache = {"mtime": -1, "users": {}}  # -1 : jamais charge (None signifie "fichier absent")


def hash_pw(pw, salt=None, iters=ITER):
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), iters).hex()
    return f"pbkdf2_sha256${iters}${salt}${h}"


def _parts(stored):
    p = stored.split("$")
    if len(p) == 4 and p[0] == "pbkdf2_sha256":
        return int(p[1]), p[2], p[3]
    if len(p) == 2:  # ancien format
        return LEGACY_ITER, p[0], p[1]
    raise ValueError("format de hash inconnu")


def check_pw(pw, stored):
    iters, salt, h = _parts(stored)
    cand = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), iters).hex()
    return hmac.compare_digest(cand, h)


def needs_rehash(stored):
    return _parts(stored)[0] < ITER


DUMMY = hash_pw("x" * 16)


def policy_error(pw, user=""):
    """Renvoie un message si le mot de passe est refuse, sinon None."""
    if len(pw) < MIN_LEN:
        return f"{MIN_LEN} caracteres minimum"
    if sum(bool(re.search(rx, pw)) for rx in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]")) < 3:
        return "melangez au moins 3 types : minuscules, majuscules, chiffres, symboles"
    if user and user.lower() in pw.lower():
        return "le mot de passe ne doit pas contenir le nom d'utilisateur"
    if any(w in pw.lower() for w in COMMON):
        return "mot de passe trop courant (contient un mot ou une suite predictible)"
    return None


def random_password(n=20):
    alphabet = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789-_.!#%+="
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(n))
        if policy_error(pw) is None:
            return pw


def save_users(users):
    DATA.mkdir(mode=0o700, exist_ok=True)
    tmp = USERS_FILE.with_suffix(".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2)
    os.replace(tmp, USERS_FILE)
    try:
        os.chmod(USERS_FILE, 0o600)
    except OSError:
        pass


def load_users():
    """Charge users.json ; le cree au premier lancement avec un mot de passe aleatoire affiche une seule fois."""
    DATA.mkdir(mode=0o700, exist_ok=True)
    if not USERS_FILE.exists():
        user = os.environ.get("SWITCHMON_USER", "admin")
        pw = os.environ.get("SWITCHMON_PASS") or random_password()
        save_users({user: {"hash": hash_pw(pw), "role": "admin"}})
        if not os.environ.get("SWITCHMON_PASS"):
            print(f"\n*** PREMIER LANCEMENT : compte '{user}' cree avec le mot de passe aleatoire : {pw}\n*** Notez-le maintenant, il ne sera plus affiche.\n", flush=True)
    return json.loads(USERS_FILE.read_text(encoding="utf-8"))


def get_users():
    """Liste des comptes, relue si le fichier a change."""
    with _lock:
        try:
            m = USERS_FILE.stat().st_mtime_ns
        except OSError:
            m = None
        if m != _cache["mtime"]:
            _cache["users"] = load_users()
            _cache["mtime"] = USERS_FILE.stat().st_mtime_ns if USERS_FILE.exists() else None
        return _cache["users"]


def set_password(user, pw):
    with _lock:
        users = load_users()
        users[user]["hash"] = hash_pw(pw)
        save_users(users)
        _cache["mtime"] = None


def create_user(name, role, pw):
    """Cree un compte ; False si le nom existe deja (sans tenir compte des majuscules)."""
    with _lock:
        users = load_users()
        if any(n.lower() == name.lower() for n in users):
            return False
        users[name] = {"hash": hash_pw(pw), "role": role}
        save_users(users)
        _cache["mtime"] = -1
    return True


def verify(user, password, users=None):
    """Renvoie le role si les identifiants sont bons, sinon None. Meme duree que le compte existe ou non."""
    users = users if users is not None else get_users()
    u = users.get(user)
    ok = check_pw(password, u["hash"] if u else DUMMY)
    if u and ok:
        if needs_rehash(u["hash"]):
            set_password(user, password)
        return u["role"]
    return None


# ---------- double authentification (TOTP, RFC 6238) ----------
def totp_new():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _hotp(secret, counter):
    key = base64.b32decode(secret + "=" * ((8 - len(secret) % 8) % 8))
    h = hmac.new(key, struct.pack(">Q", counter), "sha1").digest()
    o = h[-1] & 15
    return str((struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 1_000_000).zfill(6)


def totp_verify(secret, code, last_step=0, window=1):
    """Renvoie le pas de temps valide (pour interdire la reutilisation d'un code), ou None."""
    if not (code.isdigit() and len(code) == 6):
        return None
    now = int(time.time() // 30)
    for step in range(now - window, now + window + 1):
        if step > last_step and hmac.compare_digest(_hotp(secret, step), code):
            return step
    return None


def get_totp(user):
    return get_users().get(user, {}).get("totp")


def set_totp(user, data):
    with _lock:
        users = load_users()
        if user not in users:
            return
        if data is None:
            users[user].pop("totp", None)
        else:
            users[user]["totp"] = data
        save_users(users)
        _cache["mtime"] = -1


# ---------- masquage des secrets dans les configurations affichees ----------
_SECRET = re.compile(r"(?i)\b(hash-key|password|passwd|secret|community|auth-key|priv-key|psk|pre-shared-key)(\s+)(\S+)")


def mask_secrets(text):
    return _SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)}********", text)
