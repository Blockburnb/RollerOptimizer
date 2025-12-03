# RollerOptimizer
Auto optimizer de room rollercoin

pas d'api
utiliser les requêtes du navigateur pour récupérer les infos

## Règles et définitions (source unique — garder en mémoire)

- Terminologie
  - raw power : somme simple de la "power" de tous les miners placés (avant application de tout bonus).
  - bonus miner : champ `bonus_percent` des miners (dans `room_config.json`). Valeur exprimée en centi-pourcent : `100` = 1%.
  - bonus rack : pourcentage appliqué sur le raw power des miners installés sur ce rack (indépendant du bonus des miners).

- Règles d'espace / tailles
  - Dans l'inventaire, les racks sont identifiés par `size` égal à 6 ou 8.
  - Dans le `room_config.json`, les racks sont représentés par `rack_info.height` qui vaut `3` ou `4`. Pour obtenir la `size` du rack : size = height * 2 (3 -> size 6, 4 -> size 8).
  - Chaque rack est composé d'étages (height). Sur chaque étage on peut placer :
    - un miner de `width = 2`, ou
    - deux miners de `width = 1` (côte à côte).
  - Le champ `miner.width` dans `room_config.json` donne la largeur (1 ou 2) utilisée pour le placement.

- Application des bonus
  - Les bonus des racks s'appliquent uniquement au raw power des miners qui sont physiquement installés sur ce rack. Ils sont indépendants des bonus des miners.
  - Les bonus des miners sont des pourcentages appliqués sur le raw power total (somme de toutes les powers). Exemple : si la somme des `bonus_percent` uniques vaut 500, cela équivaut à 5% (= 0.05) appliqué au raw power.
  - Le bonus d'un miner est pris en compte au maximum une fois par combinaison (name, level). Si plusieurs miners identiques (même name et même level) sont placés, leur `bonus_percent` n'est compté qu'une seule fois.
  - Ordre / méthode de calcul utilisée par le programme :
    1. Calculer raw_power = somme des `power` de tous les miners présents.
    2. Calculer miner_bonus_percent_total = somme des `bonus_percent` uniques par (name, level).
       - miner_bonus_power = raw_power * (miner_bonus_percent_total / 10000). (car 100 -> 1% => diviser par 10000 pour obtenir la fraction)
    3. Pour chaque rack :
       - rack_raw_power = somme des `power` des miners placés sur ce rack.
       - rack_bonus_power = rack_raw_power * (rack_bonus_percent / 10000). (si le JSON de room contient `bonus` pour le rack)
       - Les racks peuvent aussi être mappés à l'inventaire des racks pour récupérer un `percent` si nécessaire ; mais par défaut le programme utilise le champ `bonus` présent dans `room_config.json`.
    4. final_power = raw_power + miner_bonus_power + sum(rack_bonus_power pour tous les racks)

- Capacités par room
  - Room 1 (level 0) peut contenir 12 racks
  - Room 2 (level 1) peut contenir 18 racks
  - Room 3 (level 2) peut contenir 18 racks
  - Room 4 (level 3) peut contenir 18 racks

- Remarques pratiques
  - Le programme initial se contente d'utiliser uniquement `room_config.json` pour calculer la puissance actuelle (raw + bonuses disponible localement dans ce JSON).
  - Plus tard on pourra enrichir le calcul en important les données d'inventaire (pour récupérer les `percent` des racks si le `room_config.json` n'en fournit pas).

## Utilisation du script de calcul (fichier dédié)
- Il existe un script `calculate_room_power.py` qui lit par défaut `room_config.json` (situé dans le même dossier) et affiche :
  - raw power total
  - bonus miners total (pourcentage et puissance additionnelle)
  - bonuses par rack et total
  - puissance finale (après application de tous les bonus)

Conserver ces règles dans le README permet de garder une trace et d'éviter des interprétations divergentes lors des évolutions du code.
