#!/usr/bin/env python3
"""
Génère une page HTML interactive qui affiche le layout optimal en conservant l'animation des GIFs.
Usage:
  python generate_layout_html.py [--layout room_layout_optimal.json] [--icons icons] [--out room_layout_visual.html]

Le script cherche des GIFs dans `icons/` en fonction du nom du miner (slugifié). Si aucun GIF n'est trouvé pour un miner, il utilise `har_icon.gif` si présent.
La page HTML place les racks côte-à-côte et les miners par étage (left-to-right). Les GIF restent animés car la page référence les fichiers GIF.
"""
import argparse
import json
import os
import re
from html import escape

# try to import Pillow to read GIF dimensions; fail gracefully
try:
    from PIL import Image
except Exception:
    Image = None

UNIT_PX = 48
FLOOR_PX = 48
RACK_SPACING = 24
MARGIN = 12


def slugify(s: str) -> str:
    if not s:
        return ''
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", '_', s)
    s = s.strip('_')
    return s


def pick_icon_path(icons_dir, miner):
    # Try filename field, then name slug, then simple variants
    filename_token = miner.get('filename') if isinstance(miner.get('filename'), str) else None
    candidates = []
    if filename_token:
        candidates.append(filename_token)
    name = miner.get('name')
    if isinstance(name, dict):
        # name may be localized dict — pick english or first value
        name_val = name.get('en') or next(iter(name.values()), '')
    else:
        name_val = name or ''
    candidates.append(name_val)
    candidates.append(slugify(name_val))
    candidates = [slugify(c) for c in candidates if c]
    for c in candidates:
        p = os.path.join(icons_dir, f"{c}.gif")
        if os.path.exists(p):
            return os.path.relpath(p).replace('\\', '/')
    # fallback
    fallback = os.path.join(os.path.dirname(__file__), 'har_icon.gif')
    if os.path.exists(fallback):
        return os.path.relpath(fallback).replace('\\', '/')
    return None


def _get_icon_size(icon_path):
    """Return (width, height) for a GIF file or None if unavailable."""
    if not icon_path:
        return None
    # accept either relative path (as used in HTML) or absolute
    abs_path = os.path.abspath(icon_path)
    if not os.path.exists(abs_path):
        return None
    if Image is None:
        return None
    try:
        with Image.open(abs_path) as im:
            return im.width, im.height
    except Exception:
        return None


