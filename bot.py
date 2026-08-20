# -*- coding: utf-8 -*-
"""
ربات پیام ناشناس چالش‌ها - pyTelegramBotAPI (telebot)

ویژگی‌های این نسخه:
- عضویت اجباری قبل از استفاده از ربات
- سه کانال برای جوین: لینک خصوصی + دو کانال عمومی
- دکمه «عضو شدم | فعال‌سازی» برای بررسی مجدد عضویت
- رنگ‌بندی دکمه‌ها با استایل‌های رسمی Telegram Bot API:
  primary (آبی)، success (سبز)، danger (قرمز)
- حفظ منطق قبلی پیام ناشناس، پاسخ ادمین، انتشار و پنل مدیریت

نصب:
    pip install -U "pyTelegramBotAPI>=4.34.0"

متغیرهای محیطی:
    BOT_TOKEN=...
    ADMIN_IDS=1391789851,7484808604
    CHANNEL_ID=@void_qr

    # برای کانال خصوصی اول، چون لینک invite خصوصی قابل استفاده در getChat نیست،
    # باید Chat ID عددی همان کانال را وارد کنید:
    FORCE_JOIN_PRIVATE_ID=-100xxxxxxxxxx

    DB_PATH=anon_bot.db
"""

import logging
import os
import sqlite3
import threading
from datetime import datetime

import telebot
from telebot import types


# ================================================================
# ⚙️ CONFIG
# ================================================================

# توکن قبلی داخل پیام شما افشا شده بود؛ آن را اینجا قرار ندهید.
# حتماً از @BotFather توکن را revoke/rotate کنید و فقط از ENV بدهید.
BOT_TOKEN = os.getenv("BOT_TOKEN", "8959682206:AAGKs0UIiy6jV7Olvd4Xr7cr6T3RIo_Gkgg").strip()

_admin_ids_raw = os.getenv("ADMIN_IDS", "1391789851,7484808604")
ADMIN_IDS = [
    int(x.strip())
    for x in _admin_ids_raw.split(",")
    if x.strip().lstrip("-").isdigit()
]
ADMIN_ID = ADMIN_IDS[0] if ADMIN_IDS else None

# کانال انتشار پاسخ‌ها
CHANNEL_ID = os.getenv("CHANNEL_ID", "@void_qr").strip()

DB_PATH = os.getenv("DB_PATH", "anon_bot.db").strip()

# ================================================================
# 🔒 عضویت اجباری
# ================================================================
#
# کانال اول لینک خصوصی دارد:
# https://t.me/+3mkzbv4FfrQyMDg0
#
# برای بررسی واقعی عضویت در کانال خصوصی، Bot API به chat_id نیاز دارد.
# مقدار FORCE_JOIN_PRIVATE_ID را از اطلاعات کانال بردارید و در ENV بگذارید.
#
# دو کانال عمومی:
# https://t.me/void_qr
# https://t.me/Srssec
#
# برای get_chat_member بهتر است ربات در هر سه کانال ادمین باشد.

# آیدی عددی کانال خصوصی
FORCE_JOIN_PRIVATE_ID = "-1004370596151"

FORCE_JOIN_CHANNELS = [
    {
        "title": "کانال اول",
        "url": "https://t.me/+3mkzbv4FfrQyMDg0",
        "chat_id": FORCE_JOIN_PRIVATE_ID,
        "style": "primary",
    },
    {
        "title": "@void_qr",
        "url": "https://t.me/void_qr",
        "chat_id": "@void_qr",
        "style": "primary",
    },
    {
        "title": "@Srssec",
        "url": "https://t.me/Srssec",
        "chat_id": "@Srssec",
        "style": "primary",
    },
]


if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN تنظیم نشده است. آن را به صورت متغیر محیطی BOT_TOKEN قرار دهید."
    )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="Markdown")
db_lock = threading.Lock()

# state ساده در حافظه:
# {user_id: {"state": "...", "data": {...}}}
user_states: dict[int, dict] = {}
pending_admin_reply: dict[int, int] = {}


STATE_WAITING_CATEGORY = "waiting_category"
STATE_WAITING_CONTENT = "waiting_content"
STATE_ADMIN_WAITING_REPLY = "admin_waiting_reply"


