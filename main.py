# -*- coding: utf-8 -*-
"""
Telegram Multi-Engine Media Downloader Bot - V12

Install:
    pip install -U python-telegram-bot "yt-dlp[default]" yt-dlp-ejs pytubefix instaloader

System dependency:
    FFmpeg must be installed and available in PATH.

Setup:
    1) Set BOT_TOKEN below in the CONFIGURATION section.
    2) Install: pip install -U python-telegram-bot "yt-dlp[default]" yt-dlp-ejs pytubefix instaloader
    3) Run: python bot.py

Supports public media that the user owns or is authorized to download.
No login, DRM, paywall, private-account, or access-control bypass.
Engine selection/fallback is automatic and hidden from users.
"""

import asyncio
import logging
import os
import re
import subprocess
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes,
    MessageHandler, filters,
)

# =============== CONFIGURATION ===============

# Paste your test bot token between the quotes below.
# Keep this file private and never publish it with a real token.
BOT_TOKEN = "9258183648:AAF7LF5kG7gIjb0BbuECkf-sK1LaqjvjbRY"
ADMIN_ID = 8150202704
DEVELOPER_USERNAME = "nhnhhnhn"

DATABASE_FILE = "downloader_bot_v2.sqlite3"
TEMP_ROOT = Path(tempfile.gettempdir()) / "telegram_media_downloader_v2"

MAX_UPLOAD_MB = 49
MAX_CONCURRENT_DOWNLOADS = 1
MAX_PARALLEL_BROADCAST = 5
INSPECT_TIMEOUT = 45
DOWNLOAD_TIMEOUT = 240
MAX_URL_LENGTH = 2048

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("media-downloader-v12")
_INSTANCE_LOCK_HANDLE = None
TEMP_ROOT.mkdir(parents=True, exist_ok=True)
download_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
broadcast_semaphore = asyncio.Semaphore(MAX_PARALLEL_BROADCAST)

DEFAULT_TEXTS = {
    "welcome": "أهلاً بك في بوت تنزيل الوسائط\n\nأرسل رابطاً عاماً من أحد المواقع المدعومة، وسأفحصه تلقائياً ثم أعرض لك خيار الصوت أو الفيديو.",
    "error": "ما قدرت أجهّز هذا الرابط حالياً. تأكد أن المحتوى عام والرابط صحيح، ثم حاول مرة ثانية.",
    "developer": "تواصل مع المطور", "busy": "طلبات التنزيل مشغولة حالياً. حاول بعد قليل.",
    "working": "جارٍ تجهيز الملف... سأختار طريقة المعالجة تلقائياً.",
    "invalid_url": "أرسل رابطاً صحيحاً يبدأ بـ http أو https.", "checking": "جارٍ فحص الرابط...",
    "recognized": "تم التعرف على المحتوى", "duration": "المدة: {seconds} ثانية",
    "choose_type": "اختار نوع الملف:", "audio_button": "ملف صوتي", "video_button": "ملف فيديو",
    "cancel_button": "إلغاء", "cancelled": "تم إلغاء العملية.",
    "inspect_timeout": "انتهت مهلة فحص الرابط. حاول مرة ثانية.",
    "link_expired": "انتهت صلاحية الرابط. أرسل الرابط من جديد.",
    "success_caption": "تم تجهيز الملف\n{title}\nالحجم: {size}",
    "send_another": "تقدر ترسل رابطاً آخر متى ما تريد.",
    "download_timeout": "انتهت مهلة تجهيز الملف. حاول مرة ثانية لاحقاً.",
    "download_failed": "تعذر تجهيز الملف. قد يكون الرابط غير مدعوم أو المحتوى غير عام، أو الملف أكبر من {max_mb}MB، أو توجد مشكلة مؤقتة.",
    "youtube_blocked": "يوتيوب رفض طلب التنزيل من خادم الاستضافة حالياً. جرّب لاحقاً أو استخدم طريقة التنزيل الرسمية المتاحة للمحتوى الذي تملك حق الوصول إليه.",
    "tiktok_unavailable": "تيك توك لم يُرجع صفحة يمكن لمحرّك التنزيل قراءتها حالياً. قد تكون المشكلة مؤقتة أو من استجابة تيك توك لخادم الاستضافة. جرّب لاحقاً؛ بقية المنصات غير متأثرة.",
    "admin_title": "لوحة تحكم الإدارة\nاختر العملية المطلوبة:",
    "admin_stats_button": "الإحصائيات", "admin_users_button": "المستخدمون",
    "admin_downloads_button": "آخر التنزيلات", "admin_broadcast_button": "بث للجميع",
    "admin_single_button": "رسالة لمستخدم", "admin_edit_button": "تعديل النصوص والأزرار",
    "admin_refresh_button": "تحديث اللوحة", "admin_back_button": "رجوع للوحة الأدمن",
    "admin_back_short": "رجوع", "admin_only": "هذه اللوحة للأدمن فقط.",
    "stats_title": "إحصائيات البوت", "stats_users": "المستخدمون: {users}",
    "stats_downloads": "التنزيلات: {total}", "stats_success": "الناجحة: {success}",
    "stats_failed": "الفاشلة/المتوقفة: {failed}", "stats_day": "آخر 24 ساعة: {today}",
    "stats_audio": "صوتيات: {audio}", "stats_video": "فيديوهات: {video}",
    "users_page": "المستخدمون — صفحة {page}", "no_username": "بدون يوزر",
    "generic_user": "مستخدم", "users_empty": "لا يوجد مستخدمون بعد.",
    "previous_button": "السابق", "next_button": "التالي", "downloads_title": "آخر 15 عملية تنزيل",
    "no_title": "بدون عنوان", "kind_audio": "صوت", "kind_video": "فيديو",
    "broadcast_prompt": "أرسل نص الرسالة التي تريد بثها لجميع المستخدمين.\nللإلغاء /cancel",
    "single_id_prompt": "أرسل آيدي المستخدم.\nللإلغاء /cancel",
    "edit_menu_prompt": "اختر النص أو اسم الزر الذي تريد تعديله:",
    "edit_welcome_button": "تعديل رسالة الترحيب", "edit_developer_button": "تعديل اسم زر المطور",
    "edit_error_button": "تعديل رسالة الخطأ", "edit_misc_button": "تعديل بقية النصوص والأزرار",
    "edit_prompt": "أرسل النص الجديد.\n\nالنص الحالي:\n{current}\n\nللإلغاء /cancel",
    "invalid_option": "خيار غير صالح.", "invalid_text": "أرسل نصاً صالحاً.",
    "unknown_size": "غير معروف", "unit_b": "B", "unit_kb": "KB", "unit_mb": "MB", "unit_gb": "GB",
    "id_label": "ID", "engine_unknown": "-", "media_title": "media",
    "broadcast_started": "بدأ البث إلى {count} مستخدم...",
    "broadcast_done": "انتهى البث.\n\nوصلت: {sent}\nتعذر الإرسال: {failed}",
    "admin_panel_label": "لوحة الأدمن:", "single_message_prompt": "أرسل نص الرسالة التي تريد إرسالها.",
    "invalid_user_id": "أرسل آيدي صحيحاً مكوّناً من أرقام.", "message_sent": "تم إرسال الرسالة.",
    "message_failed": "تعذر الإرسال. ربما المستخدم لم يبدأ البوت أو قام بحظره.",
    "not_editable": "هذا النص غير قابل للتعديل.", "saved": "تم حفظ النص الجديد.",
    "setup_token_error": "ضع توكن البوت داخل المتغير BOT_TOKEN في أعلى ملف البوت.",
}

