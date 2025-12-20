import os
import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta
from threading import Thread
from flask import Flask
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ChatJoinRequest

# ==================== 1. AYARLAR (RENDER'DAN ALIR) ====================
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))  # Senin ID'n

# ==================== 2. WEB SERVER (7/24 AKTİFLİK İÇİN) ====================
logging.basicConfig(level=logging.INFO)
logging.getLogger("pyrogram").setLevel(logging.WARNING)
app = Flask(__name__)

@app.route('/')
def home(): return "YaelManager V46 (Full) Active! 🟢"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = Thread(target=run_web)
    t.daemon = True
    t.start()

# ==================== 3. VERİTABANI & SİSTEM ====================
DB_NAME = "bot_data.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # Kullanıcı Lisansları
    c.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, status TEXT, join_date TEXT)''')
    # Ayarlar (Kanal ID, Oto Onay vs.)
    c.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
    # Zamanlayıcı Kuyruğu
    c.execute('''CREATE TABLE IF NOT EXISTS scheduled_posts 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  user_id INTEGER, channel_id INTEGER, 
                  message_id INTEGER, run_time TEXT)''')
    conn.commit()
    conn.close()

# --- DB Yardımcıları ---
def get_setting(key):
    with sqlite3.connect(DB_NAME) as conn:
        res = conn.cursor().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return res[0] if res else None

def set_setting(key, value):
    with sqlite3.connect(DB_NAME) as conn:
        conn.cursor().execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))

def add_schedule(user_id, channel_id, message_id, run_time):
    with sqlite3.connect(DB_NAME) as conn:
        conn.cursor().execute("INSERT INTO scheduled_posts (user_id, channel_id, message_id, run_time) VALUES (?, ?, ?, ?)", 
                              (user_id, channel_id, message_id, run_time.isoformat()))

def get_due_posts():
    posts = []
    with sqlite3.connect(DB_NAME) as conn:
        now = datetime.now().isoformat()
        cursor = conn.cursor()
        rows = cursor.execute("SELECT * FROM scheduled_posts WHERE run_time <= ?", (now,)).fetchall()
        for row in rows:
            posts.append(row)
            cursor.execute("DELETE FROM scheduled_posts WHERE id=?", (row[0],))
        conn.commit()
    return posts

# --- Lisans Kontrolü ---
def check_user_access(user_id):
    if user_id == OWNER_ID: return True, "👑 Yönetici (Sınırsız)"
    conn = sqlite3.connect(DB_NAME)
    res = conn.cursor().execute("SELECT status, join_date FROM users WHERE user_id=?", (user_id,)).fetchone()
    
    if not res: # Yeni kullanıcı
        now = datetime.now().isoformat()
        conn.cursor().execute("INSERT INTO users VALUES (?, 'FREE', ?)", (user_id, now))
        conn.commit(); conn.close()
        return True, "🟢 Deneme (24 Saat)"
    
    status, join_str = res
    conn.close()
    
    if status == "VIP": return True, "💎 VIP Üye (Sınırsız)"
    
    # 24 Saat Kontrolü
    join_date = datetime.fromisoformat(join_str)
    if datetime.now() < join_date + timedelta(hours=24): return True, "🟢 Deneme Sürümü"
    return False, "🔴 Süre Doldu"

def set_vip(user_id, is_vip):
    status = "VIP" if is_vip else "FREE"
    with sqlite3.connect(DB_NAME) as conn:
        try: conn.cursor().execute("INSERT INTO users VALUES (?, ?, ?)", (user_id, status, datetime.now().isoformat()))
        except: conn.cursor().execute("UPDATE users SET status=? WHERE user_id=?", (status, user_id))

# ==================== 4. İSTEMCİ ====================
init_db()
bot = Client("manager_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True)

# ==================== 5. MENÜLER (HİÇBİRİ EKSİK DEĞİL) ====================
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💣 Süreli Mesaj", callback_data="info_flash"),
         InlineKeyboardButton("⏳ Zamanlayıcı", callback_data="info_schedule")],
        [InlineKeyboardButton("🔘 Butonlu Post", callback_data="info_buton"),
         InlineKeyboardButton("📢 Direkt Post", callback_data="info_post")],
        [InlineKeyboardButton("🔐 Oto Onay", callback_data="info_approve"),
         InlineKeyboardButton("👤 Hesabım", callback_data="info_account")],
        [InlineKeyboardButton("🛠 İsteğe Özel Bot Yaptır (@yasin33)", url="https://t.me/yasin33")]
    ])

def back_btn(): return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ana Menü", callback_data="main")]])

# ==================== 6. KOMUTLAR VE FONKSİYONLAR ====================

@bot.on_message(filters.command("start") & filters.private)
async def start(client, message):
    _, status = check_user_access(message.from_user.id)
    await message.reply(f"👋 **Kanal Yönetim Asistanı**\nℹ️ Durum: {status}", reply_markup=main_menu())

@bot.on_callback_query()
async def cb_handler(client, cb):
    if cb.data == "main":
        await cb.message.edit_text("👋 **Ana Menü**", reply_markup=main_menu())
        
    elif cb.data == "info_flash":
        await cb.message.edit_text("💣 **Süreli Mesaj:**\nYanıtla -> `/flash 30` (30 saniye sonra siler).", reply_markup=back_btn())
        
    elif cb.data == "info_schedule":
        await cb.message.edit_text("⏳ **Zamanlayıcı:**\nYanıtla -> `/zamanla 1h` (1 saat sonra paylaşır).", reply_markup=back_btn())
        
    elif cb.data == "info_buton":
        await cb.message.edit_text("🔘 **Butonlu Post:**\nYanıtla -> `/buton İsim | Link`\nÖrn: `/buton Git | https://google.com`", reply_markup=back_btn())
        
    elif cb.data == "info_post":
        await cb.message.edit_text("📢 **Direkt Post:**\nYanıtla -> `/post` (Bot adıyla kanala atar).", reply_markup=back_btn())
        
    elif cb.data == "info_approve":
        await cb.message.edit_text("🔐 **Oto Onay:**\n`/otoonay ac` yazarsan istekleri kabul ederim.", reply_markup=back_btn())
        
    elif cb.data == "info_account":
        uid = cb.from_user.id
        _, status = check_user_access(uid)
        await cb.message.edit_text(f"👤 ID: `{uid}`\n📊 Lisans: {status}\n🛒 Satın Al: @yasin33", reply_markup=back_btn())

# --- Ön Kontrol (Kanal & Lisans) ---
async def pre_check(client, message):
    user_id = message.from_user.id
    access, _ = check_user_access(user_id)
    if not access: await message.reply("⛔ **Süreniz Doldu!**\nDevam etmek için: @yasin33"); return None
    channel_id = get_setting("channel_id")
    if not channel_id: await message.reply("⚠️ Önce kanaldan bir mesaj iletip `/setchannel` yaz."); return None
    return int(channel_id)

# --- 1. SÜRELİ MESAJ ---
@bot.on_message(filters.command("flash") & filters.private)
async def flash(client, message):
    cid = await pre_check(client, message)
    if not cid or not message.reply_to_message: return
    try:
        raw = message.command[1]
        sec = int(raw.replace("m", "")) * 60 if "m" in raw else int(raw)
        sent = await message.reply_to_message.copy(cid)
        alert = await client.send_message(cid, f"⏳ {raw} sonra silinecek!", reply_to_message_id=sent.id)
        await message.reply(f"✅ {raw} ayarlandı.")
        await asyncio.sleep(sec)
        try: await sent.delete(); await alert.delete()
        except: pass
    except: await message.reply("❌ Hata")

# --- 2. ZAMANLAYICI ---
@bot.on_message(filters.command("zamanla") & filters.private)
async def schedule(client, message):
    cid = await pre_check(client, message)
    if not cid or not message.reply_to_message: return
    try:
        raw = message.command[1]
        delay = int(raw.replace("h", "")) * 3600 if "h" in raw else int(raw.replace("m", "")) * 60
        run_time = datetime.now() + timedelta(seconds=delay)
        add_schedule(message.from_user.id, cid, message.reply_to_message.id, run_time)
        await message.reply(f"✅ **Planlandı!** {raw} sonra paylaşılacak.")
    except: await message.reply("❌ Hata: `/zamanla 1h`")

# --- 3. BUTONLU POST ---
@bot.on_message(filters.command("buton") & filters.private)
async def buton(client, message):
    cid = await pre_check(client, message)
    if not cid or not message.reply_to_message: return
    try:
        name, url = message.text.split(None, 1)[1].split("|")
        btn = InlineKeyboardMarkup([[InlineKeyboardButton(name.strip(), url=url.strip())]])
        await message.reply_to_message.copy(cid, reply_markup=btn)
        await message.reply("✅")
    except: await message.reply("⚠️ Hata: `/buton İsim | Link`")

# --- 4. DİREKT POST ---
@bot.on_message(filters.command("post") & filters.private)
async def post(client, message):
    cid = await pre_check(client, message)
    if not cid or not message.reply_to_message: return
    try: await message.reply_to_message.copy(cid); await message.reply("✅")
    except: await message.reply("❌ Hata")

# --- 5. OTO ONAY & AYARLAR ---
@bot.on_chat_join_request()
async def auto_approve_handler(client, req: ChatJoinRequest):
    if get_setting("auto_approve") == "1":
        try:
            await client.approve_chat_join_request(req.chat.id, req.from_user.id)
            msg = get_setting("welcome_msg")
            if msg: await client.send_message(req.from_user.id, msg)
        except: pass

@bot.on_message(filters.command("otoonay") & filters.user(OWNER_ID))
async def set_approve(c, m):
    try:
        if m.command[1] == "ac": set_setting("auto_approve", "1"); await m.reply("✅ Açıldı")
        else: set_setting("auto_approve", "0"); await m.reply("❌ Kapatıldı")
    except: await m.reply("`/otoonay ac` veya `kapat`")

@bot.on_message(filters.command("hosgeldin") & filters.user(OWNER_ID))
async def set_welcome(c, m):
    try: set_setting("welcome_msg", m.text.split(None, 1)[1]); await m.reply("✅ Ayarlandı")
    except: await m.reply("`/hosgeldin Mesaj...`")

@bot.on_message(filters.command("setchannel") & filters.user(OWNER_ID))
async def set_channel(c, m):
    if m.reply_to_message and m.reply_to_message.forward_from_chat:
        set_setting("channel_id", m.reply_to_message.forward_from_chat.id)
        await m.reply("✅ Kanal Kaydedildi.")
    else: await m.reply("⚠️ Kanaldan mesaj ilet.")

# --- 6. ADMİN PANEL ---
@bot.on_message(filters.command("addvip") & filters.user(OWNER_ID))
async def addvip(c, m): 
    try: set_vip(int(m.command[1]), True); await m.reply("✅ VIP Verildi")
    except: pass

@bot.on_message(filters.command("delvip") & filters.user(OWNER_ID))
async def delvip(c, m): 
    try: set_vip(int(m.command[1]), False); await m.reply("❌ FREE Yapıldı")
    except: pass

# ==================== BAŞLATMA ====================
async def scheduler_task():
    print("⏳ Zamanlayıcı Aktif...")
    while True:
        await asyncio.sleep(60)
        try:
            posts = get_due_posts()
            if posts:
                for post in posts: # post: id, uid, cid, mid, time
                    try:
                        await bot.copy_message(chat_id=post[2], from_chat_id=post[1], message_id=post[3])
                        await bot.send_message(post[1], "🚀 Zamanlı post paylaşıldı!")
                    except Exception as e: print(f"Post Hata: {e}")
        except: pass

async def main():
    print("Bot Başlıyor...")
    await bot.start()
    asyncio.create_task(scheduler_task()) # Zamanlayıcıyı başlat
    await idle()
    await bot.stop()

if __name__ == '__main__':
    keep_alive()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())