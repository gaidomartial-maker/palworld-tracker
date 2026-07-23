# paldata

Tables de correspondance "ID interne du jeu -> nom affichable" pour les
Pals (`pal_names.json`) et les competences passives (`passive_names.json`).

- Cle : l'ID interne (`CharacterID` / nom de passif) en minuscules.
- Valeur : `{"name": "...", "icon": "..."}` pour les Pals (icon = chemin
  relatif servi par https://github.com/deafdudecomputers/PalworldSaveTools,
  concatener avec `https://raw.githubusercontent.com/deafdudecomputers/PalworldSaveTools/main/resources/game_data`
  pour obtenir l'URL complete), `{"name": "...", "rank": N}` pour les
  passifs (rank : plus c'est eleve, meilleur est le passif ; negatif = passif
  penalisant).

Ces donnees sont extraites des fichiers de donnees du jeu Palworld
(resources/game_data/characters.json et skills.json du projet cite
ci-dessus) -- ce sont des donnees de jeu (noms, stats), pas du code, donc
distinctes de la licence GPL-3.0 de palsav_lite/. Elles appartiennent a
Pocketpair ; utilisees ici a des fins d'affichage communautaire non
commercial, comme le fait la quasi-totalite des sites de stats Palworld.

Pour regenerer/mettre a jour ces fichiers : retelecharger characters.json
et skills.json depuis le repo source et ne garder que name/asset/icon
(pals) ou name/asset/rank (passifs), indexes par asset en minuscules.
