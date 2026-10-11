"""Supervision des hyperviseurs VMware ESXi, en LECTURE SEULE, via l'API vSphere (SOAP, https://<hote>/sdk).

Seules des methodes de consultation sont autorisees (liste blanche ALLOWED) : aucune methode de modification, de
mise sous/hors tension, de snapshot, de migration ou de configuration n'est jamais envoyee aux hotes ni aux VM.
Le certificat de l'hote est epingle a la premiere connexion (comme les cles SSH des switches).
Les identifiants viennent d'un fichier JSON (identifiant systemd 'esxi' ou VIGILIA_ESXI_FILE), jamais du code.
"""
import hashlib
import json
import re
import socket
import ssl
import threading
import time
import xml.etree.ElementTree as ET
from collections import deque

import requests
import urllib3
from requests.adapters import HTTPAdapter

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import auth

CYCLE = 30            # secondes entre deux releves
HISTORY = 180         # points gardes en memoire (90 min)
METRIC_EVERY = 60     # une mesure enregistree par minute et par hote
SNAP_WARN_DAYS = 7    # un snapshot plus vieux que ca ralentit la VM et remplit le datastore
AUTH_RETRY = 1800    # apres un refus d'identifiants : une seule nouvelle tentative toutes les 30 min (evite de verrouiller le compte root de l'ESXi)
PINS = auth.DATA / "esxi_pins.json"
_PINLOCK = threading.Lock()

# Liste blanche : uniquement de la consultation.
ALLOWED = {"RetrieveServiceContent", "Login", "Logout", "CreateContainerView", "DestroyView",
           "RetrievePropertiesEx", "ContinueRetrievePropertiesEx", "CancelRetrievePropertiesEx"}

NS = 'xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"

HOST_PROPS = ["name", "summary.overallStatus", "summary.hardware", "summary.quickStats", "summary.runtime.connectionState",
              "summary.runtime.powerState", "summary.runtime.inMaintenanceMode", "summary.runtime.bootTime", "summary.config.product",
              "config.network.pnic", "runtime.healthSystemRuntime.systemHealthInfo"]
VM_PROPS = ["name", "runtime.powerState", "runtime.host", "runtime.question", "summary.config", "summary.quickStats", "summary.guest",
            "summary.storage", "summary.overallStatus", "guest.disk", "snapshot.rootSnapshotList", "runtime.bootTime"]
DS_PROPS = ["name", "summary.capacity", "summary.freeSpace", "summary.type", "summary.accessible", "summary.maintenanceMode"]


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _scalar(el):
    t = (el.get(XSI_TYPE) or "").split(":")[-1]
    txt = el.text or ""
    if t in ("int", "long", "short", "byte"):
        try:
            return int(txt)
        except ValueError:
            return None
    if t in ("float", "double"):
        try:
            return float(txt)
        except ValueError:
            return None
    if t == "boolean":
        return txt == "true"
    return txt


def conv(el):
    """XML vSphere -> structures Python (listes pour les ArrayOf*, dictionnaires pour les objets, scalaires typés)."""
    kids = list(el)
    t = (el.get(XSI_TYPE) or "").split(":")[-1]
    if t.startswith("ArrayOf"):
        return [conv(k) for k in kids]
    if not kids:
        return _scalar(el)
    d = {}
    for k in kids:
        d.setdefault(_local(k.tag), []).append(conv(k))
    return {k: v[0] if len(v) == 1 else v for k, v in d.items()}


class PinAdapter(HTTPAdapter):
    """Refuse toute connexion dont le certificat n'a pas l'empreinte SHA-256 epinglee."""

    def __init__(self, fp, **kw):
        self.fp = fp
        super().__init__(**kw)

    def init_poolmanager(self, *a, **kw):
        kw["assert_fingerprint"] = self.fp
        kw["cert_reqs"] = "CERT_NONE"
        super().init_poolmanager(*a, **kw)


def _peer_fp(host, port=443):
    ctx = ssl.create_default_context()
    ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=8) as s, ctx.wrap_socket(s) as ss:
        return hashlib.sha256(ss.getpeercert(binary_form=True)).hexdigest()


def pinned_fp(host):
    """Premiere connexion : on memorise l'empreinte. Ensuite, une empreinte differente est refusee."""
    with _PINLOCK:
        try:
            pins = json.loads(PINS.read_text(encoding="utf-8")) if PINS.exists() else {}
        except ValueError:
            pins = {}
        if host not in pins:
            pins[host] = _peer_fp(host)
            tmp = PINS.with_suffix(".tmp")
            tmp.write_text(json.dumps(pins), encoding="utf-8")
            tmp.replace(PINS)
        return pins[host]