def generate_html(layout, icons_dir, out_path):
    racks = layout.get('racks', [])
    title = f"Room layout generated: {layout.get('generated_at','') }"

    # Try to precompute icon intrinsic sizes by scanning the icons directory (Pillow optional)
    icon_sizes = {}
    try:
        from PIL import Image
        for fn in os.listdir(icons_dir):
            if not fn.lower().endswith('.gif'):
                continue
            p = os.path.join(icons_dir, fn)
            try:
                with Image.open(p) as im:
                    w, h = im.size
                rel = os.path.relpath(p).replace('\\', '/')
                icon_sizes[rel] = (w, h)
                icon_sizes[fn] = (w, h)
                icon_sizes[os.path.splitext(fn)[0]] = (w, h)
            except Exception:
                # skip unreadable files
                pass
    except Exception:
        # Pillow not available or error occured: we'll fall back to CSS-only sizing
        icon_sizes = {}

    # Start building HTML
    parts = []
    parts.append('<!doctype html>')
    parts.append('<html><head><meta charset="utf-8"><title>' + escape(title) + '</title>')
    parts.append('<meta name="viewport" content="width=device-width,initial-scale=1">')
    parts.append('<style>')
    parts.append('body{font-family:Segoe UI,Arial,sans-serif;background:#fff;color:#111;padding:12px}')
    parts.append('.room{white-space:nowrap}')
    parts.append('.rack{display:inline-block;vertical-align:top;margin-right:%dpx;border:1px solid #888;padding:8px;background:#f7f7f7}' % RACK_SPACING)
    # make rack a positioned container so absolutely positioned .miner elements are relative to it
    parts.append('.rack{position:relative;}')
    parts.append('.rack .rack-title{font-weight:700;margin-bottom:6px;text-align:center}')
    parts.append('.floor{position:relative;border:1px solid rgba(0,0,0,0.06);margin-bottom:6px;height:%dpx;width:100%%;background:linear-gradient(#fff,#eee)}' % FLOOR_PX)
    # miner container: no green border here; make sure the miner box cannot overflow the floor
    parts.append('.miner{position:absolute;top:4px;left:4px;overflow:hidden;box-sizing:border-box;border-radius:4px;background:transparent;display:flex;align-items:center;gap:6px;padding:4px;white-space:nowrap;max-height:%dpx}' % (FLOOR_PX - 4))
    # icon wrapper: green border only around the GIF
    parts.append('.miner .icon{border:2px solid rgba(20,120,20,0.9);padding:2px;border-radius:4px;background:#fff;display:inline-flex;align-items:center;justify-content:center;}')
    # constrain gif height to floor height but let width be intrinsic; use a reasonable max so labels have room
    parts.append('.miner .icon img{height:auto;max-height:%dpx;width:auto;display:block;}' % (FLOOR_PX - 12))
    # allow labels to wrap when space is tight; they will stack under the icon for small miners
    parts.append('.miner .label{font-size:11px;white-space:normal;flex:0 0 auto;color:#111;line-height:1.1;overflow-wrap:break-word;}')
    parts.append('.legend{margin-top:12px;font-size:13px;color:#333}')
    parts.append('</style></head><body>')

    parts.append(f'<h2>{escape(title)}</h2>')
    parts.append('<div class="room">')

    for ri, r in enumerate(racks, start=1):
        # collect overflow miners globally
        if 'overflow_miners' not in locals():
            overflow_miners = []
        height = int(r.get('height', 3))
        units = height * 2
        rack_width_px = units * UNIT_PX
        parts.append(f'<div class="rack" style="width:{rack_width_px}px">')
        parts.append(f'<div class="rack-title">Rack #{ri} ' + escape(str(r.get('name',''))) + f' (h={height})</div>')
        # floors: draw from top to bottom so visually top floor is first
        # we'll maintain floor_slots count and left offset
        floor_units = [2] * height
        floor_offsets = [0] * height
        miners = r.get('miners', []) or []
        # sort as in python script
        try:
            miners_sorted = sorted(miners, key=lambda x: float(x.get('power',0)), reverse=True)
        except Exception:
            miners_sorted = miners
        # We will render floors stacked top->bottom
        for fi in range(height-1, -1, -1):
            parts.append(f'<div class="floor" style="width:{rack_width_px}px">')
            parts.append('</div>')
        # Now place miners as absolutely positioned elements relative to the rack container
        # We must compute top position for each floor: since floors were added top->bottom, compute y
        floor_tops = []
        # compute cumulative top for each floor index (0..height-1 top->bottom)
        rack_inner_top = 36  # approx title height + margin
        for fh in range(height):
            top = rack_inner_top + fh * (FLOOR_PX + 6)  # floor height + margin
            floor_tops.append(top)
        # For layout simplicity, we'll place miners by finding first floor with space and render absolute divs using inline styles
        placed_miners = []
        for m in miners_sorted:
            mw = int(m.get('width',1))
            placed = False
            for fi in range(height):
                if floor_units[fi] >= mw:
                    left_px = floor_offsets[fi] * UNIT_PX + 4
                    top_px = floor_tops[fi] + 4
                    w_px = mw * UNIT_PX - 8
                    icon = pick_icon_path(icons_dir, m)

                    # compute display size for the icon if available (uses precomputed icon_sizes)
                    display_w = None
                    display_h = None
                    img_style = ''
                    if icon:
                        # look up by relpath, basename or slug
                        size = icon_sizes.get(icon) or icon_sizes.get(os.path.basename(icon)) or icon_sizes.get(os.path.splitext(os.path.basename(icon))[0])
                        if size:
                            ow, oh = size
                            max_h = max(8, FLOOR_PX - 12)
                            try:
                                scale = min(1.0, float(max_h) / float(oh)) if oh > 0 else 1.0
                            except Exception:
                                scale = 1.0
                            display_h = max(1, int(oh * scale))
                            display_w = max(1, int(ow * scale))
                            img_style = f'style="height:{display_h}px;width:{display_w}px"'
                        else:
                            # fallback: constrain by CSS max-height
                            img_style = f'style="max-height:{FLOOR_PX - 12}px"'

                    # wrap the image in a .icon div so the green border surrounds only the GIF
                    img_html_raw = f'<img src="{escape(icon)}" alt="{escape(str(m.get("name","")))}" {img_style}/>' if icon else ''
                    img_html = f'<div class="icon">{img_html_raw}</div>' if icon else ''

                    # determine miner container min-width so the GIF fits; keep at least the allocated grid width
                    allocated_px = w_px
                    if display_w:
                        min_width = max(allocated_px, display_w + 16)
                        min_height = display_h + 8
                    else:
                        min_width = allocated_px
                        min_height = FLOOR_PX - 8

                    # If this miner occupies only 1 unit (so there may be two miners on the floor),
                    # allow the label to wrap to a second line while keeping the icon on the left.
                    stack_label = (mw == 1)
                    inline_extra = ''
                    # we keep the normal left-icon/right-label flex layout; when stacking is needed
                    # compute a max-width for the label so it will wrap instead of overflowing.
                    label_style_attr = ''
                    if stack_label:
                        # approximate icon rendered width (use display_w if known, else a reasonable fallback)
                        icon_w = display_w if display_w else (FLOOR_PX - 12)
                        # include icon wrapper padding/border/gap estimate
                        icon_total = int(icon_w) + 8
                        # Allow the label to be substantially wider so it doesn't wrap into tiny fragments.
                        # Use a reference width equal to what a full-width miner would permit so
                        # single-unit miners on crowded floors get the same available label space.
                        reference_desired = UNIT_PX * 2 * 2
                        label_max = max(48, int(reference_desired - icon_total))
                        label_style_attr = f'style="max-width:{label_max}px;"'
                        # increase min-height slightly so two wrapped lines can fit within the floor
                        # only use display_h if available, otherwise fall back to a reasonable value
                        if display_h:
                            min_height = max(min_height, display_h + 12)
                        else:
                            min_height = max(min_height, FLOOR_PX - 8)

                    # resolve localized name if necessary
                    name_field = m.get('name')
                    if isinstance(name_field, dict):
                        name_text = name_field.get('en') or next(iter(name_field.values()), '')
                    else:
                        name_text = name_field or ''
                    label = escape(str(name_text))
                    level = int(m.get('level', 0)) if m.get('level') is not None else 0
                    power = int(float(m.get('power', 0))) if m.get('power') is not None else 0
                    # format power with spaces every 3 digits (e.g. 1234567 -> '1 234 567')
                    try:
                        formatted_power = f"{power:,}".replace(',', ' ')
                    except Exception:
                        formatted_power = str(power)
                    # bonus in source appears to be in hundredths of a percent (e.g. 4500 -> 45.00%)
                    raw_bonus = m.get('bonus_percent', 0)
                    try:
                        bonus_val = float(raw_bonus)
                    except Exception:
                        bonus_val = 0.0
                    bonus_pct = bonus_val / 100.0
                    # format with comma as decimal separator, drop unnecessary zeros (45.00 -> 45%)
                    if abs(bonus_pct - round(bonus_pct)) < 1e-9:
                        bonus_str = f"{int(round(bonus_pct))}%"
                    else:
                        s = f"{bonus_pct:.2f}".rstrip('0').rstrip('.')
                        bonus_str = s.replace('.', ',') + '%'

                    # render miner: prepare label HTML (compact: no '— power' / '— bonus' words)
                    label_text = f"{label} lv{level} {formatted_power} {bonus_str}"
                    if label_style_attr:
                        label_html = f'<div class="label" {label_style_attr}>{label_text}</div>'
                    else:
                        label_html = f'<div class="label">{label_text}</div>'

                    parts.append(f'<div class="miner" style="left:{left_px}px;top:{top_px}px;min-width:{min_width}px;min-height:{min_height}px;{inline_extra}">{img_html}{label_html}</div>')
                    floor_units[fi] -= mw
                    floor_offsets[fi] += mw
                    placed = True
                    break
            if not placed:
                # if cannot place, append to legend later
                placed_miners.append(m)
                overflow_miners.append(m)

        parts.append('</div>')

    parts.append('</div>')
    # legend overflow
    parts.append('<div class="legend">')
    parts.append("<strong>Légende:</strong> miners non placés (s'il y en a) apparaissent ici.")
    # list overflow miners if any
    if 'overflow_miners' in locals() and overflow_miners:
        parts.append('<ul>')
        for om in overflow_miners:
            name = om.get('name') if not isinstance(om.get('name'), dict) else (om.get('name').get('en') or next(iter(om.get('name').values()), ''))
            # format overflow miner power
            try:
                om_power = int(float(om.get('power', 0)))
            except Exception:
                om_power = 0
            try:
                om_power_fmt = f"{om_power:,}".replace(',', ' ')
            except Exception:
                om_power_fmt = str(om_power)
            # format overflow bonus to human percent like above
            raw_b = om.get('bonus_percent', 0)
            try:
                bval = float(raw_b)
            except Exception:
                bval = 0.0
            b_pct = bval / 100.0
            if abs(b_pct - round(b_pct)) < 1e-9:
                b_str = f"{int(round(b_pct))}%"
            else:
                s = f"{b_pct:.2f}".rstrip('0').rstrip('.')
                b_str = s.replace('.', ',') + '%'
            parts.append('<li>' + escape(str(name)) + ' (width=' + str(int(om.get('width',1))) + ', power=' + om_power_fmt + ', bonus=' + b_str + ')</li>')
        parts.append('</ul>')
    parts.append('</div>')

    parts.append('</body></html>')

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(parts))
    # try to open the generated HTML in the default app/browser
    try:
        # Windows: open with default program
        if hasattr(os, 'startfile'):
            os.startfile(out_path)
        else:
            import webbrowser
            webbrowser.open('file://' + os.path.abspath(out_path))
    except Exception:
        try:
            import webbrowser
            webbrowser.open('file://' + os.path.abspath(out_path))
        except Exception:
            pass

    return out_path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--layout', default=os.path.join(os.path.dirname(__file__), 'room_layout_optimal.json'))
    p.add_argument('--icons', default=os.path.join(os.path.dirname(__file__), 'icons'))
    p.add_argument('--out', default=os.path.join(os.path.dirname(__file__), 'room_layout_visual.html'))
    args = p.parse_args()

    if not os.path.exists(args.layout):
        print('Fichier layout introuvable:', args.layout)
        return
    layout = json.load(open(args.layout, 'r', encoding='utf-8'))

    out = generate_html(layout, args.icons, args.out)
    print('Page HTML générée:', out)

if __name__ == '__main__':
    main()
