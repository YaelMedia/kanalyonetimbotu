import os
import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta
from threading import Thread
from flask import Flask
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ChatJoinRequest
# HATA YAKALAMAK İÇİN ÖZEL KÜTÜPHANELERİ EKLEDİM 👇
from pyrogram.errors import ChatWriteForbidden, ChatAdminRequired, RightForbidden

# ==================== 1. AYARLAR ====================
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))

# ==================== 2. WEB SERVER ====================
logging.basicConfig(level=logging.INFO)
logging.getLogger("pyrogram").setLevel(logging.WARNING)
app = Flask(__name__)

@app.route('/')
def home(): return "YaelManager V50 Active! 🟢"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = Thread(target=run_web)
    t.daemon = True
    t.start()

# ==================== 3. VERİTABANI ====================
DB_NAME = "bot_data.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, status TEXT, join_date TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_settings (user_id INTEGER PRIMARY KEY, channel_id INTEGER, auto_approve INTEGER DEFAULT 0, welcome_msg TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS scheduled_posts (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, channel_id INTEGER, message_id INTEGER, run_time TEXT)''')
    conn.commit()
    conn.close()

# --- DB Yardımcıları ---
def set_user_channel(user_id, channel_id):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO user_settings (user_id) VALUES (?)", (user_id,))
        cursor.execute("UPDATE user_settings SET channel_id=? WHERE user_id=?", (channel_id, user_id))

def get_user_channel(user_id):
    with sqlite3.connect(DB_NAME) as conn:
        res = conn.cursor().execute("SELECT channel_id FROM user_settings WHERE user_id=?", (user_id,)).fetchone()
    return res[0] if res else None

def set_approve_status(user_id, status):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO user_settings (user_id) VALUES (?)", (user_id,))
        cursor.execute("UPDATE user_settings SET auto_approve=? WHERE user_id=?", (status, user_id))

def get_settings_by_channel(channel_id):
    with sqlite3.connect(DB_NAME) as conn:
        res = conn.cursor().execute("SELECT auto_approve, welcome_msg FROM user_settings WHERE channel_id=?", (channel_id,)).fetchone()
    return res if res else (0, None)

def add_schedule(user_id, channel_id, message_id, run_time):
    with sqlite3.connect(DB_NAME) as conn:
        conn.cursor().execute("INSERT INTO scheduled_posts (user_id, channel_id, message_id, run_time) VALUES (?, ?, ?, ?)", (user_id, channel_id, message_id, run_time.isoformat()))

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

def check_user_access(user_id):
    if user_id == OWNER_ID: return True, "👑 Yönetici"
    conn = sqlite3.connect(DB_NAME)
    res = conn.cursor().execute("SELECT status, join_date FROM users WHERE user_id=?", (user_id,)).fetchone()
    if not res:
        now = datetime.now().isoformat()
        conn.cursor().execute("INSERT INTO users VALUES (?, 'FREE', ?)", (user_id, now))
        conn.commit(); conn.close()
        return True, "🟢 Deneme (24 Saat)"
    status, join_str = res
    conn.close()
    if status == "VIP": return True, "💎 VIP Üye"
    if datetime.now() < datetime.fromisoformat(join_str) + timedelta(hours=24): return True, "🟢 Deneme Sürümü"
    return False, "🔴 Süre Doldu"

def set_vip(user_id, is_vip):
    status = "VIP" if is_vip else "FREE"
    with sqlite3.connect(DB_NAME) as conn:
        try: conn.cursor().execute("INSERT INTO users VALUES (?, ?, ?)", (user_id, status, datetime.now().isoformat()))
        except: conn.cursor().execute("UPDATE users SET status=? WHERE user_id=?", (status, user_id))

# ==================== 4. İSTEMCİ ====================
init_db()
bot = Client("manager_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True)

# ==================== 5. MENÜLER ====================
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💣 Süreli Mesaj", callback_data="info_flash"),
         InlineKeyboardButton("⏳ Zamanlayıcı", callback_data="info_schedule")],
        [InlineKeyboardButton("🔘 Butonlu Post", callback_data="info_buton"),
         InlineKeyboardButton("📢 Direkt Post", callback_data="info_post")],
        [InlineKeyboardButton("🔐 Oto Onay", callback_data="info_approve"),
         InlineKeyboardButton("👤 Hesabım", callback_data="info_account")],
        [InlineKeyboardButton("⚙️ KANAL DEĞİŞTİR", callback_data="change_channel")]
    ])

def setup_menu():
    return InlineKeyboardMarkup([[InlineKeyboardButton("Nasıl Yapılır?", callback_data="help_setup")]])
def back_btn(): return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ana Menü", callback_data="main")]])

# ==================== 6. KURULUM VE UYARILAR ====================

