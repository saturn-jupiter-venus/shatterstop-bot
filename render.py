"""Renders one vertical promo video (1080x1920) for one product.

make_video(product, lang, script, out_mp4, code=None)
  product: dict with title, price, handle, images (urls)
  script:  {"hook": str, "say": str, "chips": [3 short labels]}
  code:    optional dict {"code","spoken","off","ends_text"} for a REAL, active Shopify discount
"""
import os, io, re, json, math, base64, random, subprocess, tempfile, wave, asyncio, urllib.request
from xml.sax.saxutils import escape
import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage
import cairosvg
import audio as A
from audio import SR, place, kick, clap, hat, lp, hp, saw, sine, note, env, noise

FPS = 24
CY, PU, PK, BG, MUT = "#00e5ff", "#8b5cf6", "#ff3df5", "#07070c", "#8a8fa8"
VOICE = {"en": "en-US-AndrewMultilingualNeural", "es": "es-MX-JorgeNeural"}
RATE = {"en": "+4%", "es": "+8%"}
BRAND = os.environ.get("BRAND_NAME", "AstraPoint")
END = {"en": f"{BRAND}. Greenville owned. Link in the post.", "es": f"{BRAND}. De aquí de Greenville. El enlace está en la publicación."}
UI = {"en": dict(tag="Greenville owned", link="Link in the post", ships="Ships from US warehouses", code="With code", price="Price"),
      "es": dict(tag="De aquí de Greenville", link="Enlace en la publicación", ships="Envío desde almacenes en EE.UU.", code="Con el código", price="Precio")}

# ------------------------------------------------------------------ words
_EN = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
_ENT = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
_ES = ("cero uno dos tres cuatro cinco seis siete ocho nueve diez once doce trece catorce quince dieciséis diecisiete dieciocho diecinueve "
       "veinte veintiuno veintidós veintitrés veinticuatro veinticinco veintiséis veintisiete veintiocho veintinueve").split()
