import logging
import os
import sqlite3
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatJoinRequestHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ============================================================
# JANEMAN BOT SUPPORT - FIXED BUTTON VERSION
# ============================================================
# IMPORTANT:
# 1) Put BOT_TOKEN in Render Environment Variables.
# 2) Put ADMIN_ID in Render Environment Variables.
# 3) Run only ONE copy/instance of this bot with polling.
# ============================================================

# Setup logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# =================== [ CRITICAL CONFIGURATION ] ===================
BOT_TOKEN = "8831391243:AAFNUMEngpQns6MQk3Hf9WZb9uBDuk_3mRw" 
ADMIN_ID = 8767998937
# ===================================================================

if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE" or ADMIN_ID == 123456789:
    print("\n❌ ERROR: Pehle apna BOT_TOKEN aur ADMIN_ID code me sahi se badlo!\n")
    sys.exit(1)

# --- GLOBAL LIVE MEMORY CACHE FOR ULTRA SPEED ---
CACHED_MESSAGES = [] 
# ------------------------------------------------

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("janeman_bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0").strip())
except ValueError:
    ADMIN_ID = 0

if not BOT_TOKEN or not ADMIN_ID:
    raise RuntimeError(
        "BOT_TOKEN and ADMIN_ID environment variables are required."
    )

DB_FILE = os.getenv("DB_FILE", "janeman_pro.db")

