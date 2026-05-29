import logging
import json
import sys
import os
import sqlite3
import threading
import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ChatJoinRequestHandler, ContextTypes, MessageHandler, filters

# Setup logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# =================== [ CRITICAL CONFIGURATION ] ===================
BOT_TOKEN = "8519668511:AAGRSIALAvifSGxmKQwvggZnTIamiu7707Q" 
ADMIN_ID = 8767998937 
# ===================================================================

if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE" or ADMIN_ID == 123456789:
    print("\n❌ ERROR: Pehle apna BOT_TOKEN aur ADMIN_ID code me sahi se badlo!\n")
    sys.exit(1)

# --- GLOBAL LIVE MEMORY CACHE FOR ULTRA SPEED ---
# Yeh system database ka load 100% khatam karke direct RAM se message deliver karega
CACHED_MESSAGES = [] 
# ------------------------------------------------

# --- RENDER PORT BINDING CODES (STOPS CRASH) ---
class HealthCheckServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"Bot is Running 24/7 Deeply Active on Render!")

def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckServer)
    logging.info(f"🟢 Web Server started successfully on port {port}")
    server.serve_forever()

# SQLite Database Initialization
def init_db():
    global CACHED_MESSAGES
    conn = sqlite3.connect('janeman_pro.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS stats (key TEXT PRIMARY KEY, count INTEGER)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS messages_list (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, 
                        chat_id TEXT, 
                        msg_id TEXT
                    )''')

    cursor.execute("INSERT OR IGNORE INTO settings VALUES ('auto_accept', 'OFF')")
    cursor.execute("INSERT OR IGNORE INTO stats VALUES ('total_requests', 0)")
    cursor.execute("INSERT OR IGNORE INTO stats VALUES ('accepted', 0)")
    conn.commit()
    
    # Load messages directly into RAM on startup
    cursor.execute("SELECT chat_id, msg_id FROM messages_list ORDER BY id ASC")
    CACHED_MESSAGES = cursor.fetchall()
    
    conn.close()

# Fast Database Helpers
def get_setting(key):
    conn = sqlite3.connect('janeman_pro.db')
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key=?", (key,))
    res = cursor.fetchone()
    conn.close()
    return res[0] if res else "OFF"

def set_setting(key, value):
    conn = sqlite3.connect('janeman_pro.db')
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def add_saved_message(chat_id, msg_id):
    global CACHED_MESSAGES
    conn = sqlite3.connect('janeman_pro.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO messages_list (chat_id, msg_id) VALUES (?, ?)", (str(chat_id), str(msg_id)))
    conn.commit()
    # Instantly sync cache
    cursor.execute("SELECT chat_id, msg_id FROM messages_list ORDER BY id ASC")
    CACHED_MESSAGES = cursor.fetchall()
    conn.close()

def clear_saved_messages():
    global CACHED_MESSAGES
    conn = sqlite3.connect('janeman_pro.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM messages_list")
    conn.commit()
    CACHED_MESSAGES = []
    conn.close()

def add_user(user_id):
    conn = sqlite3.connect('janeman_pro.db')
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect('janeman_pro.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users

def get_stats():
    conn = sqlite3.connect('janeman_pro.db')
    cursor = conn.cursor()
    cursor.execute("SELECT key, count FROM stats")
    res = dict(cursor.fetchall())
    conn.close()
    return res

def update_stat(key, amount=1):
    conn = sqlite3.connect('janeman_pro.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE stats SET count = count + ? WHERE key=?", (amount, key))
    conn.commit()
    conn.close()

# Menu UI Generation
def get_main_menu():
    stats = get_stats()
    total_users = len(get_all_users())
    keyboard = [
        [InlineKeyboardButton(f"📊 Total Requests: {stats.get('total_requests', 0)}", callback_data="none")],
        [InlineKeyboardButton(f"✅ Auto-Approved: {stats.get('accepted', 0)}", callback_data="none")],
        [InlineKeyboardButton(f"👥 Database Users: {total_users}", callback_data="none")],
        [InlineKeyboardButton("⚙️ Welcome Settings", callback_data="welcome_settings"), InlineKeyboardButton("📣 Broadcast Tool", callback_data="broadcast_tool")],
        [InlineKeyboardButton("🔄 Refresh Panel", callback_data="refresh_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_welcome_menu():
    auto_status = get_setting("auto_accept")
    status_emoji = "🟢 ON (Auto Accept)" if auto_status == "ON" else "🔴 OFF (Manual/No Accept)"
    total_saved = len(CACHED_MESSAGES)
    keyboard = [
        [InlineKeyboardButton(f"Status: {status_emoji}", callback_data="toggle_auto")],
        [InlineKeyboardButton(f"➕ Add Message / Voice / Media", callback_data="edit_welcome")],
        [InlineKeyboardButton(f"🗑️ Clear All Saved ({total_saved})", callback_data="clear_welcome")],
        [InlineKeyboardButton("👁️ Test Sequence Message", callback_data="test_msg")],
        [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="refresh_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ⚡ LIVE RAM DELIVERY (0ms LAG) ⚡
async def send_sequence_messages_instant(bot, chat_id):
    if not CACHED_MESSAGES:
        return

    for row in CACHED_MESSAGES:
        s_chat_id, s_msg_id = row
        try:
            # Direct low-level payload forward
            await bot.copy_message(chat_id=chat_id, from_chat_id=int(s_chat_id), message_id=int(s_msg_id))
        except Exception as e:
            logging.error(f"⚠️ Fast Delivery skipped to {chat_id}: {e}")

# Command Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user:
        return
    add_user(update.effective_user.id)
    if update.effective_user.id != ADMIN_ID:
        return
        
    await update.message.reply_text("👑 **JANEMAN BOT SUPPORT V20 (RAM Boost Mode)** 👑\n\nAapka bot ab zero database lag par set hai. Request aate hi microsecond me deliver karega:", reply_markup=get_main_menu(), parse_mode="Markdown")

async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or query.from_user.id != ADMIN_ID:
        await query.answer("Access Denied!", show_alert=True)
        return
    await query.answer()

    if query.data == "refresh_main":
        await query.edit_message_text("👑 **JANEMAN BOT SUPPORT V20** 👑\n\nAapka panel ab memory cache par hyper-fast chal raha hai:", reply_markup=get_main_menu(), parse_mode="Markdown")

    elif query.data == "welcome_settings":
        auto_status = get_setting("auto_accept")
        total_saved = len(CACHED_MESSAGES)
        text = f"⚙️ **Welcome Sequence Settings**\n\n🔄 Auto Accept Status: **{auto_status}**\n📦 RAM-Cached Messages: **{total_saved}**\n\n⚡ *Engine Status: Hyperactive (0ms Delay)*"
        await query.edit_message_text(text, reply_markup=get_welcome_menu(), parse_mode="Markdown")

    elif query.data == "toggle_auto":
        current = get_setting("auto_accept")
        new_status = "ON" if current == "OFF" else "OFF"
        set_setting("auto_accept", new_status)
        total_saved = len(CACHED_MESSAGES)
        text = f"⚙️ **Welcome Sequence Settings**\n\n🔄 Auto Accept Status: **{new_status}**\n📦 RAM-Cached Messages: **{total_saved}**"
        await query.edit_message_text(text, reply_markup=get_welcome_menu(), parse_mode="Markdown")

    elif query.data == "edit_welcome":
        context.user_data['state'] = 'waiting_welcome'
        await query.edit_message_text("📝 **Apna Welcome Message/Voice/Media send karein:**\n\nEk ek karke bhejein. Finish karne par dubara `/start` type karein.")

    elif query.data == "clear_welcome":
        clear_saved_messages()
        auto_status = get_setting("auto_accept")
        text = f"🗑️ **Saare saved messages cache se saaf ho gaye!**\n\n🔄 Auto Accept Status: **{auto_status}**\n📦 RAM-Cached Messages: **0**"
        await query.edit_message_text(text, reply_markup=get_welcome_menu(), parse_mode="Markdown")

    elif query.data == "broadcast_tool":
        context.user_data['state'] = 'waiting_broadcast'
        await query.edit_message_text("📣 **Broadcast Post bhejein:**\n\nJo post sabhi users ko bhejni hai wo send karein. Cancel ke liye /start likhein.")

    elif query.data == "test_msg":
        await query.message.reply_text("⚡ *RAM sequence message trigger ho raha hai...*")
        await send_sequence_messages_instant(context.bot, ADMIN_ID)

async def content_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return
    state = context.user_data.get('state')
    if not state:
        return

    if state == 'waiting_welcome':
        add_saved_message(update.message.chat_id, update.message.message_id)
        total_saved = len(CACHED_MESSAGES)
        await update.message.reply_text(f"✅ Cache me update hua! (Total In-Memory: {total_saved})\nAur bhejna hai toh send karte rahiye, ya `/start` likhiye.")

    elif state == 'waiting_broadcast':
        context.user_data['state'] = None
        users = get_all_users()
        await update.message.reply_text(f"🚀 Broadcast Shuru! Total Users: {len(users)}")
        s, f = 0, 0
        for u_id in users:
            try:
                await context.bot.copy_message(chat_id=u_id, from_chat_id=update.message.chat_id, message_id=update.message.message_id)
                s += 1
            except Exception:
                f += 1
        await update.message.reply_text(f"🏁 Broadcast Complete!\n\n✅ Pass: {s}\n❌ Fail: {f}")

# 🔥 REAL-TIME LIGHTNING REFLEX DELIVERY 🔥
async def hyper_delivery_worker(bot, chat_id, user_id, auto_mode):
    # Action 1: RAM Cache se message seedha fire karo bina database ko touch kiye
    await send_sequence_messages_instant(bot, user_id)
    
    # Action 2: Baad me background me auto-accept system ko handle karo
    if auto_mode == "ON":
        try:
            await bot.approve_chat_join_request(chat_id=chat_id, user_id=user_id)
            update_stat('accepted', 1)
        except Exception:
            pass

async def join_request_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    request = update.chat_join_request
    if not request:
        return

    user_id = request.from_user.id
    chat_id = request.chat.id
    auto_mode = get_setting("auto_accept")

    # Fast counter background increments
    update_stat('total_requests', 1)
    add_user(user_id)

    # ⚡ Microsecond task dispatcher
    asyncio.create_task(hyper_delivery_worker(context.bot, chat_id, user_id, auto_mode))

def main():
    init_db()
    
    # Port binding for Render stability
    threading.Thread(target=run_health_server, daemon=True).start()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callbacks))
    app.add_handler(ChatJoinRequestHandler(join_request_handler))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, content_handler))
    
    print("\n🟢 VIP HYPER-SPEED MEMORY ENGINE ENGINE ONLINE! 🟢\n")
    app.run_polling()

if __name__ == '__main__':
    main()
    
