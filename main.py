import asyncio
import io
import os
import re
import textwrap
import time
from datetime import datetime
from io import BytesIO

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import (
    BufferedInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    PreCheckoutQuery,
)
from dotenv import load_dotenv
from google import genai
from PIL import Image, ImageDraw, ImageFont
from redis.asyncio import Redis
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# Загрузка переменных окружения из .env
load_dotenv()

# Безопасное чтение конфигов
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "@conspect_for_easy")
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/conspect_for_easy")

# Чтение списков администраторов и привилегированных пользователей
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.isdigit()]
PERMANENT_PRO_PLUS_USERNAMES = [x.strip().lower() for x in os.getenv("PERMANENT_PRO_PLUS_USERNAMES", "").split(",") if x.strip()]
ADMIN_STATUS_USERNAMES = [x.strip().lower() for x in os.getenv("ADMIN_USERNAMES", "").split(",") if x.strip()]

# Ключи API Gemini
GEMINI_KEYS = [k.strip() for k in os.getenv("GEMINI_API_KEYS", "").split(",") if k.strip()]

# Подключение к Redis
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

redis_client = Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)
storage = RedisStorage(redis=redis_client)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)

class Form(StatesGroup):
    waiting_for_lang_select = State()
    waiting_for_main_choice = State()
    
    # Конспект
    waiting_for_content = State()
    waiting_for_length = State()
    summary_waiting_for_lang = State()
    summary_ready = State()
    
    # Рукописный формат
    hw_waiting_for_lang = State()
    hw_waiting_for_color = State()
    hw_waiting_for_paper = State()
    
    # Переводчик
    translator_waiting_for_lang = State()
    translator_waiting_for_content = State()
    translator_ready = State()

    # Задания / ДЗ
    hw_task_waiting_for_mode = State()
    hw_task_waiting_for_grade = State()
    hw_task_waiting_for_subject = State()
    hw_task_waiting_for_content = State()
    hw_task_ready = State()

    # Правка (BETA)
    waiting_for_edit_request = State()

LANG_NAMES = {
    "de": "Deutsch",
    "en": "English",
    "ru": "Русский",
    "uk": "Українська",
    "fr": "Français"
}

# --- ТЕКСТЫ ИНТЕРФЕЙСА НА РАЗНЫХ ЯЗЫКАХ ---
I18N = {
    "ru": {
        "welcome_lang": "👋 Выберите язык интерфейса / Select interface language:",
        "main_menu": "Главное меню! Выберите нужную функцию:",
        "btn_summary": "📝 КОНСПЕКТ",
        "btn_translator": "🌐 ПЕРЕВОДЧИК",
        "btn_tasks": "📚 ЗАДАНИЯ / ДЗ",
        "btn_profile": "👤 ЛИЧНЫЙ КАБИНЕТ",
        "btn_settings": "⚙️ Настройки",
        "btn_back": "🔙 Назад",
        "btn_home": "🏠 Главное меню",
        "profile_title": "<b>👤 ВАШ ЛИЧНЫЙ КАБИНЕТ</b>\n━━━━━━━━━━━━━━━━━━━\n\n",
        "profile_tier": "<b>Тариф:</b> ",
        "profile_expires": "<b>Осталось подписки:</b> ",
        "profile_used": "📊 <b>Использовано сегодня:</b> ",
        "profile_extra": "📦 <b>Купленных запросов:</b> ",
        "sub_required": "⚠️ Для использования функции необходимо подписаться на наш канал!",
        "btn_sub": "📢 Подписаться на канал",
        "btn_check_sub": "✅ Я подписался",
        "sub_success": "✅ Подписка подтверждена!",
        "settings_title": "<b>⚙️ НАСТРОЙКИ</b>\n━━━━━━━━━━━━━━━━━━━\n\nВыберите язык интерфейса:",
        "lang_changed": "✅ Язык интерфейса успешно изменен на Русский!"
    },
    "uk": {
        "welcome_lang": "👋 Оберіть мову інтерфейсу / Select interface language:",
        "main_menu": "Головне меню! Оберіть потрібную функцію:",
        "btn_summary": "📝 КОНСПЕКТ",
        "btn_translator": "🌐 ПЕРЕКЛАДАЧ",
        "btn_tasks": "📚 ЗАВДАННЯ / ДЗ",
        "btn_profile": "👤 ОСОБИСТИЙ КАБІНЕТ",
        "btn_settings": "⚙️ Налаштування",
        "btn_back": "🔙 Назад",
        "btn_home": "🏠 Головне меню",
        "profile_title": "<b>👤 ВАШ ОСОБИСТИЙ КАБІНЕТ</b>\n━━━━━━━━━━━━━━━━━━━\n\n",
        "profile_tier": "<b>Тариф:</b> ",
        "profile_expires": "<b>Залишилось передплати:</b> ",
        "profile_used": "📊 <b>Використано сьогодні:</b> ",
        "profile_extra": "📦 <b>Куплених запитів:</b> ",
        "sub_required": "⚠️ Для використання функції необхідно підписатися на наш канал!",
        "btn_sub": "📢 Подписатися на канал",
        "btn_check_sub": "✅ Я підписався",
        "sub_success": "✅ Підписку підтверджено!",
        "settings_title": "<b>⚙️ НАЛАШТУВАННЯ</b>\n━━━━━━━━━━━━━━━━━━━\n\nОберіть мову інтерфейсу:",
        "lang_changed": "✅ Мову інтерфейсу успішно змінено на Українську!"
    },
    "en": {
        "welcome_lang": "👋 Select interface language:",
        "main_menu": "Main Menu! Choose a feature:",
        "btn_summary": "📝 SUMMARY",
        "btn_translator": "🌐 TRANSLATOR",
        "btn_tasks": "📚 HOMEWORK",
        "btn_profile": "👤 PROFILE",
        "btn_settings": "⚙️ Settings",
        "btn_back": "🔙 Back",
        "btn_home": "🏠 Main Menu",
        "profile_title": "<b>👤 YOUR PROFILE</b>\n━━━━━━━━━━━━━━━━━━━\n\n",
        "profile_tier": "<b>Tier:</b> ",
        "profile_expires": "<b>Subscription left:</b> ",
        "profile_used": "📊 <b>Used today:</b> ",
        "profile_extra": "📦 <b>Extra requests:</b> ",
        "sub_required": "⚠️ You must subscribe to our channel to use this feature!",
        "btn_sub": "📢 Subscribe to channel",
        "btn_check_sub": "✅ I Subscribed",
        "sub_success": "✅ Subscription confirmed!",
        "settings_title": "<b>⚙️ SETTINGS</b>\n━━━━━━━━━━━━━━━━━━━\n\nSelect interface language:",
        "lang_changed": "✅ Interface language successfully changed to English!"
    },
    "de": {
        "welcome_lang": "👋 Wähle die Schnittstellensprache / Select interface language:",
        "main_menu": "Hauptmenü! Wähle eine Funktion:",
        "btn_summary": "📝 ZUSAMMENFASSUNG",
        "btn_translator": "🌐 ÜBERSETZER",
        "btn_tasks": "📚 HAUSAUFGABEN",
        "btn_profile": "👤 PROFIL",
        "btn_settings": "⚙️ Einstellungen",
        "btn_back": "🔙 Zurück",
        "btn_home": "🏠 Hauptmenü",
        "profile_title": "<b>👤 DEIN PROFIL</b>\n━━━━━━━━━━━━━━━━━━━\n\n",
        "profile_tier": "<b>Tarif:</b> ",
        "profile_expires": "<b>Abonnement übrig:</b> ",
        "profile_used": "📊 <b>Heute genutzt:</b> ",
        "profile_extra": "📦 <b>Gekaufte Anfragen:</b> ",
        "sub_required": "⚠️ Du musst unseren Kanal abonnieren, um diese Funktion zu nutzen!",
        "btn_sub": "📢 Kanal abonnieren",
        "btn_check_sub": "✅ Ich habe abonniert",
        "sub_success": "✅ Abonnement bestätigt!",
        "settings_title": "<b>⚙️ EINSTELLUNGEN</b>\n━━━━━━━━━━━━━━━━━━━\n\nWähle die Schnittstellensprache:",
        "lang_changed": "✅ Schnittstellensprache erfolgreich auf Deutsch geändert!"
    }
}

