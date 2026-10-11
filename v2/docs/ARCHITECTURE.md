# Architecture

```
Navigateur ──HTTPS──▶ Vigilia (Python, 1 processus)
                         ├─ server.py   routes, sessions, droits, en-têtes, limitation de débit
                         ├─ auth.py     comptes (users.json), PBKDF2, TOTP, masquage des secrets
                         ├─ db.py       SQLite (WAL) : historique, audit, notes, appareils, configurations
                         ├─ live.py     1 session SSH par switch, collecte toutes les 20 s, alertes, exports
                         ├─ esxi.py     1 thread par hôte ESXi, API vSphere (SOAP) en lecture seule, toutes les 30 s
                         ├─ demo.py     mêmes interfaces que live.py avec un réseau fictif
                         └─ web/        interface (aucun framework : JS, CSS et polices locales)
                                │
                                ├──SSH 22 (lecture seule)──▶ switches
                                └──HTTPS 443 (lecture seule)──▶ hôtes VMware ESXi
```

## Collecte (live.py)

Une session SSH persistante par switch (empreinte épinglée dans `data/known_hosts`). Seules des commandes d'**affichage** sont envoyées :

| Commande | Usage | Fréquence |
|---|---|---|
| `show health`, `show temperature` | CPU, mémoire, température | 20 s |
| `show interfaces status`, `show interfaces alias` | vitesse, duplex, état, noms des ports | 20 s |
| `show interfaces counters`, `counters errors` | débit par port, erreurs | 20 s |
| `show system`, `show chassis`, `show lldp remote-system` | identité, firmware, séries, voisins | 2 min |
| `show mac-learning`, `show lanpower slot X/Y` | appareils connectés, PoE | 1 min |
| `show interfaces <port>`, `show vlan members port <port>`, `show lldp port <port> remote-system` | détail d'un port (à la demande, 60/min/session) | à la demande |
| `write terminal` | affiche la configuration pour la sauvegarde (n'écrit rien) | 1/jour ou sur demande |

Les noms de ports insérés dans une commande proviennent d'une liste blanche issue des switches : aucune saisie libre n'est envoyée.

## Supervision ESXi (esxi.py)

Un thread par hôte ouvre une session sur l'API vSphere (`https://<hôte>/sdk`) et relit toutes les 30 s, **en une seule requête**, l'inventaire :
hôte (matériel, CPU, mémoire, capteurs, cartes réseau), machines virtuelles (état, ressources, VMware Tools, disques, snapshots) et datastores.

- **Lecture seule garantie par le code** : le client n'accepte qu'une liste blanche de méthodes de consultation (`RetrieveServiceContent`, `Login`, `Logout`,
  `CreateContainerView`, `DestroyView`, `RetrievePropertiesEx`, `ContinueRetrievePropertiesEx`, `CancelRetrievePropertiesEx`). Toute autre méthode lève une
  erreur avant d'être envoyée ; les tests le vérifient.
- **Certificat épinglé** : l'empreinte SHA-256 du certificat de l'hôte est mémorisée à la première connexion (`data/esxi_pins.json`) ; un certificat différent est refusé.
- **Pas de verrouillage de compte** : après un refus d'identifiants, une seule nouvelle tentative toutes les 30 min (l'ESXi verrouille un compte après quelques échecs).
- **Alertes** (mêmes mécanismes que les switches) : hôte injoignable / déconnecté / en maintenance, identifiants refusés, CPU (75 / 90 %), mémoire (85 / 95 %),
  capteurs matériels jaunes ou rouges, température processeur (80 / 90 °C) et entrée d'air (32 / 40 °C), datastore (85 / 95 % ou inaccessible),
  VM en erreur ou bloquée sur une question, snapshots de plus de 7 jours (une alerte par hôte), CPU / mémoire de VM ≥ 95 %, disque de VM ≥ 95 %.
- Les mesures CPU / mémoire de chaque hôte sont enregistrées une fois par minute dans la table `metrics` (mêmes durées de conservation que les switches).
- Identifiants : fichier JSON (`/etc/vigilia/esxi.json`, identifiant systemd `esxi`), jamais dans le code ni dans l'interface.

## Alertes

| Alerte | Seuil orange | Seuil rouge |
|---|---|---|
| CPU | ≥ 75 % | ≥ 90 % |
| Température | ≥ 62 °C | ≥ 75 °C |
| Charge d'un lien | ≥ 85 % | ≥ 95 % |
| Erreurs sur un port | ≥ 5 /s | ≥ 40 /s |
| Port actif devenu inactif | port d'accès | lien inter-switch ou serveur |
| Port instable | ≥ 3 coupures en 10 min | — |
| Lien à 10 Mb/s, half-duplex | oui | — |
| Switch injoignable | jamais joint | joint puis perdu |
| Clé SSH modifiée | — | toujours |

Une alerte apparaît, se met à jour et se résout automatiquement ; chaque transition est écrite dans le journal avec son contexte.

## Données (SQLite)

| Table | Contenu | Conservation |
|---|---|---|
| `events` | journal détaillé (niveau, switch, port, type, détail JSON) | 180 jours |
| `alert_hist` | historique des alertes (ouverture, fermeture) | illimitée |
| `metrics` | CPU, mémoire, température, débit (1 mesure/min/switch) | 35 jours |
| `port_events` | changements d'état de ports | 180 jours |
| `macs` | appareils vus (première vue, emplacement, déplacements) | illimitée |
| `inventory`, `configs`, `notes` | inventaire, versions de configuration, notes | illimitée |
| `audit` | connexions, échecs, actions sensibles | 365 jours |

Les configurations sont écrites dans `data/backups/<switch>/AAAAMMJJ-HHMMSS.cfg` (fichiers 600, dossier 700).

## Interface de programmation

| Route | Méthode | Rôle minimal |
|---|---|---|
| `/`, `/app.css`, `/login.js`, `/theme.js`, `/favicon.svg`, `/fonts/*` | GET | aucun (liste blanche) |
| `/app.js`, `/views.js`, `/topo.js`, `/journal.js`, `/devices.js`, `/account.js`, `/servers.js` | GET | session |
| `/login`, `/logout` | POST | aucun / session |
| `/api/state`, `/api/me`, `/api/servers` | GET | viewer |
| `/api/port`, `/api/history`, `/api/report`, `/api/events`, `/api/event` | GET | viewer (limités par session) |
| `/api/password`, `/api/totp/start|enable|disable` | POST | viewer (son propre compte) |
| `/api/note`, `/api/backup` | POST | tech |
| `/api/configs`, `/api/config`, `/api/diff`, `/api/logs.zip` | GET | tech |
| `/api/users` (création), `/api/audit` | POST / GET | admin |

Toute requête d'écriture exige `Content-Type: application/json` et une origine identique au site (anti-CSRF).
