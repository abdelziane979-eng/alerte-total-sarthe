#!/usr/bin/env python3
"""
Alerte TotalEnergies < 2€/L — Sarthe (72)
+ page web + recap quotidien
"""

import requests
import json
import math
import os
from datetime import datetime
from zoneinfo import ZoneInfo

# ============================================================
# CONFIGURATION
# ============================================================

NTFY_TOPIC = "total72-lemans-z2a9n4k7"
SEUIL_PRIX = 2.00
DISTANCE_MAX_METRES = 150
FICHIER_MEMOIRE = "alertes_envoyees.json"
FICHIER_CACHE = "stations_total_cache.json"
FICHIER_STOCKS = "etats_stocks.json"
FICHIER_RECAP = "recap_dernier.json"
DOSSIER_PUBLIC = "public"
HEURE_RECAP = 8  # 8h heure de Paris

# ============================================================


def charger_json(fichier, defaut):
    if os.path.exists(fichier):
        try:
            with open(fichier, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return defaut
    return defaut


def sauvegarder_json(fichier, data):
    with open(fichier, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def envoyer_notification(titre, message, priorite="max"):
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={
                "Title": titre.encode("utf-8"),
                "Priority": "max",
                "Tags": "fuel,rotating_light,warning",
                "X-Priority": "1",
            },
            timeout=10,
        )
        print(f"[{datetime.now():%H:%M:%S}] Notification envoyee : {titre}")
    except Exception as e:
        print(f"[ERREUR] Envoi notification : {e}")


def distance_metres(lat1, lon1, lat2, lon2):
    dlat = (lat1 - lat2) * 111000
    dlon = (lon1 - lon2) * 111000 * math.cos(math.radians(lat1))
    return math.sqrt(dlat**2 + dlon**2)


def recuperer_positions_total_sarthe():
    cache = charger_json(FICHIER_CACHE, None)
    if cache and isinstance(cache, dict):
        positions = cache.get("positions", [])
        if positions:
            print(f"   Cache trouve ({len(positions)} stations)")
            return positions

    print("   Interrogation d'Overpass...")
    serveurs = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.private.coffee/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    ]
    query = """
    [out:json][timeout:60];
    (
      node["amenity"="fuel"]["brand"~"Total",i](47.70,-0.70,48.50,1.00);
      way["amenity"="fuel"]["brand"~"Total",i](47.70,-0.70,48.50,1.00);
    );
    out center;
    """
    for serveur in serveurs:
        try:
            r = requests.get(
                serveur,
                params={"data": query},
                headers={"User-Agent": "AlerteTotalSarthe/1.0"},
                timeout=60,
            )
            r.raise_for_status()
            data = r.json()
            positions = []
            for el in data.get("elements", []):
                lat = el.get("lat") or (el.get("center") or {}).get("lat")
                lon = el.get("lon") or (el.get("center") or {}).get("lon")
                if lat is None or lon is None:
                    continue
                tags = el.get("tags", {})
                nom = tags.get("name") or tags.get("brand") or tags.get("operator") or "Total"
                positions.append({"lat": float(lat), "lon": float(lon), "nom": nom})
            if positions:
                print(f"      {len(positions)} stations recues")
                sauvegarder_json(FICHIER_CACHE, {
                    "date": datetime.now().isoformat(),
                    "positions": positions,
                })
                return positions
        except Exception as e:
            print(f"      Echec : {type(e).__name__}")
            continue

    print("[ERREUR] Aucun serveur Overpass et pas de cache.")
    return []


def recuperer_stations_sarthe():
    url = (
        "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/"
        "prix-des-carburants-en-france-flux-instantane-v2/records"
        "?where=startswith(cp,%2272%22)&limit=100"
    )
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.json().get("results", [])
    except Exception as e:
        print(f"[ERREUR] API gouvernementale : {e}")
        return []


def etat_carburant(station, prefix):
    rupture = station.get(f"{prefix}_rupture_type")
    prix = station.get(f"{prefix}_prix")
    if rupture == "temporaire":
        return "temp"
    if rupture == "definitive":
        return "def"
    if prix is not None:
        return "dispo"
    return None


def verifier_prix(station):
    resultats = []
    for champ_prix, champ_rupture, nom in [
        ("sp95_prix", "sp95_rupture_type", "SP95"),
        ("e10_prix", "e10_rupture_type", "E10"),
        ("sp98_prix", "sp98_rupture_type", "SP98"),
        ("gazole_prix", "gazole_rupture_type", "Gazole"),
    ]:
        prix = station.get(champ_prix)
        rupture = station.get(champ_rupture)
        if rupture in ("temporaire", "definitive"):
            continue
        if prix is not None:
            try:
                p = float(prix)
                if p < SEUIL_PRIX:
                    resultats.append((nom, p))
            except (ValueError, TypeError):
                pass
    return resultats


