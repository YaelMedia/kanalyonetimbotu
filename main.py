import os
import asyncio
import json
import time
from datetime import datetime, timedelta
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from threading import Thread
from flask import Flask

# ==================== AYARLAR ====================
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_ID = int(os.environ.get("OWNER_ID", 0))

bot = Client("yael_commercial", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ==================== VERİTABANI SİSTEMİ (JSON) ====================
DB_FILE = "users.json"

def load_db():
    if not os.path.exists(DB_FILE):
        return {"users": {}, "vips": []}
    with open(DB_FILE, "r") as f:
        return json.load(f)

def save_db(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=4)

# ==================== WEB SERVER (7/24) ====================
app = Flask(__name__)
@app.route('/')
def home(): return "Yael Ticari Bot Aktif! 💸"
def run_web(): app.run(host="0.0.0.0", port=8080)
def keep_alive():
    t = Thread(target=run_web)
    t.daemon = True
    t.start()

# ==================== YARDIMCI FONKSİYONLAR ====================
def check_status(user_id):
    """Kullanıcının süresi var mı kontrol eder"""
    data = load_db()
    str_id = str(user_id)
    
    # 1. VIP Kontrolü
    if str_id in data["vips"] or user_id == OWNER_ID:
        return True, "Sınırsız (VIP) 👑"
    
    # 2. Deneme Süresi Kontrolü
    if str_id in data["users"]:
        start_time = datetime.fromisoformat(data["users"][str_id])
        # 24 Saatlik Süre (Değiştirebilirsin)
        if datetime.now() < start_time + timedelta(hours=24):
            remaining = (start_time + timedelta(hours=24)) - datetime.now()
            hours = int(remaining.total_seconds() // 3600)
            return True, f"Deneme Sürümü ({hours} Saat Kaldı) ⏳"
        else:
            return False, "Süre Doldu ❌"
    
    return False, "Kayıt Yok"

# ==================== 1. KULLANICI ARAYÜZÜ (DM) ====================

@bot.on_message(filters.command("start") & filters.private)
async def start_handler(client, message):
    user_id = str(message.from_user.id)
    data = load_db()
    
    # Yeni Kullanıcı Kaydı
    if user_id not in data["users"]:
        data["users"][user_id] = datetime.now().isoformat()
        save_db(data)
        welcome_text = (
            f"👋 **Hoşgeldin {message.from_user.first_name}!**\n\n"
            f"🤖 Ben **Yael Manager**. Gruplarını otomatik yönetirim.\n"
            f"🎁 **24 Saatlik Ücretsiz Deneme** sürümün başladı!\n\n"
            f"⚡ **Özellikler:**\n"
            f"• Oto Katılım Onayı (Auto Approve)\n"
            f"• Reklam Engelleyici\n"
            f"• Hoşgeldin + ID Sistemi\n\n"
            f"👇 Botu kullanmaya başlamak için grubuna ekle."
        )
    else:
        # Eski Kullanıcı
        welcome_text = "👋 **Tekrar Hoşgeldin!**\nDurumunu kontrol etmek için aşağıdaki butonu kullan."

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Beni Grubuna Ekle", url=f"https://t.me/{bot.me.username}?startgroup=true")],
        [InlineKeyboardButton("📊 Durumum / Hesabım", callback_data="my_status")],
        [InlineKeyboardButton("📥 Video İndirici (Sponsor)", url="https://t.me/YaelSaverBot")]
    ])
    
    await message.reply(welcome_text, reply_markup=buttons)

# Durumum Butonu
@bot.on_callback_query(filters.regex("my_status"))
async def status_callback(client, callback):
    active, msg = check_status(callback.from_user.id)
    
    text = (
        f"👤 **Kullanıcı:** {callback.from_user.first_name}\n"
        f"🆔 **ID:** `{callback.from_user.id}`\n"
        f"📊 **Durum:** {msg}\n\n"
    )
    
    if not active:
        text += "⚠️ **Süreniz dolmuş!** Devam etmek için admin ile görüşün."
        # Buraya kendi iletişim butonunu koyabilirsin
        btns = InlineKeyboardMarkup([[InlineKeyboardButton("👑 VIP Satın Al", user_id=OWNER_ID)]])
    else:
        text += "✅ Botu gruplarında kullanabilirsin."
        btns = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Geri", callback_data="back_start")]])
        
    await callback.message.edit(text, reply_markup=btns)

@bot.on_callback_query(filters.regex("back_start"))
async def back_callback(client, callback):
    # Start menüsüne dönüş (Basitçe start mesajını tekrar atar gibi editleriz)
    await start_handler(client, callback.message)

# ==================== 2. GRUP YÖNETİMİ & OTO ONAY ====================

# A) Oto Katılım Onayı (En Önemli Özellik)
@bot.on_chat_join_request()
async def auto_approve(client, update):
    chat_id = update.chat.id
    # Grubu kimin kurduğunu veya botu kimin eklediğini bilmediğimiz için
    # Burada basitçe "Bot Gruptaysa Onayla" mantığı güdüyoruz.
    # Ticari mantıkta: Eğer bot gruptaysa çalışır. Botu gruptan atmak bizim elimizde (uzaktan leave).
    try:
        await client.approve_chat_join_request(chat_id, update.from_user.id)
        # İstersen kullanıcıya DM atabilirsin: "Girişin onaylandı!"
    except Exception as e:
        print(f"Onay hatası: {e}")

