#!/usr/bin/env python3
"""ShatterStop Video Bot.

Every run: pulls the live product list from the store, picks the next product
in the rotation, writes the script (EN or ES), renders a vertical video, and
posts it as a Reel on the Facebook Page through Meta's official Graph API.

Env vars:
  MAKE_WEBHOOK_URL  Make.com webhook that posts the video to the ShatterStop Page (no Meta developer account needed)
  FB_PAGE_ID / FB_PAGE_TOKEN  optional direct Graph API route instead of Make
  STORE_URL       default https://jdzpva-zd.myshopify.com
  SLOT            post of the day, 0..POSTS_PER_DAY-1 (default from the UTC hour)
  LANG_MODE       alternate (default), en, es, or both

Usage:
  python videobot.py --dry-run                 render the next video, do not post
  python videobot.py                           render and post
  python videobot.py --product <handle> --lang es --dry-run
  python videobot.py --render-all              render every product in both languages (preview)
  python videobot.py --calendar 7              print the plan for the next 7 days
"""
import argparse, datetime as dt, html, json, os, random, re, sys, time, urllib.request
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.environ.get("STORE_URL", "https://jdzpva-zd.myshopify.com").rstrip("/")
GRAPH = "https://graph.facebook.com/v21.0"
# 8 posts a day, every 90 minutes from 8:00 AM to 6:30 PM Eastern (UTC times, daylight saving)
SLOT_MINUTES_UTC = [720, 810, 900, 990, 1080, 1170, 1260, 1350]
POSTS_PER_DAY = int(os.environ.get("POSTS_PER_DAY", str(len(SLOT_MINUTES_UTC))))
OUT = os.path.join(HERE, "out")
BRAND_SHORT = os.environ.get("BRAND_NAME", "AstraPoint")

SCRIPTS = json.load(open(os.path.join(HERE, "scripts.json"), encoding="utf-8"))
CODES = json.load(open(os.path.join(HERE, "codes.json"), encoding="utf-8"))

