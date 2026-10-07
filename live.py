"""Collecte reelle en SSH (commandes d'affichage uniquement, lecture seule) sur des switches Alcatel-Lucent OmniSwitch AOS8.

Commandes utilisees : show health/temperature/interfaces/mac-learning/lldp/lanpower/system/chassis/vlan et
`write terminal` (affichage de la configuration, ne modifie rien). Aucune commande de configuration n'est envoyee.
snapshot() renvoie le JSON consomme par le front-end.
"""
import csv
import difflib
import hashlib
import io
import json
import os
import re
import threading
import time
import zipfile
from collections import deque
from datetime import datetime
from pathlib import Path

import paramiko

import auth
from hints import HINTS

CYCLE = 20           # secondes entre deux releves complets
SLOW_EVERY = 6       # system / chassis / LLDP : un cycle sur 6
HISTORY = 180        # points gardes en memoire pour les courbes live
METRIC_EVERY = 60    # une mesure enregistree par minute et par switch
BACKUP_EVERY = 86400 # sauvegarde automatique de configuration : une fois par jour
BACKUPS = auth.DATA / "backups"
KNOWN = auth.DATA / "known_hosts"   # empreintes SSH des switches (epinglees a la premiere connexion)
_KEYLOCK = threading.Lock()
PROMPT = re.compile(r"\S+ => ?$")

P_STATUS = re.compile(r"^\s*(\d+/\d+/\d+)\s+(en|dis)\s+(en|dis)\s+(\S+)\s+(\S+)", re.M)
P_ALIAS = re.compile(r'^\s*(\d+/\d+/\d+)\s+(enable|disable)\s+(up|down)\s+\d+\s+\d+\s+"(.*)"', re.M)
P_BLOCK = re.compile(r"^(\d+/\d+/\d+)\s*,", re.M)
P_MAC = re.compile(r"^\s*VLAN\s+(\d+)\s+([0-9a-fA-F:]{17})\S*\s+(\S+)\s+\S+\s+(\d+/\d+/\d+)\s*$", re.M)
P_POE = re.compile(r"^\s*(\d+/\d+/\d+)\s+(\d+)\s+(\d+)\s+(.*?)\s{2,}", re.M)
P_LLDP = re.compile(r"Local Port (\d+/\d+/\d+):(.*?)(?=Remote LLDP nearest-bridge Agents|\Z)", re.S)
P_CHASSIS = re.compile(r"(Local|Remote) Chassis ID (\d+) \((\w+)\)(.*?)(?=(?:Local|Remote) Chassis ID|\Z)", re.S)


def fmt_speed(mbps):
    return f"{mbps / 1000:g}G" if mbps >= 1000 else f"{mbps}M"


def grab(rx, txt, default=""):
    m = re.search(rx, txt, re.M)
    return m.group(1).strip().rstrip(",").strip() if m else default


class PinPolicy(paramiko.MissingHostKeyPolicy):
    """Premiere connexion : on memorise la cle du switch. Ensuite, toute cle differente est refusee (BadHostKeyException)."""

    def missing_host_key(self, client, hostname, key):
        with _KEYLOCK:
            hk = paramiko.HostKeys()
            if KNOWN.exists():
                hk.load(str(KNOWN))
            hk.add(hostname, key.get_name(), key)
            hk.save(str(KNOWN))
        client.get_host_keys().add(hostname, key.get_name(), key)


class Shell:
    """Session SSH persistante vers un switch."""

    def __init__(self, host, user, password):
        self.host, self.user, self.password = host, user, password
        self.c = self.sh = None
        self.io = threading.Lock()

    def open(self):
        self.close()
        c = paramiko.SSHClient()
        if KNOWN.exists():
            c.load_host_keys(str(KNOWN))
        c.set_missing_host_key_policy(PinPolicy())
        c.connect(self.host, username=self.user, password=self.password, timeout=8, banner_timeout=8,
                  auth_timeout=8, look_for_keys=False, allow_agent=False)
        self.c = c
        self.sh = c.invoke_shell(width=250, height=2000)
        self._read(5)

    def close(self):
        try:
            if self.c:
                self.c.close()
        finally:
            self.c = self.sh = None

    def _read(self, timeout):
        buf = ""
        end = time.time() + timeout
        while time.time() < end:
            if self.sh.recv_ready():
                buf += self.sh.recv(65535).decode(errors="replace")
                if PROMPT.search(buf.rstrip()):
                    time.sleep(0.05)
                    if not self.sh.recv_ready():
                        break
            else:
                time.sleep(0.05)
        return buf

    def run(self, cmd, timeout=25):
        with self.io:
            if not self.sh or self.sh.closed:
                raise ConnectionError("session fermee")
            self.sh.send(cmd + "\n")
            return self._read(timeout).replace("\r", "")


