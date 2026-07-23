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

/!\ Le chemin JSON utilise dans parse_characters() (SaveParameter -> CharacterID,
Level, Talent_*, OwnerPlayerUId, IsPlayer...) correspond a la structure
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
# Chemin SFTP vers la vraie bibliotheque Oodle du serveur dedie (celle que le
# jeu utilise lui-meme pour ecrire ses saves), ex: .../Pal/Binaries/Linux/liboo2corelinux64.so.9
# Optionnel : si absent, on retombe sur le decompresseur Kraken open source
# (moins fiable, cf. decompress_sav()).
SFTP_OODLE_LIB_PATH = env("SFTP_OODLE_LIB_PATH", required=False)

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


_oodle_lib = None
_oodle_lib_attempted = False


def _get_oodle_lib():
    """
    Charge la vraie bibliotheque Oodle (celle qui accompagne le serveur
    dedie Palworld) via SFTP + ctypes -- la garantie de compatibilite la
    plus solide puisque c'est le decodeur d'origine. Optionnel : si le
    serveur n'expose pas ce fichier (hebergement mutualise sans acces aux
    binaires), on retombe sur pyooz puis kraken-decompressor (cf.
    _oodle_decompress()).

    Retourne None si SFTP_OODLE_LIB_PATH n'est pas configure ou si le
    telechargement/chargement echoue.
    """
    global _oodle_lib, _oodle_lib_attempted
    if _oodle_lib_attempted:
        return _oodle_lib
    _oodle_lib_attempted = True

    if not SFTP_OODLE_LIB_PATH:
        return None

    import ctypes

    local_path = os.path.abspath("liboodle.so")
    try:
        transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
        transport.connect(username=SFTP_USER, password=SFTP_PASSWORD)
        sftp = paramiko.SFTPClient.from_transport(transport)
        sftp.get(SFTP_OODLE_LIB_PATH, local_path)
        sftp.close()
        transport.close()

        lib = ctypes.CDLL(local_path)
        # Signature verifiee aupres de plusieurs outils reels (dont quickbms) :
        # OodleLZ_Decompress(in, insz, out, outsz, fuzzSafe, checkCRC, verbosity,
        #                     decBufBase, decBufSize, callback, callbackData,
        #                     decoderMemory, decoderMemorySize, threadPhase)
        lib.OodleLZ_Decompress.restype = ctypes.c_int64
        lib.OodleLZ_Decompress.argtypes = [
            ctypes.c_char_p, ctypes.c_int64,
            ctypes.c_char_p, ctypes.c_int64,
            ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_void_p, ctypes.c_int64,
            ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_void_p, ctypes.c_int64,
            ctypes.c_int,
        ]
        _oodle_lib = lib
        print(f"[oodle] bibliotheque Oodle chargee depuis {SFTP_OODLE_LIB_PATH}")
    except Exception as e:
        print(f"[oodle] impossible de charger la vraie lib Oodle ({e}) -- repli sur kraken-decompressor")
        _oodle_lib = None
    return _oodle_lib


def _oodle_decompress(body, uncompressed_len):
    import ctypes

    lib = _get_oodle_lib()
    if lib is not None:
        out_buf = ctypes.create_string_buffer(uncompressed_len)
        written = lib.OodleLZ_Decompress(
            body, len(body), out_buf, uncompressed_len,
            0, 0, 0, None, 0, None, None, None, 0, 3,
        )
        if written == uncompressed_len:
            return out_buf.raw
        print(
            f"[oodle] OodleLZ_Decompress a renvoye {written} octets au lieu de "
            f"{uncompressed_len} -- repli sur pyooz"
        )

    # pyooz compile tous les codecs Oodle (Kraken, Mermaid, Selkie, Leviathan,
    # BitKnit...). kraken-decompressor ne compile que le codec Kraken pur --
    # or l'octet "type de compression" du flux (juste apres le magic PlM)
    # indique souvent un autre codec (ex: BitKnit) selon la mise a jour du
    # jeu, ce que kraken-decompressor ne sait pas du tout decoder (il
    # renvoie -1 immediatement). On essaie donc pyooz en premier.
    try:
        import ooz
        return ooz.decompress(body, uncompressed_len)
    except Exception as e:
        print(f"[oodle] pyooz a echoue ({e}) -- repli sur kraken-decompressor")

    from kraken_decompressor import decompress as kraken_decompress
    return kraken_decompress(body, uncompressed_len)


