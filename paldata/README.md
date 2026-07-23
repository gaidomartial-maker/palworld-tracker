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
applique bien son bonus). Approximation assumee : on ajoute la valeur
brute (30% ici) sans chercher a reproduire un eventuel facteur de
dilution que le jeu semble appliquer sur l'affichage de la stat generique
(exemple observe : 30% de bonus brut, mais +16% affiche sur "Attaque" en
jeu) -- accepte comme compromis raisonnable plutot que d'ignorer
totalement ces passifs tres frequents sur les Pals forts.

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
