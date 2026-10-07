# Sécurité

## Signaler une vulnérabilité

Merci de **ne pas** ouvrir d'issue publique. Utilisez le signalement privé de GitHub (*Security → Report a vulnerability*) ou
contactez directement le propriétaire du dépôt. Indiquez la version, les étapes de reproduction et l'impact estimé.

## Modèle de menace

Vigilia est un outil d'**administration réseau** : il détient un accès SSH aux switches et stocke leurs configurations.
Un attaquant qui le compromet vise ces secrets. Les protections sont donc organisées en couches : accès à l'interface,
accès aux switches, données stockées, système hôte.

## Contrôles en place

### Accès à l'interface
| Contrôle | Détail |
|---|---|
| Mots de passe | PBKDF2-HMAC-SHA256, 600 000 itérations, sel aléatoire ; conversion automatique des anciens hachés |
| Politique | 12 caractères minimum, 3 types sur 4, ni le nom d'utilisateur ni un mot courant |
| Pas de mot de passe par défaut | compte `admin` créé avec un mot de passe aléatoire affiché une seule fois |
| Double authentification | TOTP (RFC 6238), un code ne sert qu'une fois, désactivation soumise au mot de passe et au code |
| Force brute | 5 échecs/min/IP, 10 échecs/15 min/compte, pause à chaque échec ; réponse identique (compte inconnu ou faux mot de passe) |
| Sessions | jeton de 256 bits ; 2 h d'inactivité, 12 h maximum ; 5 par compte ; révoquées si compte supprimé, rôle changé, mot de passe changé |
| Cookie | `__Host-` + `Secure` + `HttpOnly` + `SameSite=Strict` (HTTPS) |
| CSRF | contrôle `Origin` / `Sec-Fetch-Site` et `Content-Type: application/json` sur toute écriture |
| Droits | rôles viewer / tech / admin vérifiés **côté serveur** à chaque requête |
| Limitation de débit | détail de port 60/min, rapports 30/min, exports 6/h, créations de comptes 10/h, par session ou compte |
| Journal d'audit | connexions, échecs, changements de mot de passe, créations de comptes, notes, sauvegardes, exports, consultations de configuration |

### Navigateur et réseau
| Contrôle | Détail |
|---|---|
| HTTPS obligatoire hors machine locale | refus de démarrer sans `--cert/--key` (sauf `--allow-http` explicite) ; TLS ≥ 1.2 ; HSTS |
| En-têtes | CSP stricte (aucun script externe ni en ligne), `X-Frame-Options`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, COOP/CORP |
| Fichiers servis | liste blanche (aucun parcours de dossiers possible) ; code de l'interface réservé aux utilisateurs connectés |
| Connexions | délai de 20 s par connexion, plafond de 120 connexions (25 par adresse), corps de requête limité à 8 Ko, poignée de main TLS dans le thread du client |
| XSS | toute donnée venant des switches ou des utilisateurs est échappée ou affichée en texte brut ; vérifié par analyse automatisée |
| Injection | requêtes SQL toujours paramétrées ; aucune saisie libre envoyée aux switches (liste blanche) ; CSV protégés contre les formules Excel |

### Accès aux switches et données
| Contrôle | Détail |
|---|---|
| Lecture seule | uniquement des commandes d'affichage ; aucune commande de configuration |
| Empreintes SSH épinglées | première connexion mémorisée dans `data/known_hosts` ; toute clé différente est refusée avec une alerte critique |
| Secret des switches | via identifiant systemd (`LoadCredential`) ou fichier 600, hors de l'environnement du processus |
| Configurations | fichiers 600 dans un dossier 700 ; secrets masqués pour le rôle `tech`, en clair pour `admin` seulement |
| Fichiers de données | `umask 077`, écriture atomique de `users.json`, base SQLite en dossier 700 |

### Système hôte (déploiement fourni)
Service systemd sous un utilisateur dédié sans shell, système de fichiers en lecture seule sauf `data/`, `NoNewPrivileges`, filtre d'appels système,
capacités réduites à `CAP_NET_BIND_SERVICE` (score `systemd-analyze security` ≈ 1,6/10), pare-feu nftables, SSH par clé uniquement.

## Liste de contrôle avant mise en production

- [ ] Compte SSH des switches **en lecture seule** (et non un administrateur)
- [ ] Certificat TLS de votre autorité interne (SAN : IP et DNS) ; sinon exception navigateur à accepter
- [ ] Mot de passe `admin` robuste, comptes **nominatifs** `tech` / `viewer` au quotidien, double authentification activée pour les administrateurs
- [ ] SSH du serveur : clé uniquement, pas de connexion root par mot de passe (`deploy/sshd_hardening.conf`)
- [ ] Pare-feu : 22 limité aux postes d'administration, 443 aux utilisateurs concernés (`deploy/nftables.conf`)
- [ ] Sauvegarde **chiffrée** de `data/` (contient des configurations de switches)
- [ ] Vérifier les empreintes SSH épinglées au premier lancement (`data/known_hosts`)
- [ ] Journaux envoyés vers un serveur central (`journalctl -u vigilia`, lignes `[securite]`)

## Limites connues

| Limite | Recommandation |
|---|---|
| Serveur HTTP de la bibliothèque standard Python | réseau interne uniquement ; au besoin nginx en frontal (TLS, filtrage d'adresses), Vigilia sur 127.0.0.1 |
| Pas d'annuaire ni de SSO | comptes locaux + TOTP ; SSO derrière un proxy d'authentification si besoin |
| `style-src 'unsafe-inline'` dans la CSP | les scripts, eux, sont strictement limités au site ; migration à terme vers des styles sans attributs en ligne |
| Empreintes SSH épinglées « à la première connexion » | comparer une fois les empreintes avec celles affichées par les switches |
| Journaux d'audit stockés sur la même machine | les transférer vers un serveur syslog central |
| Clé de double authentification stockée dans `users.json` (600) | protéger le dossier `data/` ; ne pas le copier |

## Tests

`python tests/test_vigilia.py` exécute 96 contrôles de sécurité et de fonctionnalités (authentification, CSRF, rôles, politique de mots de passe,
limitation de débit, double authentification, injection SQL, parcours de dossiers, exports, saturation, connexions lentes).
