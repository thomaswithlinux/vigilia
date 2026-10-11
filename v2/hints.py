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
    # ---- serveurs VMware ESXi (supervision en lecture seule : Vigilia ne modifie jamais un hote ni une VM)
    "esx_unreach": (
        "L'hote ESXi ne repond plus a l'API : serveur eteint ou en plantage, lien reseau coupe, ou service de gestion arrete.",
        ["ping de l'IP de l'hote", "Verifier l'alimentation et l'iDRAC / la console du serveur", "Controler le lien du VLAN de management"],
    ),
    "esx_auth": (
        "L'hote refuse le compte de supervision (mot de passe change ou compte verrouille). Vigilia ne reessaie que toutes les 30 min pour ne pas verrouiller le compte.",
        ["Verifier le mot de passe du compte de supervision sur l'hote", "Mettre a jour /etc/vigilia/esxi.json puis redemarrer Vigilia", "Si le compte est verrouille, attendre la fin du verrouillage (15 min par defaut)"],
    ),
    "esx_state": (
        "L'hote est vu comme deconnecte ou ne repond pas : redemarrage en cours, service hostd arrete.",
        ["Verifier la console du serveur", "Redemarrer les services de gestion depuis la console si necessaire"],
    ),
    "esx_maint": (
        "L'hote est en mode maintenance : les VM ont normalement ete deplacees ou arretees.",
        ["Verifier que la maintenance est planifiee", "Sortir du mode maintenance une fois terminee"],
    ),
    "esx_cpu": (
        "L'hote est tres charge en CPU : une ou plusieurs VM consomment beaucoup, ou l'hote est sur-alloue.",
        ["Voir les VM les plus gourmandes dans la page Serveurs", "Repartir des VM sur un autre hote ou reduire les vCPU"],
    ),
    "esx_mem": (
        "La memoire de l'hote est presque pleine : risque de swap et de ralentissements.",
        ["Voir les VM qui consomment le plus de memoire", "Eviter la sur-allocation, ajouter de la RAM ou deplacer des VM"],
    ),
    "esx_status": (
        "Le materiel du serveur signale un etat degrade (capteur jaune ou rouge : alimentation, ventilateur, memoire, batterie RAID...).",
        ["Ouvrir l'iDRAC / iLO du serveur et lire le journal materiel", "Verifier alimentations, ventilateurs, batterie du controleur RAID", "Ouvrir un incident chez le constructeur si le defaut persiste"],
    ),
    "esx_temp": (
        "Temperature anormale dans le serveur : ventilation ou climatisation insuffisante.",
        ["Verifier les ventilateurs et le flux d'air de la baie", "Controler la climatisation de la salle", "Lire les capteurs dans l'iDRAC / iLO"],
    ),
    "ds_space": (
        "Datastore presque plein : les VM peuvent se bloquer si le disque est sature (snapshots, disques dynamiques).",
        ["Supprimer les snapshots inutiles", "Liberer ou etendre le datastore", "Verifier les disques thin en croissance"],
    ),
    "ds_down": (
        "Datastore inaccessible : stockage ou NAS injoignable, lien iSCSI/NFS coupe.",
        ["Verifier le NAS / la baie de stockage et le reseau de stockage", "Controler les VM qui utilisent ce datastore"],
    ),
    "vm_status": (
        "VMware signale un probleme sur cette machine virtuelle (statut jaune ou rouge).",
        ["Ouvrir la VM dans l'interface vSphere pour lire l'alarme", "Verifier le disque, la memoire et le journal de l'invite"],
    ),
    "vm_question": (
        "La VM est bloquee sur une question (espace disque, deplacement/copie, media...) : elle ne reprend pas tant que personne ne repond.",
        ["Ouvrir la VM dans vSphere et repondre a la question affichee"],
    ),
    "vm_snapshot": (
        "Un snapshot ancien ralentit la VM et remplit le datastore : il grossit a chaque ecriture.",
        ["Verifier si le snapshot est encore utile", "Le supprimer / consolider depuis vSphere apres validation"],
    ),
    "vm_cpu": (
        "La VM utilise la quasi-totalite de ses vCPU : application saturee ou VM sous-dimensionnee.",
        ["Regarder le processus gourmand dans la VM", "Augmenter les vCPU si la charge est normale"],
    ),
    "vm_mem": (
        "La VM utilise presque toute sa memoire : risque de swap dans l'invite.",
        ["Regarder les processus gourmands dans la VM", "Augmenter la memoire si la charge est normale"],
    ),
    "vm_disk": (
        "Un disque de la VM est presque plein (information remontee par les VMware Tools).",
        ["Nettoyer ou etendre le volume dans la VM", "Etendre le disque virtuel si besoin"],
    ),
}
