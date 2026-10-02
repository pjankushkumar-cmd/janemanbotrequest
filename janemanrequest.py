import logging
import os
import sqlite3
import threading
import asyncio
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ChatJoinRequestHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ============================================================
# JANEMAN BOT SUPPORT V22 PRO
# Join-request greeting + approval tracking + broadcast
# Existing saved-message system is preserved.
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ============================================================
# BOT CONFIGURATION — EDIT ONLY THESE 2 LINES
# ============================================================
BOT_TOKEN = "8831391243:AAFNUMEngpQns6MQk3Hf9WZb9uBDuk_3mRw"
ADMIN_ID = 8767998937
# ============================================================

DB_FILE = "janeman_pro.db"

CACHED_MESSAGES = []
CACHE_LOCK = threading.RLock()


# ------------------------------------------------------------
# Render health server
# ------------------------------------------------------------
class HealthCheckServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"JANEMAN BOT V22 PRO is running.")

    def log_message(self, format, *args):
        return


def run_health_server():
    port = int(os.environ.get("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), HealthCheckServer)
    logger.info("Health server started on port %s", port)
    server.serve_forever()


def self_ping_loop():
    render_url = os.environ.get("RENDER_EXTERNAL_URL", "").strip()
    if not render_url:
        logger.info("RENDER_EXTERNAL_URL not set; self-ping disabled.")
        return

    logger.info("Self-ping engine enabled: %s", render_url)
    while True:
        try:
            import time
            time.sleep(30)
            req = urllib.request.Request(
                render_url,
                headers={"User-Agent": "JANEMAN-BOT-HealthCheck/2.0"},
            )
            with urllib.request.urlopen(req, timeout=8) as response:
                logger.info("Health ping: HTTP %s", response.status)
        except Exception as exc:
            logger.warning("Self-ping warning: %s", exc)


# ------------------------------------------------------------
# Database
# ------------------------------------------------------------
def db_connect():
    conn = sqlite3.connect(DB_FILE, timeout=15)
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


def init_db():
    global CACHED_MESSAGES

    conn = db_connect()
    cur = conn.cursor()

    cur.execute(
        "CREATE TABLE IF NOT EXISTS settings "
        "(key TEXT PRIMARY KEY, value TEXT)"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS stats "
        "(key TEXT PRIMARY KEY, count INTEGER)"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS users "
        "(user_id INTEGER PRIMARY KEY)"
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS messages_list (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL,
            msg_id TEXT NOT NULL
        )
        """
    )

    # New durable join-request table. Existing DBs are upgraded automatically.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS join_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            requested_at TEXT NOT NULL,
            approved_at TEXT DEFAULT '',
            rejected_at TEXT DEFAULT '',
            greeting_sent INTEGER NOT NULL DEFAULT 0,
            greeting_failed INTEGER NOT NULL DEFAULT 0,
            UNIQUE(chat_id, user_id)
        )
        """
    )

    # New counters are added without touching old counters.
    defaults = {
        "total_requests": 0,
        "accepted": 0,
        "rejected": 0,
        "pending": 0,
        "greeting_sent": 0,
        "greeting_failed": 0,
    }
    for key, value in defaults.items():
        cur.execute(
            "INSERT OR IGNORE INTO stats(key, count) VALUES(?, ?)",
            (key, value),
        )

    cur.execute(
        "INSERT OR IGNORE INTO settings(key, value) VALUES('auto_accept', 'OFF')"
    )
    cur.execute(
        "SELECT chat_id, msg_id FROM messages_list ORDER BY id ASC"
    )
    with CACHE_LOCK:
        CACHED_MESSAGES = cur.fetchall()

    conn.commit()
    conn.close()
    logger.info("Database initialized. Cached messages: %s", len(CACHED_MESSAGES))


def get_setting(key, default="OFF"):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else default


def set_setting(key, value):
    conn = db_connect()
    conn.execute(
        "INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)",
        (key, value),
    )
    conn.commit()
    conn.close()


def add_saved_message(chat_id, msg_id):
    global CACHED_MESSAGES
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO messages_list(chat_id, msg_id) VALUES(?, ?)",
        (str(chat_id), str(msg_id)),
    )
    cur.execute(
        "SELECT chat_id, msg_id FROM messages_list ORDER BY id ASC"
    )
    new_cache = cur.fetchall()
    conn.commit()
    conn.close()

    with CACHE_LOCK:
        CACHED_MESSAGES = new_cache


def clear_saved_messages():
    # Kept for compatibility with the existing panel.
    # It is NEVER called automatically.
    global CACHED_MESSAGES
    conn = db_connect()
    conn.execute("DELETE FROM messages_list")
    conn.commit()
    conn.close()
    with CACHE_LOCK:
        CACHED_MESSAGES = []


def add_user(user_id):
    conn = db_connect()
    conn.execute(
        "INSERT OR IGNORE INTO users(user_id) VALUES(?)",
        (int(user_id),),
    )
    conn.commit()
    conn.close()


def get_all_users():
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users ORDER BY user_id")
    users = [row[0] for row in cur.fetchall()]
    conn.close()
    return users


def get_stats():
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT key, count FROM stats")
    stats = dict(cur.fetchall())
    conn.close()
    return stats


def update_stat(key, amount=1):
    conn = db_connect()
    conn.execute(
        "INSERT OR IGNORE INTO stats(key, count) VALUES(?, 0)",
        (key,),
    )
    conn.execute(
        "UPDATE stats SET count = count + ? WHERE key=?",
        (int(amount), key),
    )
    conn.commit()
    conn.close()


# ------------------------------------------------------------
# Join-request database helpers
# ------------------------------------------------------------
def upsert_join_request(chat_id, user):
    now = datetime.now(timezone.utc).isoformat()
    conn = db_connect()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, status FROM join_requests
        WHERE chat_id=? AND user_id=?
        """,
        (str(chat_id), int(user.id)),
    )
    existing = cur.fetchone()

    if existing:
        request_id, old_status = existing
        # A fresh Telegram request should be pending again if the old
        # record had been closed. Existing greeting settings are retained.
        cur.execute(
            """
            UPDATE join_requests
            SET username=?, first_name=?, status='pending',
                requested_at=?, approved_at='', rejected_at=''
            WHERE id=?
            """,
            (
                user.username or "",
                user.first_name or "",
                now,
                request_id,
            ),
        )
    else:
        cur.execute(
            """
            INSERT INTO join_requests
            (chat_id, user_id, username, first_name, status, requested_at)
            VALUES (?, ?, ?, ?, 'pending', ?)
            """,
            (
                str(chat_id),
                int(user.id),
                user.username or "",
                user.first_name or "",
                now,
            ),
        )
        request_id = cur.lastrowid

    conn.commit()
    conn.close()
    return int(request_id)


def mark_greeting(request_id, success):
    conn = db_connect()
    if success:
        conn.execute(
            "UPDATE join_requests SET greeting_sent=1, greeting_failed=0 WHERE id=?",
            (int(request_id),),
        )
        conn.commit()
        conn.close()
        update_stat("greeting_sent", 1)
    else:
        conn.execute(
            "UPDATE join_requests SET greeting_failed=1 WHERE id=?",
            (int(request_id),),
        )
        conn.commit()
        conn.close()
        update_stat("greeting_failed", 1)


def set_request_status(request_id, status):
    conn = db_connect()
    now = datetime.now(timezone.utc).isoformat()

    if status == "approved":
        conn.execute(
            """
            UPDATE join_requests
            SET status='approved', approved_at=?, rejected_at=''
            WHERE id=?
            """,
            (now, int(request_id)),
        )
    elif status == "rejected":
        conn.execute(
            """
            UPDATE join_requests
            SET status='rejected', rejected_at=?, approved_at=''
            WHERE id=?
            """,
            (now, int(request_id)),
        )
    else:
        conn.execute(
            "UPDATE join_requests SET status=? WHERE id=?",
            (status, int(request_id)),
        )

    conn.commit()
    conn.close()


def get_request(request_id):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, chat_id, user_id, username, first_name, status,
               requested_at, approved_at, rejected_at,
               greeting_sent, greeting_failed
        FROM join_requests WHERE id=?
        """,
        (int(request_id),),
    )
    row = cur.fetchone()
    conn.close()
    return row


