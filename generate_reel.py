#!/usr/bin/env python3
"""
VocabReelGenerator — generate_reel.py

End-to-end pipeline:
  1. Render a 1080×1920 vocabulary card (Pillow)
  2. Generate Arabic + English voiceover (gTTS for English vocab, Gemini for Arabic vocab)
  3. Combine into an MP4 (FFmpeg)
  4. Upload to YouTube as a Short (YouTube Data API v3)
"""

import os
import sys
import csv
import json
import subprocess
import tempfile
import time
import shutil
import datetime
import urllib.request
from pathlib import Path


# ══════════════════════════════════════════════════════════════════════════════
# ❶  WORD LIST  ── edit this section to change the vocabulary
# ══════════════════════════════════════════════════════════════════════════════

WORD_PAIRS = [
    # (  Arabic word  ,   English translation  )
    ("مُسْتَدَام",    "Sustainable"),
    ("مُتَطَوِّر",    "Evolving"),
    ("اِزْدِهَار",    "Prosperity"),
    ("مُتَّسِق",      "Consistent"),
    ("إِبْدَاع",      "Creativity"),
]


# ══════════════════════════════════════════════════════════════════════════════
# ❷  YOUTUBE METADATA  ── edit title, description, and tags here
# ══════════════════════════════════════════════════════════════════════════════

# "private"   → only you can see it (good for reviewing before publishing)
# "unlisted"  → anyone with the link can see it
# "public"    → visible to everyone on YouTube
PRIVACY_STATUS = "public"

# In CI (GitHub Actions) this is overridden to "true" via env var.
# Locally it stays False so you never accidentally upload while designing.
UPLOAD_TO_YOUTUBE = os.getenv("UPLOAD_TO_YOUTUBE", "false").lower() == "true"

# Set to True to generate ONLY the image (skips audio, video, and upload).
PREVIEW_ONLY = os.getenv("PREVIEW_ONLY", "false").lower() == "true"

# Set to True to generate both reel types in one run.
RUN_BOTH_REELS = os.getenv("RUN_BOTH_REELS", "false").lower() == "true"

# Keep the existing daily flow as the default. Set ARABIC_WORDS_REEL=true for
# the newer "learn 7 Arabic words" reel type once its background is ready.
ARABIC_WORDS_REEL = os.getenv("ARABIC_WORDS_REEL", "false").lower() == "true"


# ══════════════════════════════════════════════════════════════════════════════
# ❸  PATHS & TIMING  ── usually no need to change these
# ══════════════════════════════════════════════════════════════════════════════

OUTPUT_DIR   = Path("outputs")
FONTS_DIR    = Path("assets") / "fonts"

SHEET_CSV_URL  = os.getenv("SHEET_CSV_URL", "https://docs.google.com/spreadsheets/d/e/2PACX-1vTwrDK1Jvw6JKf2wVntr4uq1ruHof4oe0z_blIlTIkanPEbbpOfH4p0agPZjZY_CfhiwmwpQ59YfY9x/pub?output=csv")
ARABIC_SHEET_CSV_URL = os.getenv("ARABIC_SHEET_CSV_URL", "https://docs.google.com/spreadsheets/d/e/2PACX-1vTiOO_C_FHe7QeNPitUx6BXkkJWgQ0yVXJdThwVciqR6bKW9URZ0gSQDrdk88E9zxlIEpiYNVWG9wp9/pub?output=csv")
ENGLISH_STATE_FILE = Path("state_english.json")
ARABIC_STATE_FILE  = Path("state_arabic.json")
WORDS_PER_REEL = 5
ARABIC_WORDS_PER_REEL = 7
FFMPEG_BIN = shutil.which("ffmpeg")
if not FFMPEG_BIN:
    for candidate in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if Path(candidate).exists():
            FFMPEG_BIN = candidate
            break
if FFMPEG_BIN:
    ffmpeg_dir = str(Path(FFMPEG_BIN).parent)
    os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
FFPROBE_BIN = shutil.which("ffprobe")
if not FFPROBE_BIN:
    for candidate in ("/opt/homebrew/bin/ffprobe", "/usr/local/bin/ffprobe"):
        if Path(candidate).exists():
            FFPROBE_BIN = candidate
            break

ARABIC_FONT_CANDIDATES = [
    FONTS_DIR / "Amiri-Regular.ttf",
    FONTS_DIR / "NotoNaskhArabic-Regular.ttf",
    Path("/System/Library/Fonts/GeezaPro.ttc"),                          # macOS — best Arabic
    Path("/System/Library/Fonts/SFArabic.ttf"),                          # macOS
    Path("/System/Library/Fonts/Supplemental/DecoTypeNaskh.ttc"),         # macOS fallback
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),        # macOS fallback
    Path("/Library/Fonts/Arial Unicode.ttf"),                            # macOS fallback
    Path("/usr/share/fonts/truetype/amiri/Amiri-Regular.ttf"),           # Ubuntu (CI)
    Path("/usr/share/fonts/truetype/hosny-amiri/Amiri-Regular.ttf"),      # Ubuntu package path
    Path("/usr/share/fonts/truetype/hosny-amiri/amiri-regular.ttf"),      # Ubuntu package path
    Path("/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf"),   # Ubuntu Noto Arabic
    Path("/usr/share/fonts/truetype/arabeyes/ae_AlArabiya.ttf"),         # Ubuntu fallback
]

