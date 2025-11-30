import telebot
from telebot import types
import json
import time
from dotenv import load_dotenv
import os


load_dotenv()


TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
SPEAKER_PASSWORD = os.getenv("SPEAKER_PASSWORD")

bot = telebot.TeleBot(TOKEN)

# --------------------- JSON ---------------------

DB_PATH = os.getenv("DB_PATH")

def load_db():
    try:
        with open(DB_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"roles": {}, "events": [], "speakers": {}, "questions": [], "password_attempts": {}}

def save_db():
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=4, ensure_ascii=False)

db = load_db()

# --------------------- HELPERS ---------------------

BACK_KEYS = {"🔙 Назад", "⬅ Назад", "Назад"}

def is_back(text):
    return isinstance(text, str) and text.strip() in BACK_KEYS

def set_role(uid, role):
    db["roles"][str(uid)] = role
    save_db()

def remove_user(uid):
    """Полное удаление пользователя из базы (roles, speakers, questions as from/to)."""
    uid_s = str(uid)
    db.get("roles", {}).pop(uid_s, None)
    db.get("speakers", {}).pop(uid_s, None)
    db["questions"] = [q for q in db.get("questions", []) if q.get("from") != int(uid) and q.get("to") != int(uid)]
    save_db()

def get_role(uid):
    return db["roles"].get(str(uid), "user")

def register_speaker(uid, name):
    db.setdefault("speakers", {})[str(uid)] = name
    save_db()

def safe_username(uid):
    try:
        ch = bot.get_chat(int(uid))
        if getattr(ch, "username", None):
            return f"@{ch.username}"
        return getattr(ch, "first_name", None) or f"id{uid}"
    except Exception:
        return f"id{uid}"

def send_main_menu(chat_id, user_id):
    role = get_role(user_id)
    bot.send_message(chat_id, f"Меню обновлено. Ваша роль: *{role}*", parse_mode="Markdown", reply_markup=get_menu(role))


def notify_all(text, exclude=None):
    """Рассылка всем пользователям (кроме исключённого ID)."""
    for uid in list(db.get("roles", {}).keys()):
        if str(uid) == str(exclude):
            continue
        try:
            bot.send_message(int(uid), text, parse_mode="Markdown")
        except Exception:
            pass


def send_broadcast_message(message):
    text = message.text
    notify_all(f"Сообщение от организатора:\n\n{text}", exclude=message.from_user.id)
    bot.send_message(message.chat.id, "✅ Рассылка отправлена!")


def get_current_speaker():
    now = int(time.time())
    for e in db["events"]:
        if e["start_time"] <= now <= e["end_time"]:
            return e["speaker_id"], e["title"]
    return None, None


# --------------------- MENUS ---------------------

def menu_user():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("📅 Посмотреть мероприятия")
    kb.add("❓ Задать вопрос спикеру")
    kb.add("📨 Мои ответы")
    kb.add("🎤 Стать спикером")
    kb.add("🔙 Назад")
    return kb

def menu_speaker():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("➕ Создать мероприятие")
    kb.add("📅 Посмотреть мероприятия")
    kb.add("📨 Мои вопросы")
    kb.add("🔙 Назад")
    return kb

def menu_admin():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("➕ Создать мероприятие")
    kb.add("📅 Посмотреть мероприятия")
    kb.add("🔧 Админ-панель")
    kb.add("🔙 Назад")
    return kb

def get_menu(role):
    if role == "admin":
        return menu_admin()
    if role == "speaker":
        return menu_speaker()
    return menu_user()

# --------------------- START ---------------------

@bot.message_handler(commands=["start"])
def start(message):
    uid = str(message.from_user.id)
    if uid not in db["roles"]:
        db["roles"][uid] = "admin" if message.from_user.id == ADMIN_ID else "user"
        save_db()
    send_main_menu(message.chat.id, message.from_user.id)


@bot.message_handler(func=lambda m: is_back(m.text))
def handle_back(message):

    send_main_menu(message.chat.id, message.from_user.id)

# --------------------- BECOME SPEAKER ---------------------

MAX_TRIES = 3
BLOCK_SECONDS = 300  

