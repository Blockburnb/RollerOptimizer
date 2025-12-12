#!/usr/bin/env python3
"""
Génère une page HTML ergonomique (Dashboard) pour le layout RollerCoin.
Affiche les miners, racks, stats, et répartit le tout par Room.
"""
import argparse
import json
import os
import re
import math
import base64
from html import escape

# Configuration visuelle
UNIT_PX = 60  # Largeur d'une unité (1 cellule) en pixels
FLOOR_HEIGHT_PX = 55 # Hauteur d'un étage
RACK_MARGIN = 10

def format_power(power_raw):
    """Formate la puissance en Th/s, Ph/s, Eh/s, Zh/s."""
    try:
        p = float(power_raw)
    except:
        return "0 Gh/s"
    
    units = ["Gh/s", "Th/s", "Ph/s", "Eh/s", "Zh/s"]
    unit_idx = 0
    while p >= 1000 and unit_idx < len(units) - 1:
        p /= 1000.0
        unit_idx += 1
    return f"{p:.2f} {units[unit_idx]}"

def format_bonus(bonus_raw):
    """Formate le bonus (ex: 4500 -> 45%)."""
    try:
        val = float(bonus_raw) / 100.0
    except:
        return "0%"
    
    # Si c'est un entier (ex: 10.0), on affiche 10%, sinon 10.5%
    if val.is_integer():
        return f"{int(val)}%"
    return f"{val:.2f}%".replace('.', ',')

def slugify(s: str) -> str:
    if not s:
        return ''
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", '_', s)
    s = s.strip('_')
    return s

def pick_icon_path(icons_dir, miner):
    """Cherche l'icône du mineur (GIF)"""
    # Priorité 1: filename explicite
    filename_token = miner.get('filename') if isinstance(miner.get('filename'), str) else None
    candidates = []
    if filename_token:
        candidates.append(filename_token)
    
    # Priorité 2: Nom du mineur
    name = miner.get('name')
    if isinstance(name, dict):
        name_val = name.get('en') or next(iter(name.values()), '')
    else:
        name_val = name or ''
    
    candidates.append(name_val)
    candidates.append(slugify(name_val))
    
    # Nettoyage des candidats
    candidates = [slugify(c) for c in candidates if c]
    
    for c in candidates:
        p = os.path.join(icons_dir, f"{c}.gif")
        if os.path.exists(p):
            return os.path.relpath(p).replace('\\', '/')
            
    # Fallback générique
    fallback = os.path.join(os.path.dirname(__file__), 'har_icon.gif')
    if os.path.exists(fallback):
        return os.path.relpath(fallback).replace('\\', '/')
    return None

def resolve_rack_percent(room_config, rack):
    """Retourne le pourcentage du rack en centi-percent (int) si possible, sinon 0.
    Recherche dans le dict `rack` lui-même puis dans `room_config` (data -> racks / rack_info).
    """
    # Priorité: champ dans le rack lui-même
    if isinstance(rack, dict):
        for k in ('percent', 'bonus', 'rack_percent'):
            if k in rack and isinstance(rack.get(k), (int, float)):
                try:
                    return int(rack.get(k))
                except Exception:
                    pass
    # Ensuite recherche dans room_config si fourni
    if not room_config:
        return 0
    try:
        data = room_config.get('data', room_config) if isinstance(room_config, dict) else {}
        # chercher dans listes plausibles
        for key in ('racks', 'rack_templates', 'rack_info', 'racks_list', 'items'):
            if key in data and isinstance(data[key], list):
                for entry in data[key]:
                    if not isinstance(entry, dict):
                        continue
                    # match by id or by name
                    if rack.get('_id') and entry.get('_id') == rack.get('_id'):
                        for k in ('percent', 'bonus', 'rack_percent'):
                            if k in entry and isinstance(entry.get(k), (int, float)):
                                return int(entry.get(k))
                    # name matching (entry name can be dict or string)
                    rname = rack.get('name')
                    if rname:
                        # normalize both to string
                        try:
                            en = entry.get('name')
                            if isinstance(en, dict):
                                en_val = en.get('en') or next(iter(en.values()), '')
                            else:
                                en_val = str(en or '')
                            # compare lowercased
                            if isinstance(rname, dict):
                                rname_val = rname.get('en') or next(iter(rname.values()), '')
                            else:
                                rname_val = str(rname)
                            if en_val and rname_val and en_val.lower() == rname_val.lower():
                                for k in ('percent', 'bonus', 'rack_percent'):
                                    if k in entry and isinstance(entry.get(k), (int, float)):
                                        return int(entry.get(k))
                        except Exception:
                            pass
        # deep scan fallback: some configs nest racks under rooms
        def scan(o):
            if isinstance(o, dict):
                for k,v in o.items():
                    if isinstance(v, (dict, list)):
                        res = scan(v)
                        if res is not None:
                            return res
                # check this dict itself for percent/name
                for k in ('percent','bonus','rack_percent'):
                    if k in o and isinstance(o.get(k), (int,float)):
                        # optional name match
                        en = o.get('name')
                        if en:
                            try:
                                if isinstance(en, dict):
                                    en_val = en.get('en') or next(iter(en.values()), '')
                                else:
                                    en_val = str(en or '')
                                rname = rack.get('name')
                                if rname:
                                    if isinstance(rname, dict):
                                        rname_val = rname.get('en') or next(iter(rname.values()), '')
                                    else:
                                        rname_val = str(rname)
                                    if en_val and rname_val and en_val.lower() == rname_val.lower():
                                        return int(o.get(k))
                            except Exception:
                                pass
                return None
            elif isinstance(o, list):
                for i in o:
                    res = scan(i)
                    if res is not None:
                        return res
            return None
        res = scan(data)
        if isinstance(res, int):
            return res
    except Exception:
        pass
    return 0

