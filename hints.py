"""Causes probables et verifications proposees pour chaque type de probleme."""
HINTS = {
    "port_down": (
        "Lien tombe sur un port qui devrait etre actif.",
        ["Verifier le cable et le connecteur cote equipement", "show interfaces {port} status", "Tester avec un autre cable ou un autre port"],
    ),
    "errors": (
        "Erreurs CRC/FCS en hausse : cable abime, SFP fatigue ou negociation duplex incorrecte.",
        ["show interfaces {port} counters errors", "Remplacer le cable, nettoyer la fibre / le SFP", "Verifier la vitesse et le duplex des deux cotes"],
    ),
    "util": (
        "Lien sature : les paquets risquent d'etre perdus et la latence monte.",
        ["show interfaces {port} | include rate", "Identifier le flux dominant (NetFlow / sFlow)", "Envisager un agregat LACP ou un lien plus rapide"],
    ),
    "flap": (
        "Port instable : le lien monte et descend a repetition.",
        ["show logs | include {port}", "Changer de cable, verifier l'alimentation de l'equipement distant", "Desactiver Energy Efficient Ethernet cote client"],
    ),
    "duplex": (
        "Duplex different entre les deux extremites : collisions et debit degrade.",
        ["show interfaces {port} status", "Forcer auto-negociation des deux cotes", "Verifier la config du port distant"],
    ),
    "temp": (
        "Temperature elevee : ventilation insuffisante ou salle trop chaude.",
        ["show environment temperature", "Verifier ventilateurs et flux d'air de la baie", "Controler la climatisation de la salle"],
    ),
    "cpu": (
        "Charge CPU elevee : tempete de broadcast, boucle STP ou trop de trafic vers le plan de controle.",
        ["show processes cpu sorted", "show spanning-tree | include Root", "Chercher une boucle ou un flux broadcast anormal"],
    ),
    "speed": (
        "Liaison negociee en 10 Mb/s : cable ou carte reseau defaillants, ou equipement tres ancien.",
        ["show interfaces {port} status", "Changer de cable, tester un autre port", "Verifier la carte reseau de l'equipement"],
    ),
    "unreach": (
        "Le switch ne repond plus en SSH : equipement eteint, lien d'administration coupe ou IP modifiee.",
        ["ping de l'IP de management", "Verifier l'alimentation et le lien vers le coeur", "Controler le VLAN de management / le pare-feu"],
    ),
    "hostkey": (
        "L'empreinte SSH du switch a change : remplacement ou reinitialisation du switch, ou usurpation (attaque man-in-the-middle). Vigilia refuse de s'y connecter pour ne pas livrer le mot de passe.",
        ["Verifier que le switch a bien ete remplace ou reinitialise", "Apres validation : ssh-keygen -R <ip> -f /opt/vigilia/data/known_hosts, puis redemarrer Vigilia"],
    ),
}