@bot.message_handler(func=lambda m: m.text == "🎤 Стать спикером")
def req_speaker(message):
    uid = str(message.from_user.id)
    db.setdefault("password_attempts", {})
    db["password_attempts"].setdefault(uid, {"tries": 0})
    attempts = db["password_attempts"][uid]

    if attempts.get("blocked_until", 0) > time.time():
        wait = int(attempts["blocked_until"] - time.time())
        return bot.send_message(message.chat.id, f"⛔ Блокировка. Попробуйте через {wait} сек.")
    bot.send_message(message.chat.id, "Введите пароль спикера (или 🔙 Назад):")
    bot.register_next_step_handler(message, check_speaker_password)

def check_speaker_password(message):
    if is_back(message.text):
        return send_main_menu(message.chat.id, message.from_user.id)

    uid = str(message.from_user.id)
    attempts = db.setdefault("password_attempts", {}).setdefault(uid, {"tries": 0})

    if message.text == SPEAKER_PASSWORD:
        set_role(uid, "speaker")
        register_speaker(uid, message.from_user.first_name)
        db["password_attempts"][uid] = {"tries": 0}
        save_db()
        return bot.send_message(message.chat.id, "🎤 Вы стали спикером!", reply_markup=get_menu("speaker"))

    attempts["tries"] = attempts.get("tries", 0) + 1
    if attempts["tries"] >= MAX_TRIES:
        attempts["blocked_until"] = time.time() + BLOCK_SECONDS
        save_db()
        return bot.send_message(message.chat.id, f"⛔ Неверно {MAX_TRIES} раз. Блокировка {BLOCK_SECONDS // 60} минут.")
    save_db()
    bot.send_message(message.chat.id, f"❌ Неверно! Осталось попыток: {MAX_TRIES - attempts['tries']}\nПопробуйте снова или нажмите 🔙 Назад.")
    bot.register_next_step_handler(message, check_speaker_password)

# --------------------- CREATE EVENT ---------------------

@bot.message_handler(func=lambda m: m.text == "➕ Создать мероприятие")
def create_event_step1(message):
    if get_role(message.from_user.id) not in ("speaker", "admin"):
        return bot.send_message(message.chat.id, "⛔ Только спикер/админ.")
    bot.send_message(message.chat.id, "Введите название мероприятия (или 🔙 Назад):")
    bot.register_next_step_handler(message, create_event_step2)

def create_event_step2(message):
    if is_back(message.text):
        return send_main_menu(message.chat.id, message.from_user.id)
    title = message.text
    bot.send_message(message.chat.id, "Введите описание мероприятия (или 🔙 Назад):")
    bot.register_next_step_handler(message, create_event_step3, title)

def create_event_step3(message, title):
    if is_back(message.text):
        return send_main_menu(message.chat.id, message.from_user.id)
    description = message.text
    uid = str(message.from_user.id)
    db.setdefault("events", []).append({
        "title": title,
        "description": description,
        "speaker_id": uid,
        "speaker_name": db.get("speakers", {}).get(uid, message.from_user.first_name),
        "created_at": int(time.time())
    })
    save_db()
    bot.send_message(message.chat.id, "✔ Мероприятие создано!", reply_markup=get_menu(get_role(message.from_user.id)))
    notify_all(f"Новое мероприятие добавлено!\n\n*{title}*\n{description}", exclude=message.from_user.id)

# --------------------- EVENTS LIST ---------------------

@bot.message_handler(func=lambda m: m.text == "📅 Посмотреть мероприятия")
def show_events(message):
    events = db.get("events", [])
    if not events:
        return bot.send_message(message.chat.id, "Нет мероприятий.", reply_markup=get_menu(get_role(message.from_user.id)))
    txt = "📅 *Мероприятия:*\n\n"
    for i, e in enumerate(events, 1):
        txt += f"*{i}. {e['title']}*\n{e['description']}\n🎤 Спикер: {e.get('speaker_name')}\n\n"
    bot.send_message(message.chat.id, txt, parse_mode="Markdown", reply_markup=get_menu(get_role(message.from_user.id)))

# --------------------- USER QUESTIONS ---------------------

