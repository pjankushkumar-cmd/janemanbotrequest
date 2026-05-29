import logging
import json
import sys
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ChatJoinRequestHandler, ContextTypes, MessageHandler, filters

# Setup logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# =================== [ CRITICAL CONFIGURATION ] ===================
BOT_TOKEN = "8519668511:AAGRSIALAvifSGxmKQwvggZnTIamiu7707Q" 
ADMIN_ID = 8767998937 
# ===================================================================

# In-Memory Storage (Render restart hone par yeh khali ho jayega, par niche diye gaye step se hum iska backup handle karenge)
SAVED_MESSAGES = [] 
AUTO_ACCEPT_STATUS = "OFF"
TOTAL_REQUESTS = 0
ACCEPTED_REQUESTS = 0
DATABASE_USERS = set([ADMIN_ID])

if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE" or ADMIN_ID == 123456789:
    print("\n❌ ERROR: Pehle apna BOT_TOKEN aur ADMIN_ID code me sahi se badlo, tabhi admin panel chalega!\n")
    sys.exit(1)

# --- RENDER PORT BINDING CODES (FREE TIER COMPATIBLE) ---
class HealthCheckServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"Bot is Running Perfectly on Render Free Tier!")

def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckServer)
    logging.info(f"🟢 Web Server started on port {port} for Render Free Tier.")
    server.serve_forever()
# --------------------------------------------------------

