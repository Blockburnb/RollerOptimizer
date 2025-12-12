#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Optimise la disposition des miners/racks pour maximiser la final power.
Usage: python optimize_layout.py [--room-level N] [--miners miners.json] [--room room_config.json]
Options principales:
  --room-level N    : niveau de room (0..3). Utilise la capacité de racks par README (12 pour level 0, 18 sinon) sauf si --max-racks est fourni
  --max-racks N     : forcer nombre maximum de racks
  --rack3-percent P : bonus centi-pourcent pour les racks 3-étages (ex: 300 -> 3%)
  --rack4-percent P : bonus centi-pourcent pour les racks 4-étages
Le script va comparer deux scénarios (tous racks height=3 vs height=4) et afficher la meilleure sélection de miners pour chaque cas.
"""
import json
import argparse
import math
from collections import defaultdict
import glob
import os
import time
from datetime import datetime

DEFAULT_ROOM_FILE = "room_config.json"
DEFAULT_MINERS_FILE = "inventory_miners_1.json"

# capacité par niveau (voir README)
ROOM_CAPACITY = {0: 12, 1: 18, 2: 18, 3: 18}


def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        txt = f.read()
    txt = '\n'.join([l for l in txt.splitlines() if not l.strip().startswith('//')])
    return json.loads(txt)


def collect_miners(miners_path, room_config_path=None, room_level=None):
    # Charger miners depuis le fichier fourni ou depuis room_config.json si miners list y est
    miners = []
    # If a single path is provided but multiple inventory files exist, load them all
    try:
        # gather inventory_miners_*.json in current dir
        cwd = os.path.dirname(os.path.abspath(__file__))
        miner_files = sorted(glob.glob(os.path.join(cwd, 'inventory_miners_*.json')))
        if miner_files:
            miners = []
            for mf in miner_files:
                try:
                    data = load_json(mf)
                except Exception:
                    continue
                if isinstance(data, dict):
                    for k in ('data', 'miners', 'items', 'list', 'inventory'):
                        if k in data and isinstance(data[k], list):
                            miners.extend(data[k])
                            break
                    else:
                        # try to append first list found
                        appended = False
                        for v in data.values():
                            if isinstance(v, list):
                                miners.extend(v)
                                appended = True
                                break
                        if not appended:
                            # not a structure we know, skip
                            pass
                elif isinstance(data, list):
                    miners.extend(data)
        else:
            # fallback to provided path if no glob matches
            if miners_path:
                try:
                    miners = load_json(miners_path)
                    if isinstance(miners, dict):
                        for k in ('data', 'miners', 'items', 'list', 'inventory'):
                            if k in miners and isinstance(miners[k], list):
                                miners = miners[k]
                                break
                        else:
                            for v in miners.values():
                                if isinstance(v, list):
                                    miners = v
                                    break
                except Exception as e:
                    print(f"Impossible de charger {miners_path}: {e}")
                    miners = []
    except Exception:
        miners = []

    # fallback: try to read miners from room_config.json
    if not miners and room_config_path:
        try:
            rc = load_json(room_config_path)
            data = rc.get('data', rc)
            miners = data.get('miners', [])
        except Exception:
            miners = []

    # filtrer éventuellement par room-level : si room_level donné on conserve uniquement miners déjà placés dans ce niveau
    if room_level is not None and room_config_path:
        try:
            rc = load_json(room_config_path)
            data = rc.get('data', rc)
            user_room_ids = set()
            for room in data.get('rooms', []):
                ri = room.get('room_info', {})
                if ri.get('level') == room_level:
                    user_room_ids.add(room.get('_id'))
            # miners placement has placement.user_room_id sometimes; fallback to placement -> not always present in inventory exports
            filtered = []
            for m in miners:
                placement = m.get('placement') or {}
                if placement.get('user_room_id') in user_room_ids:
                    filtered.append(m)
            if filtered:
                miners = filtered
        except Exception:
            pass

    # normalize miners fields
    normalized = []
    for m in miners:
        name = m.get('name') or m.get('miner_name') or 'unknown'
        level = m.get('level', 0)
        power = m.get('power') or m.get('hashrate') or 0
        width = m.get('width') or (m.get('miner', {}) or {}).get('width') or m.get('miner.width') or 1
        try:
            width = int(width)
        except Exception:
            width = 1
        bonus = m.get('bonus_percent') or m.get('bonus') or 0
        normalized.append({'name': name, 'level': level, 'power': float(power), 'width': int(width), 'bonus_percent': int(bonus)})
    return normalized


def collect_rack_percents(room_config_path=None):
    """Collecte les pourcentages des racks depuis tous les fichiers inventory_rack_*.json et depuis room_config.json.
    Retourne un tuple (percents_dict, names_dict) where each is {3: [ints], 4: [ints]} and names_dict has parallel strings.
    """
    cwd = os.path.dirname(os.path.abspath(__file__))
    rack_files = sorted(glob.glob(os.path.join(cwd, 'inventory_rack_*.json')))
    percents = {3: [], 4: []}
    names = {3: [], 4: []}
    def _add_percent(entry, size_hint=None):
        # find numeric percent-like keys
        name_val = None
        for nk in ('name', 'title', 'display_name', 'label'):
            if nk in entry and isinstance(entry[nk], str):
                name_val = entry[nk]
                break
        # fallback to some identifier
        if name_val is None:
            name_val = entry.get('id') or entry.get('type') or None
        for k, v in entry.items():
            if not isinstance(v, (int, float)):
                continue
            kl = k.lower()
            if 'percent' in kl or 'bonus' in kl or 'percent' in kl:
                try:
                    val = int(v)
                except Exception:
                    continue
                # determine height
                if 'height' in entry and isinstance(entry.get('height'), int):
                    h = entry.get('height')
                elif 'size' in entry and isinstance(entry.get('size'), int):
                    h = entry.get('size') // 2
                elif size_hint:
                    h = size_hint
                else:
                    # unknown -> assume height 3
                    h = 3
                if h in (3,4):
                    percents[h].append(int(val))
                    # store provided name or a placeholder (we'll label later if missing)
                    names[h].append(name_val or (f"{h}-étages"))
                return

    # parse inventory rack files
    for rf in rack_files:
        try:
            data = load_json(rf)
        except Exception:
            continue
        if isinstance(data, dict):
            # try common keys
            candidates = []
            for k in ('data', 'racks', 'items', 'list'):
                if k in data and isinstance(data[k], list):
                    candidates = data[k]
                    break
            if not candidates:
                # find first list value
                for v in data.values():
                    if isinstance(v, list):
                        candidates = v
                        break
            for entry in candidates:
                if isinstance(entry, dict):
                    _add_percent(entry)
        elif isinstance(data, list):
            for entry in data:
                if isinstance(entry, dict):
                    _add_percent(entry)

    # also try room_config.json racks if present
    if room_config_path:
        try:
            rc = load_json(room_config_path)
            data = rc.get('data', rc)
            # look for racks list
            for key in ('racks', 'rack_templates', 'rack_info', 'racks_list'):
                if key in data and isinstance(data[key], list):
                    for entry in data[key]:
                        if isinstance(entry, dict):
                            _add_percent(entry)
            # some room_config stores racks inside 'racks' under room or appearance - try to scan whole object
            def scan(o):
                if isinstance(o, dict):
                    _add_percent(o)
                    for v in o.values():
                        scan(v)
                elif isinstance(o, list):
                    for i in o:
                        scan(i)
            for key in ('racks', 'miners', 'appearance'):
                scan(data.get(key, {}))
        except Exception:
            pass

    # normalize: sort descending so best racks come first while keeping names aligned
    for h in (3,4):
        pairs = [(percents[h][i], names[h][i]) for i in range(len(percents[h]))] if percents[h] else []
        pairs = sorted(pairs, key=lambda x: x[0], reverse=True)
        percents[h] = [p for p, n in pairs]
        names[h] = [n for p, n in pairs]
    return percents, names


def group_miners(miners):
    groups = {}
    for m in miners:
        key = (m['name'], m['level'], m['power'], m['width'], m['bonus_percent'])
        groups.setdefault(key, 0)
        groups[key] += 1
    # transform to list of dicts
    out = []
    for (name, level, power, width, bonus), count in groups.items():
        out.append({'name': name, 'level': level, 'power': power, 'width': width, 'bonus_percent': bonus, 'count': count})
    return out


def prune_states(states):
    # states: list of (raw_power, miner_bonus_total, selection_dict)
    # keep non-dominated: A dominates B if raw>= and bonus>=
    if not states:
        return []
    # sort by raw,bonus desc
    states = sorted(states, key=lambda x: (x[0], x[1]), reverse=True)
    pruned = []
    max_bonus = -1
    for raw, bonus, sel in states:
        if bonus > max_bonus:
            pruned.append((raw, bonus, sel))
            max_bonus = bonus
    return pruned


def optimize_for_height(groups, capacity_racks, height, rack_percent_list=None, rack_percent_fallback=0):
    """Optimise en supposant `capacity_racks` de ce `height`.
    rack_percent_list: list of centi-percent available for this height (inventory). If provided, the function will pick the top-K racks_used from this list and use their average percent. Otherwise uses rack_percent_fallback (single centi-percent).
    """
    capacity_units = capacity_racks * height * 2
    # dp[w] = list of (raw_power, miner_bonus_total)
    dp = {0: [(0.0, 0)]}
    for g in groups:
        p = g['power']
        w_item = g['width']
        n = g['count']
        b = g['bonus_percent'] or 0
        new_dp = {}
        for used_w, states in dp.items():
            for k in range(0, n + 1):
                add_w = k * w_item
                new_w = used_w + add_w
                if new_w > capacity_units:
                    break
                add_power = k * p
                add_bonus = b if k >= 1 else 0
                for (raw, mb) in states:
                    nw = raw + add_power
                    nmb = mb + add_bonus
                    new_dp.setdefault(new_w, []).append((nw, nmb))
        # prune per width
        dp = {}
        for w, st in new_dp.items():
            dp[w] = prune_states(st)
    # final: evaluate best final_power among dp widths <= capacity
    best = None
    best_state = None
    for w, st in dp.items():
        for raw, mb in st:
            # determine racks used and estimated rack percent
            racks_used = math.ceil(w / (height * 2)) if w > 0 else 0
            avg_rack_percent = 0
            if rack_percent_list and racks_used > 0:
                # take the top-k available percents; if less than needed, take what's available and assume zeros for missing
                topk = rack_percent_list[:racks_used]
                if topk:
                    avg_rack_percent = sum(topk) / len(topk)
                else:
                    avg_rack_percent = rack_percent_fallback
            else:
                avg_rack_percent = rack_percent_fallback

            final = raw * (1.0 + (mb + avg_rack_percent) / 10000.0)
            if best is None or final > best:
                best = final
                best_state = {'used_units': w, 'raw': raw, 'miner_bonus': mb, 'avg_rack_percent': avg_rack_percent}
    # compute racks used minimal
    if best_state:
        racks_used = math.ceil(best_state['used_units'] / (height * 2))
        return {"final_power": best, "raw_power": best_state['raw'], "miner_bonus_percent": best_state['miner_bonus'], "used_units": best_state['used_units'], "racks_used": racks_used, "avg_rack_percent": best_state.get('avg_rack_percent', 0)}
    return None


def compute_dp_for_max_units(groups, max_units):
    """Compute DP table once for capacity up to max_units. Returns dp dict mapping used_units->pruned states (raw, mb, sel)."""
    dp = {0: [(0.0, 0, {})]}
    for gi, g in enumerate(groups):
        p = g['power']
        w_item = g['width']
        n = g['count']
        b = g['bonus_percent'] or 0
        new_dp = {}
        for used_w, states in dp.items():
            for k in range(0, n + 1):
                add_w = k * w_item
                new_w = used_w + add_w
                if new_w > max_units:
                    break
                add_power = k * p
                add_bonus = b if k >= 1 else 0
                for (raw, mb, sel) in states:
                    nw = raw + add_power
                    nmb = mb + add_bonus
                    # copy selection and add k for this group
                    if k:
                        new_sel = dict(sel)
                        new_sel[gi] = new_sel.get(gi, 0) + k
                    else:
                        new_sel = sel
                    new_dp.setdefault(new_w, []).append((nw, nmb, new_sel))
        # prune per width
        dp = {}
        for w, st in new_dp.items():
            dp[w] = prune_states(st)
    return dp


def optimize_mixed_racks(groups, capacity_racks, rack_percents_dict, rack_names_dict, rack3_fallback=0, rack4_fallback=0, top_n_results=5):
    """Try all combinations racks3 in [0..capacity] and racks4 in [0..capacity - racks3].
    Uses inventory rack_percents_dict {3: [...], 4: [...]} and rack_names_dict {3:[...],4:[...]}.
    Returns sorted list of candidate dicts (best first) and includes chosen rack_name_list for assignment.
    """
    max_units = capacity_racks * 4 * 2
    dp_max = compute_dp_for_max_units(groups, max_units)

    candidates = []
    # enumerate only combinations where r3 + r4 == capacity_racks (exact fill)
    total_combinations = capacity_racks + 1 if capacity_racks >= 0 else 0
    comb_index = 0
    for r3 in range(0, capacity_racks + 1):
        r4 = capacity_racks - r3
        total_racks = r3 + r4
        # total_racks == capacity_racks by construction
        if total_racks == 0:
            # skip empty full-capacity only if capacity is zero
            continue
        # progress update
        comb_index += 1
        try:
            pct = (comb_index / total_combinations) * 100 if total_combinations > 0 else 100.0
            print(f"Progress tests: {comb_index}/{total_combinations} ({pct:.1f}%) — testing r3={r3} r4={r4}", end='\r', flush=True)
        except Exception:
            pass
        cap_units = r3 * 3 * 2 + r4 * 4 * 2
        # build avg rack percent using inventory top-K and fallback for missing slots
        top3 = rack_percents_dict.get(3, [])[:r3]
        top4 = rack_percents_dict.get(4, [])[:r4]
        # names for top3/top4
        top3_names = rack_names_dict.get(3, [])[:r3]
        top4_names = rack_names_dict.get(4, [])[:r4]
        # fill missing with fallbacks
        if len(top3) < r3 and r3 > 0:
            top3 = top3 + [rack3_fallback] * (r3 - len(top3))
        if len(top4) < r4 and r4 > 0:
            top4 = top4 + [rack4_fallback] * (r4 - len(top4))
        if len(top3_names) < r3 and r3 > 0:
            # append default names for missing
            top3_names = top3_names + [f"3-étages"] * (r3 - len(top3_names))
        if len(top4_names) < r4 and r4 > 0:
            top4_names = top4_names + [f"4-étages"] * (r4 - len(top4_names))
        all_perc = []
        if top3:
            all_perc.extend(top3)
        if top4:
            all_perc.extend(top4)
        avg_rack_percent = int(sum(all_perc) / len(all_perc)) if all_perc else 0

        # evaluate best final power using dp_max states up to cap_units
        best = None
        best_state = None
        best_sel = None
        for w, st in dp_max.items():
            if w > cap_units:
                continue
            for raw, mb, sel in st:
                final = raw * (1.0 + (mb + avg_rack_percent) / 10000.0)
                if best is None or final > best:
                    best = final
                    best_state = {'used_units': w, 'raw': raw, 'miner_bonus': mb}
                    best_sel = sel

        if best_state:
            # build rack name list in order: first 3-height then 4-height
            rack_name_list = []
            rack_name_list.extend(top3_names)
            rack_name_list.extend(top4_names)
            candidates.append({
                'r3': r3,
                'r4': r4,
                'total_racks': total_racks,
                'final_power': best,
                'raw_power': best_state['raw'],
                'miner_bonus_percent': best_state['miner_bonus'],
                'used_units': best_state['used_units'],
                'avg_rack_percent': avg_rack_percent,
                'selection': best_sel or {},
                'rack_name_list': rack_name_list
            })

    # sort and return top candidates
    candidates = sorted(candidates, key=lambda x: x['final_power'], reverse=True)
    # finish progress line
    try:
        print(' ' * 120, end='\r')
    except Exception:
        pass
    return candidates[:top_n_results]


def assign_miners_to_racks(selection, groups, r3, r4, rack_names=None):
    """Assign selected miners (selection: {group_index: count}) into racks (r3 and r4 counts).
    rack_names: optional list of names for each rack (length r3+r4). If provided, used in same order: first r3 names for 3-height, then r4 for 4-height.
    Returns list of racks with structure {'height':h, 'name':..., 'miners': [items], 'raw': total_power}.
    """
    # build rack objects
    racks = []
    name_iter = list(rack_names) if rack_names else []
    for _ in range(r3):
        nm = name_iter.pop(0) if name_iter else '3-étages'
        racks.append({'height': 3, 'name': nm, 'floors': [2] * 3, 'miners': [], 'raw': 0.0})
    for _ in range(r4):
        nm = name_iter.pop(0) if name_iter else '4-étages'
        racks.append({'height': 4, 'name': nm, 'floors': [2] * 4, 'miners': [], 'raw': 0.0})

    # expand selection into individual miner instances
    instances = []
    for gi, cnt in (selection or {}).items():
        g = groups[gi]
        for _ in range(cnt):
            instances.append({'name': g['name'], 'level': g['level'], 'power': g['power'], 'width': g['width'], 'bonus_percent': g['bonus_percent']})

    # sort instances by power desc
    instances.sort(key=lambda x: x['power'], reverse=True)

    for inst in instances:
        best_choice = None
        best_after_raw = -1
        best_floor_idx = None
        # try every rack and floor
        for ri, rack in enumerate(racks):
            for fi, free in enumerate(rack['floors']):
                if free >= inst['width']:
                    after_raw = rack['raw'] + inst['power']
                    if after_raw > best_after_raw:
                        best_after_raw = after_raw
                        best_choice = ri
                        best_floor_idx = fi
        if best_choice is not None:
            # place
            racks[best_choice]['floors'][best_floor_idx] -= inst['width']
            racks[best_choice]['miners'].append(inst)
            racks[best_choice]['raw'] += inst['power']
        else:
            # cannot place (shouldn't happen if selection matches capacity), skip
            continue

    # compute simple summary and sort racks by raw desc
    for r in racks:
        r['miners_count'] = len(r['miners'])
    racks = sorted(racks, key=lambda x: x['raw'], reverse=True)
    return racks

def format_rack_output(racks):
    lines = []
    for i, r in enumerate(racks, start=1):
        # include rack name next to number
        rack_name = r.get('name', '')
        if rack_name:
            lines.append(f"Rack #{i} ({rack_name}): height={r['height']}, raw={int(r['raw'])}, miners={r['miners_count']}")
        else:
            lines.append(f"Rack #{i}: height={r['height']}, raw={int(r['raw'])}, miners={r['miners_count']}")
        for m in sorted(r['miners'], key=lambda x: x['power'], reverse=True):
            lines.append(f"  - {m['name']} lv{m['level']} power={int(m['power'])} width={m['width']} bonus={m.get('bonus_percent',0)}")
    return "\n".join(lines)

def compute_max_raw_and_max_bonus(groups, capacity_racks):
    """Return (max_raw, max_bonus) achievable using up to capacity_racks * 4 * 2 units.
    max_raw: sum of powers maximizing raw power (ignore rack percents and miner bonuses).
    max_bonus: maximum sum of unique miner bonuses reachable (each group's bonus counted once if at least one placed).
    """
    max_units = capacity_racks * 4 * 2
    dp = compute_dp_for_max_units(groups, max_units)
    max_raw = 0.0
    max_bonus = 0
    for w, st in dp.items():
        for raw, mb, sel in st:
            if raw > max_raw:
                max_raw = raw
            if mb > max_bonus:
                max_bonus = mb
    return max_raw, max_bonus

def compute_max_miners_count(groups, capacity_racks):
    """Return the maximum number of miner instances that can be placed using up to
    capacity_racks * 4 * 2 unit-slots (assume all racks are 4-height to maximize slots).
    Greedy strategy: place all width=1 miners first, then width=2, then larger widths —
    this maximizes the count of placed miners (ignores power and bonuses).
    Returns integer count.
    """
    max_units = capacity_racks * 4 * 2
    # aggregate counts by width
    counts_by_width = {}
    for g in groups:
        w = int(g.get('width', 1))
        counts_by_width.setdefault(w, 0)
        counts_by_width[w] += int(g.get('count', 0))
    total = 0
    rem = max_units
    for w in sorted(counts_by_width.keys()):
        if rem <= 0:
            break
        avail = counts_by_width[w]
        fit = min(avail, rem // w)
        total += fit
        rem -= fit * w
    return total

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--room-level', type=int, choices=[0,1,2,3], help='niveau de room')
    p.add_argument('--room', default=DEFAULT_ROOM_FILE)
    p.add_argument('--miners', default=DEFAULT_MINERS_FILE)
    p.add_argument('--max-racks', type=int, help='forcer nombre maximum de racks')
    p.add_argument('--rack3-percent', type=int, default=0, help='bonus centi-pourcent pour racks 3-étages (ex: 300 -> 3%)')
    p.add_argument('--rack4-percent', type=int, default=0, help='bonus centi-pourcent pour racks 4-étages')
    args = p.parse_args()
    start_time = time.time()

    miners = collect_miners(args.miners, args.room, args.room_level)
    if not miners:
        print('Aucun miner trouvé dans les fichiers fournis.')
        elapsed = time.time() - start_time
        print(f"Temps d'exécution: {elapsed:.1f}s")
        return
    groups = group_miners(miners)

    if args.max_racks is not None:
        capacity = args.max_racks
    else:
        # Determine cumulative capacity across unlocked room levels.
        # If --room-level provided, consider all levels 0..room_level unlocked.
        # Otherwise try to infer highest unlocked level from room_config.json 'rooms'.
        try:
            # load room config
            rc = load_json(args.room) if args.room else load_json(DEFAULT_ROOM_FILE)
            data = rc.get('data', rc)
            if args.room_level is not None:
                max_level = args.room_level
            else:
                max_level = -1
                for room in data.get('rooms', []):
                    rl = room.get('room_info', {}).get('level')
                    if isinstance(rl, int) and rl > max_level:
                        max_level = rl
                if max_level < 0:
                    # fallback to highest known level
                    max_level = max(ROOM_CAPACITY.keys())
            # sum capacities for levels 0..max_level
            capacity = sum(ROOM_CAPACITY.get(l, 18) for l in range(0, max_level + 1))
        except Exception:
            # fallback: single-room capacity
            if args.room_level is not None:
                capacity = ROOM_CAPACITY.get(args.room_level, 18)
            else:
                capacity = max(ROOM_CAPACITY.values())

    # collect inventory racks percents (by height)
    rack_percents, rack_names = collect_rack_percents(args.room)
    # evaluate mixed combos and keep top results
    top_candidates = optimize_mixed_racks(groups, capacity, rack_percents, rack_names, rack3_fallback=args.rack3_percent, rack4_fallback=args.rack4_percent, top_n_results=10)

    print('Capacité racks utilisée pour test: {} racks (on évalue toutes combinaisons r3+r4 <= capacité)'.format(capacity))
    if not top_candidates:
        print('Aucun agencement trouvé.')
    else:
        best = top_candidates[0]
        print('\n--- Meilleur agencement (mix racks) ---')
        print('Composition: {} racks 3-étages, {} racks 4-étages (total {})'.format(best['r3'], best['r4'], best['total_racks']))
        print('Final power: {:,.0f}'.format(best['final_power']))
        print('Raw power placé: {:,.0f}'.format(best['raw_power']))
        print('Miner bonus percent unique total: {}'.format(int(best['miner_bonus_percent'])))

        # compute and print global maxima (raw only and unique bonuses only)
        raw_max, bonus_max = compute_max_raw_and_max_bonus(groups, capacity)
        print('\n--- Résumé global (indépendant du mix racks) ---')
        print('Raw power max atteignable (placer les miners les plus puissants): {:,.0f}'.format(raw_max))
        print('Max miner unique bonus total atteignable (somme des bonus uniques possibles): {}'.format(int(bonus_max)))
        # compute and print maximum number of miners placeable (ignoring power/bonus)
        max_count = compute_max_miners_count(groups, capacity)
        print('Max miners placables avec l\'inventaire (en maximisant le nombre, sans power/bonus): {}'.format(int(max_count)))

        # build and print detailed rack assignments for the best candidate
        selection = best.get('selection', {})
        racks = assign_miners_to_racks(selection, groups, best['r3'], best['r4'], rack_names=best.get('rack_name_list'))
        print('\n--- Détail des racks et miners (trié par raw desc) ---')
        print(format_rack_output(racks))

        # Exporter le layout optimal dans un fichier JSON (à côté du script)
        try:
            out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'room_layout_optimal.json')
            output = {
                'generated_at': datetime.now().isoformat(sep=' '),
                'capacity': capacity,
                'best_candidate': {
                    'r3': int(best.get('r3', 0)),
                    'r4': int(best.get('r4', 0)),
                    'total_racks': int(best.get('total_racks', 0)),
                    'final_power': float(best.get('final_power', 0.0)),
                    'raw_power': float(best.get('raw_power', 0.0)),
                    'miner_bonus_percent': int(best.get('miner_bonus_percent', 0)),
                    'used_units': int(best.get('used_units', 0)),
                    'avg_rack_percent': float(best.get('avg_rack_percent', 0.0))
                },
                'selection': best.get('selection', {}),
                'racks': racks
            }
            with open(out_path, 'w', encoding='utf-8') as of:
                json.dump(output, of, indent=2, ensure_ascii=False)
            print(f"\nLayout optimal sauvegardé dans: {out_path}")
        except Exception as e:
            print(f"\nImpossible d'écrire le fichier de sortie: {e}")

        # print execution time
        elapsed = time.time() - start_time
        print(f"Temps d'exécution: {elapsed:.1f}s")


if __name__ == '__main__':
    main()