# B) Hoşgeldin + ID + Reklam Engelleyici
@bot.on_message(filters.group)
async def group_handler(client, message):
    chat_id = message.chat.id
    
    # 1. YENİ ÜYE GELDİ Mİ? (Hoşgeldin Mesajı)
    if message.new_chat_members:
        for member in message.new_chat_members:
            # Botun kendisi eklendiyse
            if member.id == bot.me.id:
                # Botu ekleyen kişiyi bul
                adder = message.from_user
                try:
                    # ÖZEL MESAJ AT (DM)
                    await client.send_message(
                        adder.id,
                        f"👋 **Selam {adder.first_name}!**\n\n"
                        f"Beni **{message.chat.title}** grubuna ekledin.\n"
                        f"Çalışabilmem için beni **YÖNETİCİ (ADMIN)** yapman şart!\n\n"
                        f"✅ **Gerekli Yetkiler:**\n- Kullanıcı Ekleme (İstek Onayı için)\n- Mesajları Silme\n- Kullanıcıları Engelleme"
                    )
                except:
                    # DM Kapalıysa Gruba Yaz ve Sil
                    m = await message.reply(f"⚠️ {adder.mention}, DM kutun kapalı! Beni yönetici yapmazsan çalışmam. (Bu mesaj silinecek)")
                    await asyncio.sleep(10)
                    try: await m.delete()
                    except: pass
            
            # Normal üye eklendiyse (ID Göster)
            else:
                txt = f"👋 **Hoşgeldin** {member.mention}\n🆔 **ID:** `{member.id}`"
                sent = await message.reply(txt)
                await asyncio.sleep(30) # 30 saniye sonra temizle
                try: await sent.delete()
                except: pass

    # 2. REKLAM ENGELLEYİCİ (Metin Mesajıysa)
    if message.text:
        text = message.text.lower()
        forbidden = ["t.me/", "joinchat", "http://", "https://", "bit.ly", "discord.gg"]
        
        # Yasaklı kelime var mı?
        if any(x in text for x in forbidden):
            # Admin değilse sil
            # (Hız için: Try-Except ile direkt silmeyi dene. Adminse hata verir, silinmez)
            try:
                await message.delete()
                w = await message.reply(f"⛔ {message.from_user.mention}, reklam yasak! (Yael Güvenlik)")
                await asyncio.sleep(5)
                await w.delete()
            except:
                pass 

# ==================== 3. ADMIN PANELİ (SADECE SEN) ====================

# VIP Ekleme
@bot.on_message(filters.command("addvip") & filters.user(OWNER_ID))
async def add_vip(client, message):
    # Kullanım: /addvip 123456789
    try:
        target_id = message.command[1]
        data = load_db()
        if target_id not in data["vips"]:
            data["vips"].append(target_id)
            save_db(data)
            await message.reply(f"✅ `{target_id}` **VIP listesine eklendi.**")
        else:
            await message.reply("⚠️ Bu kullanıcı zaten VIP.")
    except IndexError:
        await message.reply("⚠️ ID girmeyi unuttun. Örn: `/addvip 123456`")

# VIP Silme
@bot.on_message(filters.command("delvip") & filters.user(OWNER_ID))
async def del_vip(client, message):
    try:
        target_id = message.command[1]
        data = load_db()
        if target_id in data["vips"]:
            data["vips"].remove(target_id)
            save_db(data)
            await message.reply(f"❌ `{target_id}` **VIP listesinden çıkarıldı.**")
        else:
            await message.reply("⚠️ Bu kullanıcı zaten VIP değil.")
    except:
        await message.reply("⚠️ ID girmeyi unuttun.")

# İstatistikler
@bot.on_message(filters.command("admin") & filters.user(OWNER_ID))
async def admin_stats(client, message):
    data = load_db()
    total_users = len(data["users"])
    total_vips = len(data["vips"])
    
    # VIP Listesi
    vip_list = "\n".join([f"- `{uid}`" for uid in data["vips"]]) if data["vips"] else "Yok"
    
    txt = (
        f"👑 **YÖNETİCİ PANELİ**\n\n"
        f"👥 **Toplam Kayıtlı:** {total_users}\n"
        f"🌟 **Toplam VIP:** {total_vips}\n\n"
        f"📜 **VIP Listesi:**\n{vip_list}\n\n"
        f"📢 Reklam yapmak için: `/reklamyap Mesaj`"
    )
    await message.reply(txt)

# Reklam Yayını (Broadcast)
@bot.on_message(filters.command("reklamyap") & filters.user(OWNER_ID))
async def broadcast(client, message):
    if len(message.command) < 2:
        await message.reply("⚠️ Mesaj yazmadın.")
        return
    
    text = message.text.split(None, 1)[1]
    
    # Reklam Butonları (Video İndirici)
    btns = InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Ücretsiz Video İndirici", url="https://t.me/YaelSaverBot")],
        [InlineKeyboardButton("➕ Beni Grubuna Ekle", url=f"https://t.me/{bot.me.username}?startgroup=true")]
    ])
    
    await message.reply("📢 **Reklam, veritabanındaki kullanıcıların gruplarına gönderilmiyor (Bot API kısıtlaması).**\nSadece botun ekli olduğu ve hafızada tuttuğu gruplara atabiliriz. (Şu anlık pasif).")
    # Not: Bot API ile "botun olduğu tüm grupları listele" diye bir komut yoktur.
    # Grupları kaydetmek için ayrı bir veritabanı mantığı gerekir (önceki kodda vardı).
    # İstersen onu buraya da ekleyebilirim ama kafa karıştırmasın diye sade bıraktım.

if __name__ == '__main__':
    keep_alive()
    bot.run()