# ---------------------------------------------------------------- store
def fetch_products():
    r = requests.get(f"{STORE}/products.json?limit=250", headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    items = []
    for p in r.json().get("products", []):
        avail = [v for v in p.get("variants", []) if v.get("available")]
        if not avail or not p.get("images"):
            continue
        items.append(dict(id=p["id"], title=p["title"].strip(), type=p.get("product_type") or "", handle=p["handle"],
                          price=min(float(v["price"]) for v in avail), images=[i["src"] for i in p["images"]],
                          body=p.get("body_html") or ""))
    items.sort(key=lambda x: x["id"])
    return items

# ---------------------------------------------------------------- scripts
HOOKS = {
    "en": {"Car Accessories": ["Your car is missing this.", "Every driver should have one of these.", "Small upgrade. Big difference."],
           "Gadgets": ["The gadget everybody asks about.", "Didn't know I needed this. Now I use it daily."],
           "Home & Kitchen": ["Your room, upgraded.", "Small thing. Whole new vibe."],
           "Beauty": ["Your routine, but easier.", "Salon results. At home."],
           "Health & Wellness": ["Long day? This fixes that.", "The best fifteen minutes of your day."],
           "": ["New drop just landed."]},
    "es": {"Car Accessories": ["A su carro le falta esto.", "Todo conductor debería tener uno.", "Un detalle pequeño. Una gran diferencia."],
           "Gadgets": ["El aparato que todos preguntan.", "No sabía que lo necesitaba. Ahora lo uso diario."],
           "Home & Kitchen": ["Su cuarto, a otro nivel.", "Algo pequeño. Otro ambiente."],
           "Beauty": ["Su rutina, más fácil.", "Resultados de salón. En casa."],
           "Health & Wellness": ["¿Día largo? Esto lo arregla.", "Los mejores quince minutos de su día."],
           "": ["Acaba de llegar algo nuevo."]},
}

def auto_script(p, lang):
    """Fallback for products added later that have no hand written script."""
    rnd = random.Random(p["handle"] + lang)
    hook = rnd.choice(HOOKS[lang].get(p["type"], HOOKS[lang][""]))
    pieces = [x.strip() for x in re.split(r",| with | and ", p["title"]) if x.strip()]
    chips = [x.upper()[:24] for x in pieces[:3]] or [p["title"].upper()[:24]]
    while len(chips) < 3: chips.append({"en": "SHIPS FROM THE US", "es": "ENVÍO DESDE EE.UU."}[lang] if len(chips) == 1 else
                                       {"en": "TRACKING ON EVERY ORDER", "es": "CON NÚMERO DE RASTREO"}[lang])
    say = (f"{pieces[0]}." if lang == "en" else f"{pieces[0]}.")  # title is English; keep the spoken part short
    if lang == "en" and len(pieces) > 1: say += " " + ". ".join(pieces[1:3]) + "."
    return {"hook": hook, "say": say, "chips": chips}

def script_for(p, lang):
    return SCRIPTS.get(p["handle"], {}).get(lang) or auto_script(p, lang)

def code_for(p, lang, today=None):
    c = CODES.get(p["handle"])
    if not c or not c.get("active"): return None
    today = today or dt.date.today()
    end = dt.date.fromisoformat(c["ends"])
    if today > end: return None
    month_en = end.strftime("%B"); months_es = "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split()
    return dict(code=c["code"], off=float(c["off"]), spoken=c["spoken_" + lang],
                ends_text=(f"through {month_en} {end.day}" if lang == "en" else f"hasta el {end.day} de {months_es[end.month-1]}"),
                ends_label=(f"Through {end.strftime('%b')} {end.day}" if lang == "en" else f"Hasta el {end.day} de {months_es[end.month-1]}"))

# ---------------------------------------------------------------- rotation
def _order(n, cycle):
    def shuf(c, t=0):
        o = list(range(n)); random.Random(f"shatter-{c}-{t}").shuffle(o); return o
    if cycle == 0: return shuf(0)
    prev = _order(n, cycle - 1); gap = min(6, n // 3)
    for t in range(200):
        o = shuf(cycle, t)
        if not set(o[:gap]) & set(prev[-gap:]): return o
    return shuf(cycle)

def pick(products, day, slot):
    n = len(products); k = day * POSTS_PER_DAY + slot
    cycle, pos = divmod(k, n)
    i = _order(n, cycle)[pos]
    return products[i], k + (i + cycle) % 2 - k % 2  # language flips each time a product comes back around

def langs_for(k):
    mode = os.environ.get("LANG_MODE", "alternate")
    if mode == "both": return ["en", "es"]
    if mode in ("en", "es"): return [mode]
    return ["en" if k % 2 == 0 else "es"]

# ---------------------------------------------------------------- caption
def caption(p, lang, script, code, k):
    link = f"{STORE}/products/{p['handle']}?utm_source=facebook&utm_medium=reel&utm_campaign=videobot_{lang}"
    rnd = random.Random(f"{p['id']}-{k}")
    if lang == "en":
        cta = rnd.choice(["Grab yours here 👇", "Order here 👇 Ships from US warehouses.", "Shop it here 👇 Tracking on every order."])
        price = f"💲 ${p['price']:.2f}"
        if code: price += f"\n🏷️ Code {code['code']} takes ${code['off']:.0f} off ({code['ends_label']})"
        local = "📍 Greenville owned, ships to your door."
        tags = "#greenvillesc #upstatesc #" + re.sub(r"[^a-z]", "", (p["type"] or "deals").lower())
    else:
        cta = rnd.choice(["Pídalo aquí 👇", "Ordene aquí 👇 Envío desde almacenes en EE.UU.", "Cómprelo aquí 👇 Con número de rastreo."])
        price = f"💲 ${p['price']:.2f}"
        if code: price += f"\n🏷️ Con el código {code['code']}, ${code['off']:.0f} menos ({code['ends_label']})"
        local = "📍 De aquí de Greenville, llega a su puerta."
        tags = "#greenvillesc #upstatesc #latinosengreenville"
    hook = script["hook"]
    return f"{hook}\n\n{p['title']}\n{price}\n{local}\n\n{cta}\n{link}\n\n{tags}"

# ---------------------------------------------------------------- facebook
def fb_reel(video_path, description):
    page, tok = os.environ["FB_PAGE_ID"], os.environ["FB_PAGE_TOKEN"]
    r = requests.post(f"{GRAPH}/{page}/video_reels", data={"upload_phase": "start", "access_token": tok}, timeout=60)
    if r.status_code != 200: raise RuntimeError(f"reel start failed: {r.text[:400]}")
    vid = r.json()["video_id"]; up = r.json().get("upload_url") or f"https://rupload.facebook.com/video-upload/v21.0/{vid}"
    size = os.path.getsize(video_path)
    with open(video_path, "rb") as fh:
        u = requests.post(up, headers={"Authorization": f"OAuth {tok}", "offset": "0", "file_size": str(size)}, data=fh, timeout=600)
    if u.status_code != 200: raise RuntimeError(f"reel upload failed: {u.text[:400]}")
    f = requests.post(f"{GRAPH}/{page}/video_reels", data={"upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED",
                                                         "description": description, "access_token": tok}, timeout=120)
    if f.status_code != 200 or not f.json().get("success", True): raise RuntimeError(f"reel publish failed: {f.text[:400]}")
    return {"reel_video_id": vid}

def fb_video(video_path, description):
    page, tok = os.environ["FB_PAGE_ID"], os.environ["FB_PAGE_TOKEN"]
    with open(video_path, "rb") as fh:
        r = requests.post(f"https://graph-video.facebook.com/v21.0/{page}/videos", data={"description": description, "access_token": tok},
                          files={"source": fh}, timeout=900)
    if r.status_code != 200: raise RuntimeError(f"video upload failed: {r.text[:400]}")
    return r.json()

def post_facebook(video_path, description):
    try:
        return fb_reel(video_path, description)
    except Exception as e:
        print("Reel upload did not work, posting as a regular Page video instead:", e)
        return fb_video(video_path, description)

# ---------------------------------------------------------------- run
def build(p, lang, k, today=None):
    from render import make_video
    os.makedirs(OUT, exist_ok=True)
    s = script_for(p, lang); c = code_for(p, lang, today)
    mp4 = os.path.join(OUT, f"{p['handle']}_{lang}.mp4")
    make_video(p, lang, s, mp4, code=c, workdir=os.path.join(OUT, "work", f"{p['handle']}_{lang}"))
    return mp4, caption(p, lang, s, c, k)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--product"); ap.add_argument("--lang")
    ap.add_argument("--render-all", action="store_true")
    ap.add_argument("--calendar", type=int, default=0)
    a = ap.parse_args()
    products = fetch_products()
    if not products: sys.exit("No available products found.")
    day = (dt.date.today() - dt.date(2026, 1, 1)).days
    if a.calendar:
        for d in range(a.calendar):
            for s in range(POSTS_PER_DAY):
                p, k = pick(products, day + d, s)
                print(f"{dt.date.today() + dt.timedelta(days=d)} slot {s}: {p['title']} ({'/'.join(langs_for(k))})")
        return
    if a.render_all:
        for i, p in enumerate(products):
            for lang in ("en", "es"):
                mp4, cap = build(p, lang, i); open(mp4[:-4] + ".txt", "w", encoding="utf-8").write(cap)
        return
    if a.product:
        p = next(x for x in products if x["handle"] == a.product); k = 0
    else:
        now = dt.datetime.utcnow(); m = now.hour * 60 + now.minute
        slot = int(os.environ.get("SLOT", min(range(len(SLOT_MINUTES_UTC)), key=lambda i: abs(SLOT_MINUTES_UTC[i] - m)) % POSTS_PER_DAY))
        p, k = pick(products, day, slot)
    for lang in ([a.lang] if a.lang else langs_for(k)):
        mp4, cap = build(p, lang, k)
        print(f"\nProduct: {p['title']} [{lang}]\nVideo: {mp4}\n---\n{cap}\n---")
        if a.dry_run:
            print("DRY RUN, nothing posted."); continue
        if os.environ.get("MAKE_WEBHOOK_URL"):
            # Make.com route: the workflow hosts the video and hands it to Make, which posts it to the Page
            short = re.sub(r"[0-9]", "", script_for(p, lang)["hook"]).strip() or BRAND_SHORT
            job = dict(file=mp4, name=os.path.basename(mp4), caption=cap, short=short, title=p["title"].split(",")[0],
                       product=p["handle"], lang=lang)
            json.dump(job, open(mp4[:-4] + ".json", "w", encoding="utf-8"), ensure_ascii=False)
            print("Queued for Make:", mp4[:-4] + ".json"); continue
        for var in ("FB_PAGE_ID", "FB_PAGE_TOKEN"):
            if not os.environ.get(var): sys.exit("Missing MAKE_WEBHOOK_URL (or FB_PAGE_ID + FB_PAGE_TOKEN).")
        print("Facebook:", post_facebook(mp4, cap))

if __name__ == "__main__":
    main()