ENGLISH_FONT_CANDIDATES = [
    Path("/System/Library/Fonts/Supplemental/Georgia.ttf"),              # macOS — elegant serif
    FONTS_DIR / "Roboto-Regular.ttf",
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),                # macOS fallback
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),  # Ubuntu (CI)
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),             # Ubuntu fallback
]

BOLD_FONT_CANDIDATES = [
    Path("/System/Library/Fonts/Supplemental/Georgia Bold.ttf"),         # macOS — elegant serif
    FONTS_DIR / "Roboto-Bold.ttf",
    Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),           # macOS fallback
    Path("/System/Library/Fonts/HelveticaNeue.ttc"),                     # macOS fallback
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),# Ubuntu (CI)
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),        # Ubuntu fallback
]

SECRETS_FILE = Path("client_secrets.json")  # from Google Cloud Console
TOKEN_FILE   = Path("token.json")            # auto-created after first login

IMG_W, IMG_H = 1080, 1920  # 9:16 portrait — required for YouTube Shorts

# How long to pause between spoken segments (milliseconds)
PAUSE_AFTER_ARABIC  = 600   # between Arabic and English of the same pair
PAUSE_AFTER_ENGLISH = 1200  # between one pair and the next

# Gemini is the preferred Arabic TTS provider. If GEMINI_API_KEY is missing,
# Arabic falls back to regular gTTS so local previews can still run.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-3.1-flash-tts-preview")
GEMINI_TTS_VOICE = os.getenv("GEMINI_TTS_VOICE", "Achird")
GEMINI_REEL_PROMPT_PREFIX = os.getenv(
    "GEMINI_REEL_PROMPT_PREFIX",
    "Fast friendly Egyptian Arabic lesson. For each item, say the English once, "
    "then pronounce the Egyptian Arabic twice. Speak clearly at a natural learning pace. "
    "Use brief pauses between repeats. Keep the full audio around 34 "
    "seconds. Avoid formal Arabic pronunciation. List:\n"
)
GEMINI_TTS_MAX_RETRIES = int(os.getenv("GEMINI_TTS_MAX_RETRIES", "2"))
GEMINI_TTS_RETRY_DELAY_SECONDS = int(os.getenv("GEMINI_TTS_RETRY_DELAY_SECONDS", "65"))


# ══════════════════════════════════════════════════════════════════════════════
# ❹  IMPORTS  ── with a clear error message if a package is missing
# ══════════════════════════════════════════════════════════════════════════════

def _require(module: str, pip_name: str = ""):
    """Import a module; exit with install instructions if it's not installed."""
    import importlib
    try:
        return importlib.import_module(module)
    except ImportError:
        pkg = pip_name or module
        sys.exit(
            f"\n  Missing package '{module}'.\n"
            f"  Fix: pip install {pkg}\n"
            f"  Or install everything at once: pip install -r requirements.txt\n"
        )


_require("PIL",                  "Pillow")
_require("gtts",                 "gTTS")
_require("pydub",                "pydub")
_require("arabic_reshaper",      "arabic-reshaper")
_require("bidi.algorithm",       "python-bidi")

from PIL import Image, ImageDraw, ImageFont, features
from gtts import gTTS
from pydub import AudioSegment
import arabic_reshaper
from bidi.algorithm import get_display

if FFMPEG_BIN:
    AudioSegment.converter = FFMPEG_BIN
if FFPROBE_BIN:
    AudioSegment.ffprobe = FFPROBE_BIN

if UPLOAD_TO_YOUTUBE:
    _require("googleapiclient",       "google-api-python-client")
    _require("google_auth_oauthlib",  "google-auth-oauthlib")
    _require("google.auth.transport", "google-auth-httplib2")

    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request


