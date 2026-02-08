#!/usr/bin/env python3
"""
Pixel art animated background generator for Reels (1080x1920, 9:16).

Generates hypnotic, dark, text-friendly animated backgrounds.

Usage:
    python scripts/pixel_backgrounds.py neon_rain -o input/backgrounds/pixel_neon_rain.mp4
    python scripts/pixel_backgrounds.py heart_matrix -o input/backgrounds/pixel_heart_matrix.mp4
    python scripts/pixel_backgrounds.py cozy_room -o input/backgrounds/pixel_cozy_room.mp4
    python scripts/pixel_backgrounds.py --list
"""

import argparse
import math
import os
import random
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

# Output dimensions (9:16 Reels)
WIDTH = 1080
HEIGHT = 1920
FPS = 30
DURATION = 12  # seconds, enough for a loop


def lerp(a, b, t):
    return a + (b - a) * max(0, min(1, t))


def hex_to_rgb(h):
    return (int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16))


def ease_in_out(t):
    return t * t * (3 - 2 * t)


# ============================================================
# STYLE 1: NEON RAIN — неоновые капли дождя на тёмном фоне
# ============================================================
def generate_neon_rain(output_path):
    """Neon pink/purple rain drops falling with glow trails on dark background."""
    frames_count = FPS * DURATION
    random.seed(12)

    # Rain columns
    num_columns = 60
    columns = []
    for _ in range(num_columns):
        columns.append({
            'x': random.randint(0, WIDTH),
            'speed': random.uniform(400, 900),  # px/sec
            'y_offset': random.uniform(-HEIGHT, 0),
            'length': random.randint(40, 180),
            'width': random.choice([2, 3, 4]),
            'hue': random.choice(['#FF4D6D', '#FF6B9D', '#C77DFF', '#9D4EDD', '#E88D9D', '#F472B6']),
            'glow_radius': random.choice([6, 8, 10, 12]),
        })

    # Floating orbs (large, slow, blurry)
    num_orbs = 8
    orbs = []
    for _ in range(num_orbs):
        orbs.append({
            'x': random.uniform(100, WIDTH - 100),
            'y': random.uniform(200, HEIGHT - 200),
            'radius': random.uniform(40, 120),
            'color': random.choice(['#FF4D6D', '#C77DFF', '#7B2FBE', '#E88D9D']),
            'drift_x': random.uniform(-20, 20),
            'drift_y': random.uniform(-15, 15),
            'phase': random.uniform(0, math.pi * 2),
            'pulse_speed': random.uniform(0.3, 0.8),
        })

    # Horizontal neon lines (subtle)
    lines = []
    for i in range(5):
        lines.append({
            'y': random.randint(300, HEIGHT - 300),
            'alpha_base': random.uniform(0.03, 0.08),
            'phase': random.uniform(0, math.pi * 2),
        })

    print(f'Generating {frames_count} frames...')
    frames = []

    for f in range(frames_count):
        t = f / FPS

        # Dark gradient background
        img = Image.new('RGBA', (WIDTH, HEIGHT), (8, 5, 18, 255))
        draw = ImageDraw.Draw(img)

        # Gradient: slightly lighter at top
        for y in range(0, HEIGHT, 4):
            frac = y / HEIGHT
            r = int(lerp(15, 5, frac))
            g = int(lerp(8, 3, frac))
            b = int(lerp(30, 12, frac))
            draw.rectangle([0, y, WIDTH, y + 4], fill=(r, g, b))

        # Subtle horizontal lines
        for line in lines:
            alpha = int((line['alpha_base'] + 0.02 * math.sin(t * 0.5 + line['phase'])) * 255)
            alpha = max(0, min(255, alpha))
            draw.rectangle([0, line['y'], WIDTH, line['y'] + 1], fill=(180, 120, 255, alpha))

        # Glow orbs (on a separate layer, then blur)
        orb_layer = Image.new('RGBA', (WIDTH, HEIGHT), (0, 0, 0, 0))
        orb_draw = ImageDraw.Draw(orb_layer)

        for orb in orbs:
            ox = orb['x'] + orb['drift_x'] * math.sin(t * 0.3 + orb['phase'])
            oy = orb['y'] + orb['drift_y'] * math.cos(t * 0.25 + orb['phase'])
            pulse = 0.5 + 0.5 * math.sin(t * orb['pulse_speed'] + orb['phase'])
            radius = orb['radius'] * (0.8 + 0.4 * pulse)
            alpha = int(lerp(15, 40, pulse))

            r, g, b = hex_to_rgb(orb['color'])
            # Draw concentric circles for soft glow
            for ring in range(int(radius), 0, -3):
                ring_alpha = int(alpha * (ring / radius))
                orb_draw.ellipse(
                    [int(ox - ring), int(oy - ring), int(ox + ring), int(oy + ring)],
                    fill=(r, g, b, ring_alpha)
                )

        # Blur the orb layer for soft glow
        orb_layer = orb_layer.filter(ImageFilter.GaussianBlur(radius=30))
        img = Image.alpha_composite(img, orb_layer)
        draw = ImageDraw.Draw(img)

        # Rain drops with glow
        rain_layer = Image.new('RGBA', (WIDTH, HEIGHT), (0, 0, 0, 0))
        rain_draw = ImageDraw.Draw(rain_layer)

        for col in columns:
            y_pos = (col['y_offset'] + t * col['speed']) % (HEIGHT + col['length'] * 2) - col['length']
            r, g, b = hex_to_rgb(col['hue'])

            # Draw the rain streak
            for seg in range(col['length']):
                sy = int(y_pos + seg)
                if 0 <= sy < HEIGHT:
                    # Fade: bright at bottom (head), dim at top (tail)
                    fade = 1.0 - (seg / col['length'])
                    alpha = int(255 * fade * fade)

                    # Core (bright)
                    rain_draw.rectangle(
                        [col['x'], sy, col['x'] + col['width'], sy + 1],
                        fill=(r, g, b, alpha)
                    )
                    # Glow (wider, dimmer)
                    glow_w = col['glow_radius']
                    glow_alpha = int(alpha * 0.15)
                    rain_draw.rectangle(
                        [col['x'] - glow_w, sy, col['x'] + col['width'] + glow_w, sy + 1],
                        fill=(r, g, b, glow_alpha)
                    )

        # Light blur on rain for softness
        rain_layer = rain_layer.filter(ImageFilter.GaussianBlur(radius=2))
        img = Image.alpha_composite(img, rain_layer)

        # Floor reflection (bottom 15%)
        reflect_start = int(HEIGHT * 0.88)
        reflect = img.crop((0, reflect_start - 200, WIDTH, reflect_start))
        reflect = reflect.transpose(Image.FLIP_TOP_BOTTOM)
        reflect = reflect.resize((WIDTH, HEIGHT - reflect_start))
        reflect_with_alpha = reflect.copy()
        # Fade reflection
        alpha_gradient = Image.new('L', reflect_with_alpha.size, 0)
        ag_draw = ImageDraw.Draw(alpha_gradient)
        for ry in range(reflect_with_alpha.size[1]):
            a = int(50 * (1 - ry / reflect_with_alpha.size[1]))
            ag_draw.rectangle([0, ry, WIDTH, ry + 1], fill=a)
        reflect_with_alpha.putalpha(alpha_gradient)
        img.paste(reflect_with_alpha, (0, reflect_start), reflect_with_alpha)

        # Convert to RGB for video
        final = Image.new('RGB', (WIDTH, HEIGHT), (0, 0, 0))
        final.paste(img, mask=img.split()[3] if img.mode == 'RGBA' else None)
        frames.append(np.array(final))

        if f % FPS == 0:
            print(f'  {f}/{frames_count} ({int(f/frames_count*100)}%)')

    _save_video(frames, output_path)


