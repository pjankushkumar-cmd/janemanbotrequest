import logging
import json
import sys
import os
import sqlite3
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

# SQLite Database Initialization (FIXED: AUTOINCREMENT Syntax Error Solved)
def init_db():
    conn = sqlite3.connect('janeman_pro.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS stats (key TEXT PRIMARY KEY, count INTEGER)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)''')
    
    # Render aur SQLite me hamesha AUTOINCREMENT hota hai (AUTO_INCREMENT nahi)
    cursor.execute('''CREATE TABLE IF NOT EXISTS messages_list (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, 
                        chat_id TEXT, 
                        msg_id TEXT
                    )''')

    cursor.execute("INSERT OR IGNORE INTO settings VALUES ('auto_accept', 'OFF')")
    cursor.execute("INSERT OR IGNORE INTO stats VALUES ('total_requests', 0)")
    cursor.execute("INSERT OR IGNORE INTO stats VALUES ('accepted', 0)")
    conn.commit()
    conn.close()

# Database helper functions
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
    conn = sqlite3.connect('janeman_pro.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO messages_list (chat_id, msg_id) VALUES (?, ?)", (str(chat_id), str(msg_id)))
    conn.commit()
    conn.close()

def clear_saved_messages():
    conn = sqlite3.connect('janeman_pro.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM messages_list")
    conn.commit()
    conn.close()

def get_all_saved_messages():
    conn = sqlite3.connect('janeman_pro.db')
    cursor = conn.cursor()
    cursor.execute("SELECT chat_id, msg_id FROM messages_list ORDER BY id ASC")
    rows = cursor.fetchall()
    conn.close()
    return rows

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
    total_saved = len(get_all_saved_messages())
    keyboard = [
        [InlineKeyboardButton(f"Status: {status_emoji}", callback_data="toggle_auto")],
        [InlineKeyboardButton(f"➕ Add Message / Voice / Media", callback_data="edit_welcome")],
        [InlineKeyboardButton(f"🗑️ Clear All Saved ({total_saved})", callback_data="clear_welcome")],
        [InlineKeyboardButton("👁️ Test Sequence Message", callback_data="test_msg")],
        [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="refresh_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def send_sequence_messages(bot, chat_id):
    saved_messages = get_all_saved_messages()
    if not saved_messages:
        try:
            await bot.send_message(chat_id=chat_id, text="👋 Aapki join request received ho gayi hai!")
        except Exception:
            pass
        return

    for row in saved_messages:
        s_chat_id, s_msg_id = row
        try:
            # VIP Direct Copy Method - Fast & Reliable
            await bot.copy_message(chat_id=chat_id, from_chat_id=int(s_chat_id), message_id=int(s_msg_id))
        except Exception as e:
            logging.error(f"Copy message failed in sequence: {e}")

# Command Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user:
        return
    add_user(update.effective_user.id)
    if update.effective_user.id != ADMIN_ID:
        return
        
    await update.message.reply_text("👑 **JANEMAN BOT SUPPORT V10** 👑\n\nAapka swagat hai admin! Panel bilkul tayyar hai:", reply_markup=get_main_menu(), parse_mode="Markdown")

async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or query.from_user.id != ADMIN_ID:
        await query.answer("Access Denied!", show_alert=True)
        return
    await query.answer()

    if query.data == "refresh_main":
        await query.edit_message_text("👑 **JANEMAN BOT SUPPORT V10** 👑\n\nAapka swagat hai admin! Panel refreshed:", reply_markup=get_main_menu(), parse_mode="Markdown")

    elif query.data == "welcome_settings":
        auto_status = get_setting("auto_accept")
        total_saved = len(get_all_saved_messages())
        text = f"⚙️ **Welcome Sequence Settings**\n\n🔄 Auto Accept Status: **{auto_status}**\n📦 Total Messages Added: **{total_saved}**"
        await query.edit_message_text(text, reply_markup=get_welcome_menu(), parse_mode="Markdown")

    elif query.data == "toggle_auto":
        current = get_setting("auto_accept")
        new_status = "ON" if current == "OFF" else "OFF"
        set_setting("auto_accept", new_status)
        total_saved = len(get_all_saved_messages())
        text = f"⚙️ **Welcome Sequence Settings**\n\n🔄 Auto Accept Status: **{new_status}**\n📦 Total Messages Added: **{total_saved}**"
        await query.edit_message_text(text, reply_markup=get_welcome_menu(), parse_mode="Markdown")

    elif query.data == "edit_welcome":
        context.user_data['state'] = 'waiting_welcome'
        await query.edit_message_text("📝 **Apna Welcome Message/Voice/Media send karein:**\n\nEk ek karke bhejein. Finish karne par dubara `/start` type karein.")

    elif query.data == "clear_welcome":
        clear_saved_messages()
        auto_status = get_setting("auto_accept")
        text = f"🗑️ **Saare saved messages clear ho gaye!**\n\n🔄 Auto Accept Status: **{auto_status}**\n📦 Total Messages Added: **0**"
        await query.edit_message_text(text, reply_markup=get_welcome_menu(), parse_mode="Markdown")

    elif query.data == "broadcast_tool":
        context.user_data['state'] = 'waiting_broadcast'
        await query.edit_message_text("📣 **Broadcast Post bhejein:**\n\nJo post sabhi users ko bhejni hai wo send karein. Cancel ke liye /start likhein.")

    elif query.data == "test_msg":
        await query.message.reply_text("🔄 *Test sequence deliver ho raha hai...*")
        try:
            await send_sequence_messages(context.bot, ADMIN_ID)
        except Exception as e:
            await query.message.reply_text(f"❌ Error: {e}")

async def content_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return
    state = context.user_data.get('state')
    if not state:
        return

    if state == 'waiting_welcome':
        add_saved_message(update.message.chat_id, update.message.message_id)
        total_saved = len(get_all_saved_messages())
        await update.message.reply_text(f"✅ Added to sequence! (Total: {total_saved})\nAur bhejna hai toh send karte rahiye, ya `/start` likhiye.")

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

async def join_request_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    request = update.chat_join_request
    chat = request.chat
    user = request.from_user

    update_stat('total_requests', 1)
    add_user(user.id)

    auto_mode = get_setting("auto_accept")

    if auto_mode == "ON":
        try:
            await context.bot.approve_chat_join_request(chat_id=chat.id, user_id=user.id)
            update_stat('accepted', 1)
            await send_sequence_messages(context.bot, user.id)
        except Exception as e:
            logging.error(f"Error in auto_accept: {e}")
    else:
        try:
            await send_sequence_messages(context.bot, user.id)
        except Exception as e:
            logging.error(f"Error in manual_accept notification: {e}")

def main():
    init_db()
    
    port = int(os.environ.get("PORT", 8080))
    render_url = os.environ.get("RENDER_EXTERNAL_URL")

    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callbacks))
    app.add_handler(ChatJoinRequestHandler(join_request_handler))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, content_handler))
    
    if render_url:
        print(f"\n🚀 WEBHOOK ENGINE STARTED ON: {render_url}\n")
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=BOT_TOKEN,
            webhook_url=f"{render_url}/{BOT_TOKEN}"
        )
    else:
        print("\n🟢 LOCAL POLLING STARTED (Termux Test Mode Active) 🟢\n")
        app.run_polling()

if __name__ == '__main__':
    main()
    