# ══════════════════════════════════════════════════════════════════════════════
# ❺  UTILITY HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def check_ffmpeg():
    """Confirm FFmpeg is on PATH before we start, so we fail early."""
    if not FFMPEG_BIN:
        sys.exit(
            "\n  FFmpeg not found!\n"
            "  Install it with Homebrew:\n"
            "    brew install ffmpeg\n"
        )
    try:
        subprocess.run(
            [FFMPEG_BIN, "-version"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        sys.exit(f"\n  FFmpeg exists but failed to run: {FFMPEG_BIN}\n")


def load_font(candidates: list, size: int) -> ImageFont.FreeTypeFont:
    """
    Try each path in `candidates` in order; return the first one that loads.
    Falls back to PIL's tiny built-in bitmap font only if nothing works.
    """
    for path in candidates:
        p = Path(path)
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except Exception:
                continue
    print(f"  Warning: no usable font found — text will look plain.")
    return ImageFont.load_default()


def arabic_display(text: str) -> str:
    """
    Arabic text needs two transformations before PIL can render it correctly:
      1. arabic_reshaper  — connects letters the way they appear in real Arabic
                            (letters change shape depending on neighbours)
      2. get_display      — applies the Unicode bidirectional algorithm so the
                            string flows right-to-left in a left-to-right engine
    """
    reshaped = arabic_reshaper.reshape(text)
    return get_display(reshaped)


def draw_arabic_text(draw: ImageDraw.ImageDraw, xy: tuple, text: str,
                     font: ImageFont.FreeTypeFont, fill: tuple,
                     anchor: str = "mm") -> None:
    """
    Draw Arabic correctly across environments.
    GitHub's Pillow build can use libraqm for native RTL shaping; local/macOS
    builds often cannot, so they still need the manual reshaper+bidi fallback.
    """
    if features.check("raqm"):
        draw.text(xy, text, font=font, fill=fill, anchor=anchor,
                  direction="rtl", language="ar")
    else:
        draw.text(xy, arabic_display(text),
                  font=font, fill=fill, anchor=anchor)


# ══════════════════════════════════════════════════════════════════════════════
# ❻  AUTOMATION HELPERS  (Google Sheets → word batch → YouTube metadata)
# ══════════════════════════════════════════════════════════════════════════════

def fetch_sheet_words(csv_url: str) -> list:
    """
    Download a Google Sheet published as CSV and return all word pairs.
    The sheet must have two columns with headers: arabic, english
    Optional columns: level, pronunciation
    Publish via: File → Share → Publish to web → select sheet → CSV → Publish
    """
    try:
        with urllib.request.urlopen(csv_url, timeout=15) as resp:
            text = resp.read().decode("utf-8-sig")
    except Exception as exc:
        sys.exit(f"\n  Failed to fetch Google Sheet:\n  {exc}\n"
                 "  Check that SHEET_CSV_URL is correct and the sheet is published publicly.\n")

    reader = csv.DictReader(text.splitlines())
    headers = reader.fieldnames or []
    header_lookup = {header.strip().lower(): header for header in headers if header}

    arabic_col = header_lookup.get("arabic")
    english_col = header_lookup.get("english")
    level_col = header_lookup.get("level")
    pronunciation_col = header_lookup.get("pronunciation")

    if not arabic_col or not english_col:
        seen = ", ".join(headers) if headers else "(none)"
        sys.exit(
            "\n  Sheet is missing required columns.\n"
            "  Required headers: arabic, english\n"
            "  Optional header: level\n"
            f"  Headers found: {seen}\n"
        )

    pairs  = []
    for row in reader:
        ar = row.get(arabic_col, "").strip()
        en = row.get(english_col, "").strip()
        level = row.get(level_col, "").strip() if level_col else ""
        pronunciation = row.get(pronunciation_col, "").strip() if pronunciation_col else ""
        if ar and en:
            pairs.append((ar, en, level, pronunciation))

    if not pairs:
        sys.exit(
            "\n  Sheet has no valid rows.\n"
            "  Make sure at least one row has both arabic and english filled in.\n"
        )

    print(f"  Sheet loaded: {len(pairs)} word pairs total")
    return pairs


def load_next_batch(all_pairs: list, words_per_reel: int = WORDS_PER_REEL,
                    include_pronunciation: bool = False,
                    state_file: Path = ENGLISH_STATE_FILE) -> tuple:
    """
    Read the state file to find the current position and return the next batch.
    State is written only after a successful upload, so previews/dry runs do not
    consume words.
    """
    state = json.loads(state_file.read_text()) if state_file.exists() else {"next_index": 0}
    idx   = state["next_index"] % len(all_pairs)

    batch    = (all_pairs * 2)[idx : idx + words_per_reel]
    next_idx = (idx + words_per_reel) % len(all_pairs)

    print(f"  Batch: words {idx + 1}–{idx + len(batch)} of {len(all_pairs)} "
          f"(next run starts at {next_idx + 1})")

    level      = batch[0][2] if batch and batch[0][2] else "متوسط"
    if include_pronunciation:
        word_pairs = [
            (row[0], row[1], row[3])
            for row in batch
        ]
    else:
        word_pairs = [(row[0], row[1]) for row in batch]
    return word_pairs, level, next_idx


def save_next_index(state_file: Path, next_idx: int) -> None:
    """Persist the next sheet row index after a successful upload."""
    state_file.write_text(json.dumps({"next_index": next_idx}, indent=2) + "\n")
    print(f"  State saved → {state_file}")


def build_metadata(word_pairs: list) -> tuple:
    import random

    title_variations = [
        "5 كلمات إنجليزي هتسمعهم كل يوم 🔥 #Shorts",
        "لو عايز الإنجليزي بتاعك يتحسن.. احفظ دول 👌 #Shorts",
        "5 كلمات إنجليزي مهمين جدًا للمحادثة 💬 #Shorts",
        "اختبر نفسك في الإنجليزي 🧠 #Shorts",
        "5 كلمات إنجليزي لازم تبقى عارفهم ✅ #Shorts",
        "كلمات هتخليك تفهم الإنجليزي أسرع 🚀 #Shorts",
        "5 كلمات هتفرق معاك في الإنجليزي 🔥 #Shorts",
        "بتتعلم إنجليزي؟ متفوتش الكلمات دي 📌 #Shorts",
        "كلمات إنجليزي مهمة للحياة اليومية 🗣️ #Shorts",
        "تعلم 5 كلمات في أقل من دقيقة ⚡ #Shorts",
        "مستواك إيه في الإنجليزي؟ جرب الكلمات دي 👀 #Shorts",
        "5 كلمات جديدة ضيفهم لقاموسك 📚 #Shorts",
        "خد جرعة إنجليزي سريعة 🎯 #Shorts",
        "5 كلمات هتسمعهم في الشغل والدراسة 💼 #Shorts",
        "لو نسيت الكلمات دي هتتوه في المحادثة 😅 #Shorts",
        "احفظ كلمة جديدة كل يوم.. ابدأ بدول 💡 #Shorts",
        "كلمات بسيطة بس مهمة جدًا 🔥 #Shorts",
        "عايز تتكلم إنجليزي بطلاقة؟ ابدأ بالكلمات دي 🚀 #Shorts",
        "خمس كلمات هيستخدمهم أي Native Speaker 🇺🇸 #Shorts",
        "تحدي سريع: تعرف معنى الكلمات دي؟ 🤔 #Shorts",
        "احفظهم النهارده واشكرني بعدين 😎 #Shorts",
    ]
    title = random.choice(title_variations)

    word_list = "\n".join(f"• {en} — {ar}" for ar, en in word_pairs)

    desc = f"""تعلم 5 كلمات انجليزي مع الترجمة العربية!

{word_list}

📌 تابعنا لتتعلم 5 كلمات انجليزي جديدة كل يوم!
Follow us for 5 new English words every day!

#كلمات_انجليزي #تعلم_الانجليزي #كلمات_انجليزية #تعلم_اللغة_الانجليزية #انجليزي_للعرب #مفردات_انجليزية #كلمة_اليوم #تعليم_الانجليزي #انجليزي_بالعربي #LearnEnglish #EnglishVocabulary #EnglishForArabics #ArabicSpeakers #DailyEnglish #LanguageLearning #Shorts #YouTubeShorts #English #Arabic #EnglishWords"""

    tags = [
        # Arabic tags — primary audience
        "كلمات انجليزي",
        "تعلم الانجليزي",
        "كلمات انجليزية",
        "تعلم اللغة الانجليزية",
        "انجليزي للعرب",
        "مفردات انجليزية",
        "تعليم الانجليزي",
        "انجليزي بالعربي",
        "كلمة اليوم",
        "تعلم انجليزي",
        "انجليزي مبتدئين",
        "تحسين الانجليزي",
        # English tags
        "learn english",
        "english vocabulary",
        "english words",
        "daily english",
        "english for arabic speakers",
        "english lesson",
        "learn english fast",
        "improve english",
        "arabic to english",
        "english arabic",
        "language learning",
        "vocabulary",
        # Shorts
        "shorts",
        "youtube shorts",
    ]

    return title, desc, tags


def build_arabic_words_metadata(word_pairs: list) -> tuple:
    import random

    title_variations = [
        "7 everyday Egyptian Arabic words 🇪🇬 #Shorts",
        "Egyptian Arabic for beginners: 7 words #Shorts",
        "Learn 7 common Egyptian Arabic words #Shorts",
        "7 useful Egyptian Arabic words #Shorts",
        "Egyptian Arabic for beginners 🇪🇬 #Shorts",
        "Common Egyptian Arabic vocabulary #Shorts",
        "7 words in Egyptian Arabic #Shorts",
        "Simple Egyptian Arabic vocabulary #Shorts",
        "Egyptian Arabic words with pronunciation #Shorts",
        "Beginner Egyptian Arabic: 7 words #Shorts",
    ]
    title = random.choice(title_variations)

    def format_row(row):
        arabic, english = row[0], row[1]
        pronunciation = row[2] if len(row) > 2 and row[2] else ""
        if pronunciation:
            return f"• {arabic} ({pronunciation}) — {english}"
        return f"• {arabic} — {english}"

    word_list = "\n".join(format_row(row) for row in word_pairs)

    desc = f"""Learn 7 everyday Egyptian Arabic words with English meanings.

{word_list}

Simple Egyptian Arabic vocabulary with pronunciation for beginners.

#EgyptianArabic #LearnArabic #ArabicForBeginners #ArabicVocabulary #EgyptianDialect #SpeakArabic #ArabicLesson #LearnEgyptianArabic #Shorts #YouTubeShorts"""

    tags = [
        "egyptian arabic",
        "learn arabic",
        "arabic words",
        "arabic vocabulary",
        "arabic for beginners",
        "egyptian dialect",
        "learn egyptian arabic",
        "speak arabic",
        "arabic lesson",
        "arabic pronunciation",
        "egyptian arabic for beginners",
        "egyptian arabic words",
        "daily arabic",
        "arabic shorts",
        "language learning",
        "shorts",
        "youtube shorts",
    ]
    return title, desc, tags


# ══════════════════════════════════════════════════════════════════════════════
# ❼  IMAGE GENERATION
# ══════════════════════════════════════════════════════════════════════════════

# Layout constants — pixel-accurate from background.png (1080×1920)
_EN_CENTER_X   = 300    # centre of English left half (0 to divider ~373)
_AR_CENTER_X   = 800    # centre of Arabic right half (373 to 1050)
_CARD_Y = [800, 1010, 1210, 1420, 1630]
_PILL_X1       = 290    # pill left edge
_PILL_Y1       = 600    # pill top edge
_PILL_X2       = 644    # pill right edge
_PILL_Y2       = 652    # pill bottom edge

BACKGROUND_IMG = Path("assets") / "background.png"
ARABIC_WORDS_BACKGROUND_IMG = Path("assets") / "image.png"


def create_image(word_pairs: list, level: str, output_path: Path) -> Path:
    """
    Loads the designer background, then overlays word pairs and the level pill.
      English word (left half) + Arabic word (right half) in each card slot.
      Level text in the oval pill shape in the header.
    """
    print("  Creating image…")

    if not BACKGROUND_IMG.exists():
        sys.exit(f"\n  Background image not found: {BACKGROUND_IMG}\n"
                 "  Place your background PNG at assets/background.png\n")

    # ── Load and scale background to target size ────────────────────────────
    bg  = Image.open(str(BACKGROUND_IMG)).resize((IMG_W, IMG_H), Image.LANCZOS)
    img = bg.convert("RGBA")
    draw = ImageDraw.Draw(img)

    # ── Colours (match the design palette) ─────────────────────────────────
    NAVY = (13,  27,  75)    # dark navy — used in the design for main text
    GOLD = (160, 122,  40)   # antique gold — matches the design accents

    # ── Fonts ───────────────────────────────────────────────────────────────
    english_font = load_font(BOLD_FONT_CANDIDATES,    62)
    arabic_font  = load_font(ARABIC_FONT_CANDIDATES,  58)
    level_font   = load_font(ARABIC_FONT_CANDIDATES, 32)

    # ── Level pill ──────────────────────────────────────────────────────────
    pill_cx = (_PILL_X1 + _PILL_X2) // 2
    pill_cy = (_PILL_Y1 + _PILL_Y2) // 2
    draw_arabic_text(draw, (pill_cx, pill_cy), level,
                     font=level_font, fill=GOLD)

    # ── Word rows ──────────────────────────────────────────────────────────
    for i, (ar, en) in enumerate(word_pairs):
        if i >= len(_CARD_Y):
            break                          # safety guard for > 5 words
        mid_y = _CARD_Y[i]

        # English word — centred in the left card half
        draw.text((_EN_CENTER_X, mid_y), en,
                  font=english_font, fill=NAVY, anchor="mm")

        # Arabic word — centred in the right card half
        draw_arabic_text(draw, (_AR_CENTER_X, mid_y), ar,
                         font=arabic_font, fill=NAVY)

    # ── Save ───────────────────────────────────────────────────────────────
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rgb = img.convert("RGB")
    rgb.save(str(output_path))
    print(f"  Saved  → {output_path}")

    return output_path


def create_arabic_words_image(word_pairs: list, level: str, output_path: Path) -> Path:
    """
    Render the newer "learn 7 Arabic words" card.
    Uses a separate background so the existing 5-English-words design is untouched.
    """
    print("  Creating Arabic words image…")

    if not ARABIC_WORDS_BACKGROUND_IMG.exists():
        sys.exit(
            f"\n  Arabic words background image not found: {ARABIC_WORDS_BACKGROUND_IMG}\n"
            "  Place the Arabic words background PNG at assets/image.png\n"
        )

    bg = Image.open(str(ARABIC_WORDS_BACKGROUND_IMG)).resize((IMG_W, IMG_H), Image.LANCZOS)
    img = bg.convert("RGBA")
    draw = ImageDraw.Draw(img)

    NAVY = (13, 27, 75)
    RUST = (144, 63, 22)
    english_font = load_font(BOLD_FONT_CANDIDATES, 30)
    arabic_font = load_font(ARABIC_FONT_CANDIDATES, 34)
    pronunciation_font = load_font(BOLD_FONT_CANDIDATES, 30)

    # assets/image.png has a three-column table. It visually contains 6 row
    # bands, so 7 words are packed evenly within the full table body.
    row_y = [870 + (i * 130) for i in range(ARABIC_WORDS_PER_REEL)]
    english_x = 200
    arabic_x = 535
    pronunciation_x = 865

    for i, row in enumerate(word_pairs[:ARABIC_WORDS_PER_REEL]):
        y = row_y[i]
        ar, en = row[0], row[1]
        pronunciation = row[2] if len(row) > 2 else ""

        draw.text((english_x, y), en, font=english_font, fill=NAVY, anchor="mm")
        draw_arabic_text(draw, (arabic_x, y), ar, font=arabic_font, fill=NAVY)
        draw.text((pronunciation_x, y), pronunciation,
                  font=pronunciation_font, fill=RUST, anchor="mm")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    rgb = img.convert("RGB")
    rgb.save(str(output_path))
    print(f"  Saved  → {output_path}")
    return output_path


# ══════════════════════════════════════════════════════════════════════════════
# ❼  AUDIO GENERATION
# ══════════════════════════════════════════════════════════════════════════════

SAMPLE_ARABIC_WORDS = [
    # (English meaning, Egyptian Arabic, pronunciation guide) for local previews
    ("Water", "مَيَّه", "Mayya"),
    ("Bread", "عيش", "Eish"),
    ("House", "بيت", "Beit"),
    ("Door", "باب", "Bab"),
    ("Window", "شباك", "Shebbak"),
    ("Street", "شارع", "Share'"),
    ("Car", "عربية", "Arabeyya"),
]


def gemini_tts_enabled() -> bool:
    return bool(GEMINI_API_KEY)


def write_wave_file(filename: Path, pcm: bytes,
                    channels: int = 1, rate: int = 24000,
                    sample_width: int = 2) -> None:
    """Save Gemini PCM audio as a WAV file."""
    import wave

    filename.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(filename), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(pcm)


def synthesize_gemini_prompt(prompt: str, output_path: Path) -> Path:
    """Synthesize speech with Gemini TTS from a complete prompt."""
    if not gemini_tts_enabled():
        sys.exit(
            "\n  Gemini TTS is not configured.\n"
            "  Set GEMINI_API_KEY, then try again.\n"
        )

    genai = _require("google.genai", "google-genai")
    types = _require("google.genai.types", "google-genai")

    client = genai.Client(api_key=GEMINI_API_KEY)
    last_exc = None
    for attempt in range(GEMINI_TTS_MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=GEMINI_TTS_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=GEMINI_TTS_VOICE,
                            )
                        )
                    )
                ),
            )
            break
        except Exception as exc:
            last_exc = exc
            is_rate_limited = "429" in str(exc) or "quota" in str(exc).lower()
            if not is_rate_limited or attempt >= GEMINI_TTS_MAX_RETRIES:
                raise

            print(
                f"      Gemini quota/rate limit hit; waiting "
                f"{GEMINI_TTS_RETRY_DELAY_SECONDS}s before retry "
                f"{attempt + 1}/{GEMINI_TTS_MAX_RETRIES}..."
            )
            time.sleep(GEMINI_TTS_RETRY_DELAY_SECONDS)
    else:
        raise last_exc

    try:
        data = response.candidates[0].content.parts[0].inline_data.data
    except Exception as exc:
        raise RuntimeError(f"Gemini TTS returned no audio: {response}") from exc

    write_wave_file(output_path, data)
    return output_path


