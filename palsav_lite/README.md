# palsav_lite

Ce dossier contient une copie (vendored) des modules de **parsing** GVAS
(`archive.py`, `gvas.py`, `paltypes.py`, `json_tools.py`, `rawdata/`) du
projet [deafdudecomputers/PalworldSaveTools](https://github.com/deafdudecomputers/PalworldSaveTools)
(sous-dossier `src/palsav`), sous licence GPL-3.0-or-later (voir `LICENSE`).

Pourquoi une copie plutot qu'une dependance pip normale :
- Ce sous-projet n'est pas publie sur PyPI.
- Son `__init__.py` d'origine importe aussi ses modules de compression
  (`core`, `compressor`), qui dependent d'un paquet C++ compile
  (`palooz`) non necessaire ici -- la decompression Oodle est deja geree
  par `pyooz` dans `generate_data.py`. Cette copie ne garde que les
  modules de parsing purs Python, avec les imports internes adaptes
  (`palsav.` -> `palsav_lite.`).

Pourquoi cette copie existe : le paquet publie sur PyPI,
`palworld-save-tools` (utilise par ailleurs dans `requirements.txt` pour
le format de sauvegarde historique PlZ), n'a plus ete mis a jour depuis
fin 2024 et ses decodeurs `RawData` (personnages, objets de la carte...)
plantent des qu'ils rencontrent des champs ajoutes par une mise a jour
plus recente du jeu. `palsav_lite` reprend la version a jour et
activement maintenue de ces memes decodeurs.

Ne pas modifier ces fichiers a la main -- pour les mettre a jour, re-
telecharger la derniere version depuis le depot source et refaire le
remplacement `palsav.` -> `palsav_lite.`.