# ================================================================
# 🧠 State helpers
# ================================================================

def set_state(user_id: int, state: str, data: dict | None = None):
    user_states[user_id] = {"state": state, "data": data or {}}


def get_state(user_id: int):
    entry = user_states.get(user_id)
    return entry["state"] if entry else None


def get_state_data(user_id: int) -> dict:
    entry = user_states.get(user_id)
    return entry["data"] if entry else {}


def clear_state(user_id: int):
    user_states.pop(user_id, None)


# ================================================================
# 🌐 متن‌های دوزبانه
# ================================================================

TEXTS = {
    "fa": {
        "choose_lang": "🌐 لطفاً زبان خودت رو انتخاب کن:",
        "welcome": (
            "👋 سلام!\n\n"
            "به ربات پیام ناشناس *چالش‌ها* خوش اومدی 🎯\n"
            "از اینجا می‌تونی سوال، انتقاد، پیشنهاد یا گزارش تخلف بفرستی و "
            "هویتت کاملاً محفوظ می‌مونه 🔒\n\n"
            "یکی از گزینه‌های زیر رو انتخاب کن 👇"
        ),
        "menu_send": "📩 ارسال پیام ناشناس",
        "menu_help": "ℹ️ راهنما",
        "menu_lang": "🌐 تغییر زبان",
        "menu_mystatus": "📊 وضعیت پیام‌های من",
        "choose_category": "🗂 نوع پیامت رو انتخاب کن:",
        "cat_question": "❓ سوال",
        "cat_criticism": "💬 انتقاد",
        "cat_suggestion": "💡 چالش",
        "cat_report": "🚫 گزارش تخلف",
        "back": "🔙 برگشت",
        "ask_message": (
            "📩 پیام ناشناس خود را ارسال کنید\n\n"
            "متن، عکس، فیلم، ویس، فایل، موزیک، استیکر یا GIF می‌توانید ارسال کنید.\n\n"
            "برای لغو /cancel را بزنید."
        ),
        "message_sent": "✅ پیامت با موفقیت و کاملاً ناشناس ارسال شد!\nمنتظر پاسخ باش 🙏",
        "message_cancelled": "❌ لغو شد.",
        "blocked": "🚫 متاسفانه امکان ارسال پیام برای شما وجود نداره.",
        "help_text": (
            "ℹ️ *راهنمای ربات*\n\n"
            "📩 ارسال پیام ناشناس → سوال/انتقاد/پیشنهاد/گزارش تخلف بفرست\n"
            "📊 وضعیت پیام‌های من → ببین پیامت جواب داده شده یا نه\n"
            "🌐 تغییر زبان → فارسی ⇄ English\n\n"
            "🔒 هویت تو هیچ‌وقت با بقیه به اشتراک گذاشته نمیشه."
        ),
        "new_msg_admin": "📬 *پیام جدید* [#{msg_id}]\n🗂 دسته: {category}\n👤 شناسه داخلی: `{user_id}`",
        "admin_reply_btn": "💬 پاسخ",
        "admin_publish_btn": "📢 انتشار در کانال",
        "admin_block_btn": "🚫 بلاک فرستنده",
        "admin_unblock_btn": "✅ آنبلاک فرستنده",
        "admin_ignore_btn": "🗑 نادیده گرفتن",
        "ask_admin_reply": "✍️ پاسخت رو برای پیام #{msg_id} بنویس:",
        "reply_sent_to_admin": "✅ پاسخ برای کاربر ارسال شد.",
        "reply_received": "📩 *پاسخ به پیام شما:*\n\n{reply}",
        "user_blocked_notice": "🚫 کاربر بلاک شد و دیگه نمی‌تونه پیام بفرسته.",
        "user_unblocked_notice": "✅ کاربر آنبلاک شد.",
        "msg_ignored": "🗑 پیام نادیده گرفته شد.",
        "published_ok": "📢 پیام با موفقیت در کانال منتشر شد.",
        "published_need_reply": "⚠️ برای انتشار در کانال، اول باید پاسخ بدی.",
        "channel_post": "❓ *سوال/پیام ناشناس:*\n{question}\n\n💬 *پاسخ:*\n{answer}",
        "status_none": "📭 شما هنوز پیامی نفرستادی.",
        "status_header": "📊 *آخرین پیام‌های تو:*\n\n",
        "status_pending": "⏳ در انتظار پاسخ",
        "status_answered": "✅ پاسخ داده شد",
        "status_line": "#{msg_id} | {category} | {status}\n",
        "admin_only": "⛔️ این بخش فقط برای ادمین در دسترسه.",
        "admin_panel_title": "🛠 *پنل مدیریت*",
        "admin_stats_btn": "📊 آمار کلی",
        "admin_blocklist_btn": "🚫 لیست بلاک‌شده‌ها",
        "stats_text": (
            "📊 *آمار ربات*\n\n"
            "📨 کل پیام‌ها: {total}\n"
            "⏳ در انتظار پاسخ: {pending}\n"
            "✅ پاسخ داده‌شده: {answered}\n"
            "🚫 کاربران بلاک‌شده: {blocked}\n"
            "👥 کل کاربران: {users}"
        ),
        "no_blocked": "✅ فعلاً هیچ کاربری بلاک نیست.",

        # forced join
        "join_title": (
            "🔐 *برای استفاده از ربات، ابتدا عضو کانال‌های زیر شوید.*\n\n"
            "بعد از عضویت، روی «عضو شدم | فعال‌سازی» بزنید تا عضویت شما بررسی شود."
        ),
        "join_check": "عضو شدم | فعال‌سازی",
        "join_success": "✅ عضویت شما تأیید شد. خوش اومدی!",
        "join_not_done": (
            "⚠️ هنوز عضویت شما در همه کانال‌ها تأیید نشده.\n"
            "ابتدا عضو هر سه کانال شوید و دوباره دکمه فعال‌سازی را بزنید."
        ),
        "join_check_error": (
            "⚠️ بررسی یکی از کانال‌ها ممکن نشد. "
            "مطمئن شوید ربات در کانال‌ها دسترسی لازم را دارد."
        ),
    },
    "en": {
        "choose_lang": "🌐 Please choose your language:",
        "welcome": (
            "👋 Hello!\n\n"
            "Welcome to the *Challenges* anonymous message bot 🎯\n"
            "You can send questions, criticism, suggestions, or report a violation, "
            "and your identity stays fully private 🔒\n\n"
            "Pick an option below 👇"
        ),
        "menu_send": "📩 Send Anonymous Message",
        "menu_help": "ℹ️ Help",
        "menu_lang": "🌐 Change Language",
        "menu_mystatus": "📊 My Messages Status",
        "choose_category": "🗂 Choose your message type:",
        "cat_question": "❓ Question",
        "cat_criticism": "💬 Criticism",
        "cat_suggestion": "💡 Challenge",
        "cat_report": "🚫 Report Violation",
        "back": "🔙 Back",
        "ask_message": (
            "📩 Send your anonymous message\n\n"
            "You can send text, photo, video, voice, file, audio, sticker or GIF.\n\n"
            "Send /cancel to abort."
        ),
        "message_sent": "✅ Your message was sent anonymously!\nWait for a reply 🙏",
        "message_cancelled": "❌ Cancelled.",
        "blocked": "🚫 Sorry, you're not allowed to send messages.",
        "help_text": (
            "ℹ️ *Bot Help*\n\n"
            "📩 Send Anonymous Message → question/criticism/suggestion/report\n"
            "📊 My Messages Status → check if you got a reply\n"
            "🌐 Change Language → English ⇄ فارسی\n\n"
            "🔒 Your identity is never shared with anyone else."
        ),
        "new_msg_admin": "📬 *New message* [#{msg_id}]\n🗂 Category: {category}\n👤 Internal ID: `{user_id}`",
        "admin_reply_btn": "💬 Reply",
        "admin_publish_btn": "📢 Publish to Channel",
        "admin_block_btn": "🚫 Block Sender",
        "admin_unblock_btn": "✅ Unblock Sender",
        "admin_ignore_btn": "🗑 Ignore",
        "ask_admin_reply": "✍️ Type your reply to message #{msg_id}:",
        "reply_sent_to_admin": "✅ Reply sent to the user.",
        "reply_received": "📩 *Reply to your message:*\n\n{reply}",
        "user_blocked_notice": "🚫 User has been blocked.",
        "user_unblocked_notice": "✅ User has been unblocked.",
        "msg_ignored": "🗑 Message ignored.",
        "published_ok": "📢 Successfully published to the channel.",
        "published_need_reply": "⚠️ You need to reply first before publishing.",
        "channel_post": "❓ *Anonymous question/message:*\n{question}\n\n💬 *Answer:*\n{answer}",
        "status_none": "📭 You haven't sent any messages yet.",
        "status_header": "📊 *Your recent messages:*\n\n",
        "status_pending": "⏳ Waiting for reply",
        "status_answered": "✅ Answered",
        "status_line": "#{msg_id} | {category} | {status}\n",
        "admin_only": "⛔️ This section is admin-only.",
        "admin_panel_title": "🛠 *Admin Panel*",
        "admin_stats_btn": "📊 Overall Stats",
        "admin_blocklist_btn": "🚫 Blocked Users List",
        "stats_text": (
            "📊 *Bot Stats*\n\n"
            "📨 Total messages: {total}\n"
            "⏳ Pending: {pending}\n"
            "✅ Answered: {answered}\n"
            "🚫 Blocked users: {blocked}\n"
            "👥 Total users: {users}"
        ),
        "no_blocked": "✅ No blocked users currently.",

        # forced join
        "join_title": (
            "🔐 *Please join all channels below before using the bot.*\n\n"
            "After joining, press «Joined | Activate» to verify your membership."
        ),
        "join_check": "Joined | Activate",
        "join_success": "✅ Membership verified. Welcome!",
        "join_not_done": (
            "⚠️ You are not verified in all required channels yet.\n"
            "Join all three channels and press the activation button again."
        ),
        "join_check_error": (
            "⚠️ One of the channels could not be checked. "
            "Make sure the bot has the required access in the channels."
        ),
    },
}


