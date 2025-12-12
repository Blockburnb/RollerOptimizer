#!/usr/bin/env python3
"""
Parse a .har file and extract responses for requests containing 'limit=48'.
Saves individual JSON/text responses into inventory files and also creates combined
`inventory_miners_combined.json` and `inventory_rack_combined.json` when possible.

Usage: adjust HAR path or run from the workspace root where `rollercoin.com.har` lives.
"""
import argparse
import base64
import json
import os
import re
import sys
from urllib.parse import urlparse, parse_qs
from datetime import datetime


def safe_decode_content(content_obj):
    """Return text decoded from HAR response.content object (handles base64).
    Returns None if no text present.
    """
    if not content_obj:
        return None
    text = content_obj.get('text')
    if text is None:
        return None
    if content_obj.get('encoding') == 'base64':
        try:
            return base64.b64decode(text).decode('utf-8', errors='replace')
        except Exception:
            return base64.b64decode(text)
    return text


def is_limit_48(url: str) -> bool:
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        if 'limit' in qs:
            return any(v == '48' or v == '48 ' for v in qs.get('limit', []))
        # fallback substring match
        return 'limit=48' in url
    except Exception:
        return 'limit=48' in url


def classify_url(url: str) -> str:
    url_lower = url.lower()
    if re.search(r"\bminers\b", url_lower) or '/inventory/miners' in url_lower or 'inventory/miners' in url_lower:
        return 'miners'
    if 'rack' in url_lower or 'racks' in url_lower or 'inventory/rack' in url_lower or 'inventory/racks' in url_lower:
        return 'rack'
    return 'other'


def try_parse_json(text):
    try:
        return json.loads(text)
    except Exception:
        return None


def main():
    p = argparse.ArgumentParser(description='Extract HAR responses with limit=48 into inventory JSON files')
    p.add_argument('har', nargs='?', default=os.path.join(os.path.dirname(__file__), 'rollercoin.com.har'))
    # Put extracted files in the same directory as this script (no subfolder)
    p.add_argument('--outdir', '-o', default=os.path.dirname(__file__))
    args = p.parse_args()

    har_path = args.har
    outdir = args.outdir
    os.makedirs(outdir, exist_ok=True)

    try:
        with open(har_path, 'r', encoding='utf-8') as f:
            har = json.load(f)
    except Exception as e:
        print(f'Failed to read HAR file: {e}', file=sys.stderr)
        sys.exit(2)

    # compute HAR file modification time and human-readable age (French)
    try:
        har_mtime_ts = os.path.getmtime(har_path)
        har_dt = datetime.fromtimestamp(har_mtime_ts)
    except Exception:
        har_dt = None

    def human_age(dt: datetime) -> str:
        if dt is None:
            return "inconnue"
        now = datetime.now()
        delta = now - dt
        seconds = int(delta.total_seconds())
        if seconds < 60:
            return f"il y a {seconds} seconde{'s' if seconds != 1 else ''}"
        minutes = seconds // 60
        if minutes < 60:
            return f"il y a {minutes} minute{'s' if minutes != 1 else ''}"
        hours = minutes // 60
        if hours < 24:
            return f"il y a {hours} heure{'s' if hours != 1 else ''}"
        days = delta.days
        return f"il y a {days} jour{'s' if days != 1 else ''}"

    har_meta = {
        'har_path': har_path,
        'har_modified': har_dt.isoformat(sep=' ') if har_dt is not None else None,
        'har_age': human_age(har_dt)
    }

    # Afficher les infos du fichier HAR dans le terminal (en français)
    print(f"Fichier HAR: {har_meta['har_path']}")
    if har_meta['har_modified']:
        print(f"Modifié: {har_meta['har_modified']} ({har_meta['har_age']})")
    else:
        print(f"Modifié: inconnue ({har_meta['har_age']})")

    entries = har.get('log', {}).get('entries', [])
    miners_count = 0
    rack_count = 0
    other_count = 0

    miners_objs = []
    racks_objs = []

    for idx, entry in enumerate(entries, start=1):
        req = entry.get('request', {})
        url = req.get('url') or req.get('path') or ''
        if not url:
            continue
        if not is_limit_48(url):
            continue

        content_obj = entry.get('response', {}).get('content', {})
        text = safe_decode_content(content_obj)
        if text is None:
            # nothing to save
            continue

        parsed_json = try_parse_json(text)
        kind = classify_url(url)

        if kind == 'miners':
            miners_count += 1
            fname = f'inventory_miners_{miners_count}.json'
            fullpath = os.path.join(outdir, fname)
            if parsed_json is not None:
                # écrire la réponse JSON telle quelle
                with open(fullpath, 'w', encoding='utf-8') as out:
                    json.dump(parsed_json, out, indent=2, ensure_ascii=False)
                # collect for combined
                if isinstance(parsed_json, list):
                    miners_objs.extend(parsed_json)
                elif isinstance(parsed_json, dict) and 'items' in parsed_json and isinstance(parsed_json['items'], list):
                    miners_objs.extend(parsed_json['items'])
                else:
                    miners_objs.append(parsed_json)
            else:
                # sauvegarder le texte brut tel quel
                with open(fullpath, 'w', encoding='utf-8') as out:
                    out.write(text)

        elif kind == 'rack':
            rack_count += 1
            fname = f'inventory_rack_{rack_count}.json'
            fullpath = os.path.join(outdir, fname)
            if parsed_json is not None:
                with open(fullpath, 'w', encoding='utf-8') as out:
                    json.dump(parsed_json, out, indent=2, ensure_ascii=False)
                if isinstance(parsed_json, list):
                    racks_objs.extend(parsed_json)
                elif isinstance(parsed_json, dict) and 'items' in parsed_json and isinstance(parsed_json['items'], list):
                    racks_objs.extend(parsed_json['items'])
                else:
                    racks_objs.append(parsed_json)
            else:
                with open(fullpath, 'w', encoding='utf-8') as out:
                    out.write(text)

        else:
            other_count += 1
            fname = f'other_response_{other_count}.json'
            fullpath = os.path.join(outdir, fname)
            # try to save as JSON if possible
            if parsed_json is not None:
                with open(fullpath, 'w', encoding='utf-8') as out:
                    json.dump(parsed_json, out, indent=2, ensure_ascii=False)
            else:
                with open(fullpath, 'w', encoding='utf-8') as out:
                    out.write(text)

    # Combined output files are intentionally not created (per user request)

    print(f'Extracted: miners={miners_count}, racks={rack_count}, others={other_count} into "{outdir}"')


if __name__ == '__main__':
    main()
