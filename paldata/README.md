# paldata

Tables de correspondance "ID interne du jeu -> nom affichable" pour les
Pals (`pal_names.json`) et les competences passives (`passive_names.json`).

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