EDIT_LABELS = {
    "welcome": "edit_welcome_button", "error": "edit_error_button",
    "developer": "edit_developer_button", "busy": "busy",
    "working": "working", "invalid_url": "invalid_url", "checking": "checking",
    "recognized": "recognized", "duration": "duration", "choose_type": "choose_type",
    "audio_button": "audio_button", "video_button": "video_button",
    "cancel_button": "cancel_button", "cancelled": "cancelled",
    "inspect_timeout": "inspect_timeout", "link_expired": "link_expired",
    "success_caption": "success_caption", "send_another": "send_another",
    "download_timeout": "download_timeout", "download_failed": "download_failed",
    "youtube_blocked": "youtube_blocked", "tiktok_unavailable": "tiktok_unavailable",
    "admin_title": "admin_title", "admin_stats_button": "admin_stats_button",
    "admin_users_button": "admin_users_button", "admin_downloads_button": "admin_downloads_button",
    "admin_broadcast_button": "admin_broadcast_button", "admin_single_button": "admin_single_button",
    "admin_edit_button": "admin_edit_button", "admin_refresh_button": "admin_refresh_button",
    "admin_back_button": "admin_back_button", "admin_back_short": "admin_back_short",
    "admin_only": "admin_only", "stats_title": "stats_title", "stats_users": "stats_users",
    "stats_downloads": "stats_downloads", "stats_success": "stats_success",
    "stats_failed": "stats_failed", "stats_day": "stats_day", "stats_audio": "stats_audio",
    "stats_video": "stats_video", "users_page": "users_page", "no_username": "no_username",
    "generic_user": "generic_user", "users_empty": "users_empty", "previous_button": "previous_button",
    "next_button": "next_button", "downloads_title": "downloads_title", "no_title": "no_title",
    "kind_audio": "kind_audio", "kind_video": "kind_video", "broadcast_prompt": "broadcast_prompt",
    "single_id_prompt": "single_id_prompt", "edit_menu_prompt": "edit_menu_prompt",
    "edit_welcome_button": "edit_welcome_button", "edit_developer_button": "edit_developer_button",
    "edit_error_button": "edit_error_button", "edit_misc_button": "edit_misc_button",
    "edit_prompt": "edit_prompt", "invalid_option": "invalid_option", "invalid_text": "invalid_text",
    "broadcast_started": "broadcast_started", "broadcast_done": "broadcast_done",
    "admin_panel_label": "admin_panel_label", "single_message_prompt": "single_message_prompt",
    "invalid_user_id": "invalid_user_id", "message_sent": "message_sent", "message_failed": "message_failed",
    "not_editable": "not_editable", "saved": "saved", "unknown_size": "unknown_size",
    "unit_b": "unit_b", "unit_kb": "unit_kb", "unit_mb": "unit_mb", "unit_gb": "unit_gb",
    "id_label": "id_label", "engine_unknown": "engine_unknown", "media_title": "media_title",
}


# =============== DATABASE ===============

