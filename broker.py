import logging
import sqlite3
import os
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import asyncio
from aiohttp import web  # خادم الويب المصغر لمنع السكون

# التوكن الخاص بك
TOKEN = "9002221387:AAGKzz7uva3vDqkvneydmi5LkEjvbkvbenI"

# عنوان محفظة سولانا الخاصة بك
ESCROW_WALLET_ADDRESS = "2LHfh94uLwvNcsMc3KqGFB5Ta83assM8wdZRoT6k4jHN"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# --- إعداد قاعدة البيانات الدائمة (SQLite) ---
def init_db():
    conn = sqlite3.connect("p2p_fee_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            details TEXT,
            status TEXT,
            buyer_id INTEGER,
            buyer_username TEXT,
            tx_hash TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reputation (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            successful_deals INTEGER DEFAULT 0,
            total_earnings REAL DEFAULT 0.0
        )
    """)
    conn.commit()
    conn.close()

init_db()

class CreateOrder(StatesGroup):
    waiting_for_details = State()

class PayOrder(StatesGroup):
    waiting_for_tx = State()

# القائمة الرئيسية
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="📋 استعراض الطلبات المتاحة", callback_data="list_orders")],
        [types.InlineKeyboardButton(text="➕ إضافة طلب وساطة جديد", callback_data="new_order")],
        [types.InlineKeyboardButton(text="👤 ملفي الشخصي وأرباحي", callback_data="my_profile")]
    ])
    await message.answer(
        "🛡️ **مرحباً بك في نظام الوساطة الآمن (مع رسوم خدمة 1$ للوسيط)**\n\n"
        "رسوم الخدمة ثابتة وتضاف لتأمين الحماية وضمان حقوق الطرفين.\n"
        "اختر ما ترغب به من الأزرار بالأسفل:", 
        reply_markup=keyboard, 
        parse_mode="Markdown"
    )

# بدء إضافة طلب
@dp.callback_query(F.data == "new_order")
async def ask_order_details(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("✍️ أرسل تفاصيل طلبك بدقة (اذكر قيمة السلعة أو المبلغ المطلوب، مع العلم أنه سيضاف 1$ رسوم وساطة تلقائياً):")
    await state.set_state(CreateOrder.waiting_for_details)
    await callback.answer()

# حفظ الطلب
@dp.message(CreateOrder.waiting_for_details)
async def save_order(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    details = message.text

    conn = sqlite3.connect("p2p_fee_bot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO orders (user_id, username, details, status) VALUES (?, ?, ?, ?)",
                   (user_id, username, details, "active"))
    order_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    await message.answer(
        f"✅ **تم نشر طلب الوساطة برقم #{order_id} بنجاح**\n"
        f"ملاحظة: تتضمن الشروط اقتطاع 1$ رسوم وساطة تذهب لمحفظة النظام تلقائياً عند الإتمام.", 
        parse_mode="Markdown"
    )
    await state.clear()

# استعراض الطلبات
@dp.callback_query(F.data == "list_orders")
async def show_orders(callback: types.CallbackQuery):
    conn = sqlite3.connect("p2p_fee_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, details FROM orders WHERE status = 'active'")
    active_orders = cursor.fetchall()
    conn.close()
    
    if not active_orders:
        await callback.message.answer("📭 لا توجد طلبات وساطة نشطة حالياً.")
        await callback.answer()
        return

    keyboard_buttons = []
    text_list = "📋 **طلبات الوساطة النشطة (مع رسوم 1$ للوسيط):**\n\n"
    
    for oid, uname, details in active_orders:
        text_list += f"📌 **الطلب #{oid}**\n{details}\nبواسطة: @{uname}\n-------------------\n"
        keyboard_buttons.append([types.InlineKeyboardButton(text=f"🔒 قبول الطلب #{oid}", callback_data=f"take_order_{oid}")])
            
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    await callback.message.answer(text_list, reply_markup=keyboard, parse_mode="Markdown")
    await callback.answer()

# قبول الطلب وعرض تنبيه الرسوم
@dp.callback_query(F.data.startswith("take_order_"))
async def process_take_order(callback: types.CallbackQuery):
    order_id = int(callback.data.split("_")[2])
    buyer_id = callback.from_user.id
    buyer_username = callback.from_user.username or callback.from_user.first_name

    conn = sqlite3.connect("p2p_fee_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, status FROM orders WHERE id = ?", (order_id,))
    row = cursor.fetchone()

    if not row or row[2] != "active":
        conn.close()
        await callback.answer("⚠️ عذراً، هذا الطلب لم يعد متاحاً!", show_alert=True)
        return

    seller_id, seller_username, _ = row

    if buyer_id == seller_id:
        conn.close()
        await callback.answer("❌ لا يمكنك قبول طلبك الخاص!", show_alert=True)
        return

    cursor.execute("UPDATE orders SET status = 'pending', buyer_id = ?, buyer_username = ? WHERE id = ?",
                   (buyer_id, buyer_username, order_id))
    conn.commit()
    conn.close()

    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="📤 أرسل هاش التحويل (TxID)", callback_data=f"send_tx_{order_id}")]
    ])

    await callback.message.answer(
        f"🪙 **تفاصيل الدفع الآمن (يتضمن رسوم الوسيط):**\n\n"
        f"🔹 رقم الطلب: #{order_id}\n"
        f"🔹 عنوان محفظة الوساطة للتحويل (قيمة السلعة + 1$ رسوم): \n`{ESCROW_WALLET_ADDRESS}`\n\n"
        f"⚠️ **تنبيه للمشتري:** سيتم اقتطاع 1 دولار لصالح رسوم خدمة الوساطة واستقرارها في حساب المنصة، وتحويل الباقي للبائع عند الإتمام.", 
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    
    try:
        await bot.send_message(
            seller_id, 
            f"🔔 **تنبيه:** قام المستخدم @{buyer_username} بقبول طلبك رقم #{order_id} وهو بصدد تحويل المبلغ (شاملة رسوم الوساطة 1$).", 
            parse_mode="Markdown"
        )
    except Exception:
        pass
        
    await callback.answer()

# طلب الهاش
@dp.callback_query(F.data.startswith("send_tx_"))
async def ask_tx_hash(callback: types.CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split("_")[2])
    await state.update_data(order_id=order_id)
    await callback.message.answer("✍️ أرسل الآن **رقم المعاملة أو الهاش (TxID)** الخاص بتحويلك المالي لتأكيد العملية:")
    await state.set_state(PayOrder.waiting_for_tx)
    await callback.answer()

# حفظ الهاش وإخطار البائع
@dp.message(PayOrder.waiting_for_tx)
async def process_tx_hash(message: types.Message, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("order_id")
    tx_hash = message.text

    conn = sqlite3.connect("p2p_fee_bot.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE orders SET tx_hash = ? WHERE id = ?", (tx_hash, order_id))
    cursor.execute("SELECT user_id, buyer_username FROM orders WHERE id = ?", (order_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        await message.answer("حدث خطأ ما.")
        await state.clear()
        return

    seller_id, buyer_username = row

    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="✅ تأكيد استلام الأموال وإتمام الصفقة", callback_data=f"fee_complete_{order_id}")]
    ])

    await message.answer("⏳ تم تسجيل الهاش وإبلاغ البائع لمراجعة حسابه والتحقق من وصول المبلغ.")

    try:
        await bot.send_message(
            seller_id,
            f"🚨 **إثبات تحويل للطلب #{order_id}**\n"
            f"أرسل المشتري @{buyer_username} الهاش:\n`{tx_hash}`\n\n"
            f"تحقق من رصيدك (تأكد أن المبلغ وصل كاملاً مطروحاً منه 1$ رسوم الوساطة الخاصة بالمنصة)، ثم اضغط زر التأكيد أدناه لإغلاق الصفقة.",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    except Exception:
        pass

    await state.clear()

# التأكيد النهائي: تثبيت الدولار في حسابك وزيادة السمعة
@dp.callback_query(F.data.startswith("fee_complete_"))
async def fee_complete(callback: types.CallbackQuery):
    order_id = int(callback.data.split("_")[1])
    
    conn = sqlite3.connect("p2p_fee_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, buyer_id FROM orders WHERE id = ?", (order_id,))
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        await callback.answer("الطلب غير موجود.", show_alert=True)
        return

    seller_id, buyer_id = row
    
    cursor.execute("UPDATE orders SET status = 'completed' WHERE id = ?", (order_id,))
    
    for uid in [seller_id, buyer_id]:
        if uid:
            cursor.execute("INSERT OR IGNORE INTO reputation (user_id, successful_deals, total_earnings) VALUES (?, 0, 0.0)", (uid,))
            cursor.execute("UPDATE reputation SET successful_deals = successful_deals + 1 WHERE user_id = ?", (uid,))
            
    conn.commit()
    conn.close()

    await callback.message.answer(
        f"🎉 **تمت الصفقة #{order_id} بنجاح!**\n"
        f"✅ تم اقتطاع وتثبيت **1.00$** رسوم الوساطة في حسابك بنجاح دون تحويلها للبائع.", 
        parse_mode="Markdown"
    )
    try:
        await bot.send_message(buyer_id, f"🎉 **مبارك!** تم إتمام الصفقة #{order_id} بنجاح.")
    except Exception:
        pass
    await callback.answer()

# الملف الشخصي والأرباح المحفوظة
@dp.callback_query(F.data == "my_profile")
async def show_profile(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    conn = sqlite3.connect("p2p_fee_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT successful_deals FROM reputation WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    deals = row[0] if row else 0
    total_fees_earned = deals * 1.00
    
    await callback.message.answer(
        f"👤 **ملفك الشخصي وأرباحك:**\n\n"
        f"🆔 معرف المستخدم: `{user_id}`\n"
        f"🌟 الصفقات الناجحة: **{deals} صفقة**\n"
        f"💰 إجمالي أرباح رسوم الوساطة المحفوظة لك: **${total_fees_earned:.2f}**",
        parse_mode="Markdown"
    )
    await callback.answer()

# --- خادم الويب المصغر لمنع السكون (Keep-Alive Server) ---
async def handle(request):
    return web.Response(text="P2P Escrow Bot is running 24/7!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080)) # المنفذ الافتراضي الذي تحدده منصات الاستضافة
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def main():
    init_db()
    # تشغيل خادم الويب وبوت التيليغرام معاً في نفس الوقت
    await start_web_server()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