def extract_gifs_from_har(har_path, icons_dir):
    """Extrait tous les .gif contenus dans un fichier HAR et les écrit dans icons_dir.
    Fonction robuste: cherche les réponses avec mimeType image/gif ou URL finissant par .gif.
    Supporte le contenu encodé en base64 (response.content.encoding == 'base64').
    """
    if not os.path.exists(har_path):
        print(f"ℹ️  HAR introuvable: {har_path} — aucune extraction effectuée.")
        return

    try:
        with open(har_path, 'r', encoding='utf-8') as fh:
            har = json.load(fh)
    except Exception as e:
        print(f"⚠️  Impossible de lire le HAR: {e}")
        return

    entries = har.get('log', {}).get('entries', [])
    os.makedirs(icons_dir, exist_ok=True)
    found = 0
    skipped = 0

    for i, entry in enumerate(entries):
        try:
            req = entry.get('request', {})
            resp = entry.get('response', {})
            url = req.get('url', '')
            cont = resp.get('content', {})
            mime = cont.get('mimeType', '') or ''

            is_gif = mime.startswith('image/gif') or url.lower().split('?')[0].endswith('.gif')
            if not is_gif:
                continue

            filename = os.path.basename(url.split('?')[0]) or f'icon_{i}.gif'
            filename = filename if filename.lower().endswith('.gif') else filename + '.gif'
            out_path = os.path.join(icons_dir, filename)

            # Si le fichier existe déjà, on skip pour éviter d'écraser
            if os.path.exists(out_path):
                skipped += 1
                continue

            text = cont.get('text')
            encoding = cont.get('encoding')
            if text is None:
                # Pas de contenu in-har, on ne peut pas récupérer l'image
                skipped += 1
                continue

            if encoding == 'base64':
                try:
                    data = base64.b64decode(text)
                except Exception:
                    # Parfois le HAR contient des données mal formées
                    data = text.encode('utf-8', errors='ignore')
            else:
                # Texte brut -> écrire en bytes en supposant UTF-8 ou iso-8859-1
                try:
                    data = text.encode('utf-8')
                except Exception:
                    data = text.encode('iso-8859-1', errors='ignore')

            with open(out_path, 'wb') as of:
                of.write(data)
            found += 1
        except Exception:
            skipped += 1
            continue

    print(f"✅ Extraction GIF HAR: {found} fichiers écrits, {skipped} ignorés (déjà présents ou erreur).")