def get_join_counts():
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT status, COUNT(*) FROM join_requests GROUP BY status"
    )
    data = dict(cur.fetchall())
    conn.close()
    return {
        "pending": int(data.get("pending", 0)),
        "approved": int(data.get("approved", 0)),
        "rejected": int(data.get("rejected", 0)),
    }


def get_recent_requests(limit=10):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, user_id, username, first_name, status, requested_at
        FROM join_requests
        ORDER BY id DESC LIMIT ?
        """,
        (int(limit),),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


# ------------------------------------------------------------
# UI helpers
# ------------------------------------------------------------
def main_text():
    stats = get_stats()
    jr = get_join_counts()
    with CACHE_LOCK:
        saved = len(CACHED_MESSAGES)

    return (
        "<b>👑 JANEMAN BOT SUPPORT V22 PRO 👑</b>\n\n"
        "⚡ Join Request + Welcome + Broadcast\n\n"
        f"📨 Total Requests: <b>{stats.get('total_requests', 0)}</b>\n"
        f"🟡 Pending: <b>{jr['pending']}</b>\n"
        f"✅ Approved: <b>{jr['approved']}</b>\n"
        f"❌ Rejected: <b>{jr['rejected']}</b>\n"
        f"👥 Broadcast Users: <b>{len(get_all_users())}</b>\n"
        f"💾 Saved Greeting Items: <b>{saved}</b>"
    )


def welcome_text():
    auto_status = get_setting("auto_accept")
    status = "🟢 ON" if auto_status == "ON" else "🔴 OFF"

    with CACHE_LOCK:
        total_saved = len(CACHED_MESSAGES)

    return (
        "<b>⚙️ Welcome Sequence Settings</b>\n\n"
        f"🔄 Auto Accept: <b>{status}</b>\n"
        f"📦 Saved Messages: <b>{total_saved}</b>\n\n"
        "Request आते ही saved messages requester को भेजे जाएंगे.\n"
        "Telegram Premium/custom emoji वाले saved messages "
        "copy_message से अपनी original entities के साथ भेजे जाएंगे.\n\n"
        "➕ Add से message/voice/photo/video/document/media save करें."
    )


def broadcast_text():
    users = get_all_users()
    return (
        "<b>📣 Broadcast Tool</b>\n\n"
        f"👥 Database Users: <b>{len(users)}</b>\n\n"
        "अब message/media भेजने पर database users को copy किया जाएगा.\n"
        "❌ Cancel के लिए button दबाएँ."
    )


def requests_text():
    c = get_join_counts()
    return (
        "<b>📋 Join Request Statistics</b>\n\n"
        f"📨 Total: <b>{get_stats().get('total_requests', 0)}</b>\n"
        f"🟡 Pending: <b>{c['pending']}</b>\n"
        f"✅ Approved: <b>{c['approved']}</b>\n"
        f"❌ Rejected: <b>{c['rejected']}</b>\n"
        f"🎁 Greetings Sent: <b>{get_stats().get('greeting_sent', 0)}</b>\n"
        f"⚠️ Greeting Failed: <b>{get_stats().get('greeting_failed', 0)}</b>"
    )


def get_main_menu():
    keyboard = [
        [
            InlineKeyboardButton("📋 Join Requests", callback_data="request_stats"),
            InlineKeyboardButton("🔄 Refresh", callback_data="refresh_main"),
        ],
        [
            InlineKeyboardButton("⚙️ Welcome Settings", callback_data="welcome_settings"),
            InlineKeyboardButton("📣 Broadcast", callback_data="broadcast_tool"),
        ],
        [
            InlineKeyboardButton("🧾 Recent Requests", callback_data="recent_requests"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_welcome_menu():
    auto_status = get_setting("auto_accept")
    status = "🟢 ON" if auto_status == "ON" else "🔴 OFF"

    with CACHE_LOCK:
        total_saved = len(CACHED_MESSAGES)

    keyboard = [
        [InlineKeyboardButton(f"🔄 Auto Accept: {status}", callback_data="toggle_auto")],
        [InlineKeyboardButton(
            "➕ Add Message / Voice / Media",
            callback_data="edit_welcome",
        )],
        [InlineKeyboardButton(
            f"🗑️ Clear All Saved ({total_saved})",
            callback_data="clear_welcome",
        )],
        [InlineKeyboardButton("👁️ Test Sequence", callback_data="test_msg")],
        [InlineKeyboardButton("⬅️ Main Menu", callback_data="refresh_main")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_broadcast_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 Send Broadcast", callback_data="start_broadcast")],
        [
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_action"),
            InlineKeyboardButton("🔄 Refresh", callback_data="broadcast_tool"),
        ],
        [InlineKeyboardButton("⬅️ Main Menu", callback_data="refresh_main")],
    ])


def get_request_action_menu(request_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_req:{request_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_req:{request_id}"),
        ],
    ])


# ------------------------------------------------------------
# Telegram helpers
# ------------------------------------------------------------
async def safe_edit(query, text, reply_markup=None):
    try:
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML,
        )
        return True
    except Exception as exc:
        logger.warning("Panel edit failed: %s", exc)
        try:
            if query.message:
                await query.message.reply_text(
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML,
                )
                return True
        except Exception:
            logger.exception("Panel fallback reply failed")
        return False


async def send_sequence_messages_instant(bot, chat_id):
    # IMPORTANT: this only READS saved messages; it never deletes them.
    with CACHE_LOCK:
        messages = list(CACHED_MESSAGES)

    if not messages:
        return 0, 0

    success = 0
    failed = 0

    for source_chat_id, source_msg_id in messages:
        try:
            await bot.copy_message(
                chat_id=chat_id,
                from_chat_id=int(source_chat_id),
                message_id=int(source_msg_id),
            )
            success += 1
        except Exception as exc:
            failed += 1
            logger.warning(
                "Sequence delivery failed to %s: %s",
                chat_id,
                exc,
            )

    return success, failed


# ------------------------------------------------------------
# /start
# ------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user:
        return

    add_user(update.effective_user.id)

    if update.effective_user.id != ADMIN_ID:
        return

    context.user_data["state"] = None

    if not update.message:
        return

    await update.message.reply_text(
        main_text(),
        reply_markup=get_main_menu(),
        parse_mode=ParseMode.HTML,
    )


# ------------------------------------------------------------
# CALLBACK HANDLER
# ------------------------------------------------------------
async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query is None:
        return

    try:
        await query.answer()
    except Exception:
        pass

    if not query.from_user or query.from_user.id != ADMIN_ID:
        try:
            await query.answer("Access Denied!", show_alert=True)
        except Exception:
            pass
        return

    data = query.data or ""
    logger.info("ADMIN BUTTON CLICK: %s", data)

    try:
        if data == "none":
            return

        if data == "refresh_main":
            context.user_data["state"] = None
            await safe_edit(query, main_text(), get_main_menu())
            return

        if data == "request_stats":
            context.user_data["state"] = None
            await safe_edit(
                query,
                requests_text(),
                InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Refresh", callback_data="request_stats")],
                    [InlineKeyboardButton("⬅️ Main Menu", callback_data="refresh_main")],
                ]),
            )
            return

        if data == "recent_requests":
            rows = get_recent_requests(10)
            if not rows:
                text = "<b>🧾 Recent Requests</b>\n\nNo requests yet."
            else:
                parts = ["<b>🧾 Recent Requests</b>\n"]
                for rid, uid, username, first_name, status, requested_at in rows:
                    name = first_name or "Unknown"
                    uname = f"@{username}" if username else "no username"
                    icon = {"pending": "🟡", "approved": "✅", "rejected": "❌"}.get(
                        status, "•"
                    )
                    parts.append(
                        f"{icon} <b>#{rid}</b> {name} ({uname})\n"
                        f"   ID: <code>{uid}</code> | {status}\n"
                        f"   {requested_at}\n"
                    )
                text = "\n".join(parts)

            await safe_edit(
                query,
                text,
                InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Refresh", callback_data="recent_requests")],
                    [InlineKeyboardButton("⬅️ Main Menu", callback_data="refresh_main")],
                ]),
            )
            return

        if data == "welcome_settings":
            context.user_data["state"] = None
            await safe_edit(query, welcome_text(), get_welcome_menu())
            return

        if data == "toggle_auto":
            current = get_setting("auto_accept")
            new_status = "OFF" if current == "ON" else "ON"
            set_setting("auto_accept", new_status)
            context.user_data["state"] = None
            await safe_edit(query, welcome_text(), get_welcome_menu())
            return

        if data == "edit_welcome":
            context.user_data["state"] = "waiting_welcome"
            await safe_edit(
                query,
                "<b>📝 Add Welcome Message / Voice / Media</b>\n\n"
                "अब message, voice, photo, video या document भेजें.\n"
                "हर item permanent SQLite storage में save होगा.\n\n"
                "✅ Save के बाद और messages भेज सकते हैं.\n"
                "⬅️ Panel के लिए /start भेजें.",
                get_welcome_menu(),
            )
            return

        if data == "clear_welcome":
            clear_saved_messages()
            context.user_data["state"] = None
            await safe_edit(
                query,
                "<b>🗑️ Saved Welcome Messages Cleared</b>\n\n"
                "📦 Saved Messages: <b>0</b>\n\n"
                "⚠️ यह action केवल तब होता है जब admin खुद Clear button दबाता है.",
                get_welcome_menu(),
            )
            return

        if data == "test_msg":
            context.user_data["state"] = None
            with CACHE_LOCK:
                total = len(CACHED_MESSAGES)

            if total == 0:
                await query.answer(
                    "Pehle Welcome Settings me message save karo.",
                    show_alert=True,
                )
                return

            success, failed = await send_sequence_messages_instant(
                context.bot, ADMIN_ID
            )
            await query.message.reply_text(
                f"👁️ <b>Test Complete</b>\n\n"
                f"📦 Saved: <b>{total}</b>\n"
                f"✅ Sent: <b>{success}</b>\n"
                f"❌ Failed: <b>{failed}</b>",
                parse_mode=ParseMode.HTML,
            )
            return

        if data == "broadcast_tool":
            context.user_data["state"] = None
            await safe_edit(query, broadcast_text(), get_broadcast_menu())
            return

        if data == "start_broadcast":
            context.user_data["state"] = "waiting_broadcast"
            await safe_edit(
                query,
                "<b>📣 Broadcast Ready</b>\n\n"
                "अब message/media भेजें.\n"
                "वही message database users को copy किया जाएगा.\n\n"
                "❌ Cancel के लिए Cancel दबाएँ.",
                InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]
                ]),
            )
            return

        if data == "cancel_action":
            context.user_data["state"] = None
            await safe_edit(query, main_text(), get_main_menu())
            return

        # Manual approve/reject buttons for individual join requests.
        if data.startswith("approve_req:"):
            request_id = int(data.split(":", 1)[1])
            row = get_request(request_id)
            if not row:
                await query.answer("Request record नहीं मिला.", show_alert=True)
                return

            _, chat_id, user_id, username, first_name, status, *_ = row
            if status == "approved":
                await query.answer("Already approved.", show_alert=True)
                return
            if status == "rejected":
                await query.answer("Already rejected.", show_alert=True)
                return

            try:
                await context.bot.approve_chat_join_request(
                    chat_id=int(chat_id),
                    user_id=int(user_id),
                )
                set_request_status(request_id, "approved")
                update_stat("accepted", 1)
                update_stat("pending", -1)

                await safe_edit(
                    query,
                    f"✅ <b>Request Approved</b>\n\n"
                    f"👤 {first_name or 'Unknown'}\n"
                    f"🆔 <code>{user_id}</code>\n"
                    f"📌 Request: <b>#{request_id}</b>",
                    None,
                )
            except Exception as exc:
                logger.warning("Manual approval failed: %s", exc)
                await query.answer(
                    "Approve failed. Bot admin rights / channel settings check करें.",
                    show_alert=True,
                )
            return

        if data.startswith("reject_req:"):
            request_id = int(data.split(":", 1)[1])
            row = get_request(request_id)
            if not row:
                await query.answer("Request record नहीं मिला.", show_alert=True)
                return

            _, chat_id, user_id, username, first_name, status, *_ = row
            if status == "rejected":
                await query.answer("Already rejected.", show_alert=True)
                return
            if status == "approved":
                await query.answer("Already approved.", show_alert=True)
                return

            try:
                await context.bot.decline_chat_join_request(
                    chat_id=int(chat_id),
                    user_id=int(user_id),
                )
                set_request_status(request_id, "rejected")
                update_stat("rejected", 1)
                update_stat("pending", -1)

                await safe_edit(
                    query,
                    f"❌ <b>Request Rejected</b>\n\n"
                    f"👤 {first_name or 'Unknown'}\n"
                    f"🆔 <code>{user_id}</code>\n"
                    f"📌 Request: <b>#{request_id}</b>",
                    None,
                )
            except Exception as exc:
                logger.warning("Manual rejection failed: %s", exc)
                await query.answer(
                    "Reject failed. Bot admin rights / channel settings check करें.",
                    show_alert=True,
                )
            return

        await query.answer("Unknown button action.", show_alert=True)

    except Exception as exc:
        logger.exception("Callback handler error for %r: %s", data, exc)
        try:
            await query.message.reply_text(
                "❌ <b>Button Error</b>\n\n"
                "Action: <code>"
                + str(data).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                + "</code>\n"
                "Error server log में record हो गया है.",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass


# ------------------------------------------------------------
# Content handler
# ------------------------------------------------------------
async def content_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return

    if not update.message:
        return

    state = context.user_data.get("state")

    if state == "waiting_welcome":
        # Existing saved message is only appended; previous saved messages
        # are never overwritten or deleted.
        add_saved_message(
            update.message.chat_id,
            update.message.message_id,
        )

        with CACHE_LOCK:
            total_saved = len(CACHED_MESSAGES)

        await update.message.reply_text(
            f"✅ <b>Welcome message saved!</b>\n\n"
            f"📦 Total Saved: <b>{total_saved}</b>\n\n"
            "Aur message/media भेजें, या /start से panel खोलें.",
            parse_mode=ParseMode.HTML,
        )
        return

    if state == "waiting_broadcast":
        context.user_data["state"] = None
        users = get_all_users()

        await update.message.reply_text(
            f"🚀 <b>Broadcast Started</b>\n\n"
            f"👥 Total Users: <b>{len(users)}</b>",
            parse_mode=ParseMode.HTML,
        )

        success = 0
        failed = 0

        for user_id in users:
            try:
                await context.bot.copy_message(
                    chat_id=user_id,
                    from_chat_id=update.message.chat_id,
                    message_id=update.message.message_id,
                )
                success += 1
            except Exception as exc:
                failed += 1
                logger.warning("Broadcast failed for %s: %s", user_id, exc)

        await update.message.reply_text(
            f"🏁 <b>Broadcast Complete</b>\n\n"
            f"✅ Sent: <b>{success}</b>\n"
            f"❌ Failed: <b>{failed}</b>",
            parse_mode=ParseMode.HTML,
        )
        return


# ------------------------------------------------------------
# Join request / greeting / approval
# ------------------------------------------------------------
async def process_join_request(bot, request_id, chat_id, user_id, auto_mode):
    # 1) Greeting is attempted immediately after the join request event.
    greeting_success = True
    with CACHE_LOCK:
        has_saved = bool(CACHED_MESSAGES)

    if has_saved:
        try:
            _, failed = await send_sequence_messages_instant(bot, user_id)
            greeting_success = failed == 0
        except Exception as exc:
            logger.warning("Greeting sequence failed for %s: %s", user_id, exc)
            greeting_success = False

        mark_greeting(request_id, greeting_success)

    # 2) Approval happens after greeting attempt.
    if auto_mode == "ON":
        try:
            await bot.approve_chat_join_request(
                chat_id=chat_id,
                user_id=user_id,
            )
            set_request_status(request_id, "approved")
            update_stat("accepted", 1)
            update_stat("pending", -1)
        except Exception as exc:
            logger.warning(
                "Auto approval failed for request %s / user %s: %s",
                request_id,
                user_id,
                exc,
            )
            # It remains pending in DB; admin can use manual controls.
    else:
        # Keep request pending. Admin gets Approve/Reject buttons.
        try:
            row = get_request(request_id)
            if row:
                _, _, _, username, first_name, *_ = row
                name = first_name or "Unknown"
                uname = f"@{username}" if username else "no username"
                await bot.send_message(
                    chat_id=ADMIN_ID,
                    text=(
                        "📥 <b>New Join Request</b>\n\n"
                        f"👤 {name}\n"
                        f"🔗 {uname}\n"
                        f"🆔 <code>{user_id}</code>\n"
                        f"📌 Request: <b>#{request_id}</b>\n\n"
                        "Greeting delivery is attempted. "
                        "Choose what to do with the request:"
                    ),
                    reply_markup=get_request_action_menu(request_id),
                    parse_mode=ParseMode.HTML,
                )
        except Exception as exc:
            logger.warning("Admin request notification failed: %s", exc)


async def join_request_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    request = update.chat_join_request
    if not request:
        return

    user_id = request.from_user.id
    chat_id = request.chat.id
    auto_mode = get_setting("auto_accept")

    request_id = upsert_join_request(chat_id, request.from_user)
    update_stat("total_requests", 1)
    update_stat("pending", 1)
    add_user(user_id)

    # Every join request is processed independently.
    asyncio.create_task(
        process_join_request(
            context.bot,
            request_id,
            chat_id,
            user_id,
            auto_mode,
        )
    )


# ------------------------------------------------------------
# Admin utility commands
# ------------------------------------------------------------
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return
    await update.message.reply_text(
        requests_text(),
        parse_mode=ParseMode.HTML,
    )


async def requests_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return

    rows = get_recent_requests(20)
    if not rows:
        await update.message.reply_text("No join requests yet.")
        return

    parts = ["<b>🧾 Last 20 Join Requests</b>\n"]
    for rid, uid, username, first_name, status, requested_at in rows:
        icon = {"pending": "🟡", "approved": "✅", "rejected": "❌"}.get(status, "•")
        parts.append(
            f"{icon} #{rid} | {first_name or 'Unknown'} | "
            f"<code>{uid}</code> | {status}\n"
        )
    await update.message.reply_text(
        "\n".join(parts),
        parse_mode=ParseMode.HTML,
    )


# ------------------------------------------------------------
# Error handler
# ------------------------------------------------------------
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Unhandled Telegram error: %s", context.error)


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------
def main():
    if not BOT_TOKEN or BOT_TOKEN == "8831391243:AAFNUMEngpQns6MQk3Hf9WZb9uBDuk_3mRw":
        raise RuntimeError("BOT_TOKEN set nahi hai.")

    if not ADMIN_ID or ADMIN_ID == 8767998937:
        raise RuntimeError("ADMIN_ID set nahi hai.")

    init_db()

    threading.Thread(
        target=run_health_server,
        daemon=True,
        name="health-server",
    ).start()

    if os.environ.get("RENDER_EXTERNAL_URL"):
        threading.Thread(
            target=self_ping_loop,
            daemon=True,
            name="self-ping",
        ).start()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("requests", requests_command))
    app.add_handler(CallbackQueryHandler(handle_callbacks))
    app.add_handler(ChatJoinRequestHandler(join_request_handler))
    app.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            content_handler,
        )
    )

    app.add_error_handler(error_handler)

    logger.info("JANEMAN BOT SUPPORT V22 PRO started.")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    )


if __name__ == "__main__":
    main()
    