def decompress_sav(data):
    """
    Gere les deux formats de sauvegarde Palworld :
      - PlZ (zlib) : ancien format, gere par palworld-save-tools
      - PlM (Oodle) : nouveau format depuis la mise a jour ete 2026, gere
        par _oodle_decompress() (vraie lib Oodle si disponible, sinon
        pyooz, sinon kraken-decompressor en dernier recours)

    Header (12 octets) : uncompressed_len (u32), compressed_len (u32),
    magic (3 octets), save_type (1 octet). Pour le format PlM, save_type
    vaut toujours 0x31 et le corps est decompresse en une seule passe
    Oodle -- il n'y a pas de zlib par-dessus.
    """
    import struct

    uncompressed_len, compressed_len = struct.unpack("<II", data[0:8])
    magic = data[8:11]
    body = data[12:12 + compressed_len]

    if magic == b"PlZ":
        from palworld_save_tools.palsav import decompress_sav_to_gvas
        raw, _ = decompress_sav_to_gvas(data)
        return raw
    elif magic == b"PlM":
        try:
            raw = _oodle_decompress(body, uncompressed_len)
        except Exception as e:
            raise Exception(
                f"Echec decompression Oodle (body_len={len(body)}, "
                f"uncompressed_len={uncompressed_len}) : {e}"
            ) from e
        if len(raw) != uncompressed_len:
            raise Exception(
                f"Decompression Oodle incoherente : {len(raw)} octets obtenus, "
                f"{uncompressed_len} attendus"
            )
        return raw
    else:
        raise Exception(f"Format de sauvegarde non reconnu (magic={magic!r})")


def _normalize_uid(value):
    """
    L'API REST renvoie les UID joueur sous forme hex sans tirets
    (ex: "9B41274E000000000000000000000000"), alors que Level.sav les
    expose comme de vrais objets UUID ("75567350-0000-0000-0000-...").
    Sans normaliser les deux vers la meme forme, un joueur connecte se
    retrouverait en double : une fois "en ligne" (API), une fois "hors
    ligne" (sauvegarde), avec deux UID qui ne matchent jamais.
    """
    if not value:
        return ""
    return str(value).replace("-", "").upper()