def generate_html(layout, room_config, icons_dir, out_path):
    racks_layout = layout.get('racks', [])
    
    # Récupération des infos globales
    best = layout.get('best_candidate', {})
    total_power = format_power(best.get('final_power', 0))
    total_bonus = format_bonus(best.get('miner_bonus_percent', 0))
    generated_date = layout.get('generated_at', 'Inconnue')

    # Calculate raw power and estimated rack bonuses for the whole layout
    total_raw_units = 0.0
    total_rack_bonus_power = 0.0
    # store per-rack computed percent for display
    for rk in racks_layout:
        miners = rk.get('miners', []) or []
        raw = 0.0
        for m in miners:
            try:
                raw += float(m.get('power', 0) or 0)
            except Exception:
                pass
        # resolve percent (centi-percent) and compute bonus power
        r_percent = resolve_rack_percent(room_config, rk) or 0
        rk['_computed_raw'] = raw
        rk['_computed_percent'] = int(r_percent)
        try:
            total_raw_units += raw
            total_rack_bonus_power += raw * (r_percent / 10000.0)
        except Exception:
            pass

    # Format totals for display
    total_raw_fmt = format_power(total_raw_units)
    total_rack_bonus_fmt = format_power(total_rack_bonus_power)

    # Tentative de reconstruction des Rooms basée sur room_config
    rooms_structure = []
    
    if room_config and 'rooms' in room_config.get('data', {}):
        # Utiliser la config réelle
        rc_data = room_config['data']['rooms']
        for room in rc_data:
            r_info = room.get('room_info', {})
            r_id = room.get('_id', 'Unknown')
            rooms_structure.append({
                "name": f"Room {len(rooms_structure) + 1}",
                "racks": [] 
            })
    else:
        rooms_structure.append({"name": "Main Room", "racks": []})

    # HTML Header & CSS
    parts = []
    parts.append('<!doctype html>')
    parts.append('<html lang="fr"><head><meta charset="utf-8">')
    parts.append(f'<title>RollerOptimizer Dashboard - {generated_date}</title>')
    parts.append('<meta name="viewport" content="width=device-width,initial-scale=1">')
    parts.append('<link href="https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;700&display=swap" rel="stylesheet">')
    parts.append('<style>')
    parts.append('''
        :root {
            --bg-color: #1a1a2e;
            --card-bg: #16213e;
            --accent-color: #0f3460;
            --text-color: #e94560;
            --text-light: #f1f1f1;
            --rack-border: #444;
            --rack-bg: #2a2a2a;
            --floor-border: #555;
            --bonus-color: #ffd700;
            --power-color: #00d4ff;
        }
        body { font-family: 'Roboto', sans-serif; background: var(--bg-color); color: var(--text-light); margin: 0; padding: 20px; }
        
        /* Header Stats */
        .stats-bar {
            display: flex; gap: 20px; background: var(--card-bg); padding: 15px; border-radius: 8px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.3); margin-bottom: 20px; flex-wrap: wrap; align-items: center;
        }
        .stat-item { display: flex; flex-direction: column; }
        .stat-label { font-size: 0.8em; color: #888; text-transform: uppercase; letter-spacing: 1px; }
        .stat-value { font-size: 1.5em; font-weight: bold; color: var(--text-light); }
        .highlight { color: var(--text-color); }

        /* Layout Grid */
        .room-container {
            display: flex;
            flex-wrap: wrap;
            gap: 20px;
            justify-content: flex-start;
        }

        /* Rack Design */
        .rack {
            background: var(--rack-bg);
            border: 2px solid var(--rack-border);
            border-radius: 6px;
            padding: 5px;
            display: flex;
            flex-direction: column;
            width: fit-content;
            box-shadow: 0 4px 10px rgba(0,0,0,0.5);
            position: relative;
            transition: transform 0.2s;
            /* Allow tooltips to overflow the rack and ensure stacking order */
            overflow: visible;
            z-index: 1;
        }
        .rack:hover { transform: translateY(-5px); border-color: var(--text-color); z-index: 1000; }
        
        .rack-header {
            text-align: center; font-size: 0.85em; margin-bottom: 4px; color: #aaa;
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 140px;
        }

        .floor {
            height: 55px; /* FLOOR_HEIGHT_PX */
            width: 124px; /* 2 units * UNIT_PX + margins */
            border-bottom: 2px solid var(--floor-border);
            position: relative;
            background: rgba(255,255,255,0.02);
        }
        .floor:last-child { border-bottom: none; }

        /* Miner Design */
        .miner {
            position: absolute;
            bottom: 2px;
            height: 50px;
            border-radius: 4px;
            overflow: visible; /* Allow hover tooltip to show */
            cursor: pointer;
            transition: filter 0.2s;
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 0; /* Ensure miner itself doesn't outrank the tooltip */
        }
        .miner:hover { filter: brightness(1.2); }
        
        .miner img {
            max-height: 100%;
            max-width: 100%;
            object-fit: contain;
            display: block;
        }

        /* Badges on Miner */
        .badge {
            position: absolute;
            font-size: 9px;
            font-weight: bold;
            padding: 1px 3px;
            border-radius: 3px;
            /* keep badges under the tooltip */
            z-index: 1;
            pointer-events: none; /* don't block tooltip hover */
            text-shadow: 1px 1px 0 #000;
            transition: opacity 0.18s ease, transform 0.18s ease;
        }
        .badge-lvl { top: -2px; left: -2px; background: #4caf50; color: white; }
        .badge-bonus { top: -2px; right: -2px; background: var(--bonus-color); color: black; }

        /* When hovering a miner, fade/move badges so they don't cover the tooltip */
        .miner:hover .badge {
            opacity: 0.12;
            transform: translateY(-6px) scale(0.95);
        }

        /* Tooltip (Custom Hover Card) */
        .miner .tooltip {
            visibility: hidden;
            width: 180px;
            background-color: rgba(0, 0, 0, 0.95);
            color: #fff;
            text-align: left;
            border-radius: 6px;
            padding: 10px;
            position: absolute;
            /* Very high z-index to be above all other elements */
            z-index: 2147483647 !important; /* Max safe z-index to ensure top layering */
            bottom: 110%; /* Place above */
            left: 50%;
            transform: translateX(-50%);
            opacity: 0;
            transition: opacity 0.3s;
            border: 1px solid var(--text-color);
            box-shadow: 0 0 10px var(--text-color);
            pointer-events: auto; /* allow hover interaction */
            will-change: transform, opacity; /* hint to browser for stacking */
        }
        
        .miner:hover .tooltip { visibility: visible; opacity: 1; }

        /* Legend */
        .legend { margin-top: 30px; padding: 15px; background: var(--card-bg); border-radius: 8px; }
        .legend h3 { margin-top: 0; }
        .legend ul { list-style: none; padding: 0; }
        .legend li { padding: 5px 0; border-bottom: 1px solid #333; }

    ''')
    parts.append('</style></head><body>')

    # Top Stats Bar (ajout Raw power et Rack bonus)
    parts.append(f'''
    <div class="stats-bar">
        <div class="stat-item">
            <span class="stat-label">Date Génération</span>
            <span class="stat-value" style="font-size:1em">{generated_date.split('.')[0]}</span>
        </div>
        <div class="stat-item">
            <span class="stat-label">Puissance Totale</span>
            <span class="stat-value highlight">{total_power}</span>
        </div>
        <div class="stat-item">
            <span class="stat-label">Puissance brute (miners)</span>
            <span class="stat-value highlight">{total_raw_fmt}</span>
        </div>
        <div class="stat-item">
            <span class="stat-label">Bonus racks (est.)</span>
            <span class="stat-value" style="color:var(--bonus-color)">{total_rack_bonus_fmt}</span>
        </div>
        <div class="stat-item">
            <span class="stat-label">Bonus Total (miners)</span>
            <span class="stat-value" style="color:var(--bonus-color)">{total_bonus}</span>
        </div>
        <div class="stat-item">
            <span class="stat-label">Racks utilisés</span>
            <span class="stat-value">{len(racks_layout)}</span>
        </div>
    </div>
    ''')

    parts.append('<h2>Configuration Optimale</h2>')
    parts.append('<div class="room-container">')

    overflow_miners = []

    # Boucle sur les racks
    for i, rack in enumerate(racks_layout):
        rack_name = rack.get('name', f'Rack #{i+1}')
        height = int(rack.get('height', 4))
        
        parts.append(f'<div class="rack">')
        parts.append(f'<div class="rack-header" title="{escape(rack_name)}">{escape(rack_name)}</div>')
        
        floors_capacity = [2] * height # 2 slots par étage
        floors_html = [""] * height # Contenu HTML par étage
        
        miners = rack.get('miners', [])
        
        current_floor = height - 1
        
        for m in miners:
            m_width = int(m.get('width', 1))
            m_name = m.get('name', 'Unknown')
            if isinstance(m_name, dict): m_name = m_name.get('en', 'Unknown')
            
            placed = False
            for f_idx in range(height):
                if floors_capacity[f_idx] >= m_width:
                    left_pos = (2 - floors_capacity[f_idx]) * UNIT_PX + 2
                    
                    icon_path = pick_icon_path(icons_dir, m)
                    
                    p_fmt = format_power(m.get('power', 0))
                    b_fmt = format_bonus(m.get('bonus_percent', 0))
                    lvl = m.get('level', 0)
                    
                    width_px = (m_width * UNIT_PX) - 4
                    img_tag = f'<img src="{icon_path}" alt="icon">' if icon_path else '<span style="font-size:10px">No Img</span>'
                    
                    tooltip = f'''
                    <div class="tooltip">
                        <h4>{escape(m_name)}</h4>
                        <div>Niveau: {lvl}</div>
                        <div>Puissance: <span class="val-power">{p_fmt}</span></div>
                        <div>Bonus: <span class="val-bonus">{b_fmt}</span></div>
                    </div>
                    '''
                    
                    badges = f'<span class="badge badge-lvl">L{lvl}</span>'
                    if float(m.get('bonus_percent',0)) > 0:
                        badges += f'<span class="badge badge-bonus">{b_fmt}</span>'

                    div_miner = f'''
                    <div class="miner" style="width:{width_px}px; left:{left_pos}px;">
                        {img_tag}
                        {badges}
                        {tooltip}
                    </div>
                    '''
                    
                    floors_html[f_idx] += div_miner
                    floors_capacity[f_idx] -= m_width
                    placed = True
                    break
            
            if not placed:
                overflow_miners.append(m)

        for f_html in floors_html:
            parts.append(f'<div class="floor">{f_html}</div>')
            
        parts.append('</div>') # End Rack

    parts.append('</div>') # End Room Container

    if overflow_miners:
        parts.append('<div class="legend">')
        parts.append('<h3>⚠️ Mineurs non placés (Overflow)</h3><ul>')
        for om in overflow_miners:
            n = om.get('name', 'Unknown')
            if isinstance(n, dict): n = n.get('en')
            p = format_power(om.get('power', 0))
            parts.append(f'<li>{escape(str(n))} - {p}</li>')
        parts.append('</ul></div>')

    parts.append('</body></html>')

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(parts))
    
    print(f"✅ Dashboard généré avec succès : {out_path}")
    
    try:
        if hasattr(os, 'startfile'):
            os.startfile(out_path)
        else:
            import webbrowser
            webbrowser.open('file://' + os.path.abspath(out_path))
    except:
        pass

