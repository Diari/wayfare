"""Original score for the Wayfare showreel, synthesized from scratch (numpy + scipy).

    python3 music.py out.wav

100 BPM in D major. A pad and arpeggio bed (Dmaj9 - Bm9 - Gmaj9 - A9sus4),
half-time drums from the trip-page reveal, and sound effects placed on the
animation's events. Event times are design times from showreel.src.html and
are mapped through the same HOLDS table, so audio and picture stay in sync.
"""
import sys
import wave

import numpy as np
from scipy.signal import butter, sosfilt, fftconvolve, sawtooth

SR = 44100
DUR = 60.0
N = int(SR * DUR)
BPM = 100
BEAT = 60 / BPM
BAR = BEAT * 4
HOLDS = [(3.38, 2.5), (6.99, 1.5), (10.4, 3.5), (14.05, 2.5), (15.5, 2.5), (16.95, 2.5),
         (18.05, 2.5), (21.3, 2), (22.75, 2), (26.24, 4.5)]
rng = np.random.default_rng(7)


def real(d):
    """Design time (seconds in the 30 s animation) -> real time in the 60 s cut."""
    return d + sum(h for h0, h in HOLDS if h0 < d)


def hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def lp(x, f, order=2):
    return sosfilt(butter(order, f, "low", fs=SR, output="sos"), x)


def hp(x, f, order=2):
    return sosfilt(butter(order, f, "high", fs=SR, output="sos"), x)


def bp(x, lo, hi, order=2):
    return sosfilt(butter(order, [lo, hi], "band", fs=SR, output="sos"), x)


class Bus:
    def __init__(self):
        self.L = np.zeros(N + SR * 4)
        self.R = np.zeros(N + SR * 4)

    def add(self, t, sig, gain=1.0, pan=0.0):
        i = int(t * SR)
        if i < 0:
            sig = sig[-i:]
            i = 0
        n = min(len(sig), len(self.L) - i)
        if n <= 0:
            return
        gl = gain * np.cos((pan + 1) * np.pi / 4) * 1.414
        gr = gain * np.sin((pan + 1) * np.pi / 4) * 1.414
        self.L[i:i + n] += sig[:n] * gl
        self.R[i:i + n] += sig[:n] * gr


dry, wet, drums = Bus(), Bus(), Bus()


def env(n, a, d=None, r=0.0):
    """Attack (s), exponential decay time constant d (s) or sustain, release r (s)."""
    t = np.arange(n) / SR
    e = np.minimum(1, t / max(a, 1e-4))
    if d:
        e *= np.exp(-np.maximum(0, t - a) / d)
    if r:
        rel = int(r * SR)
        e[-rel:] *= np.linspace(1, 0, rel) ** 1.5
    return e


# ---------------------------------------------------------------- harmony
CHORDS = [
    [50, 57, 61, 64, 66],   # Dmaj9
    [47, 54, 57, 61, 62],   # Bm9
    [43, 50, 54, 57, 59],   # Gmaj9
    [45, 52, 55, 59, 62],   # A9sus4
]
ROOTS = [38, 35, 31, 33]
NBARS = int(np.ceil(DUR / BAR))
FINAL_BAR = 22                      # 52.8 s: the logo lands, the band stops
GROOVE_FROM = 5                     # 12.0 s: drums enter just before the page reveal


