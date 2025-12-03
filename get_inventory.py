#!/usr/bin/env python3
"""
Récupère l'inventaire de miners en itérant les pages (skip/limit) via le navigateur pour utiliser la session.
Usage: python get_inventory.py --url "...skip=0&limit=48" -o miners.json
"""
import json
import subprocess
import sys
import argparse
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

DEFAULT_URL = "https://rollercoin.com/api/storage/inventory/miners?sort=date&sort_direction=-1&skip=0&limit=48"
DEFAULT_OUTPUT = "miners_inventory.json"


def ensure_playwright_installed():
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        print("Playwright non trouvé, tentative d'installation automatique...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright"], stdout=subprocess.DEVNULL)
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"], stdout=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        print("Échec de l'installation automatique. Installez manuellement :")
        print(f"  {sys.executable} -m pip install playwright")
        print(f"  {sys.executable} -m playwright install chromium")
        return False
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        return False


def build_url_with_skip(url, skip_val):
    parts = urlparse(url)
    qs = parse_qs(parts.query)
    qs['skip'] = [str(skip_val)]
    new_query = urlencode(qs, doseq=True)
    return urlunparse((parts.scheme, parts.netloc, parts.path, parts.params, new_query, parts.fragment))


def extract_list_from_response(obj):
    if isinstance(obj, list):
        return obj
    if not isinstance(obj, dict):
        return []
    if 'data' in obj:
        if isinstance(obj['data'], list):
            return obj['data']
        if isinstance(obj['data'], dict):
            for key in ('items', 'miners', 'inventory', 'results', 'docs', 'list'):
                if key in obj['data'] and isinstance(obj['data'][key], list):
                    return obj['data'][key]
            for v in obj['data'].values():
                if isinstance(v, list):
                    return v
    for key in ('items', 'miners', 'inventory', 'results', 'docs', 'list'):
        if key in obj and isinstance(obj[key], list):
            return obj[key]
    for v in obj.values():
        if isinstance(v, list):
            return v
    return []


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--url', default=DEFAULT_URL)
    p.add_argument('-o', '--output', default=DEFAULT_OUTPUT)
    p.add_argument('--timeout', type=float, default=60.0)
    args = p.parse_args()

    if not ensure_playwright_installed():
        sys.exit(1)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        print("Navigateur ouvert. Connectez-vous si nécessaire.")
        page.goto("https://rollercoin.com")
        input('Après connexion, appuyez sur Entrée pour lancer la récupération de l\'inventaire...')

        parsed = urlparse(args.url)
        qs = parse_qs(parsed.query)
        limit = int(qs.get('limit', ['48'])[0])
        skip = int(qs.get('skip', ['0'])[0])

        aggregated = []
        while True:
            page_url = build_url_with_skip(args.url, skip)
            print(f"Fetching: {page_url}")
            try:
                js_result = page.evaluate("async url => { const r = await fetch(url, {credentials: 'include', headers: {'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'}}); const t = await r.text(); return {status: r.status, ok: r.ok, headers: Array.from(r.headers.entries()), body: t}; }", page_url)
            except Exception as e:
                print("Erreur lors du fetch via page.evaluate:", e)
                browser.close()
                sys.exit(3)

            # js_result est maintenant {status, ok, headers, body}
            status = js_result.get('status') if isinstance(js_result, dict) else None
            body = js_result.get('body') if isinstance(js_result, dict) else None
            if status is None:
                print('Réponse inattendue du fetch, arrêt.')
                break

            if status != 200:
                print(f"Fetch returned status {status}. Tentative d'ouverture directe pour debug...")
                try:
                    resp_nav = page.goto(page_url, wait_until='networkidle', timeout=int(args.timeout * 1000))
                    if resp_nav is not None:
                        ct = resp_nav.headers.get('content-type', '') if hasattr(resp_nav, 'headers') else ''
                        print('Nav content-type:', ct)
                        try:
                            text = resp_nav.text()
                            print('Nav body (start):', text[:400])
                        except Exception:
                            pass
                except Exception as e:
                    print('Erreur lors de la navigation directe:', e)
                # arrêter l'itération si statut non-200
                break

            if not body:
                print('Body vide reçu, arrêt.')
                break

            # essayer de parser JSON
            try:
                parsed = json.loads(body)
            except Exception:
                print('Impossible de parser le JSON de la page, affichage du début du body:')
                print(body[:400])
                break

            items = extract_list_from_response(parsed)
            if not items:
                print("Aucun item retourné pour cette page, arrêt.")
                break

            aggregated.extend(items)
            print(f"Pages récupérées: skip={skip}, items page={len(items)}, total={len(aggregated)}")

            if len(items) < limit:
                break
            skip += limit

        try:
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(aggregated, f, ensure_ascii=False, indent=2)
        except OSError as e:
            print("Impossible d'écrire le fichier de sortie:", e)
            browser.close()
            sys.exit(4)

        print(f"Inventaire complet sauvegardé dans: {args.output} (total items: {len(aggregated)})")
        browser.close()
        sys.exit(0)


if __name__ == '__main__':
    main()