# ============================================================
# STYLE 2: HEART MATRIX — сердца падают как в Матрице
# ============================================================
def generate_heart_matrix(output_path):
    """Hearts falling in Matrix-style columns on dark background."""
    frames_count = FPS * DURATION
    random.seed(7)

    # Heart pixel pattern (7x6 grid)
    HEART = [
        [0,1,1,0,1,1,0],
        [1,1,1,1,1,1,1],
        [1,1,1,1,1,1,1],
        [0,1,1,1,1,1,0],
        [0,0,1,1,1,0,0],
        [0,0,0,1,0,0,0],
    ]

    cell_size = 6  # pixels per heart-pixel
    heart_w = 7 * cell_size  # 42px
    heart_h = 6 * cell_size  # 36px

    num_columns = WIDTH // (heart_w + 10)

    columns = []
    for i in range(num_columns):
        x = i * (heart_w + 10) + 5
        columns.append({
            'x': x,
            'speed': random.uniform(60, 200),
            'hearts': [],
            'spawn_rate': random.uniform(0.3, 1.2),  # hearts per second
            'next_spawn': random.uniform(0, 2),
            'color_base': random.choice([
                ('#FF4D6D', '#FF8FA3', '#FFB3C6'),  # pink
                ('#C77DFF', '#9D4EDD', '#D4AAFF'),  # purple
                ('#FF6B9D', '#E88D9D', '#FFD1DC'),  # rose
            ]),
        })

    def draw_heart(draw, x, y, cell, colors, age):
        """Draw a single pixel heart with fade based on age."""
        fade = max(0, 1.0 - age / 8.0)  # fade over 8 seconds
        if fade <= 0:
            return

        for row_i, row in enumerate(HEART):
            for col_i, val in enumerate(row):
                if val:
                    # Color: newest = bright, oldest = dim
                    if age < 0.5:
                        color = colors[0]
                    elif age < 3:
                        color = colors[1]
                    else:
                        color = colors[2]

                    r, g, b = hex_to_rgb(color)
                    alpha = int(255 * fade)
                    px_x = x + col_i * cell
                    px_y = y + row_i * cell
                    if 0 <= px_y < HEIGHT and 0 <= px_x < WIDTH:
                        draw.rectangle(
                            [px_x, px_y, px_x + cell - 1, px_y + cell - 1],
                            fill=(r, g, b, alpha)
                        )

    print(f'Generating {frames_count} frames...')
    frames = []

    for f in range(frames_count):
        t = f / FPS
        dt = 1.0 / FPS

        img = Image.new('RGBA', (WIDTH, HEIGHT), (5, 3, 15, 255))
        draw = ImageDraw.Draw(img)

        # Dark gradient
        for y in range(0, HEIGHT, 8):
            frac = y / HEIGHT
            r = int(lerp(10, 3, frac))
            g = int(lerp(5, 2, frac))
            b = int(lerp(22, 8, frac))
            draw.rectangle([0, y, WIDTH, y + 8], fill=(r, g, b))

        for col in columns:
            # Spawn new hearts
            col['next_spawn'] -= dt
            if col['next_spawn'] <= 0:
                col['hearts'].append({'y': -heart_h, 'age': 0})
                col['next_spawn'] = 1.0 / col['spawn_rate'] + random.uniform(-0.3, 0.3)

            # Update and draw hearts
            alive = []
            for heart in col['hearts']:
                heart['y'] += col['speed'] * dt
                heart['age'] += dt

                if heart['y'] < HEIGHT + 50 and heart['age'] < 10:
                    draw_heart(draw, col['x'], int(heart['y']), cell_size, col['color_base'], heart['age'])
                    alive.append(heart)

            col['hearts'] = alive

        # Subtle glow overlay
        glow = Image.new('RGBA', (WIDTH, HEIGHT), (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow)
        # Central glow
        cx, cy = WIDTH // 2, HEIGHT // 2
        pulse = 0.5 + 0.5 * math.sin(t * 0.4)
        for ring in range(200, 0, -5):
            a = int(3 * pulse * (ring / 200))
            glow_draw.ellipse(
                [cx - ring * 3, cy - ring * 4, cx + ring * 3, cy + ring * 4],
                fill=(200, 80, 180, a)
            )
        glow = glow.filter(ImageFilter.GaussianBlur(radius=40))
        img = Image.alpha_composite(img, glow)

        final = Image.new('RGB', (WIDTH, HEIGHT), (0, 0, 0))
        final.paste(img, mask=img.split()[3])
        frames.append(np.array(final))

        if f % FPS == 0:
            print(f'  {f}/{frames_count} ({int(f/frames_count*100)}%)')

    _save_video(frames, output_path)


# ============================================================
# STYLE 3: COZY ROOM — lo-fi комната ночью с дождём
# ============================================================
def generate_cozy_room(output_path):
    """Lo-fi pixel art room at night: window with rain, warm lamp, plant."""
    frames_count = FPS * DURATION
    random.seed(99)

    PX = 6  # pixel size for chunky retro look

    # Color palette
    WALL = (25, 20, 40)
    WALL_LIGHT = (35, 28, 55)
    FLOOR = (20, 16, 30)
    WINDOW_FRAME = (45, 35, 60)
    NIGHT_SKY = (10, 8, 25)
    LAMP_ON = (255, 200, 100)
    LAMP_WARM = (255, 180, 80)
    LAMP_BODY = (60, 50, 80)
    DESK = (50, 40, 65)
    PLANT_POT = (70, 55, 45)
    PLANT_GREEN = (40, 120, 60)
    PLANT_GREEN2 = (60, 150, 80)
    RAIN_COLOR = (120, 140, 200)
    CURTAIN = (40, 30, 55)

    # Window position (centered, upper half)
    win_x, win_y = 280, 200
    win_w, win_h = 520, 600

    # Rain drops
    rain_drops = []
    for _ in range(150):
        rain_drops.append({
            'x': random.randint(win_x + 20, win_x + win_w - 20),
            'y': random.randint(win_y, win_y + win_h),
            'speed': random.uniform(200, 500),
            'length': random.randint(8, 25),
        })

    # Stars in window
    stars = [(random.randint(win_x + 30, win_x + win_w - 30),
              random.randint(win_y + 20, win_y + 200),
              random.uniform(0, math.pi * 2))
             for _ in range(15)]

    print(f'Generating {frames_count} frames...')
    frames = []

    for f in range(frames_count):
        t = f / FPS

        img = Image.new('RGB', (WIDTH, HEIGHT), WALL)
        draw = ImageDraw.Draw(img)

        # Wall gradient (lighter near lamp)
        lamp_cx, lamp_cy = 820, 900
        for y in range(0, HEIGHT, PX):
            for x in range(0, WIDTH, PX):
                dist = math.sqrt((x - lamp_cx)**2 + (y - lamp_cy)**2) / 600
                dist = min(1, dist)
                warmth = (1 - dist) * 0.15
                pulse = 0.005 * math.sin(t * 3 + dist * 5)  # lamp flicker
                r = int(WALL[0] + warmth * 80 + pulse * 30)
                g = int(WALL[1] + warmth * 50 + pulse * 20)
                b = int(WALL[2] + warmth * 20)
                draw.rectangle([x, y, x + PX - 1, y + PX - 1], fill=(
                    max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))
                ))

        # Floor (bottom 30%)
        floor_y = int(HEIGHT * 0.72)
        for y in range(floor_y, HEIGHT, PX):
            frac = (y - floor_y) / (HEIGHT - floor_y)
            r = int(lerp(FLOOR[0] + 5, FLOOR[0], frac))
            g = int(lerp(FLOOR[1] + 3, FLOOR[1], frac))
            b = int(lerp(FLOOR[2] + 8, FLOOR[2], frac))
            draw.rectangle([0, y, WIDTH, y + PX - 1], fill=(r, g, b))

        # Floor line
        draw.rectangle([0, floor_y, WIDTH, floor_y + PX], fill=(35, 28, 50))

        # === WINDOW ===
        # Frame
        frame_t = 16
        draw.rectangle([win_x - frame_t, win_y - frame_t,
                        win_x + win_w + frame_t, win_y + win_h + frame_t], fill=WINDOW_FRAME)
        # Night sky inside
        for wy in range(win_y, win_y + win_h, PX):
            sky_frac = (wy - win_y) / win_h
            r = int(lerp(12, 8, sky_frac))
            g = int(lerp(10, 6, sky_frac))
            b = int(lerp(35, 18, sky_frac))
            draw.rectangle([win_x, wy, win_x + win_w, wy + PX - 1], fill=(r, g, b))

        # Crossbar
        mid_x = win_x + win_w // 2
        mid_y = win_y + win_h // 2
        draw.rectangle([mid_x - 4, win_y, mid_x + 4, win_y + win_h], fill=WINDOW_FRAME)
        draw.rectangle([win_x, mid_y - 4, win_x + win_w, mid_y + 4], fill=WINDOW_FRAME)

        # Stars (twinkling)
        for sx, sy, sp in stars:
            twinkle = 0.4 + 0.6 * (0.5 + 0.5 * math.sin(t * 2 + sp))
            alpha = int(200 * twinkle)
            star_size = PX if twinkle > 0.7 else PX // 2
            draw.rectangle([sx, sy, sx + star_size, sy + star_size],
                          fill=(255, 255, int(200 + 55 * twinkle)))

        # Rain on window
        for drop in rain_drops:
            dy = (drop['y'] + t * drop['speed']) % win_h + win_y
            if win_y < dy < win_y + win_h:
                for seg in range(drop['length']):
                    ry = int(dy + seg)
                    if win_y < ry < win_y + win_h:
                        fade = 1.0 - seg / drop['length']
                        r_c = int(RAIN_COLOR[0] * fade)
                        g_c = int(RAIN_COLOR[1] * fade)
                        b_c = int(RAIN_COLOR[2] * fade)
                        draw.rectangle([drop['x'], ry, drop['x'] + 2, ry + 1],
                                      fill=(r_c, g_c, b_c))

        # Curtains (left and right)
        sway = int(3 * math.sin(t * 0.8))
        draw.rectangle([win_x - frame_t - 30 + sway, win_y - frame_t,
                        win_x - frame_t + sway, win_y + win_h + frame_t], fill=CURTAIN)
        draw.rectangle([win_x + win_w + frame_t - sway, win_y - frame_t,
                        win_x + win_w + frame_t + 30 - sway, win_y + win_h + frame_t], fill=CURTAIN)

        # === DESK ===
        desk_y = floor_y - 30
        draw.rectangle([650, desk_y, 1050, desk_y + 20], fill=DESK)
        # Desk legs
        draw.rectangle([670, desk_y + 20, 685, floor_y], fill=DESK)
        draw.rectangle([1020, desk_y + 20, 1035, floor_y], fill=DESK)

        # === LAMP on desk ===
        # Lamp stand
        draw.rectangle([830, desk_y - 120, 840, desk_y], fill=LAMP_BODY)
        # Lamp shade
        draw.polygon([(790, desk_y - 120), (880, desk_y - 120),
                       (860, desk_y - 170), (810, desk_y - 170)], fill=LAMP_BODY)
        # Lamp glow (bulb)
        flicker = 0.92 + 0.08 * math.sin(t * 7.3)
        glow_r = int(LAMP_ON[0] * flicker)
        glow_g = int(LAMP_ON[1] * flicker)
        glow_b = int(LAMP_ON[2] * flicker)
        draw.ellipse([815, desk_y - 145, 855, desk_y - 120], fill=(glow_r, glow_g, glow_b))

        # === PLANT ===
        # Pot
        pot_x, pot_y = 150, floor_y - 120
        draw.rectangle([pot_x, pot_y, pot_x + 60, floor_y], fill=PLANT_POT)
        draw.rectangle([pot_x - 5, pot_y, pot_x + 65, pot_y + 12], fill=PLANT_POT)

        # Leaves (swaying slightly)
        sway2 = 2 * math.sin(t * 0.6)
        for lx, ly, angle in [(-15, -40, -30), (20, -50, 10), (40, -30, 40),
                               (0, -60, -10), (30, -55, 25)]:
            leaf_x = pot_x + 30 + lx + int(sway2)
            leaf_y = pot_y + ly
            draw.ellipse([leaf_x - 12, leaf_y - 8, leaf_x + 12, leaf_y + 8],
                        fill=PLANT_GREEN if angle < 0 else PLANT_GREEN2)

        # Stem
        draw.rectangle([pot_x + 28, pot_y - 10, pot_x + 32, pot_y], fill=(30, 80, 40))

        # === COFFEE MUG on desk ===
        mug_x = 720
        draw.rectangle([mug_x, desk_y - 30, mug_x + 25, desk_y], fill=(80, 65, 100))
        draw.rectangle([mug_x - 3, desk_y - 30, mug_x + 28, desk_y - 25], fill=(80, 65, 100))
        # Steam
        for si in range(3):
            steam_y = desk_y - 35 - si * 15 - int(t * 8) % 20
            steam_x = mug_x + 10 + int(5 * math.sin(t * 1.5 + si))
            if steam_y > desk_y - 80:
                alpha = max(0, 150 - si * 40 - int(t * 8) % 20 * 3)
                draw.ellipse([steam_x - 4, steam_y - 3, steam_x + 4, steam_y + 3],
                            fill=(200, 200, 220))

        # Warm light cone from lamp (overlay)
        light_layer = Image.new('RGBA', (WIDTH, HEIGHT), (0, 0, 0, 0))
        light_draw = ImageDraw.Draw(light_layer)
        for ring in range(300, 0, -5):
            a = int(6 * flicker * (ring / 300))
            light_draw.ellipse([
                lamp_cx - ring, lamp_cy - 200 - ring,
                lamp_cx + ring, lamp_cy - 200 + int(ring * 1.5)
            ], fill=(255, 180, 80, a))
        light_layer = light_layer.filter(ImageFilter.GaussianBlur(radius=20))

        img_rgba = img.convert('RGBA')
        img_rgba = Image.alpha_composite(img_rgba, light_layer)
        final = img_rgba.convert('RGB')

        frames.append(np.array(final))

        if f % FPS == 0:
            print(f'  {f}/{frames_count} ({int(f/frames_count*100)}%)')

    _save_video(frames, output_path)


