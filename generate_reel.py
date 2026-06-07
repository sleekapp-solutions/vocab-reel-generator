#!/usr/bin/env python3
"""
VocabReelGenerator — generate_reel.py

End-to-end pipeline:
  1. Render a 1080×1920 vocabulary card (Pillow)
  2. Generate Arabic + English voiceover (gTTS + pydub)
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
PRIVACY_STATUS = "private"

# In CI (GitHub Actions) this is overridden to "true" via env var.
# Locally it stays False so you never accidentally upload while designing.
UPLOAD_TO_YOUTUBE = os.getenv("UPLOAD_TO_YOUTUBE", "false").lower() == "true"

# Set to True to generate ONLY the image (skips audio, video, and upload).
PREVIEW_ONLY = os.getenv("PREVIEW_ONLY", "false").lower() == "true"


# ══════════════════════════════════════════════════════════════════════════════
# ❸  PATHS & TIMING  ── usually no need to change these
# ══════════════════════════════════════════════════════════════════════════════

OUTPUT_DIR   = Path("output")
PREVIEWS_DIR = Path("previews")   # timestamped images saved here for review
VIDEOS_DIR   = Path("videos")     # timestamped videos saved here for review
FONTS_DIR    = Path("assets") / "fonts"

SHEET_CSV_URL  = os.getenv("SHEET_CSV_URL", "")
STATE_FILE     = Path("state.json")
WORDS_PER_REEL = 5

ARABIC_FONT_CANDIDATES = [
    FONTS_DIR / "Amiri-Regular.ttf",
    Path("/System/Library/Fonts/GeezaPro.ttc"),                          # macOS — best Arabic
    Path("/System/Library/Fonts/SFArabic.ttf"),                          # macOS
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),        # macOS fallback
    Path("/Library/Fonts/Arial Unicode.ttf"),                            # macOS fallback
    Path("/usr/share/fonts/truetype/amiri/Amiri-Regular.ttf"),           # Ubuntu (CI)
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

from PIL import Image, ImageDraw, ImageFont
from gtts import gTTS
from pydub import AudioSegment
import arabic_reshaper
from bidi.algorithm import get_display

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
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        sys.exit(
            "\n  FFmpeg not found!\n"
            "  Install it with Homebrew:\n"
            "    brew install ffmpeg\n"
        )


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


# ══════════════════════════════════════════════════════════════════════════════
# ❻  AUTOMATION HELPERS  (Google Sheets → word batch → YouTube metadata)
# ══════════════════════════════════════════════════════════════════════════════

def fetch_sheet_words(csv_url: str) -> list:
    """
    Download a Google Sheet published as CSV and return all word pairs.
    The sheet must have two columns with headers: arabic, english
    Publish via: File → Share → Publish to web → select sheet → CSV → Publish
    """
    try:
        with urllib.request.urlopen(csv_url, timeout=15) as resp:
            text = resp.read().decode("utf-8")
    except Exception as exc:
        sys.exit(f"\n  Failed to fetch Google Sheet:\n  {exc}\n"
                 "  Check that SHEET_CSV_URL is correct and the sheet is published publicly.\n")

    reader = csv.DictReader(text.splitlines())
    pairs  = []
    for row in reader:
        ar = row.get("arabic", "").strip()
        en = row.get("english", "").strip()
        if ar and en:
            pairs.append((ar, en))

    if not pairs:
        sys.exit("  Sheet has no valid rows. Make sure columns are named 'arabic' and 'english'.\n")

    print(f"  Sheet loaded: {len(pairs)} word pairs total")
    return pairs


def load_next_batch(all_pairs: list) -> tuple:
    """
    Read state.json to find the current position, return the next WORDS_PER_REEL
    pairs and the level from the first row. Wraps around when the list ends.
    """
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {"next_index": 0}
    idx   = state["next_index"] % len(all_pairs)

    batch    = (all_pairs * 2)[idx : idx + WORDS_PER_REEL]
    next_idx = (idx + WORDS_PER_REEL) % len(all_pairs)

    STATE_FILE.write_text(json.dumps({"next_index": next_idx}, indent=2))
    print(f"  Batch: words {idx + 1}–{idx + len(batch)} of {len(all_pairs)} "
          f"(next run starts at {next_idx + 1})")

    level      = batch[0][2] if batch and batch[0][2] else "متوسط"
    word_pairs = [(ar, en) for ar, en, _ in batch]
    return word_pairs, level


def build_metadata(word_pairs: list) -> tuple:
    import random

    title_variations = [
        "5 كلمات انجليزي لازم تعرفها 🔥 #Shorts",
        "تعلم 5 كلمات انجليزي بالعربي 💡 #Shorts",
        "كلمات انجليزي يومية للعرب ✅ #Shorts",
        "5 كلمات انجليزي مع الترجمة العربية 📚 #Shorts",
        "طور انجليزيك في 30 ثانية 🚀 | كلمات انجليزي #Shorts",
        "كلمات انجليزي متقدمة للعرب 💪 #Shorts",
        "تعلم انجليزي بسرعة | 5 كلمات انجليزي جديدة 🎯 #Shorts",
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
    level_font   = load_font(ENGLISH_FONT_CANDIDATES, 28)

    # ── Level pill ──────────────────────────────────────────────────────────
    pill_cx = (_PILL_X1 + _PILL_X2) // 2  # = 467
    pill_cy = (_PILL_Y1 + _PILL_Y2) // 2  # = 626
    draw.text((pill_cx, pill_cy), level,
              font=level_font, fill=GOLD, anchor="mm")

    # ── Word rows ──────────────────────────────────────────────────────────
    for i, (ar, en) in enumerate(word_pairs):
        if i >= len(_CARD_Y):
            break                          # safety guard for > 5 words
        mid_y = _CARD_Y[i]

        # English word — centred in the left card half
        draw.text((_EN_CENTER_X, mid_y), en,
                  font=english_font, fill=NAVY, anchor="mm")

        # Arabic word — centred in the right card half (RTL-transformed)
        draw.text((_AR_CENTER_X, mid_y), arabic_display(ar),
                  font=arabic_font, fill=NAVY, anchor="mm")

    # ── Save ───────────────────────────────────────────────────────────────
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rgb = img.convert("RGB")
    rgb.save(str(output_path))
    print(f"  Saved  → {output_path}")

    PREVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    preview_path = PREVIEWS_DIR / f"preview_{ts}.png"
    rgb.save(str(preview_path))
    print(f"  Preview → {preview_path}")

    return output_path


# ══════════════════════════════════════════════════════════════════════════════
# ❼  AUDIO GENERATION
# ══════════════════════════════════════════════════════════════════════════════

def create_audio(word_pairs: list, output_path: Path) -> Path:
    """
    Build an MP3 voiceover by concatenating gTTS clips:
      Arabic (slow) → 0.6 s pause → English → 1.2 s pause → (next pair) …

    Each gTTS call makes an HTTP request to Google's servers, so:
      • You need an internet connection.
      • A small sleep between calls avoids hitting Google's rate limit.
    """
    print("  Generating audio…")

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
                sys.exit(f"\n  gTTS failed for Arabic word '{ar}': {exc}\n"
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
        "ffmpeg", "-y",
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

    # Save a timestamped copy to videos/ for review
    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    review_path = VIDEOS_DIR / f"reel_{ts}.mp4"
    shutil.copy2(str(output_path), str(review_path))
    print(f"  Review  → {review_path}")

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
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"\n  Uploaded! → {video_url}")
    return video_url


# ══════════════════════════════════════════════════════════════════════════════
# ⓫  MAIN  ── orchestrates the full pipeline
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("\n" + "═" * 56)
    print("  VocabReelGenerator")
    print("═" * 56 + "\n")

    # ── Resolve word pairs ─────────────────────────────────────────────────
    # Automated run (GitHub Actions): fetch from Google Sheet + advance state
    # Local run: use WORD_PAIRS hardcoded above
    if SHEET_CSV_URL:
        print("  Source: Google Sheet")
        all_pairs          = fetch_sheet_words(SHEET_CSV_URL)
        word_pairs, level  = load_next_batch(all_pairs)
    else:
        print("  Source: hardcoded WORD_PAIRS")
        word_pairs = WORD_PAIRS
        level      = "متوسط"

    if not word_pairs:
        sys.exit("  Error: no word pairs to process.\n")

    yt_title, yt_desc, yt_tags = build_metadata(word_pairs)
    print()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    image_path = OUTPUT_DIR / "vocab_image.png"
    audio_path = OUTPUT_DIR / "vocab_audio.mp3"
    video_path = OUTPUT_DIR / "vocab_reel.mp4"

    # ── Step 1: Image ──────────────────────────────────────────────────────
    print("Step 1/4 — Rendering image")
    create_image(word_pairs, level, image_path)
    print()

    # ── Preview-only mode: stop here ───────────────────────────────────────
    if PREVIEW_ONLY:
        print("  PREVIEW_ONLY=true — skipping audio, video, and upload.")
        print("  Image saved in previews/  ← open that folder to review.")
        print("\n" + "═" * 56 + "\n")
        return

    # ── Pre-flight check for FFmpeg ────────────────────────────────────────
    check_ffmpeg()

    # ── Step 2: Audio ──────────────────────────────────────────────────────
    print("Step 2/4 — Generating voiceover")
    create_audio(word_pairs, audio_path)
    print()

    # ── Step 3: Video ──────────────────────────────────────────────────────
    print("Step 3/4 — Building MP4")
    create_video(image_path, audio_path, video_path)
    print()

    print(f"  Video ready: {video_path}\n")

    # ── Step 4: Upload ─────────────────────────────────────────────────────
    if UPLOAD_TO_YOUTUBE:
        print("Step 4/4 — Uploading to YouTube")
        youtube = authenticate_youtube()
        url = upload_to_youtube(video_path, youtube, yt_title, yt_desc, yt_tags)
        print(f"\n  Done! Your Short is at:\n  {url}")
        print(f"  (Privacy: '{PRIVACY_STATUS}')\n")
    else:
        print("Step 4/4 — YouTube upload skipped (UPLOAD_TO_YOUTUBE not set)\n")

    print("═" * 56 + "\n")


if __name__ == "__main__":
    main()