SUBJECTS = [
    ("Математика / Алгебра", "math"),
    ("Геометрия", "geom"),
    ("Физика", "phys"),
    ("Химия", "chem"),
    ("Биология / Естествознание", "bio"),
    ("История", "hist"),
    ("Языки / Литература", "lang"),
    ("Другой предмет", "other")
]

def clean_markdown(text: str) -> str:
    text = re.sub(r'\*+', '', text)
    text = re.sub(r'#+\s*', '', text)
    text = re.sub(r'`+', '', text)
    text = re.sub(r'~+', '', text)
    return text.strip()

# --- ЯЗЫКОВЫЕ НАСТРОЙКИ ПОЛЬЗОВАТЕЛЯ ---

async def get_user_lang(user_id: int) -> str:
    lang = await redis_client.get(f"user:{user_id}:lang")
    return lang if lang in I18N else "ru"

async def set_user_lang(user_id: int, lang_code: str):
    await redis_client.set(f"user:{user_id}:lang", lang_code)

def get_text(user_lang: str, key: str) -> str:
    return I18N.get(user_lang, I18N["ru"]).get(key, I18N["ru"].get(key, ""))

# --- РЕГИСТРАЦИЯ И ПРОВЕРКА КАНАЛА ---

async def register_user_activity(user_id: int, username: str = None, first_name: str = ""):
    now = time.time()
    await redis_client.sadd("bot_users:all", user_id)
    display_name = f"@{username}" if username else (first_name or "Без имени")
    await redis_client.hset("bot_users:names", str(user_id), display_name)
    await redis_client.zadd("bot_users:active", {str(user_id): now})

async def check_channel_subscription(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=REQUIRED_CHANNEL, user_id=user_id)
        return member.status in ["creator", "administrator", "member"]
    except Exception:
        return True

def get_subscribe_keyboard(lang: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text(lang, "btn_sub"), url=CHANNEL_LINK)],
        [InlineKeyboardButton(text=get_text(lang, "btn_check_sub"), callback_data="check_sub_again")]
    ])

# --- ТАРИФЫ И ЛИМИТЫ REDIS ---

async def get_user_tier_info(user_id: int, username: str = None):
    is_admin_status = username and username.lower() in ADMIN_STATUS_USERNAMES
    admin_postfix = " 👑 [АДМИН]" if is_admin_status else ""

    if username and username.lower() in PERMANENT_PRO_PLUS_USERNAMES:
        return "pro_plus", f"Навсегда ♾️{admin_postfix}"

    tier = await redis_client.get(f"user:{user_id}:tier") or "free"
    expires_at = await redis_client.get(f"user:{user_id}:tier_expires")
    
    if expires_at and tier != "free":
        expires_timestamp = float(expires_at)
        now = time.time()
        if now > expires_timestamp:
            await redis_client.set(f"user:{user_id}:tier", "free")
            await redis_client.delete(f"user:{user_id}:tier_expires")
            return "free", f"Истекла{admin_postfix}"
        
        days_left = int((expires_timestamp - now) // 86400)
        hours_left = int(((expires_timestamp - now) % 86400) // 3600)
        return tier, f"{days_left} дн. {hours_left} ч.{admin_postfix}"
    
    return "free", f"Нет активной подписки{admin_postfix}"

async def set_user_subscription(user_id: int, tier: str, months: int):
    now = time.time()
    current_expires = await redis_client.get(f"user:{user_id}:tier_expires")
    current_tier = await redis_client.get(f"user:{user_id}:tier")
    
    if current_expires and current_tier == tier and float(current_expires) > now:
        new_expires = float(current_expires) + (months * 30 * 86400)
    else:
        new_expires = now + (months * 30 * 86400)

    await redis_client.set(f"user:{user_id}:tier", tier)
    await redis_client.set(f"user:{user_id}:tier_expires", str(new_expires))

async def add_extra_requests(user_id: int, count: int):
    await redis_client.incrby(f"user:{user_id}:extra_requests", count)

async def check_and_increment_limit(user_id: int, username: str = None) -> bool:
    tier, _ = await get_user_tier_info(user_id, username)
    if tier == "pro_plus":
        return True
    
    max_limits = {"free": 5, "pro": 100}
    daily_limit = max_limits.get(tier, 5)
    
    today = datetime.now().date().isoformat()
    key = f"user:{user_id}:usage:{today}"
    
    current_usage = await redis_client.get(key)
    count = int(current_usage) if current_usage else 0
    
    if count < daily_limit:
        await redis_client.incr(key)
        if count == 0:
            await redis_client.expire(key, 86400)
        return True
    
    extra = await redis_client.get(f"user:{user_id}:extra_requests")
    extra_count = int(extra) if extra else 0
    
    if extra_count > 0:
        await redis_client.decr(f"user:{user_id}:extra_requests")
        return True
    
    return False

async def save_user_conspect(user_id: int, title: str, content: str):
    conspect_id = await redis_client.incr(f"user:{user_id}:conspect_seq")
    await redis_client.hset(f"user:{user_id}:conspects", str(conspect_id), f"{title}|||{content}")

async def get_user_conspects(user_id: int) -> dict:
    return await redis_client.hgetall(f"user:{user_id}:conspects")

# --- ГЕНЕРАЦИЯ PDF И РУКОПИСНОГО ТЕКСТА ---

def create_pdf(text: str) -> bytes:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    text_object = c.beginText(50, 750)
    text_object.setFont("Helvetica", 10)
    
    for line in text.split("\n"):
        text_object.textLine(line[:90])
        if text_object.getY() < 50:
            c.drawText(text_object)
            c.showPage()
            text_object = c.beginText(50, 750)
            text_object.setFont("Helvetica", 10)
            
    c.drawText(text_object)
    c.save()
    buffer.seek(0)
    return buffer.getvalue()

def generate_handwritten_image(text: str, paper_type: str, color_type: str) -> BytesIO:
    width, height = 1000, 1400
    image = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(image)

    font_size = 32
    font = None
    font_names = ["Caveat-Regular.ttf", "Caveat-Regular.ttf.ttf", "Caveat-Regular", "Caveat-VariableFont_wght.ttf"]
    
    for font_name in font_names:
        try:
            font = ImageFont.truetype(font_name, size=font_size)
            break
        except IOError:
            continue

    if font is None:
        font = ImageFont.load_default()

    if paper_type == "grid":
        grid_size = 35
        for x in range(0, width, grid_size):
            draw.line((x, 0, x, height), fill=(215, 228, 242), width=1)
        for y in range(0, height, grid_size):
            draw.line((0, y, width, y), fill=(215, 228, 242), width=1)
        draw.line((120, 0, 120, height), fill=(255, 140, 140), width=2)
        x_start, line_h = 140, 35
    elif paper_type == "line":
        line_step = 40
        for y in range(100, height, line_step):
            draw.line((0, y, width, y), fill=(215, 228, 242), width=1)
        draw.line((120, 0, 120, height), fill=(255, 140, 140), width=2)
        x_start, line_h = 140, 40
    else:
        x_start, line_h = 80, 42

    pen_color = (20, 40, 160) if color_type == "blue" else (20, 20, 20)

    lines = []
    for paragraph in text.split('\n'):
        wrapped = textwrap.wrap(paragraph, width=42)
        lines.extend(wrapped if wrapped else [''])

    y_offset = 60
    for line in lines:
        if y_offset + line_h > height - 60:
            break
        draw.text((x_start, y_offset), line, fill=pen_color, font=font)
        y_offset += line_h

    img_byte_arr = BytesIO()
    image.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    return img_byte_arr

# --- КЛАВИАТУРЫ ---

def get_start_language_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇩🇪 Deutsch", callback_data="set_lang_de"), InlineKeyboardButton(text="🇬🇧 English", callback_data="set_lang_en")],
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang_ru"), InlineKeyboardButton(text="🇺🇦 Українська", callback_data="set_lang_uk")]
    ])

