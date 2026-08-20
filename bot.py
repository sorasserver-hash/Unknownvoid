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
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

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
            "✍️ حالا پیامت رو بنویس یا بفرست "
            "(متن، عکس، ویس یا ویدیو).\n\n"
            "برای لغو /cancel رو بزن."
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
            "✍️ Now send your message "
            "(text, photo, voice or video).\n\n"
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
    admin_reply TEXT,
    status TEXT DEFAULT 'pending',
    created_at TEXT
);
"""


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


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
) -> int:
    with db_lock:
        conn = get_conn()
        cur = conn.execute(
            """
            INSERT INTO messages
            (user_id, category, content_type, text_content, file_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                category,
                content_type,
                text_content,
                file_id,
                datetime.utcnow().isoformat(),
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
        (False, "not_joined") -> user is not a member
    """
    for channel in FORCE_JOIN_CHANNELS:
        chat_id = channel["chat_id"]

        # A private invite URL alone is not enough for get_chat_member.
        if not chat_id:
            logging.error(
                "FORCE_JOIN_PRIVATE_ID is not configured; "
                "cannot verify the private channel."
            )
            return False, "missing"

        try:
            member = bot.get_chat_member(chat_id, user_id)

            if not membership_is_active(
                getattr(member, "status", ""),
                getattr(member, "is_member", None),
            ):
                return False, "not_joined"

        except Exception as exc:
            logging.warning(
                "Membership check failed for %s / user %s: %s",
                chat_id,
                user_id,
                exc,
            )
            return False, "error"

    return True, None


def forced_join_keyboard(lang: str):
    kb = types.InlineKeyboardMarkup()

    # همه دکمه‌های عضویت آبی؛ دکمه تأیید سبز.
    for channel in FORCE_JOIN_CHANNELS:
        kb.row(
            styled_button(
                f"🔗 عضویت",
                style=channel["style"],
                url=channel["url"],
            )
        )

    # دکمه فعال‌سازی سبز تا از دکمه‌های لینک متمایز باشد.
    kb.row(
        styled_button(
            f"✅ {t(lang, 'join_check')}",
            style="success",
            callback_data="forcejoin:check",
        )
    )
    return kb


def send_forced_join(chat_id: int, lang: str):
    bot.send_message(
        chat_id,
        t(lang, "join_title"),
        reply_markup=forced_join_keyboard(lang),
    )


def ensure_joined_or_prompt(message) -> bool:
    """
    Gate اصلی ربات.
    اگر کاربر عضو نباشد، هیچ‌کدام از قابلیت‌های اصلی اجرا نمی‌شوند.
    """
    ok, reason = check_user_membership(message.from_user.id)

    if ok:
        return True

    lang = get_language(message.from_user.id)

    if reason == "missing":
        bot.send_message(
            message.chat.id,
            "⚠️ تنظیمات عضویت اجباری کامل نشده است.\n"
            "ادمین باید FORCE_JOIN_PRIVATE_ID را تنظیم کند.",
        )
    elif reason == "error":
        bot.send_message(
            message.chat.id,
            t(lang, "join_check_error"),
            reply_markup=forced_join_keyboard(lang),
        )
    else:
        send_forced_join(message.chat.id, lang)

    return False


# ================================================================
# ⌨️ Keyboards
# ================================================================

def language_keyboard():
    kb = types.ReplyKeyboardMarkup(
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    kb.row(
        styled_reply_button("🇮🇷 فارسی", "primary"),
        styled_reply_button("🇬🇧 English", "primary"),
    )
    return kb


def main_menu_keyboard(lang: str):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)

    # رنگ‌بندی کنترل‌شده: اکشن اصلی سبز، وضعیت/راهنما آبی، تغییر زبان خنثی/آبی.
    kb.row(
        styled_reply_button(t(lang, "menu_send"), "success")
    )
    kb.row(
        styled_reply_button(t(lang, "menu_mystatus"), "primary"),
        styled_reply_button(t(lang, "menu_help"), "primary"),
    )
    kb.row(
        styled_reply_button(t(lang, "menu_lang"), "primary")
    )
    return kb


def category_keyboard(lang: str):
    kb = types.InlineKeyboardMarkup()

    kb.row(
        styled_button(
            t(lang, "cat_question"),
            style="primary",
            callback_data="cat:question",
        ),
        styled_button(
            t(lang, "cat_criticism"),
            style="primary",
            callback_data="cat:criticism",
        ),
    )
    kb.row(
        styled_button(
            t(lang, "cat_suggestion"),
            style="success",
            callback_data="cat:suggestion",
        ),
        styled_button(
            t(lang, "cat_report"),
            style="danger",
            callback_data="cat:report",
        ),
    )
    return kb


def admin_message_keyboard(
    lang: str,
    msg_id: int,
    user_id: int,
    user_blocked: bool,
):
    kb = types.InlineKeyboardMarkup()

    kb.row(
        styled_button(
            t(lang, "admin_reply_btn"),
            style="success",
            callback_data=f"reply:{msg_id}",
        )
    )
    kb.row(
        styled_button(
            t(lang, "admin_publish_btn"),
            style="primary",
            callback_data=f"publish:{msg_id}",
        )
    )

    block_btn = (
        styled_button(
            t(lang, "admin_unblock_btn"),
            style="success",
            callback_data=f"unblock:{user_id}",
        )
        if user_blocked
        else styled_button(
            t(lang, "admin_block_btn"),
            style="danger",
            callback_data=f"block:{user_id}",
        )
    )

    kb.row(
        block_btn,
        styled_button(
            t(lang, "admin_ignore_btn"),
            style="primary",
            callback_data=f"ignore:{msg_id}",
        ),
    )
    return kb


def admin_panel_keyboard(lang: str):
    kb = types.InlineKeyboardMarkup()

    kb.row(
        styled_button(
            t(lang, "admin_stats_btn"),
            style="primary",
            callback_data="admin:stats",
        )
    )
    kb.row(
        styled_button(
            t(lang, "admin_blocklist_btn"),
            style="danger",
            callback_data="admin:blocklist",
        )
    )
    return kb


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ================================================================
# 🚦 /start + Language
# ================================================================

@bot.message_handler(commands=["start"])
def cmd_start(message):
    user_id = message.from_user.id

    clear_state(user_id)
    upsert_user(user_id, message.from_user.username)

    # اول عضویت اجباری، بعد زبان.
    if not ensure_joined_or_prompt(message):
        return

    bot.send_message(
        message.chat.id,
        t("fa", "choose_lang") + "\n" + t("en", "choose_lang"),
        reply_markup=language_keyboard(),
    )


@bot.message_handler(
    func=lambda m: m.text in ["🇮🇷 فارسی", "🇬🇧 English"]
)
def choose_language(message):
    if not ensure_joined_or_prompt(message):
        return

    lang = "fa" if "فارسی" in message.text else "en"

    set_language(message.from_user.id, lang)
    clear_state(message.from_user.id)

    bot.send_message(
        message.chat.id,
        t(lang, "welcome"),
        reply_markup=main_menu_keyboard(lang),
    )


@bot.callback_query_handler(func=lambda c: c.data == "forcejoin:check")
def forcejoin_check(call):
    user_id = call.from_user.id

    ok, reason = check_user_membership(user_id)

    if ok:
        lang = get_language(user_id)
        bot.answer_callback_query(
            call.id,
            t(lang, "join_success"),
            show_alert=True,
        )

        # پیام جوین را حذف می‌کنیم تا صفحه تمیز بماند.
        try:
            bot.delete_message(
                call.message.chat.id,
                call.message.message_id,
            )
        except Exception:
            pass

        bot.send_message(
            call.message.chat.id,
            t(lang, "welcome"),
            reply_markup=main_menu_keyboard(lang),
        )
        return

    lang = get_language(user_id)

    if reason == "missing":
        text = (
            "⚠️ تنظیمات عضویت اجباری کامل نشده است.\n"
            "ادمین باید FORCE_JOIN_PRIVATE_ID را تنظیم کند."
        )
    elif reason == "error":
        text = t(lang, "join_check_error")
    else:
        text = t(lang, "join_not_done")

    bot.answer_callback_query(
        call.id,
        text,
        show_alert=True,
    )


@bot.message_handler(
    func=lambda m: m.text in [
        t("fa", "menu_lang"),
        t("en", "menu_lang"),
    ]
)
def change_language(message):
    if not ensure_joined_or_prompt(message):
        return

    clear_state(message.from_user.id)

    bot.send_message(
        message.chat.id,
        t("fa", "choose_lang") + "\n" + t("en", "choose_lang"),
        reply_markup=language_keyboard(),
    )


@bot.message_handler(
    func=lambda m: m.text in [
        t("fa", "menu_help"),
        t("en", "menu_help"),
    ]
)
def show_help(message):
    if not ensure_joined_or_prompt(message):
        return

    lang = get_language(message.from_user.id)
    bot.send_message(
        message.chat.id,
        t(lang, "help_text"),
    )


# ================================================================
# 📩 ارسال پیام ناشناس
# ================================================================

@bot.message_handler(
    func=lambda m: m.text in [
        t("fa", "menu_send"),
        t("en", "menu_send"),
    ]
)
def start_send_message(message):
    if not ensure_joined_or_prompt(message):
        return

    lang = get_language(message.from_user.id)

    if is_blocked(message.from_user.id):
        bot.send_message(message.chat.id, t(lang, "blocked"))
        return

    bot.send_message(
        message.chat.id,
        t(lang, "choose_category"),
        reply_markup=category_keyboard(lang),
    )

    set_state(
        message.from_user.id,
        STATE_WAITING_CATEGORY,
    )


@bot.callback_query_handler(
    func=lambda c: (
        c.data.startswith("cat:")
        and get_state(c.from_user.id) == STATE_WAITING_CATEGORY
    )
)
def choose_category_cb(call):
    # callbackهای اصلی هم باید از gate عبور کنند.
    ok, _ = check_user_membership(call.from_user.id)
    if not ok:
        lang = get_language(call.from_user.id)
        bot.answer_callback_query(
            call.id,
            t(lang, "join_not_done"),
            show_alert=True,
        )
        return

    lang = get_language(call.from_user.id)
    category = call.data.split(":")[1]

    set_state(
        call.from_user.id,
        STATE_WAITING_CONTENT,
        {"category": category},
    )

    try:
        bot.edit_message_reply_markup(
            call.message.chat.id,
            call.message.message_id,
            reply_markup=None,
        )
    except Exception:
        pass

    bot.send_message(
        call.message.chat.id,
        t(lang, "ask_message"),
    )
    bot.answer_callback_query(call.id)


@bot.message_handler(commands=["cancel"])
def cancel_any(message):
    if not ensure_joined_or_prompt(message):
        return

    lang = get_language(message.from_user.id)

    if get_state(message.from_user.id) is not None:
        clear_state(message.from_user.id)

        bot.send_message(
            message.chat.id,
            t(lang, "message_cancelled"),
            reply_markup=main_menu_keyboard(lang),
        )


@bot.message_handler(
    func=lambda m: (
        get_state(m.from_user.id) == STATE_WAITING_CONTENT
        and m.content_type in [
            "text",
            "photo",
            "voice",
            "video",
            "document",
        ]
    )
)
def receive_user_content(message):
    if not ensure_joined_or_prompt(message):
        return

    lang = get_language(message.from_user.id)
    data = get_state_data(message.from_user.id)
    category = data.get("category", "question")

    content_type = "text"
    text_content = None
    file_id = None

    if message.photo:
        content_type = "photo"
        file_id = message.photo[-1].file_id
        text_content = message.caption

    elif message.voice:
        content_type = "voice"
        file_id = message.voice.file_id

    elif message.video:
        content_type = "video"
        file_id = message.video.file_id
        text_content = message.caption

    elif message.document:
        content_type = "document"
        file_id = message.document.file_id
        text_content = message.caption

    elif message.text:
        content_type = "text"
        text_content = message.text

    else:
        return

    msg_id = add_message(
        message.from_user.id,
        category,
        content_type,
        text_content,
        file_id,
    )

    user_blocked = is_blocked(message.from_user.id)

    admin_lang = "fa"

    caption = t(
        admin_lang,
        "new_msg_admin",
        msg_id=msg_id,
        category=CATEGORY_LABELS[admin_lang].get(
            category,
            category,
        ),
        user_id=message.from_user.id,
    )

    kb = admin_message_keyboard(
        admin_lang,
        msg_id,
        message.from_user.id,
        user_blocked,
    )

    for admin_id in ADMIN_IDS:
        try:
            if content_type == "text":
                bot.send_message(
                    admin_id,
                    f"{caption}\n\n{text_content}",
                    reply_markup=kb,
                )

            elif content_type == "photo":
                bot.send_photo(
                    admin_id,
                    file_id,
                    caption=f"{caption}\n\n{text_content or ''}",
                    reply_markup=kb,
                )

            elif content_type == "voice":
                bot.send_voice(
                    admin_id,
                    file_id,
                    caption=caption,
                    reply_markup=kb,
                )

            elif content_type == "video":
                bot.send_video(
                    admin_id,
                    file_id,
                    caption=f"{caption}\n\n{text_content or ''}",
                    reply_markup=kb,
                )

            elif content_type == "document":
                bot.send_document(
                    admin_id,
                    file_id,
                    caption=f"{caption}\n\n{text_content or ''}",
                    reply_markup=kb,
                )

        except Exception as exc:
            logging.warning(
                "Could not deliver new message to admin %s: %s",
                admin_id,
                exc,
            )

    clear_state(message.from_user.id)

    bot.send_message(
        message.chat.id,
        t(lang, "message_sent"),
        reply_markup=main_menu_keyboard(lang),
    )


# ================================================================
# 📊 وضعیت پیام‌های کاربر
# ================================================================

@bot.message_handler(
    func=lambda m: m.text in [
        t("fa", "menu_mystatus"),
        t("en", "menu_mystatus"),
    ]
)
def my_status(message):
    if not ensure_joined_or_prompt(message):
        return

    lang = get_language(message.from_user.id)
    rows = get_user_messages(message.from_user.id)

    if not rows:
        bot.send_message(
            message.chat.id,
            t(lang, "status_none"),
        )
        return

    text = t(lang, "status_header")

    for row in rows:
        status_label = (
            t(lang, "status_answered")
            if row["status"] == "answered"
            else t(lang, "status_pending")
        )

        cat_label = CATEGORY_LABELS[lang].get(
            row["category"],
            row["category"],
        )

        text += t(
            lang,
            "status_line",
            msg_id=row["msg_id"],
            category=cat_label,
            status=status_label,
        )

    bot.send_message(
        message.chat.id,
        text,
    )


# ================================================================
# 🛠 Admin actions
# ================================================================

@bot.callback_query_handler(
    func=lambda c: c.data.startswith("reply:")
)
def admin_reply_start(call):
    if not _is_admin(call.from_user.id):
        bot.answer_callback_query(
            call.id,
            t("fa", "admin_only"),
            show_alert=True,
        )
        return

    msg_id = int(call.data.split(":")[1])

    pending_admin_reply[call.from_user.id] = msg_id
    set_state(
        call.from_user.id,
        STATE_ADMIN_WAITING_REPLY,
    )

    bot.send_message(
        call.message.chat.id,
        t("fa", "ask_admin_reply", msg_id=msg_id),
    )
    bot.answer_callback_query(call.id)


@bot.message_handler(
    func=lambda m: (
        get_state(m.from_user.id) == STATE_ADMIN_WAITING_REPLY
    )
)
def admin_reply_receive(message):
    if not _is_admin(message.from_user.id):
        return

    msg_id = pending_admin_reply.get(message.from_user.id)

    if msg_id is None:
        clear_state(message.from_user.id)
        return

    row = get_message(msg_id)

    if row is None:
        clear_state(message.from_user.id)
        return

    # پاسخ ادمین فقط به صورت متن است.
    if not message.text:
        bot.send_message(
            message.chat.id,
            "⚠️ لطفاً پاسخ را به صورت متن ارسال کن.",
        )
        return

    set_admin_reply(msg_id, message.text)

    user_lang = get_language(row["user_id"])

    try:
        bot.send_message(
            row["user_id"],
            t(
                user_lang,
                "reply_received",
                reply=message.text,
            ),
        )
    except Exception as exc:
        logging.warning(
            "Could not deliver reply to user %s: %s",
            row["user_id"],
            exc,
        )

    bot.send_message(
        message.chat.id,
        t("fa", "reply_sent_to_admin"),
    )

    clear_state(message.from_user.id)
    pending_admin_reply.pop(
        message.from_user.id,
        None,
    )


@bot.callback_query_handler(
    func=lambda c: c.data.startswith("publish:")
)
def admin_publish(call):
    if not _is_admin(call.from_user.id):
        bot.answer_callback_query(
            call.id,
            t("fa", "admin_only"),
            show_alert=True,
        )
        return

    msg_id = int(call.data.split(":")[1])
    row = get_message(msg_id)

    if row is None:
        bot.answer_callback_query(
            call.id,
            "Message not found",
            show_alert=True,
        )
        return

    if not CHANNEL_ID:
        bot.answer_callback_query(
            call.id,
            "CHANNEL_ID تنظیم نشده",
            show_alert=True,
        )
        return

    question_text = row["text_content"] or "(رسانه)"

    if row["admin_reply"]:
        post_text = t(
            "fa",
            "channel_post",
            question=question_text,
            answer=row["admin_reply"],
        )
    else:
        post_text = (
            "❓ *سوال/پیام ناشناس:*\n"
            f"{question_text}"
        )

    try:
        bot.send_message(
            CHANNEL_ID,
            post_text,
        )

        bot.answer_callback_query(
            call.id,
            t("fa", "published_ok"),
            show_alert=True,
        )

    except Exception as exc:
        logging.warning("Could not publish to channel: %s", exc)
        bot.answer_callback_query(
            call.id,
            f"خطا در انتشار: {exc}",
            show_alert=True,
        )


@bot.callback_query_handler(
    func=lambda c: c.data.startswith("block:")
)
def admin_block(call):
    if not _is_admin(call.from_user.id):
        bot.answer_callback_query(
            call.id,
            t("fa", "admin_only"),
            show_alert=True,
        )
        return

    user_id = int(call.data.split(":")[1])

    set_blocked(user_id, True)

    bot.answer_callback_query(
        call.id,
        t("fa", "user_blocked_notice"),
        show_alert=True,
    )


@bot.callback_query_handler(
    func=lambda c: c.data.startswith("unblock:")
)
def admin_unblock(call):
    if not _is_admin(call.from_user.id):
        bot.answer_callback_query(
            call.id,
            t("fa", "admin_only"),
            show_alert=True,
        )
        return

    user_id = int(call.data.split(":")[1])

    set_blocked(user_id, False)

    bot.answer_callback_query(
        call.id,
        t("fa", "user_unblocked_notice"),
        show_alert=True,
    )


@bot.callback_query_handler(
    func=lambda c: c.data.startswith("ignore:")
)
def admin_ignore(call):
    if not _is_admin(call.from_user.id):
        bot.answer_callback_query(
            call.id,
            t("fa", "admin_only"),
            show_alert=True,
        )
        return

    bot.answer_callback_query(
        call.id,
        t("fa", "msg_ignored"),
    )

    try:
        bot.edit_message_reply_markup(
            call.message.chat.id,
            call.message.message_id,
            reply_markup=None,
        )
    except Exception:
        pass


# ================================================================
# 🛠 Admin panel
# ================================================================

@bot.message_handler(commands=["admin"])
def admin_panel(message):
    if not _is_admin(message.from_user.id):
        bot.send_message(
            message.chat.id,
            t("fa", "admin_only"),
        )
        return

    bot.send_message(
        message.chat.id,
        t("fa", "admin_panel_title"),
        reply_markup=admin_panel_keyboard("fa"),
    )


@bot.callback_query_handler(
    func=lambda c: c.data == "admin:stats"
)
def admin_stats(call):
    if not _is_admin(call.from_user.id):
        bot.answer_callback_query(
            call.id,
            t("fa", "admin_only"),
            show_alert=True,
        )
        return

    stats = get_stats()

    bot.send_message(
        call.message.chat.id,
        t("fa", "stats_text", **stats),
    )

    bot.answer_callback_query(call.id)


@bot.callback_query_handler(
    func=lambda c: c.data == "admin:blocklist"
)
def admin_blocklist(call):
    if not _is_admin(call.from_user.id):
        bot.answer_callback_query(
            call.id,
            t("fa", "admin_only"),
            show_alert=True,
        )
        return

    rows = get_blocked_users()

    if not rows:
        bot.send_message(
            call.message.chat.id,
            t("fa", "no_blocked"),
        )
    else:
        text = "🚫 *کاربران بلاک‌شده:*\n\n"

        for row in rows:
            uname = (
                f"@{row['username']}"
                if row["username"]
                else "—"
            )

            text += (
                f"`{row['user_id']}` "
                f"({uname})\n"
            )

        bot.send_message(
            call.message.chat.id,
            text,
        )

    bot.answer_callback_query(call.id)


# ================================================================
# ▶️ Run
# ================================================================

def main():
    init_db()

    logging.info("ربات در حال اجراست...")
    logging.info(
        "Forced join channels: %s",
        [
            {
                "title": x["title"],
                "chat_id": x["chat_id"],
                "url": x["url"],
            }
            for x in FORCE_JOIN_CHANNELS
        ],
    )

    if not FORCE_JOIN_PRIVATE_ID:
        logging.warning(
            "FORCE_JOIN_PRIVATE_ID تنظیم نشده؛ "
            "عضویت کانال خصوصی قابل بررسی نیست و ربات کاربران را عبور نمی‌دهد."
        )

    bot.infinity_polling(
        skip_pending=True,
        allowed_updates=["message", "callback_query"],
    )


if __name__ == "__main__":
    main()
