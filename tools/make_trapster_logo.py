"""Trapster icon v3: white patas silhouette (traced from reference, head turned to profile),
lime rounded square, orange ground. No sun circle."""
import sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont
import glob

L = "/home/claude/logo/"
FONT_BOLD = glob.glob("/usr/share/fonts/**/Inter-ExtraBold.otf", recursive=True)[0]
FONT_MED = glob.glob("/usr/share/fonts/**/Inter-Medium.otf", recursive=True)[0]
LIME = (150, 205, 60)
LIME_DARK = (104, 160, 38)
ORANGE = (247, 147, 30)
OLIVE_DARK = (54, 64, 31)


def silhouette():
    m = np.array(Image.open(L + "src/patas_mask.png"))
    # profile muzzle: brow -> nose -> mouth -> chin, added in front of the flat face
    pts = np.array([[128, 205], [104, 228], [86, 252], [80, 270], [90, 284], [104, 292],
                    [102, 304], [118, 318], [140, 326], [150, 270]], np.int32)
    cv2.fillPoly(m, [pts], 255)
    # trim the fuzzy cheek tufts so the head reads as one rounded shape
    cv2.ellipse(m, (205, 225), (95, 92), 0, 0, 360, 255, -1)
    # extra smoothing for a clean graphic outline
    m = cv2.GaussianBlur(m, (0, 0), 6.5)
    m = np.where(m > 128, 255, 0).astype(np.uint8)
    # eye cut-out
    # (no eye)
    return m


MONKEY = (255, 255, 255, 255)


def icon(size=1024):
    S = 2048
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    bg = Image.new("RGBA", (S, S))
    d = ImageDraw.Draw(bg)
    for y in range(S):
        t = y / S
        d.line([(0, y), (S, y)], fill=tuple(int(LIME[i] * (1 - t) + LIME_DARK[i] * t) for i in range(3)) + (255,))
    ground = int(S * 0.80)
    d.rectangle([0, ground, S, S], fill=ORANGE + (255,))
    d.rectangle([0, ground, S, ground + 10], fill=(255, 226, 180, 255))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.22), fill=255)
    img.paste(bg, (0, 0), mask)

    sil = silhouette()
    ys, xs = np.nonzero(sil)
    crop = sil[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    target_w = int(S * 0.72)
    scale = target_w / crop.shape[1]
    new = (target_w, int(crop.shape[0] * scale))
    crop = cv2.resize(crop, new, interpolation=cv2.INTER_CUBIC)
    white = Image.new("RGBA", new, MONKEY)
    x0 = (S - new[0]) // 2 + int(S * 0.005)
    y0 = ground - new[1] + int(S * 0.012)     # feet just on the ground line
    img.paste(white, (x0, y0), Image.fromarray(crop))
    return img.resize((size, size), Image.LANCZOS)


def lockup(path, dark_bg):
    ic = icon(520)
    W_, H_ = 1800, 640
    im = Image.new("RGBA", (W_, H_), OLIVE_DARK + (255,) if dark_bg else (0, 0, 0, 0))
    im.alpha_composite(ic, (60, 60))
    d = ImageDraw.Draw(im)
    d.text((650, 120), "Trapster", font=ImageFont.truetype(FONT_BOLD, 250),
           fill=(255, 255, 255, 255) if dark_bg else OLIVE_DARK + (255,))
    d.text((660, 420), "by Wildsolutions", font=ImageFont.truetype(FONT_MED, 82), fill=ORANGE + (255,))
    im.save(path)


out = sys.argv[1]
if len(sys.argv) > 2 and sys.argv[2] == "dark":
    MONKEY = (38, 58, 20, 255)  # dark green
    out = out + "dark_"
big = icon(1024)
big.save(out + "trapster_icon_1024.png")
for s in (256, 64, 32):
    icon(s).save(out + f"trapster_icon_{s}.png")
lockup(out + "trapster_logo_dark.png", True)
lockup(out + "trapster_logo_transparent_light_text.png", False)
# preview sheet
sheet = Image.new("RGBA", (1900, 1060), OLIVE_DARK + (255,))
x = 60
for s in (380, 128, 64, 32, 16):
    sheet.alpha_composite(big.resize((s, s), Image.LANCZOS), (x, 50 + (380 - s) // 2))
    x += s + 50
dark = Image.open(out + "trapster_logo_dark.png").resize((1350, 480), Image.LANCZOS)
sheet.alpha_composite(dark, (40, 520))
sheet.convert("RGB").save(out + "trapster_preview_v3.png")
print("ok")
