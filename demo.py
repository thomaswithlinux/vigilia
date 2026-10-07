"""Mode demonstration : un reseau FICTIF complet (aucune connexion reseau, aucune donnee reelle).

Reproduit tout ce que fait le mode reel : switches, ports, appareils (MAC, LLDP, PoE), alertes, journal, historique,
configurations et rapports. Les adresses IP appartiennent a la plage reservee a la documentation (192.0.2.0/24, RFC 5737).
Lancer :  python server.py     (sans --live)
"""
import hashlib
import json
import math
import random
import threading
import time
import zlib
from collections import deque
from datetime import datetime
from pathlib import Path

import live
from hints import HINTS
from live import Live

CHASSIS_MAC = "02:00:5e:00:10:{:02x}"
OUI_POOL = {  # prefixes reels courants (voir la table du front-end) + prefixes generiques
    "pc": ["b4:45:06", "3c:52:82", "f8:b4:6a", "a4:4c:c8", "00:e0:4c"], "srv": ["00:50:56", "00:0c:29", "24:5e:be", "00:15:5d"],
    "phone": ["00:80:9f", "00:1b:0d"], "ap": ["6c:d6:e3"], "fw": ["70:4c:a5", "38:c0:ea"], "other": ["00:1e:c9", "5c:60:ba"],
}


def fake_config(name, loc, ip, version, vlans, stations):
    lines = [f"! Chassis:", f'system name "{name}"', f'system location "{loc}"', "", "! VLAN:"]
    lines += [f'vlan {v} admin-state enable name "{n}"' for v, n in vlans]
    lines += ["", "! IP:", f"ip interface \"mgmt\" address {ip} mask 255.255.255.0 vlan 1", "", "! SNMP:",
              "snmp community-map mode enable", 'snmp community-map hash-key 0123456789abcdef user "demo" enable']
    lines += [f"snmp station {s} 162 v2 enable" for s in stations]
    lines += ["", "! AAA:", 'aaa authentication default "local"', 'aaa authentication ssh "local"',
              'user "admin" password $2a$10$FAKEFAKEFAKEFAKEFAKEFAKEFAKE read-write all', "",
              "! Spanning tree:", "spantree mode flat", "spantree vlan 1 admin-state enable", "", f"! Version de la configuration : {version}"]
    return "\n".join(lines) + "\n"