def parse_characters(save_path, online_players):
    """
    Level.sav contient un CharacterSaveParameterMap qui liste TOUS les
    "personnages" du monde -- pals ET joueurs -- et persiste meme quand
    un joueur est deconnecte. On s'en sert donc aussi pour construire le
    classement complet des joueurs (pas seulement ceux renvoyes par
    l'API REST, qui ne liste que les joueurs actuellement connectes).

    Le parsing GVAS passe par palsav_lite/ (vendore dans ce repo depuis
    deafdudecomputers/PalworldSaveTools, projet activement maintenu),
    pas par le paquet pip "palworld-save-tools" -- celui-ci est fige sur
    PyPI depuis fin 2024 et ses decodeurs RawData (character, map_object,
    etc.) plantent des qu'ils rencontrent des octets ajoutes par une mise
    a jour plus recente du jeu. palsav_lite ne reprend que les modules de
    parsing purs Python (archive/gvas/paltypes/rawdata) -- pas la partie
    compression, deja geree par _oodle_decompress() ci-dessus.
    """
    from palsav_lite.gvas import GvasFile
    from palsav_lite.paltypes import PALWORLD_CUSTOM_PROPERTIES, PALWORLD_TYPE_HINTS

    with open(save_path, "rb") as f:
        raw = decompress_sav(f.read())
    # custom_properties est indispensable : sans lui, RawData (qui contient
    # justement la structure SaveParameter d'un Pal/joueur) reste un tableau
    # d'octets brut non decode plutot que d'etre parse en objet exploitable.
    gvas = GvasFile.read(raw, PALWORLD_TYPE_HINTS, PALWORLD_CUSTOM_PROPERTIES)

    char_map = gvas.properties["worldSaveData"]["value"]["CharacterSaveParameterMap"]["value"]

    online_by_uid = {_normalize_uid(p["playerId"]): p for p in online_players}
    players_by_uid = {}
    pals_raw = []

    for entry in char_map:
        try:
            params = entry["value"]["RawData"]["value"]["object"]["SaveParameter"]["value"]
        except (KeyError, TypeError):
            continue

        if params.get("IsPlayer", {}).get("value", False):
            uid = _normalize_uid(entry.get("key", {}).get("PlayerUId", {}).get("value"))
            if not uid or uid == "0" * 32:
                continue
            online_info = online_by_uid.get(uid)
            players_by_uid[uid] = {
                "name": params.get("NickName", {}).get("value") or (online_info["name"] if online_info else "Joueur inconnu"),
                "level": params.get("Level", {}).get("value", 1),
                "building_count": online_info["building_count"] if online_info else None,
                "ping": online_info["ping"] if online_info else None,
                "online": online_info is not None,
                "playerId": uid,
            }
            continue

        owner_uid = _normalize_uid(params.get("OwnerPlayerUId", {}).get("value"))

        def talent(key):
            return params.get(key, {}).get("value", 0)

        passives_raw = params.get("PassiveSkillList", {}).get("value", {}).get("values", [])

        pals_raw.append((owner_uid, {
            "nickname": params.get("NickName", {}).get("value") or params.get("CharacterID", {}).get("value", "???"),
            "species": params.get("CharacterID", {}).get("value", "???"),
            "level": params.get("Level", {}).get("value", 1),
            "rank": params.get("Rank", {}).get("value", 0),
            "is_alpha": params.get("IsRarePal", {}).get("value", False),
            "talents": {
                "hp": talent("Talent_HP"),
                "melee": talent("Talent_Melee"),
                "shot": talent("Talent_Shot"),
                "defense": talent("Talent_Defense"),
            },
            "passives": [p.get("value", p) if isinstance(p, dict) else p for p in passives_raw],
        }))

    print(
        f"[parse_characters] char_map={len(char_map)} entrees, "
        f"joueurs_trouves={len(players_by_uid)}, pals_trouves={len(pals_raw)}"
    )

    # Un joueur qui vient de se connecter pour la premiere fois peut ne pas
    # encore avoir ete ecrit dans Level.sav -- on le rajoute quand meme.
    for uid, p in online_by_uid.items():
        players_by_uid.setdefault(uid, dict(p))

    pals = []
    for owner_uid, pal in pals_raw:
        pal["owner"] = players_by_uid.get(owner_uid, {}).get("name", "inconnu")
        pals.append(pal)

    players = sorted(players_by_uid.values(), key=lambda p: p["level"] or 0, reverse=True)
    return players, pals


def main():
    server, online_players = fetch_server_info_and_players()

    players = online_players
    pals = []
    try:
        save_path = download_save_file()
        players, pals = parse_characters(save_path, online_players)
    except Exception:
        # On ne bloque pas le reste du site pour autant : on publie quand
        # meme le classement des joueurs en ligne (renvoye par l'API REST).
        # La trace complete part dans les logs du run GitHub Actions pour
        # pouvoir diagnostiquer precisement ce qui a casse.
        import traceback
        print("AVERTISSEMENT -- lecture de Level.sav impossible pour l'instant :")
        traceback.print_exc()

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