def build_gemini_sequence_prompt(word_pairs: list) -> str:
    """Build one prompt that asks Gemini to read all vocabulary pairs in order."""
    lines = []
    for i, row in enumerate(word_pairs, start=1):
        arabic, english = row[0], row[1]
        pronunciation = row[2] if len(row) > 2 and row[2] else ""
        if pronunciation:
            lines.append(f"{i}. {english} - {arabic} ({pronunciation}) - {arabic} ({pronunciation})")
        else:
            lines.append(f"{i}. {english} - {arabic} - {arabic}")
    return GEMINI_REEL_PROMPT_PREFIX + "\n".join(lines)


def synthesize_gemini_sequence(word_pairs: list, output_path: Path) -> Path:
    """Synthesize the full reel voiceover in a single Gemini request."""
    return synthesize_gemini_prompt(build_gemini_sequence_prompt(word_pairs), output_path)


def create_arabic_vocab_audio(word_pairs: list, output_path: Path) -> Path:
    """
    Build the newer "learn Arabic words" voiceover in one Gemini request.
    word_pairs are still shaped as (Arabic, English), matching the sheet flow.
    """
    if not gemini_tts_enabled():
        sys.exit(
            "\n  Gemini TTS is required for ARABIC_WORDS_REEL=true.\n"
            "  Set GEMINI_API_KEY, then try again.\n"
        )

    print("  Generating audio… Arabic words reel TTS: Gemini")
    with tempfile.TemporaryDirectory() as tmp:
        sequence_path = Path(tmp) / "gemini_sequence.wav"
        try:
            synthesize_gemini_sequence(word_pairs, sequence_path)
        except Exception as exc:
            sys.exit(f"\n  Gemini TTS failed for Arabic words sequence: {exc}\n"
                     "  Check your Gemini quota/key and try again.\n")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        combined = AudioSegment.from_file(sequence_path)
        combined.export(str(output_path), format="mp3")

    duration_s = len(combined) / 1000
    print(f"  Saved  → {output_path}  ({duration_s:.1f} s)")
    return output_path