def main():
    p = argparse.ArgumentParser(description="Générateur Dashboard RollerCoin")
    p.add_argument('--layout', default='room_layout_optimal.json', help="Fichier JSON du layout optimal")
    p.add_argument('--config', default='room_config.json', help="Fichier JSON de config des rooms (optionnel)")
    p.add_argument('--icons', default='icons', help="Dossier des images")
    p.add_argument('--out', default='room_layout_visual.html', help="Fichier HTML de sortie")
    p.add_argument('--har', default='rollercoin.com.har', help="Fichier .har pour extraire les icônes (optionnel)")
    args = p.parse_args()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    layout_path = os.path.join(base_dir, args.layout)
    config_path = os.path.join(base_dir, args.config)
    icons_path = os.path.join(base_dir, args.icons)
    out_path = os.path.join(base_dir, args.out)
    har_path = os.path.join(base_dir, args.har)

    try:
        os.makedirs(icons_path, exist_ok=True)
        if os.path.exists(har_path):
            extract_gifs_from_har(har_path, icons_path)
    except Exception:
        pass

    if not os.path.exists(layout_path):
        print(f"❌ Erreur: Fichier layout introuvable: {layout_path}")
        return

    layout_data = json.load(open(layout_path, 'r', encoding='utf-8'))
    
    config_data = None
    if os.path.exists(config_path):
        try:
            config_data = json.load(open(config_path, 'r', encoding='utf-8'))
        except:
            print("⚠️ Attention: Impossible de lire room_config.json, continuation sans les infos de room.")

    generate_html(layout_data, config_data, icons_path, out_path)

if __name__ == '__main__':
    main()