class DemoLive(Live):
    def __init__(self, db):
        # pas de threads SSH : on prepare les memes structures que Live avec des donnees fictives
        self.lock = threading.Lock()
        self.db = db
        self.events = deque(maxlen=200)
        self.active, self.alert_id, self.sw = {}, 0, {}
        self.creds = ("demo", "")
        self.shells, self.detail_cache, self.notes, self.mac_db = {}, {}, {}, {}
        self.started = time.time()
        self.r = random.Random(2026)
        self._load_state()
        fresh = db.one("SELECT COUNT(*) n FROM metrics")["n"] == 0
        self._build()
        if fresh:
            self._history()
        with self.lock:
            self._evaluate(time.time())
        threading.Thread(target=self._run, daemon=True).start()

    # ------------------------------------------------------------------ reseau fictif
    def _mac(self, kind, private=False):
        r = self.r
        if private:
            return ":".join(f"{x:02x}" for x in [r.choice([0x46, 0x7a, 0xca, 0xd2]), *[r.randrange(256) for _ in range(5)]])
        return ":".join([r.choice(OUI_POOL[kind])] + [f"{r.randrange(256):02x}" for _ in range(3)])

    def _port(self, name, **kw):
        base = {"ever_up": False, "flaps": 0, "flap_times": deque(maxlen=20), "link": False, "crc": 0, "err": 0.0, "admin": True, "alias": "Libre", "speed": 0,
                "duplex": "full", "in": 0.0, "out": 0.0, "macs": [], "base": 0.0, "phase": self.r.uniform(0, 6.28), "scn_err": 0.0}
        base.update(kw)
        return base

    def _add_switch(self, ip, name, model, loc, fw, n_ports, n_chassis=1, uplink_speed=10000):
        st = {"ip": ip, "name": name, "desc": "", "loc": loc, "model": model, "firmware": fw, "ports": {}, "order": [], "cpu": 14.0, "mem": self.r.uniform(34, 62),
              "temp": 41.0, "uptime": self.r.randrange(20, 140) * 86400, "hist": deque(maxlen=live.HISTORY), "reach": True, "seen": True, "last_ok": time.time(), "err": "",
              "lldp_full": {}, "prev_err": {}, "prev_t": 0, "cycle": 0, "mac_ready": True, "last_metric": 0, "last_backup": 0, "poe_total": 0.0, "hostkey_bad": False,
              "chassis": [{"id": c + 1, "role": "Master" if c == 0 else "Slave", "model": model, "serial": f"DEMO{zlib.crc32((name + str(c)).encode()) % 10**7:07d}", "part": "904000-90",
                           "hw": "03", "mfg": "Mar 12 2024", "status": "UP", "mac": CHASSIS_MAC.format(len(self.sw) * 4 + c + 1)} for c in range(n_chassis)]}
        for c in range(1, n_chassis + 1):
            for n in range(1, n_ports + 1):
                st["order"].append(f"{c}/1/{n}")
        self.sw[ip] = st
        return st

    def _pc(self, st, port, vlan=20):
        r = self.r
        dept = r.choice(["COMPTA", "RH", "DEV", "COM", "DIR", "SUPPORT", "ACHATS"])
        macs = [(self._mac("pc"), vlan)]
        st["ports"][port] = self._port(port, link=True, ever_up=True, alias=f"PC-{dept}-{r.randrange(1, 40):02d}", speed=r.choice([1000, 1000, 1000, 100]),
                                       macs=macs, base=r.uniform(0.002, 0.03))

    def _build(self):
        r = self.r
        core = self._add_switch("192.0.2.10", "SW-CORE", "OS6860E-24", "Salle serveurs - Baie A1", "8.10.86.R04", 28, 2)
        acc = [self._add_switch(f"192.0.2.{11 + i}", f"SW-ETAGE-{i + 1}", "OS6560-P48X4", loc, "8.10.86.R04" if i != 2 else "8.10.85.R02", 52)
               for i, loc in enumerate(["Local technique RDC", "Local technique R+1", "Local technique R+2"])]
        park = self._add_switch("192.0.2.15", "SW-PARKING", "OS6560-P24X4", "Parking - coffret", "8.10.86.R04", 28)
        # --- cœur : serveurs, pare-feu, liens vers les switches d'etage
        servers = [("ESXI-01", 10000, 0.02), ("ESXI-02", 10000, 0.015), ("NAS-BACKUP", 1000, 0.12), ("SRV-AD-01", 1000, 0.01), ("SRV-FICHIERS", 1000, 0.07), ("SRV-VEEAM", 1000, 0.08)]
        for k, (nm, spd, base) in enumerate(servers, 1):
            kind = "srv"
            core["ports"][f"1/1/{k}"] = self._port(f"1/1/{k}", link=True, ever_up=True, alias=nm, speed=spd, base=base, macs=[(self._mac(kind), 10)])
            if nm.startswith("ESXI"):
                core["ports"][f"1/1/{k}"]["macs"] += [(self._mac("srv"), 10) for _ in range(r.randrange(4, 9))]
                core["lldp_full"][f"1/1/{k}"] = {"name": nm.lower() + ".lab.example", "chassis": self._mac("srv"), "caps": "Station", "rport": "vmnic0"}
        core["ports"]["1/1/10"] = self._port("1/1/10", link=True, ever_up=True, alias="FW-EDGE-01", speed=1000, base=0.12, macs=[(self._mac("fw"), 5)])
        core["lldp_full"]["1/1/10"] = {"name": "FW-EDGE-01.example", "chassis": self._mac("fw"), "caps": "Router", "rport": "port3"}
        for i, a in enumerate(acc, 1):  # core 1/1/(24+i) et 2/1/(24+i) <-> uplinks 1/1/49 et 1/1/50 de l'etage
            spd = 1000 if i == 3 else 10000
            for c, up in ((1, "1/1/49"), (2, "1/1/50")):
                cp = f"{c}/1/{24 + i}"
                base = 0.88 if (i == 3 and c == 1) else r.uniform(0.012, 0.045)
                core["ports"][cp] = self._port(cp, link=True, ever_up=True, alias=f"TRUNK-{a['name']}", speed=spd, base=base)
                core["lldp_full"][cp] = {"name": a["name"], "chassis": a["chassis"][0]["mac"], "caps": "Bridge, Router", "rport": up}
                a["ports"][up] = self._port(up, link=True, ever_up=True, alias=f"UPLINK-CORE-{c}", speed=spd, base=base * 0.9)
                a["lldp_full"][up] = {"name": "SW-CORE", "chassis": core["chassis"][c - 1]["mac"], "caps": "Bridge, Router", "rport": cp}
        # --- switches d'etage : postes, telephones, bornes Wi-Fi, imprimantes, cameras
        for ai, a in enumerate(acc, 1):
            free_target = r.randrange(14, 22)
            for n in range(1, 45):
                port = f"1/1/{n}"
                x = r.random()
                if n <= 44 and len([p for p in a["ports"].values() if not p["link"]]) < free_target and x < 0.28:
                    a["ports"][port] = self._port(port, alias="Libre")
                elif x < 0.40:  # telephone IP avec poste derriere (PoE)
                    self._pc(a, port)
                    p = a["ports"][port]
                    p["macs"].append((self._mac("phone"), 30))
                    p["poe_w"], p["poe_max_w"], p["poe_status"] = r.uniform(3, 6.5), 30.0, "Powered On"
                    p["alias"] = "TEL+" + p["alias"]
                    a["lldp_full"][port] = {"name": "", "chassis": p["macs"][1][0], "caps": "Telephone", "rport": ""}
                elif x < 0.46:  # imprimante
                    a["ports"][port] = self._port(port, link=True, ever_up=True, alias=f"IMP-ETAGE{ai}-{r.randrange(1, 4)}", speed=100, base=0.002, macs=[(self._mac("other"), 20)])
                else:
                    self._pc(a, port)
            for k in range(45, 49):  # bornes Wi-Fi (PoE, nombreux clients)
                port = f"1/1/{k}"
                nm = f"AP-WIFI-{ai}{k - 44}"
                a["ports"][port] = self._port(port, link=True, ever_up=True, alias=nm, speed=1000, base=r.uniform(0.01, 0.06),
                                              macs=[(self._mac("ap"), 6)] + [(self._mac("x", private=True), 6) for _ in range(r.randrange(3, 24))],
                                              poe_w=r.uniform(7, 14), poe_max_w=30.0, poe_status="Powered On")
                a["lldp_full"][port] = {"name": nm, "chassis": a["ports"][port]["macs"][0][0], "caps": "Bridge, WLAN", "rport": "Gi0"}
            for n in (51, 52):
                a["ports"][f"1/1/{n}"] = self._port(f"1/1/{n}", alias="Libre")
        # --- cas d'ecole : alertes et pannes
        e1, e2, e3 = acc
        self._pc(e1, "1/1/17")
        e1["ports"]["1/1/17"]["scn_err"] = 14.0
        self._pc(e2, "1/1/9")
        e2["ports"]["1/1/9"]["speed"] = 10
        e2["ports"]["1/1/9"]["alias"] = "PC-ACHATS-07"
        p = self._port("1/1/30", alias="IMP-RDC-LABEL", ever_up=True, flaps=2)
        e1["ports"]["1/1/30"] = p
        p["flap_times"].extend([time.time() - 900, time.time() - 400])
        e3["ports"]["1/1/51"] = self._port("1/1/51", alias="UPLINK-PARKING", ever_up=True, flaps=3, speed=1000)
        e3["ports"]["1/1/51"]["flap_times"].extend([time.time() - 3000, time.time() - 2000, time.time() - 1500])
        e3["lldp_full"]["1/1/51"] = {"name": "SW-PARKING", "chassis": park["chassis"][0]["mac"], "caps": "Bridge", "rport": "1/1/25"}
        for n in range(1, 25):  # parking : cameras (PoE)
            port = f"1/1/{n}"
            if n <= 9:
                park["ports"][port] = self._port(port, link=True, ever_up=True, alias=f"CAM-PARKING-{n:02d}", speed=100, base=0.05, macs=[(self._mac("other"), 40)],
                                                 poe_w=r.uniform(4, 9), poe_max_w=30.0, poe_status="Powered On")
            else:
                park["ports"][port] = self._port(port, alias="Libre")
        park["ports"]["1/1/25"] = self._port("1/1/25", link=True, ever_up=True, alias="UPLINK-ETAGE-3", speed=1000, base=0.06)
        park["lldp_full"]["1/1/25"] = {"name": "SW-ETAGE-3", "chassis": e3["chassis"][0]["mac"], "caps": "Bridge", "rport": "1/1/51"}
        park["reach"], park["last_ok"], park["cpu"], park["temp"] = False, time.time() - 780, 0.0, 0.0
        e3["ports"]["1/1/51"]["link"] = False
        for st in self.sw.values():  # ports non decrits : libres
            for name in st["order"]:
                st["ports"].setdefault(name, self._port(name))
            for name, p in st["ports"].items():
                for m, v in p["macs"]:
                    self.mac_db.setdefault(m, {"ip": st["ip"], "port": name, "vlan": v, "first": time.time() - r.uniform(0.2, 40) * 86400, "last": time.time(),
                                               "moves": 1 if r.random() < 0.04 else 0, "saved": time.time()})
            st["poe_total"] = sum(p.get("poe_w", 0) for p in st["ports"].values())
            tot = sum(p["base"] * (p["speed"] or 1000) * 1e6 for p in st["ports"].values() if p["link"]) if st["reach"] else 0
            for k in range(live.HISTORY):  # courbes deja remplies au demarrage
                w = 0.8 + 0.2 * math.sin(k / 9)
                st["hist"].append([time.time() - (live.HISTORY - k) * 3, tot * w * r.uniform(.9, 1.1) * 0.8, tot * w * r.uniform(.9, 1.1) * 0.6,
                                   st["cpu"] + r.uniform(-2, 2) if st["reach"] else 0, st["temp"] + r.uniform(-.4, .4) if st["reach"] else 0])
        self.notes[core["ip"]] = {"text": "Baie A1 - U14/U15. Pile de 2 chassis. Contact : equipe reseau.", "updated": time.time(), "by": "demo"}
        self.notes[e1["ip"] + "|1/1/30"] = {"text": "Imprimante etiquettes RDC - cable a changer.", "updated": time.time(), "by": "demo"}
        for k, v in self.notes.items():
            self.db.execute("INSERT OR REPLACE INTO notes VALUES(?,?,?,?)", (k, v["text"], v["updated"], v["by"]))

    # ------------------------------------------------------------------ historique fictif (7 jours)
    def _history(self):
        r, now, db = self.r, time.time(), self.db
        rows = []
        for st in self.sw.values():
            for k in range(7 * 144):  # une mesure toutes les 10 minutes
                t = now - (7 * 144 - k) * 600
                h = (t % 86400) / 86400
                load = 0.5 + 0.45 * math.sin((h - 0.3) * 2 * math.pi)
                tin = sum(p["base"] * (p["speed"] or 1000) * 1e6 for p in st["ports"].values() if p["link"]) * (0.4 + 0.6 * load) * r.uniform(0.9, 1.1)
                rows.append((t, st["ip"], 10 + 14 * load + r.uniform(-2, 2), st["mem"], 38 + 6 * load + r.uniform(-.5, .5), tin, tin * r.uniform(0.6, 1.0)))
        with db.lock:
            db.c.executemany("INSERT INTO metrics VALUES(?,?,?,?,?,?,?)", rows)
            db.c.commit()
        sw = list(self.sw.values())
        # configurations
        versions = {sw[0]["ip"]: [6.2, 3.1, 1.1], sw[1]["ip"]: [5.0, 0.7]}
        vl = [(1, "DEFAULT"), (10, "SERVEURS"), (20, "BUREAUTIQUE"), (30, "TELEPHONIE"), (40, "CAMERAS")]
        cfg_ids = {}
        for ip, days_list in versions.items():
            st = self.sw[ip]
            for n, dd in enumerate(days_list):
                text = fake_config(st["name"], st["loc"], ip, n + 1, vl + ([(50, "INVITES")] if n >= 1 else []), ["192.0.2.50"] + (["192.0.2.51"] if n >= 2 else []))
                t = now - dd * 86400
                folder = live.BACKUPS / st["name"]
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / (datetime.fromtimestamp(t).strftime("%Y%m%d-%H%M%S") + ".cfg")
                path.write_text(text, encoding="utf-8")
                cid = db.execute("INSERT INTO configs(ip,name,t,sha,path,size) VALUES(?,?,?,?,?,?)", (ip, st["name"], t, hashlib.sha256(text.encode()).hexdigest(), str(path), len(text)))
                cfg_ids.setdefault(ip, []).append((cid, t))
                st["last_backup"] = t
        # incidents passes (ouverts puis resolus) + evenements
        names = [(s["name"], s["ip"]) for s in sw[:4]]
        kinds = ["port_down", "errors", "util", "flap", "cpu", "temp", "speed"]
        evs = []
        for n in range(46):
            nm, ip = r.choice(names)
            kind = r.choice(kinds)
            port = f"1/1/{r.randrange(1, 45)}"
            t0 = now - r.uniform(0.2, 6.8) * 86400
            dur = r.choice([90, 240, 600, 1500, 3600, 9000])
            sev = "crit" if kind in ("port_down", "cpu") and r.random() < 0.3 else "warn"
            title = {"port_down": f"Port {port} down", "errors": f"Erreurs sur {port}", "util": f"Charge elevee {port}", "flap": f"Port instable {port}", "cpu": "CPU eleve",
                     "temp": "Temperature elevee", "speed": f"Lien en 10 Mb/s sur {port}"}[kind]
            if kind in ("cpu", "temp"):
                port = ""
            cause, steps = HINTS[kind]
            hid = db.execute("INSERT INTO alert_hist(key,sw,ip,title,sev,kind,port,opened,closed) VALUES(?,?,?,?,?,?,?,?,?)", (f"{nm}:{port}:{kind}", nm, ip, title, sev, kind, port, t0, t0 + dur))
            steps = [x.format(port=port) for x in steps]
            evs.append((t0, sev, nm, f"{title} (PC-DEMO-{r.randrange(1, 40):02d})", kind, port, {"alerte_id": hid, "titre": title, "gravite": sev, "cause": cause, "verifications": steps}))
            evs.append((t0 + dur, "ok", nm, f"resolu : {title}", kind, port, {"alerte_id": hid, "titre": title, "gravite": sev, "ouverte": t0, "duree_s": dur, "cause": cause}))
            if kind in ("port_down", "flap"):
                db.execute("INSERT INTO port_events VALUES(?,?,?,?)", (t0, ip, port, "down"))
                db.execute("INSERT INTO port_events VALUES(?,?,?,?)", (t0 + dur, ip, port, "up"))
        for n in range(10):
            nm, ip = r.choice(names)
            mac, port, t0 = self._mac("pc"), f"1/1/{r.randrange(1, 44)}", now - r.uniform(0.1, 6.5) * 86400
            evs.append((t0, "info", nm, f"Nouvel appareil {mac} sur {port} (VLAN 20)", "device_new", port, {"mac": mac, "vlan": 20, "port": port, "premiere_vue": t0}))
        for n in range(3):
            nm, ip = r.choice(names)
            mac, port, t0 = self._mac("pc"), f"1/1/{r.randrange(1, 44)}", now - r.uniform(0.1, 6.5) * 86400
            evs.append((t0, "info", nm, f"Appareil {mac} deplace : SW-ETAGE-1 1/1/{r.randrange(1, 40)} -> {port}", "device_move", port, {"mac": mac, "vlan": 20, "de": "SW-ETAGE-1 1/1/12", "vers": f"{nm} {port}", "deplacements": 1}))
        for ip, lst in cfg_ids.items():
            for n, (cid, t) in enumerate(lst):
                if n > 0:
                    evs.append((t, "info", self.sw[ip]["name"], "Configuration modifiee (sauvegarde automatique) - voir Configurations", "config", "",
                                {"sauvegarde": "automatique", "config_id": cid, "precedente_id": lst[n - 1][0], "taille_octets": 900}))
        for t, sev, nm, text, kind, port, detail in sorted(evs, key=lambda e: e[0]):
            self._event(t, sev, nm, text, kind=kind, port=port, detail=detail)

    # ------------------------------------------------------------------ vie du reseau fictif
    def _run(self):
        n = 0
        while True:
            time.sleep(3)
            n += 1
            now = time.time()
            with self.lock:
                for st in self.sw.values():
                    if not st["reach"]:
                        continue
                    k = zlib.crc32(st["ip"].encode()) % 7
                    st["cpu"] = max(2.0, 13 + 6 * math.sin(n / 18 + k) + self.r.uniform(-1.5, 1.5) + (66 if st["name"] == "SW-ETAGE-2" and 140 < n % 400 < 170 else 0))
                    st["temp"] = 41 + 3 * math.sin(n / 60 + k) + self.r.uniform(-.3, .3)
                    tin = tout = 0.0
                    for p in st["ports"].values():
                        if not p["link"]:
                            p["in"] = p["out"] = p["err"] = 0.0
                            continue
                        cap = (p["speed"] or 1000) * 1e6
                        wave = 0.75 + 0.25 * math.sin(n / 9 + p["phase"])
                        p["in"] = min(cap, cap * p["base"] * wave * self.r.uniform(0.8, 1.2))
                        p["out"] = min(cap, cap * p["base"] * wave * self.r.uniform(0.5, 1.1))
                        p["err"] = p["scn_err"] * self.r.uniform(0.7, 1.3) if p["scn_err"] else 0.0
                        p["crc"] += int(p["err"] * 3)
                        tin += p["in"]
                        tout += p["out"]
                    st["hist"].append([now, tin, tout, st["cpu"], st["temp"]])
                    if now - st["last_metric"] >= 60:
                        st["last_metric"] = now
                        self.db.execute("INSERT INTO metrics VALUES(?,?,?,?,?,?,?)", (now, st["ip"], st["cpu"], st["mem"], st["temp"], tin, tout))
                self._evaluate(now)

    # ------------------------------------------------------------------ remplacements des acces reseau
    def port_detail(self, ip, port):
        st = self.sw.get(ip)
        if st is None or port not in st["ports"]:
            return {"error": "port inconnu"}
        p, r = st["ports"][port], random.Random(zlib.crc32(f"{ip}{port}".encode()))
        vl = sorted({v for _, v in p["macs"]})
        lf = st["lldp_full"].get(port)
        d = {"oper": "up" if p["link"] else "down", "reason": "None", "last_change": "Mon Sep 14 08:12:41 2026", "changes": r.randrange(1, 12), "type": "Copper", "sfp": "N/A",
             "port_mac": f"02:00:5e:{zlib.crc32(ip.encode()) % 256:02x}:00:{int(port.split('/')[-1]):02x}", "bandwidth": p["speed"] or 1000, "duplex": p["duplex"].capitalize(),
             "autoneg": "1  [ 1000-F 100-F 100-H 10-F 10-H ]", "frame": 9216,
             "rx": {"bytes": r.randrange(10**9, 10**12), "unicast": r.randrange(10**6, 10**9), "broadcast": r.randrange(10**3, 10**6), "multicast": r.randrange(10**3, 10**6), "undersize": 0,
                    "oversize": 0, "lost": 0, "errors": p["crc"], "crc": p["crc"], "align": 0},
             "tx": {"bytes": r.randrange(10**9, 10**12), "unicast": r.randrange(10**6, 10**9), "broadcast": r.randrange(10**3, 10**6), "multicast": r.randrange(10**3, 10**6), "lost": 0,
                    "errors": 0, "collisions": 0, "late": 0},
             "vlans": [{"vlan": v, "type": "untagged" if i == 0 else "tagged", "state": "forwarding"} for i, v in enumerate(vl or [1])]}
        if lf:
            d["lldp"] = {"chassis": lf["chassis"], "port": lf["rport"], "name": lf["name"], "ip": "192.0.2.99" if lf["name"] else None, "descr": "Equipement fictif (demonstration)", "caps": lf["caps"]}
        return d

    def snapshot(self):
        snap = super().snapshot()
        snap["mode"] = "demo"
        return snap

    def backup_config(self, ip, who="automatique"):
        return {"changed": False, "id": 0, "info": "mode demonstration : pas de sauvegarde reelle"}