def create_english_vocab_audio(word_pairs: list, output_path: Path) -> Path:
    """
    Build the original "learn 5 English words" MP3 voiceover with gTTS:
      Arabic (slow) → 0.6 s pause → English → 1.2 s pause → next pair.

    Each TTS call makes an HTTP request, so:
      • You need an internet connection.
      • A small sleep between calls avoids hitting provider rate limits.
    """
    print("  Generating audio… English vocab reel TTS: gTTS")

    silence_short = AudioSegment.silent(duration=PAUSE_AFTER_ARABIC)
    silence_long  = AudioSegment.silent(duration=PAUSE_AFTER_ENGLISH)
    combined      = AudioSegment.empty()

    with tempfile.TemporaryDirectory() as tmp:
        for i, (ar, en) in enumerate(word_pairs):
            print(f"    [{i + 1}/{len(word_pairs)}]  {en}  /  {ar}")

            # ── Arabic clip ────────────────────────────────────────────────
            ar_path = os.path.join(tmp, f"ar_{i}.mp3")
            try:
                gTTS(text=ar, lang="ar", slow=True).save(ar_path)
            except Exception as exc:
                sys.exit(f"\n  Arabic TTS failed for word '{ar}': {exc}\n"
                         "  Check your internet connection and try again.\n")
            ar_seg = AudioSegment.from_mp3(ar_path)
            time.sleep(0.35)   # brief pause to avoid Google rate-limit

            # ── English clip ───────────────────────────────────────────────
            en_path = os.path.join(tmp, f"en_{i}.mp3")
            try:
                gTTS(text=en, lang="en").save(en_path)
            except Exception as exc:
                sys.exit(f"\n  gTTS failed for English word '{en}': {exc}\n"
                         "  Check your internet connection and try again.\n")
            en_seg = AudioSegment.from_mp3(en_path)
            time.sleep(0.35)

            # Arabic → short pause → English → long pause
            combined += ar_seg + silence_short + en_seg + silence_long

    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.export(str(output_path), format="mp3")
    duration_s = len(combined) / 1000
    print(f"  Saved  → {output_path}  ({duration_s:.1f} s)")
    return output_path