def generer_page_html(stations_sous_seuil, chemin="public/index.html"):
    os.makedirs(os.path.dirname(chemin), exist_ok=True)

    paris = datetime.now(ZoneInfo("Europe/Paris"))
    date_heure = paris.strftime("%d/%m/%Y a %Hh%M")

    items = sorted(stations_sous_seuil.values(), key=lambda s: s.get("ville", "ZZZ"))

    html_cards = []
    for s in items:
        carburants_html = ""
        for c, p in s["carburants_sous_seuil"]:
            carburants_html += f'<div class="carburant">{c} : <span class="prix">{p:.3f} EUR/L</span></div>'

        ruptures_html = ""
        if s.get("ruptures"):
            ruptures_html = f'<div class="rupture">Rupture : {", ".join(s["ruptures"])}</div>'

        html_cards.append(f'''
        <div class="station">
            <div class="ville">{s.get("ville", "?")} <span class="cp">({s.get("cp", "?")})</span></div>
            <div class="adresse">{s.get("adresse", "?")}</div>
            {carburants_html}
            {ruptures_html}
        </div>''')

    html = f'''<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Alerte Total Sarthe</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif;
         margin: 0; padding: 16px; background: #f0f2f5; color: #222; }}
  header {{ background: linear-gradient(135deg, #c00, #900);
            color: white; padding: 20px; border-radius: 12px;
            margin-bottom: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
  h1 {{ margin: 0; font-size: 1.4em; }}
  .compteur {{ margin-top: 8px; font-size: 1.1em; opacity: 0.95; }}
  .station {{ background: white; padding: 14px; margin-bottom: 10px;
              border-radius: 10px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }}
  .ville {{ font-weight: bold; font-size: 1.1em; color: #c00; }}
  .cp {{ font-weight: normal; color: #888; font-size: 0.85em; }}
  .adresse {{ color: #555; font-size: 0.9em; margin: 4px 0 8px 0; }}
  .carburant {{ font-size: 0.95em; padding: 2px 0; }}
  .prix {{ color: #090; font-weight: bold; }}
  .rupture {{ color: #c00; font-size: 0.85em; margin-top: 6px;
              font-style: italic; }}
  .date {{ text-align: center; color: #888; font-size: 0.85em;
           margin: 20px 0; }}
  .vide {{ background: white; padding: 30px; text-align: center;
           border-radius: 10px; color: #666; }}
</style>
</head>
<body>
<header>
  <h1>TotalEnergies Sarthe &lt; 2 EUR/L</h1>
  <div class="compteur">{len(items)} station(s) en ce moment</div>
</header>
{"".join(html_cards) if items else '<div class="vide">Aucune station Total sous 2 EUR/L actuellement.</div>'}
<div class="date">Derniere mise a jour : {date_heure}</div>
</body>
</html>'''

    with open(chemin, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"   Page HTML generee ({len(items)} stations)")


def envoyer_recap(stations_sous_seuil):
    if not stations_sous_seuil:
        message = "Aucune station Total sous 2 EUR/L en Sarthe aujourd'hui."
    else:
        lignes = []
        for s in sorted(stations_sous_seuil.values(), key=lambda x: x.get("ville", "ZZZ")):
            bloc = [f"{c} : {p:.3f} EUR/L" for c, p in s["carburants_sous_seuil"]]
            bloc.append(f"   {s.get('adresse', '?')}, {s.get('cp', '?')} {s.get('ville', '?')}")
            if s.get("ruptures"):
                bloc.append(f"   Rupture : {', '.join(s['ruptures'])}")
            lignes.append("\n".join(bloc))
        message = "\n\n".join(lignes)

    titre = f"Recap matin : {len(stations_sous_seuil)} station(s) Total < 2 EUR/L"
    envoyer_notification(titre, message)