@bot.message_handler(func=lambda m: m.text == "❓ Задать вопрос спикеру")
def choose_speaker(message):
    speakers = db.get("speakers", {})
    if not speakers:
        return bot.send_message(message.chat.id, "Нет спикеров.", reply_markup=get_menu(get_role(message.from_user.id)))
    kb = types.InlineKeyboardMarkup()
    for uid, name in speakers.items():
        kb.add(types.InlineKeyboardButton(name, callback_data=f"ask_{uid}"))
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="ask_back"))
    bot.send_message(message.chat.id, "Выберите спикера:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "ask_back")
def ask_back(call):
    send_main_menu(call.message.chat.id, call.from_user.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("ask_"))
def ask_question_start(call):
    speaker_id = call.data.split("_", 1)[1]
    bot.send_message(call.message.chat.id, "Введите вопрос (или 🔙 Назад):")
    bot.register_next_step_handler(call.message, send_question_to_speaker, speaker_id)

def send_question_to_speaker(message, speaker_id):
    if is_back(message.text):
        return send_main_menu(message.chat.id, message.from_user.id)
    db.setdefault("questions", []).append({
        "from": message.from_user.id,
        "to": int(speaker_id),
        "question": message.text,
        "answer": None,
        "created_at": int(time.time())
    })
    save_db()
    try:
        bot.send_message(int(speaker_id), f"❓ Новый вопрос от {safe_username(message.from_user.id)}:\n\n{message.text}")
    except Exception:
        pass
    bot.send_message(message.chat.id, "✔ Вопрос отправлен!", reply_markup=get_menu(get_role(message.from_user.id)))

# --------------------- SPEAKER QUESTIONS ---------------------

@bot.message_handler(func=lambda m: m.text == "📨 Мои вопросы")
def speaker_questions(message):
    uid = message.from_user.id
    qs = [q for q in db.get("questions", []) if q["to"] == uid]
    if not qs:
        return bot.send_message(message.chat.id, "У вас нет вопросов.", reply_markup=get_menu(get_role(uid)))
    kb = types.InlineKeyboardMarkup()
    for idx, q in enumerate(qs):
        kb.add(types.InlineKeyboardButton(f"{'✅' if q.get('answer') else '❓'} Вопрос #{idx+1}", callback_data=f"answer_{idx}"))
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="speaker_questions_back"))
    bot.send_message(message.chat.id, "Ваши вопросы:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "speaker_questions_back")
def speaker_questions_back(call):
    send_main_menu(call.message.chat.id, call.from_user.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("answer_"))
def answer_question_start(call):
    idx = int(call.data.split("_", 1)[1])
    qs = [q for q in db.get("questions", []) if q["to"] == call.from_user.id]
    if idx < 0 or idx >= len(qs):
        return bot.answer_callback_query(call.id, "Неверный индекс.")
    q = qs[idx]
    bot.send_message(call.message.chat.id, f"Вопрос:\n{q['question']}\nВведите ответ (или 🔙 Назад):")
    bot.register_next_step_handler(call.message, answer_question_finish, q)

def answer_question_finish(message, q):
    if is_back(message.text):
        return send_main_menu(message.chat.id, message.from_user.id)
    q["answer"] = message.text
    q["answered_at"] = int(time.time())
    save_db()
    try:
        bot.send_message(q["from"], f"💬 Ответ спикера:\n\n{q['answer']}")
    except Exception:
        pass
    bot.send_message(message.chat.id, "✔ Ответ отправлен!", reply_markup=get_menu(get_role(message.from_user.id)))

# --------------------- USER ANSWERS ---------------------

@bot.message_handler(func=lambda m: m.text == "📨 Мои ответы")
def user_answers(message):
    uid = message.from_user.id
    ans = [q for q in db.get("questions", []) if q["from"] == uid and q.get("answer")]
    if not ans:
        return bot.send_message(message.chat.id, "У вас нет ответов.", reply_markup=get_menu(get_role(uid)))
    txt = "📨 *Ваши ответы:*\n\n"
    for q in ans:
        txt += f"*Вопрос:* {q['question']}\n*Ответ:* {q['answer']}\n\n"
    bot.send_message(message.chat.id, txt, parse_mode="Markdown", reply_markup=get_menu(get_role(uid)))

# --------------------- ADMIN PANEL (helpers) ---------------------

def build_admin_panel_kb():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("Пользователи", callback_data="admin_users"))
    kb.add(types.InlineKeyboardButton("Спикеры", callback_data="admin_speakers"))
    kb.add(types.InlineKeyboardButton("Мероприятия", callback_data="admin_events"))
    kb.add(types.InlineKeyboardButton("Вопросы", callback_data="admin_questions"))
    kb.add(types.InlineKeyboardButton("Рассылка", callback_data="admin_broadcast"))
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back"))
    return kb

def open_admin_panel_message(chat_id):
    """Отправить новую админ-панель сообщением (для message handlers)."""
    kb = build_admin_panel_kb()
    bot.send_message(chat_id, "🔧 Админ-панель:", reply_markup=kb)

