# Installation

## 1. Essayer en local (démonstration)

```bash
pip install -r requirements.txt
python server.py                  # http://127.0.0.1:8090/ — réseau fictif
```

Le mot de passe du compte `admin` est généré au premier lancement et affiché **une seule fois**. Les données
(base, comptes) sont dans `./data` (ou `VIGILIA_DATA`). Sous Windows : mêmes commandes dans PowerShell.

## 2. Production sur Debian / Ubuntu (recommandé)

### Installation automatique

```bash
sudo ./deploy/install.sh --hosts "192.0.2.10,192.0.2.11-14" \
                         --switch-user vigiliaro \
                         --san "IP:192.0.2.100,DNS:vigilia.example.org" --firewall
```

Le script installe `python3-paramiko`, crée l'utilisateur système `vigilia`, copie l'application dans `/opt/vigilia`,
génère un certificat TLS auto-signé, demande le mot de passe SSH des switches (jamais affiché ni écrit dans un fichier
lisible par d'autres), installe le service systemd durci, crée le compte `admin` avec un mot de passe aléatoire affiché
une seule fois, et active le pare-feu si `--firewall` est donné.

### Installation manuelle (équivalent)

1. **Utilisateur et dossiers** : `useradd --system --home-dir /opt/vigilia --shell /usr/sbin/nologin vigilia` ;
   code dans `/opt/vigilia` (propriétaire root), données dans `/opt/vigilia/data` (propriétaire `vigilia`, mode 700).
2. **Certificat TLS** : `openssl req -x509 -newkey rsa:2048 -nodes -keyout data/key.pem -out data/cert.pem -days 825 -subj "/CN=vigilia" -addext "subjectAltName=IP:192.0.2.100,DNS:vigilia.example.org"` (droits 600, propriétaire `vigilia`).
3. **Secret des switches** : écrire le mot de passe dans `/etc/vigilia/sw_pass` (dossier 700, fichier 600, root). Le service le reçoit via
   `LoadCredential` : il n'apparaît pas dans l'environnement du processus.
4. **Configuration** : `/etc/vigilia/vigilia.env` (voir `deploy/vigilia.env.example`) — compte SSH et liste des switches.
5. **Service** : copier `deploy/vigilia.service` dans `/etc/systemd/system/`, puis `systemctl enable --now vigilia`.
6. **Premier compte** : `sudo -u vigilia env VIGILIA_DATA=/opt/vigilia/data python3 /opt/vigilia/adduser.py admin admin --random`.

### Compte SSH des switches

Créez sur les switches un compte dédié **en lecture seule** (profil sans droit d'écriture) et utilisez-le pour Vigilia.
Vérifiez qu'il peut exécuter `show ...` et `write terminal` (affichage de la configuration, utilisé pour les sauvegardes).
Au premier contact, Vigilia mémorise l'empreinte SSH de chaque switch (`data/known_hosts`) et refuse toute clé différente.

### Certificat de votre autorité interne

Remplacez `data/cert.pem` et `data/key.pem` par un certificat émis par votre autorité (SAN : adresse IP et nom DNS), droits 600,
propriétaire `vigilia`, puis `systemctl restart vigilia`. Évitez ainsi l'avertissement du navigateur.

### Pare-feu et SSH du serveur

- `deploy/nftables.conf` : entrée refusée par défaut, 22/tcp (limité) et 443/tcp ouverts. Restreignez le 22 à vos postes d'administration.
- `deploy/sshd_hardening.conf` : connexion par clé uniquement, pas de mot de passe, pas de redirections. **Testez votre clé dans une autre session avant de recharger sshd.**

## 3. Exploitation

```bash
systemctl status vigilia
journalctl -u vigilia -f                  # journal ; événements de sécurité préfixés [securite]
systemctl restart vigilia
```

| Tâche | Commande |
|---|---|
| Lister / ajouter / supprimer un compte | `adduser.py --list`, `adduser.py nom role [--random]`, `adduser.py --delete nom` |
| Mot de passe admin perdu | `adduser.py admin admin --random` puis `systemctl restart vigilia` |
| Désactiver la double authentification d'un compte | `adduser.py --reset-totp nom` |
| Changer le mot de passe SSH des switches | `printf '%s' '...' > /etc/vigilia/sw_pass` (600) puis redémarrer |
| Switch remplacé (alerte « clé SSH modifiée ») | `ssh-keygen -R <ip> -f /opt/vigilia/data/known_hosts` puis redémarrer |
| Mettre à jour | arrêter le service, remplacer les `.py` et `web/` (sans toucher à `data/`), redémarrer |
| Sauvegarder | `/opt/vigilia/data` (contient comptes, base, **configurations des switches : sensible**) — chiffrer la sauvegarde |

Les commandes `adduser.py` se lancent ainsi : `sudo -u vigilia env VIGILIA_DATA=/opt/vigilia/data python3 /opt/vigilia/adduser.py ...`.

## 4. Docker (démonstration)

```bash
docker compose up --build        # http://127.0.0.1:8090/
docker compose logs vigilia | grep "PREMIER LANCEMENT"
```

L'image n'est pas prévue pour la production (HTTP). Pour une supervision réelle, utilisez l'installation systemd.