_EST = "_ _ veinte treinta cuarenta cincuenta sesenta setenta ochenta noventa".split()
def n2w(n, lang):
    if lang == "en":
        if n < 20: return _EN[n]
        return _ENT[n // 10] + ("" if n % 10 == 0 else " " + _EN[n % 10])
    if n < 30: return _ES[n]
    return _EST[n // 10] + ("" if n % 10 == 0 else " y " + _ES[n % 10])
def price_words(p, lang):
    d, c = int(p), int(round((p - int(p)) * 100))
    if d >= 100: return f"${p:.2f}"
    if c == 0: return n2w(d, lang) + (" dollars" if lang == "en" else " dólares")
    return f"{n2w(d, lang)} {n2w(c, lang)}"

# ------------------------------------------------------------------ images
def fetch_images(urls, cache, n=4):
    os.makedirs(cache, exist_ok=True); out = []
    for i, u in enumerate(urls[:n]):
        p = os.path.join(cache, f"{i}.jpg")
        if not os.path.exists(p):
            req = urllib.request.Request(u + ("&" if "?" in u else "?") + "width=1200", headers={"User-Agent": "Mozilla/5.0"})
            raw = urllib.request.urlopen(req, timeout=60).read()
            im = Image.open(io.BytesIO(raw)).convert("RGB"); im.thumbnail((1200, 1200)); im.save(p, quality=90)
        out.append(p)
    return out

def white_bg(im):
    a = np.asarray(im.convert("RGB")).astype(int)
    border = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    return (border.min(axis=1) > 230).mean() > .85

def cutout(path, out):
    im = Image.open(path).convert("RGB"); a = np.asarray(im).astype(int)
    white = a.min(axis=2) > 232
    lab, _ = ndimage.label(white)
    border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
    bg = np.isin(lab, list(border))
    alpha = Image.fromarray(((~bg) * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(1.2))
    im.putalpha(alpha); bb = im.getbbox()
    if not bb: return None
    im = im.crop(bb); im.thumbnail((1000, 1000)); im.save(out)
    return out

def b64(path):
    return base64.b64encode(open(path, "rb").read()).decode()

# ------------------------------------------------------------------ audio
async def _tts(voice, text, out, rate):
    import edge_tts
    kw = {"proxy": os.environ["HTTPS_PROXY"]} if os.environ.get("HTTPS_PROXY") else {}
    await edge_tts.Communicate(text, voice, rate=rate, **kw).save(out)

def tts(text, lang, out_wav):
    mp3 = out_wav[:-4] + ".mp3"
    for attempt in range(3):
        try: asyncio.run(_tts(VOICE[lang], text, mp3, RATE[lang])); break
        except Exception:
            if attempt == 2: raise
    trim = "silenceremove=start_periods=1:start_threshold=-42dB,areverse,silenceremove=start_periods=1:start_threshold=-42dB,areverse,"
    fx = "aresample=44100,highpass=f=80,lowpass=f=10500,acompressor=threshold=-20dB:ratio=2.5:attack=8:release=120:makeup=2dB,bass=g=1.5"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", mp3, "-af", trim + fx, "-ac", "1", "-ar", str(SR), out_wav], check=True)
    with wave.open(out_wav) as w: return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768

def score(total, drop, seed):
    rnd = random.Random(seed); N = int(total * SR) + SR
    music = np.zeros(N); bpm = rnd.choice([90, 94, 98, 102]); b = 60 / bpm
    progs = [[(45, 52, 60), (41, 48, 57), (43, 50, 59), (40, 47, 55)], [(45, 52, 60), (43, 50, 59), (41, 48, 57), (41, 48, 57)],
             [(40, 47, 55), (36, 43, 52), (43, 50, 59), (38, 45, 53)]]
    prog = rnd.choice(progs); tr = rnd.choice([-2, 0, 1, 3])
    def pad(ns, d): return sum(lp(saw(note(n + tr) * (1 + dt), d), 900) for n in ns for dt in (-.004, .004)) * env(int(d * SR), .8, .2, .9, .8)
    T, bar = 0.0, 0
    while T < total + 2:
        ns = prog[bar % 4]; place(music, pad(ns, 4 * b) * .035, T)
        if T < drop - .05:
            for q in (0, 2): place(music, kick() * .35, T + q * b)
        else:
            for q, k_ in ((0, 1), (1.5, .7), (2.5, .8)): place(music, kick() * .7 * k_, T + q * b)
            place(music, clap() * .45, T + b); place(music, clap() * .45, T + 3 * b)
            for e in range(8): place(music, hat(e % 4 == 3) * .5, T + e * b / 2)
            if bar % 2: [place(music, hat() * .35, T + 3 * b + e * b / 4) for e in range(4)]
            d = 4 * b * .95; sub = sine(note(ns[0] - 12 + tr), d) * env(int(d * SR), .01, .3, .8, .2)
            place(music, lp(np.tanh(sub * 1.5), 300) * .35, T)
        T += 4 * b; bar += 1
    fx = np.zeros(N)
    r = hp(noise(.9), 2000) * np.linspace(0, 1, int(.9 * SR)) ** 2
    place(fx, lp(r, 7000) * .12, drop - .9); place(fx, A.s_boom() * .8, drop); place(fx, A.timpani(41, 1.6) * .5, drop)
    return music, fx

# ------------------------------------------------------------------ visuals
DEFS = f'''<defs>
<radialGradient id="glow1" r=".5"><stop offset="0" stop-color="{CY}" stop-opacity=".35"/><stop offset="1" stop-color="{CY}" stop-opacity="0"/></radialGradient>
<radialGradient id="glow2" r=".5"><stop offset="0" stop-color="{PU}" stop-opacity=".35"/><stop offset="1" stop-color="{PU}" stop-opacity="0"/></radialGradient>
<linearGradient id="shade" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#000" stop-opacity=".6"/><stop offset=".5" stop-color="#000" stop-opacity=".45"/><stop offset="1" stop-color="#000" stop-opacity=".92"/></linearGradient>
<linearGradient id="line" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{CY}"/><stop offset="1" stop-color="{PK}"/></linearGradient>
<filter id="blur"><feGaussianBlur stdDeviation="18"/></filter>
<filter id="shadow" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="20" stdDeviation="24" flood-color="#000" flood-opacity=".7"/></filter>
</defs>'''
def svg(body): return f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="1080" height="1920" viewBox="0 0 1080 1920">{DEFS}<rect width="1080" height="1920" fill="{BG}"/>{body}</svg>'
def ease(x): x = max(0., min(1., x)); return 1 - (1 - x) ** 3
def T(x, y, txt, size, fill="#fff", weight=700, anchor="middle", op=1, ls=0):
    return f'<text x="{x}" y="{y}" font-family="Space Grotesk" font-weight="{weight}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" opacity="{op}" letter-spacing="{ls}">{escape(txt)}</text>'
def wrap(txt, n):
    rows, cur = [], []
    for w in txt.split():
        if cur and len(" ".join(cur + [w])) > n: rows.append(" ".join(cur)); cur = [w]
        else: cur.append(w)
    rows.append(" ".join(cur)); return rows
def card(data, mime, x, y, w, h, z=1.0, fit="slice", rx=40):
    cid = f"c{int(x)}{int(y)}{int(w)}"; cx, cy = x + w / 2, y + h / 2
    return (f'<clipPath id="{cid}"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}"/></clipPath><g clip-path="url(#{cid})"><rect x="{x}" y="{y}" width="{w}" height="{h}" fill="#fff"/>'
            f'<g transform="translate({cx},{cy}) scale({z}) translate({-cx},{-cy})"><image x="{x}" y="{y}" width="{w}" height="{h}" preserveAspectRatio="xMidYMid {fit}" xlink:href="data:{mime};base64,{data}"/></g></g>')
def floatimg(data, size, cx, cy, w, z=1.0, rot=0):
    W0, H0 = size; h = w * H0 / W0
    return (f'<g transform="translate({cx},{cy}) scale({z}) rotate({rot})" filter="url(#shadow)"><image x="{-w/2}" y="{-h/2}" width="{w}" height="{h}" '
            f'xlink:href="data:image/png;base64,{data}"/></g>')

# ------------------------------------------------------------------ main
def make_video(product, lang, script, out_mp4, code=None, workdir=None, log=print):
    wd = workdir or tempfile.mkdtemp(prefix="vb_"); os.makedirs(wd, exist_ok=True)
    seed = f"{product['handle']}-{lang}"
    ui = UI[lang]
    # images
    imgs = fetch_images(product["images"], os.path.join(wd, "img"), n=6)
    hero = imgs[0]; cut = None
    wb = [p for p in imgs if white_bg(Image.open(p))]
    if wb: cut = cutout(wb[0], os.path.join(wd, "cut.png"))
    imgs = imgs[:4]
    ALL = [b64(p) for p in imgs]
    bgimg = next((p for p in imgs if not white_bg(Image.open(p))), imgs[0])
    bim = Image.open(bgimg).convert("RGB"); bim = bim.resize((540, int(540 * bim.height / bim.width)))
    bim = bim.filter(ImageFilter.GaussianBlur(8)); bim.save(os.path.join(wd, "bgblur.jpg"), quality=85)
    BGB = b64(os.path.join(wd, "bgblur.jpg")); HERO = b64(cut) if cut else b64(hero); HSZ = Image.open(cut).size if cut else None
    # lines
    price_line = price_words(product["price"], lang) + "."
    if code:
        price_line += (f" Code {code['spoken']} takes {n2w(int(code['off']), 'en')} off {code['ends_text']}." if lang == "en" else
                       f" Con el código {code['spoken']}, {n2w(int(code['off']), 'es')} dólares menos {code['ends_text']}.")
    else:
        price_line += " Ships from US warehouses." if lang == "en" else " Envío desde almacenes en Estados Unidos."
    parts = [("hook", script["hook"]), ("say", script["say"]), ("price", price_line), ("end", END[lang])]
    gaps = {"hook": .55, "say": .35, "price": .4, "end": 1.4}
    tl, t, voices = [], .5, []
    for i, (shot, text) in enumerate(parts):
        x = tts(text, lang, os.path.join(wd, f"v{i}.wav")); d = len(x) / SR
        tl.append(dict(shot=shot, text=text, start=t, dur=d)); voices.append((x, t)); t += d + gaps[shot]
    total = t; drop = tl[1]["start"]
    # mix
    music, fx = score(total, drop, seed)
    N = len(music); voice = np.zeros(N)
    for x, st in voices: place(voice, x * (10 ** (-18 / 20) / (np.sqrt(np.mean(x ** 2)) + 1e-9)), st)
    def rms(a): return float(np.sqrt(np.mean(a ** 2)) + 1e-9)
    music *= 10 ** (-22 / 20) / rms(music[int(drop * SR):int(total * SR)])
    fx *= 10 ** (-20 / 20) / (np.max(np.abs(fx)) + 1e-9) * 4
    act = (np.abs(voice) > 10 ** (-45 / 20)).astype(float); k = int(.3 * SR)
    act = np.clip(np.convolve(act, np.ones(k) / k, "same") * 3, 0, 1); music *= 1 - act * (1 - 10 ** (-9 / 20))
    mix = (voice + music + fx)[:int(total * SR)]; e = int(1.2 * SR); mix[-e:] *= np.linspace(1, 0, e)
    mix /= max(1, np.max(np.abs(mix)) / .89)
    A.write(os.path.join(wd, "mix.wav"), mix)
    js = subprocess.run(["ffmpeg", "-hide_banner", "-i", f"{wd}/mix.wav", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                        capture_output=True, text=True).stderr
    m = json.loads(js[js.rindex("{"):js.rindex("}") + 1])
    ln = (f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
          f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true,alimiter=limit=0.84:attack=3:release=60:level=disabled")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", f"{wd}/mix.wav", "-af", ln, "-ar", "44100", f"{wd}/master.wav"], check=True)

    title_rows = wrap(re.split(r",| with ", product["title"])[0], 24)[:2]
    def at(tt):
        cur = tl[0]
        for L in tl:
            if tt >= L["start"] - .02: cur = L
        return cur
    def frame(f):
        tt = f / FPS; L = at(tt); lt = tt - L["start"]; sh = L["shot"]; b = ""
        if sh == "hook":
            b += f'<g><image x="-200" y="-100" width="1480" height="2120" preserveAspectRatio="xMidYMid slice" xlink:href="data:image/jpeg;base64,{BGB}" transform="translate(540,960) scale({1.05 + .02*tt}) translate(-540,-960)"/></g>'
            b += '<rect width="1080" height="1920" fill="url(#shade)"/><rect width="1080" height="1920" fill="#05050a" opacity=".35"/>'
            words = L["text"].split(); n = len(words)
            shown = max(1, min(n, int(n * (lt + .2) / max(.4, L["dur"])) + 1))
            rows = wrap(" ".join(words[:shown]), 18)
            for j, r in enumerate(rows):
                b += T(540, 960 + (j - (len(rows) - 1) / 2) * 104, r, 88)
            b += f'<rect x="440" y="{960 + len(rows)*52 + 40}" width="200" height="6" fill="url(#line)" opacity="{ease(lt/.4)}"/>'
        elif sh == "say":
            chips = script["chips"][:3]; nC = len(chips)
            j = min(nC - 1, int(lt / max(.5, L["dur"]) * nC)) if lt >= 0 else 0
            flash = max(0, 1 - lt / .25)
            b += '<circle cx="540" cy="760" r="760" fill="url(#glow1)"/><circle cx="540" cy="1100" r="700" fill="url(#glow2)"/>'
            if j == 0 and cut:
                b += floatimg(HERO, HSZ, 540, 760, 860, 1 + .05 * lt, -2 + lt)
            else:
                data = ALL[j % len(ALL)] if len(ALL) > 1 else ALL[0]
                b += f'<g filter="url(#shadow)">{card(data, "image/jpeg", 90, 260, 900, 900, 1.06 - .04 * min(1, lt / 3))}</g>'
                b += '<rect x="90" y="260" width="900" height="900" rx="40" fill="none" stroke="url(#line)" stroke-width="5"/>'
            for r_, row in enumerate(title_rows):
                b += T(540, 170 + r_ * 62, row.upper(), 46 if len(title_rows) > 1 else 50, CY, 700, ls=3, op=ease(lt / .3))
            for i, lab in enumerate(chips):
                t0 = L["dur"] * i / nC; k = ease((lt - t0) / .25); on = i == j
                size = 48 if len(lab) < 18 else 38
                b += (f'<g transform="translate({540 + (1-k)*-80},{1300 + i*120})" opacity="{k*(1 if on else .4)}">'
                      f'<rect x="-420" y="-52" width="840" height="104" rx="52" fill="{"#0e2a33" if on else "#12121c"}" stroke="{CY if on else "#2a2a3a"}" stroke-width="4"/>'
                      + T(0, 16, lab, size, "#fff", 700, ls=2) + '</g>')
            b += f'<rect width="1080" height="1920" fill="#fff" opacity="{flash*.85}"/>'
        elif sh == "price":
            b += '<circle cx="540" cy="640" r="700" fill="url(#glow1)"/>'
            if cut: b += floatimg(HERO, HSZ, 540, 600, 700, 1 + .02 * lt)
            else: b += f'<g filter="url(#shadow)">{card(b64(hero), "image/jpeg", 240, 260, 600, 600)}</g>'
            if code:
                b += T(540, 1040, ui["price"], 40, MUT, 500) + T(540, 1130, f"${product['price']:.2f}", 96, "#fff" if lt < 1.4 else MUT)
                if lt > 1.2:
                    k = ease((lt - 1.2) / .3); np_ = product["price"] - code["off"]
                    b += f'<line x1="380" y1="1100" x2="{380 + 320*k}" y2="1100" stroke="#ff2b3d" stroke-width="8"/>'
                    b += f'<g opacity="{k}">' + T(540, 1300, f"${np_:.2f}", 150) + T(540, 1370, ui["code"], 40, MUT, 500)
                    b += f'<rect x="300" y="1410" width="480" height="110" rx="55" fill="none" stroke="{PK}" stroke-width="5"/>' + T(540, 1485, code["code"], 64, PK, 700, ls=6)
                    b += T(540, 1600, code["ends_label"], 40, "#fff", 500, op=.8) + '</g>'
            else:
                k = ease(lt / .35)
                b += f'<g opacity="{k}" transform="translate(0,{(1-k)*30})">' + T(540, 1180, f"${product['price']:.2f}", 170)
                b += T(540, 1280, ui["ships"], 42, "#fff", 500, op=.85) + '</g>'
        else:
            b += '<circle cx="540" cy="760" r="650" fill="url(#glow2)"/>'
            if cut: b += f'<g opacity="{ease(lt/.5)}">{floatimg(HERO, HSZ, 540, 700, 560)}</g>'
            b += T(540, 1120, BRAND, 120, op=ease((lt - .1) / .35))
            kk = ease((lt - .3) / .5); b += f'<rect x="{540 - 220*kk}" y="1160" width="{440*kk}" height="5" fill="url(#line)"/>'
            b += T(540, 1240, ui["tag"], 46, MUT, 500, op=ease((lt - .5) / .35), ls=2)
            b += T(540, 1400, ui["link"], 56, CY, 700, op=ease((lt - 1.0) / .35))
        return svg(b)
    fr = os.path.join(wd, "frames"); os.makedirs(fr, exist_ok=True)
    n = int(total * FPS)
    for f in range(n):
        cairosvg.svg2png(bytestring=frame(f).encode(), write_to=f"{fr}/{f:05d}.png", output_width=1080, output_height=1920)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", f"{fr}/%05d.png", "-i", f"{wd}/master.wav",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                    "-shortest", "-movflags", "+faststart", out_mp4], check=True)
    log(f"rendered {out_mp4} ({total:.1f}s)")
    return out_mp4
