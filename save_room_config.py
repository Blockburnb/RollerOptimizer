#!/usr/bin/env python3
"""
Script minimal : ouvre un navigateur (Playwright), vous laisse vous connecter et capture la réponse JSON
pour l'URL cible (par défaut la room-config fournie). Si Playwright n'est pas installé, le script tente
de l'installer automatiquement (pip + installation du navigateur Chromium).
Usage: python save_room_config.py [--url URL] [--output FILE] [--timeout SECONDS]
"""

import argparse
import importlib
import json
import subprocess
import sys

# URL par défaut ciblée (modifiable via --url)
DEFAULT_URL = "https://rollercoin.com/api/game/room-config/65d26ed27cee99a45d4f0848"


def ensure_playwright_installed():
    """Vérifie l'import de Playwright et l'installe automatiquement si nécessaire.
    Retourne True si Playwright est prêt, False sinon.
    """
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        print("Playwright non trouvé, tentative d'installation automatique...")

    try:
        # Installer le paquet Python
        subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright"], stdout=subprocess.DEVNULL)
        # Installer Chromium (n'installe que chromium pour gagner du temps)
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"], stdout=subprocess.DEVNULL)
    except subprocess.CalledProcessError as e:
        print("Échec de l'installation automatique de Playwright.")
        print("Essayez d'exécuter manuellement :")
        print(f"  {sys.executable} -m pip install playwright")
        print(f"  {sys.executable} -m playwright install chromium")
        return False

    # Vérifier de nouveau
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        return False


