#!/usr/bin/env python3
"""
Ouvre un navigateur, tente d'ouvrir directement l'URL de room-config et sauvegarde le JSON dans room_config.json.
Si redirigé vers le login, ouvre rollercoin.com, laissez-vous connecter puis appuyez Entrée pour charger la cible.
"""
import json
import subprocess
import sys
import argparse

DEFAULT_URL = "https://rollercoin.com/api/game/room-config/65d26ed27cee99a45d4f0848"
DEFAULT_OUTPUT = "room_config.json"


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
        print("Ouverture du navigateur...")

        # Try direct navigation first
        try:
            resp = page.goto(args.url, wait_until='networkidle', timeout=int(args.timeout * 1000))
        except Exception:
            resp = None

        def save_response(resp_obj, path):
            try:
                data = resp_obj.json()
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                return True
            except Exception:
                try:
                    text = resp_obj.text()
                    with open(path, 'w', encoding='utf-8') as f:
                        f.write(text)
                    return True
                except Exception:
                    return False

        if resp is not None:
            ct = resp.headers.get('content-type', '') if hasattr(resp, 'headers') else ''
            if 'json' in ct:
                ok = save_response(resp, args.output)
                print("Saved:" , args.output if ok else "failed")
                browser.close()
                sys.exit(0 if ok else 2)

        # If not JSON immediately, ask user to log in then load target
        print("La cible n'a pas retourné de JSON directement. Connectez-vous si nécessaire dans la fenêtre ouverte.")
        page.goto("https://rollercoin.com")
        input('Après connexion, appuyez sur Entrée pour charger la cible et la sauvegarder...')

        try:
            resp2 = page.wait_for_response(lambda r: args.url in r.url, timeout=int(args.timeout * 1000))
        except Exception as e:
            print("Erreur/timeout:", e)
            browser.close()
            sys.exit(3)

        ok = save_response(resp2, args.output)
        print("Saved:", args.output if ok else "failed")
        browser.close()
        sys.exit(0 if ok else 4)


if __name__ == '__main__':
    main()