# ============================================================
# Video encoder
# ============================================================
def _save_video(frames, output_path):
    print(f'Encoding {len(frames)} frames to {output_path}...')
    from moviepy import ImageSequenceClip

    clip = ImageSequenceClip(frames, fps=FPS)
    clip.write_videofile(
        output_path,
        fps=FPS,
        codec='libx264',
        audio=False,
        logger='bar',
        ffmpeg_params=['-pix_fmt', 'yuv420p', '-crf', '18', '-preset', 'fast']
    )
    print(f'Done: {output_path}')


# ============================================================
# CLI
# ============================================================
STYLES = {
    'neon_rain': ('Neon Rain — неоновые капли на тёмном фоне с отражениями', generate_neon_rain),
    'heart_matrix': ('Heart Matrix — сердца падают как в Матрице', generate_heart_matrix),
    'cozy_room': ('Cozy Room — lo-fi комната ночью с дождём и лампой', generate_cozy_room),
}


def main():
    parser = argparse.ArgumentParser(description='Generate pixel art animated backgrounds for Reels')
    parser.add_argument('style', nargs='?', help='Background style name')
    parser.add_argument('-o', '--output', help='Output path (default: input/backgrounds/pixel_STYLE.mp4)')
    parser.add_argument('--list', action='store_true', help='List available styles')
    parser.add_argument('--duration', type=int, default=DURATION, help=f'Duration in seconds (default: {DURATION})')
    args = parser.parse_args()

    if args.list or not args.style:
        print('Available styles:')
        for name, (desc, _) in STYLES.items():
            print(f'  {name:20s} — {desc}')
        if not args.style:
            parser.print_help()
        return

    if args.style not in STYLES:
        print(f'Unknown style: {args.style}')
        print(f'Available: {", ".join(STYLES.keys())}')
        sys.exit(1)

    duration = args.duration

    output = args.output or f'input/backgrounds/pixel_{args.style}.mp4'
    os.makedirs(os.path.dirname(output) or '.', exist_ok=True)

    _, generator = STYLES[args.style]
    # Patch module-level duration
    sys.modules[__name__].DURATION = duration
    generator(output)


if __name__ == '__main__':
    main()
