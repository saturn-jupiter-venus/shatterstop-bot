"""Procedural score + SFX for the promo. All original, generated with numpy."""
import numpy as np
from scipy import signal
SR = 44100
rng = np.random.default_rng(7)

def t_(d): return np.arange(int(d * SR)) / SR
def note(n): return 440.0 * 2 ** ((n - 69) / 12)  # midi -> hz
def env(n, a=0.01, d=0.1, s=0.7, r=0.2):
    a_, d_, r_ = int(a * SR), int(d * SR), int(r * SR); e = np.ones(n) * s
    e[:a_] = np.linspace(0, 1, a_) if a_ else e[:a_]
    if a_ + d_ < n: e[a_:a_ + d_] = np.linspace(1, s, d_)
    if r_ < n: e[-r_:] *= np.linspace(1, 0, r_)
    return e
def lp(x, fc, o=2): b, a = signal.butter(o, min(fc, SR / 2 - 100) / (SR / 2)); return signal.lfilter(b, a, x)
def hp(x, fc, o=2): b, a = signal.butter(o, fc / (SR / 2), 'high'); return signal.lfilter(b, a, x)
def bp(x, lo, hi, o=2): b, a = signal.butter(o, [lo / (SR / 2), min(hi, SR / 2 - 100) / (SR / 2)], 'band'); return signal.lfilter(b, a, x)
def _blep(ph, dt):
    out = np.zeros_like(ph)
    m = ph < dt; x = ph[m] / dt; out[m] = x + x - x * x - 1
    m = ph > 1 - dt; x = (ph[m] - 1) / dt; out[m] = x * x + x + x + 1
    return out
def saw(f, d):  # band-limited (polyBLEP)
    t = t_(d); dt = f / SR; ph = (t * f) % 1
    return (2 * ph - 1) - _blep(ph, dt)
def sq(f, d):
    t = t_(d); dt = f / SR; ph = (t * f) % 1
    return np.where(ph < .5, 1.0, -1.0) + _blep(ph, dt) - _blep((ph + .5) % 1, dt)
def sine(f, d): return np.sin(2 * np.pi * f * t_(d))
def noise(d): return rng.standard_normal(int(d * SR))
def norm(x, peak=0.9): m = np.max(np.abs(x)) or 1; return x / m * peak
def reverb(x, decay=1.6, mix=0.25):
    ir = noise(decay) * np.exp(-np.linspace(0, 6, int(decay * SR))); ir = lp(ir, 6000); ir /= np.sum(np.abs(ir)) / 30
    wet = signal.fftconvolve(x, ir)[:len(x)]; return x * (1 - mix) + norm(wet, np.max(np.abs(x))) * mix
def place(buf, x, at):
    i = int(at * SR)
    if i >= len(buf) or i < 0: return
    j = min(len(buf), i + len(x)); buf[i:j] += x[:j - i]

# ---------- instruments ----------
def epiano(f, d): t = t_(d); x = sum(np.sin(2 * np.pi * f * k * t) / k ** 1.6 for k in (1, 2, 3, 4)); return x * np.exp(-t * 2.2)
def pad(f, d): x = sum(saw(f * (1 + dt), d) for dt in (-0.004, 0, 0.005)); return lp(x, 1800) * env(len(x), .4, .2, .8, .6)
def strings(f, d, trem=0):
    x = sum(saw(f * (1 + dt), d) for dt in (-0.006, -0.002, 0.003, 0.007)); x = lp(x, 2500) * env(len(x), .25, .1, .9, .4)
    if trem: x *= 0.6 + 0.4 * np.sin(2 * np.pi * trem * t_(d))
    return x
def brass(f, d):
    t = t_(d); x = sum(saw(f * k * (1 + 0.003 * k), d) / k for k in (1, 2)); fc = 600 + 3500 * np.exp(-t * 3)
    y = np.zeros_like(x);
    for k in range(0, len(x), 2048): y[k:k + 2048] = lp(x[k:k + 2048], fc[k])
    return y * env(len(x), .03, .2, .8, .3)
