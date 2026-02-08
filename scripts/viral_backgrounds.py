#!/usr/bin/env python3
"""
Viral animated backgrounds for Reels (1080x1920).

Each style is designed around a psychological hook that prevents scrolling.

Usage:
    python scripts/viral_backgrounds.py orbits -o input/backgrounds/vbg_orbits.mp4
    python scripts/viral_backgrounds.py drawing -o input/backgrounds/vbg_drawing.mp4
    python scripts/viral_backgrounds.py morph -o input/backgrounds/vbg_morph.mp4
    python scripts/viral_backgrounds.py assemble -o input/backgrounds/vbg_assemble.mp4
    python scripts/viral_backgrounds.py zoom -o input/backgrounds/vbg_zoom.mp4
    python scripts/viral_backgrounds.py --list
"""

import argparse
import math
import os
import random
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

WIDTH = 1080
HEIGHT = 1920
FPS = 30


def ease_in_out(t):
    return t * t * (3 - 2 * t)


def ease_out_elastic(t):
    if t <= 0: return 0
    if t >= 1: return 1
    return math.sin(-13 * math.pi / 2 * (t + 1)) * math.pow(2, -10 * t) + 1


def smoothstep(edge0, edge1, x):
    t = max(0, min(1, (x - edge0) / (edge1 - edge0)))
    return t * t * (3 - 2 * t)


def make_bg_gradient():
    """Create a rich dark gradient background (deep navy/purple)."""
    bg = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    for y in range(HEIGHT):
        frac = y / HEIGHT
        # Deep navy at top → dark purple at bottom
        bg[y, :, 0] = int(8 + 12 * frac)      # R
        bg[y, :, 1] = int(6 + 4 * frac)        # G
        bg[y, :, 2] = int(25 + 10 * (1 - frac))  # B — more blue at top
    return bg


def draw_glow(img_array, cx, cy, radius, color, intensity=1.0):
    """Draw a soft Gaussian glow circle on numpy array. Much bigger and brighter."""
    r, g, b = color
    spread = radius * 2.5
    y_min = max(0, int(cy - spread))
    y_max = min(HEIGHT, int(cy + spread))
    x_min = max(0, int(cx - spread))
    x_max = min(WIDTH, int(cx + spread))

    if y_min >= y_max or x_min >= x_max:
        return

    ys = np.arange(y_min, y_max)
    xs = np.arange(x_min, x_max)
    yy, xx = np.meshgrid(ys, xs, indexing='ij')

    dist_sq = (xx - cx)**2 + (yy - cy)**2
    sigma = radius * 0.7
    # Gaussian falloff — much smoother and wider
    glow = np.exp(-dist_sq / (2 * sigma * sigma)) * intensity

    region = img_array[y_min:y_max, x_min:x_max].astype(np.float32)
    region[:, :, 0] = np.clip(region[:, :, 0] + glow * r, 0, 255)
    region[:, :, 1] = np.clip(region[:, :, 1] + glow * g, 0, 255)
    region[:, :, 2] = np.clip(region[:, :, 2] + glow * b, 0, 255)
    img_array[y_min:y_max, x_min:x_max] = region.astype(np.uint8)


def draw_ambient_dust(img, t, particles, color=(60, 50, 80)):
    """Draw floating ambient dust particles for atmosphere."""
    for px, py, speed, phase, size in particles:
        # Slow drift
        x = (px + t * speed * 15) % WIDTH
        y = (py + math.sin(t * 0.5 + phase) * 30) % HEIGHT
        twinkle = 0.4 + 0.6 * (0.5 + 0.5 * math.sin(t * 1.2 + phase))
        r = int(color[0] * twinkle)
        g = int(color[1] * twinkle)
        b = int(color[2] * twinkle)
        s = max(1, int(size * twinkle))
        y_lo = max(0, int(y) - s)
        y_hi = min(HEIGHT, int(y) + s + 1)
        x_lo = max(0, int(x) - s)
        x_hi = min(WIDTH, int(x) + s + 1)
        if y_lo < y_hi and x_lo < x_hi:
            img[y_lo:y_hi, x_lo:x_hi] = np.clip(
                img[y_lo:y_hi, x_lo:x_hi].astype(np.int16) + [[r, g, b]], 0, 255
            ).astype(np.uint8)


def make_dust_particles(n=120):
    """Generate random dust particle positions."""
    return [(random.randint(0, WIDTH), random.randint(0, HEIGHT),
             random.uniform(-0.3, 0.3), random.uniform(0, math.pi * 2),
             random.randint(1, 3)) for _ in range(n)]