class AuthError(Exception):
    pass


class Client:
    def __init__(self, host, user, password):
        self.host, self.user, self.password = host, user, password
        self.s = None
        self.sc = None   # ServiceContent

    # ---- transport
    def _open(self):
        s = requests.Session()
        s.verify = False   # certificat auto-signe de l'ESXi : la confiance repose sur l'empreinte epinglee (PinAdapter), pas sur une autorite
        s.mount("https://", PinAdapter(pinned_fp(self.host)))
        s.headers.update({"Content-Type": "text/xml; charset=utf-8", "SOAPAction": "urn:vim25/6.5"})
        self.s = s

    def _call(self, method, this=None, body=""):
        if method not in ALLOWED:
            raise PermissionError(f"methode interdite (lecture seule) : {method}")
        h = f'<_this type="{this[0]}">{this[1]}</_this>' if this else ""
        xml = f'<?xml version="1.0" encoding="UTF-8"?><soapenv:Envelope {NS}><soapenv:Body><{method} xmlns="urn:vim25">{h}{body}</{method}></soapenv:Body></soapenv:Envelope>'
        r = self.s.post(f"https://{self.host}/sdk", data=xml.encode(), timeout=(8, 40))
        root = ET.fromstring(r.content)
        fault = root.find(".//{*}Fault")
        if fault is not None:
            msg = (fault.findtext("faultstring") or "erreur").strip()
            code = (fault.findtext("faultcode") or "")
            if "InvalidLogin" in ET.tostring(fault, encoding="unicode") or "Cannot complete login" in msg:
                raise AuthError(msg)
            if "NotAuthenticated" in ET.tostring(fault, encoding="unicode"):
                raise ConnectionError("session expiree")
            raise RuntimeError(f"{code}: {msg}"[:200])
        resp = root.find(f".//{{*}}{method}Response")
        return resp

    # ---- session
    def login(self):
        self._open()
        resp = self._call("RetrieveServiceContent", ("ServiceInstance", "ServiceInstance"))
        self.sc = conv(resp.find("{*}returnval"))
        self._call("Login", ("SessionManager", self._ref("sessionManager")),
                   f"<userName>{_x(self.user)}</userName><password>{_x(self.password)}</password>")

    def _ref(self, key):
        return self.sc[key]

    def close(self):
        try:
            if self.s and self.sc:
                self._call("Logout", ("SessionManager", self._ref("sessionManager")))
        except Exception:  # noqa: BLE001
            pass
        self.s = self.sc = None

    # ---- inventaire
    def inventory(self):
        """Hotes, VM et datastores avec leurs proprietes (une seule requete, lecture seule)."""
        root = self._ref("rootFolder")
        vm = self._ref("viewManager")
        r = self._call("CreateContainerView", ("ViewManager", vm),
                       f'<container type="Folder">{root}</container><type>HostSystem</type><type>VirtualMachine</type><type>Datastore</type><recursive>true</recursive>')
        view = r.findtext("{*}returnval")
        try:
            def pset(t, paths):
                return f'<propSet><type>{t}</type>' + "".join(f"<pathSet>{p}</pathSet>" for p in paths) + "</propSet>"
            body = (f'<specSet>{pset("HostSystem", HOST_PROPS)}{pset("VirtualMachine", VM_PROPS)}{pset("Datastore", DS_PROPS)}'
                    f'<objectSet><obj type="ContainerView">{view}</obj><skip>true</skip><selectSet xsi:type="TraversalSpec"><name>tv</name>'
                    f'<type>ContainerView</type><path>view</path><skip>false</skip></selectSet></objectSet></specSet><options/>')
            out = {"HostSystem": {}, "VirtualMachine": {}, "Datastore": {}}
            resp = self._call("RetrievePropertiesEx", ("PropertyCollector", self._ref("propertyCollector")), body)
            while True:
                rv = resp.find("{*}returnval")
                if rv is None:
                    break
                for o in rv.findall("{*}objects"):
                    ob = o.find("{*}obj")
                    props = {}
                    for ps in o.findall("{*}propSet"):
                        props[ps.findtext("{*}name")] = conv(ps.find("{*}val"))
                    out.get(ob.get("type"), {})[ob.text] = props
                tok = rv.findtext("{*}token")
                if not tok:
                    break
                resp = self._call("ContinueRetrievePropertiesEx", ("PropertyCollector", self._ref("propertyCollector")), f"<token>{_x(tok)}</token>")
            return out
        finally:
            try:
                self._call("DestroyView", ("ContainerView", view))
            except Exception:  # noqa: BLE001
                pass