def fetch_via_browser(target_url, output_path, timeout):
    from playwright.sync_api import sync_playwright
    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

    def build_url_with_skip(url, skip_val):
        parts = urlparse(url)
        qs = parse_qs(parts.query)
        qs['skip'] = [str(skip_val)]
        new_query = urlencode(qs, doseq=True)
        return urlunparse((parts.scheme, parts.netloc, parts.path, parts.params, new_query, parts.fragment))

    def extract_list_from_response(obj):
        # Retourne la première liste significative trouvée dans la réponse JSON
        if isinstance(obj, list):
            return obj
        if not isinstance(obj, dict):
            return []
        # cas courant: {"data": [...]}
        if 'data' in obj:
            if isinstance(obj['data'], list):
                return obj['data']
            if isinstance(obj['data'], dict):
                for key in ('items', 'miners', 'inventory', 'results', 'docs', 'list'):
                    if key in obj['data'] and isinstance(obj['data'][key], list):
                        return obj['data'][key]
                # fallback: return any list value inside data
                for v in obj['data'].values():
                    if isinstance(v, list):
                        return v
        # cas courant: {"items": [...]}, {"miners": [...]}
        for key in ('items', 'miners', 'inventory', 'results', 'docs', 'list'):
            if key in obj and isinstance(obj[key], list):
                return obj[key]
        # fallback: retourner la première valeur qui est une liste
        for v in obj.values():
            if isinstance(v, list):
                return v
        return []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        print("Navigateur ouvert.")

        # Première tentative : ouvrir directement l'URL cible
        print(f"Ouverture directe de l'URL cible : {target_url}")
        resp = None
        try:
            resp = page.goto(target_url, wait_until='networkidle', timeout=int(timeout * 1000))
        except Exception:
            resp = None

        def save_response_obj(resp_obj):
            try:
                data = resp_obj.json()
                out_text = json.dumps(data, indent=2, ensure_ascii=False)
            except Exception:
                try:
                    out_text = resp_obj.text()
                except Exception:
                    out_text = ''
            try:
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(out_text)
            except OSError as e:
                print(f"Impossible d'écrire le fichier de sortie: {e}")
                return 4
            return 0

        # Si la réponse directe est du JSON simple et non paginée -> sauvegarder
        if resp is not None:
            ct = resp.headers.get('content-type', '') if hasattr(resp, 'headers') else ''
            if 'application/json' in ct or 'json' in ct:
                # vérifier si l'URL contient des paramètres de pagination
                parsed = urlparse(target_url)
                qs = parse_qs(parsed.query)
                if 'skip' in qs or 'limit' in qs:
                    # nous gérons la pagination plus bas
                    pass
                else:
                    rc = save_response_obj(resp)
                    print(f"Réponse sauvegardée dans: {output_path}")
                    browser.close()
                    return rc

        # Si on arrive ici, soit la cible n'a pas retourné de JSON direct, soit elle est paginée.
        print("La cible n'a pas retourné de JSON immédiatement OU nécessite pagination. Si nécessaire, connectez-vous dans la fenêtre qui s'est ouverte.")
        page.goto("https://rollercoin.com")
        input("Après vous être connecté, appuyez sur Entrée pour lancer les requêtes API et récupérer les pages...")

        # Si l'URL contient skip/limit, on itère ; sinon on attend la première réponse correspondante
        parsed = urlparse(target_url)
        qs = parse_qs(parsed.query)
        if 'skip' in qs or 'limit' in qs:
            limit = int(qs.get('limit', ['48'])[0])
            aggregated = []
            skip = int(qs.get('skip', ['0'])[0])
            while True:
                page_url = build_url_with_skip(target_url, skip)
                print(f"Récupération: {page_url}")
                try:
                    # effectuer la requête depuis le contexte de la page (avec cookies de session)
                    js_result = page.evaluate("async url => { const r = await fetch(url); const t = await r.text(); try{return JSON.parse(t);}catch(e){return {__raw: t};} }", page_url)
                except Exception as e:
                    print(f"Erreur lors du fetch via page.evaluate: {e}")
                    browser.close()
                    return 3

                if isinstance(js_result, dict) and '__raw' in js_result:
                    print("Réponse non JSON brute reçue, arrêt.")
                    break

                items = extract_list_from_response(js_result)
                if not items:
                    print("Aucun item retourné pour cette page, arrêt.")
                    break

                aggregated.extend(items)
                print(f"Pages récupérées: skip={skip}, items page={len(items)}, total={len(aggregated)}")

                if len(items) < limit:
                    # dernière page
                    break
                skip += limit

            # sauvegarder le résultat agrégé
            try:
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(aggregated, f, ensure_ascii=False, indent=2)
            except OSError as e:
                print(f"Impossible d'écrire le fichier de sortie: {e}")
                browser.close()
                return 4

            print(f"Inventaire complet sauvegardé dans: {output_path} (total items: {len(aggregated)})")
            browser.close()
            return 0

        else:
            # Cas non paginé : attendre la réponse correspondant à target_url
            print(f"Chargement et attente de la réponse pour l'URL contenant: {target_url} (timeout {timeout}s)...")
            try:
                resp2 = page.wait_for_response(lambda r: target_url in r.url, timeout=int(timeout * 1000))
            except Exception as e:
                print(f"Erreur ou timeout lors de l'attente de la réponse: {e}")
                browser.close()
                return 3

            rc = save_response_obj(resp2)
            if rc == 0:
                print(f"Réponse sauvegardée dans: {output_path}")
            browser.close()
            return rc


def main():
    p = argparse.ArgumentParser(description='Ouvre un navigateur pour se connecter et capturer une requête JSON.')
    p.add_argument('--url', default=DEFAULT_URL, help='URL (ou portion d\'URL) à attendre (défaut: room-config ciblée)')
    p.add_argument('-o', '--output', default='room_config.json', help='Fichier de sortie (défaut: room_config.json)')
    p.add_argument('--timeout', type=float, default=60.0, help='Timeout en secondes pour attendre la requête (défaut: 60s)')
    args = p.parse_args()

    if not ensure_playwright_installed():
        print('Playwright non disponible. Abandon.')
        sys.exit(5)

    # Lancer le flux navigateur
    rc = fetch_via_browser(args.url, args.output, args.timeout)
    sys.exit(rc)


if __name__ == '__main__':
    main()