# ============================================================
# STYLE 1: ORBITS — два огонька притягиваются и отталкиваются
# Hook: "они соединятся или нет?"
# ============================================================
def generate_orbits(output_path, duration=12):
    frames_count = FPS * duration
    random.seed(42)

    trail_a = []
    trail_b = []
    max_trail = 80

    # Initial positions — more separated
    ax, ay = WIDTH * 0.3, HEIGHT * 0.4
    bx, by = WIDTH * 0.7, HEIGHT * 0.6
    avx, avy = 1.2, -2.0
    bvx, bvy = -1.2, 2.0

    # Background particles (twinkling stars)
    bg_particles = [(random.randint(0, WIDTH), random.randint(0, HEIGHT),
                     random.uniform(0.4, 1.0), random.uniform(0, math.pi * 2),
                     random.randint(1, 3))
                    for _ in range(150)]
    dust = make_dust_particles(100)

    print(f'Generating orbits: {frames_count} frames...')
    frames = []

    for f in range(frames_count):
        t = f / FPS

        # Physics: mutual attraction + repulsion at close range
        dx = bx - ax
        dy = by - ay
        dist = max(math.sqrt(dx * dx + dy * dy), 30)

        # Gravity — stronger
        force = 1200 / (dist * dist) * 60
        # Repulsion when very close
        if dist < 120:
            force -= 4000 / (dist * dist) * 60

        fx = force * dx / dist
        fy = force * dy / dist

        avx += fx / FPS
        avy += fy / FPS
        bvx -= fx / FPS
        bvy -= fy / FPS

        avx *= 0.997
        avy *= 0.997
        bvx *= 0.997
        bvy *= 0.997

        # Pull toward center
        center_x, center_y = WIDTH / 2, HEIGHT / 2
        avx += (center_x - ax) * 0.0004
        avy += (center_y - ay) * 0.0004
        bvx += (center_x - bx) * 0.0004
        bvy += (center_y - by) * 0.0004

        ax += avx
        ay += avy
        bx += bvx
        by += bvy

        # Soft bounds
        margin = 120
        if ax < margin: avx += 3
        if ax > WIDTH - margin: avx -= 3
        if ay < margin: avy += 3
        if ay > HEIGHT - margin: avy -= 3
        if bx < margin: bvx += 3
        if bx > WIDTH - margin: bvx -= 3
        if by < margin: bvy += 3
        if by > HEIGHT - margin: bvy -= 3

        trail_a.append((ax, ay))
        trail_b.append((bx, by))
        if len(trail_a) > max_trail: trail_a.pop(0)
        if len(trail_b) > max_trail: trail_b.pop(0)

        # Render
        img = make_bg_gradient().copy()

        # Ambient dust
        draw_ambient_dust(img, t, dust, color=(40, 35, 65))

        # Background stars
        for px, py, brightness, phase, size in bg_particles:
            twinkle = 0.3 + 0.7 * (0.5 + 0.5 * math.sin(t * 1.5 + phase))
            val = int(55 * brightness * twinkle)
            iy, ix = int(py), int(px)
            if 0 <= ix < WIDTH and 0 <= iy < HEIGHT:
                for ddx in range(-size, size + 1):
                    for ddy in range(-size, size + 1):
                        ny, nx = iy + ddy, ix + ddx
                        if 0 <= nx < WIDTH and 0 <= ny < HEIGHT:
                            fade = max(0, 1 - (abs(ddx) + abs(ddy)) / (size + 1))
                            img[ny, nx] = np.clip(
                                img[ny, nx].astype(int) + [int(val * fade * 0.7),
                                                            int(val * fade * 0.8),
                                                            int(val * fade * 1.3)], 0, 255
                            ).astype(np.uint8)

        # Connection line (energy thread between orbs)
        line_alpha = max(0, 1.0 - dist / 500) * 0.6
        if line_alpha > 0.02:
            steps = max(int(dist), 10)
            for s in range(steps):
                frac = s / max(steps, 1)
                lx = int(ax + (bx - ax) * frac)
                ly = int(ay + (by - ay) * frac)
                # Sinusoidal wave on the line
                wave_amp = 6 * math.sin(frac * 12 - t * 6)
                perp_x = -(by - ay) / max(dist, 1)
                perp_y = (bx - ax) / max(dist, 1)
                lx += int(wave_amp * perp_x)
                ly += int(wave_amp * perp_y)
                if 0 <= lx < WIDTH and 0 <= ly < HEIGHT:
                    pulse = 0.5 + 0.5 * math.sin(frac * 25 - t * 10)
                    val = int(100 * line_alpha * pulse)
                    y_lo = max(0, ly - 2)
                    y_hi = min(HEIGHT, ly + 3)
                    x_lo = max(0, lx - 2)
                    x_hi = min(WIDTH, lx + 3)
                    if y_lo < y_hi and x_lo < x_hi:
                        img[y_lo:y_hi, x_lo:x_hi] = np.clip(
                            img[y_lo:y_hi, x_lo:x_hi].astype(int) + [val, val // 2, val // 3], 0, 255
                        ).astype(np.uint8)

        # Trails — much bigger and brighter
        for trail, color in [(trail_a, (255, 160, 80)), (trail_b, (120, 180, 255))]:
            for i, (tx, ty) in enumerate(trail):
                age = i / max(len(trail), 1)  # 0=oldest, 1=newest
                radius = int(12 + 30 * age)
                intensity = age * 0.5
                r = int(color[0] * 0.3)
                g = int(color[1] * 0.3)
                b = int(color[2] * 0.3)
                draw_glow(img, tx, ty, radius, (r, g, b), intensity)

        # Main orbs — MUCH bigger
        closeness = max(0, 1.0 - dist / 250)

        # Orb A: warm amber — outer glow + inner core
        orb_r = 70 + closeness * 30
        draw_glow(img, ax, ay, orb_r, (255, 120, 40), 0.7 + closeness * 0.5)
        draw_glow(img, ax, ay, orb_r * 0.5, (255, 180, 80), 0.9)
        draw_glow(img, ax, ay, orb_r * 0.2, (255, 230, 180), 1.0)

        # Orb B: cool blue
        draw_glow(img, bx, by, orb_r, (60, 140, 255), 0.7 + closeness * 0.5)
        draw_glow(img, bx, by, orb_r * 0.5, (130, 190, 255), 0.9)
        draw_glow(img, bx, by, orb_r * 0.2, (200, 230, 255), 1.0)

        # Sparks when close
        if dist < 150:
            spark_intensity = (150 - dist) / 150
            mid_x = (ax + bx) / 2
            mid_y = (ay + by) / 2
            for _ in range(int(12 * spark_intensity)):
                sx = mid_x + random.gauss(0, 35)
                sy = mid_y + random.gauss(0, 35)
                spark_r = random.uniform(4, 12)
                draw_glow(img, sx, sy, spark_r, (255, 230, 200), spark_intensity * 0.7)

        frames.append(img)
        if f % FPS == 0:
            print(f'  {f}/{frames_count}')

    _save_video(frames, output_path)


# ============================================================
# STYLE 2: DRAWING — линия рисует сама себя
# Hook: "что это будет?"
# ============================================================
def generate_drawing(output_path, duration=12):
    frames_count = FPS * duration

    shapes = [_heart_path(300), _couple_path(300), _hands_path(300)]

    draw_time = 3.5
    hold_time = 1.0
    fade_time = 1.5
    shape_time = draw_time + hold_time + fade_time

    dust = make_dust_particles(80)

    print(f'Generating drawing: {frames_count} frames...')
    frames = []
    particles = []

    for f in range(frames_count):
        t = f / FPS
        shape_idx = int(t / shape_time) % len(shapes)
        shape_t = (t % shape_time)
        path = shapes[shape_idx]

        img = make_bg_gradient().copy()
        draw_ambient_dust(img, t, dust, color=(50, 40, 70))

        pil_img = Image.fromarray(img)
        draw = ImageDraw.Draw(pil_img)

        # Gold/warm color for the line
        line_color_base = (220, 190, 140)

        if shape_t < draw_time:
            progress = ease_in_out(shape_t / draw_time)
            num_points = max(1, int(len(path) * progress))

            if num_points > 1:
                for i in range(num_points - 1):
                    x1, y1 = path[i]
                    x2, y2 = path[i + 1]
                    age = 0.5 + 0.5 * (i / len(path))
                    r = int(line_color_base[0] * age)
                    g = int(line_color_base[1] * age)
                    b = int(line_color_base[2] * age)
                    draw.line([(x1, y1), (x2, y2)], fill=(r, g, b), width=6)

                hx, hy = path[num_points - 1]
                for _ in range(3):
                    particles.append({'x': hx, 'y': hy,
                                      'vx': random.gauss(0, 2.5),
                                      'vy': random.gauss(0, 2.5),
                                      'life': 1.0, 'size': random.uniform(6, 14)})

        elif shape_t < draw_time + hold_time:
            # Hold: full shape, bright
            for i in range(len(path) - 1):
                x1, y1 = path[i]
                x2, y2 = path[i + 1]
                draw.line([(x1, y1), (x2, y2)], fill=line_color_base, width=6)
        else:
            fade = max(0, 1.0 - (shape_t - draw_time - hold_time) / fade_time)
            r = int(line_color_base[0] * fade)
            g = int(line_color_base[1] * fade)
            b = int(line_color_base[2] * fade)
            w = max(1, int(6 * fade))
            for i in range(len(path) - 1):
                x1, y1 = path[i]
                x2, y2 = path[i + 1]
                draw.line([(x1, y1), (x2, y2)], fill=(r, g, b), width=w)

        # Apply slight blur to the line for glow effect
        pil_img_blurred = pil_img.filter(ImageFilter.GaussianBlur(radius=3))
        # Composite: original + blurred for glow
        img_sharp = np.array(pil_img).astype(np.float32)
        img_blur = np.array(pil_img_blurred).astype(np.float32)
        img = np.clip(img_sharp + img_blur * 0.5, 0, 255).astype(np.uint8)

        # Update and draw particles
        alive = []
        for p in particles:
            p['x'] += p['vx']
            p['y'] += p['vy']
            p['vy'] += 0.05  # slight gravity
            p['life'] -= 0.025
            if p['life'] > 0:
                draw_glow(img, p['x'], p['y'], p['size'] * p['life'],
                          (255, 220, 160), p['life'] * 0.6)
                alive.append(p)
        particles = alive[-300:]

        # Drawing head glow — BIG and bright
        if shape_t < draw_time:
            progress = ease_in_out(shape_t / draw_time)
            idx = min(int(len(path) * progress), len(path) - 1)
            hx, hy = path[idx]
            draw_glow(img, hx, hy, 55, (255, 200, 100), 0.7)
            draw_glow(img, hx, hy, 25, (255, 235, 200), 1.0)
            draw_glow(img, hx, hy, 10, (255, 250, 240), 1.0)

        frames.append(img)
        if f % FPS == 0:
            print(f'  {f}/{frames_count}')

    _save_video(frames, output_path)


def _heart_path(num_points):
    points = []
    scale = 320
    cx, cy = WIDTH / 2, HEIGHT / 2 - 50
    for i in range(num_points):
        t = 2 * math.pi * i / num_points
        x = scale * 16 * math.sin(t)**3 / 16
        y = -scale * (13 * math.cos(t) - 5 * math.cos(2*t) - 2 * math.cos(3*t) - math.cos(4*t)) / 16
        points.append((cx + x, cy + y))
    return points


def _couple_path(num_points):
    raw = []
    cx, cy = WIDTH / 2, HEIGHT / 2
    s = 3.0
    keypoints = [
        (-80, -80), (-70, -100), (-50, -110), (-30, -100), (-20, -80),
        (-40, -60), (-50, -20), (-55, 20), (-50, 60), (-60, 120),
        (-40, 60), (-30, 20), (-15, 0),
        (15, 0), (30, 20), (40, 60),
        (50, 120), (50, 60), (55, 20), (50, -20), (40, -60),
        (20, -80), (30, -100), (50, -110), (70, -100), (80, -80),
    ]
    for (x1, y1), (x2, y2) in zip(keypoints[:-1], keypoints[1:]):
        steps = max(2, num_points // len(keypoints))
        for j in range(steps):
            frac = j / steps
            x = x1 + (x2 - x1) * frac
            y = y1 + (y2 - y1) * frac
            raw.append((cx + x * s, cy + y * s))
    return raw[:num_points]


def _hands_path(num_points):
    raw = []
    cx, cy = WIDTH / 2, HEIGHT / 2
    s = 3.5
    keypoints = [
        (-120, 40), (-100, 20), (-80, 0), (-60, -10),
        (-40, -30), (-30, -50), (-35, -30),
        (-30, -20), (-20, -45), (-25, -20),
        (-20, -15), (-8, -40), (-15, -15),
        (-10, -10), (0, -30), (-5, -10),
        (-5, 0), (0, 5),
        (5, 0), (10, -10),
        (0, -30), (10, -10),
        (8, -40), (20, -15),
        (20, -45), (30, -20),
        (30, -50), (40, -30),
        (60, -10), (80, 0), (100, 20), (120, 40),
    ]
    for (x1, y1), (x2, y2) in zip(keypoints[:-1], keypoints[1:]):
        steps = max(2, num_points // len(keypoints))
        for j in range(steps):
            frac = j / steps
            x = x1 + (x2 - x1) * frac
            y = y1 + (y2 - y1) * frac
            raw.append((cx + x * s, cy + y * s))
    return raw[:num_points]


# ============================================================
# STYLE 3: MORPH — сердце ломается и собирается
# Hook: залипательный бесконечный цикл
# ============================================================
def generate_morph(output_path, duration=12):
    frames_count = FPS * duration
    random.seed(33)

    num_pts = 400
    heart_points = []
    for i in range(num_pts):
        t = 2 * math.pi * i / num_pts
        x = 16 * math.sin(t)**3
        y = -(13 * math.cos(t) - 5 * math.cos(2*t) - 2 * math.cos(3*t) - math.cos(4*t))
        heart_points.append((x, y))
    heart_points = np.array(heart_points, dtype=np.float64)

    scattered = np.array([(random.gauss(0, 30), random.gauss(0, 30)) for _ in range(num_pts)])

    # Each point gets a random "personality" for slight individual movement
    point_phase = np.random.uniform(0, math.pi * 2, num_pts)
    point_speed = np.random.uniform(0.5, 1.5, num_pts)

    cycle = duration
    dust = make_dust_particles(60)

    print(f'Generating morph: {frames_count} frames...')
    frames = []

    scale = 20.0
    cx, cy = WIDTH / 2, HEIGHT / 2

    for f in range(frames_count):
        t = f / FPS
        ct = t % cycle

        # Breathing: individual points oscillate slightly
        breathe = np.sin(t * 2 + point_phase) * 0.3

        if ct < 2:
            pulse = 1.0 + 0.06 * math.sin(ct * math.pi)
            pts = heart_points * pulse
            pts[:, 0] += breathe * point_speed
            color = (255, 60, 120)
            glow_color = (255, 40, 100)
            glow_size = 18
        elif ct < 4:
            frac = ease_in_out((ct - 2) / 2)
            pts = heart_points.copy()
            for i in range(num_pts):
                if heart_points[i, 0] <= 0:
                    pts[i, 0] -= frac * 10
                else:
                    pts[i, 0] += frac * 10
                if abs(heart_points[i, 0]) < 3:
                    pts[i, 1] += frac * random.gauss(0, 1.5)
            pts[:, 0] += breathe * point_speed * (1 - frac * 0.5)
            color = (int(255 - 60 * frac), int(60 + 40 * frac), int(120 + 100 * frac))
            glow_color = (220, 50, 180)
            glow_size = int(18 + 6 * frac)
        elif ct < 5:
            pts = heart_points.copy()
            for i in range(num_pts):
                if heart_points[i, 0] <= 0:
                    pts[i, 0] -= 10
                else:
                    pts[i, 0] += 10
            pts[:, 0] += breathe * point_speed * 0.5
            color = (195, 100, 220)
            glow_color = (170, 70, 200)
            glow_size = 22
        elif ct < 7:
            frac = ease_in_out((ct - 5) / 2)
            broken = heart_points.copy()
            for i in range(num_pts):
                if heart_points[i, 0] <= 0:
                    broken[i, 0] -= 10
                else:
                    broken[i, 0] += 10
            pts = broken * (1 - frac) + scattered * frac
            color = (int(195 - 95 * frac), int(100 + 20 * frac), int(220 - 60 * frac))
            glow_color = (120, 100, 180)
            glow_size = int(22 - 4 * frac)
        elif ct < 8:
            pts = scattered.copy()
            pts[:, 0] += breathe * point_speed * 2
            pts[:, 1] += np.cos(t * 1.5 + point_phase) * 0.5
            color = (100, 120, 160)
            glow_color = (80, 100, 150)
            glow_size = 16
        elif ct < 10.5:
            frac = ease_in_out((ct - 8) / 2.5)
            pts = scattered * (1 - frac) + heart_points * frac
            pts[:, 0] += breathe * point_speed * (1 - frac)
            color = (int(100 + 155 * frac), int(120 - 60 * frac), int(160 - 40 * frac))
            glow_color = (220, 50, 110)
            glow_size = int(16 + 4 * frac)
        else:
            pulse = 1.0 + 0.06 * math.sin((ct - 10.5) * math.pi * 2)
            pts = heart_points * pulse
            pts[:, 0] += breathe * point_speed
            color = (255, 60, 120)
            glow_color = (255, 40, 100)
            glow_size = 18

        # Render
        img = make_bg_gradient().copy()
        draw_ambient_dust(img, t, dust, color=(40, 30, 60))

        # Central ambient glow — big and soft
        draw_glow(img, cx, cy, 350, (glow_color[0] // 6, glow_color[1] // 6, glow_color[2] // 6), 0.4)

        # Draw points as glowing dots — MUCH bigger
        for i, (px, py) in enumerate(pts):
            sx = cx + px * scale
            sy = cy + py * scale
            if -20 <= sx < WIDTH + 20 and -20 <= sy < HEIGHT + 20:
                # Outer glow
                draw_glow(img, sx, sy, glow_size, glow_color, 0.2)
                # Core — bright pixel cluster
                ix, iy = int(np.clip(sx, 0, WIDTH - 1)), int(np.clip(sy, 0, HEIGHT - 1))
                for ddx in range(-3, 4):
                    for ddy in range(-3, 4):
                        nx, ny = ix + ddx, iy + ddy
                        if 0 <= nx < WIDTH and 0 <= ny < HEIGHT:
                            d = math.sqrt(ddx * ddx + ddy * ddy)
                            fade = max(0, 1 - d / 4)
                            img[ny, nx] = np.clip(
                                img[ny, nx].astype(int) + [int(color[0] * fade * 0.7),
                                                            int(color[1] * fade * 0.7),
                                                            int(color[2] * fade * 0.7)], 0, 255
                            ).astype(np.uint8)

        frames.append(img)
        if f % FPS == 0:
            print(f'  {f}/{frames_count}')

    _save_video(frames, output_path)


# ============================================================
# STYLE 4: ASSEMBLE — частицы хаотично летают → собираются в форму
# Hook: "что соберётся?"
# ============================================================
def generate_assemble(output_path, duration=12):
    frames_count = FPS * duration
    random.seed(21)

    num_particles = 500

    shape_funcs = [_shape_heart, _shape_infinity, _shape_couple_silhouette]

    px_arr = np.random.uniform(100, WIDTH - 100, num_particles)
    py_arr = np.random.uniform(100, HEIGHT - 100, num_particles)
    vx_arr = np.random.uniform(-2, 2, num_particles)
    vy_arr = np.random.uniform(-2, 2, num_particles)

    # Brighter, more saturated palette
    palette = [
        (255, 100, 130), (255, 140, 80), (220, 100, 255),
        (100, 180, 255), (255, 200, 80), (255, 80, 180),
    ]
    colors = np.array([random.choice(palette) for _ in range(num_particles)], dtype=np.float64)
    sizes = np.random.uniform(3, 7, num_particles)

    # Phase timing: chaos(2) → assemble(3) → hold(2) → dissolve(2) → chaos(3) = 12s
    phase_times = [2, 3, 2, 2, 3]
    dust = make_dust_particles(80)

    print(f'Generating assemble: {frames_count} frames...')
    frames = []

    for f in range(frames_count):
        t = f / FPS
        cycle_t = t % duration

        shape_cycle = int(t / duration)
        shape_idx = shape_cycle % len(shape_funcs)
        target_positions = shape_funcs[shape_idx](num_particles)

        cum = 0
        phase = 0
        phase_t = 0
        for i, pt in enumerate(phase_times):
            if cycle_t < cum + pt:
                phase = i
                phase_t = (cycle_t - cum) / pt
                break
            cum += pt
        else:
            phase = 4
            phase_t = 1

        if phase == 0 or phase == 4:
            vx_arr += np.random.uniform(-0.4, 0.4, num_particles)
            vy_arr += np.random.uniform(-0.4, 0.4, num_particles)
            vx_arr += (WIDTH / 2 - px_arr) * 0.0006
            vy_arr += (HEIGHT / 2 - py_arr) * 0.0006
            vx_arr *= 0.99
            vy_arr *= 0.99
        elif phase == 1:
            strength = ease_in_out(phase_t) * 0.1
            tx = target_positions[:, 0]
            ty = target_positions[:, 1]
            vx_arr += (tx - px_arr) * strength
            vy_arr += (ty - py_arr) * strength
            vx_arr *= 0.90
            vy_arr *= 0.90
        elif phase == 2:
            tx = target_positions[:, 0]
            ty = target_positions[:, 1]
            vx_arr = (tx - px_arr) * 0.18
            vy_arr = (ty - py_arr) * 0.18
        elif phase == 3:
            strength = ease_in_out(phase_t)
            vx_arr += np.random.uniform(-4, 4, num_particles) * strength * 2
            vy_arr += np.random.uniform(-4, 4, num_particles) * strength * 2
            vx_arr *= 0.97
            vy_arr *= 0.97

        px_arr += vx_arr
        py_arr += vy_arr
        px_arr = np.clip(px_arr, 5, WIDTH - 5)
        py_arr = np.clip(py_arr, 5, HEIGHT - 5)

        # Render
        img = make_bg_gradient().copy()
        draw_ambient_dust(img, t, dust, color=(35, 30, 55))

        # Draw particles with REAL glow
        for i in range(num_particles):
            x, y = px_arr[i], py_arr[i]
            if 0 <= x < WIDTH and 0 <= y < HEIGHT:
                r, g, b = colors[i]
                sz = sizes[i]

                # Outer glow
                draw_glow(img, x, y, sz * 3, (int(r * 0.4), int(g * 0.4), int(b * 0.4)), 0.3)

                # Core bright dot
                ix, iy = int(x), int(y)
                s = int(sz)
                for ddx in range(-s, s + 1):
                    for ddy in range(-s, s + 1):
                        nx, ny = ix + ddx, iy + ddy
                        if 0 <= nx < WIDTH and 0 <= ny < HEIGHT:
                            d = math.sqrt(ddx * ddx + ddy * ddy)
                            fade = max(0, 1 - d / (sz + 0.5))
                            img[ny, nx] = np.clip(
                                img[ny, nx].astype(int) + [int(r * fade * 0.8),
                                                            int(g * fade * 0.8),
                                                            int(b * fade * 0.8)], 0, 255
                            ).astype(np.uint8)

        frames.append(img)
        if f % FPS == 0:
            print(f'  {f}/{frames_count}')

    _save_video(frames, output_path)


def _shape_heart(n):
    pts = []
    cx, cy = WIDTH / 2, HEIGHT / 2
    for i in range(n):
        t = 2 * math.pi * i / n
        x = 16 * math.sin(t)**3
        y = -(13 * math.cos(t) - 5 * math.cos(2*t) - 2 * math.cos(3*t) - math.cos(4*t))
        r = random.uniform(0.3, 1.0)
        pts.append((cx + x * 20 * r, cy + y * 20 * r))
    return np.array(pts)


def _shape_infinity(n):
    pts = []
    cx, cy = WIDTH / 2, HEIGHT / 2
    for i in range(n):
        t = 2 * math.pi * i / n
        denom = 1 + math.sin(t)**2
        x = math.cos(t) / denom
        y = math.sin(t) * math.cos(t) / denom
        r = random.uniform(0.7, 1.0)
        pts.append((cx + x * 380 * r, cy + y * 280 * r))
    return np.array(pts)


def _shape_couple_silhouette(n):
    pts = []
    cx, cy = WIDTH / 2, HEIGHT / 2
    for i in range(n):
        if i < n // 2:
            angle = 2 * math.pi * i / (n // 2)
            if i < n // 6:
                r = 70
                pts.append((cx - 90 + r * math.cos(angle), cy - 130 + r * math.sin(angle)))
            else:
                pts.append((cx - 90 + random.gauss(0, 35), cy + random.uniform(-60, 140)))
        else:
            j = i - n // 2
            angle = 2 * math.pi * j / (n // 2)
            if j < n // 6:
                r = 70
                pts.append((cx + 90 + r * math.cos(angle), cy - 130 + r * math.sin(angle)))
            else:
                pts.append((cx + 90 + random.gauss(0, 35), cy + random.uniform(-60, 140)))
    return np.array(pts)


# ============================================================
# STYLE 5: ZOOM — бесконечный зум внутрь
# Hook: "что будет дальше?"
# ============================================================
def generate_zoom(output_path, duration=12):
    frames_count = FPS * duration
    random.seed(55)

    num_layers = 40
    layers = []
    for i in range(num_layers):
        shapes = []
        n_shapes = random.randint(4, 10)
        for _ in range(n_shapes):
            shapes.append({
                'type': random.choice(['circle', 'ring', 'heart_small', 'heart_small']),
                'x': random.gauss(0, 0.25),
                'y': random.gauss(0, 0.25),
                'size': random.uniform(0.03, 0.12),
                'color': random.choice([
                    (255, 80, 130), (220, 70, 255), (100, 170, 255),
                    (255, 170, 80), (180, 255, 100), (255, 140, 200),
                    (120, 255, 200), (255, 100, 100),
                ]),
                'rotation': random.uniform(0, math.pi * 2),
                'glow_radius': random.uniform(20, 50),
            })
        layers.append(shapes)

    zoom_speed = 0.2
    dust = make_dust_particles(80)

    print(f'Generating zoom: {frames_count} frames...')
    frames = []

    for f in range(frames_count):
        t = f / FPS
        current_zoom = math.exp(t * zoom_speed)

        img = make_bg_gradient().copy()
        draw_ambient_dust(img, t, dust, color=(40, 35, 60))

        pil_img = Image.fromarray(img)
        draw = ImageDraw.Draw(pil_img)

        cx, cy = WIDTH / 2, HEIGHT / 2

        # Center glow (vortex feel)
        draw_glow(img, cx, cy, 120, (20, 15, 40), 0.5)

        for layer_idx in range(num_layers):
            depth = (layer_idx + 1) * 1.8
            scale = current_zoom / depth

            if scale < 0.008 or scale > 60:
                continue

            alpha = min(1.0, scale * 3) * min(1.0, 4.0 / scale)
            if alpha < 0.03:
                continue

            for shape in layers[layer_idx]:
                sx = cx + shape['x'] * WIDTH * scale
                sy = cy + shape['y'] * HEIGHT * scale
                sz = shape['size'] * min(WIDTH, HEIGHT) * scale
                r, g, b = shape['color']
                r = int(r * alpha)
                g = int(g * alpha)
                b = int(b * alpha)

                if sz < 2 or sz > 3000:
                    continue
                if sx < -sz * 2 or sx > WIDTH + sz * 2 or sy < -sz * 2 or sy > HEIGHT + sz * 2:
                    continue

                line_w = max(2, int(sz * 0.12))

                if shape['type'] == 'circle':
                    draw.ellipse([sx - sz, sy - sz, sx + sz, sy + sz],
                                 outline=(r, g, b), width=line_w)
                elif shape['type'] == 'ring':
                    for ring_r in [sz, sz * 0.65]:
                        if ring_r > 3:
                            draw.ellipse([sx - ring_r, sy - ring_r, sx + ring_r, sy + ring_r],
                                         outline=(r, g, b), width=max(2, int(ring_r * 0.08)))
                elif shape['type'] == 'heart_small':
                    if sz > 8:
                        heart_pts = []
                        for hi in range(30):
                            ht = 2 * math.pi * hi / 30
                            hx = 16 * math.sin(ht)**3
                            hy = -(13 * math.cos(ht) - 5 * math.cos(2*ht) - 2 * math.cos(3*ht) - math.cos(4*ht))
                            heart_pts.append((sx + hx * sz / 16, sy + hy * sz / 16))
                        if len(heart_pts) > 2:
                            draw.polygon(heart_pts, outline=(r, g, b))
                            # Filled with lower alpha
                            fr = max(0, r // 4)
                            fg = max(0, g // 4)
                            fb = max(0, b // 4)
                            draw.polygon(heart_pts, fill=(fr, fg, fb))

        # Apply glow blur
        pil_blurred = pil_img.filter(ImageFilter.GaussianBlur(radius=4))
        img_sharp = np.array(pil_img).astype(np.float32)
        img_blur = np.array(pil_blurred).astype(np.float32)
        img = np.clip(img_sharp + img_blur * 0.6, 0, 255).astype(np.uint8)

        frames.append(img)
        if f % FPS == 0:
            print(f'  {f}/{frames_count}')

    _save_video(frames, output_path)


# ============================================================
# Video encoder
# ============================================================
def _save_video(frames, output_path):
    print(f'Encoding {len(frames)} frames to {output_path}...')
    from moviepy import ImageSequenceClip

    clip = ImageSequenceClip(frames, fps=FPS)
    clip.write_videofile(
        output_path, fps=FPS, codec='libx264',
        audio=False, logger='bar',
        ffmpeg_params=['-pix_fmt', 'yuv420p', '-crf', '18', '-preset', 'fast']
    )
    print(f'Done: {output_path}')


STYLES = {
    'orbits':   ('Two orbs attracting/repelling — "will they connect?"', generate_orbits),
    'drawing':  ('Self-drawing line reveals shapes — "what is it?"', generate_drawing),
    'morph':    ('Heart breaks and reassembles — satisfying loop', generate_morph),
    'assemble': ('Particles chaos → shape → dissolve — "what will form?"', generate_assemble),
    'zoom':     ('Infinite zoom through layers — "what\'s next?"', generate_zoom),
}


def main():
    parser = argparse.ArgumentParser(description='Generate viral animated backgrounds')
    parser.add_argument('style', nargs='?', help='Style name')
    parser.add_argument('-o', '--output', help='Output path')
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--duration', type=int, default=12)
    args = parser.parse_args()

    if args.list or not args.style:
        print('Available viral background styles:')
        for name, (desc, _) in STYLES.items():
            print(f'  {name:12s} — {desc}')
        return

    if args.style not in STYLES:
        print(f'Unknown: {args.style}. Available: {", ".join(STYLES.keys())}')
        sys.exit(1)

    output = args.output or f'input/backgrounds/vbg_{args.style}.mp4'
    os.makedirs(os.path.dirname(output) or '.', exist_ok=True)

    _, gen = STYLES[args.style]
    gen(output, args.duration)


if __name__ == '__main__':
    main()
