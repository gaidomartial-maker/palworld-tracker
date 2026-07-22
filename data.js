// data.js
// ---------------------------------------------------------------
// Ce fichier est régénéré automatiquement par generate_data.py.
// Pour l'instant il contient des données DE DÉMONSTRATION pour que
// la page s'affiche correctement avant le premier vrai export.
// ---------------------------------------------------------------
window.PALWORLD_DATA = {
  "generated_at": "2026-07-21T17:12:00+02:00",
  "server": {
    "name": "Serveur Palworld DES COP1",
    "description": "Serv Palworld herbergé par Martial",
    "address": "monserveur.helloserv.net:7784",
    "online": true,
    "current_players": 4,
    "max_players": 15,
    "version": "v1.12.0"
  },
  "players": [
    { "name": "1PrinceBoiteux", "level": 42, "building_count": 214, "ping": 18, "online": true },
    { "name": "ChocoRaptor",     "level": 38, "building_count": 97,  "ping": 34, "online": true },
    { "name": "MamieFusion",     "level": 35, "building_count": 156, "ping": 27, "online": false },
    { "name": "Kevin_du_78",     "level": 29, "building_count": 42,  "ping": 51, "online": true },
    { "name": "NocturnePal",     "level": 22, "building_count": 18,  "ping": 63, "online": false }
  ],
  "pals": [
    { "nickname": "Grillade",  "species": "Foxparks",   "owner": "1PrinceBoiteux", "level": 48, "rank": 4, "is_alpha": false,
      "talents": { "hp": 92, "melee": 88, "shot": 70, "defense": 76 },
      "passives": ["Legend", "Musclehead"] },
    { "nickname": "Big Moss",  "species": "Mossanda",    "owner": "ChocoRaptor",    "level": 45, "rank": 3, "is_alpha": false,
      "talents": { "hp": 100, "melee": 65, "shot": 40, "defense": 88 },
      "passives": ["Motivational Leader"] },
    { "nickname": "Toubib",    "species": "Chikipi",     "owner": "MamieFusion",    "level": 12, "rank": 2, "is_alpha": false,
      "talents": { "hp": 55, "melee": 20, "shot": 15, "defense": 30 },
      "passives": [] },
    { "nickname": "Le Boss",   "species": "Jetragon",    "owner": "1PrinceBoiteux", "level": 50, "rank": 4, "is_alpha": true,
      "talents": { "hp": 100, "melee": 100, "shot": 95, "defense": 90 },
      "passives": ["Legend", "Ferocious", "Runner"] },
    { "nickname": "Petit Pote","species": "Lamball",     "owner": "Kevin_du_78",    "level": 8,  "rank": 1, "is_alpha": false,
      "talents": { "hp": 40, "melee": 22, "shot": 10, "defense": 25 },
      "passives": [] }
  ],
  // Ce bloc sera rempli plus tard si un tracker d'évènements
  // (kills / captures en temps réel) est mis en place — voir README.
  "records": null
};
