# Changelog

## v2 — 2026-10-12

### Ajouté
- **Supervision des hôtes VMware ESXi** (`v2/esxi.py`, menu **Serveurs**) : hôtes (modèle, CPU, mémoire, températures, capteurs matériels,
  cartes réseau), machines virtuelles (état, CPU, mémoire, IP, VMware Tools, disques, snapshots), datastores.
  - **Lecture seule garantie** : liste blanche de méthodes de consultation de l'API vSphere ; toute méthode d'écriture est refusée par le client (testé).
  - Certificat de chaque hôte **épinglé** à la première connexion ; identifiants dans un fichier JSON root 600 injecté par `LoadCredential`.
  - Pas de verrouillage de compte : une seule nouvelle tentative toutes les 30 min après un refus d'identifiants.
  - Alertes intégrées aux **Problèmes**, au **Journal**, au bandeau et au **Rapport** (hôte injoignable, CPU, mémoire, état matériel, température,
    datastore plein, VM en erreur, snapshots anciens regroupés, etc.), avec causes probables et vérifications.
  - Historique CPU / mémoire des hôtes (table `metrics`), graphique en direct, panneau « Serveurs ESXi » sur la vue d'ensemble.
  - Route `GET /api/servers` (rôle `viewer`), script `web/servers.js`.
  - Données fictives en mode démonstration (hôtes `192.0.2.201-202`).
- `deploy/esxi.json.example`, `LoadCredential=esxi:` dans le service systemd, création du fichier par `deploy/install.sh`.
- Dépendance `requests` (`requirements.txt`, Dockerfile, `install.sh`).
- Tests : ceux du terminal intégré sont retirés, ceux de la supervision ESXi (lecture seule, alertes, mode démonstration) sont ajoutés : **112** tests au total.

### Sécurité (reprise de la version déployée en production)
- Réponses HTTP : en-tête `Server` neutre, CSP renforcée (`script-src 'self'`, `connect-src 'self'`, `worker-src 'none'`…), `X-Permitted-Cross-Domain-Policies`.
- Exceptions internes : réponse 500 générique, détail uniquement dans le journal.
- Limitation des échecs de connexion par compte (50) et par couple compte+adresse (10) sur 15 min ; noms de comptes réservés.
- Valeur de thème validée côté client ; page de connexion non indexable.
- Masquage des secrets de configuration étendu (`key`, `token`, `passphrase`, `shared-secret`, `private-key`).
  *Effet de bord connu* : la clé LACP `admin-key` est aussi masquée.
- `adduser.py` lancé en root conserve le propriétaire du fichier `users.json`.
- Hachage illisible dans `users.json` : refus propre au lieu d'une erreur serveur.

### Interface
- Nouvelle page de connexion (canal sécurisé, fond animé) et styles mis à jour.

### Retiré / différent de la v1
- **Terminal SSH intégré** (`web/shell.js`, routes `/api/shell/*`) : absent de la v2, qui ne contient que des fonctions de consultation.
  Il reste disponible dans `v1/`.
- Test de l'en-tête `Server` adapté (`web` au lieu de `Vigilia`).

## v1

Première version publiée : supervision en lecture seule des switches OmniSwitch AOS 8 (vue d'ensemble, switches, topologie, problèmes, journal,
appareils, PoE, performance, inventaire, configurations, rapport, administration, double authentification), terminal SSH intégré, 105 tests.
Voir [`v1/`](v1/).