def edit_admin_panel_inplace(call):
    """Редактировать текущее сообщение callback'а под админ-панель."""
    kb = build_admin_panel_kb()
    try:
        bot.edit_message_text("🔧 Админ-панель:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb)
    except Exception:

        open_admin_panel_message(call.message.chat.id)

# --------------------- ADMIN PANEL (entry) ---------------------

@bot.message_handler(func=lambda m: m.text == "🔧 Админ-панель")
def admin_panel_open(message):
    if message.from_user.id != ADMIN_ID:
        return bot.send_message(message.chat.id, "⛔ У вас нет прав.")
    open_admin_panel_message(message.chat.id)

# --------------------- ADMIN CALLBACKS ---------------------

@bot.callback_query_handler(func=lambda c: c.data.startswith("admin_") and c.data != "admin_back")
def admin_menu(call):
    if call.from_user.id != ADMIN_ID:
        return bot.answer_callback_query(call.id, "Нет прав.")
    action = call.data.split("_", 1)[1]

    # USERS
    if action == "users":
        kb = types.InlineKeyboardMarkup()

        for uid, role in db.get("roles", {}).items():
            kb.add(types.InlineKeyboardButton(f"{uid} ({role})", callback_data=f"user_{uid}"))
        kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back"))
        return bot.edit_message_text("Пользователи:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb)

    # SPEAKERS
    if action == "speakers":
        kb = types.InlineKeyboardMarkup()
        for uid, name in db.get("speakers", {}).items():
            kb.add(types.InlineKeyboardButton(f"{name} ({uid})", callback_data=f"speaker_{uid}"))
        kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back"))
        return bot.edit_message_text("Спикеры:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb)

    # EVENTS
    if action == "events":
        kb = types.InlineKeyboardMarkup()
        for i, e in enumerate(db.get("events", [])):
            kb.add(types.InlineKeyboardButton(f"{i+1}. {e['title']}", callback_data=f"event_{i}"))
        kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back"))
        return bot.edit_message_text("Мероприятия:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb)

    # QUESTIONS
    if action == "questions":
        kb = types.InlineKeyboardMarkup()
        for i, q in enumerate(db.get("questions", [])):
            kb.add(types.InlineKeyboardButton(f"{'✅' if q.get('answer') else '❓'} Q#{i+1}", callback_data=f"q_{i}"))
        kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back"))
        return bot.edit_message_text("Вопросы:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb)

    # BROADCAST MESSAGE
    if action == "broadcast":
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "Введите текст рассылки:")
        bot.register_next_step_handler(call.message, send_broadcast_message)
        return

@bot.callback_query_handler(func=lambda c: c.data == "admin_back")
def admin_back(call):

    edit_admin_panel_inplace(call)

# --------------------- ADMIN ACTIONS (users/speakers/events/questions) ---------------------

@bot.callback_query_handler(func=lambda c: any(c.data.startswith(x) for x in ("user_", "speaker_", "event_", "q_")))
def admin_actions(call):
    if call.from_user.id != ADMIN_ID:
        return bot.answer_callback_query(call.id, "Нет прав.")
    data = call.data

    # ---------- USERS ----------
    if data.startswith("user_") and not data.startswith("user_to_user_") and not data.startswith("user_delete_"):
        uid = data.split("_", 1)[1]
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("Сделать USER", callback_data=f"user_to_user_{uid}"))
        kb.add(types.InlineKeyboardButton("Удалить пользователя", callback_data=f"user_delete_{uid}"))
        kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_users"))
        return bot.edit_message_text(f"Пользователь {uid}\nРоль: {get_role(uid)}", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb)

    if data.startswith("user_to_user_"):
        uid = data.split("_", 3)[3]
        set_role(uid, "user")
        save_db()
        bot.answer_callback_query(call.id, "Роль изменена")


        kb = types.InlineKeyboardMarkup()
        for u, role in db.get("roles", {}).items():
            kb.add(types.InlineKeyboardButton(f"{u} ({role})", callback_data=f"user_{u}"))
        kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back"))
        return bot.edit_message_text("Пользователи:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb)


    if data.startswith("user_delete_"):
        uid = data.split("_", 2)[2]
        remove_user(uid)
        bot.answer_callback_query(call.id, "Пользователь удалён")
        kb = types.InlineKeyboardMarkup()
        for u, role in db.get("roles", {}).items():
            kb.add(types.InlineKeyboardButton(f"{u} ({role})", callback_data=f"user_{u}"))
        kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back"))
        return bot.edit_message_text("Пользователи:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb)

    # ---------- SPEAKERS ----------
    if data.startswith("speaker_") and not data.startswith("speaker_delete_"):
        uid = data.split("_", 1)[1]
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("Удалить спикера", callback_data=f"speaker_delete_{uid}"))
        kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_speakers"))
        return bot.edit_message_text(f"Спикер {uid}\nИмя: {db.get('speakers', {}).get(uid, '-')}", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb)

    if data.startswith("speaker_delete_"):
        uid = data.split("_", 2)[2]
        db.get("speakers", {}).pop(uid, None)
        db.get("roles", {}).pop(uid, None) 
        save_db()
        bot.answer_callback_query(call.id, "Спикер удалён")

        kb = types.InlineKeyboardMarkup()
        for u, name in db.get("speakers", {}).items():
            kb.add(types.InlineKeyboardButton(f"{name} ({u})", callback_data=f"speaker_{u}"))
        kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back"))
        return bot.edit_message_text("Спикеры:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb)


    # ---------- EVENTS ----------
    if data.startswith("event_") and not data.startswith("event_delete_"):
        try:
            idx = int(data.split("_", 1)[1])
        except Exception:
            return bot.answer_callback_query(call.id, "Неверный индекс.")
        events = db.get("events", [])
        if idx < 0 or idx >= len(events):
            return bot.answer_callback_query(call.id, "Индекс вне диапазона.")
        e = events[idx]
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("Удалить мероприятие", callback_data=f"event_delete_{idx}"))
        kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_events"))
        txt = f"Мероприятие {idx+1}:\n{e['title']}\n\n{e['description']}\nСпикер: {e.get('speaker_name')}"
        return bot.edit_message_text(txt, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb)

    if data.startswith("event_delete_"):
        try:
            idx = int(data.split("_", 2)[2])
        except Exception:
            return bot.answer_callback_query(call.id, "Неверный индекс.")
        events = db.get("events", [])
        if 0 <= idx < len(events):
            ev = events.pop(idx)
            save_db()
            notify_all(f"Мероприятие удалено:\n\n❌ *{ev['title']}*")
            bot.answer_callback_query(call.id, f"Мероприятие удалено: {ev['title']}")
            kb = types.InlineKeyboardMarkup()
            for i, e in enumerate(events):
                kb.add(types.InlineKeyboardButton(f"{i+1}. {e['title']}", callback_data=f"event_{i}"))
            kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_events"))
            return bot.edit_message_text("Мероприятия:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb)
        else:
            return bot.answer_callback_query(call.id, "Индекс вне диапазона.")

    # ---------- QUESTIONS ----------
    if data.startswith("q_") and not data.startswith("q_delete_"):
        try:
            idx = int(data.split("_", 1)[1])
        except Exception:
            return bot.answer_callback_query(call.id, "Неверный индекс.")
        qs = db.get("questions", [])
        if idx < 0 or idx >= len(qs):
            return bot.answer_callback_query(call.id, "Индекс вне диапазона.")
        q = qs[idx]
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("Удалить вопрос", callback_data=f"q_delete_{idx}"))
        kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_questions"))
        txt = (f"Вопрос #{idx+1}\nОт: {safe_username(q['from'])}\nКому: {safe_username(q['to'])}\n\n"
               f"❓ {q['question']}\n💬 Ответ: {q.get('answer') or 'Нет'}")
        return bot.edit_message_text(txt, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=kb)

    if data.startswith("q_delete_"):
        qid = int(data.split("_", 2)[2])

        questions = db.get("questions", [])
        if 0 <= qid < len(questions):
            removed = questions.pop(qid)
            save_db()
            bot.answer_callback_query(call.id, "Вопрос удалён")
        else:
            bot.answer_callback_query(call.id, "Индекс вне диапазона")

        questions = db.get("questions", [])
        kb = types.InlineKeyboardMarkup()

        if questions:
            for idx, q in enumerate(questions):
                text = q.get("text", "Без текста")
                sender = q.get("from")
                kb.add(types.InlineKeyboardButton(
                    f"{idx+1}. {text[:30]}... от {sender}",
                    callback_data=f"question_{idx}"
                ))
        else:
            kb.add(types.InlineKeyboardButton("Нет вопросов", callback_data="none"))

        kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back"))

        return bot.edit_message_text(
            "Вопросы:",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=kb
        )

# --------------------- RUN ---------------------

if __name__ == "__main__":
    print("Bot started...")
    bot.polling(none_stop=True)