def kick(): t = t_(0.35); f = 45 + 110 * np.exp(-t * 30); return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)
def snare(): t = t_(0.25); return (bp(noise(.25), 1500, 8000) * 0.7 + np.sin(2 * np.pi * 190 * t) * 0.5) * np.exp(-t * 18)
def hat(open_=False): d = .25 if open_ else .05; return lp(hp(noise(d), 6000), 10000) * np.exp(-t_(d) * (12 if open_ else 80)) * 0.18
def clap(): x = np.zeros(int(.2 * SR)); [place(x, bp(noise(.12), 900, 5000) * np.exp(-t_(.12) * 30), k * .012) for k in range(3)]; return x
def timpani(f=55, d=1.2): t = t_(d); return (np.sin(2 * np.pi * f * t) + .4 * np.sin(2 * np.pi * f * 1.5 * t) + .2 * lp(noise(d), 300)) * np.exp(-t * 3)
def bell(f, d=1.2): t = t_(d); return sum(np.sin(2 * np.pi * f * r * t) * a for r, a in ((1, 1), (2.76, .5), (5.4, .25), (8.9, .1)) if f * r < 9000) * np.exp(-t * 4)

# ---------- music cues (return arrays of exact length) ----------
def m_intro(d):
    buf = np.zeros(int(d * SR) + SR); bpm = 82; b = 60 / bpm
    chords = [[60, 64, 67, 71], [57, 60, 64, 67], [53, 57, 60, 64], [55, 59, 62, 65]]
    for k in range(int(d / (b * 4)) + 1):
        ch = chords[k % 4]
        for n in ch: place(buf, epiano(note(n), b * 4) * 0.16, k * b * 4)
        place(buf, sine(note(ch[0] - 24), b * 4) * env(int(b * 4 * SR), .02, .3, .5, .3) * .25, k * b * 4)
        for q in range(8): place(buf, hat() * .6, k * b * 4 + q * b / 2)
        place(buf, kick() * .5, k * b * 4); place(buf, kick() * .4, k * b * 4 + b * 2.5); place(buf, snare() * .25, k * b * 4 + b); place(buf, snare() * .25, k * b * 4 + b * 3)
    buf += lp(rng.standard_normal(len(buf)), 3000) * 0.006 * (rng.random(len(buf)) > .998)  # vinyl crackle
    for k in range(0):  # birds removed
        f0 = 3000 + rng.random() * 1500; tt = t_(.12); place(buf, np.sin(2 * np.pi * np.cumsum(f0 + 1500 * np.sin(tt * 60)) / SR) * np.exp(-tt * 20) * .05, k * 2 + rng.random())
    return reverb(buf, 1.2, .18)[:int(d * SR)]

def m_tension(d):
    buf = np.zeros(int(d * SR) + SR)
    for n in (38, 45, 50): place(buf, strings(note(n), d + .5, trem=7) * .12, 0)
    place(buf, strings(note(65), d + .5, trem=7) * .05, 0)
    b = 60 / 72
    for k in range(int(d / b) + 1):  # heartbeat + taiko
        place(buf, kick() * .55, k * b); place(buf, kick() * .35, k * b + .18)
        if k % 4 == 3: place(buf, timpani(41) * .5, k * b + b / 2)
    return reverb(buf, 2.2, .3)[:int(d * SR)]

def m_sting():
    d = 3.2; buf = np.zeros(int(d * SR))
    for at, root in ((0, 50), (.45, 49), (.9, 46)):
        dur = .35 if at < .9 else 2.2
        for iv in (0, 7, 12, 15): place(buf, brass(note(root + iv - 12), dur) * .18, at)
        place(buf, timpani(note(root - 24), 1.4) * .7, at)
    place(buf, hp(noise(2.2), 4000) * np.exp(-t_(2.2) * 1.5) * .15, .9)  # cymbal
    return reverb(buf, 2.6, .35)

def m_suspense(d):
    buf = np.zeros(int(d * SR) + SR)
    for k in range(int(d / .5) + 1): place(buf, bp(noise(.03), 2000, 6000) * np.exp(-t_(.03) * 120) * (.5 if k % 2 else .3), k * .5)  # tick
    t = t_(d + .5); f = 55 * (1 + t / (d + .5)); place(buf, lp(np.sign(np.sin(2 * np.pi * np.cumsum(f) / SR)), 400) * .12 * (0.5 + 0.5 * np.sin(2 * np.pi * 4 * t)), 0)
    place(buf, strings(note(74), d + .5, trem=12) * .04, 0)
    return reverb(buf, 1.5, .2)[:int(d * SR)]