class Live:
    def __init__(self, hosts, user, password, db):
        self.lock = threading.Lock()
        self.db = db
        self.events = deque(maxlen=200)
        self.active = {}
        self.alert_id = 0
        self.sw = {}
        self.creds = (user, password)
        self.shells = {}
        self.detail_cache = {}
        self.notes = {}
        self.mac_db = {}
        self.started = time.time()
        for h in hosts:
            self.sw[h] = {
                "ip": h, "name": h, "desc": "", "loc": "", "model": "", "firmware": "", "chassis": [], "ports": {}, "order": [],
                "cpu": 0.0, "mem": 0.0, "temp": 0.0, "uptime": 0, "hist": deque(maxlen=HISTORY), "reach": None, "seen": False,
                "last_ok": 0, "err": "", "lldp_full": {}, "prev_err": {}, "prev_t": 0, "cycle": 0, "mac_ready": False,
                "last_metric": 0, "last_backup": 0,
            }
        self._load_state()
        for h in hosts:
            threading.Thread(target=self._worker, args=(h,), daemon=True).start()

    def _load_state(self):
        db = self.db
        db.execute("UPDATE alert_hist SET closed=? WHERE closed IS NULL", (self.started,))
        for r in reversed(db.query("SELECT * FROM events ORDER BY id DESC LIMIT 200")):
            self.events.appendleft(self._event_row(r))
        for r in db.query("SELECT * FROM notes"):
            self.notes[r["key"]] = {"text": r["text"], "updated": r["updated"], "by": r["by"]}
        for r in db.query("SELECT * FROM macs"):
            self.mac_db[r["mac"]] = {"ip": r["ip"], "port": r["port"], "vlan": r["vlan"], "first": r["first_seen"], "last": r["last_seen"],
                                     "moves": r["moves"], "saved": r["last_seen"]}
        for r in db.query("SELECT * FROM inventory"):
            st = self.sw.get(r["ip"])
            if st:
                inv = json.loads(r["json"])
                st.update(name=inv.get("name", st["name"]), model=inv.get("model", ""), firmware=inv.get("firmware", ""),
                          chassis=inv.get("chassis", []), loc=inv.get("loc", ""))
        for ip, st in self.sw.items():
            r = db.one("SELECT t FROM configs WHERE ip=? ORDER BY id DESC LIMIT 1", (ip,))
            st["last_backup"] = r["t"] if r else 0

    @staticmethod
    def _event_row(r):
        try:
            detail = json.loads(r.get("detail") or "{}")
        except ValueError:
            detail = {}
        return {"id": r["id"], "t": r["t"], "sev": r["sev"], "sw": r.get("sw") or "", "ip": r.get("ip") or "", "port": r.get("port") or "",
                "kind": r.get("kind") or "", "text": r["text"], "detail": detail}

    def _event(self, now, sev, sw, text, kind="", port="", detail=None):
        full = f"{sw} - {text}" if sw else text
        ip = self._ip_of(sw) if sw else ""
        eid = self.db.execute("INSERT INTO events(t,sev,sw,text,kind,port,ip,detail) VALUES(?,?,?,?,?,?,?,?)",
                              (now, sev, sw, full, kind, port, ip, json.dumps(detail, ensure_ascii=False) if detail else ""))
        self.events.appendleft({"id": eid, "t": now, "sev": sev, "sw": sw, "ip": ip, "port": port, "kind": kind, "text": full, "detail": detail or {}})
        return eid

    # ------------------------------------------------------------ collecte
    def _worker(self, host):
        sh = self.shells[host] = Shell(host, *self.creds)
        st = self.sw[host]
        while True:
            t0 = time.time()
            try:
                if sh.sh is None or sh.sh.closed:
                    sh.open()
                self._collect(sh, st)
                with self.lock:
                    st["reach"], st["seen"], st["last_ok"], st["err"], st["hostkey_bad"] = True, True, time.time(), "", False
                    self._evaluate(time.time())
                if st["cycle"] >= 2 and time.time() - st["last_backup"] > BACKUP_EVERY:
                    self.backup_config(host, "automatique")
            except Exception as e:  # noqa: BLE001 - toute erreur reseau => switch injoignable
                sh.close()
                with self.lock:
                    st["reach"], st["err"] = False, f"{type(e).__name__}: {e}"[:160]
                    st["hostkey_bad"] = isinstance(e, paramiko.BadHostKeyException)
                    self._evaluate(time.time())
            time.sleep(max(2, CYCLE - (time.time() - t0)))

    def _collect(self, sh, st):
        now = time.time()
        slow = st["cycle"] % SLOW_EVERY == 0
        mid = st["cycle"] % 3 == 1  # MAC et PoE : un cycle sur 3 (les ports sont deja connus)
        st["cycle"] += 1
        out = {}
        cmds = ["show health", "show temperature", "show interfaces status", "show interfaces alias",
                "show interfaces counters", "show interfaces counters errors"]
        if slow:
            cmds += ["show system", "show chassis", "show lldp remote-system"]
        if mid:
            cmds.append("show mac-learning")
            slots = sorted({p.rsplit("/", 1)[0] for p in st["order"]})
            cmds += [f"show lanpower slot {s}" for s in slots]
        for c in cmds:
            out[c] = sh.run(c, timeout=40 if c == "show mac-learning" else 25)
        with self.lock:
            m = re.search(r"CPU\s+(\d+)", out["show health"])
            st["cpu"] = float(m.group(1)) if m else st["cpu"]
            m = re.search(r"Memory\s+(\d+)", out["show health"])
            st["mem"] = float(m.group(1)) if m else st["mem"]
            temps = [int(x) for x in re.findall(r"^\s*\d+/\w+\s+(\d+)\s+-?\d+ to \d+", out["show temperature"], re.M)]
            if temps:
                st["temp"] = float(max(temps))
            if slow:
                self._parse_system(st, out["show system"], out["show chassis"])
            self._parse_ports(st, out, now)
            if slow:
                self._parse_lldp(st, out["show lldp remote-system"], now)
            if mid:
                self._parse_mac_poe(st, out)
                self._track_macs(st, now)
            tin = sum(p["in"] for p in st["ports"].values() if p["link"])
            tout = sum(p["out"] for p in st["ports"].values() if p["link"])
            st["hist"].append([now, tin, tout, st["cpu"], st["temp"]])
            if now - st["last_metric"] >= METRIC_EVERY:
                st["last_metric"] = now
                self.db.execute("INSERT INTO metrics VALUES(?,?,?,?,?,?,?)", (now, st["ip"], st["cpu"], st["mem"], st["temp"], tin, tout))

    def _parse_system(self, st, system, chassis):
        st["name"] = grab(r"Name:\s+(.*?),?\s*$", system) or st["ip"]
        st["loc"] = grab(r"Location:\s+(.*?),?\s*$", system)
        desc = grab(r"Description:\s+(.*?),?\s*$", system)
        d = re.search(r"Alcatel-Lucent Enterprise (\S+) (\S+)", desc)
        st["model"] = d.group(1) if d else desc[:30]
        st["firmware"] = d.group(2) if d else ""
        m = re.search(r"(\d+) days (\d+) hours (\d+) minutes", system)
        if m:
            st["uptime"] = int(m.group(1)) * 86400 + int(m.group(2)) * 3600 + int(m.group(3)) * 60
        ch = []
        for kind, cid, role, body in P_CHASSIS.findall(chassis):
            ch.append({"id": int(cid), "role": role, "model": grab(r"Model Name:\s*(.+)", body), "serial": grab(r"Serial Number:\s*(.+)", body),
                       "part": grab(r"Part Number:\s*(.+)", body), "hw": grab(r"Hardware Revision:\s*(.+)", body),
                       "mfg": grab(r"Manufacture Date:\s*(.+)", body), "status": grab(r"Operational Status:\s*(.+)", body),
                       "mac": grab(r"MAC Address:\s*(.+)", body).lower()})
        if ch:
            st["chassis"] = ch
            self.db.execute("INSERT OR REPLACE INTO inventory VALUES(?,?,?)", (st["ip"], json.dumps(
                {"name": st["name"], "model": st["model"], "firmware": st["firmware"], "chassis": ch, "loc": st["loc"]}), time.time()))

    @staticmethod
    def _parse_lldp(st, txt, now):
        seen = set()
        for port, body in P_LLDP.findall(txt):
            nm = grab(r"System Name\s*=\s*(.+)", body)
            ch = re.search(r"Chassis ([0-9A-Fa-f:]{17})", body)
            st["lldp_full"][port] = {"name": "" if nm == "(null)" else nm, "chassis": ch.group(1).lower() if ch else "",
                                     "caps": grab(r"Capabilities Enabled\s*=\s*(.+)", body), "rport": grab(r"Port Description\s*=\s*(.+)", body)}
            seen.add(port)
        for port in list(st["lldp_full"]):  # un voisin disparu d'un port encore actif est oublie ; sur un port tombe on garde le dernier connu
            if port not in seen and st["ports"].get(port, {}).get("link"):
                del st["lldp_full"][port]

    def _parse_mac_poe(self, st, out):
        txt = out.get("show mac-learning", "")
        if "Legend" in txt:
            macs = {}
            for m in P_MAC.finditer(txt):
                macs.setdefault(m.group(4), []).append((m.group(2).lower(), int(m.group(1))))
            for port, p in st["ports"].items():
                p["macs"] = macs.get(port, [])
        total = 0.0
        for cmd, txt in out.items():
            if not cmd.startswith("show lanpower"):
                continue
            for m in P_POE.finditer(txt):
                p = st["ports"].get(m.group(1))
                if p is not None:
                    p["poe_w"] = int(m.group(3)) / 1000
                    p["poe_max_w"] = int(m.group(2)) / 1000
                    p["poe_status"] = m.group(4).strip()
                    total += p["poe_w"]
        st["poe_total"] = total

    def _track_macs(self, st, now):
        """Memorise les appareils vus ; signale un nouvel appareil ou un deplacement (ports d'extremite seulement)."""
        ready, st["mac_ready"], n_evt = st["mac_ready"], True, 0
        for port, p in st["ports"].items():
            macs = p.get("macs") or []
            if not p["link"] or not macs or len(macs) > 3:
                continue
            caps = st["lldp_full"].get(port, {}).get("caps", "")
            if "Bridge" in caps or "Router" in caps:  # borne Wi-Fi / switch / routeur : les clients bougent, pas d'alerte
                continue
            for mac, vlan in macs:
                r = self.mac_db.get(mac)
                if r is None:
                    r = self.mac_db[mac] = {"ip": st["ip"], "port": port, "vlan": vlan, "first": now, "last": now, "moves": 0, "saved": now}
                    self.db.execute("INSERT OR REPLACE INTO macs VALUES(?,?,?,?,?,?,?)", (mac, vlan, st["ip"], port, now, now, 0))
                    if ready and n_evt < 5:
                        n_evt += 1
                        self._event(now, "info", st["name"], f"Nouvel appareil {mac} sur {port} (VLAN {vlan})", kind="device_new", port=port,
                                    detail={"mac": mac, "vlan": vlan, "port": port, "premiere_vue": now})
                elif (r["ip"], r["port"]) != (st["ip"], port):
                    old = f"{self._swname(r['ip'])} {r['port']}"
                    r.update(ip=st["ip"], port=port, vlan=vlan, last=now, saved=now)
                    r["moves"] += 1
                    self.db.execute("UPDATE macs SET vlan=?,ip=?,port=?,last_seen=?,moves=? WHERE mac=?", (vlan, st["ip"], port, now, r["moves"], mac))
                    if ready and n_evt < 5:
                        n_evt += 1
                        self._event(now, "info", st["name"], f"Appareil {mac} deplace : {old} -> {port}", kind="device_move", port=port,
                                    detail={"mac": mac, "vlan": vlan, "de": old, "vers": f"{st['name']} {port}", "deplacements": r["moves"]})
                else:
                    r["last"] = now
                    if now - r["saved"] > 600:
                        r["saved"] = now
                        self.db.execute("UPDATE macs SET last_seen=? WHERE mac=?", (now, mac))

    def _swname(self, ip):
        st = self.sw.get(ip)
        return st["name"] if st else ip

    def _parse_ports(self, st, out, now):
        stat = {m.group(1): m for m in P_STATUS.finditer(out["show interfaces status"])}
        alias = {m.group(1): m for m in P_ALIAS.finditer(out["show interfaces alias"])}
        rate = {}
        txt = out["show interfaces counters"]
        idx = [(m.start(), m.group(1)) for m in P_BLOCK.finditer(txt)] + [(len(txt), None)]
        for (a, port), (b, _) in zip(idx, idx[1:]):
            blk = txt[a:b]
            i = re.search(r"InBits/s\s*=\s*(\d+)", blk)
            o = re.search(r"OutBits/s\s*=\s*(\d+)", blk)
            rate[port] = (int(i.group(1)) if i else 0, int(o.group(1)) if o else 0)
        errs = {}
        txt = out["show interfaces counters errors"]
        idx = [(m.start(), m.group(1)) for m in P_BLOCK.finditer(txt)] + [(len(txt), None)]
        for (a, port), (b, _) in zip(idx, idx[1:]):
            m = re.search(r"IfInErrors\s*=\s*(\d+)", txt[a:b])
            if m:
                errs[port] = int(m.group(1))
        dt = max(1.0, now - st["prev_t"]) if st["prev_t"] else None
        order = sorted(alias, key=lambda p: tuple(int(x) for x in p.split("/")))
        st["order"] = order
        for port in order:
            a = alias[port]
            s = stat.get(port)
            p = st["ports"].setdefault(port, {"ever_up": False, "flaps": 0, "flap_times": deque(maxlen=20), "link": False,
                                              "crc": 0, "err": 0.0})
            link = a.group(3) == "up"
            if st["prev_t"] and p["link"] != link:  # vraie transition (pas le premier releve)
                self.db.execute("INSERT INTO port_events VALUES(?,?,?,?)", (now, st["ip"], port, "up" if link else "down"))
            if p["link"] and not link:
                p["flaps"] += 1
                p["flap_times"].append(now)
            p["link"] = link
            p["ever_up"] = p["ever_up"] or link
            p["admin"] = a.group(2) == "enable"
            p["alias"] = a.group(4)
            spd = s.group(4) if s else "-"
            p["speed"] = int(spd) if spd.isdigit() else 0
            p["duplex"] = (s.group(5).lower() if s and s.group(5) in ("Full", "Half") else "full")
            p["in"], p["out"] = rate.get(port, (0, 0)) if link else (0, 0)
            if port in errs:
                prev = st["prev_err"].get(port)
                p["err"] = max(0.0, (errs[port] - prev) / dt) if (prev is not None and dt) else 0.0
                st["prev_err"][port] = errs[port]
                p["crc"] = errs[port]
            else:
                p["err"] = 0.0
        st["prev_t"] = now

    # ------------------------------------------------------------- alertes
    def _evaluate(self, now):
        found = {}

        def add(key, sev, kind, sw, port, title, detail):
            found[key] = (sev, kind, sw, port, title, detail)

        for st in self.sw.values():
            n = st["name"]
            if st["reach"] is False:
                if st.get("hostkey_bad"):
                    add(f"{st['ip']}:hostkey", "crit", "hostkey", n, None, "Cle SSH du switch modifiee",
                        f"{st['ip']} - connexion refusee par prudence (remplacement ou usurpation)")
                elif st["seen"]:
                    add(f"{st['ip']}:unreach", "crit", "unreach", n, None, "Switch injoignable",
                        f"{st['ip']} - derniere reponse il y a {int(now - st['last_ok'])} s")
                else:
                    add(f"{st['ip']}:unreach", "warn", "unreach", n, None, "Switch jamais joint",
                        f"{st['ip']} - {st['err']}")
                continue
            if st["reach"] is None:
                continue
            if st["cpu"] >= 90:
                add(f"{n}:cpu", "crit", "cpu", n, None, "CPU critique", f"{st['cpu']:.0f} % de charge")
            elif st["cpu"] >= 75:
                add(f"{n}:cpu", "warn", "cpu", n, None, "CPU eleve", f"{st['cpu']:.0f} % de charge")
            if st["temp"] >= 75:
                add(f"{n}:temp", "crit", "temp", n, None, "Temperature critique", f"{st['temp']:.0f} °C")
            elif st["temp"] >= 62:
                add(f"{n}:temp", "warn", "temp", n, None, "Temperature elevee", f"{st['temp']:.0f} °C")
            for i, port in enumerate(st["order"], 1):
                p = st["ports"][port]
                pk = f"{n}:{port}"
                lab = self._label(st, port, p) or "equipement non identifie"
                cap = (p["speed"] or 1000) * 1e6
                util = max(p["in"], p["out"]) / cap
                if p["admin"] and not p["link"] and p["ever_up"]:
                    add(pk + ":down", "crit" if p["flaps"] and self._is_uplink(p) else "warn", "port_down", n, i,
                        f"Port {port} down", lab)
                    continue
                if not p["link"]:
                    continue
                if p["err"] >= 40:
                    add(pk + ":err", "crit", "errors", n, i, f"Erreurs sur {port}", f"{p['err']:.0f} erreurs/s - {lab}")
                elif p["err"] >= 5:
                    add(pk + ":err", "warn", "errors", n, i, f"Erreurs sur {port}", f"{p['err']:.0f} erreurs/s - {lab}")
                if util >= 0.95:
                    add(pk + ":util", "crit", "util", n, i, f"Saturation {port}", f"{util * 100:.0f} % de {fmt_speed(p['speed'] or 1000)} - {lab}")
                elif util >= 0.85:
                    add(pk + ":util", "warn", "util", n, i, f"Charge elevee {port}", f"{util * 100:.0f} % de {fmt_speed(p['speed'] or 1000)} - {lab}")
                if p["duplex"] == "half":
                    add(pk + ":duplex", "warn", "duplex", n, i, f"Half-duplex sur {port}", lab)
                if p["speed"] == 10:
                    add(pk + ":speed", "warn", "speed", n, i, f"Lien en 10 Mb/s sur {port}", lab)
            for i, port in enumerate(st["order"], 1):
                p = st["ports"][port]
                if len([x for x in p["flap_times"] if now - x <= 600]) >= 3:
                    add(f"{n}:{port}:flap", "warn", "flap", n, i, f"Port instable {port}", f"{p['flaps']} coupures - {self._label(st, port, p)}")

        for key, (sev, kind, sw, port, title, detail) in found.items():
            a = self.active.get(key)
            if a is None:
                self.alert_id += 1
                cause, steps = HINTS[kind]
                pname = self._portname(sw, port) if port else ""
                hid = self.db.execute("INSERT INTO alert_hist(key,sw,ip,title,sev,kind,port,opened) VALUES(?,?,?,?,?,?,?,?)",
                                      (key, sw, self._ip_of(sw), title, sev, kind, pname, now))
                self.active[key] = {"id": self.alert_id, "hid": hid, "key": key, "sev": sev, "kind": kind, "switch": sw, "port": port,
                                    "title": title, "detail": detail, "since": now, "cause": cause,
                                    "steps": [s.format(port=pname) for s in steps]}
                self._event(now, sev, sw, f"{title} ({detail})", kind=kind, port=pname,
                            detail={"alerte_id": hid, "titre": title, "detail": detail, "gravite": sev, "cause": cause,
                                    "verifications": [x.format(port=pname) for x in steps]})
            else:
                if a["sev"] != sev:
                    self._event(now, sev, sw, f"{title} passe en {'critique' if sev == 'crit' else 'alerte'}", kind=a["kind"],
                                port=self._portname(sw, a["port"]) if a["port"] else "",
                                detail={"alerte_id": a["hid"], "avant": a["sev"], "apres": sev, "detail": detail})
                    self.db.execute("UPDATE alert_hist SET sev=? WHERE id=?", (sev, a["hid"]))
                a.update(sev=sev, title=title, detail=detail)
        for key in [k for k in self.active if k not in found]:
            a = self.active.pop(key)
            self.db.execute("UPDATE alert_hist SET closed=? WHERE id=?", (now, a["hid"]))
            self._event(now, "ok", a["switch"], f"resolu : {a['title']}", kind=a["kind"],
                        port=self._portname(a["switch"], a["port"]) if a["port"] else "",
                        detail={"alerte_id": a["hid"], "titre": a["title"], "gravite": a["sev"], "ouverte": a["since"], "duree_s": round(now - a["since"]), "cause": a["cause"]})

    def _ip_of(self, name):
        for st in self.sw.values():
            if st["name"] == name:
                return st["ip"]
        return ""

    @staticmethod
    def _is_uplink(p):
        return p["speed"] >= 10000 or bool(re.search(r"uplink|core|trunk|lag", p["alias"], re.I))

    def _chassis_owner(self, mac):
        if mac:
            for st in self.sw.values():
                if any(c["mac"] == mac for c in st["chassis"]):
                    return st["name"]
        return ""

    def _label(self, st, port, p):
        alias = "" if p["alias"].lower() == "libre" else p["alias"]
        lf = st["lldp_full"].get(port, {})
        nb = lf.get("name") or self._chassis_owner(lf.get("chassis", ""))
        return " - ".join(x for x in (alias, nb) if x)

    def _portname(self, swname, n):
        for st in self.sw.values():
            if st["name"] == swname and 1 <= n <= len(st["order"]):
                return st["order"][n - 1]
        return ""

    # ------------------------------------------------- detail d'un port (a la demande)
    def port_detail(self, ip, port):
        st = self.sw.get(ip)
        sh = self.shells.get(ip)
        if st is None or port not in st["ports"]:  # liste blanche : jamais de texte libre envoye au switch
            return {"error": "port inconnu"}
        key = (ip, port)
        hit = self.detail_cache.get(key)
        if hit and time.time() - hit[0] < 8:
            return hit[1]
        if sh is None or st["reach"] is not True:
            return {"error": "switch injoignable"}
        try:
            info = sh.run(f"show interfaces {port}")
            vl = sh.run(f"show vlan members port {port}")
            ld = sh.run(f"show lldp port {port} remote-system")
        except Exception as e:  # noqa: BLE001
            return {"error": f"{type(e).__name__}: {e}"[:160]}
        d = self._parse_detail(info, vl, ld)
        self.detail_cache[key] = (time.time(), d)
        return d

    @staticmethod
    def _parse_detail(info, vl, ld):
        def one(rx, txt, cast=str):
            m = re.search(rx, txt)
            return cast(m.group(1).strip().rstrip(",")) if m else None

        i_rx, _, i_tx = info.partition(" Tx ")
        d = {
            "oper": one(r"Operational Status\s*:\s*(.+)", info),
            "reason": one(r"Port-Down/Violation Reason\s*:\s*(.+)", info),
            "last_change": one(r"Last Time Link Changed\s*:\s*(.+)", info),
            "changes": one(r"Number of Status Change\s*:\s*(\d+)", info, int),
            "type": one(r"Interface Type\s*:\s*(.+)", info),
            "sfp": one(r"SFP/XFP\s*:\s*(.+)", info),
            "port_mac": one(r"MAC address\s*:\s*(\S+)", info),
            "bandwidth": one(r"BandWidth \(Megabits\)\s*:\s*(\d+)", info, int),
            "duplex": one(r"Duplex\s*:\s*(\w+)", info),
            "autoneg": one(r"Autonegotiation\s*:\s*(.+)", info),
            "frame": one(r"Long Frame Size\(Bytes\)\s*:\s*(\d+)", info, int),
            "rx": {k: one(rx, i_rx, int) for k, rx in (
                ("bytes", r"Bytes Received\s*:\s*(\d+)"), ("unicast", r"Unicast Frames\s*:\s*(\d+)"),
                ("broadcast", r"Broadcast Frames:\s*(\d+)"), ("multicast", r"M-cast Frames\s*:\s*(\d+)"),
                ("undersize", r"UnderSize Frames:\s*(\d+)"), ("oversize", r"OverSize Frames:\s*(\d+)"),
                ("lost", r"Lost Frames\s*:\s*(\d+)"), ("errors", r"Error Frames\s*:\s*(\d+)"),
                ("crc", r"CRC Error Frames:\s*(\d+)"), ("align", r"Alignments Err\s*:\s*(\d+)"))},
            "tx": {k: one(rx, i_tx, int) for k, rx in (
                ("bytes", r"Bytes Xmitted\s*:\s*(\d+)"), ("unicast", r"Unicast Frames\s*:\s*(\d+)"),
                ("broadcast", r"Broadcast Frames:\s*(\d+)"), ("multicast", r"M-cast Frames\s*:\s*(\d+)"),
                ("lost", r"Lost Frames\s*:\s*(\d+)"), ("errors", r"Error Frames\s*:\s*(\d+)"),
                ("collisions", r"Collisions\s*:\s*(\d+)"), ("late", r"Late collisions\s*:\s*(\d+)"))},
            "vlans": [{"vlan": int(a), "type": b, "state": c} for a, b, c in re.findall(r"^\s*(\d+)\s+(tagged|untagged)\s+(\S+)", vl, re.M)],
        }
        if "Remote LLDP" in ld:
            d["lldp"] = {
                "chassis": one(r"Chassis ([0-9a-fA-F:]+),", ld),
                "port": one(r"Port Description\s*=\s*(.+)", ld),
                "name": one(r"System Name\s*=\s*(.+)", ld),
                "ip": one(r"Management IP Address\s*=\s*(.+)", ld),
                "descr": (one(r"System Description\s*=\s*(.+)", ld) or "")[:120],
                "caps": one(r"Capabilities Enabled\s*=\s*(.+)", ld),
            }
        return d

    # ------------------------------------------------------ sauvegarde des configurations
    @staticmethod
    def _clean_config(raw):
        lines = raw.split("\n")[1:]  # 1re ligne = echo de la commande
        while lines and (not lines[-1].strip() or PROMPT.search(lines[-1].strip())):
            lines.pop()
        out, blank = [], False
        for ln in lines:
            ln = ln.rstrip()
            if not ln:
                if blank:
                    continue
                blank = True
            else:
                blank = False
            out.append(ln)
        return "\n".join(out).strip() + "\n"

    def backup_config(self, ip, who="automatique"):
        st, sh = self.sw.get(ip), self.shells.get(ip)
        if st is None or sh is None or st["reach"] is not True:
            return {"error": "switch injoignable"}
        try:
            raw = sh.run("write terminal", timeout=90)  # affichage de la configuration courante : ne modifie rien
        except Exception as e:  # noqa: BLE001
            return {"error": f"{type(e).__name__}: {e}"[:160]}
        text = self._clean_config(raw)
        if len(text) < 200 or "ERROR" in text[:300]:
            return {"error": "sortie inattendue du switch"}
        now = time.time()
        if who != "automatique" and now - st.get("last_manual", 0) < 30:
            return {"error": "trop frequent, reessayez dans 30 secondes"}
        if who != "automatique":
            st["last_manual"] = now
        st["last_backup"] = now
        sha = hashlib.sha256(text.encode()).hexdigest()
        last = self.db.one("SELECT id, sha FROM configs WHERE ip=? ORDER BY id DESC LIMIT 1", (ip,))
        if last and last["sha"] == sha:
            return {"changed": False, "id": last["id"]}
        folder = BACKUPS / re.sub(r"[^A-Za-z0-9_.-]", "_", st["name"])
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = folder / (datetime.fromtimestamp(now).strftime("%Y%m%d-%H%M%S") + ".cfg")
        path.write_text(text, encoding="utf-8")
        os.chmod(path, 0o600)
        cid = self.db.execute("INSERT INTO configs(ip,name,t,sha,path,size) VALUES(?,?,?,?,?,?)", (ip, st["name"], now, sha, str(path), len(text)))
        if last:
            with self.lock:
                self._event(now, "info", st["name"], f"Configuration modifiee (sauvegarde {who}) - voir Configurations", kind="config",
                            detail={"sauvegarde": who, "config_id": cid, "precedente_id": last["id"], "taille_octets": len(text)})
        return {"changed": True, "id": cid, "first": last is None}

    def configs(self, ip):
        return self.db.query("SELECT id, t, size, sha FROM configs WHERE ip=? ORDER BY id DESC LIMIT 60", (ip,))

    def config_text(self, cid):
        r = self.db.one("SELECT path, name, t FROM configs WHERE id=?", (cid,))
        if not r:
            return None
        p = Path(r["path"].replace("\\", "/"))  # chemin enregistre sous Windows ou Linux : on ne garde que dossier/fichier
        return {"name": r["name"], "t": r["t"], "text": (BACKUPS / p.parent.name / p.name).read_text(encoding="utf-8")}

    def config_diff(self, a, b):
        ra, rb = self.config_text(a), self.config_text(b)
        if not ra or not rb:
            return None
        return {"diff": "".join(difflib.unified_diff(ra["text"].splitlines(True), rb["text"].splitlines(True), "avant", "apres", n=2))}

    # ----------------------------------------------------------------- notes
    def set_note(self, key, text, user):
        ip = key.split("|")[0]
        if ip not in self.sw or (("|" in key) and key.split("|", 1)[1] not in self.sw[ip]["ports"]):
            return False
        text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text).strip()[:500]
        if text:
            self.notes[key] = {"text": text, "updated": time.time(), "by": user}
            self.db.execute("INSERT OR REPLACE INTO notes VALUES(?,?,?,?)", (key, text, time.time(), user))
        else:
            self.notes.pop(key, None)
            self.db.execute("DELETE FROM notes WHERE key=?", (key,))
        return True

    # ------------------------------------------------------- historique et rapport
    def history(self, rng):
        secs, bucket = {"1h": (3600, 60), "24h": (86400, 300), "7d": (7 * 86400, 1800), "30d": (30 * 86400, 7200)}.get(rng, (3600, 60))
        since = time.time() - secs
        rows = self.db.query(
            "SELECT ip, CAST(t/? AS INTEGER)*? AS b, AVG(cpu) cpu, AVG(mem) mem, AVG(temp) temp, AVG(tin) tin, AVG(tout) tout "
            "FROM metrics WHERE t>=? GROUP BY ip, b ORDER BY b", (bucket, bucket, since))
        out = {ip: [] for ip in self.sw}
        for r in rows:
            out.setdefault(r["ip"], []).append([r["b"], r["tin"], r["tout"], round(r["cpu"], 1), round(r["temp"], 1)])
        return {"range": rng, "series": out, "names": {ip: st["name"] for ip, st in self.sw.items()}}

    def report(self, days):
        now = time.time()
        days = max(1, min(int(days), 90))
        since = now - days * 86400
        first = self.db.one("SELECT MIN(t) t FROM metrics")
        observed = now - max(since, (first or {}).get("t") or now)
        rows = self.db.query("SELECT sw, ip, sev, kind, opened, COALESCE(closed, ?) closed FROM alert_hist WHERE COALESCE(closed, ?) >= ?", (now, now, since))
        per = {}
        for r in rows:
            d = per.setdefault(r["sw"], {"name": r["sw"], "ip": r["ip"], "crit": 0, "warn": 0, "dur": 0.0, "down": 0.0})
            d[r["sev"]] += 1
            dur = max(0.0, r["closed"] - max(r["opened"], since))
            d["dur"] += dur
            if r["kind"] == "unreach" and r["sev"] == "crit":
                d["down"] += dur
        for st in self.sw.values():
            per.setdefault(st["name"], {"name": st["name"], "ip": st["ip"], "crit": 0, "warn": 0, "dur": 0.0, "down": 0.0})
        for d in per.values():
            n = d["crit"] + d["warn"]
            d["mttr"] = d["dur"] / n if n else 0
            d["avail"] = max(0.0, 1 - d["down"] / observed) * 100 if observed > 0 else 100.0
        kinds = self.db.query("SELECT kind, COUNT(*) n FROM alert_hist WHERE opened>=? GROUP BY kind ORDER BY n DESC", (since,))
        names = {ip: st["name"] for ip, st in self.sw.items()}
        unstable = [{"sw": names.get(r["ip"], r["ip"]), "ip": r["ip"], "port": r["port"], "n": r["n"]} for r in self.db.query(
            "SELECT ip, port, COUNT(*) n FROM port_events WHERE kind='down' AND t>=? GROUP BY ip, port ORDER BY n DESC LIMIT 10", (since,))]
        tot = sum(d["crit"] + d["warn"] for d in per.values())
        return {"days": days, "observed": observed, "total": tot, "crit": sum(d["crit"] for d in per.values()),
                "mttr": (sum(d["dur"] for d in per.values()) / tot) if tot else 0, "switches": sorted(per.values(), key=lambda d: -(d["crit"] * 10 + d["warn"])),
                "kinds": kinds, "unstable": unstable}

    # ------------------------------------------------------- journal detaille et export
    def events_query(self, limit=200, before=0, sev="", sw="", kind="", q="", days=0):
        sql, args = "SELECT id,t,sev,sw,ip,port,kind,text FROM events WHERE 1=1", []
        if before > 0:
            sql += " AND id < ?"
            args.append(before)
        if sev in ("crit", "warn", "ok", "info"):
            sql += " AND sev = ?"
            args.append(sev)
        if sw:
            sql += " AND sw = ?"
            args.append(sw)
        if kind:
            sql += " AND kind = ?"
            args.append(kind)
        if q:
            sql += " AND text LIKE ? ESCAPE '\\'"
            args.append("%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
        if days > 0:
            sql += " AND t >= ?"
            args.append(time.time() - min(days, 3650) * 86400)
        limit = max(1, min(int(limit), 500))
        rows = self.db.query(sql + " ORDER BY id DESC LIMIT ?", (*args, limit))
        total = self.db.one("SELECT COUNT(*) n FROM events")["n"]
        kinds = [r["kind"] for r in self.db.query("SELECT DISTINCT kind FROM events WHERE kind IS NOT NULL AND kind <> '' ORDER BY kind")]
        return {"events": rows, "more": len(rows) == limit, "total": total, "kinds": kinds, "switches": sorted(st["name"] for st in self.sw.values())}

    def event_detail(self, eid):
        r = self.db.one("SELECT * FROM events WHERE id=?", (eid,))
        if not r:
            return None
        ev = self._event_row(r)
        alert = None
        if ev["detail"].get("alerte_id"):
            alert = self.db.one("SELECT id,sw,ip,title,sev,kind,port,opened,closed FROM alert_hist WHERE id=?", (ev["detail"]["alerte_id"],))
        if ev["sw"] and ev["port"]:
            rel = self.db.query("SELECT id,t,sev,kind,text FROM events WHERE sw=? AND port=? AND id<>? ORDER BY id DESC LIMIT 12", (ev["sw"], ev["port"], eid))
        elif ev["sw"] and ev["kind"]:
            rel = self.db.query("SELECT id,t,sev,kind,text FROM events WHERE sw=? AND kind=? AND id<>? ORDER BY id DESC LIMIT 12", (ev["sw"], ev["kind"], eid))
        else:
            rel = []
        around = self.db.query("SELECT id,t,sev,kind,text FROM events WHERE id<>? AND t BETWEEN ? AND ? ORDER BY t LIMIT 15", (eid, ev["t"] - 300, ev["t"] + 300))
        return {"event": ev, "alert": alert, "related": rel, "around": around}

    KIND_LABEL = {"port_down": "Port down", "errors": "Erreurs sur un port", "util": "Saturation de lien", "flap": "Port instable", "duplex": "Half-duplex",
                  "temp": "Temperature", "cpu": "CPU", "speed": "Lien en 10 Mb/s", "unreach": "Switch injoignable", "hostkey": "Cle SSH modifiee",
                  "device_new": "Nouvel appareil", "device_move": "Appareil deplace", "config": "Configuration modifiee"}

    @staticmethod
    def _csv(header, rows):
        def safe(v):  # neutralise l'injection de formules (=, +, -, @) a l'ouverture dans Excel
            s = "" if v is None else str(v)
            return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
        w.writerow(header)
        for r in rows:
            w.writerow([safe(c) for c in r])
        return ("\ufeff" + buf.getvalue()).encode("utf-8")

    def logs_zip(self, days, include_audit, who):
        since = time.time() - days * 86400
        fd = lambda t: datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S") if t else ""  # noqa: E731
        ev = self.db.query("SELECT id,t,sev,sw,ip,port,kind,text,detail FROM events WHERE t>=? ORDER BY id", (since,))
        al = self.db.query("SELECT id,sw,ip,port,kind,sev,title,opened,closed FROM alert_hist WHERE COALESCE(closed, ?) >= ? ORDER BY id", (time.time(), since))
        pe = self.db.query("SELECT t,ip,port,kind FROM port_events WHERE t>=? ORDER BY t", (since,))
        files = {
            "evenements.csv": self._csv(["id", "date", "niveau", "switch", "ip", "port", "type", "message", "detail_json"],
                                        [(r["id"], fd(r["t"]), r["sev"], r["sw"], r["ip"], r["port"], self.KIND_LABEL.get(r["kind"], r["kind"] or ""), r["text"], r["detail"]) for r in ev]),
            "alertes.csv": self._csv(["id", "switch", "ip", "port", "type", "gravite", "titre", "ouverte", "fermee", "duree_s"],
                                     [(r["id"], r["sw"], r["ip"], r["port"], self.KIND_LABEL.get(r["kind"], r["kind"] or ""), r["sev"], r["title"], fd(r["opened"]), fd(r["closed"]),
                                       round((r["closed"] or time.time()) - r["opened"])) for r in al]),
            "coupures_ports.csv": self._csv(["date", "ip", "port", "evenement"], [(fd(r["t"]), r["ip"], r["port"], r["kind"]) for r in pe]),
        }
        n_audit = 0
        if include_audit:
            au = self.db.query("SELECT t,user,action,detail,ip FROM audit WHERE t>=? ORDER BY id", (since,))
            n_audit = len(au)
            files["audit.csv"] = self._csv(["date", "utilisateur", "action", "detail", "adresse_ip"], [(fd(r["t"]), r["user"], r["action"], r["detail"], r["ip"]) for r in au])
        readme = (f"Vigilia - export des journaux\r\nGenere le {fd(time.time())} par {who}\r\nPeriode : {days} derniers jours (depuis {fd(since)})\r\n\r\n"
                  f"evenements.csv     : {len(ev)} lignes (alertes, resolutions, appareils, configurations)\r\n"
                  f"alertes.csv        : {len(al)} alertes avec dates d'ouverture et de fermeture\r\n"
                  f"coupures_ports.csv : {len(pe)} changements d'etat de ports\r\n"
                  + (f"audit.csv          : {n_audit} lignes (connexions, actions) - reserve aux administrateurs\r\n" if include_audit else "audit.csv          : non inclus (reserve aux administrateurs)\r\n")
                  + "\r\nFormat : CSV separe par des points-virgules, encodage UTF-8 (Excel : Donnees > Depuis un fichier texte).\r\n"
                  "Document sensible : il decrit votre infrastructure reseau. Ne pas diffuser.\r\n")
        mem = io.BytesIO()
        with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            z.writestr("LISEZMOI.txt", readme.encode("utf-8"))
            for name, data in files.items():
                z.writestr(name, data)
        return mem.getvalue(), "vigilia-logs-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".zip"

    # ------------------------------------------------------------ snapshot
    def snapshot(self):
        with self.lock:
            sws = []
            for st in sorted(self.sw.values(), key=lambda s: tuple(int(x) for x in s["ip"].split("."))):
                ports = []
                for i, port in enumerate(st["order"], 1):
                    p = st["ports"][port]
                    spd = p["speed"] or 1000
                    cap = spd * 1e6
                    if p["link"]:
                        status = "up"
                    elif p["admin"] and p["ever_up"]:
                        status = "down"
                    else:
                        status = "off"
                    macs = p.get("macs", []) if p["link"] else []
                    vlans = {v for _, v in macs}
                    lf = st["lldp_full"].get(port)
                    note = self.notes.get(f"{st['ip']}|{port}")
                    ports.append({
                        "n": i, "name": port, "role": "uplink" if self._is_uplink(p) and p["link"] else "user",
                        "macs": [{"mac": m, "vlan": v, "first": self.mac_db.get(m, {}).get("first"), "moves": self.mac_db.get(m, {}).get("moves", 0)} for m, v in macs][:50],
                        "mac_count": len(macs), "mac": macs[0][0] if macs else "", "poe_status": p.get("poe_status", ""), "poe_max": p.get("poe_max_w", 0),
                        "desc": self._label(st, port, p), "vlan": next(iter(vlans)) if len(vlans) == 1 else 0, "status": status,
                        "speed": fmt_speed(p["speed"]) if p["link"] else "-", "duplex": p["duplex"], "in": p["in"], "out": p["out"],
                        "cap": cap, "util": round(min(1.0, max(p["in"], p["out"]) / cap), 3) if p["link"] else 0.0,
                        "err": round(p["err"], 1), "crc": p["crc"], "drops": 0, "flaps": p["flaps"], "poe": round(p.get("poe_w", 0), 1) if p["link"] else 0,
                        "note": note["text"] if note else "",
                        "nb": {"name": lf["name"], "chassis": lf["chassis"], "owner": self._chassis_owner(lf["chassis"]), "rport": lf["rport"], "caps": lf["caps"]} if lf else None,
                    })
                hist = list(st["hist"]) or [[time.time(), 0, 0, 0, 0]] * 2
                note = self.notes.get(st["ip"])
                sws.append({
                    "name": st["name"], "desc": st["loc"] or st["ip"], "ip": st["ip"], "loc": st["loc"], "model": st["model"] or "inconnu",
                    "firmware": st["firmware"], "chassis": st["chassis"], "note": note["text"] if note else "",
                    "cpu": st["cpu"], "mem": st["mem"], "temp": st["temp"], "fans": [], "poe": round(st.get("poe_total", 0), 1), "poe_max": 0,
                    "uptime": st["uptime"], "ports": ports, "hist": hist, "reach": st["reach"], "last_backup": st["last_backup"],
                })
            alerts = sorted(self.active.values(), key=lambda a: (a["sev"] != "crit", -a["since"]))
            return {"mode": "live", "ssh_user": self.creds[0], "now": time.time(), "tick": CYCLE, "switches": sws, "alerts": alerts, "events": list(self.events)[:200]}