def get_start_keyboard(lang: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text(lang, "btn_summary"), callback_data="main_summary"),
         InlineKeyboardButton(text=get_text(lang, "btn_translator"), callback_data="main_translator")],
        [InlineKeyboardButton(text=get_text(lang, "btn_tasks"), callback_data="main_hw_task")],
        [InlineKeyboardButton(text=get_text(lang, "btn_profile"), callback_data="main_profile")]
    ])

def get_profile_keyboard(lang: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Улучшить подписку", callback_data="buy_subscription")],
        [InlineKeyboardButton(text="⚡ Купить пакет запросов", callback_data="buy_extra_requests")],
        [InlineKeyboardButton(text="📑 Сохраненные конспекты", callback_data="my_conspects")],
        [InlineKeyboardButton(text=get_text(lang, "btn_settings"), callback_data="open_settings")],
        [InlineKeyboardButton(text=get_text(lang, "btn_home"), callback_data="act_restart")]
    ])

def get_settings_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇩🇪 Deutsch", callback_data="set_lang_de"), InlineKeyboardButton(text="🇬🇧 English", callback_data="set_lang_en")],
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang_ru"), InlineKeyboardButton(text="🇺🇦 Українська", callback_data="set_lang_uk")],
        [InlineKeyboardButton(text="🔙 Назад в кабинет", callback_data="main_profile")]
    ])

def get_tariffs_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡ Подписка PRO", callback_data="choose_pro")],
        [InlineKeyboardButton(text="👑 Подписка PRO+", callback_data="choose_pro_plus")],
        [InlineKeyboardButton(text="🔙 Назад в кабинет", callback_data="main_profile")]
    ])

def get_period_keyboard(tier_type: str):
    prefix = "pay_pro" if tier_type == "pro" else "pay_plus"
    prices = {
        "pro": [("1 мес. — 79 ⭐️", "1"), ("3 мес. — 179 ⭐️", "3"), ("6 мес. — 250 ⭐️", "6"), ("12 мес. — 399 ⭐️", "12")],
        "plus": [("1 мес. — 159 ⭐️", "1"), ("3 мес. — 359 ⭐️", "3"), ("6 мес. — 499 ⭐️", "6"), ("12 мес. — 799 ⭐️", "12")]
    }
    buttons = [[InlineKeyboardButton(text=label, callback_data=f"{prefix}_{m}")] for label, m in prices[tier_type]]
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="buy_subscription")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_extra_requests_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 10 запросов — 25 ⭐️", callback_data="pay_req_10")],
        [InlineKeyboardButton(text="📦 50 запросов — 100 ⭐️", callback_data="pay_req_50")],
        [InlineKeyboardButton(text="📦 100 запросов — 179 ⭐️", callback_data="pay_req_100")],
        [InlineKeyboardButton(text="🔙 Назад в кабинет", callback_data="main_profile")]
    ])

def get_input_mode_keyboard(lang: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Текст", callback_data="mode_text"), InlineKeyboardButton(text="💡 Тема", callback_data="mode_topic")],
        [InlineKeyboardButton(text="🖼️ Фото", callback_data="mode_photo"), InlineKeyboardButton(text="🎥 Видео", callback_data="mode_video")],
        [InlineKeyboardButton(text=get_text(lang, "btn_home"), callback_data="act_restart")]
    ])

def get_task_input_mode_keyboard(lang: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Текст с вопросом", callback_data="task_mode_text"), InlineKeyboardButton(text="🖼️ Фото", callback_data="task_mode_photo")],
        [InlineKeyboardButton(text=get_text(lang, "btn_home"), callback_data="act_restart")]
    ])

def get_grades_keyboard(lang: str):
    buttons = []
    row = []
    for grade in range(1, 12):
        row.append(InlineKeyboardButton(text=f"{grade} класс", callback_data=f"grade_{grade}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text=get_text(lang, "btn_home"), callback_data="act_restart")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_subjects_keyboard(lang: str):
    buttons = [[InlineKeyboardButton(text=name, callback_data=f"subj_{code}")] for name, code in SUBJECTS]
    buttons.append([InlineKeyboardButton(text=get_text(lang, "btn_home"), callback_data="act_restart")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_target_lang_keyboard(prefix="target_"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇩🇪 Deutsch", callback_data=f"{prefix}de"), InlineKeyboardButton(text="🇬🇧 English", callback_data=f"{prefix}en")],
        [InlineKeyboardButton(text="🇺🇦 Українська", callback_data=f"{prefix}uk"), InlineKeyboardButton(text="🇷🇺 Русский", callback_data=f"{prefix}ru")],
        [InlineKeyboardButton(text="🇫🇷 Français", callback_data=f"{prefix}fr")],
        [InlineKeyboardButton(text="🏠 Меню", callback_data="act_restart")]
    ])

def get_color_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟦 Синяя ручка", callback_data="hw_color_blue"), InlineKeyboardButton(text="⬛ Черная ручка", callback_data="hw_color_black")],
        [InlineKeyboardButton(text="🏠 Меню", callback_data="act_restart")]
    ])

def get_paper_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📐 В клетку", callback_data="hw_paper_grid"), InlineKeyboardButton(text="📝 В линию", callback_data="hw_paper_line")],
        [InlineKeyboardButton(text="📄 Чистый А4", callback_data="hw_paper_a4")],
        [InlineKeyboardButton(text="🏠 Меню", callback_data="act_restart")]
    ])

def get_length_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡ Краткий", callback_data="len_short"), InlineKeyboardButton(text="📄 Средний", callback_data="len_medium"), InlineKeyboardButton(text="📚 Подробный", callback_data="len_long")],
        [InlineKeyboardButton(text="🎒 Простыми словами", callback_data="len_simple")],
        [InlineKeyboardButton(text="🏠 Меню", callback_data="act_restart")]
    ])

