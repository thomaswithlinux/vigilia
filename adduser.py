"""Gerer les comptes Vigilia.

  python adduser.py <nom> <viewer|tech|admin> [--random]   ajouter ou modifier (mot de passe saisi, ou aleatoire affiche une fois)
  python adduser.py --list                                 lister les comptes
  python adduser.py --delete <nom>                         supprimer un compte
  python adduser.py --reset-totp <nom>                     desactiver la double authentification d'un compte

viewer = lecture seule | tech = + notes, sauvegardes de config | admin = + administration et journal d'audit
Mot de passe : 12 caracteres minimum, 3 types de caracteres sur 4. Les changements sont pris en compte sans redemarrage.
"""
import getpass
import sys

import auth

a = sys.argv[1:]
if a == ["--list"]:
    for n, u in auth.load_users().items():
        print(f"{n:20} {u['role']}")
    sys.exit()
if len(a) == 2 and a[0] == "--reset-totp":
    if a[1] not in auth.load_users():
        sys.exit("Compte inconnu.")
    auth.set_totp(a[1], None)
    sys.exit(f"Double authentification desactivee pour {a[1]}.")
if len(a) == 2 and a[0] == "--delete":
    users = auth.load_users()
    if a[1] not in users:
        sys.exit("Compte inconnu.")
    if sum(1 for u in users.values() if u["role"] == "admin") == 1 and users[a[1]]["role"] == "admin":
        sys.exit("Refus : c'est le dernier administrateur.")
    del users[a[1]]
    auth.save_users(users)
    sys.exit(f"Compte {a[1]} supprime.")
if len(a) not in (2, 3) or a[1] not in auth.ROLES or (len(a) == 3 and a[2] != "--random"):
    sys.exit(__doc__)
name, role = a[0], a[1]
if len(a) == 3:
    pw = auth.random_password()
    shown = True
else:
    pw, shown = getpass.getpass(f"Mot de passe pour {name} : "), False
    err = auth.policy_error(pw, name)
    if err or pw != getpass.getpass("Confirmer : "):
        sys.exit(f"Refuse : {err or 'les deux saisies different'}.")
users = auth.load_users()
if name in users and users[name]["role"] == "admin" and role != "admin" and sum(1 for u in users.values() if u["role"] == "admin") == 1:
    sys.exit("Refus : c'est le dernier administrateur, il ne peut pas etre retrograde.")
users[name] = {"hash": auth.hash_pw(pw), "role": role}
auth.save_users(users)
print(f"Compte {name} enregistre avec le role {role}.")
if shown:
    print(f"Mot de passe (affiche une seule fois) : {pw}")
