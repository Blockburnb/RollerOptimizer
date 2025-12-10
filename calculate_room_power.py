#!/usr/bin/env python3
"""
Calcule la puissance d'une room à partir de room_config.json suivant les règles du README.
Usage: python calculate_room_power.py [--room-level N] [--file room_config.json]
"""
import json
import argparse
from collections import defaultdict

DEFAULT_FILE = "room_config.json"


def load_room_config(path):
    with open(path, 'r', encoding='utf-8') as f:
        txt = f.read()
    # Certains exports peuvent contenir des // commentaires en début; essayer de dépolluer
    txt = '\n'.join([l for l in txt.splitlines() if not l.strip().startswith('//')])
    return json.loads(txt)


def find_rack_by_id(racks, rack_id):
    for r in racks:
        if r.get('_id') == rack_id or r.get('rack_id') == rack_id:
            return r
    return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--file', default=DEFAULT_FILE)
    p.add_argument('--room-level', type=int, help='Si fourni, calcule uniquement pour ce niveau de room (0-based)')
    args = p.parse_args()

    data = load_room_config(args.file)
    data = data.get('data', data)

    miners = data.get('miners', [])
    racks = data.get('racks', [])

    # filtrer par room-level si demandé
    if args.room_level is not None:
        room_level = args.room_level
        # recueillir user_room_ids pour ce niveau
        user_room_ids = set()
        for room in data.get('rooms', []):
            ri = room.get('room_info', {})
            if ri.get('level') == room_level:
                user_room_ids.add(room.get('_id'))
        # garder racks qui ont placement.user_room_id in user_room_ids
        racks = [r for r in racks if r.get('placement', {}).get('user_room_id') in user_room_ids]

    # map rack_id (_id) -> list of miners
    miners_by_rack = defaultdict(list)
    for m in miners:
        placement = m.get('placement') or {}
        rid = placement.get('user_rack_id')
        if rid:
            miners_by_rack[rid].append(m)

    # raw power total
    raw_power = 0
    for m in miners:
        raw_power += m.get('power', 0)

    # miner bonuses unique by (name, level)
    seen_miner_bonus = {}
    for m in miners:
        key = (m.get('name'), m.get('level'))
        if key not in seen_miner_bonus:
            seen_miner_bonus[key] = m.get('bonus_percent', 0)
    miner_bonus_percent_total = sum(v for v in seen_miner_bonus.values() if isinstance(v, (int, float)))

    miner_bonus_power = raw_power * (miner_bonus_percent_total / 10000.0)

    # rack bonuses
    rack_bonus_total = 0.0
    rack_details = []
    for r in racks:
        rid = r.get('_id')
        # some JSON use rack_id to reference template; placement._id is unique id stored in miners placement
        # we use rid as reference to match placement.user_rack_id
        r_miners = miners_by_rack.get(rid, [])
        # compute rack_raw_power
        rack_raw = sum(m.get('power', 0) for m in r_miners)
        rack_percent = r.get('bonus', 0) or 0
        # if rack_percent seems 3000 style in inventory, but here bonus is likely in percent like 3000 -> 30%
        # assume here bonus is in same centi-percent format
        rack_bonus = rack_raw * (rack_percent / 10000.0)
        rack_bonus_total += rack_bonus
        rack_details.append((rid, rack_raw, rack_percent, rack_bonus, len(r_miners)))

    final_power = raw_power + miner_bonus_power + rack_bonus_total

    # Print summary
    print('Raw power total: {:,}'.format(int(raw_power)))
    print('Miner bonus percent total: {} (-> {:.4f} fraction)'.format(int(miner_bonus_percent_total), miner_bonus_percent_total / 10000.0))
    print('Miner bonus power (appliqué au raw power): {:,}'.format(int(miner_bonus_power)))
    print('Rack bonus total: {:,}'.format(int(rack_bonus_total)))
    print('Final power: {:,}'.format(int(final_power)))
    #print('')
    #print('Détails par rack (id, raw, percent, bonus, miners_count):')
    #for d in rack_details:
        #print(' -', d[0], '{:,}'.format(int(d[1])), d[2], '{:,}'.format(int(d[3])), d[4])


if __name__ == '__main__':
    main()