def db_connect():
    conn = sqlite3.connect(DATABASE_FILE, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def strip_emoji(value):
    # Keep the bot interface emoji-free, including legacy settings and admin edits.
    return re.sub(
        r"[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0000FE0F\U0000200D]",
        "", str(value),
    )


def init_db():
    with db_connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT NOT NULL DEFAULT '',
                first_name TEXT NOT NULL DEFAULT '',
                joined_at INTEGER NOT NULL,
                last_seen INTEGER NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS downloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                media_type TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                engine TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_downloads_created_at ON downloads(created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_downloads_status ON downloads(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_last_seen ON users(last_seen DESC)")
        for key, value in DEFAULT_TEXTS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)",
                (key, value),
            )
        # Migrate previously stored labels/messages to the requested emoji-free UI.
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        for row in rows:
            cleaned = strip_emoji(row["value"])
            if cleaned != row["value"]:
                conn.execute("UPDATE settings SET value=? WHERE key=?", (cleaned, row["key"]))


def get_setting(key):
    with db_connect() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
    return row["value"] if row else DEFAULT_TEXTS.get(key, "")


def put_setting(key, value):
    value = strip_emoji(value)
    with db_connect() as conn:
        conn.execute("""
            INSERT INTO settings(key, value) VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """, (key, value))


def ui(key, **values):
    """Render an editable UI string; malformed admin templates fail safely."""
    template = get_setting(key)
    if not values:
        return template
    try:
        return template.format(**values)
    except (KeyError, ValueError, IndexError):
        logger.warning("Invalid editable template for UI key %s", key)
        return DEFAULT_TEXTS.get(key, template)


def save_user(user):
    now = int(time.time())
    with db_connect() as conn:
        conn.execute("""
            INSERT INTO users(user_id, username, first_name, joined_at, last_seen)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                last_seen=excluded.last_seen
        """, (user.id, user.username or "", user.first_name or "", now, now))


def record_download(user_id, url, media_type, title, engine, status):
    with db_connect() as conn:
        conn.execute("""
            INSERT INTO downloads(user_id, url, media_type, title, engine, status, created_at)
            VALUES(?, ?, ?, ?, ?, ?, ?)
        """, (user_id, url, media_type, title or "", engine or "", status, int(time.time())))


def is_admin(user_id):
    return int(user_id) == int(ADMIN_ID)


# =============== UI / HELPERS ===============

def developer_url():
    return f"https://t.me/{DEVELOPER_USERNAME.lstrip('@')}"


def user_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(get_setting("developer"), url=developer_url())],
    ])


def admin_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(get_setting("admin_stats_button"), callback_data="adm:stats"),
            InlineKeyboardButton(get_setting("admin_users_button"), callback_data="adm:users:0"),
        ],
        [
            InlineKeyboardButton(get_setting("admin_downloads_button"), callback_data="adm:downloads"),
            InlineKeyboardButton(get_setting("admin_broadcast_button"), callback_data="adm:broadcast"),
        ],
        [
            InlineKeyboardButton(get_setting("admin_single_button"), callback_data="adm:single"),
            InlineKeyboardButton(get_setting("admin_edit_button"), callback_data="adm:edit"),
        ],
        [InlineKeyboardButton(get_setting("admin_refresh_button"), callback_data="adm:home")],
    ])


def back_admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(get_setting("admin_back_button"), callback_data="adm:home")]
    ])


def extract_url(text):
    if not text:
        return None
    match = re.search(r"https?://[^\s<>]+", text.strip())
    if not match:
        return None
    url = match.group(0).rstrip(".,،؛)")
    if len(url) > MAX_URL_LENGTH:
        return None
    try:
        parsed = urlparse(url)
        return url if parsed.scheme in ("http", "https") and parsed.netloc else None
    except Exception:
        return None


def safe_title(value):
    fallback = get_setting("media_title")
    return (str(value or fallback).replace("\n", " ").strip()[:180] or fallback)


def format_size(size):
    if not size:
        return get_setting("unknown_size")
    value = float(size)
    units = (get_setting("unit_b"), get_setting("unit_kb"), get_setting("unit_mb"), get_setting("unit_gb"))
    for index, unit in enumerate(units):
        if value < 1024 or index == 3:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} {units[-1]}"


def find_media_file(folder, media_type):
    files = [
        p for p in Path(folder).rglob("*")
        if p.is_file() and not p.name.endswith((".part", ".ytdl", ".temp"))
    ]
    if media_type == "audio":
        # yt-dlp commonly returns WebM/Opus for non-YouTube services.
        allowed = {".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".flac", ".webm", ".mka", ".mp4"}
    else:
        allowed = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}
    candidates = [p for p in files if p.suffix.lower() in allowed]
    return max(candidates, key=lambda p: p.stat().st_size) if candidates else None


def validate_file(path, media_type):
    if not path or not Path(path).is_file():
        return False
    path = Path(path)
    if path.stat().st_size < 1024 or path.stat().st_size > MAX_UPLOAD_MB * 1024 * 1024:
        return False
    allowed_audio = {".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".flac", ".webm", ".mka", ".mp4"}
    allowed_video = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}
    return path.suffix.lower() in (allowed_audio if media_type == "audio" else allowed_video)


def prepare_telegram_video(path, workdir):
    """Prepare a Telegram-playable MP4 while avoiding needless heavy re-encoding."""
    source = Path(path)
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required to prepare Telegram-compatible video")

    output = Path(workdir) / "telegram_ready_video.mp4"
    probe_info = {}
    if ffprobe:
        probe = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries",
             "stream=codec_type,codec_name,pix_fmt", "-of", "json", str(source)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30,
        )
        if probe.returncode == 0:
            try:
                import json
                streams = json.loads(probe.stdout).get("streams", [])
                for stream in streams:
                    probe_info[stream.get("codec_type")] = stream
            except (ValueError, TypeError):
                probe_info = {}

    video = probe_info.get("video", {})
    audio = probe_info.get("audio", {})
    already_compatible = (
        video.get("codec_name") == "h264"
        and video.get("pix_fmt") == "yuv420p"
        and audio.get("codec_name") in (None, "aac")
    )

    # H.264/AAC files can usually be remuxed without expensive CPU encoding.
    if already_compatible:
        remux = subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
             "-map", "0:v:0", "-map", "0:a?", "-c", "copy",
             "-movflags", "+faststart", str(output)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120,
        )
        if remux.returncode == 0 and output.is_file() and output.stat().st_size >= 1024:
            if output.stat().st_size <= MAX_UPLOAD_MB * 1024 * 1024:
                return output
            output.unlink(missing_ok=True)
            raise RuntimeError(f"Converted video exceeds Telegram upload limit ({MAX_UPLOAD_MB} MB)")
        output.unlink(missing_ok=True)

    # Fallback: lower-resolution, single-thread encoding for constrained hosting.
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostats", "-y",
        "-i", str(source), "-map", "0:v:0", "-map", "0:a?",
        "-vf", "scale='min(640,iw)':-2", "-c:v", "libx264",
        "-preset", "ultrafast", "-crf", "30", "-threads", "1",
        "-filter_threads", "1", "-filter_complex_threads", "1",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k",
        "-movflags", "+faststart", str(output),
    ]
    try:
        result = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=360,
        )
    except subprocess.TimeoutExpired:
        output.unlink(missing_ok=True)
        raise RuntimeError("FFmpeg conversion timed out on the hosting server")

    if result.returncode != 0 or not output.is_file() or output.stat().st_size < 1024:
        output.unlink(missing_ok=True)
        detail = (result.stderr or "FFmpeg conversion failed")[-2500:]
        if result.returncode < 0:
            detail = f"FFmpeg was terminated (signal {-result.returncode}). " + detail
        raise RuntimeError(detail)
    if output.stat().st_size > MAX_UPLOAD_MB * 1024 * 1024:
        output.unlink(missing_ok=True)
        raise RuntimeError(f"Converted video exceeds Telegram upload limit ({MAX_UPLOAD_MB} MB)")
    return output


