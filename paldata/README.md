# paldata

Tables de correspondance "ID interne du jeu -> nom affichable" pour les
Pals (`pal_names.json`) et les competences passives (`passive_names.json`),
plus les stats de base par espece necessaires au calcul des vraies stats
finales (`pal_stats.json`).

## pal_stats.json

Cle : asset en minuscules (sans prefixe Boss_, cf. generate_data.py qui le
retire avant de chercher). Valeur : `{hp_scaling, def_scaling, shot_attack,
craft_speed, friendship_hp, friendship_shotattack, friendship_defense}`,
extraits de characters.json (deafdudecomputers/PalworldSaveTools). Utilise
par `_compute_pal_power_stats()` dans generate_data.py, qui porte en Python
la formule de calcul de stats verifiee en jeu documentee dans
`.opencode/skills/pst-stat-formula/SKILL.md` et `src/palworld_aio/utils.py`
de ce meme depot (fonctions `_hp_breakdown`/`_atk_breakdown`/`_def_breakdown`).

Le bonus des passifs qui boostent directement PV/ATQ/DEF (ex: Legend =
+20% ATQ/+20% DEF) est extrait dans `passive_names.json` (cle `effects`,
ajoutee via `efftype1-4`/`effect1-4` de skills.json, en ne gardant que
MaxHP -> hp, ShotAttack/MeleeAttack -> atk, Defense -> def) et applique
par `_passive_stat_bonus()` + `_compute_pal_power_stats()`. Le classement
de puissance des Pals (palScore cote index.html) prend donc en compte :
niveau, %IV, rang/etoiles, confiance, eveil, et ces bonus de passifs --
tout est deja mecaniquement inclus dans PV/ATQ/DEF final, donc sommer ces
trois valeurs suffit sans compter separement le rang ou l'eveil (qui
biaiserait le score en les comptant deux fois).

Les passifs "Empereur elementaire" (ElementBoost_Fire/Earth/Water/...)
utilisent un type d'effet a part (pas ShotAttack) et boostent les degats
d'un element specifique -- extraits separement dans `passive_names.json`
(cle `element_atk`, ex: `{"Fire": 30}`) et dans `pal_stats.json` (cle
`elements`, ex: `["Fire"]` pour KingBahamut/Blazamut). Le bonus n'est
ajoute a l'ATQ que si l'element du passif correspond a un des elements du
Pal (verifie en jeu : Blazamut, de type Feu, avec Empereur Enflamme
applique bien son bonus).

Dilution verifiee en jeu : la valeur brute de skills.json (30) ne
correspond pas au bonus reellement affiche sur la stat ATQ. Tooltip
exacte de Blazamut (Empereur Enflamme, raw=30) : Attaque 977 -> 1594,
avec "Bonus d'ame +27%" et "Competences passives +16%" -- donc le vrai
bonus applique est 16%, pas 30%. Comme tous les passifs "_2_PAL"
(Fire/Dark/Water/Earth/Ice/Normal/Electricity/Leaf/Dragon) partagent
exactement la meme valeur brute 30 dans skills.json (meme definition de
competence reskinnee par element), ce facteur verifie est applique via
`ELEMENT_ATK_VERIFIED_DILUTION = {30: 16.0}` dans generate_data.py a
toute occurrence de cette valeur, sans extrapoler vers les autres
paliers (raw=10, 1, 6, 12, 18, 20...) qui n'ont pas ete verifies en jeu
et restent donc pris tels quels par prudence (moins frequents et impact
plus faible sur le classement).

- Cle : l'ID interne (`CharacterID` / nom de passif) en minuscules.
- Valeur pour les Pals : `{"name": "...", "name_fr": "..." (optionnel), "icon": "..."}`.
  `icon` = chemin relatif servi par https://github.com/deafdudecomputers/PalworldSaveTools,
  concatener avec `https://raw.githubusercontent.com/deafdudecomputers/PalworldSaveTools/main/resources/game_data`
  pour obtenir l'URL complete.
- Valeur pour les passifs : `{"name": "...", "name_fr": "..." (optionnel), "rank": N}`.
  rank : plus c'est eleve, meilleur est le passif ; negatif = passif penalisant.

Sources (donnees de jeu Palworld, pas du code -- distinctes de la licence
GPL-3.0 de palsav_lite/ ; appartiennent a Pocketpair, utilisees ici a des
fins d'affichage communautaire non commercial comme le fait la quasi-
totalite des sites de stats Palworld) :
- `name`/`icon` : resources/game_data/characters.json et skills.json du
  projet deafdudecomputers/PalworldSaveTools (activement maintenu, mais
  uniquement en anglais).
- `name_fr` : data-provider/baked-data/fr/pals.json et fr/skills.json du
  projet blaynem/paldex. Cette source date du lancement du jeu (janvier
  2024) et ne couvre donc PAS les Pals/passifs ajoutes depuis (la plupart
  des variantes BOSS_* recentes notamment) -- pour ceux-la, `name_fr` est
  absent et generate_data.py retombe sur le nom anglais.

Pour regenerer/mettre a jour ces fichiers : retelecharger characters.json/
skills.json (EN) et fr/pals.json/fr/skills.json depuis les repos source,
reconstruire name/icon/rank par asset en minuscules, puis fusionner
name_fr par-dessus quand une correspondance existe.

## breeding.json

Table statique pour le calculateur de breeding (`breeding.html`), sans
rapport avec le serveur -- purement des donnees de jeu officielles.

- `species` : cle = ID Paldex a 3 chiffres, avec un suffixe lettre pour
  les variantes elementaires (ex: `"024"` = Mau, `"024B"` = Mau Cryst).
  Valeur : `{name, name_fr, icon}`.
- `pairs` : cle = les deux ID Paldex parents tries et joints par `_`
  (ordre parent A/B indifferent), valeur = ID Paldex du bebe obtenu.

Genere une fois via un script Perl (non commite, jetable) qui :
1. Recupere `breeding.json` du depot MIT `mlg404/palworld-paldex-api`
   (table combi-rank du jeu deja inversee : bebe -> liste de paires de
   parents) et l'inverse en paire -> bebe.
2. Pour chaque ID Paldex, prend le nom/icone de `characters.json`
   (meme source que le reste du site) quand l'espece existe cote base
   (pas de suffixe lettre) ; sinon (variantes elementaires type Mau
   Cryst, Broncherry Aqua... absentes de characters.json) retombe sur
   le nom/icone de `mlg404/palworld-paldex-api` lui-meme (aussi MIT,
   images servies depuis son propre depot).
3. Merge `name_fr` depuis blaynem/paldex par asset quand disponible
   (variantes lettrees non couvertes, comme pour pal_names.json).

Verifie : la regle "meme espece + meme espece = meme espece" tient
(`001_001` -> `001`), coherent avec la mecanique connue du jeu. Couverture
complete : 137 especes, toutes avec un nom et une icone resolue (aucune
entree manquante).