# Live RAM cache
CACHED_MESSAGES = []

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
        "(key TEXT PRIMARY KEY, count INTEGER NOT NULL DEFAULT 0)"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS users "
        "(user_id INTEGER PRIMARY KEY)"
    )
    cur.execute(
        """CREATE TABLE IF NOT EXISTS messages_list (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL,
            msg_id TEXT NOT NULL
        )"""
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

    cur.execute(
        "SELECT chat_id, msg_id FROM messages_list ORDER BY id ASC"
    )
    CACHED_MESSAGES = cur.fetchall()

    conn.commit()
    conn.close()

    logger.info("Database ready. Cached messages: %s", len(CACHED_MESSAGES))


def get_setting(key):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else "OFF"


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
    cur.execute(
        "SELECT chat_id, msg_id FROM messages_list ORDER BY id ASC"
    )
    CACHED_MESSAGES = cur.fetchall()
    conn.commit()
    conn.close()


def clear_saved_messages():
    global CACHED_MESSAGES

    conn = db_connect()
    conn.execute("DELETE FROM messages_list")
    conn.commit()
    conn.close()
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
    cur.execute("SELECT user_id FROM users")
    users = [row[0] for row in cur.fetchall()]
    conn.close()
    return users


def get_stats():
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT key, count FROM stats")
    result = dict(cur.fetchall())
    conn.close()
    return result


def update_stat(key, amount=1):
    conn = db_connect()
    conn.execute(
        "UPDATE stats SET count = count + ? WHERE key=?",
        (int(amount), key),
    )
    conn.commit()
    conn.close()


# ------------------------------------------------------------
# UI
# ------------------------------------------------------------
MAIN_TEXT = (
    "👑 <b>JANEMAN BOT SUPPORT V20</b> 👑\n\n"
    "⚡ Panel is online.\n"
    "Buttons are callback-enabled and ready."
)


def main_menu():
    stats = get_stats()
    total_users = len(get_all_users())

    keyboard = [
        [
            InlineKeyboardButton(
                f"📊 Total Requests: {stats.get('total_requests', 0)}",
                callback_data="noop",
            )
        ],
        [
            InlineKeyboardButton(
                f"✅ Auto-Approved: {stats.get('accepted', 0)}",
                callback_data="noop",
            )
        ],
        [
            InlineKeyboardButton(
                f"👥 Database Users: {total_users}",
                callback_data="noop",
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


def welcome_menu():
    status = get_setting("auto_accept")
    status_text = "🟢 ON (Auto Accept)" if status == "ON" else "🔴 OFF (Manual/No Accept)"

    keyboard = [
        [
            InlineKeyboardButton(
                f"Status: {status_text}",
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
                f"🗑️ Clear All Saved ({len(CACHED_MESSAGES)})",
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


async def safe_edit(query, text, markup):
    """Edit the existing Telegram panel safely."""
    try:
        await query.edit_message_text(
            text=text,
            reply_markup=markup,
            parse_mode="HTML",
        )
        return True

    except BadRequest as exc:
        msg = str(exc).lower()

        # Telegram returns this when the exact same content is edited.
        if "message is not modified" in msg:
            try:
                await query.edit_message_reply_markup(reply_markup=markup)
            except TelegramError:
                pass
            return True

        logger.exception("Telegram BadRequest while editing panel: %s", exc)
        return False

    except TelegramError as exc:
        logger.exception("Telegram error while editing panel: %s", exc)
        return False


async def answer_callback(query, text=None, alert=False):
    try:
        if text:
            await query.answer(text=text, show_alert=alert)
        else:
            await query.answer()
    except TelegramError:
        # Callback can expire; don't let that kill the handler.
        pass


# ------------------------------------------------------------
# Welcome sequence delivery
# ------------------------------------------------------------
async def send_sequence_messages(bot, target_chat_id):
    if not CACHED_MESSAGES:
        return 0, 0

    success = 0
    failed = 0

    for source_chat_id, source_message_id in list(CACHED_MESSAGES):
        try:
            await bot.copy_message(
                chat_id=target_chat_id,
                from_chat_id=int(source_chat_id),
                message_id=int(source_message_id),
            )
            success += 1
        except TelegramError as exc:
            failed += 1
            logger.warning(
                "Sequence delivery failed to %s: %s",
                target_chat_id,
                exc,
            )

    return success, failed


# ------------------------------------------------------------
# Commands
# ------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return

    add_user(update.effective_user.id)

    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Access denied.")
        return

    context.user_data["state"] = None

    await update.message.reply_text(
        MAIN_TEXT,
        reply_markup=main_menu(),
        parse_mode="HTML",
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return

    context.user_data["state"] = None
    await update.message.reply_text(
        "❌ Current action cancelled.",
        reply_markup=main_menu(),
        parse_mode="HTML",
    )


# ------------------------------------------------------------
# BUTTON HANDLER - FIXED
# ------------------------------------------------------------
async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if not query:
        return

    # ALWAYS answer the callback first so Telegram stops the loading spinner.
    if query.from_user.id != ADMIN_ID:
        await answer_callback(query, "Access Denied!", alert=True)
        return

    await answer_callback(query)

    data = query.data or ""
    logger.info("Button pressed: %s by %s", data, query.from_user.id)

    try:
        if data == "noop":
            return

        if data == "refresh_main":
            context.user_data["state"] = None
            await safe_edit(
                query,
                MAIN_TEXT,
                main_menu(),
            )
            return

        if data == "welcome_settings":
            context.user_data["state"] = None
            auto_status = get_setting("auto_accept")

            text = (
                "⚙️ <b>Welcome Sequence Settings</b>\n\n"
                f"🔄 Auto Accept Status: <b>{auto_status}</b>\n"
                f"📦 RAM-Cached Messages: <b>{len(CACHED_MESSAGES)}</b>\n\n"
                "⚡ Engine: Active"
            )

            await safe_edit(
                query,
                text,
                welcome_menu(),
            )
            return

        if data == "toggle_auto":
            current = get_setting("auto_accept")
            new_status = "ON" if current != "ON" else "OFF"
            set_setting("auto_accept", new_status)

            text = (
                "⚙️ <b>Welcome Sequence Settings</b>\n\n"
                f"🔄 Auto Accept Status: <b>{new_status}</b>\n"
                f"📦 RAM-Cached Messages: <b>{len(CACHED_MESSAGES)}</b>"
            )

            await safe_edit(
                query,
                text,
                welcome_menu(),
            )
            return

        if data == "edit_welcome":
            context.user_data["state"] = "waiting_welcome"

            await safe_edit(
                query,
                "📝 <b>Welcome Message / Voice / Media</b>\n\n"
                "Ab jo message save karna hai woh bhejo.\n"
                "Ek-ek karke multiple messages bhej sakte ho.\n\n"
                "➡️ Finish karne ke baad /start ya /cancel bhejo.",
                welcome_menu(),
            )
            return

        if data == "clear_welcome":
            clear_saved_messages()

            text = (
                "🗑️ <b>All saved welcome messages cleared.</b>\n\n"
                f"📦 RAM-Cached Messages: <b>{len(CACHED_MESSAGES)}</b>"
            )

            await safe_edit(
                query,
                text,
                welcome_menu(),
            )
            return

        if data == "broadcast_tool":
            context.user_data["state"] = "waiting_broadcast"

            await safe_edit(
                query,
                "📣 <b>Broadcast Tool</b>\n\n"
                "Ab jo post sabhi database users ko bhejni hai, "
                "woh yahin send karo.\n\n"
                "❌ Cancel: /cancel",
                main_menu(),
            )
            return

        if data == "test_msg":
            context.user_data["state"] = None

            await query.message.reply_text(
                "⚡ <b>Test sequence started...</b>",
                parse_mode="HTML",
            )

            success, failed = await send_sequence_messages(
                context.bot,
                ADMIN_ID,
            )

            await query.message.reply_text(
                f"🏁 <b>Test Complete</b>\n\n"
                f"✅ Sent: {success}\n"
                f"❌ Failed: {failed}",
                parse_mode="HTML",
            )
            return

        # Unknown callback: don't leave the user wondering.
        await answer_callback(
            query,
            "Unknown button action. Use /start again.",
            alert=True,
        )

    except Exception as exc:
        logger.exception("Button handler crashed for %s: %s", data, exc)

        try:
            await answer_callback(
                query,
                "Button error. Panel refreshed.",
                alert=True,
            )
        except Exception:
            pass

        try:
            await query.message.reply_text(
                "⚠️ <b>Button error caught.</b>\n"
                "Please use /start to reopen the panel.",
                parse_mode="HTML",
            )
        except Exception:
            pass


# ------------------------------------------------------------
# Text / media handler
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

        await update.message.reply_text(
            f"✅ Saved successfully.\n"
            f"📦 Total saved: {len(CACHED_MESSAGES)}\n\n"
            "Aur message/media bhejo, ya /start /cancel karo."
        )
        return

    if state == "waiting_broadcast":
        context.user_data["state"] = None

        users = get_all_users()

        await update.message.reply_text(
            f"🚀 <b>Broadcast started</b>\n"
            f"👥 Total users: {len(users)}",
            parse_mode="HTML",
        )

        sent = 0
        failed = 0

        for user_id in users:
            try:
                await context.bot.copy_message(
                    chat_id=user_id,
                    from_chat_id=update.message.chat_id,
                    message_id=update.message.message_id,
                )
                sent += 1

            except Forbidden:
                failed += 1

            except TelegramError as exc:
                failed += 1
                logger.warning(
                    "Broadcast failed for %s: %s",
                    user_id,
                    exc,
                )

        await update.message.reply_text(
            f"🏁 <b>Broadcast Complete</b>\n\n"
            f"✅ Sent: {sent}\n"
            f"❌ Failed: {failed}",
            parse_mode="HTML",
        )


# ------------------------------------------------------------
# Join request
# ------------------------------------------------------------
async def hyper_delivery_worker(bot, chat_id, user_id, auto_mode):
    # Send saved welcome sequence first.
    await send_sequence_messages(bot, user_id)

    if auto_mode == "ON":
        try:
            await bot.approve_chat_join_request(
                chat_id=chat_id,
                user_id=user_id,
            )
            update_stat("accepted", 1)

        except TelegramError as exc:
            logger.warning(
                "Could not approve %s in %s: %s",
                user_id,
                chat_id,
                exc,
            )


async def join_request_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    request = update.chat_join_request

    if not request:
        return

    user_id = request.from_user.id
    chat_id = request.chat.id
    auto_mode = get_setting("auto_accept")

    update_stat("total_requests", 1)
    add_user(user_id)

    # Fire-and-forget so join request isn't blocked by welcome copies.
    asyncio_task = context.application.create_task(
        hyper_delivery_worker(
            context.bot,
            chat_id,
            user_id,
            auto_mode,
        )
    )

    # Keep a reference through task registration handled by PTB.
    del asyncio_task


# ------------------------------------------------------------
# Render health server
# ------------------------------------------------------------
class HealthCheckServer(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"JANEMAN BOT is running."

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


def run_health_server():
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthCheckServer)

    logger.info("Health server listening on port %s", port)

    try:
        server.serve_forever()
    finally:
        server.server_close()


# ------------------------------------------------------------
# Optional Render self-ping
# ------------------------------------------------------------
def self_ping_loop():
    render_url = os.environ.get("RENDER_EXTERNAL_URL", "").strip()

    if not render_url:
        logger.info("RENDER_EXTERNAL_URL not set; self-ping disabled.")
        return

    logger.info("Self-ping enabled: %s", render_url)

    while True:
        try:
            time.sleep(30)

            req = urllib.request.Request(
                render_url,
                headers={"User-Agent": "JANEMAN-BOT-HealthCheck"},
               )

            with urllib.request.urlopen(req, timeout=8):
                pass

        except Exception as exc:
            logger.debug("Self-ping error: %s", exc)


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------
def main():
    init_db()

    # Web health server for Render.
    threading.Thread(
        target=run_health_server,
        daemon=True,
        name="health-server",
    ).start()

    # Optional self-ping.
    if os.environ.get("RENDER_EXTERNAL_URL"):
        threading.Thread(
            target=self_ping_loop,
            daemon=True,
            name="self-ping",
        ).start()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)
        .build()
    )

    # Commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cancel", cancel))

    # IMPORTANT: callback handler is registered explicitly for all panel buttons.
    application.add_handler(
        CallbackQueryHandler(
            handle_callbacks,
            pattern=r"^(noop|welcome_settings|broadcast_tool|refresh_main|"
                    r"toggle_auto|edit_welcome|clear_welcome|test_msg)$",
        )
    )

    # Join requests
    application.add_handler(
        ChatJoinRequestHandler(join_request_handler)
    )

    # Messages/media used by welcome and broadcast states.
    application.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            content_handler,
        )
    )

    logger.info("JANEMAN BOT V20 FIXED BUTTON VERSION is starting...")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    )


if __name__ == "__main__":
    main()
    
