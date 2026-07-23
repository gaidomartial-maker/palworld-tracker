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

PALDATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "paldata")
PAL_ICON_BASE_URL = (
    "https://raw.githubusercontent.com/deafdudecomputers/PalworldSaveTools/main/resources/game_data"
)


def _load_paldata(filename):
    path = os.path.join(PALDATA_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


PAL_NAMES = _load_paldata("pal_names.json")
PASSIVE_NAMES = _load_paldata("passive_names.json")
PAL_STATS = _load_paldata("pal_stats.json")

# Seuils de points de confiance -> rang de confiance (0-10), verifies en jeu
# (cf. paldata/README.md). Utilises par _compute_pal_power_stats().
FRIENDSHIP_THRESHOLDS = [0, 6000, 13000, 21000, 30000, 40000, 55000, 80000, 110000, 150000, 200000]


def _lookup_pal(char_id):
    # Les variantes "Boss_"/"BOSS_" ont souvent un nom a rallonge dans les
    # donnees (ex: "Gardien du soleil tenebreux Anubis" pour BOSS_Anubis,
    # "(Boss)" en anglais) -- on prefere toujours le nom de la version de
    # base ("Anubis") quand elle existe, sinon on retombe sur l'entree
    # Boss_ telle quelle.
    key = str(char_id).lower()
    base_key = key[5:] if key.startswith("boss_") else key
    entry = PAL_NAMES.get(base_key) or PAL_NAMES.get(key)
    if not entry:
        clean_id = char_id[5:] if key.startswith("boss_") else char_id
        return {"name": clean_id, "icon": None}
    name = entry.get("name_fr") or entry["name"]
    icon = f"{PAL_ICON_BASE_URL}{entry['icon']}" if entry.get("icon") else None
    return {"name": name, "icon": icon}


def _lookup_passive(passive_id):
    entry = PASSIVE_NAMES.get(str(passive_id).lower())
    if not entry:
        return {"id": passive_id, "name": passive_id, "rank": 0}
    name = entry.get("name_fr") or entry["name"]
    return {"id": passive_id, "name": name, "rank": entry.get("rank", 0)}


def _pal_elements(char_id):
    """Meme logique de lookup que _compute_pal_power_stats (cle exacte
    d'abord, repli sur la forme de base si la variante Boss n'a pas sa
    propre entree)."""
    key = str(char_id).lower()
    sd = PAL_STATS.get(key)
    if not sd and key.startswith("boss_"):
        sd = PAL_STATS.get(key[5:])
    return (sd or {}).get("elements", [])



ELEMENT_ATK_VERIFIED_DILUTION = {30: 16.0}


def _passive_stat_bonus(passive_ids, pal_elements):
    """
    Somme, sur tous les passifs d'un Pal, les bonus en % qui boostent
    directement PV/ATQ/DEF (ex: Legend = +20% ATQ, +20% DEF). Necessaire
    pour que le classement de puissance soit complet -- sans ca, un Pal
    avec Legend etait sous-estime par rapport a un Pal sans passifs.

    Les passifs "Empereur elementaire" (ElementBoost_X, ex: Empereur
    Enflamme = +30% degats Feu) ne comptent que si le Pal est bien de cet
    element -- verifie en jeu : Blazamut (Feu) avec Empereur Enflamme
    (Feu) applique bien son bonus.

    La valeur brute (30) stockee dans passive_names.json (extraite de
    skills.json) ne correspond pas au bonus reellement affiche en jeu sur
    la stat ATQ : verifie via la tooltip in-game exacte de Blazamut
    (Attaque 977 -> 1594, avec Bonus d'ame +27% et Competences passives
    +16%), le passif "Empereur Enflamme" (raw=30) n'ajoute en realite que
    +16% a l'ATQ affichee. Comme ElementBoost_Fire_2_PAL/_Dark_2_PAL/etc.
    partagent tous exactement la meme valeur brute 30 dans skills.json
    (meme definition de competence, juste reskinnee par element -- voir
    paldata/passive_names.json), ce facteur de dilution verifie (16/30)
    est applique a toute occurrence de cette meme valeur brute 30, sans
    inventer de facteur pour les autres paliers (raw=10, etc.) qui n'ont
    pas ete verifies en jeu et restent donc pris tels quels.
    """
    pal_elements = set(pal_elements or [])
    bonus = {"hp": 0.0, "atk": 0.0, "def": 0.0}
    for pid in passive_ids:
        entry = PASSIVE_NAMES.get(str(pid).lower())
        if not entry:
            continue
        effects = entry.get("effects")
        if effects:
            for stat in bonus:
                bonus[stat] += effects.get(stat, 0)
        element_atk = entry.get("element_atk")
        if element_atk:
            for element, value in element_atk.items():
                if element in pal_elements:
                    bonus["atk"] += ELEMENT_ATK_VERIFIED_DILUTION.get(value, value)
    return {k: v / 100 for k, v in bonus.items()}


def _friendship_rank(trust_points):
    for r in range(len(FRIENDSHIP_THRESHOLDS) - 1, 0, -1):
        if trust_points >= FRIENDSHIP_THRESHOLDS[r]:
            return r
    return 0


def _compute_pal_power_stats(char_id, level, talents, rank_hp, rank_attack, rank_defense,
                              condenser_rank, friendship_points, is_awake, passive_bonus=None):
    """
    Porte en Python la formule de calcul des vraies stats (PV/ATQ/DEF)
    verifiee en jeu par deafdudecomputers/PalworldSaveTools
    (.opencode/skills/pst-stat-formula/SKILL.md, src/palworld_aio/utils.py) :
    niveau, %IV, rang (etoiles/condenser), confiance, eveil ET bonus des
    passifs qui boostent directement une stat (ex: Legend) sont tous pris
    en compte -- c'est la base du classement de puissance des Pals.

    Retourne None si l'espece n'est pas dans paldata/pal_stats.json.
    """
    passive_bonus = passive_bonus or {"hp": 0, "atk": 0, "def": 0}
    import math

    # Contrairement a _lookup_pal() (qui affiche le nom "propre" sans le
    # prefixe Boss_), ici il ne faut PAS l'enlever avant de chercher : les
    # variantes Boss ont leurs propres stats de base, souvent nettement
    # superieures (ex: BOSS_BlackCentaur hp_scaling=156 vs 130 pour la
    # version normale). On cherche donc la cle exacte en priorite, et on
    # ne retombe sur la version de base que si la variante Boss n'a pas
    # sa propre entree.
    key = str(char_id).lower()
    sd = PAL_STATS.get(key)
    if not sd and key.startswith("boss_"):
        sd = PAL_STATS.get(key[5:])
    if not sd:
        return None

    friendship_rank = _friendship_rank(friendship_points)
    condenser_bonus = max(0, condenser_rank - 1) * 0.05
    awake = bool(is_awake)

    # -- PV --
    hp_scaling = sd["hp_scaling"]
    hp_iv = talents.get("hp", 0) * 0.3 / 100
    base_hp = math.floor(500 + 5 * level + hp_scaling * 0.5 * level * (1 + hp_iv))
    base_wc_hp = math.floor(base_hp * (1 + condenser_bonus))
    trust_hp = int(level * friendship_rank * sd["friendship_hp"] * 0.65 * (1 + condenser_bonus) + 0.5)
    awake_hp = math.floor(hp_scaling * level * 0.065 * (1 + condenser_bonus)) if awake else 0
    subtotal_hp = base_wc_hp + trust_hp + awake_hp
    hp = math.floor(subtotal_hp * (1 + rank_hp * 0.03) * (1 + passive_bonus["hp"]))

    # -- ATQ (Shot Attack, seule stat d'attaque depuis la fusion Melee/Shot) --
    shot_scaling = sd["shot_attack"]
    atk_iv = talents.get("shot", 0) * 0.3 / 100
    additive_const = math.floor(1.5 * level)
    base_atk = math.floor(additive_const + shot_scaling * 0.075 * level * (1 + atk_iv) * (1 + condenser_bonus))
    base_trust_atk = level * friendship_rank * sd["friendship_shotattack"] / 10.2
    trust_atk = math.floor(base_trust_atk) + math.floor(base_trust_atk * condenser_bonus)
    awake_atk = math.floor(shot_scaling * level * (1 + atk_iv) * 0.009) if awake else 0
    subtotal_atk = base_atk + trust_atk + awake_atk
    atk = math.floor(subtotal_atk * (1 + rank_attack * 0.03) * (1 + passive_bonus["atk"]))

    # -- DEF --
    def_scaling = sd["def_scaling"]
    def_iv = talents.get("defense", 0) * 0.3 / 100
    additive_const_def = math.floor(0.75 * level)
    base_def = math.floor(additive_const_def + def_scaling * 0.075 * level * (1 + def_iv) * (1 + condenser_bonus))
    trust_def = math.floor(level * friendship_rank * sd["friendship_defense"] / 10.2 * (1 + condenser_bonus))
    awake_def = math.floor(def_scaling * level * (1 + def_iv) * 0.009) if awake else 0
    subtotal_def = base_def + trust_def + awake_def
    defense = math.floor(subtotal_def * (1 + rank_defense * 0.03) * (1 + passive_bonus["def"]))

    return {"hp": hp, "atk": atk, "def": defense}


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


def _players_folder():
    idx = SFTP_SAVE_PATH.rfind("/")
    if idx == -1:
        return None
    return SFTP_SAVE_PATH[:idx] + "/Players"


def fetch_player_records(uids):
    """
    Level.sav (CharacterSaveParameterMap) n'a ni temps de jeu ni nombre de
    morts -- verifie a fond, ces infos n'existent nulle part dans la
    sauvegarde (le temps de jeu est probablement suivi cote Steam, pas par
    le jeu lui-meme). Par contre, les fichiers individuels Players/<uid>.sav
    contiennent un vrai historique (SaveData.RecordData) : notamment
    PalCaptureBonusCount (compteur de captures A VIE par espece, plafonne a
    5 -- exactement le bonus "5x la meme espece") et PaldeckUnlockFlag
    (quelles especes ont ete enregistrees au Paldex, donc capturees au
    moins une fois -- style completion Pokedex). On avait d'abord essaye
    TribeCaptureCount pour ce dernier chiffre, mais les valeurs etaient
    incoherentes avec species_bonus_count (un joueur avec 8 especes au
    bonus x5 avait un TribeCaptureCount de 24, alors qu'il faut au moins
    40 captures pour ca) -- PaldeckUnlockFlag, lui, est coherent
    (toujours >= species_bonus_count, ce qui est logiquement necessaire).

    Retourne {uid: {"species_bonus_count": N, "paldeck_count": N}}, en
    ignorant silencieusement les joueurs dont le fichier est illisible.
    """
    folder = _players_folder()
    if not folder:
        return {}

    from palsav_lite.gvas import GvasFile
    from palsav_lite.paltypes import PALWORLD_CUSTOM_PROPERTIES, PALWORLD_TYPE_HINTS

    results = {}
    try:
        transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
        transport.connect(username=SFTP_USER, password=SFTP_PASSWORD)
        sftp = paramiko.SFTPClient.from_transport(transport)
        for uid in uids:
            local_path = f"player_{uid}.sav"
            try:
                sftp.get(f"{folder}/{uid}.sav", local_path)
                with open(local_path, "rb") as f:
                    raw = decompress_sav(f.read())
                gvas = GvasFile.read(raw, PALWORLD_TYPE_HINTS, PALWORLD_CUSTOM_PROPERTIES)
                record_data = gvas.properties.get("SaveData", {}).get("value", {}).get("RecordData", {}).get("value", {})

                bonus_map = record_data.get("PalCaptureBonusCount", {}).get("value", [])
                species_bonus_count = sum(1 for e in bonus_map if _as_int(e.get("value"), 0) >= 5)

                paldeck_map = record_data.get("PaldeckUnlockFlag", {}).get("value", [])
                paldeck_count = sum(1 for e in paldeck_map if e.get("value") is True)

                results[uid] = {"species_bonus_count": species_bonus_count, "paldeck_count": paldeck_count}
            except Exception as e:
                print(f"[player_records] echec pour {uid} : {e}")
        sftp.close()
        transport.close()
    except Exception as e:
        print(f"[player_records] echec connexion SFTP : {e}")
    return results


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


def _as_int(value, default=0):
    return value if isinstance(value, (int, float)) else default


def _byte_prop_value(prop, default=0):
    """
    Level, Rank et les Talent_* sont serialises comme des ByteProperty :
    {"value": {"type": "None", "value": N}} -- un niveau d'imbrication de
    plus qu'une propriete scalaire classique ({"value": N}). Sans ce
    deuxieme deballage, on retombe systematiquement sur `default`.
    """
    if not isinstance(prop, dict):
        return default
    value = prop.get("value")
    if isinstance(value, dict):
        value = value.get("value")
    return _as_int(value, default)


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

    # Diagnostic temporaire : on cherche s'il existe quelque part un compteur
    # de kills/morts/degats -- aucune piste trouvee dans la documentation
    # disponible jusqu'ici, donc on regarde la structure reelle de la save.
    print(f"[parse_characters] cles racine gvas.properties : {sorted(gvas.properties.keys())}")
    print(f"[parse_characters] cles worldSaveData : {sorted(gvas.properties['worldSaveData']['value'].keys())}")

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
                "level": _byte_prop_value(params.get("Level"), 1),
                "building_count": online_info["building_count"] if online_info else None,
                "ping": online_info["ping"] if online_info else None,
                "online": online_info is not None,
                "playerId": uid,
            }
            continue

        owner_uid = _normalize_uid(params.get("OwnerPlayerUId", {}).get("value"))

        def talent(key):
            return _byte_prop_value(params.get(key), 0)

        passives_raw = params.get("PassiveSkillList", {}).get("value", {}).get("values", [])
        passive_ids = [p.get("value", p) if isinstance(p, dict) else p for p in passives_raw]

        char_id = params.get("CharacterID", {}).get("value", "???")
        pal_info = _lookup_pal(char_id)

        level = _byte_prop_value(params.get("Level"), 1)
        # Rank est stocke decale de +1 par rapport aux etoiles affichees en jeu
        # (verifie : Lullu stockee a 4 s'affiche avec 3 etoiles) -- mais c'est
        # bien la valeur BRUTE (condenser_rank) qu'attend la formule de stats.
        raw_rank = _byte_prop_value(params.get("Rank"), 1)
        talents = {
            "hp": talent("Talent_HP"),
            "melee": talent("Talent_Melee"),
            "shot": talent("Talent_Shot"),
            "defense": talent("Talent_Defense"),
        }
        is_awakened = params.get("bIsAwakening", {}).get("value", False)
        rank_hp = talent("Rank_HP")
        rank_attack = talent("Rank_Attack")
        rank_defense = talent("Rank_Defence")
        friendship_points = _byte_prop_value(params.get("FriendshipPoint"), 0)
        pal_passive_bonus = _passive_stat_bonus(passive_ids, _pal_elements(char_id))

        power_stats = _compute_pal_power_stats(
            char_id, level, talents,
            rank_hp=rank_hp,
            rank_attack=rank_attack,
            rank_defense=rank_defense,
            condenser_rank=raw_rank,
            friendship_points=friendship_points,
            is_awake=is_awakened,
            passive_bonus=pal_passive_bonus,
        )

        pals_raw.append((owner_uid, {
            "nickname": params.get("NickName", {}).get("value") or pal_info["name"],
            "species": char_id,
            "species_name": pal_info["name"],
            "icon": pal_info["icon"],
            "level": level,
            "rank": max(0, raw_rank - 1),
            "is_alpha": params.get("IsRarePal", {}).get("value", False),
            "is_awakened": is_awakened,
            "talents": talents,
            "power_stats": power_stats,
            "souls": rank_hp + rank_attack + rank_defense,
            "passives": [_lookup_passive(pid) for pid in passive_ids],
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

    players = sorted(players_by_uid.values(), key=lambda p: _as_int(p["level"]), reverse=True)
    return players, pals


def build_records(players, pals, player_records):
    """
    Le jeu ne garde pas de temps de jeu ni de compteur de morts/degats dans
    la sauvegarde (verifie a fond : ni dans Level.sav, ni dans les fichiers
    individuels Players/<uid>.sav -- probablement suivi cote Steam pour le
    temps de jeu, pas du tout pour les morts). "most_pals"/"strongest_team"
    restent donc des instantanes de l'equipe actuelle (pas un historique :
    un Pal libere/mort n'y apparait plus). "species_bonus"/"total_captures"
    par contre viennent de player_records (RecordData) et sont de vrais
    totaux a vie, independants de ce qui est possede aujourd'hui.
    """
    by_owner = {}
    for pal in pals:
        owner = pal.get("owner", "inconnu")
        entry = by_owner.setdefault(owner, {"owner": owner, "pal_count": 0, "total_power": 0})
        entry["pal_count"] += 1
        ps = pal.get("power_stats")
        if ps:
            entry["total_power"] += ps["hp"] + ps["atk"] + ps["def"]

    most_pals = sorted(by_owner.values(), key=lambda e: e["pal_count"], reverse=True)
    strongest_team = sorted(by_owner.values(), key=lambda e: e["total_power"], reverse=True)

    captures = []
    for p in players:
        rec = player_records.get(p["playerId"])
        if rec:
            captures.append({"owner": p["name"], **rec})
    species_bonus = sorted(captures, key=lambda e: e["species_bonus_count"], reverse=True)
    paldeck = sorted(captures, key=lambda e: e["paldeck_count"], reverse=True)

    return {
        "most_pals": [{"owner": e["owner"], "pal_count": e["pal_count"]} for e in most_pals],
        "strongest_team": [{"owner": e["owner"], "total_power": e["total_power"]} for e in strongest_team],
        "species_bonus": [{"owner": e["owner"], "species_bonus_count": e["species_bonus_count"]} for e in species_bonus],
        "paldeck": [{"owner": e["owner"], "paldeck_count": e["paldeck_count"]} for e in paldeck],
    }


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

    player_records = {}
    if players:
        try:
            player_records = fetch_player_records([p["playerId"] for p in players])
        except Exception as e:
            print(f"[player_records] erreur inattendue : {e}")

    data = {
        "generated_at": datetime.datetime.now().astimezone().isoformat(),
        "server": server,
        "players": players,
        "pals": pals,
        "records": build_records(players, pals, player_records) if pals else None,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write("window.PALWORLD_DATA = ")
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write(";\n")

    print(f"OK -- {len(players)} joueurs, {len(pals)} pals -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