@bot.on_message(filters.command("start") & filters.private)
async def start(client, message):
    user_id = message.from_user.id
    access, status = check_user_access(user_id)
    
    if not access:
        await message.reply(f"⛔ **{status}**\nLütfen @yasin33 ile iletişime geçin.")
        return

    channel_id = get_user_channel(user_id)
    
    if not channel_id:
        await message.reply(
            "👋 **Kanal Yöneticisine Hoşgeldin!**\n\n"
            "🚨 **ÖNEMLİ UYARI (OKU!):**\n"
            "Bu botun çalışması için yönetmek istediğin kanalda **YÖNETİCİ (ADMIN)** olması gerekir.\n"
            "Özellikle **'Mesaj Gönderme'** yetkisini vermezsen Flash ve Post çalışmaz!\n\n"
            "👇 **KURULUM:**\n"
            "1. Botu kanalına ekle ve Yönetici yap.\n"
            "2. Kanalından herhangi bir mesajı bana ilet (forward yap).",
            reply_markup=setup_menu()
        )
    else:
        await message.reply(f"👋 **Panel Hazır!**\n📺 Bağlı Kanal: `{channel_id}`\nℹ️ {status}", reply_markup=main_menu())

@bot.on_message(filters.forwarded & filters.private)
async def channel_setup(client, message):
    if not message.forward_from_chat:
        await message.reply("❌ **Hata:** Bu bir kanal mesajı değil. Kanaldan iletmen lazım.")
        return
    
    chat_id = message.forward_from_chat.id
    title = message.forward_from_chat.title
    
    # KANAL TİPİ KONTROLÜ (Sadece kanallar ve gruplar)
    if message.forward_from_chat.type not in [enums.ChatType.CHANNEL, enums.ChatType.SUPERGROUP, enums.ChatType.GROUP]:
        await message.reply("❌ Sadece Kanal veya Grup bağlayabilirsin.")
        return

    set_user_channel(message.from_user.id, chat_id)
    
    await message.reply(
        f"✅ **KANAL BAĞLANDI!**\n\n"
        f"📺 **İsim:** {title}\n"
        f"🆔 **ID:** `{chat_id}`\n\n"
        f"🚨 **SON KONTROL:**\n"
        f"Botu bu kanalda **YÖNETİCİ** yaptın mı? Yapmadıysan komutlar çalışmaz!",
        reply_markup=main_menu()
    )

# --- İŞLEVLER (HATA YAKALAYICILI) ---

async def pre_check(client, message):
    uid = message.from_user.id
    acc, _ = check_user_access(uid)
    if not acc: await message.reply("⛔ Süre Doldu"); return None
    cid = get_user_channel(uid)
    if not cid: await message.reply("⚠️ Önce kanal bağla."); return None
    return int(cid)

@bot.on_message(filters.command("flash") & filters.private)
async def flash(client, message):
    cid = await pre_check(client, message)
    if not cid: return
    if not message.reply_to_message:
        await message.reply("⚠️ **Kullanım Hatası!**\nBir fotoğrafa veya yazıya **yanıt vererek** `/flash 5` yazmalısın."); return

    try:
        raw = message.command[1]
        sec = int(raw.replace("m", "")) * 60 if "m" in raw else int(raw)
        
        # Kanala Kopyala
        sent = await message.reply_to_message.copy(cid)
        
        # Bilgi Mesajı
        alrt = await client.send_message(cid, f"⏳ **Bu mesaj {raw} sonra silinecek!**", reply_to_message_id=sent.id)
        
        await message.reply(f"✅ **Başarılı!** Mesaj {raw} sonra silinecek.")
        
        await asyncio.sleep(sec)
        try: await sent.delete(); await alrt.delete()
        except: pass

    # ÖZEL HATA YAKALAMA (KULLANICIYA LAF ANLATMA KISMI)
    except (ChatWriteForbidden, ChatAdminRequired):
        await message.reply(
            "❌ **YETKİ HATASI!**\n\n"
            "Ben o kanalda **Yönetici (Admin)** değilim veya **Mesaj Gönderme** iznim yok.\n"
            "Lütfen kanal ayarlarına girip beni Yönetici yap!"
        )
    except IndexError:
        await message.reply("❌ **Süre Girmedin!**\nÖrnek: `/flash 30`")
    except Exception as e:
        await message.reply(f"❌ Beklenmedik Hata: {e}")

@bot.on_message(filters.command("post") & filters.private)
async def post(client, message):
    cid = await pre_check(client, message)
    if not cid or not message.reply_to_message: return
    try:
        await message.reply_to_message.copy(cid)
        await message.reply("✅ **Gönderildi!**")
    except (ChatWriteForbidden, ChatAdminRequired):
        await message.reply("❌ **YETKİ YOK!** Botu kanala Admin yap.")
    except Exception as e:
        await message.reply(f"❌ Hata: {e}")