def _x(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _refs(v):
    """Liste de references (datastore / vm) d'un ArrayOfManagedObjectReference."""
    out = []
    for x in v or []:
        out.append(x if isinstance(x, str) else x.get("#text", ""))
    return out


def _num(v, d=0):
    """Les valeurs vSphere arrivent souvent en texte (\"4096\") : on les convertit, sinon valeur par defaut."""
    if isinstance(v, bool):
        return d
    if isinstance(v, (int, float)):
        return v
    try:
        return float(v) if "." in str(v) else int(v)
    except (TypeError, ValueError):
        return d


def _bool(v):
    return v is True or str(v).lower() == "true"


def _sensors(health):
    """Temperatures utiles (°C) et capteurs en defaut, depuis les capteurs numeriques de l'hote.

    cpu = processeur le plus chaud, inlet = entree d'air (ambiance), bad = capteurs que le materiel declare jaunes/rouges.
    Le maximum de tous les capteurs n'est pas utilise : certains (bus PCIe, controleurs) tournent normalement a 80 °C."""
    cpu = inlet = None
    bad = []
    infos = (health or {}).get("numericSensorInfo") or []
    for s in infos if isinstance(infos, list) else [infos]:
        try:
            name = s.get("name") or ""
            key = ((s.get("healthState") or {}).get("key") or "").lower()
            if key in ("yellow", "red"):
                bad.append({"name": name, "state": key})
            if (s.get("sensorType") or "").lower() == "temperature":
                t = int(s["currentReading"]) * (10 ** int(s.get("unitModifier", 0)))
                low = name.lower()
                if "processor" in low or "cpu" in low:
                    cpu = t if cpu is None else max(cpu, t)
                elif "inlet" in low:
                    inlet = t
        except (KeyError, ValueError, TypeError, AttributeError):
            continue
    return cpu, inlet, bad


def _snapshots(roots):
    """(nombre, plus ancien en secondes epoch) des snapshots d'une VM."""
    n, oldest = 0, None
    stack = list(roots) if isinstance(roots, list) else ([roots] if roots else [])
    while stack:
        s = stack.pop()
        n += 1
        ct = s.get("createTime", "")
        try:
            from datetime import datetime
            t = datetime.fromisoformat(ct.replace("Z", "+00:00")).timestamp()
            oldest = t if oldest is None else min(oldest, t)
        except ValueError:
            pass
        ch = s.get("childSnapshotList")
        if ch:
            stack += ch if isinstance(ch, list) else [ch]
    return n, oldest


def _iso(t):
    try:
        from datetime import datetime
        return datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return 0


class Monitor:
    """Un thread par hote ESXi ; l'etat est expose a l'interface par snapshot() et aux alertes par alerts()."""

    def __init__(self, live, hosts):
        self.live = live
        self.lock = threading.Lock()
        self.hosts = {}
        for h in hosts:
            key = h["host"]
            self.hosts[key] = {"ip": key, "name": h.get("name") or key, "fixed": bool(h.get("name")), "reach": None, "seen": False,
                               "err": "", "auth_failed": False, "last_ok": 0, "hist": deque(maxlen=HISTORY), "last_metric": 0,
                               "info": None, "vms": [], "datastores": [], "tick": 0}
            threading.Thread(target=self._worker, args=(h,), daemon=True).start()

    # ---------------------------------------------------------------- collecte
    def _worker(self, cfg):
        st = self.hosts[cfg["host"]]
        cl = Client(cfg["host"], cfg.get("user", "root"), cfg["password"])
        while True:
            t0, wait = time.time(), CYCLE
            try:
                if cl.s is None:
                    cl.login()
                inv = cl.inventory()
                self._ingest(st, inv)
                with self.lock:
                    st["reach"], st["seen"], st["last_ok"], st["err"], st["auth_failed"] = True, True, time.time(), "", False
            except AuthError as e:
                cl.close()
                with self.lock:
                    st["reach"], st["err"], st["auth_failed"] = False, "identifiants refuses par l'hote", True
                wait = AUTH_RETRY   # jamais de rafale d'essais : l'ESXi verrouille le compte root apres quelques echecs
            except ConnectionError:
                cl.close()          # session expiree : on se reconnecte au prochain tour
                wait = 2
            except Exception as e:  # noqa: BLE001
                cl.close()
                with self.lock:
                    st["reach"], st["err"] = False, f"{type(e).__name__}: {e}"[:160]
            with self.live.lock:
                self.live._evaluate(time.time())
            time.sleep(max(2, wait - (time.time() - t0)))

    def _ingest(self, st, inv):
        now = time.time()
        hosts = inv["HostSystem"]
        if not hosts:
            raise RuntimeError("aucun hote dans la reponse")
        hid, h = next(iter(hosts.items()))
        hw, qs = h.get("summary.hardware") or {}, h.get("summary.quickStats") or {}
        prod = h.get("summary.config.product") or {}
        cores, mhz = _num(hw.get("numCpuCores"), 1), _num(hw.get("cpuMhz"), 1)
        cpu_cap, mem_cap = cores * mhz, _num(hw.get("memorySize")) / 1048576  # MHz, Mo
        cpu_use, mem_use = _num(qs.get("overallCpuUsage")), _num(qs.get("overallMemoryUsage"))
        cpu_pct = min(100.0, cpu_use / cpu_cap * 100) if cpu_cap else 0.0
        mem_pct = min(100.0, mem_use / mem_cap * 100) if mem_cap else 0.0
        temp, inlet, bad = _sensors(h.get("runtime.healthSystemRuntime.systemHealthInfo"))
        pn = h.get("config.network.pnic") or []
        pn = pn if isinstance(pn, list) else [pn]
        nics = [{"dev": p.get("device"), "mbps": _num((p.get("linkSpeed") or {}).get("speedMb")) if p.get("linkSpeed") else 0,
                 "mac": (p.get("mac") or "").lower()} for p in pn]
        dsets = {}
        for did, d in inv["Datastore"].items():
            cap, free = _num(d.get("summary.capacity")), _num(d.get("summary.freeSpace"))
            dsets[did] = {"name": d.get("name"), "type": d.get("summary.type"), "cap": cap, "free": free,
                          "pct": round((cap - free) / cap * 100, 1) if cap else 0.0, "ok": _bool(d.get("summary.accessible", True)),
                          "maint": d.get("summary.maintenanceMode") not in (None, "normal")}
        vms = []
        for vid, v in inv["VirtualMachine"].items():
            cfgv, qv, gv, sv = v.get("summary.config") or {}, v.get("summary.quickStats") or {}, v.get("summary.guest") or {}, v.get("summary.storage") or {}
            ncpu, mem_mb = _num(cfgv.get("numCpu"), 1), _num(cfgv.get("memorySizeMB"))
            disks = v.get("guest.disk") or []
            disks = disks if isinstance(disks, list) else [disks]
            nsn, oldest = _snapshots(v.get("snapshot.rootSnapshotList"))
            power = v.get("runtime.powerState") or "unknown"
            vms.append({
                "id": vid, "name": v.get("name") or cfgv.get("name") or vid, "power": power,
                "status": v.get("summary.overallStatus") or "gray", "os": cfgv.get("guestFullName") or "", "ncpu": ncpu, "mem_mb": mem_mb,
                "cpu_mhz": _num(qv.get("overallCpuUsage")), "cpu_pct": round(min(100.0, _num(qv.get("overallCpuUsage")) / (ncpu * mhz) * 100), 1) if power == "poweredOn" and mhz else 0.0,
                "mem_use_mb": _num(qv.get("guestMemoryUsage")), "mem_pct": round(min(100.0, _num(qv.get("guestMemoryUsage")) / mem_mb * 100), 1) if power == "poweredOn" and mem_mb else 0.0,
                "ip": gv.get("ipAddress") or "", "dns": gv.get("hostName") or "", "tools": gv.get("toolsRunningStatus") or gv.get("toolsStatus") or "",
                "uptime": _num(qv.get("uptimeSeconds")), "used": _num(sv.get("committed")), "prov": _num(sv.get("committed")) + _num(sv.get("uncommitted")),
                "disks": [{"path": x.get("diskPath"), "cap": _num(x.get("capacity")), "free": _num(x.get("freeSpace"))} for x in disks][:12],
                "snaps": nsn, "snap_oldest": oldest, "question": bool(v.get("runtime.question")), "template": _bool(cfgv.get("template")),
            })
        vms.sort(key=lambda x: (x["power"] != "poweredOn", x["name"].lower()))
        info = {
            "id": hid, "hostname": h.get("name") or st["ip"], "status": h.get("summary.overallStatus") or "gray",
            "conn": h.get("summary.runtime.connectionState") or "", "power": h.get("summary.runtime.powerState") or "",
            "maint": _bool(h.get("summary.runtime.inMaintenanceMode")), "boot": _iso(h.get("summary.runtime.bootTime", "")),
            "uptime": _num(qs.get("uptime")), "version": prod.get("fullName") or "", "build": prod.get("build") or "",
            "vendor": hw.get("vendor") or "", "model": hw.get("model") or "", "cpu_model": (hw.get("cpuModel") or "").strip(),
            "sockets": _num(hw.get("numCpuPkgs")), "cores": cores, "threads": _num(hw.get("numCpuThreads")), "mhz": mhz,
            "cpu_pct": round(cpu_pct, 1), "cpu_mhz": cpu_use, "cpu_cap": cpu_cap, "mem_pct": round(mem_pct, 1), "mem_use_mb": mem_use, "mem_mb": mem_cap,
            "temp": temp, "inlet": inlet, "bad_sensors": bad, "nics": nics,
            "vm_on": sum(1 for x in vms if x["power"] == "poweredOn"), "vm_total": len(vms),
        }
        with self.lock:
            st["info"], st["vms"], st["datastores"] = info, vms, sorted(dsets.values(), key=lambda d: d["name"] or "")
            if not st["fixed"]:
                st["name"] = info["hostname"]
            st["hist"].append([now, cpu_pct, mem_pct, temp or 0.0])
            if now - st["last_metric"] >= METRIC_EVERY:
                st["last_metric"] = now
                self.live.db.execute("INSERT INTO metrics VALUES(?,?,?,?,?,?,?)", (now, st["ip"], cpu_pct, mem_pct, temp or 0.0, 0, 0))

    # ----------------------------------------------------------------- alertes
    def alerts(self, now):
        """Alertes au meme format que les switches : {cle: (gravite, type, source, port, titre, detail)}."""
        found = {}
        with self.lock:
            for st in self.hosts.values():
                n, ip = st["name"], st["ip"]
                if st["reach"] is False:
                    if st["auth_failed"]:
                        found[f"{ip}:esx_auth"] = ("crit", "esx_auth", n, None, "Identifiants ESXi refuses", f"{ip} - verifier le compte de supervision")
                    elif st["seen"]:
                        found[f"{ip}:esx_unreach"] = ("crit", "esx_unreach", n, None, "Hote ESXi injoignable", f"{ip} - derniere reponse il y a {int(now - st['last_ok'])} s")
                    else:
                        found[f"{ip}:esx_unreach"] = ("warn", "esx_unreach", n, None, "Hote ESXi jamais joint", f"{ip} - {st['err']}")
                    continue
                i = st["info"]
                if not i:
                    continue
                if i["conn"] and i["conn"] != "connected":
                    found[f"{n}:esx_state"] = ("crit", "esx_state", n, None, "Hote ESXi deconnecte", f"etat : {i['conn']}")
                if i["maint"]:
                    found[f"{n}:esx_maint"] = ("warn", "esx_maint", n, None, "Hote en mode maintenance", "les VM ne tournent pas normalement")
                for key, kind, w, c, lab in (("cpu_pct", "esx_cpu", 75, 90, "CPU"), ("mem_pct", "esx_mem", 85, 95, "Memoire")):
                    v = i[key]
                    if v >= c:
                        found[f"{n}:{kind}"] = ("crit", kind, n, None, f"{lab} de l'hote critique", f"{v:.0f} % utilise")
                    elif v >= w:
                        found[f"{n}:{kind}"] = ("warn", kind, n, None, f"{lab} de l'hote eleve", f"{v:.0f} % utilise")
                if i["status"] in ("red", "yellow") or i["bad_sensors"]:
                    red = i["status"] == "red" or any(b["state"] == "red" for b in i["bad_sensors"])
                    names = ", ".join(b["name"].split(" ", 2)[-1] for b in i["bad_sensors"][:3])
                    found[f"{n}:esx_status"] = ("crit" if red else "warn", "esx_status", n, None, "Etat materiel degrade (capteurs du serveur)",
                                                f"statut {'rouge' if red else 'jaune'}" + (f" - capteur(s) : {names}" if names else ""))
                if i["temp"] is not None and i["temp"] >= 90:
                    found[f"{n}:esx_temp"] = ("crit", "esx_temp", n, None, "Temperature processeur critique", f"{i['temp']:.0f} °C")
                elif i["temp"] is not None and i["temp"] >= 80:
                    found[f"{n}:esx_temp"] = ("warn", "esx_temp", n, None, "Temperature processeur elevee", f"{i['temp']:.0f} °C")
                elif i["inlet"] is not None and i["inlet"] >= 40:
                    found[f"{n}:esx_temp"] = ("crit", "esx_temp", n, None, "Temperature d'entree d'air critique", f"{i['inlet']:.0f} °C")
                elif i["inlet"] is not None and i["inlet"] >= 32:
                    found[f"{n}:esx_temp"] = ("warn", "esx_temp", n, None, "Temperature d'entree d'air elevee", f"{i['inlet']:.0f} °C")
                for d in st["datastores"]:
                    if not d["ok"]:
                        found[f"{n}:ds:{d['name']}:acc"] = ("crit", "ds_down", n, None, f"Datastore {d['name']} inaccessible", "le stockage ne repond plus")
                    elif d["cap"] and d["pct"] >= 95:
                        found[f"{n}:ds:{d['name']}"] = ("crit", "ds_space", n, None, f"Datastore {d['name']} presque plein", f"{d['pct']:.0f} % utilise")
                    elif d["cap"] and d["pct"] >= 85:
                        found[f"{n}:ds:{d['name']}"] = ("warn", "ds_space", n, None, f"Datastore {d['name']} se remplit", f"{d['pct']:.0f} % utilise")
                old_snaps = []
                for v in st["vms"]:
                    if v["template"]:
                        continue
                    vk = f"{n}:vm:{v['id']}"
                    if v["status"] == "red" and v["power"] == "poweredOn":
                        found[vk + ":status"] = ("crit", "vm_status", n, None, f"VM {v['name']} en erreur", "statut VMware rouge")
                    elif v["status"] == "yellow" and v["power"] == "poweredOn":
                        found[vk + ":status"] = ("warn", "vm_status", n, None, f"VM {v['name']} a surveiller", "statut VMware jaune")
                    if v["question"]:
                        found[vk + ":question"] = ("warn", "vm_question", n, None, f"VM {v['name']} attend une reponse", "une question est en attente dans vSphere")
                    if v["snap_oldest"] and v["snap_oldest"] > 1262304000 and now - v["snap_oldest"] > SNAP_WARN_DAYS * 86400:  # dates avant 2010 = horloge invalide : ignorees
                        old_snaps.append((v["snap_oldest"], v["name"]))
                    if v["power"] == "poweredOn":
                        for k, kind, lab in (("cpu_pct", "vm_cpu", "CPU"), ("mem_pct", "vm_mem", "Memoire")):
                            if v[k] >= 95:
                                found[f"{vk}:{kind}"] = ("warn", kind, n, None, f"{lab} saturee sur {v['name']}", f"{v[k]:.0f} %")
                        for dk in v["disks"]:
                            if dk["cap"] and dk["free"] / dk["cap"] < 0.05:
                                found[f"{vk}:disk:{dk['path']}"] = ("warn", "vm_disk", n, None, f"Disque {dk['path']} presque plein sur {v['name']}",
                                                                    f"{100 - dk['free'] / dk['cap'] * 100:.0f} % utilise")
                if old_snaps:  # une seule alerte par hote : les snapshots anciens sont souvent nombreux et ne doivent pas noyer le reste
                    old_snaps.sort()
                    names = ", ".join(x[1] for x in old_snaps[:4]) + (f" et {len(old_snaps) - 4} autre(s)" if len(old_snaps) > 4 else "")
                    found[f"{n}:snapshots"] = ("warn", "vm_snapshot", n, None, f"{len(old_snaps)} VM avec un snapshot de plus de {SNAP_WARN_DAYS} jours",
                                               f"le plus ancien : {int((now - old_snaps[0][0]) / 86400)} j - {names}")
        return found

    # --------------------------------------------------------------- interface
    def ip_of(self, name):
        for st in self.hosts.values():
            if st["name"] == name:
                return st["ip"]
        return ""

    def snapshot(self):
        with self.lock:
            out = []
            for st in sorted(self.hosts.values(), key=lambda s: tuple(int(x) for x in s["ip"].split("."))):
                out.append({"ip": st["ip"], "name": st["name"], "reach": st["reach"], "err": st["err"], "auth_failed": st["auth_failed"], "last_ok": st["last_ok"],
                            "info": st["info"], "vms": st["vms"], "datastores": st["datastores"], "hist": list(st["hist"])})
            return {"now": time.time(), "tick": CYCLE, "hosts": out, "containers": "non exposes par l'API ESXi (voir docs)"}