# ══════════════════════════════════════════════════════════════════════════════
# ❽  VIDEO GENERATION (FFmpeg)
# ══════════════════════════════════════════════════════════════════════════════

def create_video(image_path: Path, audio_path: Path, output_path: Path) -> Path:
    """
    Combine the static PNG and the MP3 into an MP4 using FFmpeg.
    Duration is read directly from the audio file so the video ends exactly
    when the audio ends (-shortest has a known bug with -loop 1).
    """
    print("  Combining image + audio with FFmpeg…")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Measure exact audio length so we can pass -t explicitly to FFmpeg.
    # -shortest alone is unreliable with -loop 1 and can add ~70s of silence.
    duration_s = len(AudioSegment.from_mp3(str(audio_path))) / 1000.0
    print(f"  Audio duration: {duration_s:.2f}s — video will match exactly")

    cmd = [
        FFMPEG_BIN, "-y",
        "-loop", "1",
        "-framerate", "1",
        "-i", str(image_path),
        "-i", str(audio_path),
        "-c:v", "libx264",
        "-tune", "stillimage",
        "-c:a", "aac",
        "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-t", str(duration_s),   # explicit duration — no more silent tail
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("\n  FFmpeg stderr output:\n")
        print(result.stderr)
        sys.exit("\n  FFmpeg failed — see the error above.\n")

    print(f"  Saved  → {output_path}")

    return output_path


# ══════════════════════════════════════════════════════════════════════════════
# ❾  YOUTUBE AUTHENTICATION
# ══════════════════════════════════════════════════════════════════════════════

YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def authenticate_youtube():
    """
    OAuth2 authentication flow:

    First run:
      • Reads client_secrets.json (from Google Cloud Console)
      • Opens your default browser to a Google consent page
      • You click "Allow" — a token.json is saved for future runs

    Later runs:
      • Loads token.json automatically; refreshes it silently if expired
    """
    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), YOUTUBE_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("  Refreshing YouTube token…")
            creds.refresh(Request())
        else:
            # First-time login
            if not SECRETS_FILE.exists():
                sys.exit(
                    f"\n  '{SECRETS_FILE}' not found!\n"
                    "  Download it from Google Cloud Console:\n"
                    "    Console → APIs & Services → Credentials → your OAuth client → Download JSON\n"
                    "  Rename the file to 'client_secrets.json' and place it in this folder.\n"
                    "  See README.md for the full walkthrough.\n"
                )
            print("  Opening browser for YouTube authorisation…")
            print("  (A browser tab will open — click 'Allow' to continue.)\n")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(SECRETS_FILE), YOUTUBE_SCOPES
            )
            creds = flow.run_local_server(port=8080)

        TOKEN_FILE.write_text(creds.to_json())
        print(f"  Token saved → {TOKEN_FILE}")

    return build("youtube", "v3", credentials=creds)


