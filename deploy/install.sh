#!/usr/bin/env bash
# Installation de Vigilia sur Debian / Ubuntu (a lancer en root depuis la racine du depot).
#
#   sudo ./deploy/install.sh --hosts "192.0.2.10,192.0.2.11-14" --switch-user vigiliaro \
#                            --san "IP:192.0.2.100,DNS:vigilia.example.org" [--firewall]
#
# Ce que fait le script : installe les dependances (apt), cree l'utilisateur systeme `vigilia`, copie l'application
# dans /opt/vigilia, genere un certificat TLS auto-signe, enregistre le mot de passe SSH des switches (saisi, jamais
# affiche) dans /etc/vigilia/sw_pass, installe le service systemd durci, cree le compte `admin` avec un mot de passe
# ALEATOIRE affiche une seule fois, et (option) active un pare-feu nftables.
set -euo pipefail

HOSTS="" SWUSER="" SAN="" FIREWALL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --hosts) HOSTS="$2"; shift 2 ;;
    --switch-user) SWUSER="$2"; shift 2 ;;
    --san) SAN="$2"; shift 2 ;;
    --firewall) FIREWALL=1; shift ;;
    *) echo "Option inconnue : $1" >&2; exit 2 ;;
  esac
done
[ "$(id -u)" -eq 0 ] || { echo "A lancer en root (sudo)." >&2; exit 1; }
[ -n "$HOSTS" ] && [ -n "$SWUSER" ] && [ -n "$SAN" ] || { sed -n '2,10p' "$0"; exit 2; }
HERE="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$HERE/server.py" ] || { echo "Lancez ce script depuis le depot Vigilia." >&2; exit 1; }

echo "==> Dependances"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-paramiko openssl >/dev/null

echo "==> Utilisateur et dossiers"
id vigilia >/dev/null 2>&1 || useradd --system --home-dir /opt/vigilia --shell /usr/sbin/nologin vigilia
install -d -m 755 /opt/vigilia /opt/vigilia/web
install -d -m 700 -o vigilia -g vigilia /opt/vigilia/data
install -d -m 700 /etc/vigilia
for f in server.py live.py demo.py db.py auth.py hints.py adduser.py; do install -m 644 "$HERE/$f" /opt/vigilia/$f; done
rm -rf /opt/vigilia/web && cp -a "$HERE/web" /opt/vigilia/web && chmod -R go-w /opt/vigilia/web
chown -R root:root /opt/vigilia/*.py /opt/vigilia/web

echo "==> Certificat TLS auto-signe (remplacez-le par un certificat de votre autorite interne si vous en avez une)"
if [ ! -f /opt/vigilia/data/cert.pem ]; then
  openssl req -x509 -newkey rsa:2048 -nodes -keyout /opt/vigilia/data/key.pem -out /opt/vigilia/data/cert.pem -days 825 \
    -subj "/CN=vigilia" -addext "subjectAltName=$SAN" 2>/dev/null
  chown vigilia:vigilia /opt/vigilia/data/key.pem /opt/vigilia/data/cert.pem
  chmod 600 /opt/vigilia/data/key.pem /opt/vigilia/data/cert.pem
fi

echo "==> Configuration"
printf 'SW_USER=%s\nSW_HOSTS=%s\nPYTHONDONTWRITEBYTECODE=1\n' "$SWUSER" "$HOSTS" > /etc/vigilia/vigilia.env
chmod 600 /etc/vigilia/vigilia.env
if [ ! -s /etc/vigilia/sw_pass ]; then
  read -r -s -p "Mot de passe SSH du compte '$SWUSER' sur les switches : " SWPASS; echo
  printf '%s' "$SWPASS" > /etc/vigilia/sw_pass; unset SWPASS
  chmod 600 /etc/vigilia/sw_pass
fi
install -m 644 "$HERE/deploy/vigilia.service" /etc/systemd/system/vigilia.service

echo "==> Compte administrateur"
if [ ! -f /opt/vigilia/data/users.json ]; then
  runuser -u vigilia -- env VIGILIA_DATA=/opt/vigilia/data python3 /opt/vigilia/adduser.py admin admin --random
  echo "    ^ Notez ce mot de passe maintenant : il ne sera plus affiche."
fi

if [ "$FIREWALL" -eq 1 ]; then
  echo "==> Pare-feu nftables (SSH 22 limite + HTTPS 443)"
  apt-get install -y -qq nftables >/dev/null
  install -m 644 "$HERE/deploy/nftables.conf" /etc/nftables.conf
  systemctl enable --now nftables
fi

echo "==> Demarrage"
systemctl daemon-reload
systemctl enable --now vigilia
sleep 3
systemctl is-active vigilia
echo
echo "Vigilia est disponible sur https://<adresse-du-serveur>/  (certificat auto-signe : exception a accepter la premiere fois)."
echo "Journal : journalctl -u vigilia -f"