def chord_at(t):
    b = min(int(t // BAR), FINAL_BAR)
    return CHORDS[0] if b >= FINAL_BAR else CHORDS[b % 4]


# ---------------------------------------------------------------- pad
def pad_note(m, length, cutoff, detune=(-7, 0, 7)):
    n = int(length * SR)
    t = np.arange(n) / SR
    sig = np.zeros(n)
    for c in detune:
        f = hz(m) * 2 ** (c / 1200)
        sig += sawtooth(2 * np.pi * f * t + rng.uniform(0, 6.28))
    sig = lp(sig / len(detune), cutoff, 4)
    return sig * env(n, 0.7, r=0.9)


for b in range(NBARS):
    t0 = b * BAR
    if t0 >= DUR:
        break
    final = b >= FINAL_BAR
    ch = CHORDS[0] if final else CHORDS[b % 4]
    length = (DUR - t0 + 0.5) if final else BAR + 0.9
    if final and b > FINAL_BAR:
        break
    cutoff = 900 if b < 2 else (1500 if b < GROOVE_FROM else 2300)
    if final:
        cutoff = 2600
    for k, m in enumerate(ch):
        s = pad_note(m, length, cutoff)
        pan = (k / (len(ch) - 1) - 0.5) * 0.9
        g = 0.08 if not final else 0.10
        dry.add(t0, s, g, pan)
        wet.add(t0, s, g * 0.9, -pan)
    if final:
        for m in (ch[0] + 12, ch[2] + 12, ch[4] + 12):   # shimmer octave up
            s = pad_note(m, length, 4000, (-4, 4))
            wet.add(t0, s, 0.03, 0)

# ---------------------------------------------------------------- bass
for b in range(min(FINAL_BAR, NBARS)):
    if b < 2:
        continue
    t0 = b * BAR
    r = ROOTS[b % 4]
    pattern = [0, 1.5, 2, 3, 3.5] if b >= GROOVE_FROM else [0, 2]
    for p in pattern:
        n = int(BEAT * (0.9 if p % 1 else 1.4) * SR)
        t = np.arange(n) / SR
        f = hz(r)
        s = np.sin(2 * np.pi * f * t) + 0.25 * np.sin(4 * np.pi * f * t)
        s = np.tanh(s * 1.6) * env(n, 0.006, 0.45, 0.05)
        dry.add(t0 + p * BEAT, lp(s, 700), 0.11)
# final bass note
n = int(6 * SR)
t = np.arange(n) / SR
dry.add(FINAL_BAR * BAR, np.sin(2 * np.pi * hz(38) * t) * env(n, 0.01, 2.2), 0.22)

# ---------------------------------------------------------------- arpeggio
def pluck(f, length=0.5, bright=1.0):
    n = int(length * SR)
    t = np.arange(n) / SR
    s = np.sin(2 * np.pi * f * t) + 0.35 * bright * np.sin(4 * np.pi * f * t) + 0.12 * bright * np.sin(6 * np.pi * f * t)
    return s * env(n, 0.003, 0.16)


ARP = [0, 2, 1, 3, 2, 4, 3, 1]
step = BEAT / 4
t = 0.0
i = 0
while t < FINAL_BAR * BAR:
    b = int(t // BAR)
    ch = CHORDS[b % 4]
    upper = [m + 12 for m in ch[1:]] + [ch[1] + 24]
    on = b >= 1
    if on and not (b < GROOVE_FROM and i % 2):          # 8ths in the intro, 16ths later
        m = upper[ARP[i % 8]]
        vel = 0.9 if i % 4 == 0 else 0.6
        g = 0.075 * vel if b >= GROOVE_FROM else 0.055 * vel
        p = pluck(hz(m), bright=0.8 if b < GROOVE_FROM else 1.0)
        pan = 0.35 * np.sin(i * 0.7)
        dry.add(t, p, g, pan)
        wet.add(t, p, g * 0.8, pan)
        # dotted-eighth ping-pong delay
        for k in range(1, 4):
            dry.add(t + k * BEAT * 0.75, lp(p, 2500), g * 0.38 ** k, -pan if k % 2 else pan)
    t += step
    i += 1

# ---------------------------------------------------------------- drums
def kick():
    n = int(0.45 * SR)
    t = np.arange(n) / SR
    f = 46 + 95 * np.exp(-t / 0.035)
    ph = 2 * np.pi * np.cumsum(f) / SR
    s = np.sin(ph) * np.exp(-t / 0.26)
    s[:120] += rng.normal(0, 0.3, 120) * np.linspace(1, 0, 120)
    return np.tanh(s * 1.4)


def clap():
    n = int(0.35 * SR)
    t = np.arange(n) / SR
    noise = bp(rng.normal(0, 1, n), 900, 6000)
    e = np.exp(-t / 0.09)
    for d in (0.0, 0.011, 0.022):
        e += 0.6 * np.exp(-np.maximum(0, t - d) / 0.008) * (t >= d)
    tone = np.sin(2 * np.pi * 185 * t) * np.exp(-t / 0.05) * 0.5
    return noise * e * 0.35 + tone


def hat(open_=False):
    n = int((0.25 if open_ else 0.08) * SR)
    t = np.arange(n) / SR
    return hp(rng.normal(0, 1, n), 7500, 4) * np.exp(-t / (0.09 if open_ else 0.022))


K, C = kick(), clap()
kick_times = []
for b in range(GROOVE_FROM - 3, FINAL_BAR):
    t0 = b * BAR
    groove = b >= GROOVE_FROM
    for e8 in range(8):
        tt = t0 + e8 * BEAT / 2
        if groove or b >= 2:
            drums.add(tt, hat(open_=(e8 % 4 == 3) and groove), 0.05 if e8 % 2 else 0.032, 0.25)
    if groove:
        for p in ([0, 2.5] if b % 2 else [0, 1.75, 2.5]):
            drums.add(t0 + p * BEAT, K, 0.30)
            kick_times.append(t0 + p * BEAT)
        for p in (1, 3):
            drums.add(t0 + p * BEAT, C, 0.26, -0.1)
            wet.add(t0 + p * BEAT, C, 0.06)
# fill into the final bar
for k in range(8):
    tt = (FINAL_BAR - 1) * BAR + 2 * BEAT + k * BEAT / 4
    drums.add(tt, C * (0.4 + k * 0.08), 0.22, -0.4 + k * 0.1)

# ---------------------------------------------------------------- sound design
def whoosh(length, lo=300, hi=6000, rise=True):
    """Filtered noise that moves from a low band to a high band (or back)."""
    n = int(length * SR)
    t = np.arange(n) / SR
    noise = rng.normal(0, 1, n)
    low = bp(noise, lo, lo * 3)
    high = bp(noise, hi / 3, min(hi, SR / 2 - 200))
    p = t / length if rise else 1 - t / length
    out = low * (1 - p) + high * p
    e = (t / length) ** 2 if rise else np.sin(np.pi * t / length) ** 2
    return out * e


def boom(length=2.2):
    n = int(length * SR)
    t = np.arange(n) / SR
    f = 32 + 40 * np.exp(-t / 0.15)
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.7)
    s += lp(rng.normal(0, 1, n), 400) * np.exp(-t / 0.12) * 0.6
    return np.tanh(s * 1.3)


def bell(f, length=2.0, index=2.0):
    n = int(length * SR)
    t = np.arange(n) / SR
    mod = index * np.exp(-t / 0.4) * np.sin(2 * np.pi * f * 3.5 * t)
    return np.sin(2 * np.pi * f * t + mod) * env(n, 0.002, 0.7)


def tick(f=3000, length=0.03):
    n = int(length * SR)
    t = np.arange(n) / SR
    return bp(rng.normal(0, 1, n), f * 0.6, f * 1.6) * np.exp(-t / 0.006)


def ding(f1, f2):
    n = int(1.4 * SR)
    t = np.arange(n) / SR
    a = np.sin(2 * np.pi * f1 * t) * env(n, 0.003, 0.35)
    b = np.sin(2 * np.pi * f2 * t) * env(n, 0.003, 0.45)
    out = a.copy()
    o = int(0.11 * SR)
    out[o:] += b[:n - o]
    return out


# S1: the plane crosses, emails land with soft plucks on a rising pentatonic
dry.add(0.1, whoosh(2.2, 200, 5000, rise=False), 0.05, -0.6)
PENT = [74, 76, 78, 81, 83, 86, 88, 90, 93, 95]
for i in range(10):
    tt = real(1.15 + i * 0.15) + 0.25
    p = pluck(hz(PENT[i]), 0.6)
    dry.add(tt, p, 0.05, 0.6 - i * 0.12)
    wet.add(tt, p, 0.04)
# S1 -> S2
dry.add(real(3.4) - 1.2, whoosh(1.2, 400, 8000), 0.06, 0.3)
dry.add(real(3.85), boom(1.4), 0.20)
# S2: scan sweep shimmer, chips pop
dry.add(real(4.8), whoosh(1.2, 2000, 9000, rise=False), 0.04, -0.3)
CHIP = [69, 73, 76, 78, 81, 85, 88]
for k in range(7):
    tt = real(5.75 + k * 0.11) + 0.1
    p = pluck(hz(CHIP[k] + 12), 0.5)
    dry.add(tt, p, 0.045, -0.5 + k * 0.16)
    wet.add(tt, p, 0.035)
# S2 -> S3: riser into the page reveal
r3 = real(8.5)
dry.add(r3 - 1.5, whoosh(1.5, 200, 7000), 0.08, 0)
dry.add(r3, boom(2.4), 0.22)
wet.add(r3, bell(hz(74), 3.0, 1.2), 0.05)
# S4: an alert hit on each card
for k, d in enumerate([13.4, 14.85, 16.3, 17.75]):
    tt = real(d)
    ch = chord_at(tt)
    top = ch[-1] + 12 + [0, 2, 5, 7][k]
    dry.add(tt, bell(hz(top), 2.2, 2.6), 0.07, 0.2)
    wet.add(tt, bell(hz(top), 2.2, 2.6), 0.06)
    dry.add(tt, boom(1.0), 0.08)
# S4 -> S5
dry.add(real(18.2) - 0.8, whoosh(1.0, 300, 6000), 0.06, -0.3)
dry.add(real(18.85), boom(1.6), 0.18)
# flip board clatter
for row in range(2):
    start = real(19.55 + row * 0.35)
    for k in range(int(1.1 * 38)):
        tt = start + k / 38 + rng.uniform(0, 0.01)
        dry.add(tt, tick(rng.uniform(1800, 4200)), 0.05 * rng.uniform(0.4, 1), rng.uniform(-0.5, 0.5))
# phone notifications
dry.add(real(20.55) + 0.1, ding(hz(88), hz(95)), 0.08, 0.5)
wet.add(real(20.55) + 0.1, ding(hz(88), hz(95)), 0.04)
dry.add(real(21.55) + 0.1, ding(hz(88), hz(95)), 0.07, 0.5)
# S5 -> S6
dry.add(real(23.0) - 0.8, whoosh(1.0, 300, 6000), 0.06, 0.3)
dry.add(real(23.3), boom(1.4), 0.15)
for i in range(3):
    dry.add(real(24.85 + i * 0.38), pluck(hz(86 + [0, 4, 7][i]), 0.3), 0.04, -0.4)
for i in range(2):
    dry.add(real(25.05 + i * 0.4), pluck(hz(90 + [0, 5][i]), 0.3), 0.04, 0.4)
dry.add(real(25.3), tick(1500, 0.05), 0.12, 0.4)
wet.add(real(25.85), bell(hz(93), 2.0, 1.5), 0.06)
dry.add(real(25.85), bell(hz(93), 2.0, 1.5), 0.05, 0.4)
# S7: riser, then the logo lands on the final chord
r7 = FINAL_BAR * BAR
dry.add(r7 - 2.4, whoosh(2.4, 150, 9000), 0.1, 0)
dry.add(r7, boom(3.0), 0.26)
for k, m in enumerate([74, 78, 81, 85, 88]):
    s = bell(hz(m + 12), 4.0, 1.4)
    wet.add(r7 + 0.75 + k * 0.06, s, 0.05)
    dry.add(r7 + 0.75 + k * 0.06, s, 0.035, -0.4 + k * 0.2)
# typing the install command
for k in range(31):
    tt = real(28.3) + k * (0.8 / 31) + rng.uniform(0, 0.008)
    dry.add(tt, tick(rng.uniform(2500, 5000), 0.02), 0.06, 0.1)
# a last gentle arpeggio over the ringing chord
for k, m in enumerate([86, 90, 93, 97, 93, 90]):
    tt = r7 + 2 * BAR + k * BEAT / 2
    if tt < DUR - 1.2:
        p = pluck(hz(m), 0.8, 0.6)
        dry.add(tt, p, 0.03, 0.3 * np.sin(k))
        wet.add(tt, p, 0.04)

# ---------------------------------------------------------------- mix
# sidechain the pad/arp bed to the kick
duck = np.ones(len(dry.L))
for kt in kick_times:
    i = int(kt * SR)
    n = int(0.35 * SR)
    seg = 1 - 0.45 * np.exp(-np.arange(n) / SR / 0.1)
    duck[i:i + n] = np.minimum(duck[i:i + n], seg[:len(duck[i:i + n])])

# reverb: decaying filtered noise
ir_n = int(2.8 * SR)
ti = np.arange(ir_n) / SR
irL = lp(rng.normal(0, 1, ir_n), 5000) * np.exp(-ti / 0.75)
irR = lp(rng.normal(0, 1, ir_n), 5000) * np.exp(-ti / 0.75)
irL[: int(0.02 * SR)] = 0
irR[: int(0.025 * SR)] = 0
irL /= np.sqrt(np.sum(irL ** 2))
irR /= np.sqrt(np.sum(irR ** 2))
revL = fftconvolve(wet.L, irL)[: len(wet.L)]
revR = fftconvolve(wet.R, irR)[: len(wet.R)]

L = (dry.L + revL * 0.9) * duck + drums.L
R = (dry.R + revR * 0.9) * duck + drums.R
L, R = hp(L, 28), hp(R, 28)
L, R = L[:N], R[:N]

# glue: gentle saturation, then normalize
mix = np.stack([L, R])
mix = np.tanh(mix * 1.2) / 1.2
fade_in = int(0.05 * SR)
fade_out = int(3.0 * SR)
mix[:, :fade_in] *= np.linspace(0, 1, fade_in)
mix[:, -fade_out:] *= np.linspace(1, 0, fade_out) ** 2
mix *= 0.89 / np.max(np.abs(mix))

out = sys.argv[1] if len(sys.argv) > 1 else "wayfare-score.wav"
pcm = (mix.T * 32767).astype(np.int16)
with wave.open(out, "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(pcm.tobytes())
print("wrote", out, f"{DUR:.0f}s")
