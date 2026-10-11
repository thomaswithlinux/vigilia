# Vigilia — *always on watch*

Supervision **en lecture seule** de l'infrastructure : switches **Alcatel-Lucent Enterprise OmniSwitch (AOS 8)** et,
depuis la v2, hôtes **VMware ESXi** (machines virtuelles, stockage). Une seule interface, des alertes expliquées,
l'historique et les sauvegardes de configuration. Vigilia **ne modifie rien** sur les équipements supervisés.

## Versions

| Version | Dossier | Contenu | Statut |
|---|---|---|---|
| **v2** | [`v2/`](v2/) | Switches **+ serveurs VMware ESXi** (hôtes, VM, datastores), sécurité renforcée, 112 tests | **Version actuelle** |
| v1 | [`v1/`](v1/) | Switches uniquement, avec terminal SSH intégré | Conservée pour référence |

Chaque dossier est autonome (code, documentation, tests, déploiement) :

```bash
cd v2
pip install -r requirements.txt
python server.py          # démonstration : http://127.0.0.1:8090/
```

Voir [`v2/README.md`](v2/README.md) pour la présentation complète, [`v2/docs/INSTALLATION.md`](v2/docs/INSTALLATION.md)
pour la mise en production et [`v2/SECURITY.md`](v2/SECURITY.md) pour le modèle de sécurité.
L'historique des changements est dans [`CHANGELOG.md`](CHANGELOG.md).

## Passer de la v1 à la v2

Les données (`data/` : base, comptes, certificats, sauvegardes) sont compatibles : la v2 ajoute des fichiers, elle ne change pas
le format existant. Remplacez le code de `/opt/vigilia` par celui de `v2/`, ajoutez `python3-requests`, puis redémarrez le service.
Pour les serveurs ESXi : voir *Superviser des hôtes VMware ESXi* dans [`v2/docs/INSTALLATION.md`](v2/docs/INSTALLATION.md).
Attention : la v2 **n'inclut pas** le terminal SSH intégré de la v1 (voir le changelog).

## Licence

À définir par le propriétaire du dépôt (aucune licence n'est fournie pour le moment : tous droits réservés).
