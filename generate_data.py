"""
generate_data.py
------------------------------------------------------------
Genere data.js pour le site de stats a partir de deux sources :
  1. L'API REST officielle de Palworld (port secondaire de ton serveur)
     -> liste des joueurs connectes, infos serveur
  2. Le fichier de sauvegarde Level.sav, recupere par SFTP
     -> tous les Pals (espece, niveau, talents, proprietaire)

Ce script est fait pour tourner via GitHub Actions (voir
.github/workflows/update-data.yml) : toutes les infos sensibles
(mots de passe, hote SFTP...) sont lues depuis des variables
d'environnement -- JAMAIS ecrites en dur ici. Sur GitHub, ces
variables viennent des "Secrets" du repo.

/!\ Le chemin JSON utilise dans parse_pals() (SaveParameter -> CharacterID,
Level, Talent_*, OwnerPlayerUId...) correspond a la structure "historique"
documentee par la communaute palworld-save-tools. Selon la version du jeu
ca peut avoir legerement bouge -- si le script plante ou renvoie une liste
vide, on regardera les logs du run GitHub Actions pour ajuster.
------------------------------------------------------------
"""

import json
import os
import sys
import datetime
import requests
import paramiko


def env(name, required=True, default=None):
    val = os.environ.get(name, default)
    if required and not val:
        sys.exit(f"Variable d'environnement manquante : {name}")
    return val


REST_HOST = env("REST_HOST")
REST_PORT = int(env("REST_PORT", default="7785"))
ADMIN_USER = env("ADMIN_USER", default="admin")
ADMIN_PASSWORD = env("ADMIN_PASSWORD")

SFTP_HOST = env("SFTP_HOST")
SFTP_PORT = int(env("SFTP_PORT", default="22"))
SFTP_USER = env("SFTP_USER")
SFTP_PASSWORD = env("SFTP_PASSWORD")
SFTP_SAVE_PATH = env("SFTP_SAVE_PATH")

OUTPUT_PATH = "data.js"


def fetch_server_info_and_players():
    auth = (ADMIN_USER, ADMIN_PASSWORD)
    base = f"http://{REST_HOST}:{REST_PORT}/v1/api"

    info = requests.get(f"{base}/info", auth=auth, timeout=10).json()
    metrics = requests.get(f"{base}/metrics", auth=auth, timeout=10).json()
    players_raw = requests.get(f"{base}/players", auth=auth, timeout=10).json()["players"]

    server = {
        "name": info.get("servername", "Serveur Palworld"),
        "description": info.get("description", ""),
        "online": True,
        "current_players": metrics.get("currentplayernum"),
        "max_players": metrics.get("maxplayernum"),
        "version": info.get("version", ""),
    }

    players = [
        {
            "name": p["name"],
            "level": p.get("level"),
            "building_count": p.get("building_count"),
            "ping": round(p.get("ping", 0) or 0, 0),
            "online": True,
            "playerId": p.get("playerId"),
        }
        for p in players_raw
    ]
    return server, players


def download_save_file(local_path="Level.sav"):
    transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
    transport.connect(username=SFTP_USER, password=SFTP_PASSWORD)
    sftp = paramiko.SFTPClient.from_transport(transport)
    sftp.get(SFTP_SAVE_PATH, local_path)
    sftp.close()
    transport.close()
    return local_path


def decompress_sav(data):
    """
    Gere les deux formats de sauvegarde Palworld :
      - PlZ (zlib) : ancien format, gere par palworld-save-tools
      - PlM (Oodle) : nouveau format depuis la mise a jour ete 2026,
        gere ici via la librairie kraken-decompressor
    """
    import struct
    import zlib

    uncompressed_len, compressed_len = struct.unpack("<II", data[0:8])
    magic = data[8:11]
    save_type = data[11]
    body = data[12:12 + compressed_len]

    if magic == b"PlZ":
        from palworld_save_tools.palsav import decompress_sav_to_gvas
        raw, _ = decompress_sav_to_gvas(data)
        return raw
    elif magic == b"PlM":
        from kraken_decompressor import decompress as kraken_decompress
        raw = kraken_decompress(body, uncompressed_len)
        if save_type == 0x32:
            raw = zlib.decompress(raw)
        return raw
    else:
        raise Exception(f"Format de sauvegarde non reconnu (magic={magic!r})")


def parse_pals(save_path, player_id_to_name):
    from palworld_save_tools.gvas import GvasFile
    from palworld_save_tools.paltypes import PALWORLD_TYPE_HINTS

    with open(save_path, "rb") as f:
        raw = decompress_sav(f.read())
    gvas = GvasFile.read(raw, PALWORLD_TYPE_HINTS)

    char_map = gvas.properties["worldSaveData"]["value"]["CharacterSaveParameterMap"]["value"]

    pals = []
    for entry in char_map:
        try:
            params = entry["value"]["RawData"]["value"]["object"]["SaveParameter"]["value"]
        except (KeyError, TypeError):
            continue

        if params.get("IsPlayer", {}).get("value", False):
            continue  # on ne garde que les Pals

        owner_uid = str(params.get("OwnerPlayerUId", {}).get("value", ""))

        def talent(key):
            return params.get(key, {}).get("value", 0)

        passives_raw = params.get("PassiveSkillList", {}).get("value", {}).get("values", [])

        pals.append({
            "nickname": params.get("NickName", {}).get("value") or params.get("CharacterID", {}).get("value", "???"),
            "species": params.get("CharacterID", {}).get("value", "???"),
            "owner": player_id_to_name.get(owner_uid, "inconnu"),
            "level": params.get("Level", {}).get("value", 1),
            "rank": params.get("Rank", {}).get("value", 0),
            "is_alpha": params.get("IsRarePal", {}).get("value", False),
            "talents": {
                "hp": talent("Talent_HP"),
                "melee": talent("Talent_Melee"),
                "shot": talent("Talent_Shot"),
                "defense": talent("Talent_Defense"),
            },
            "passives": [p.get("value", p) for p in passives_raw],
        })
    return pals


def main():
    server, players = fetch_server_info_and_players()
    player_id_to_name = {p["playerId"]: p["name"] for p in players}

    pals = []
    try:
        save_path = download_save_file()
        pals = parse_pals(save_path, player_id_to_name)
    except Exception as e:
        # Le parsing des Pals est en cours de mise au point (nouveau format
        # de sauvegarde Oodle/PlM). On ne bloque pas le reste du site pour
        # autant : on publie quand meme le classement des joueurs.
        print(f"AVERTISSEMENT -- lecture des Pals impossible pour l'instant : {e}")

    data = {
        "generated_at": datetime.datetime.now().astimezone().isoformat(),
        "server": server,
        "players": players,
        "pals": pals,
        "records": None,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write("window.PALWORLD_DATA = ")
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write(";\n")

    print(f"OK -- {len(players)} joueurs, {len(pals)} pals -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