def get_summary_actions_keyboard(current_lang: str):
    buttons = [
        [InlineKeyboardButton(text="💾 Сохранить", callback_data="act_save_conspect"), InlineKeyboardButton(text="✍️ Почерком", callback_data="act_handwritten")],
        [InlineKeyboardButton(text="✏️ Правка (BETA)", callback_data="act_make_edit"), InlineKeyboardButton(text="🧠 Простыми словами", callback_data="act_explain")],
        [InlineKeyboardButton(text="⚡ Короче", callback_data="act_shorter"), InlineKeyboardButton(text="📚 Подробнее", callback_data="act_longer")]
    ]
    translate_row = []
    if current_lang != "de": translate_row.append(InlineKeyboardButton(text="🇩🇪 Deutsch", callback_data="act_tr_de"))
    if current_lang != "en": translate_row.append(InlineKeyboardButton(text="🇬🇧 English", callback_data="act_tr_en"))
    if current_lang != "ru": translate_row.append(InlineKeyboardButton(text="🇷🇺 Русский", callback_data="act_tr_ru"))
    if current_lang != "uk": translate_row.append(InlineKeyboardButton(text="🇺🇦 Українська", callback_data="act_tr_uk"))

    for i in range(0, len(translate_row), 2):
        buttons.append(translate_row[i:i+2])

    buttons.append([InlineKeyboardButton(text="🔄 Следующий", callback_data="main_summary"), InlineKeyboardButton(text="🏠 Меню", callback_data="act_restart")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_task_actions_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Почему так", callback_data="task_act_explain"), InlineKeyboardButton(text="✍️ От руки", callback_data="task_act_handwritten")],
        [InlineKeyboardButton(text="✏️ Правка (BETA)", callback_data="act_make_edit"), InlineKeyboardButton(text="❓ Еще вопрос", callback_data="main_hw_task")],
        [InlineKeyboardButton(text="🏠 Меню", callback_data="act_restart")]
    ])

def get_translator_actions_keyboard(current_lang: str):
    buttons = [[InlineKeyboardButton(text="✏️ Сделать правку (BETA)", callback_data="act_make_edit")]]
    translate_row = []
    if current_lang != "de": translate_row.append(InlineKeyboardButton(text="🇩🇪 Deutsch", callback_data="tr_act_de"))
    if current_lang != "en": translate_row.append(InlineKeyboardButton(text="🇬🇧 English", callback_data="tr_act_en"))
    if current_lang != "ru": translate_row.append(InlineKeyboardButton(text="🇷🇺 Русский", callback_data="tr_act_ru"))
    if current_lang != "uk": translate_row.append(InlineKeyboardButton(text="🇺🇦 Українська", callback_data="tr_act_uk"))

    for i in range(0, len(translate_row), 2):
        buttons.append(translate_row[i:i+2])

    buttons.append([InlineKeyboardButton(text="🔄 Перевести еще", callback_data="main_translator"), InlineKeyboardButton(text="🏠 Меню", callback_data="act_restart")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def send_long_message(chat_id: int, text: str, reply_markup=None):
    max_length = 3800
    if len(text) <= max_length:
        await bot.send_message(chat_id, text, reply_markup=reply_markup)
    else:
        for i in range(0, len(text), max_length):
            chunk = text[i:i + max_length]
            is_last = (i + max_length) >= len(text)
            markup = reply_markup if is_last else None
            await bot.send_message(chat_id, chunk, reply_markup=markup)

async def process_with_ai(prompt: str, user_content, is_media: bool = False) -> str:
    system_instruction = (
        "Ты универсальный учебный помощник.\n"
        "ПРАВИЛА ОФОРМЛЕНИЯ:\n"
        "1. Не используй никакую разметку Markdown (никаких *, **, ***, #, `).\n"
        "2. Выделяй заголовки ЗАГЛАВНЫМИ БУКВАМИ.\n"
        "3. Списки оформляй с помощью дефисов (-) или цифр (1., 2.).\n"
        "4. В первой строке ответа ОБЯЗАТЕЛЬНО укажи код языка итогового текста в формате LANG:code (где code это de, en, ru, uk или fr).\n"
        "Пример первой строки: LANG:ru\n"
        "Со второй строки начинай сам ответ."
    )

    if is_media:
        contents = [system_instruction, prompt, user_content]
    else:
        contents = f"{system_instruction}\n\nЗадание: {prompt}\n\nМатериал:\n{user_content}"

    loop = asyncio.get_event_loop()

    def _call_gemini():
        last_exception = None
        for key in GEMINI_KEYS:
            try:
                client = genai.Client(api_key=key)
                response = client.models.generate_content(model='gemini-2.5-flash', contents=contents)
                return response.text
            except Exception as e:
                last_exception = e
                continue
        raise last_exception if last_exception else RuntimeError("No Gemini keys configured")

    return await loop.run_in_executor(None, _call_gemini)

# --- ГЛАВНОЕ МЕНЮ И ВЫБОР ЯЗЫКА ---

@dp.message(CommandStart())
async def start_cmd(message: types.Message, state: FSMContext):
    await register_user_activity(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await state.clear()
    
    await state.set_state(Form.waiting_for_lang_select)
    await message.answer(
        "👋 Выберите язык интерфейса / Select interface language / Wähle die Sprache:",
        reply_markup=get_start_language_keyboard()
    )

@dp.callback_query(F.data.startswith("set_lang_"))
async def set_language_handler(callback: types.CallbackQuery, state: FSMContext):
    lang_code = callback.data.split("_")[2]
    await set_user_lang(callback.from_user.id, lang_code)
    
    current_state = await state.get_state()
    if current_state == Form.waiting_for_lang_select:
        await state.set_state(Form.waiting_for_main_choice)
        await callback.message.edit_text(
            get_text(lang_code, "main_menu"),
            reply_markup=get_start_keyboard(lang_code)
        )
    else:
        await callback.answer(get_text(lang_code, "lang_changed"), show_alert=True)
        await callback.message.edit_text(
            get_text(lang_code, "main_menu"),
            reply_markup=get_start_keyboard(lang_code)
        )

@dp.callback_query(F.data == "act_restart")
async def restart_cmd(callback: types.CallbackQuery, state: FSMContext):
    await register_user_activity(callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
    user_lang = await get_user_lang(callback.from_user.id)
    await state.clear()
    await state.set_state(Form.waiting_for_main_choice)
    await callback.message.answer(get_text(user_lang, "main_menu"), reply_markup=get_start_keyboard(user_lang))
    await callback.answer()

@dp.callback_query(F.data == "check_sub_again")
async def check_sub_again_handler(callback: types.CallbackQuery, state: FSMContext):
    user_lang = await get_user_lang(callback.from_user.id)
    is_sub = await check_channel_subscription(callback.from_user.id)
    if is_sub:
        await callback.message.answer(get_text(user_lang, "sub_success"), reply_markup=get_start_keyboard(user_lang))
    else:
        await callback.answer(get_text(user_lang, "sub_required"), show_alert=True)

# --- НАСТРОЙКИ И ЛИЧНЫЙ КАБИНЕТ ---

@dp.callback_query(F.data == "open_settings")
async def open_settings_handler(callback: types.CallbackQuery):
    user_lang = await get_user_lang(callback.from_user.id)
    await callback.message.edit_text(
        get_text(user_lang, "settings_title"),
        parse_mode="HTML",
        reply_markup=get_settings_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "main_profile")
async def show_profile(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    username = callback.from_user.username
    user_lang = await get_user_lang(user_id)
    await register_user_activity(user_id, username, callback.from_user.first_name)
    
    tier, time_left = await get_user_tier_info(user_id, username)
    extra_req = await redis_client.get(f"user:{user_id}:extra_requests") or "0"
    today = datetime.now().date().isoformat()
    current_usage = await redis_client.get(f"user:{user_id}:usage:{today}") or "0"
    
    daily_limits = {"free": 5, "pro": 100, "pro_plus": "Безлимит"}
    max_daily = daily_limits.get(tier, 5)
    
    tier_names = {"free": "🟢 FREE", "pro": "⚡ PRO", "pro_plus": "👑 PRO+"}
    
    text = (
        f"{get_text(user_lang, 'profile_title')}"
        f"{get_text(user_lang, 'profile_tier')}{tier_names.get(tier, 'FREE')}\n"
        f"{get_text(user_lang, 'profile_expires')}{time_left}\n\n"
        f"{get_text(user_lang, 'profile_used')}{current_usage} из {max_daily}\n"
        f"{get_text(user_lang, 'profile_extra')}{extra_req}\n"
        f"🌐 <b>Язык интерфейса:</b> {LANG_NAMES.get(user_lang, 'Русский')}\n"
    )

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_profile_keyboard(user_lang))
    await callback.answer()

# --- АДМИНИСТРИРОВАНИЕ ---

@dp.message(F.text == "/stats")
async def get_bot_stats(message: types.Message):
    if message.from_user.id not in ADMIN_IDS and (not message.from_user.username or message.from_user.username.lower() not in ADMIN_STATUS_USERNAMES):
        return

    all_users = await redis_client.smembers("bot_users:all")
    total_users = len(all_users)
    
    now = time.time()
    active_24h = await redis_client.zcount("bot_users:active", now - 86400, "+inf")
    
    users_info_list = []
    for uid in list(all_users)[:50]:
        name = await redis_client.hget("bot_users:names", uid) or "Без имени"
        uname = name.replace("@", "") if name.startswith("@") else None
        tier, _ = await get_user_tier_info(int(uid), uname)
        tier_map = {"free": "FREE", "pro": "PRO ⚡", "pro_plus": "PRO+ 👑"}
        users_info_list.append(f"• ID `{uid}` | {name} | Тариф: **{tier_map.get(tier, 'FREE')}**")

    users_text = "\n".join(users_info_list) if users_info_list else "Список пуст"

    text = (
        f"📊 **СТАТИСТИКА БОТА**\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 **Всего пользователей:** {total_users}\n"
        f"🔥 **Активных за 24ч:** {active_24h}\n\n"
        f"**Зарегистрированные пользователи:**\n{users_text}"
    )
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text.startswith("/give_sub"))
async def give_subscription_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    args = message.text.split()
    if len(args) < 4:
        await message.answer("⚠️ Формат: `/give_sub USER_ID TIER MONTHS`\nПример: `/give_sub 123456789 pro_plus 12`", parse_mode="Markdown")
        return

    try:
        target_id = int(args[1])
        tier = args[2].lower()
        months = int(args[3])

        if tier not in ["pro", "pro_plus"]:
            await message.answer("❌ Допустимые тарифы: `pro` или `pro_plus`.", parse_mode="Markdown")
            return

        await set_user_subscription(target_id, tier, months)
        await message.answer(f"✅ Подписка **{tier.upper()}** выдана пользователю `{target_id}` на {months} мес.", parse_mode="Markdown")
        
        try:
            await bot.send_message(target_id, f"🎉 Вам активирована подписка **{tier.upper()}** на {months} мес.!")
        except Exception:
            pass

    except ValueError:
        await message.answer("❌ ID и количество месяцев должны быть числами.")

# --- ОПЛАТА ПОДПИСОК ---

@dp.callback_query(F.data == "buy_subscription")
async def show_tariffs_menu(callback: types.CallbackQuery):
    text = (
        "<b>⭐ ВЫБОР ПОДПИСКИ</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>⚡ Подписка PRO:</b>\n"
        "• До <b>100 запросов</b> в день\n"
        "• Генерация конспектов и решение ДЗ\n"
        "• Создание рукописных конспектов\n"
        "• Быстрый переводчик\n\n"
        "<b>👑 Подписка PRO+:</b>\n"
        "• <b>Безлимитное количество</b> запросов\n"
        "• Скачивание конспектов в формате <b>PDF</b>\n"
        "• Приоритетная скорость обработки\n"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_tariffs_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "choose_pro")
async def choose_pro_period(callback: types.CallbackQuery):
    await callback.message.edit_text("Выберите период подписки ⚡ <b>PRO</b>:", parse_mode="HTML", reply_markup=get_period_keyboard("pro"))
    await callback.answer()

@dp.callback_query(F.data == "choose_pro_plus")
async def choose_pro_plus_period(callback: types.CallbackQuery):
    await callback.message.edit_text("Выберите период подписки 👑 <b>PRO+</b>:", parse_mode="HTML", reply_markup=get_period_keyboard("plus"))
    await callback.answer()

@dp.callback_query(F.data == "buy_extra_requests")
async def show_extra_requests_menu(callback: types.CallbackQuery):
    await callback.message.edit_text("Выберите количество дополнительных запросов:", reply_markup=get_extra_requests_keyboard())
    await callback.answer()

@dp.callback_query(F.data.startswith(("pay_pro_", "pay_plus_", "pay_req_")))
async def send_invoice_handler(callback: types.CallbackQuery):
    data = callback.data
    
    if data.startswith("pay_pro_"):
        months = int(data.split("_")[2])
        prices_map = {1: 79, 3: 179, 6: 250, 12: 399}
        stars = prices_map[months]
        title = f"Подписка PRO ({months} мес.)"
        payload = f"sub_pro_{months}"
        
    elif data.startswith("pay_plus_"):
        months = int(data.split("_")[2])
        prices_map = {1: 159, 3: 359, 6: 499, 12: 799}
        stars = prices_map[months]
        title = f"Подписка PRO+ ({months} мес.)"
        payload = f"sub_plus_{months}"
        
    elif data.startswith("pay_req_"):
        req_count = int(data.split("_")[2])
        prices_map = {10: 25, 50: 100, 100: 179}
        stars = prices_map[req_count]
        title = f"Пакет {req_count} запросов"
        payload = f"req_{req_count}"

    await callback.bot.send_invoice(
        chat_id=callback.from_user.id,
        title=title,
        description="Оплата цифровых услуг через Telegram Stars",
        payload=payload,
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label=title, amount=stars)]
    )
    await callback.answer()

@dp.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_q: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_q.id, ok=True)

