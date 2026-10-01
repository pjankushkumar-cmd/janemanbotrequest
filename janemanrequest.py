import logging
import os
import sqlite3
import threading
import asyncio
import urllib.request
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
# JANEMAN BOT SUPPORT V21
# Fixed admin callback buttons + welcome + broadcast panel
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ============================================================
# 🔐 BOT CONFIGURATION — EDIT ONLY THESE 2 LINES
# ============================================================
# Yahin apna Telegram Bot Token aur Admin Telegram User ID paste karo.
# Example:
# BOT_TOKEN = "123456:ABCDEF..."
# ADMIN_ID = 123456789
#
# ⚠️ Token ko quotes (" ") ke andar rakhna hai.
# ⚠️ ADMIN_ID number hai, quotes ki zarurat nahi.
# ============================================================
BOT_TOKEN = "8831391243:AAFNUMEngpQns6MQk3Hf9WZb9uBDuk_3mRw"
ADMIN_ID = 8767998937
# ============================================================

DB_FILE = "janeman_pro.db"

# Live RAM cache
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
        self.wfile.write(b"JANEMAN BOT V21 is running.")

    def log_message(self, format, *args):
        return


def run_health_server():
    port = int(os.environ.get("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), HealthCheckServer)
    logger.info("Health server started on port %s", port)
    server.serve_forever()


# ------------------------------------------------------------
# Optional self-ping
# ------------------------------------------------------------
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
                headers={"User-Agent": "JANEMAN-BOT-HealthCheck/1.0"},
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

    cur.execute(
        "INSERT OR IGNORE INTO settings(key, value) VALUES('auto_accept', 'OFF')"
    )
    cur.execute(
        "INSERT OR IGNORE INTO stats(key, count) VALUES('total_requests', 0)"
    )
    cur.execute(
        "INSERT OR IGNORE INTO stats(key, count) VALUES('accepted', 0)"
    )

    conn.commit()

    cur.execute(
        "SELECT chat_id, msg_id FROM messages_list ORDER BY id ASC"
    )
    with CACHE_LOCK:
        CACHED_MESSAGES = cur.fetchall()

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
    cur = conn.cursor()
    cur.execute(
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
    conn.commit()

    cur.execute(
        "SELECT chat_id, msg_id FROM messages_list ORDER BY id ASC"
    )
    new_cache = cur.fetchall()
    conn.close()

    with CACHE_LOCK:
        CACHED_MESSAGES = new_cache


def clear_saved_messages():
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
        "UPDATE stats SET count = count + ? WHERE key=?",
        (int(amount), key),
    )
    conn.commit()
    conn.close()


# ------------------------------------------------------------
# UI helpers
# ------------------------------------------------------------
def main_text():
    return (
        "<b>👑 JANEMAN BOT SUPPORT V21 👑</b>\n\n"
        "Admin Control Panel\n"
        "⚡ Fast RAM cache + SQLite storage\n"
        "👇 Neeche se koi option select karein."
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
        "➕ Add par click karke message/voice/media save karein.\n"
        "👁️ Test se admin chat me saved sequence check karein."
    )


def broadcast_text():
    users = get_all_users()
    return (
        "<b>📣 Broadcast Tool</b>\n\n"
        f"👥 Database Users: <b>{len(users)}</b>\n\n"
        "📩 Ab jo message/media bhejoge, woh database users ko "
        "broadcast kiya jayega.\n\n"
        "❌ Cancel ke liye button dabao."
    )


def get_main_menu():
    stats = get_stats()
    total_users = len(get_all_users())

    keyboard = [
        [
            InlineKeyboardButton(
                f"📊 Total Requests: {stats.get('total_requests', 0)}",
                callback_data="none",
            )
        ],
        [
            InlineKeyboardButton(
                f"✅ Auto-Approved: {stats.get('accepted', 0)}",
                callback_data="none",
            )
        ],
        [
            InlineKeyboardButton(
                f"👥 Database Users: {total_users}",
                callback_data="none",
            )
        ],
        [
            InlineKeyboardButton(
                "⚙️ Welcome Settings",
                callback_data="welcome_settings",
            ),
            InlineKeyboardButton(
                "📣 Broadcast Tool",
                callback_data="broadcast_tool",
            ),
        ],
        [
            InlineKeyboardButton(
                "🔄 Refresh Panel",
                callback_data="refresh_main",
            )
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_welcome_menu():
    auto_status = get_setting("auto_accept")
    status = "🟢 ON" if auto_status == "ON" else "🔴 OFF"

    with CACHE_LOCK:
        total_saved = len(CACHED_MESSAGES)

    keyboard = [
        [
            InlineKeyboardButton(
                f"🔄 Auto Accept: {status}",
                callback_data="toggle_auto",
            )
        ],
        [
            InlineKeyboardButton(
                "➕ Add Message / Voice / Media",
                callback_data="edit_welcome",
            )
        ],
        [
            InlineKeyboardButton(
                f"🗑️ Clear All Saved ({total_saved})",
                callback_data="clear_welcome",
            )
        ],
        [
            InlineKeyboardButton(
                "👁️ Test Sequence Message",
                callback_data="test_msg",
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ Back to Main Menu",
                callback_data="refresh_main",
            )
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_broadcast_menu():
    keyboard = [
        [
            InlineKeyboardButton(
                "📩 Send Broadcast",
                callback_data="start_broadcast",
            )
        ],
        [
            InlineKeyboardButton(
                "❌ Cancel",
                callback_data="cancel_action",
            ),
            InlineKeyboardButton(
                "🔄 Refresh",
                callback_data="broadcast_tool",
            ),
        ],
        [
            InlineKeyboardButton(
                "⬅️ Main Menu",
                callback_data="refresh_main",
            )
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


# ------------------------------------------------------------
# Telegram message helpers
# ------------------------------------------------------------
async def safe_edit(query, text, reply_markup=None):
    """Edit the panel without letting Telegram edit errors kill callbacks."""
    try:
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML,
        )
        return True
    except Exception as exc:
        logger.exception("Panel edit failed: %s", exc)

        # If the message is not editable/was already changed, send a new panel.
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

    # /start always returns the admin to the main panel.
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
# This is the main fix for the buttons.
# ------------------------------------------------------------
async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if query is None:
        return

    # Always acknowledge the callback quickly so Telegram does not keep
    # the button in the loading state.
    try:
        await query.answer()
    except Exception:
        logger.exception("Could not answer callback query")

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
            # Statistics buttons are display-only.
            try:
                await query.answer("Ye sirf stats display ke liye hai.")
            except Exception:
                pass
            return

        if data == "refresh_main":
            context.user_data["state"] = None
            await safe_edit(
                query,
                main_text(),
                get_main_menu(),
            )
            return

        if data == "welcome_settings":
            context.user_data["state"] = None
            await safe_edit(
                query,
                welcome_text(),
                get_welcome_menu(),
            )
            return

        if data == "toggle_auto":
            current = get_setting("auto_accept")
            new_status = "OFF" if current == "ON" else "ON"
            set_setting("auto_accept", new_status)
            context.user_data["state"] = None

            await safe_edit(
                query,
                welcome_text(),
                get_welcome_menu(),
            )
            return

        if data == "edit_welcome":
            context.user_data["state"] = "waiting_welcome"
            await safe_edit(
                query,
                "<b>📝 Add Welcome Message / Voice / Media</b>\n\n"
                "Ab message, voice, photo, video ya document bhejo.\n"
                "Har message save hoga.\n\n"
                "✅ Save karne ke baad aur message bhej sakte ho.\n"
                "⬅️ Panel par wapas aane ke liye /start bhejo.",
                get_welcome_menu(),
            )
            return

        if data == "clear_welcome":
            clear_saved_messages()
            context.user_data["state"] = None

            await safe_edit(
                query,
                "<b>🗑️ Saved Welcome Messages Cleared</b>\n\n"
                "📦 Saved Messages: <b>0</b>",
                get_welcome_menu(),
            )
            return

        if data == "test_msg":
            context.user_data["state"] = None

            with CACHE_LOCK:
                total = len(CACHED_MESSAGES)

            if total == 0:
                try:
                    await query.answer(
                        "Pehle Welcome Settings me message save karo.",
                        show_alert=True,
                    )
                except Exception:
                    pass
                return

            success, failed = await send_sequence_messages_instant(
                context.bot,
                ADMIN_ID,
            )

            try:
                await query.message.reply_text(
                    f"👁️ <b>Test Complete</b>\n\n"
                    f"📦 Saved: <b>{total}</b>\n"
                    f"✅ Sent: <b>{success}</b>\n"
                    f"❌ Failed: <b>{failed}</b>",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                logger.exception("Could not send test result")
            return

        if data == "broadcast_tool":
            context.user_data["state"] = None
            await safe_edit(
                query,
                broadcast_text(),
                get_broadcast_menu(),
            )
            return

        if data == "start_broadcast":
            context.user_data["state"] = "waiting_broadcast"

            await safe_edit(
                query,
                "<b>📣 Broadcast Ready</b>\n\n"
                "Ab ek message/media bhejo.\n"
                "Wahi message database ke users ko copy kiya jayega.\n\n"
                "❌ Cancel karne ke liye Cancel button dabao.",
                InlineKeyboardMarkup(
                    [[
                        InlineKeyboardButton(
                            "❌ Cancel",
                            callback_data="cancel_action",
                        )
                    ]]
                ),
            )
            return

        if data == "cancel_action":
            context.user_data["state"] = None

            await safe_edit(
                query,
                main_text(),
                get_main_menu(),
            )
            return

        # Unknown callback: do not silently fail.
        logger.warning("Unknown callback_data received: %r", data)
        try:
            await query.answer("Unknown button action.", show_alert=True)
        except Exception:
            pass

    except Exception as exc:
        # This prevents one bad callback from making the whole panel appear dead.
        logger.exception("Callback handler error for %r: %s", data, exc)

        try:
            await query.message.reply_text(
                "❌ <b>Button Error</b>\n\n"
                "Action: <code>"
                + str(data).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                + "</code>\n"
                "Error server log me record ho gaya hai.",
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
        add_saved_message(
            update.message.chat_id,
            update.message.message_id,
        )

        with CACHE_LOCK:
            total_saved = len(CACHED_MESSAGES)

        await update.message.reply_text(
            f"✅ <b>Welcome message saved!</b>\n\n"
            f"📦 Total Saved: <b>{total_saved}</b>\n\n"
            "Aur message/media bhejo, ya /start se panel kholo.",
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
                logger.warning(
                    "Broadcast failed for %s: %s",
                    user_id,
                    exc,
                )

        await update.message.reply_text(
            f"🏁 <b>Broadcast Complete</b>\n\n"
            f"✅ Sent: <b>{success}</b>\n"
            f"❌ Failed: <b>{failed}</b>",
            parse_mode=ParseMode.HTML,
        )
        return


# ------------------------------------------------------------
# Join request / auto accept
# ------------------------------------------------------------
async def hyper_delivery_worker(bot, chat_id, user_id, auto_mode):
    try:
        await send_sequence_messages_instant(bot, user_id)

        if auto_mode == "ON":
            try:
                await bot.approve_chat_join_request(
                    chat_id=chat_id,
                    user_id=user_id,
                )
                update_stat("accepted", 1)
            except Exception as exc:
                logger.warning(
                    "Join request approval failed for %s: %s",
                    user_id,
                    exc,
                )

    except Exception as exc:
        logger.exception("Delivery worker error: %s", exc)


async def join_request_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    request = update.chat_join_request

    if not request:
        return

    user_id = request.from_user.id
    chat_id = request.chat.id
    auto_mode = get_setting("auto_accept")

    update_stat("total_requests", 1)
    add_user(user_id)

    asyncio.create_task(
        hyper_delivery_worker(
            context.bot,
            chat_id,
            user_id,
            auto_mode,
        )
    )


# ------------------------------------------------------------
# Error handler
# ------------------------------------------------------------
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception(
        "Unhandled Telegram error: %s",
        context.error,
    )


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------
def main():
    if not BOT_TOKEN or BOT_TOKEN == "PASTE_YOUR_BOT_TOKEN_HERE":
        raise RuntimeError(
            "BOT_TOKEN set nahi hai. File ke CONFIGURATION section me apna bot token paste karo."
        )

    if not ADMIN_ID or ADMIN_ID == 123456789:
        raise RuntimeError(
            "ADMIN_ID set nahi hai. File ke CONFIGURATION section me apni Telegram numeric ID paste karo."
        )

    init_db()

    # Render health server
    threading.Thread(
        target=run_health_server,
        daemon=True,
        name="health-server",
    ).start()

    # Optional self-ping
    if os.environ.get("RENDER_EXTERNAL_URL"):
        threading.Thread(
            target=self_ping_loop,
            daemon=True,
            name="self-ping",
        ).start()

    app = Application.builder().token(BOT_TOKEN).build()

    # ORDER IS IMPORTANT:
    # callback queries are handled separately from normal messages.
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callbacks))
    app.add_handler(ChatJoinRequestHandler(join_request_handler))
    app.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            content_handler,
        )
    )

    app.add_error_handler(error_handler)

    logger.info("JANEMAN BOT SUPPORT V21 started.")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    )


if __name__ == "__main__":
    main()
        