# =============== ENGINE 1: YT-DLP ===============

def prepare_telegram_audio(path, workdir):
    """Normalize extractor audio containers (including WebM/Opus) to MP3."""
    source = Path(path)
    if source.suffix.lower() == ".mp3" and validate_file(source, "audio"):
        return source

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required to convert this audio format")

    output = Path(workdir) / "telegram_ready_audio.mp3"
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostats", "-y",
        "-i", str(source), "-vn", "-c:a", "libmp3lame", "-b:a", "128k",
        str(output),
    ]
    result = subprocess.run(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, timeout=180,
    )
    if result.returncode != 0 or not output.is_file() or output.stat().st_size < 1024:
        output.unlink(missing_ok=True)
        raise RuntimeError((result.stderr or "Audio conversion failed")[-1800:])
    if output.stat().st_size > MAX_UPLOAD_MB * 1024 * 1024:
        output.unlink(missing_ok=True)
        raise RuntimeError(f"Converted audio exceeds Telegram upload limit ({MAX_UPLOAD_MB} MB)")
    return output


def engine_ytdlp(url, media_type, folder):
    """Download using yt-dlp with a format fallback for extractors with sparse formats."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "ytdlp"
    target.mkdir(parents=True, exist_ok=True)

    # Some extractors (notably short-video platforms) do not expose a
    # height-filtered format list. Retry with a less restrictive selector.
    format_candidates = (
        ["bestaudio/best"] if media_type == "audio" else
        ["bv*+ba/best", "best"]
    )
    errors = []
    info = None
    # TikTok's public webpage extractor can return a transient/unknown response.
    # Restore the retry budget used by the earlier working build for TikTok only;
    # keep the lighter resource profile for every other platform.
    tiktok_source = is_tiktok_url(url)
    for attempt, selected_format in enumerate(format_candidates, start=1):
        attempt_target = target / f"attempt{attempt}"
        attempt_target.mkdir(parents=True, exist_ok=True)
        opts = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "outtmpl": str(attempt_target / "%(title).60s_%(id)s.%(ext)s"),
            "socket_timeout": 25,
            "retries": 3 if tiktok_source else 2,
            "fragment_retries": 3 if tiktok_source else 2,
            "extractor_retries": 3 if tiktok_source else 2,
            "file_access_retries": 2 if tiktok_source else 1,
            "restrictfilenames": True,
            "max_filesize": MAX_UPLOAD_MB * 1024 * 1024,
            "overwrites": True,
            "ignoreerrors": False,
            "continuedl": True,
            "format": selected_format,
            "merge_output_format": "mp4" if media_type == "video" else None,
            "concurrent_fragment_downloads": 2 if tiktok_source else 1,
        }
        # Keep yt-dlp on its built-in downloader to avoid spawning extra processes
        # on CPU-limited hosting plans.
        if media_type == "audio":
            opts.pop("merge_output_format", None)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
            file_path = find_media_file(attempt_target, media_type)
            if file_path and validate_file(file_path, media_type):
                break
            errors.append(f"format {attempt}: no valid media output")
        except Exception as exc:
            if is_youtube_url(url) and is_platform_access_blocked(exc):
                # Do not repeat extractor requests after an explicit platform denial.
                raise PlatformAccessBlocked(str(exc)) from exc
            errors.append(f"format {attempt}: {type(exc).__name__}: {str(exc)[:240]}")
            logger.warning("yt-dlp format attempt %s failed: %s", attempt, exc)
            file_path = None
    else:
        raise RuntimeError("yt-dlp formats exhausted: " + " | ".join(errors))

    if not file_path:
        raise RuntimeError("yt-dlp did not produce a recognized media file")

    if media_type == "audio":
        file_path = prepare_telegram_audio(file_path, folder)

    if validate_file(file_path, media_type):
        return file_path, safe_title((info or {}).get("title")), "yt-dlp"
    raise RuntimeError("yt-dlp output failed validation")


# =============== ENGINE 2: PYTUBEFIX (YOUTUBE) ===============

def engine_pytubefix(url, media_type, folder):
    from pytubefix import YouTube

    target = Path(folder) / "pytubefix"
    target.mkdir(parents=True, exist_ok=True)
    yt = YouTube(url)

    if media_type == "audio":
        stream = yt.streams.filter(only_audio=True).order_by("abr").desc().first()
    else:
        stream = (
            yt.streams.filter(progressive=True, file_extension="mp4")
            .order_by("resolution").desc().first()
        )

    if stream is None:
        raise RuntimeError("No suitable YouTube stream")
    downloaded = Path(stream.download(output_path=str(target)))

    if media_type == "audio" and downloaded.suffix.lower() not in {
        ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".flac"
    }:
        import subprocess
        if not shutil.which("ffmpeg"):
            raise RuntimeError("FFmpeg is required to convert this audio")
        converted = downloaded.with_suffix(".mp3")
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(downloaded), "-vn",
             "-codec:a", "libmp3lame", "-b:a", "192k", str(converted)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=90,
        )
        downloaded = converted

    if validate_file(downloaded, media_type):
        return downloaded, safe_title(yt.title), "pytubefix"
    raise RuntimeError("pytubefix output failed validation")


# =============== ENGINE 3: INSTALOADER (PUBLIC INSTAGRAM) ===============

def engine_instaloader(url, media_type, folder):
    if media_type != "video":
        raise RuntimeError("Instaloader fallback is video-only")
    match = re.search(r"instagram\.com/(?:p|reel|tv)/([A-Za-z0-9_-]+)", url, re.I)
    if not match:
        raise RuntimeError("Unsupported Instagram URL")

    import instaloader
    shortcode = match.group(1)
    target = Path(folder) / "instaloader"
    target.mkdir(parents=True, exist_ok=True)
    loader = instaloader.Instaloader(
        dirname_pattern=str(target / "{target}"),
        filename_pattern="{shortcode}",
        download_pictures=False,
        download_videos=True,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        post_metadata_txt_pattern="",
        quiet=True,
    )
    post = instaloader.Post.from_shortcode(loader.context, shortcode)
    if not post.is_video:
        raise RuntimeError("Instagram post has no video")
    loader.download_post(post, target="post")
    file_path = find_media_file(target, "video")
    if validate_file(file_path, "video"):
        return file_path, safe_title(post.caption or "Instagram video"), "instaloader"
    raise RuntimeError("Instaloader output failed validation")


# =============== AUTOMATIC FALLBACK ORCHESTRATOR ===============

class PlatformAccessBlocked(RuntimeError):
    """The source platform explicitly refused automated access."""


class TikTokResponseUnavailable(RuntimeError):
    """TikTok returned a webpage response yt-dlp cannot currently interpret."""


def is_tiktok_url(url):
    host = (urlparse(url).hostname or "").lower().split(":", 1)[0]
    return host == "tiktok.com" or host.endswith(".tiktok.com")


def is_tiktok_response_error(error):
    return "unexpected response from webpage request" in str(error).lower()


def is_platform_access_blocked(error):
    message = f"{type(error).__name__}: {error}".lower()
    markers = (
        "sign in to confirm you're not a bot",
        'sign in to confirm you are not a bot',
        "this request was detected as a bot",
        "botdetection",
    )
    return any(marker in message for marker in markers)


def download_automatically(url, media_type, folder):
    host = (urlparse(url).hostname or "").lower()
    engines = [("yt-dlp", engine_ytdlp)]
    if "youtube.com" in host or "youtu.be" in host:
        engines.append(("pytubefix", engine_pytubefix))
    if "instagram.com" in host:
        engines.append(("instaloader", engine_instaloader))

    errors = []
    for engine_name, engine in engines:
        try:
            path, title, actual_engine = engine(url, media_type, folder)
            if validate_file(path, media_type):
                return Path(path), title, actual_engine
            errors.append(f"{engine_name}: invalid output")
        except Exception as exc:
            logger.warning("Engine %s failed for %s: %s", engine_name, host, exc)
            if is_tiktok_url(url) and is_tiktok_response_error(exc):
                raise TikTokResponseUnavailable(str(exc)) from exc
            if is_youtube_url(url) and is_platform_access_blocked(exc):
                # A second extractor is unlikely to help when the platform has
                # explicitly denied the hosting server. Do not spin retries.
                raise PlatformAccessBlocked(str(exc)) from exc
            errors.append(f"{engine_name}: {type(exc).__name__}")
    raise RuntimeError("No compatible engine succeeded: " + "; ".join(errors))


def is_youtube_url(url):
    host = (urlparse(url).hostname or "").lower().split(":", 1)[0]
    return host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")


def inspect_url(url):
    """Inspect public metadata. Do not require inspection to succeed for YouTube.

    YouTube may temporarily reject metadata requests (for example, with a bot
    verification page). The user can still choose a format and the normal
    download engine/fallback chain can report whether public access is available.
    This deliberately does not use browser cookies or bypass access controls.
    """
    tiktok_source = is_tiktok_url(url)
    opts = {
        "quiet": True, "no_warnings": True, "noplaylist": True,
        "skip_download": True, "socket_timeout": 15,
        "retries": 3 if tiktok_source else 2,
        "extractor_retries": 3 if tiktok_source else 2,
        "file_access_retries": 2 if tiktok_source else 1,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info:
            raise RuntimeError("No metadata returned by extractor")
        return {
            "title": safe_title(info.get("title")),
            "duration": info.get("duration"),
            "metadata_available": True,
        }
    except Exception as exc:
        if is_tiktok_url(url):
            # Metadata inspection is optional. Do not block the user's format
            # selection when TikTok's webpage response is temporarily unreadable;
            # let the normal download engine make its own fresh attempt.
            logger.warning("TikTok metadata inspection failed; allowing download attempt: %s", exc)
            return {
                "title": "TikTok media (metadata unavailable)",
                "duration": None,
                "metadata_available": False,
            }
        if not is_youtube_url(url):
            raise
        logger.warning("YouTube metadata inspection failed; allowing download selection", exc_info=True)
        return {
            "title": "YouTube media (metadata unavailable)",
            "duration": None,
            "metadata_available": False,
        }


# =============== USER HANDLERS ===============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update.effective_user)
    context.user_data.pop("pending_action", None)
    context.user_data.pop("pending_media", None)
    await update.message.reply_text(
        get_setting("welcome"), reply_markup=user_keyboard(),
        disable_web_page_preview=True,
    )



async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update.effective_user.id):
        context.user_data.pop("pending_action", None)
        context.user_data.pop("target_user_id", None)
        await update.message.reply_text(ui("cancelled"), reply_markup=admin_keyboard())


async def receive_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)

    if is_admin(user.id) and context.user_data.get("pending_action"):
        await handle_admin_text(update, context)
        return

    url = extract_url(update.message.text or "")
    if not url:
        await update.message.reply_text(
            ui("invalid_url"),
            reply_markup=user_keyboard(),
        )
        return

    status = await update.message.reply_text(ui("checking"))
    try:
        info = await asyncio.wait_for(
            asyncio.to_thread(inspect_url, url), timeout=min(INSPECT_TIMEOUT, 30)
        )
        context.user_data["pending_media"] = {
            "url": url, "title": info["title"], "created": time.time()
        }
        duration_line = (
            "\n" + ui("duration", seconds=int(info["duration"]))
            if info.get("duration") else ""
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(get_setting("audio_button"), callback_data="dl:audio"),
                InlineKeyboardButton(get_setting("video_button"), callback_data="dl:video"),
            ],
            [InlineKeyboardButton(get_setting("cancel_button"), callback_data="dl:cancel")],
        ])
        await status.edit_text(
            f"{ui('recognized')}\n\n{info['title'][:180]}{duration_line}\n\n{ui('choose_type')}",
            reply_markup=keyboard,
        )
    except asyncio.TimeoutError:
        await status.edit_text(ui("inspect_timeout"))
    except Exception as exc:
        logger.info("Inspect failed for %s: %s", (urlparse(url).hostname or "unknown"), exc)
        if isinstance(exc, TikTokResponseUnavailable):
            await status.edit_text(ui("tiktok_unavailable"))
        else:
            await status.edit_text(get_setting("error"))


async def download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "dl:cancel":
        context.user_data.pop("pending_media", None)
        await query.edit_message_text(ui("cancelled"))
        return

    media_type = query.data.split(":", 1)[1]
    if media_type not in ("audio", "video"):
        return

    pending = context.user_data.get("pending_media")
    if not pending or time.time() - pending.get("created", 0) > 900:
        await query.edit_message_text(ui("link_expired"))
        return

    url = pending["url"]
    fallback_title = pending.get("title", "media")
    user_id = query.from_user.id
    await query.edit_message_text(get_setting("working"))

    # Acquire atomically with a very short wait so concurrent clicks receive the
    # busy response instead of starting overlapping downloads.
    try:
        await asyncio.wait_for(download_semaphore.acquire(), timeout=0.05)
    except asyncio.TimeoutError:
        await query.edit_message_text(get_setting("busy"))
        return

    workdir = None
    release_here = True
    try:
        workdir = Path(tempfile.mkdtemp(prefix=f"media_{user_id}_", dir=TEMP_ROOT))
        await context.bot.send_chat_action(
            chat_id=query.message.chat_id,
            action=ChatAction.UPLOAD_VIDEO if media_type == "video" else ChatAction.UPLOAD_DOCUMENT
        )
        worker = asyncio.create_task(
            asyncio.to_thread(download_automatically, url, media_type, workdir)
        )
        done, _pending = await asyncio.wait({worker}, timeout=DOWNLOAD_TIMEOUT)
        if not done:
            # asyncio cannot stop a running thread. Defer cleanup and semaphore
            # release until it really exits, preventing races and resource spikes.
            async def finish_timed_out_worker():
                try:
                    await worker
                except Exception:
                    pass
                finally:
                    shutil.rmtree(workdir, ignore_errors=True)
                    download_semaphore.release()

            asyncio.create_task(finish_timed_out_worker())
            release_here = False
            raise asyncio.TimeoutError
        path, title, engine = await worker
        if not validate_file(path, media_type):
            raise RuntimeError("Final file validation failed")

        if media_type == "video":
            path = await asyncio.to_thread(prepare_telegram_video, path, workdir)
            if not validate_file(path, "video") or path.suffix.lower() != ".mp4":
                raise RuntimeError("Telegram video preparation failed")

        caption = ui(
            "success_caption", title=safe_title(title),
            size=format_size(path.stat().st_size)
        )[:900]

        with path.open("rb") as media_file:
            if media_type == "audio" and path.suffix.lower() in {".mp3", ".m4a"}:
                await context.bot.send_audio(
                    chat_id=query.message.chat_id,
                    audio=media_file,
                    title=safe_title(title)[:64],
                    caption=caption,
                    read_timeout=150, write_timeout=150,
                    connect_timeout=30, pool_timeout=30,
                )
            elif media_type == "video":
                if path.suffix.lower() != ".mp4":
                    raise RuntimeError("Prepared video is not MP4; refusing document fallback")
                await context.bot.send_video(
                    chat_id=query.message.chat_id,
                    video=media_file,
                    caption=caption,
                    supports_streaming=True,
                    read_timeout=150, write_timeout=150,
                    connect_timeout=30, pool_timeout=30,
                )
            else:
                await context.bot.send_document(
                    chat_id=query.message.chat_id,
                    document=media_file,
                    caption=caption,
                    read_timeout=150, write_timeout=150,
                    connect_timeout=30, pool_timeout=30,
                )

        record_download(user_id, url, media_type, title, engine, "success")
        await query.message.reply_text(
            ui("send_another"),
            reply_markup=user_keyboard(),
        )
    except asyncio.TimeoutError:
        record_download(user_id, url, media_type, fallback_title, "", "timeout")
        await query.message.reply_text(ui("download_timeout"))
    except Exception as exc:
        logger.exception("Download failed for user %s: %s", user_id, exc)
        record_download(user_id, url, media_type, fallback_title, "", "failed")
        if isinstance(exc, PlatformAccessBlocked):
            await query.message.reply_text(ui("youtube_blocked"))
        elif isinstance(exc, TikTokResponseUnavailable):
            await query.message.reply_text(ui("tiktok_unavailable"))
        else:
            await query.message.reply_text(
                ui("download_failed", max_mb=MAX_UPLOAD_MB)
            )
    finally:
        context.user_data.pop("pending_media", None)
        if release_here:
            if workdir is not None:
                shutil.rmtree(workdir, ignore_errors=True)
            download_semaphore.release()



# =============== ADMIN PANEL ===============

def get_stats():
    with db_connect() as conn:
        users = conn.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
        total = conn.execute("SELECT COUNT(*) n FROM downloads").fetchone()["n"]
        success = conn.execute(
            "SELECT COUNT(*) n FROM downloads WHERE status='success'"
        ).fetchone()["n"]
        failed = conn.execute(
            "SELECT COUNT(*) n FROM downloads WHERE status!='success'"
        ).fetchone()["n"]
        day_ago = int(time.time()) - 86400
        today = conn.execute(
            "SELECT COUNT(*) n FROM downloads WHERE created_at>=?", (day_ago,)
        ).fetchone()["n"]
        audio = conn.execute(
            "SELECT COUNT(*) n FROM downloads WHERE media_type='audio'"
        ).fetchone()["n"]
        video = conn.execute(
            "SELECT COUNT(*) n FROM downloads WHERE media_type='video'"
        ).fetchone()["n"]
    return users, total, success, failed, today, audio, video


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    save_user(update.effective_user)
    await update.message.reply_text(
        ui("admin_title"),
        reply_markup=admin_keyboard(),
    )


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer(ui("admin_only"), show_alert=True)
        return
    await query.answer()
    data = query.data

    if data == "adm:home":
        context.user_data.pop("pending_action", None)
        context.user_data.pop("target_user_id", None)
        await query.edit_message_text(
            ui("admin_title"),
            reply_markup=admin_keyboard(),
        )

    elif data == "adm:stats":
        users, total, success, failed, today, audio, video = get_stats()
        await query.edit_message_text(
            "\n".join([ui("stats_title"), "", ui("stats_users", users=users), ui("stats_downloads", total=total), ui("stats_success", success=success), ui("stats_failed", failed=failed), ui("stats_day", today=today), ui("stats_audio", audio=audio), ui("stats_video", video=video)]),
            reply_markup=back_admin_keyboard(),
        )

    elif data.startswith("adm:users:"):
        try:
            page = max(0, min(100000, int(data.rsplit(":", 1)[1])))
        except (TypeError, ValueError):
            await query.answer(ui("invalid_option"), show_alert=True)
            return
        page_size = 12
        offset = page * page_size
        with db_connect() as conn:
            rows = conn.execute(
                "SELECT user_id, username, first_name FROM users "
                "ORDER BY last_seen DESC LIMIT ? OFFSET ?",
                (page_size, offset),
            ).fetchall()
            count = conn.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
        lines = [ui("users_page", page=page + 1) + "\n"]
        for row in rows:
            username = f"@{row['username']}" if row["username"] else get_setting("no_username")
            name = (row["first_name"] or get_setting("generic_user")).replace("\n", " ")[:30]
            lines.append(f"{name} | {username} | {get_setting('id_label')}: {row['user_id']}")
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(get_setting("previous_button"), callback_data=f"adm:users:{page-1}"))
        if offset + page_size < count:
            nav.append(InlineKeyboardButton(get_setting("next_button"), callback_data=f"adm:users:{page+1}"))
        buttons = ([nav] if nav else []) + [
            [InlineKeyboardButton(get_setting("admin_back_short"), callback_data="adm:home")]
        ]
        await query.edit_message_text(
            "\n".join(lines) if rows else ui("users_empty"),
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    elif data == "adm:downloads":
        with db_connect() as conn:
            rows = conn.execute(
                "SELECT user_id, media_type, title, engine, status, created_at "
                "FROM downloads ORDER BY id DESC LIMIT 15"
            ).fetchall()
        lines = [ui("downloads_title") + "\n"]
        for row in rows:
            title = (row["title"] or get_setting("no_title")).replace("\n", " ")[:35]
            stamp = time.strftime("%m-%d %H:%M", time.localtime(row["created_at"]))
            kind = get_setting("kind_audio") if row["media_type"] == "audio" else get_setting("kind_video")
            lines.append(
                f"{kind} | {title} | {row['engine'] or get_setting('engine_unknown')} | "
                f"{get_setting('id_label')} {row['user_id']} | {stamp}"
            )
        await query.edit_message_text("\n".join(lines), reply_markup=back_admin_keyboard())

    elif data == "adm:broadcast":
        context.user_data["pending_action"] = "broadcast"
        await query.edit_message_text(
            ui("broadcast_prompt"),
            reply_markup=back_admin_keyboard(),
        )

    elif data == "adm:single":
        context.user_data["pending_action"] = "single_id"
        await query.edit_message_text(
            ui("single_id_prompt"),
            reply_markup=back_admin_keyboard(),
        )

    elif data == "adm:edit":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(get_setting("edit_welcome_button"), callback_data="adm:edit:welcome")],
            [InlineKeyboardButton(get_setting("edit_developer_button"), callback_data="adm:edit:developer")],
            [InlineKeyboardButton(get_setting("edit_error_button"), callback_data="adm:edit:error")],
            [InlineKeyboardButton(get_setting("edit_misc_button"), callback_data="adm:edit:more")],
            [InlineKeyboardButton(get_setting("admin_back_short"), callback_data="adm:home")],
        ])
        await query.edit_message_text(ui("edit_menu_prompt"), reply_markup=keyboard)

    elif data == "adm:edit:more":
        keys = [k for k in EDIT_LABELS if k not in {"welcome", "error", "developer"}]
        rows = [[InlineKeyboardButton(get_setting(EDIT_LABELS[k]), callback_data=f"adm:edit:{k}")] for k in keys]
        rows.append([InlineKeyboardButton(get_setting("admin_back_short"), callback_data="adm:edit")])
        await query.edit_message_text(ui("edit_menu_prompt"), reply_markup=InlineKeyboardMarkup(rows))

    elif data.startswith("adm:edit:"):
        key = data.split(":")[-1]
        if key not in DEFAULT_TEXTS:
            await query.answer(ui("invalid_option"), show_alert=True)
            return
        context.user_data["pending_action"] = f"edit:{key}"
        await query.edit_message_text(
            ui("edit_prompt", current=get_setting(key)),
            reply_markup=back_admin_keyboard(),
        )


async def send_broadcast_one(bot, user_id, message_text):
    async with broadcast_semaphore:
        try:
            await bot.send_message(chat_id=user_id, text=message_text)
            return True
        except RetryAfter as exc:
            await asyncio.sleep(float(exc.retry_after) + 1)
            try:
                await bot.send_message(chat_id=user_id, text=message_text)
                return True
            except TelegramError:
                return False
        except (Forbidden, BadRequest, NetworkError, TelegramError):
            return False


async def handle_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        context.user_data.pop("pending_action", None)
        return

    action = context.user_data.get("pending_action")
    text = (update.message.text or "").strip()
    if not action:
        return
    if not text:
        await update.message.reply_text(ui("invalid_text"))
        return

    if action == "broadcast":
        context.user_data.pop("pending_action", None)
        with db_connect() as conn:
            user_ids = [
                row["user_id"] for row in
                conn.execute("SELECT user_id FROM users").fetchall()
            ]
        status = await update.message.reply_text(
            ui("broadcast_started", count=len(user_ids))
        )
        results = await asyncio.gather(*[
            send_broadcast_one(context.bot, uid, text) for uid in user_ids
        ])
        sent = sum(bool(result) for result in results)
        failed = len(results) - sent
        await status.edit_text(ui("broadcast_done", sent=sent, failed=failed))
        await update.message.reply_text(ui("admin_panel_label"), reply_markup=admin_keyboard())

    elif action == "single_id":
        try:
            target_id = int(text)
            if target_id <= 0:
                raise ValueError
            context.user_data["target_user_id"] = target_id
            context.user_data["pending_action"] = "single_message"
            await update.message.reply_text(ui("single_message_prompt"))
        except ValueError:
            await update.message.reply_text(ui("invalid_user_id"))

    elif action == "single_message":
        target_id = context.user_data.pop("target_user_id", None)
        context.user_data.pop("pending_action", None)
        try:
            if not isinstance(target_id, int) or target_id <= 0:
                raise ValueError("invalid target")
            await context.bot.send_message(chat_id=target_id, text=text)
            await update.message.reply_text(ui("message_sent"))
        except (TelegramError, ValueError):
            await update.message.reply_text(ui("message_failed"))
        await update.message.reply_text(ui("admin_panel_label"), reply_markup=admin_keyboard())

    elif action.startswith("edit:"):
        key = action.split(":", 1)[1]
        if key not in DEFAULT_TEXTS:
            context.user_data.pop("pending_action", None)
            await update.message.reply_text(ui("not_editable"))
            return
        put_setting(key, text[:3500])
        context.user_data.pop("pending_action", None)
        await update.message.reply_text(ui("saved"))
        await update.message.reply_text(ui("admin_panel_label"), reply_markup=admin_keyboard())


# =============== STARTUP ===============

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Unhandled exception: %s", context.error, exc_info=context.error)


def acquire_instance_lock():
    """Prevent two polling processes on the same host from sharing one token."""
    global _INSTANCE_LOCK_HANDLE
    lock_path = TEMP_ROOT / ".polling-instance.lock"
    handle = open(lock_path, "a+")
    try:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except ImportError:
        handle.close()
        raise RuntimeError("This deployment needs POSIX file locking; run one bot instance only")
    except BlockingIOError:
        handle.close()
        raise SystemExit("Another bot polling process already holds the instance lock")
    _INSTANCE_LOCK_HANDLE = handle


def main():
    if not BOT_TOKEN or BOT_TOKEN == "PASTE_YOUR_BOT_TOKEN_HERE":
        raise SystemExit(
            DEFAULT_TEXTS["setup_token_error"]
        )

    acquire_instance_lock()
    init_db()
    # Longer HTTP timeouts help on slow/mobile networks such as Pydroid.
    # Separate request clients are used for normal Bot API calls and long polling.
    api_request = HTTPXRequest(
        connection_pool_size=8,
        connect_timeout=35.0,
        read_timeout=35.0,
        write_timeout=35.0,
        pool_timeout=35.0,
    )
    polling_request = HTTPXRequest(
        connection_pool_size=4,
        connect_timeout=35.0,
        read_timeout=45.0,
        write_timeout=35.0,
        pool_timeout=35.0,
    )

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .request(api_request)
        .get_updates_request(polling_request)
        .concurrent_updates(4)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CallbackQueryHandler(download_callback, pattern=r"^dl:"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern=r"^adm:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_text))
    app.add_error_handler(error_handler)

    logger.info("Downloader bot V12.2 resource-optimized starting")
    deno_path = shutil.which("deno")
    if deno_path:
        logger.info("JavaScript runtime detected: Deno at %s", deno_path)
    else:
        logger.warning("Deno not detected; YouTube extraction compatibility may be reduced. This does not bypass platform access restrictions.")
    logger.info("Resource profile: max downloads=%s, fragment concurrency=1, broadcast concurrency=%s", MAX_CONCURRENT_DOWNLOADS, MAX_PARALLEL_BROADCAST)
    # This single-process polling configuration is suitable for modest traffic.
    # Large deployments require webhook workers, shared storage, Redis and PostgreSQL.
    # Retry Telegram's initial getMe/bootstrap connection instead of exiting
    # immediately when the first connection attempt times out.
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
        bootstrap_retries=-1,
        poll_interval=1.0,
        timeout=30,
    )


if __name__ == "__main__":
    main()