def m_hit():
    d = 2.5; buf = np.zeros(int(d * SR))
    for n in (48, 55, 60, 63, 67, 72): place(buf, brass(note(n), .5) * .14, 0)
    place(buf, timpani(55, 2) * .9, 0); place(buf, kick() * .8, 0)
    place(buf, hp(noise(2.4), 3500) * np.exp(-t_(2.4) * 1.3) * .22, 0)
    return reverb(buf, 2.5, .35)

def m_sad():
    d = 3.4; buf = np.zeros(int(d * SR))
    for k, (n, dur) in enumerate(((58, .45), (57, .45), (56, .45), (55, 1.6))):
        t = t_(dur); f = note(n) * (1 + .012 * np.sin(2 * np.pi * (5 if k == 3 else 0) * t))
        x = sum(np.sin(2 * np.pi * np.cumsum(f * h) / SR) / h ** 1.2 for h in range(1, 7))
        x = lp(x, 1400) * env(len(x), .05, .1, .8, .25) * (1 - .5 * (np.sin(np.pi * np.minimum(t * 4, 1)) ** 2) * 0)
        place(buf, x * .22, .12 + k * .5)
    return reverb(buf, 1.2, .2)

def m_hype(d):
    buf = np.zeros(int(d * SR) + SR); bpm = 118; b = 60 / bpm
    prog = [45, 45, 48, 43]
    for bar in range(int(d / (b * 4)) + 1):
        T = bar * b * 4; root = prog[bar % 4]
        for q in range(4): place(buf, kick() * .8, T + q * b)
        place(buf, clap() * .6, T + b); place(buf, clap() * .6, T + 3 * b)
        for e in range(8): place(buf, hat(e % 4 == 2) * .7, T + e * b / 2)
        for e, off in enumerate((0, 0, 12, 0, 7, 0, 10, 12)):
            place(buf, lp(saw(note(root - 12 + off), b / 2 * .9), 900) * env(int(b / 2 * .9 * SR), .005, .08, .5, .05) * .22, T + e * b / 2)
        for e in range(16):
            n = root + 24 + (0, 7, 12, 15)[e % 4]
            place(buf, sq(note(n), b / 4 * .6) * env(int(b / 4 * .6 * SR), .002, .05, .2, .03) * .04, T + e * b / 4)
    return reverb(buf, 1.0, .15)[:int(d * SR)]

def m_robot(d):
    buf = np.zeros(int(d * SR) + SR)
    for k in range(int(d / .18)):
        f = rng.choice([440, 660, 550, 330]); place(buf, sine(f, .07) * env(int(.07 * SR), .005, .02, .6, .03) * .05, k * .18)
    place(buf, lp(saw(55, d + .5), 300) * .08, 0)
    return buf[:int(d * SR)]

def m_victory(d):
    buf = np.zeros(int(d * SR) + SR); bpm = 112; b = 60 / bpm
    chords = [[60, 64, 67], [55, 59, 62], [57, 60, 64], [53, 57, 60]]
    for bar in range(int(d / (b * 4)) + 1):
        T = bar * b * 4; ch = chords[bar % 4]
        for n in ch: place(buf, pad(note(n), b * 4) * .08, T)
        for n in ch: place(buf, brass(note(n + 12), b * .9) * .06, T); place(buf, brass(note(n + 12), b * .9) * .05, T + b * 2.5)
        for q in range(4): place(buf, kick() * .7, T + q * b)
        place(buf, clap() * .5, T + b); place(buf, clap() * .5, T + 3 * b)
        for e in range(8): place(buf, hat() * .6, T + e * b / 2)
        place(buf, bell(note(ch[0] + 24)) * .07, T)
    return reverb(buf, 1.4, .2)[:int(d * SR)]

def m_choir(d):
    buf = np.zeros(int(d * SR) + SR)
    def voice(f, dur):  # "aah" formant pad from band-limited saws
        x = sum(saw(f * (1 + dt), dur) for dt in (-0.006, 0, 0.007))
        x = bp(x, 600, 1000) * 1.0 + bp(x, 1100, 1400) * .5 + lp(x, 500) * .6
        return x * env(len(x), .5, .2, .9, .6)
    for n in (48, 55, 60, 64, 67, 72): place(buf, voice(note(n), d) * .05, 0)
    for k in range(3): place(buf, bell(note(84 + (0, 7, 12)[k]), 1.5) * .05, .6 + k * .6)
    return reverb(buf, 3.0, .45)[:int(d * SR)]

