# Guide d'utilisation

Le menu de gauche donne accès à chaque écran. Tout tient dans la fenêtre : seuls les tableaux défilent. Le bandeau du haut
indique en permanence l'état global (vert, orange, rouge clignotant). Le bouton ◐ bascule entre thème sombre et clair,
« 👤 nom » ouvre votre compte, « ⇄ Changer de compte » ferme la session et revient à l'écran de connexion.

## Vue d'ensemble
Six compteurs, une carte par switch (état des ports en miniature, CPU, température, débit), les problèmes actifs, les derniers
événements et le trafic total. Un clic sur une carte ouvre le switch.

## Switches
Sélectionnez un switch à gauche : sa **façade** montre chaque port (vert actif, orange dégradé, rouge en panne, gris libre) avec une
barre de charge. Un clic sur un port ouvre le panneau de détail : appareils connectés (MAC, VLAN), trafic, liaison (vitesse, duplex,
auto-négociation, dernier changement), PoE, voisin LLDP, erreurs et compteurs, et la cause probable si le port a un problème.
Le bouton **« >_ Se connecter en SSH »** affiche la commande à copier et rappelle que le mot de passe se trouve dans votre gestionnaire
de mots de passe ; il propose aussi des commandes `show` utiles.

## Topologie interactive
- **Clic sur un switch** : déplie ses appareils, regroupés par catégorie (Wi-Fi, téléphones, serveurs, pare-feu, réseau, postes).
- **Clic sur une catégorie** : liste les appareils (12 premiers, « afficher tout » pour le reste).
- **Clic sur un appareil** : détails à droite (port, vitesse, VLAN, débit, PoE, toutes les MAC avec constructeur, voisin LLDP, note, problèmes).
- **Clic sur un lien** entre switches : ports, état et débit de chaque liaison (clic sur une ligne = détail du port).
- **Molette** pour zoomer, **glisser** pour déplacer, **Recentrer** pour tout voir. Les boutons « Tout déplier / replier » agissent sur tous les switches.
- La **recherche** (nom, MAC, port, VLAN, constructeur) ne garde que les appareils correspondants et déplie leurs switches.
- Les pastilles de catégorie masquent ou affichent un type d'appareil ; « Problèmes seulement » ne montre que ceux qui ont une alerte.

## Problèmes
Liste triée par gravité (critique, alerte) avec la durée de l'incident. À droite : cause probable, vérifications (commandes `show` à copier),
accès direct au port ou au switch.

## Journal détaillé
Le journal est conservé entre les redémarrages. Filtrez par **niveau**, **switch**, **type** (port down, erreurs, saturation, appareil nouveau ou déplacé,
configuration modifiée…), **période** et **texte**. Un clic sur une ligne affiche : la date exacte, l'endroit (switch, port cliquables), le contexte
(durée, MAC, anciens et nouveaux emplacements…), la cause probable, les vérifications, l'alerte liée avec ses dates d'ouverture et de fermeture, les
événements liés (même port ou même type) et ceux survenus dans les 5 minutes alentour. Boutons pour copier le message ou l'événement en JSON.

**Export** : « ⬇ Télécharger les logs (.zip) » (rôle technicien ou plus) produit une archive compressée avec `evenements.csv`, `alertes.csv`,
`coupures_ports.csv` et, pour un administrateur, `audit.csv`, sur 7, 30, 90 jours ou 1 an. Les CSV sont protégés contre l'injection de formules
Excel (valeur commençant par `=`, `+`, `-` ou `@` préfixée d'une apostrophe). Limité à 6 exports par heure.

## Appareils
Tableau de toutes les adresses MAC vues sur des ports actifs. Outre la recherche libre, des **filtres** : switch, VLAN, constructeur, type d'appareil,
vitesse, « Alimentés en PoE », « Nouveaux (24 h) », « Déplacés », « Avec un problème » et « Masquer les liens inter-switch ». Un clic sur un en-tête
trie la colonne. « Réinitialiser les filtres » remet tout à zéro ; « Exporter la liste (.csv) » exporte le résultat filtré.

## PoE, Performance, Inventaire
- **PoE** : consommation totale et par switch, ports alimentés.
- **Performance** : santé des switches ; courbes CPU et température en direct, 1 h, 24 h, 7 jours ou 30 jours.
- **Inventaire** : modèle, firmware (alerte si les versions diffèrent), numéros de série de chaque châssis, export CSV.

## Configurations
Une sauvegarde automatique par jour et par switch (commande d'affichage `write terminal`), plus « Sauvegarder maintenant ». Pour chaque version : **Voir**,
**Télécharger** (`.txt`), **Voir les changements** par rapport à la précédente. Dans le panneau « Contenu » : **Copier dans le presse-papiers** et **Télécharger .txt**.
Les secrets (clés SNMP hachées, mots de passe) sont masqués pour un technicien et visibles seulement d'un administrateur.

## Rapport
Sur 7 ou 30 jours : nombre d'incidents, critiques, durée moyenne de résolution, disponibilité par switch, ports les plus instables, types de problèmes.
Bouton « Imprimer / PDF ».

## Mon compte
Changer son mot de passe (12 caractères minimum, 3 types de caractères), voir sa **connexion précédente** (date et adresse, pour repérer une utilisation
suspecte) et activer la **double authentification** : saisir la clé affichée dans une application TOTP (Google Authenticator, Microsoft Authenticator,
Aegis, FreeOTP…), puis valider avec un code. Ensuite, chaque connexion demande le code en plus du mot de passe.

## Administration (admin)
Création de compte (nom, rôle, mot de passe saisi ou aléatoire affiché une seule fois), liste des comptes et **journal d'audit** (connexions, échecs,
changements de mot de passe, créations de comptes, sauvegardes, consultations de configuration, exports).

## Notes
Un switch ou un port peut porter une note (500 caractères), visible de tous (« prise B12, salle de réunion »). Un point bleu marque les ports annotés.