# ══════════════════════════════════════════════════════════════════════════════
# ❿  YOUTUBE UPLOAD
# ══════════════════════════════════════════════════════════════════════════════

def upload_to_youtube(video_path: Path, youtube,
                      title: str, description: str, tags: list) -> str:
    """
    Upload the MP4 using a resumable upload (handles large files and
    automatically retries partial uploads if your connection drops).
    Returns the YouTube video URL.
    """
    print("  Uploading to YouTube…")

    body = {
        "snippet": {
            "title":       title,
            "description": description,
            "tags":        tags,
            "categoryId":  "27",   # 27 = Education (see YouTube API docs for other IDs)
        },
        "status": {
            "privacyStatus":           PRIVACY_STATUS,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=5 * 1024 * 1024,   # upload in 5 MB chunks
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            print(f"  Uploading… {pct}%", end="\r", flush=True)

    video_id  = response["id"]
    video_url = f"https://www.youtube.com/shorts/{video_id}"
    print(f"\n  Uploaded! → {video_url}")
    return video_url


# ══════════════════════════════════════════════════════════════════════════════
# ⓫  MAIN  ── orchestrates the full pipeline
# ══════════════════════════════════════════════════════════════════════════════

def run_reel(arabic_words_reel: bool, youtube=None) -> Path:
    """Generate one reel type and optionally upload it."""
    reel_name = "Arabic words" if arabic_words_reel else "English vocab"
    output_stem = "arabic_words" if arabic_words_reel else "english_vocab"

    print("\n" + "─" * 56)
    print(f"  {reel_name} reel")
    print("─" * 56 + "\n")

    words_per_reel = ARABIC_WORDS_PER_REEL if arabic_words_reel else WORDS_PER_REEL
    sheet_csv_url = ARABIC_SHEET_CSV_URL if arabic_words_reel else SHEET_CSV_URL
    state_file = ARABIC_STATE_FILE if arabic_words_reel else ENGLISH_STATE_FILE
    next_idx = None

    if sheet_csv_url:
        print("  Source: Google Sheet")
        all_pairs = fetch_sheet_words(sheet_csv_url)
        word_pairs, level, next_idx = load_next_batch(
            all_pairs,
            words_per_reel,
            include_pronunciation=arabic_words_reel,
            state_file=state_file,
        )
    else:
        print("  Source: hardcoded sample words")
        if arabic_words_reel:
            word_pairs = [
                (arabic, english, pronunciation)
                for english, arabic, pronunciation
                in SAMPLE_ARABIC_WORDS[:words_per_reel]
            ]
        else:
            word_pairs = WORD_PAIRS[:words_per_reel]
        level = "متوسط"

    if not word_pairs:
        sys.exit("  Error: no word pairs to process.\n")

    if arabic_words_reel:
        yt_title, yt_desc, yt_tags = build_arabic_words_metadata(word_pairs)
    else:
        yt_title, yt_desc, yt_tags = build_metadata(word_pairs)
    print()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    image_path = OUTPUT_DIR / f"{output_stem}_image.png"
    audio_path = OUTPUT_DIR / f"{output_stem}_audio.mp3"
    video_path = OUTPUT_DIR / f"{output_stem}_reel.mp4"

    print("Step 1/4 — Rendering image")
    if arabic_words_reel:
        create_arabic_words_image(word_pairs, level, image_path)
    else:
        create_image(word_pairs, level, image_path)
    print()

    if PREVIEW_ONLY:
        print("  PREVIEW_ONLY=true — skipping audio, video, and upload.")
        print(f"  Image saved → {image_path}")
        return image_path

    check_ffmpeg()

    print("Step 2/4 — Generating voiceover")
    if arabic_words_reel:
        create_arabic_vocab_audio(word_pairs, audio_path)
    else:
        create_english_vocab_audio(word_pairs, audio_path)
    print()

    print("Step 3/4 — Building MP4")
    create_video(image_path, audio_path, video_path)
    print()

    print(f"  Video ready: {video_path}\n")

    if UPLOAD_TO_YOUTUBE:
        print("Step 4/4 — Uploading to YouTube")
        youtube = youtube or authenticate_youtube()
        url = upload_to_youtube(video_path, youtube, yt_title, yt_desc, yt_tags)
        if next_idx is not None:
            save_next_index(state_file, next_idx)
        print(f"\n  Done! Your Short is at:\n  {url}")
        print(f"  (Privacy: '{PRIVACY_STATUS}')\n")
    else:
        print("Step 4/4 — YouTube upload skipped (UPLOAD_TO_YOUTUBE not set)\n")

    return video_path


def main():
    print("\n" + "═" * 56)
    print("  VocabReelGenerator")
    print("═" * 56 + "\n")

    youtube = authenticate_youtube() if UPLOAD_TO_YOUTUBE else None

    if RUN_BOTH_REELS:
        run_reel(False, youtube=youtube)
        run_reel(True, youtube=youtube)
    else:
        run_reel(ARABIC_WORDS_REEL, youtube=youtube)

    print("═" * 56 + "\n")


if __name__ == "__main__":
    main()