def get_main_menu():
    global TOTAL_REQUESTS, ACCEPTED_REQUESTS, DATABASE_USERS
    keyboard = [
        [InlineKeyboardButton(f"📊 Total Requests: {TOTAL_REQUESTS}", callback_data="none")],
        [InlineKeyboardButton(f"✅ Auto-Approved: {ACCEPTED_REQUESTS}", callback_data="none")],
        [InlineKeyboardButton(f"👥 Database Users: {len(DATABASE_USERS)}", callback_data="none")],
        [InlineKeyboardButton("⚙️ Welcome Settings", callback_data="welcome_settings"), InlineKeyboardButton("📣 Broadcast Tool", callback_data="broadcast_tool")],
        [InlineKeyboardButton("🔄 Refresh Panel", callback_data="refresh_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_welcome_menu():
    global AUTO_ACCEPT_STATUS, SAVED_MESSAGES
    status_emoji = "🟢 ON (Auto Accept)" if AUTO_ACCEPT_STATUS == "ON" else "🔴 OFF (Manual/No Accept)"
    keyboard = [
        [InlineKeyboardButton(f"Status: {status_emoji}", callback_data="toggle_auto")],
        [InlineKeyboardButton(f"➕ Add Message / Voice / Media", callback_data="edit_welcome")],
        [InlineKeyboardButton(f"🗑️ Clear All Saved ({len(SAVED_MESSAGES)})", callback_data="clear_welcome")],
        [InlineKeyboardButton("👁️ Test Sequence Message", callback_data="test_msg")],
        [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="refresh_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def send_sequence_messages(bot, chat_id):
    global SAVED_MESSAGES
    if not SAVED_MESSAGES:
        await bot.send_message(chat_id=chat_id, text="👋 Aapki join request received ho gayi hai!")
        return

    for msg_data in SAVED_MESSAGES:
        try:
            # VIP Copy Method: Isse direct deliver hoga bina kisi database dependencies ke
            await bot.copy_message(chat_id=chat_id, from_chat_id=int(msg_data['chat_id']), message_id=int(msg_data['msg_id']))
        except Exception as e:
            logging.error(f"Copy message failed in sequence: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user:
        return
    DATABASE_USERS.add(update.effective_user.id)
    if update.effective_user.id != ADMIN_ID:
        return
        
    await update.message.reply_text("👑 **PRO Admin Control Panel v5 (No-Disk Render Ready)** 👑\n\nAapka swagat hai admin! Ab aap bina kisi Render disk ke is bot ko free me chala sakte hain:", reply_markup=get_main_menu(), parse_mode="Markdown")

async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global AUTO_ACCEPT_STATUS, SAVED_MESSAGES
    query = update.callback_query
    if not query or query.from_user.id != ADMIN_ID:
        await query.answer("Access Denied!", show_alert=True)
        return
    await query.answer()

    if query.data == "refresh_main":
        await query.edit_message_text("👑 **PRO Admin Control Panel v5** 👑\n\nAapka swagat hai admin! Sabhi functions niche se control karein:", reply_markup=get_main_menu(), parse_mode="Markdown")

    elif query.data == "welcome_settings":
        text = f"⚙️ **Welcome Sequence Settings**\n\n🔄 Auto Accept Status: **{AUTO_ACCEPT_STATUS}**\n📦 Total Messages Added in Sequence: **{len(SAVED_MESSAGES)}**\n\n📌 *Note: Render Free tier par bot restart hone par aapko ek baar dubara messages set karne pad sakte hain agar bot lambe samay tak band rahe.*"
        await query.edit_message_text(text, reply_markup=get_welcome_menu(), parse_mode="Markdown")

    elif query.data == "toggle_auto":
        AUTO_ACCEPT_STATUS = "ON" if AUTO_ACCEPT_STATUS == "OFF" else "OFF"
        text = f"⚙️ **Welcome Sequence Settings**\n\n🔄 Auto Accept Status: **{AUTO_ACCEPT_STATUS}**\n📦 Total Messages Added in Sequence: **{len(SAVED_MESSAGES)}**"
        await query.edit_message_text(text, reply_markup=get_welcome_menu(), parse_mode="Markdown")

    elif query.data == "edit_welcome":
        context.user_data['state'] = 'waiting_welcome'
        await query.edit_message_text("📝 **Apna Welcome Message/Voice Note/Media bhejein:**\n\nJo bhi message sequence me add karna hai ek-ek karke send kijiye. Rokne ke liye `/start` likhein.")

    elif query.data == "clear_welcome":
        SAVED_MESSAGES.clear()
        text = f"🗑️ **Saare saved messages delete kar diye gaye hain!**\n\n🔄 Auto Accept Status: **{AUTO_ACCEPT_STATUS}**\n📦 Total Messages Added in Sequence: **0**"
        await query.edit_message_text(text, reply_markup=get_welcome_menu(), parse_mode="Markdown")

    elif query.data == "broadcast_tool":
        context.user_data['state'] = 'waiting_broadcast'
        await query.edit_message_text("📣 **Broadcast Post bhejein:**\n\nJo bhi post sabhi users ko bhejni hai, use send karein. Cancel ke liye /start likhein.")

    elif query.data == "test_msg":
        await query.message.reply_text("🔄 *Test sequence aapko niche deliver kiya ja raha hai...*")
        try:
            await send_sequence_messages(context.bot, ADMIN_ID)
        except Exception as e:
            await query.message.reply_text(f"❌ Error: {e}")

async def content_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global SAVED_MESSAGES, DATABASE_USERS
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return
    state = context.user_data.get('state')
    if not state:
        return

    if state == 'waiting_welcome':
        # Direct message metadata memory me save ho rhi h
        SAVED_MESSAGES.append({
            "chat_id": str(update.message.chat_id),
            "msg_id": str(update.message.message_id)
        })
        await update.message.reply_text(f"✅ Message sequence mein add ho gaya! (Total Added: {len(SAVED_MESSAGES)})\n\nAap aur bhi voice/media bhej sakte hain, ya panel par wapas jaane ke liye `/start` likhein.")

    elif state == 'waiting_broadcast':
        context.user_data['state'] = None
        await update.message.reply_text(f"🚀 Broadcast Shuru! Total Users: {len(DATABASE_USERS)}")
        s, f = 0, 0
        for u_id in DATABASE_USERS:
            try:
                await context.bot.copy_message(chat_id=u_id, from_chat_id=update.message.chat_id, message_id=update.message.message_id)
                s += 1
            except Exception: 
                f += 1
        await update.message.reply_text(f"🏁 Broadcast Complete!\n\n✅ Pass: {s}\n❌ Fail: {f}")

async def join_request_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global TOTAL_REQUESTS, ACCEPTED_REQUESTS, AUTO_ACCEPT_STATUS, DATABASE_USERS
    request = update.chat_join_request
    chat = request.chat
    user = request.from_user

    TOTAL_REQUESTS += 1
    DATABASE_USERS.add(user.id)

    if AUTO_ACCEPT_STATUS == "ON":
        try:
            await context.bot.approve_chat_join_request(chat_id=chat.id, user_id=user.id)
            ACCEPTED_REQUESTS += 1
            await send_sequence_messages(context.bot, user.id)
        except Exception as e:
            logging.error(f"Error in auto_accept: {e}")
    else:
        try:
            await send_sequence_messages(context.bot, user.id)
        except Exception as e:
            logging.error(f"Error in manual_accept notification: {e}")

def main():
    # Render dummy server start
    threading.Thread(target=run_health_server, daemon=True).start()
    
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callbacks))
    app.add_handler(ChatJoinRequestHandler(join_request_handler))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, content_handler))
    
    print("\n🟢 NO-DISK RENDER BOT STARTED SUCCESSFULLY! 🟢\n")
    app.run_polling()

if __name__ == '__main__':
    main()
    