def main():
    print(f"=== Alerte TotalEnergies < {SEUIL_PRIX} EUR/L - Sarthe ===")
    print(f"Sujet ntfy : {NTFY_TOPIC}\n")

    paris = datetime.now(ZoneInfo("Europe/Paris"))
    date_aujourdhui = paris.strftime("%Y-%m-%d")

    memoire = charger_json(FICHIER_MEMOIRE, {})
    stocks_precedents = charger_json(FICHIER_STOCKS, {})
    recap_dernier = charger_json(FICHIER_RECAP, {})

    positions_total = recuperer_positions_total_sarthe()
    print(f"   {len(positions_total)} stations TotalEnergies")
    if not positions_total:
        return

    stations = recuperer_stations_sarthe()
    print(f"   {len(stations)} stations dans la Sarthe\n")

    stations_total = {}
    for station in stations:
        geom = station.get("geom") or {}
        lat = geom.get("lat")
        lon = geom.get("lon")
        if lat is None or lon is None:
            continue

        match = None
        for p in positions_total:
            if distance_metres(lat, lon, p["lat"], p["lon"]) < DISTANCE_MAX_METRES:
                match = p
                break
        if not match:
            continue

        sid = str(station.get("id", f"{lat}_{lon}"))
        etats = {}
        for prefix in ["sp95", "e10", "sp98", "gazole"]:
            etats[prefix] = etat_carburant(station, prefix)

        stations_total[sid] = {
            "ville": station.get("ville", "?"),
            "adresse": station.get("adresse", "?"),
            "cp": station.get("cp", "?"),
            "etats": etats,
            "carburants_sous_seuil": verifier_prix(station),
        }

    stations_sous_seuil = {
        sid: info for sid, info in stations_total.items()
        if info["carburants_sous_seuil"]
    }

    print("-> Generation de la page web...")
    generer_page_html(stations_sous_seuil)

    retours = []
    for sid, info in stations_total.items():
        etats_avant = stocks_precedents.get(sid, {}).get("etats", {})
        etats_maintenant = info["etats"]
        for carburant in ["sp95", "e10", "sp98", "gazole"]:
            avant = etats_avant.get(carburant)
            maintenant = etats_maintenant.get(carburant)
            if avant in ("temp", "def") and maintenant == "dispo":
                retours.append({
                    "ville": info["ville"],
                    "adresse": info["adresse"],
                    "cp": info["cp"],
                    "carburant": carburant.upper(),
                })

    nouvelles = [(sid, info) for sid, info in stations_total.items()
                 if info["carburants_sous_seuil"] and sid not in memoire]

    for sid in [s for s in memoire if s not in stations_total]:
        del memoire[sid]

    if nouvelles:
        lignes = []
        for sid, info in nouvelles:
            bloc = [f"{c} a {p:.3f} EUR/L" for c, p in info["carburants_sous_seuil"]]
            bloc.append(f"   {info['adresse']}, {info['cp']} {info['ville']}")
            ruptures = []
            for k in ["sp95", "e10", "sp98", "gazole"]:
                if info["etats"].get(k) == "temp":
                    ruptures.append(f"{k.upper()} (temp.)")
                elif info["etats"].get(k) == "def":
                    ruptures.append(f"{k.upper()} (def.)")
            if ruptures:
                bloc.append(f"   Rupture : {', '.join(ruptures)}")
            lignes.append("\n".join(bloc))
            memoire[sid] = {
                "ville": info["ville"],
                "adresse": info["adresse"],
                "derniere_alerte": datetime.now().isoformat(),
            }

        titre = f"{len(nouvelles)} nouvelle(s) Total < {SEUIL_PRIX} EUR/L"
        message = "\n\n".join(lignes)
        print(f"\n{titre}\n{message}\n")
        envoyer_notification(titre, message)

    if retours:
        lignes = []
        for r in retours:
            lignes.append(
                f"{r['carburant']} de nouveau disponible\n"
                f"   {r['adresse']}, {r['cp']} {r['ville']}"
            )
        titre = f"{len(retours)} retour(s) en stock"
        message = "\n\n".join(lignes)
        print(f"\n{titre}\n{message}\n")
        envoyer_notification(titre, message)

    derniere_date_recap = recap_dernier.get("date", "")
    if (paris.hour >= HEURE_RECAP and date_aujourdhui != derniere_date_recap):
        print(f"\n-> Envoi du recap quotidien (date : {date_aujourdhui})")
        envoyer_recap(stations_sous_seuil)
        recap_dernier["date"] = date_aujourdhui
        recap_dernier["heure_envoi"] = paris.isoformat()
        sauvegarder_json(FICHIER_RECAP, recap_dernier)

    if not nouvelles and not retours:
        print("\nAucune nouvelle alerte.")

    sauvegarder_json(FICHIER_MEMOIRE, memoire)
    sauvegarder_json(FICHIER_STOCKS, {
        sid: {"etats": info["etats"], "adresse": info["adresse"], "ville": info["ville"]}
        for sid, info in stations_total.items()
    })
    print(f"\nMemoire prix : {len(memoire)} station(s)")
    print(f"Memoire stocks : {len(stations_total)} station(s)")


if __name__ == "__main__":
    main()