MUSIC = {"choir": m_choir, "intro": m_intro, "tension": m_tension, "suspense": m_suspense, "hype": m_hype, "robot": m_robot, "victory": m_victory}

# ---------- sfx ----------
def s_horn(): d = .6; x = (sq(392, d) + sq(494, d)) * .5; return lp(x, 2500) * env(len(x), .01, .05, .8, .05) * .35
def s_screech():
    d = 1.1; t = t_(d); f = 2400 + 600 * np.sin(2 * np.pi * 9 * t) - 900 * t
    x = np.sin(2 * np.pi * np.cumsum(f * 0.55) / SR) * .25 + bp(noise(d), 900, 3200) * .6
    return lp(x, 4000) * env(len(x), .05, .1, .9, .3) * .5
def s_crash():
    d = 1.8; t = t_(d); x = lp(noise(d), 2500) * np.exp(-t * 6) * 1.0
    x[:len(kick())] += kick() * 1.2
    for f in (412, 587, 893, 1321, 1777, 2440):  # metal clang
        x += np.sin(2 * np.pi * f * t) * np.exp(-t * (3 + f / 600)) * .12
    for k in range(10): place(x, bell(3000 + rng.random() * 3000, .25) * .06, .15 + rng.random() * .6)  # glass
    return norm(x, .9)
def s_scratch():
    d = .55; t = t_(d); f = 800 + 1600 * np.abs(np.sin(2 * np.pi * 3.5 * t))
    return bp(noise(d), 300, 3000) * .6 * np.abs(np.sin(2 * np.pi * 3.5 * t)) + np.sin(2 * np.pi * np.cumsum(f) / SR) * .15
def s_whoosh(d=.5):
    x = noise(d); out = np.zeros_like(x)
    for k in range(0, len(x), 1024): out[k:k + 1024] = bp(x[k:k + 1024], 300 + 4000 * k / len(x), 600 + 6000 * k / len(x))
    return out * np.sin(np.pi * np.linspace(0, 1, len(x))) * .4
def s_ching():
    d = 1.2; x = np.zeros(int(d * SR))
    place(x, bp(noise(.08), 2000, 8000) * np.exp(-t_(.08) * 40) * .5, 0)
    for f in (2093, 2637, 3136): place(x, bell(f, 1.0) * .18, .07)
    return x
def s_rewind():
    d = .9; t = t_(d); f = 300 + 2500 * t
    return lp(np.sign(np.sin(2 * np.pi * np.cumsum(f) / SR)), 2500) * .12 + bp(noise(d), 1000, 5000) * .1
def s_boom(): t = t_(1.5); return np.sin(2 * np.pi * np.cumsum(60 * np.exp(-t * 2)) / SR) * np.exp(-t * 2.5) * .9
def s_beep(): return sine(700, .15) * env(int(.15 * SR), .005, .03, .7, .05) * .2
def s_ooh():
    d = 1.6; t = t_(d); x = np.zeros(len(t))
    for v in range(12):  # crowd "oooh": formant-ish filtered saws
        f0 = 140 + rng.random() * 120; x += lp(saw(f0, d), 700 + rng.random() * 200)
    return x / 12 * env(len(t), .3, .2, .9, .6) * .5
def s_thunder():
    d = 2.2; t = t_(d); x = lp(noise(d), 400) * (np.exp(-t * 1.6) + .6 * np.exp(-np.abs(t - .25) * 8))
    x[:len(kick())] += kick()
    return norm(x, .9)
def s_glitch():
    d = .5; x = np.zeros(int(d * SR))
    for k in range(9):
        seg = sq(rng.choice([110, 147, 220, 294]), .04) * .3 if k % 2 else bp(noise(.04), 400, 3000) * .5
        place(x, seg, k * .05)
    return lp(x, 5000)
SFX = {"thunder": s_thunder, "glitch": s_glitch, "horn": s_horn, "screech": s_screech, "crash": s_crash, "scratch": s_scratch, "whoosh": s_whoosh, "ching": s_ching,
       "rewind": s_rewind, "boom": s_boom, "beep": s_beep, "ooh": s_ooh, "sting": m_sting, "hit": m_hit, "sad": m_sad}

def write(path, x):
    x = lp(x, 14000, 4)
    import wave
    x = np.clip(x, -1, 1); y = (x * 32000).astype(np.int16)
    with wave.open(path, 'w') as w: w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(y.tobytes())