CATEGORY_LABELS = {
    "fa": {
        "question": "❓ سوال",
        "criticism": "💬 انتقاد",
        "suggestion": "💡 چالش",
        "report": "🚫 گزارش تخلف",
    },
    "en": {
        "question": "❓ Question",
        "criticism": "💬 Criticism",
        "suggestion": "💡 Challenge",
        "report": "🚫 Report",
    },
}


def t(lang: str, key: str, **kwargs) -> str:
    lang = lang if lang in TEXTS else "fa"
    raw = TEXTS[lang].get(key, key)
    return raw.format(**kwargs) if kwargs else raw


# ================================================================
# 🗄️ SQLite
# ================================================================

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    language TEXT DEFAULT 'fa',
    is_blocked INTEGER DEFAULT 0,
    joined_at TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    msg_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    category TEXT,
    content_type TEXT,
    text_content TEXT,
    file_id TEXT,
    source_chat_id INTEGER,
    source_message_id INTEGER,
    admin_reply TEXT,
    status TEXT DEFAULT 'pending',
    created_at TEXT
);
"""


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def migrate_db():
    with db_lock:
        conn = get_conn()
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(messages)")}
        if "source_chat_id" not in cols:
            conn.execute("ALTER TABLE messages ADD COLUMN source_chat_id INTEGER")
        if "source_message_id" not in cols:
            conn.execute("ALTER TABLE messages ADD COLUMN source_message_id INTEGER")
        conn.commit()
        conn.close()


def init_db():
    with db_lock:
        conn = get_conn()
        conn.executescript(CREATE_TABLES_SQL)
        conn.commit()
        conn.close()


def upsert_user(user_id: int, username):
    with db_lock:
        conn = get_conn()
        row = conn.execute(
            "SELECT user_id FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()

        if row is None:
            conn.execute(
                "INSERT INTO users (user_id, username, joined_at) VALUES (?, ?, ?)",
                (user_id, username, datetime.utcnow().isoformat()),
            )
        else:
            conn.execute(
                "UPDATE users SET username = ? WHERE user_id = ?",
                (username, user_id),
            )

        conn.commit()
        conn.close()


def set_language(user_id: int, lang: str):
    with db_lock:
        conn = get_conn()
        conn.execute(
            "UPDATE users SET language = ? WHERE user_id = ?",
            (lang, user_id),
        )
        conn.commit()
        conn.close()


def get_language(user_id: int) -> str:
    with db_lock:
        conn = get_conn()
        row = conn.execute(
            "SELECT language FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        conn.close()

        return row["language"] if row and row["language"] else "fa"


def is_blocked(user_id: int) -> bool:
    with db_lock:
        conn = get_conn()
        row = conn.execute(
            "SELECT is_blocked FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        conn.close()
        return bool(row and row["is_blocked"])


def set_blocked(user_id: int, blocked: bool):
    with db_lock:
        conn = get_conn()
        conn.execute(
            "UPDATE users SET is_blocked = ? WHERE user_id = ?",
            (1 if blocked else 0, user_id),
        )
        conn.commit()
        conn.close()


def add_message(
    user_id: int,
    category: str,
    content_type: str,
    text_content,
    file_id,
    source_chat_id: int | None = None,
    source_message_id: int | None = None,
) -> int:
    with db_lock:
        conn = get_conn()
        cur = conn.execute(
            """
            INSERT INTO messages
            (user_id, category, content_type, text_content, file_id,
             source_chat_id, source_message_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id, category, content_type, text_content, file_id,
                source_chat_id, source_message_id, datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()
        msg_id = cur.lastrowid
        conn.close()
        return msg_id


def get_message(msg_id: int):
    with db_lock:
        conn = get_conn()
        row = conn.execute(
            "SELECT * FROM messages WHERE msg_id = ?", (msg_id,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None


def set_admin_reply(msg_id: int, reply_text: str):
    with db_lock:
        conn = get_conn()
        conn.execute(
            """
            UPDATE messages
            SET admin_reply = ?, status = 'answered'
            WHERE msg_id = ?
            """,
            (reply_text, msg_id),
        )
        conn.commit()
        conn.close()


def get_user_messages(user_id: int, limit: int = 10):
    with db_lock:
        conn = get_conn()
        rows = conn.execute(
            """
            SELECT msg_id, category, status
            FROM messages
            WHERE user_id = ?
            ORDER BY msg_id DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
        conn.close()
        return rows


def get_stats():
    with db_lock:
        conn = get_conn()
        total = conn.execute(
            "SELECT COUNT(*) c FROM messages"
        ).fetchone()["c"]
        pending = conn.execute(
            "SELECT COUNT(*) c FROM messages WHERE status = 'pending'"
        ).fetchone()["c"]
        answered = conn.execute(
            "SELECT COUNT(*) c FROM messages WHERE status = 'answered'"
        ).fetchone()["c"]
        blocked = conn.execute(
            "SELECT COUNT(*) c FROM users WHERE is_blocked = 1"
        ).fetchone()["c"]
        users = conn.execute(
            "SELECT COUNT(*) c FROM users"
        ).fetchone()["c"]
        conn.close()

        return {
            "total": total,
            "pending": pending,
            "answered": answered,
            "blocked": blocked,
            "users": users,
        }


def get_blocked_users():
    with db_lock:
        conn = get_conn()
        rows = conn.execute(
            """
            SELECT user_id, username
            FROM users
            WHERE is_blocked = 1
            """
        ).fetchall()
        conn.close()
        return rows


# ================================================================
# 🎨 Button helpers
# ================================================================

def styled_button(
    text: str,
    *,
    style: str = "primary",
    url: str | None = None,
    callback_data: str | None = None,
):
    """
    Telegram supports exactly three predefined styles:
    primary = blue
    success = green
    danger = red
    """
    return types.InlineKeyboardButton(
        text=text,
        url=url,
        callback_data=callback_data,
        style=style,
    )


def styled_reply_button(text: str, style: str = "primary"):
    return types.KeyboardButton(text=text, style=style)


# ================================================================
# 🔐 Forced Join
# ================================================================

def membership_is_active(status: str, is_member: bool | None = None) -> bool:
    """
    member / administrator / creator => joined
    restricted => joined only when is_member=True
    left / kicked => not joined
    """
    if status in ("member", "administrator", "creator"):
        return True

    if status == "restricted":
        return bool(is_member)

    return False


def check_user_membership(user_id: int):
    """
    Returns:
        (True, None)       -> all verified
        (False, "missing") -> private channel ID is not configured
        (False, "error")   -> Telegram check failed
        (False, "not_joined") -> user is not a 