@dp.message(F.successful_payment)
async def successful_payment_handler(message: types.Message):
    payload = message.successful_payment.invoice_payload
    user_id = message.from_user.id

    if payload.startswith("sub_pro_"):
        months = int(payload.split("_")[2])
        await set_user_subscription(user_id, "pro", months)
        await message.answer(f"🎉 Подписка <b>PRO</b> успешно активирована на {months} мес.!", parse_mode="HTML")

    elif payload.startswith("sub_plus_"):
        months = int(payload.split("_")[2])
        await set_user_subscription(user_id, "pro_plus", months)
        await message.answer(f"🎉 Подписка <b>PRO+</b> успешно активирована на {months} мес.!", parse_mode="HTML")

    elif payload.startswith("req_"):
        req_count = int(payload.split("_")[1])
        await add_extra_requests(user_id, req_count)
        await message.answer(f"🎉 На ваш баланс добавлено <b>{req_count}</b> дополнительных запросов!", parse_mode="HTML")

# --- СОХРАНЕНИЕ КОНСПЕКТОВ И PDF ---

@dp.callback_query(F.data == "act_save_conspect")
async def save_conspect_handler(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    last_summary = data.get("last_summary")
    user_input = data.get("user_input", "Конспект")
    
    if last_summary:
        title = user_input[:25]
        await save_user_conspect(callback.from_user.id, title, last_summary)
        await callback.answer("✅ Конспект успешно сохранен!", show_alert=True)
    else:
        await callback.answer("Ошибка: текст не найден.", show_alert=True)

@dp.callback_query(F.data == "my_conspects")
async def list_conspects(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    username = callback.from_user.username
    conspects = await get_user_conspects(user_id)
    
    if not conspects:
        await callback.message.edit_text("У вас пока нет сохраненных конспектов.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="main_profile")]]))
        return

    tier, _ = await get_user_tier_info(user_id, username)
    builder = InlineKeyboardMarkup(inline_keyboard=[])
    
    for c_id, item in conspects.items():
        title, _ = item.split("|||", 1)
        row = [InlineKeyboardButton(text=f"📖 {title}", callback_data=f"open_c_{c_id}")]
        if tier == "pro_plus":
            row.append(InlineKeyboardButton(text="📥 PDF", callback_data=f"pdf_c_{c_id}"))
        builder.inline_keyboard.append(row)

    builder.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад в кабинет", callback_data="main_profile")])
    await callback.message.edit_text("<b>Ваши сохраненные конспекты:</b>", parse_mode="HTML", reply_markup=builder)

@dp.callback_query(F.data.startswith("open_c_"))
async def open_conspect(callback: types.CallbackQuery):
    c_id = callback.data.split("_")[2]
    conspects = await get_user_conspects(callback.from_user.id)
    if c_id in conspects:
        title, content = conspects[c_id].split("|||", 1)
        await callback.message.answer(f"<b>{title}</b>\n\n{content}", parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("pdf_c_"))
async def download_pdf(callback: types.CallbackQuery):
    tier, _ = await get_user_tier_info(callback.from_user.id, callback.from_user.username)
    if tier != "pro_plus":
        await callback.answer("Скачивание PDF доступно только на тарифе PRO+!", show_alert=True)
        return

    c_id = callback.data.split("_")[2]
    conspects = await get_user_conspects(callback.from_user.id)
    
    if c_id in conspects:
        title, content = conspects[c_id].split("|||", 1)
        pdf_bytes = create_pdf(f"{title}\n\n{content}")
        document = BufferedInputFile(pdf_bytes, filename=f"{title}.pdf")
        await callback.message.answer_document(document)
    await callback.answer()

# --- ПРАВКА (BETA) ---

@dp.callback_query(F.data == "act_make_edit")
async def start_edit_process(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(Form.waiting_for_edit_request)
    await callback.message.answer("Напишите что именно вы хотите изменить:")
    await callback.answer()

@dp.message(Form.waiting_for_edit_request)
async def process_edit_request(message: types.Message, state: FSMContext):
    edit_instruction = message.text
    data = await state.get_data()

    last_summary = data.get("last_summary")
    last_task_answer = data.get("last_task_answer")
    last_translator_text = data.get("last_text")
    current_lang = data.get("current_lang", "ru")

    if last_task_answer:
        base_text = last_task_answer
        keyboard_func = get_task_actions_keyboard
        text_prefix = "✅ Обновленный ответ"
    elif last_translator_text:
        base_text = last_translator_text
        keyboard_func = lambda: get_translator_actions_keyboard(current_lang)
        text_prefix = "🌐 Обновленный перевод"
    else:
        base_text = last_summary or ""
        keyboard_func = lambda: get_summary_actions_keyboard(current_lang)
        text_prefix = "📝 Обновленный конспект"

    status_msg = await message.answer("⏳ Вношу правки...")

    prompt = f"Внеси изменения в исходный текст строго по следующей просьбе пользователя.\nПросьба пользователя: {edit_instruction}\nСохраняй общую структуру текста."

    try:
        raw_text = await process_with_ai(prompt, base_text)
        if raw_text.startswith("LANG:"):
            _, clean_res = raw_text.split("\n", 1)
        else:
            clean_res = raw_text

        clean_edited = clean_markdown(clean_res)

        if last_task_answer:
            await state.update_data(last_task_answer=clean_edited)
            await state.set_state(Form.hw_task_ready)
        elif last_translator_text:
            await state.update_data(last_text=clean_edited)
            await state.set_state(Form.translator_ready)
        else:
            await state.update_data(last_summary=clean_edited)
            await state.set_state(Form.summary_ready)

        await status_msg.delete()
        await send_long_message(message.chat.id, f"{text_prefix}:\n\n{clean_edited}", reply_markup=keyboard_func())

    except Exception:
        await status_msg.edit_text("⚠️ Подождите 1-2 минуты, сервера перегружены")

# --- ВЫБОР РЕЖИМА И ЗАДАНИЯ ---

@dp.callback_query(F.data == "main_summary")
async def main_summary_selected(callback: types.CallbackQuery, state: FSMContext):
    user_lang = await get_user_lang(callback.from_user.id)
    await register_user_activity(callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
    await state.clear()
    await state.update_data(main_mode="summary")
    await callback.message.edit_text("Выбери формат ввода для конспекта:", reply_markup=get_input_mode_keyboard(user_lang))
    await callback.answer()

@dp.callback_query(F.data == "main_translator")
async def main_translator_selected(callback: types.CallbackQuery, state: FSMContext):
    await register_user_activity(callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
    await state.clear()
    await state.update_data(main_mode="translator")
    await state.set_state(Form.translator_waiting_for_lang)
    await callback.message.edit_text("На какой язык перевести?", reply_markup=get_target_lang_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "main_hw_task")
async def main_hw_task_selected(callback: types.CallbackQuery, state: FSMContext):
    user_lang = await get_user_lang(callback.from_user.id)
    await register_user_activity(callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
    await state.clear()
    await state.set_state(Form.hw_task_waiting_for_mode)
    await callback.message.edit_text("📚 Раздел Задания / ДЗ.\nВыбери способ ввода:", reply_markup=get_task_input_mode_keyboard(user_lang))
    await callback.answer()

@dp.callback_query(F.data.startswith("task_mode_"), Form.hw_task_waiting_for_mode)
async def task_mode_selected(callback: types.CallbackQuery, state: FSMContext):
    user_lang = await get_user_lang(callback.from_user.id)
    mode = callback.data.split("_")[2]
    await state.update_data(task_mode=mode)
    await state.set_state(Form.hw_task_waiting_for_grade)
    await callback.message.edit_text("В каком ты классе?", reply_markup=get_grades_keyboard(user_lang))
    await callback.answer()

@dp.callback_query(F.data.startswith("grade_"), Form.hw_task_waiting_for_grade)
async def task_grade_selected(callback: types.CallbackQuery, state: FSMContext):
    user_lang = await get_user_lang(callback.from_user.id)
    grade = callback.data.split("_")[1]
    await state.update_data(task_grade=grade)
    await state.set_state(Form.hw_task_waiting_for_subject)
    await callback.message.edit_text("Выбери предмет:", reply_markup=get_subjects_keyboard(user_lang))
    await callback.answer()

@dp.callback_query(F.data.startswith("subj_"), Form.hw_task_waiting_for_subject)
async def task_subject_selected(callback: types.CallbackQuery, state: FSMContext):
    subj = callback.data.split("_")[1]
    await state.update_data(task_subject=subj)
    await state.set_state(Form.hw_task_waiting_for_content)
    
    data = await state.get_data()
    if data.get("task_mode") == "text":
        await callback.message.edit_text("Пришли текст с заданием или вопросом:")
    else:
        await callback.message.edit_text("Отправь фото с заданием:")
    await callback.answer()

@dp.message(Form.hw_task_waiting_for_content)
async def process_task_content(message: types.Message, state: FSMContext):
    data = await state.get_data()
    task_mode = data.get("task_mode", "text")

    if task_mode == "text" and not message.text:
        await message.answer("Пожалуйста, отправь текстовое задание.")
        return
    elif task_mode == "photo" and not message.photo:
        await message.answer("Пожалуйста, отправь изображение с заданием.")
        return

    allowed = await check_and_increment_limit(message.from_user.id, message.from_user.username)
    if not allowed:
        await message.answer("⚠️ Вы исчерпали лимит запросов. Обновите подписку в Личном кабинете!")
        return

    grade = data.get("task_grade", "7")
    subj_code = data.get("task_subject", "other")
    subj_name = dict(SUBJECTS).get(subj_code, "Предмет")

    user_lang = await get_user_lang(message.from_user.id)
    prompt = f"Реши задание по предмету '{subj_name}' для {grade} класса на языке {LANG_NAMES.get(user_lang, 'Русский')}.\nСначала напиши ИТОГОВЫЙ ОТВЕТ, а затем краткое решение."
    status_msg = await message.answer("⏳ Решаю задание...")

    try:
        if task_mode == "photo":
            photo = message.photo[-1]
            file_info = await bot.get_file(photo.file_id)
            downloaded_file = await bot.download_file(file_info.file_path)
            image_input = Image.open(downloaded_file)
            
            raw_text = await process_with_ai(prompt, image_input, is_media=True)
            task_q = "[Изображение задания]"
        else:
            raw_text = await process_with_ai(prompt, message.text, is_media=False)
            task_q = message.text

        clean_ans = clean_markdown(raw_text.split("\n", 1)[1] if raw_text.startswith("LANG:") else raw_text)
        await state.update_data(last_task_question=task_q, last_task_answer=clean_ans)
        await state.set_state(Form.hw_task_ready)

        await status_msg.delete()
        await send_long_message(message.chat.id, f"✅ Ответ по предмету {subj_name} ({grade} класс):\n\n{clean_ans}", reply_markup=get_task_actions_keyboard())
    except Exception:
        await status_msg.edit_text("⚠️ Подождите 1-2 минуты, сервера перегружены")

@dp.callback_query(F.data == "task_act_explain", Form.hw_task_ready)
async def task_explain(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    q, ans, grade = data.get("last_task_question", ""), data.get("last_task_answer", ""), data.get("task_grade", "7")

    prompt = f"Объясни максимально подробно и простыми словами шаг за шагом для ученика {grade} класса."
    status_msg = await callback.message.edit_text("⏳ Подготавливаю объяснение...")

    try:
        raw_text = await process_with_ai(prompt, f"Вопрос: {q}\nОтвет: {ans}")
        exp_text = raw_text.split("\n", 1)[1] if raw_text.startswith("LANG:") else raw_text
        clean_exp = clean_markdown(exp_text)
        await status_msg.delete()
        await send_long_message(callback.message.chat.id, f"🔍 Подробное объяснение:\n\n{clean_exp}", reply_markup=get_task_actions_keyboard())
    except Exception:
        await status_msg.edit_text("⚠️ Подождите 1-2 минуты, сервера перегружены")
    await callback.answer()

@dp.callback_query(F.data == "task_act_handwritten", Form.hw_task_ready)
async def task_to_handwritten(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.update_data(last_summary=data.get("last_task_answer", ""))
    await state.set_state(Form.hw_waiting_for_lang)
    await callback.message.answer("На каком языке оформить рукописный ответ?", reply_markup=get_target_lang_keyboard("hw_lang_"))
    await callback.answer()

# --- ПЕРЕВОДЧИК И ВВОД ---

@dp.callback_query(F.data.startswith("target_"), Form.translator_waiting_for_lang)
async def translator_lang_selected(callback: types.CallbackQuery, state: FSMContext):
    user_lang = await get_user_lang(callback.from_user.id)
    await state.update_data(target_lang=callback.data.split("_")[1])
    await callback.message.edit_text("Выбери формат ввода текста для перевода:", reply_markup=get_input_mode_keyboard(user_lang))
    await callback.answer()

@dp.callback_query(F.data.startswith("mode_"))
async def process_mode_selection(callback: types.CallbackQuery, state: FSMContext):
    mode = callback.data.split("_")[1]
    await state.update_data(input_mode=mode)
    data = await state.get_data()

    prompts = {"text": "Пришли текст:", "topic": "Напиши тему:", "photo": "Отправь текст с фото:", "video": "Отправь ссылку на видео:"}
    await state.set_state(Form.waiting_for_content if data.get("main_mode") == "summary" else Form.translator_waiting_for_content)
    await callback.message.edit_text(prompts[mode])
    await callback.answer()

# --- ОБРАБОТКА КОНСПЕКТА ---

@dp.message(Form.waiting_for_content)
async def process_summary_content(message: types.Message, state: FSMContext):
    if not message.text:
        await message.answer("Пожалуйста, отправь текстовую информацию.")
        return
    await state.update_data(user_input=message.text)
    await state.set_state(Form.waiting_for_length)
    await message.answer("Выбери стиль и размер конспекта:", reply_markup=get_length_keyboard())

@dp.callback_query(F.data.startswith("len_"), Form.waiting_for_length)
async def process_summary_length(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(length_choice=callback.data.split("_")[1])
    await state.set_state(Form.summary_waiting_for_lang)
    await callback.message.edit_text("На каком языке составить конспект?", reply_markup=get_target_lang_keyboard("sum_lang_"))
    await callback.answer()

@dp.callback_query(F.data.startswith("sum_lang_"), Form.summary_waiting_for_lang)
async def process_summary_generate(callback: types.CallbackQuery, state: FSMContext):
    allowed = await check_and_increment_limit(callback.from_user.id, callback.from_user.username)
    if not allowed:
        await callback.message.answer("⚠️ Вы исчерпали лимит запросов. Обновите подписку в Личном кабинете!")
        await callback.answer()
        return

    target_lang = callback.data.split("_")[2]
    data = await state.get_data()
    target_lang_name = LANG_NAMES.get(target_lang, "Русский")

    length_instructions = {
        "short": f"Сделай максимально краткий конспект на языке {target_lang_name}.",
        "medium": f"Сделай сбалансированный конспект на языке {target_lang_name}.",
        "long": f"Сделай подробный конспект на языке {target_lang_name}.",
        "simple": f"Объясни тему простым языком на языке {target_lang_name}."
    }

    status_msg = await callback.message.edit_text("⏳ Анализирую данные и подготавливаю конспект...")

    try:
        raw_text = await process_with_ai(length_instructions[data.get("length_choice")], data.get("user_input"))
        current_lang = target_lang
        if raw_text.startswith("LANG:"):
            first_line, summary_text = raw_text.split("\n", 1)
            detected_lang = first_line.replace("LANG:", "").strip().lower()
            if detected_lang in LANG_NAMES: current_lang = detected_lang
        else:
            summary_text = raw_text

        clean_summary = clean_markdown(summary_text)
        await state.update_data(last_summary=clean_summary, current_lang=current_lang)
        await state.set_state(Form.summary_ready)

        await status_msg.delete()
        await send_long_message(callback.message.chat.id, f"📝 Результат ({LANG_NAMES.get(current_lang, 'Язык')}):\n\n{clean_summary}", reply_markup=get_summary_actions_keyboard(current_lang))
    except Exception:
        await status_msg.edit_text("⚠️ Подождите 1-2 минуты, сервера перегружены")
    await callback.answer()

# --- РУКОПИСНЫЙ ПОЧЕРК ---

@dp.callback_query(F.data == "act_handwritten")
async def start_handwritten_process(callback: types.CallbackQuery, state: FSMContext):
    user_lang = await get_user_lang(callback.from_user.id)
    await register_user_activity(callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
    
    # 1. Проверка подписки на канал
    is_subscribed = await check_channel_subscription(callback.from_user.id)
    if not is_subscribed:
        await callback.message.answer(
            get_text(user_lang, "sub_required"),
            reply_markup=get_subscribe_keyboard(user_lang),
            parse_mode="Markdown"
        )
        await callback.answer()
        return

    # 2. Проверка лимитов
    allowed = await check_and_increment_limit(callback.from_user.id, callback.from_user.username)
    if not allowed:
        await callback.message.answer("⚠️ Вы исчерпали лимит запросов. Обновите подписку в Личном кабинете!")
        await callback.answer()
        return

    await state.set_state(Form.hw_waiting_for_lang)
    await callback.message.answer("На каком языке оформить рукописный конспект?", reply_markup=get_target_lang_keyboard("hw_lang_"))
    await callback.answer()

@dp.callback_query(F.data.startswith("hw_lang_"), Form.hw_waiting_for_lang)
async def handwritten_lang_selected(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(hw_lang=callback.data.split("_")[2])
    await state.set_state(Form.hw_waiting_for_color)
    await callback.message.edit_text("Какого цвета ручкой написать конспект?", reply_markup=get_color_keyboard())
    await callback.answer()

@dp.callback_query(F.data.startswith("hw_color_"), Form.hw_waiting_for_color)
async def handwritten_color_selected(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(hw_color=callback.data.split("_")[2])
    await state.set_state(Form.hw_waiting_for_paper)
    await callback.message.edit_text("Выбери формат листка:", reply_markup=get_paper_keyboard())
    await callback.answer()

@dp.callback_query(F.data.startswith("hw_paper_"), Form.hw_waiting_for_paper)
async def handwritten_generate_final(callback: types.CallbackQuery, state: FSMContext):
    paper = callback.data.split("_")[2]
    data = await state.get_data()
    status_msg = await callback.message.edit_text("✍️ Рисую рукописный конспект...")

    try:
        raw_text = await process_with_ai(f"Переведи этот конспект на язык {LANG_NAMES.get(data.get('hw_lang', 'ru'), 'Русский')}.", data.get("last_summary", ""))
        text_to_draw = raw_text.split("\n", 1)[1] if raw_text.startswith("LANG:") else raw_text

        img_bytes = generate_handwritten_image(clean_markdown(text_to_draw), paper, data.get("hw_color", "blue"))
        photo_file = BufferedInputFile(img_bytes.read(), filename="handwritten_note.png")

        done_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Сделать правку (BETA)", callback_data="act_make_edit")],
            [InlineKeyboardButton(text="🏠 Меню", callback_data="act_restart")]
        ])

        await status_msg.delete()
        await callback.message.answer_photo(photo=photo_file, caption="✨ Твой рукописный конспект готов!", reply_markup=done_keyboard)
        await state.clear()
    except Exception:
        await status_msg.edit_text("⚠️ Подождите 1-2 минуты, сервера перегружены")
    await callback.answer()

# --- ОБРАБОТКА ПЕРЕВОДА ---

@dp.message(Form.translator_waiting_for_content)
async def process_translator_content(message: types.Message, state: FSMContext):
    if not message.text:
        await message.answer("Пожалуйста, отправь текстовую информацию.")
        return

    allowed = await check_and_increment_limit(message.from_user.id, message.from_user.username)
    if not allowed:
        await message.answer("⚠️ Вы исчерпали лимит запросов. Обновите подписку в Личном кабинете!")
        return

    data = await state.get_data()
    target_lang_code = data.get("target_lang", "ru")
    status_msg = await message.answer(f"⏳ Перевожу на {LANG_NAMES.get(target_lang_code, 'Русский')} язык...")

    try:
        raw_text = await process_with_ai(f"Переведи на {LANG_NAMES.get(target_lang_code, 'Русский')} язык.", message.text)
        translated_text = raw_text.split("\n", 1)[1] if raw_text.startswith("LANG:") else raw_text
        clean_translated = clean_markdown(translated_text)

        await state.update_data(last_text=clean_translated, current_lang=target_lang_code)
        await state.set_state(Form.translator_ready)

        await status_msg.delete()
        await send_long_message(message.chat.id, f"🌐 Перевод ({LANG_NAMES.get(target_lang_code, 'Язык')}):\n\n{clean_translated}", reply_markup=get_translator_actions_keyboard(target_lang_code))
    except Exception:
        await status_msg.edit_text("⚠️ Подождите 1-2 минуты, сервера перегружены")

# --- ДЕЙСТВИЯ С КОНСПЕКТОМ И ПЕРЕВОДОМ ---

@dp.callback_query(F.data.startswith("act_"), Form.summary_ready)
async def process_summary_action(callback: types.CallbackQuery, state: FSMContext):
    action = callback.data.split("_")[1]
    data = await state.get_data()
    last_summary, current_lang = data.get("last_summary", ""), data.get("current_lang", "ru")

    if action in ["shorter", "longer", "explain"]:
        prompts = {
            "shorter": f"Сократи этот конспект в 2 раза, сохранив язык ({LANG_NAMES.get(current_lang, 'Русский')}).",
            "longer": f"Разверни этот конспект подробнее, сохранив язык ({LANG_NAMES.get(current_lang, 'Русский')}).",
            "explain": f"Объясни этот конспект еще проще, сохранив язык ({LANG_NAMES.get(current_lang, 'Русский')})."
        }
        status_msg = await callback.message.edit_text("⏳ Обрабатываю текст...")
        try:
            raw_text = await process_with_ai(prompts[action], last_summary)
            new_summary = clean_markdown(raw_text.split("\n", 1)[1] if raw_text.startswith("LANG:") else raw_text)
            await state.update_data(last_summary=new_summary)
            await status_msg.delete()
            await send_long_message(callback.message.chat.id, f"📝 Обновленный конспект:\n\n{new_summary}", reply_markup=get_summary_actions_keyboard(current_lang))
        except Exception:
            await status_msg.edit_text("⚠️ Подождите 1-2 минуты, сервера перегружены")

    elif action == "tr":
        target_lang_code = callback.data.split("_")[2]
        status_msg = await callback.message.edit_text(f"⏳ Перевожу конспект на {LANG_NAMES[target_lang_code]} язык...")
        try:
            raw_text = await process_with_ai(f"Переведи данный конспект на {LANG_NAMES[target_lang_code]} язык.", last_summary)
            translated_summary = clean_markdown(raw_text.split("\n", 1)[1] if raw_text.startswith("LANG:") else raw_text)
            await state.update_data(last_summary=translated_summary, current_lang=target_lang_code)
            await status_msg.delete()
            await send_long_message(callback.message.chat.id, f"📝 Перевод ({LANG_NAMES[target_lang_code]}):\n\n{translated_summary}", reply_markup=get_summary_actions_keyboard(target_lang_code))
        except Exception:
            await status_msg.edit_text("⚠️ Подождите 1-2 минуты, сервера перегружены")

    await callback.answer()

@dp.callback_query(F.data.startswith("tr_act_"), Form.translator_ready)
async def process_translator_action(callback: types.CallbackQuery, state: FSMContext):
    target_lang_code = callback.data.split("_")[2]
    data = await state.get_data()

    status_msg = await callback.message.edit_text(f"⏳ Перевожу на {LANG_NAMES[target_lang_code]} язык...")
    try:
        raw_text = await process_with_ai(f"Переведи данный текст на {LANG_NAMES[target_lang_code]} язык.", data.get("last_text", ""))
        translated_text = clean_markdown(raw_text.split("\n", 1)[1] if raw_text.startswith("LANG:") else raw_text)
        await state.update_data(last_text=translated_text, current_lang=target_lang_code)
        await status_msg.delete()
        await send_long_message(callback.message.chat.id, f"🌐 Перевод ({LANG_NAMES[target_lang_code]}):\n\n{translated_text}", reply_markup=get_translator_actions_keyboard(target_lang_code))
    except Exception:
        await status_msg.edit_text("⚠️ Подождите 1-2 минуты, сервера перегружены")

    await callback.answer()

async def main():
    if not BOT_TOKEN:
        print("Ошибка: BOT_TOKEN не найден! Заполните файл .env")
        return
    print("Бот с поддержкой языков и настроек запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