@bot.on_message(filters.command("buton") & filters.private)
async def buton(client, message):
    cid = await pre_check(client, message)
    if not cid or not message.reply_to_message: return
    try:
        nm, ur = message.text.split(None, 1)[1].split("|")
        btn = InlineKeyboardMarkup([[InlineKeyboardButton(nm.strip(), url=ur.strip())]])
        await message.reply_to_message.copy(cid, reply_markup=btn)
        await message.reply("✅")
    except (ChatWriteForbidden, ChatAdminRequired):
        await message.reply("❌ **YETKİ YOK!** Botu kanala Admin yap.")
    except: await message.reply("⚠️ Hata! Format: `/buton İsim | Link`")

# --- ZAMANLAYICI & OTO ONAY (AYNI) ---
@bot.on_message(filters.command("zamanla") & filters.private)
async def schedule(c, m):
    cid = await pre_check(c, m)
    if not cid or not m.reply_to_message: return
    try:
        raw = m.command[1]
        d = int(raw.replace("h", "")) * 3600 if "h" in raw else int(raw.replace("m", "")) * 60
        add_schedule(m.from_user.id, cid, m.reply_to_message.id, datetime.now()+timedelta(seconds=d))
        await m.reply(f"✅ **Planlandı!** {raw} sonra paylaşılacak.")
    except: await m.reply("❌ Hata")

@bot.on_chat_join_request()
async def auto_approve_handler(client, req: ChatJoinRequest):
    sets = get_settings_by_channel(req.chat.id)
    if sets and sets[0] == 1:
        try: await client.approve_chat_join_request(req.chat.id, req.from_user.id)
        except: pass

@bot.on_message(filters.command("otoonay") & filters.private)
async def set_approve(c, m):
    if not await pre_check(c, m): return
    try:
        if m.command[1] == "ac": set_approve_status(m.from_user.id, 1); await m.reply("✅ Açıldı")
        else: set_approve_status(m.from_user.id, 0); await m.reply("❌ Kapatıldı")
    except: await m.reply("`/otoonay ac`")

# --- MENÜ CALLBACKS ---
@bot.on_callback_query()
async def cb_handler(client, cb):
    if cb.data == "main": await cb.message.edit_text("👋 **Ana Menü**", reply_markup=main_menu())
    elif cb.data == "change_channel": await cb.message.edit_text("🔄 Kanaldan mesaj ilet.", reply_markup=back_btn())
    elif cb.data == "help_setup": await cb.answer("Kanal > Mesaj Seç > İlet > Bot", show_alert=True)
    elif cb.data == "info_flash": await cb.message.edit_text("💣 Yanıtla -> `/flash 30`\n⚠️ Bot Admin olmalı!", reply_markup=back_btn())
    elif cb.data == "info_schedule": await cb.message.edit_text("⏳ Yanıtla -> `/zamanla 1h`", reply_markup=back_btn())
    elif cb.data == "info_buton": await cb.message.edit_text("🔘 Yanıtla -> `/buton İsim | Link`", reply_markup=back_btn())
    elif cb.data == "info_post": await cb.message.edit_text("📢 Yanıtla -> `/post`\n⚠️ Bot Admin olmalı!", reply_markup=back_btn())
    elif cb.data == "info_approve": await cb.message.edit_text("🔐 `/otoonay ac` yaz.\n⚠️ Kanalda 'İstekle Katıl' açık olmalı.", reply_markup=back_btn())
    elif cb.data == "info_account": 
        _, status = check_user_access(cb.from_user.id)
        await cb.message.edit_text(f"📊 {status}\n🛒 @yasin33", reply_markup=back_btn())

# --- ADMİN ---
@bot.on_message(filters.command("addvip") & filters.user(OWNER_ID))
async def addvip(c, m): set_vip(int(m.command[1]), True); await m.reply("OK")
@bot.on_message(filters.command("delvip") & filters.user(OWNER_ID))
async def delvip(c, m): set_vip(int(m.command[1]), False); await m.reply("OK")

# --- BAŞLATMA ---
from pyrogram import enums # ChatType için gerekli
async def scheduler_task():
    while True:
        await asyncio.sleep(60)
        try:
            posts = get_due_posts()
            if posts:
                for p in posts:
                    try: await bot.copy_message(p[2], p[1], p[3])
                    except: pass
        except: pass

async def main():
    print("Bot Başladı...")
    await bot.start()
    asyncio.create_task(scheduler_task())
    await idle()
    await bot.stop()

if __name__ == '__main__':
    keep_alive()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
