import telebot
import requests
import dotenv
import os
import json
from datetime import datetime, time as dt_time
from telebot import types
import threading
import time
import schedule

dotenv.load_dotenv(".env")

user_histories = {}
user_quizzes = {}
daily_quiz = {}
bot = telebot.TeleBot(os.getenv("TOKEN"))
FOLDER_ID = os.getenv("FOLDER_ID")
API_KEY = os.getenv("API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
GEN_TIME = os.getenv("GEN_TIME", "10:00")

with open('praz.json', 'r', encoding='utf-8') as f:
    holidays = json.load(f)


def load_data():
    try:
        with open('data.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {"users": {}, "gifts": [], "notifications": {}, "daily_quiz": {}}


def save_data(data):
    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def check_registration(message):
    data = load_data()
    user_id = str(message.chat.id)
    if user_id not in data["users"] or not data["users"][user_id].get("registered"):
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📝 Зарегистрироваться", callback_data="register"))
        bot.send_message(message.chat.id, "👋 Добро пожаловать! Для использования бота необходимо зарегистрироваться.", reply_markup=markup)
        return False
    return True


@bot.callback_query_handler(func=lambda call: call.data == "register")
def start_registration(call):
    try:
        bot.answer_callback_query(call.id)
    except:
        pass
    bot.edit_message_text("Введите ваше имя и фамилию:", call.message.chat.id, call.message.message_id)
    bot.register_next_step_handler(call.message, process_name)


def process_name(message):
    user_id = str(message.chat.id)
    data = load_data()
    
    if user_id not in data["users"]:
        data["users"][user_id] = {"points": 0, "perfect_quizzes": 0, "correct_answers": 0, "gifts_bought": 0, "last_quiz": "", "registered": False}
    
    data["users"][user_id]["name"] = message.text.strip()
    save_data(data)
    
    msg = bot.send_message(message.chat.id, "Введите ваш класс:")
    bot.register_next_step_handler(msg, process_class)


def process_class(message):
    user_id = str(message.chat.id)
    data = load_data()
    
    data["users"][user_id]["class"] = message.text.strip()
    data["users"][user_id]["registered"] = True
    data["users"][user_id]["points"] = 2  # 2 очка за регистрацию
    save_data(data)
    
    bot.send_message(message.chat.id, f"✅ Регистрация завершена!\n\nИмя: {data['users'][user_id]['name']}\nКласс: {data['users'][user_id]['class']}\n\n🎁 Вы получили 2 очка за регистрацию!\n\nИспользуйте /info для просмотра команд.")


def get_user_name(user):
    data = load_data()
    user_id = str(user.id)
    if user_id in data["users"] and data["users"][user_id].get("registered"):
        return data["users"][user_id]["name"]
    if user.username:
        return f"@{user.username}"
    return user.first_name or f"ID{user.id}"


def get_current_date():
    """Возвращает текущую дату с учетом override_date из админки"""
    data = load_data()
    if "override_date" in data and data["override_date"]:
        return data["override_date"]
    return datetime.now().strftime("%Y-%m-%d")


def get_today_holiday():
    data = load_data()
    
    # Используем override_date если установлена, иначе текущую дату
    if "override_date" in data and data["override_date"]:
        date_str = data["override_date"]
        now = datetime.strptime(date_str, "%Y-%m-%d")
    else:
        now = datetime.now()
    
    month = str(now.month)
    day = str(now.day)
    return holidays.get(month, {}).get(day, "День без праздника"), now.strftime("%d.%m.%Y")


def ask_yandex_gpt(messages, folder_id, api_key):
    url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Api-Key {api_key}"
    }
    data = {
        "modelUri": f"gpt://{folder_id}/yandexgpt-lite",
        "completionOptions": {
            "stream": False,
            "temperature": 0.7,
            "maxTokens": 2000
        },
        "messages": messages
    }
    response = requests.post(url, headers=headers, json=data)
    result = response.json()
    return result["result"]["alternatives"][0]["message"]["text"]


def parse_quiz_advanced(text):
    questions = []
    blocks = text.strip().split('\n\n')
    
    for block in blocks:
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if len(lines) < 2:
            continue
        
        # Multiple choice
        if any(l.startswith(('A)', 'B)', 'C)', 'D)')) for l in lines):
            if 'Сопоставь' in lines[0] or 'Расставь' in lines[0]:
                # Matching or Sequence
                question = lines[0]
                items = [l for l in lines[1:-1]]
                answer_line = lines[-1]
                
                if 'Сопоставь' in question:
                    answer = answer_line.split(':')[-1].strip()
                    questions.append({"type": "matching", "q": question, "items": items, "ans": answer})
                elif 'Расставь' in question:
                    answer = answer_line.split(':')[-1].strip()
                    questions.append({"type": "sequence", "q": question, "items": items, "ans": answer})
            else:
                # Standard multiple choice
                question = lines[0]
                options = [l for l in lines[1:5] if l.startswith(('A)', 'B)', 'C)', 'D)'))]
                if len(options) == 4 and len(lines) >= 6:
                    answer = lines[-1].split(':')[-1].strip()[0]
                    questions.append({"type": "multiple_choice", "q": question, "opts": options, "ans": answer})
        
        # True/False
        elif 'Правда' in lines[-1] or 'Ложь' in lines[-1]:
            question = lines[0]
            answer = 'Правда' if 'Правда' in lines[-1] else 'Ложь'
            questions.append({"type": "true_false", "q": question, "ans": answer})
        
        # Open answer
        elif len(lines) >= 2 and 'Ответ:' in lines[-1]:
            question = lines[0]
            answer = lines[-1].split('Ответ:')[-1].strip()
            if not any(c in answer for c in ['A)', 'B)', 'C)', 'D)', '1)', '2)', '3)']):
                questions.append({"type": "open_answer", "q": question, "ans": answer})
    
    return questions


def parse_quiz(text):
    questions = []
    blocks = text.strip().split('\n\n')
    
    for block in blocks:
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if len(lines) >= 6:
            question = lines[0]
            options = [lines[i] for i in range(1, 5)]
            answer = lines[5].split(':')[-1].strip()[0]
            questions.append({"type": "multiple_choice", "q": question, "opts": options, "ans": answer})
    
    return questions


def generate_daily_quiz():
    global daily_quiz
    holiday, date = get_today_holiday()
    today = get_current_date()
    
    print(f"Генерация квиза на {date}...")
    
    # Сохраняем предыдущий квиз перед генерацией нового
    data = load_data()
    if daily_quiz and daily_quiz.get("questions"):
        data["previous_quiz"] = daily_quiz.copy()
        save_data(data)
    
    prompt = f"""Сегодня {date}, праздник: {holiday}. Создай разнообразный квиз из 6 вопросов разных типов (НЕ про дату празднования):

1-2. Тип: multiple_choice
Формат:
Вопрос?
A) вариант
B) вариант
C) вариант
D) вариант
Ответ: буква

3-4. Тип: true_false
Формат:
Утверждение
Ответ: Правда/Ложь

5. Тип: matching
Формат:
Сопоставь:
1) Событие А
2) Событие Б
3) Событие В
A) Дата/факт А
B) Дата/факт Б
C) Дата/факт В
Ответ: случайный порядок (например: 1-C, 2-A, 3-B или 1-B, 2-C, 3-A). НЕ используй порядок 1-A, 2-B, 3-C!

6. Тип: sequence
Формат:
Расставь в хронологическом порядке:
A) Событие 1
B) Событие 2
C) Событие 3
Ответ: случайный порядок (например: C, A, B или B, C, A). НЕ используй порядок A, B, C!

Между вопросами пустая строка."""
    
    messages = [
        {"role": "system", "text": "Ты создаёшь интересные квизы про праздники. Не задавай вопросы про дату празднования."},
        {"role": "user", "text": prompt}
    ]
    
    quiz_text = ask_yandex_gpt(messages, FOLDER_ID, API_KEY)
    questions = parse_quiz_advanced(quiz_text)
    
    if questions:
        daily_quiz = {"questions": questions, "date": today, "holiday": holiday}
        
        data = load_data()
        data["daily_quiz"] = daily_quiz
        save_data(data)
        
        print(f"Квиз создан: {len(questions)} вопросов")
        notify_users()
    else:
        print("Ошибка генерации квиза")


def notify_users():
    data = load_data()
    holiday = daily_quiz.get("holiday", "праздник")
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🎯 Пройти квиз", callback_data="start_quiz"))
    
    # Добавляем кнопку с ответами на предыдущий квиз
    if "previous_quiz" in data and data["previous_quiz"]:
        markup.add(types.InlineKeyboardButton("📝 Ответы на предыдущий квиз", callback_data="show_prev_answers"))
    
    markup.add(types.InlineKeyboardButton("🔕 Отписаться", callback_data="unsubscribe"))
    
    for user_id in data["users"]:
        if not data.get("notifications", {}).get(user_id, True):
            continue
        try:
            bot.send_message(int(user_id), f"🎉 Новый квиз!\n\nСегодня: {holiday}\n\nПройдите квиз и заработайте очки!", reply_markup=markup)
        except:
            pass


@bot.callback_query_handler(func=lambda call: call.data == "show_prev_answers")
def show_prev_answers(call):
    bot.answer_callback_query(call.id)
    data = load_data()
    user_id = str(call.message.chat.id)
    
    if "previous_quiz" not in data or not data["previous_quiz"]:
        bot.send_message(call.message.chat.id, "❌ Нет данных о предыдущем квизе")
        return
    
    prev_quiz = data["previous_quiz"]
    holiday = prev_quiz.get("holiday", "праздник")
    date = prev_quiz.get("date", "")
    
    # Получаем ответы пользователя на предыдущий квиз
    user_answers = data["users"].get(user_id, {}).get("last_quiz_answers", {})
    
    text = f"📝 Ответы на квиз от {date}\n🎉 {holiday}\n\n"
    
    if user_answers and user_answers.get("date") == date:
        # Пользователь проходил этот квиз - показываем его ответы
        text += f"Ваш результат: {user_answers['score']}/{user_answers['total']}\n\n"
        
        for i, q in enumerate(prev_quiz["questions"]):
            user_ans = user_answers["answers"][i] if i < len(user_answers["answers"]) else None
            correct_ans = q["ans"]
            q_type = q.get("type", "multiple_choice")
            
            # Проверяем правильность ответа
            if q_type == "open_answer" and isinstance(user_ans, dict):
                is_correct = user_ans.get("is_correct", False)
                user_ans_text = user_ans.get("text", "")
            elif q_type in ["matching", "sequence"]:
                is_correct = str(user_ans).replace(" ", "").lower() == str(correct_ans).replace(" ", "").lower()
                user_ans_text = str(user_ans)
            else:
                is_correct = user_ans == correct_ans or (len(str(user_ans)) == 1 and str(user_ans) == str(correct_ans)[0])
                user_ans_text = str(user_ans)
            
            status = "✅" if is_correct else "❌"
            text += f"{status} {i+1}. {q['q']}\n"
            text += f"Ваш ответ: {user_ans_text}\n"
            text += f"Правильный ответ: {correct_ans}\n\n"
    else:
        # Пользователь не проходил - показываем только правильные ответы
        text += "Вы не проходили этот квиз.\n\n"
        for i, q in enumerate(prev_quiz["questions"]):
            text += f"{i+1}. {q['q']}\n"
            text += f"✅ Правильный ответ: {q['ans']}\n\n"
    
    bot.send_message(call.message.chat.id, text)


@bot.callback_query_handler(func=lambda call: call.data == "unsubscribe")
def unsubscribe(call):
    data = load_data()
    user_id = str(call.message.chat.id)
    if "notifications" not in data:
        data["notifications"] = {}
    data["notifications"][user_id] = False
    save_data(data)
    try:
        bot.answer_callback_query(call.id, "🔕 Вы отписались от уведомлений")
    except:
        pass
    bot.edit_message_text("Вы отписались от уведомлений о новых квизах.\nИспользуйте /quiz чтобы пройти квиз.", call.message.chat.id, call.message.message_id)


@bot.callback_query_handler(func=lambda call: call.data == "start_quiz")
def start_quiz_callback(call):
    data = load_data()
    user_id = str(call.message.chat.id)
    if user_id not in data["users"] or not data["users"][user_id].get("registered"):
        try:
            bot.answer_callback_query(call.id, "❌ Необходимо зарегистрироваться")
        except:
            pass
        bot.delete_message(call.message.chat.id, call.message.message_id)
        check_registration(call.message)
        return
    try:
        bot.answer_callback_query(call.id)
    except:
        pass
    
    # Проверка, не начат ли уже квиз
    if call.message.chat.id in user_quizzes:
        try:
            bot.answer_callback_query(call.id, "❌ Вы уже начали квиз!")
        except:
            pass
        return
    
    bot.delete_message(call.message.chat.id, call.message.message_id)
    quiz(call.message)


def parse_quiz(text):
    questions = []
    blocks = text.strip().split('\n\n')
    
    for block in blocks:
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if len(lines) >= 6:
            question = lines[0]
            options = [lines[i] for i in range(1, 5)]
            answer = lines[5].split(':')[-1].strip()[0]
            questions.append({"q": question, "opts": options, "ans": answer})
    
    return questions


@bot.message_handler(commands=['start', 'info'])
def start(message):
    if not check_registration(message):
        return
    
    data = load_data()
    user_id = str(message.chat.id)
    subscribed = data.get("notifications", {}).get(user_id, True)
    
    text = "Это бот для праздничных квизов.\n/quiz - квиз про сегодняшний праздник\n/shop - магазин подарков\n/balance - ваш баланс\n/leaderboard - топ игроков\n/notifications - управление уведомлениями"
    
    if not subscribed:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔔 Подписаться на уведомления", callback_data="subscribe"))
        bot.send_message(message.chat.id, text, reply_markup=markup)
    else:
        bot.send_message(message.chat.id, text)


@bot.message_handler(commands=['leaderboard'])
def leaderboard(message):
    if not check_registration(message):
        return
    data = load_data()
    user_id = str(message.chat.id)
    subscribed = data.get("notifications", {}).get(user_id, True)
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("💰 Очки", callback_data="lb_points"),
        types.InlineKeyboardButton("🎁 Подарки", callback_data="lb_gifts")
    )
    markup.add(
        types.InlineKeyboardButton("🏆 5/5 квизы", callback_data="lb_perfect"),
        types.InlineKeyboardButton("✅ Ответы", callback_data="lb_answers")
    )
    
    if not subscribed:
        markup.add(types.InlineKeyboardButton("🔔 Подписаться на уведомления", callback_data="subscribe"))
    
    bot.send_message(message.chat.id, "📊 Выберите категорию:", reply_markup=markup)


@bot.message_handler(commands=['notifications'])
def notifications_cmd(message):
    if not check_registration(message):
        return
    data = load_data()
    user_id = str(message.chat.id)
    enabled = data.get("notifications", {}).get(user_id, True)
    
    markup = types.InlineKeyboardMarkup()
    if enabled:
        markup.add(types.InlineKeyboardButton("🔕 Отключить уведомления", callback_data="unsubscribe"))
        bot.send_message(message.chat.id, "🔔 Уведомления включены", reply_markup=markup)
    else:
        markup.add(types.InlineKeyboardButton("🔔 Включить уведомления", callback_data="subscribe"))
        bot.send_message(message.chat.id, "🔕 Уведомления отключены", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == "subscribe")
def subscribe(call):
    data = load_data()
    user_id = str(call.message.chat.id)
    if "notifications" not in data:
        data["notifications"] = {}
    data["notifications"][user_id] = True
    save_data(data)
    try:
        bot.answer_callback_query(call.id, "🔔 Вы подписались на уведомления")
    except:
        pass
    bot.edit_message_text("Вы подписались на уведомления о новых квизах!", call.message.chat.id, call.message.message_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith('lb_'))
def show_leaderboard(call):
    data = load_data()
    category = call.data.split('_')[1]
    
    if category == "points":
        sorted_users = sorted(data["users"].items(), key=lambda x: x[1].get("points", 0), reverse=True)[:10]
        title = "💰 Топ-10 по очкам"
        key = "points"
    elif category == "gifts":
        sorted_users = sorted(data["users"].items(), key=lambda x: x[1].get("gifts_bought", 0), reverse=True)[:10]
        title = "🎁 Топ-10 по подаркам"
        key = "gifts_bought"
    elif category == "perfect":
        sorted_users = sorted(data["users"].items(), key=lambda x: x[1].get("perfect_quizzes", 0), reverse=True)[:10]
        title = "🏆 Топ-10 по 5/5 квизам"
        key = "perfect_quizzes"
    else:
        sorted_users = sorted(data["users"].items(), key=lambda x: x[1].get("correct_answers", 0), reverse=True)[:10]
        title = "✅ Топ-10 по правильным ответам"
        key = "correct_answers"
    
    text = f"{title}\n\n"
    for i, (user_id, user_data) in enumerate(sorted_users):
        value = user_data.get(key, 0)
        name = user_data.get("name", f"ID{user_id}")
        text += f"{i+1}. {name}: {value}\n"
    
    if not sorted_users:
        text += "Пока нет данных"
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("💰 Очки", callback_data="lb_points"),
        types.InlineKeyboardButton("🎁 Подарки", callback_data="lb_gifts")
    )
    markup.add(
        types.InlineKeyboardButton("🏆 5/5 квизы", callback_data="lb_perfect"),
        types.InlineKeyboardButton("✅ Ответы", callback_data="lb_answers")
    )
    
    bot.edit_message_text(text + "\n📊 Выберите категорию:", call.message.chat.id, call.message.message_id, reply_markup=markup)
    try:
        bot.answer_callback_query(call.id)
    except:
        pass


@bot.message_handler(commands=['quiz'])
def quiz(message):
    if not check_registration(message):
        return
    data = load_data()
    user_id = str(message.chat.id)
    today = get_current_date()
    subscribed = data.get("notifications", {}).get(user_id, True)
    
    if user_id not in data["users"]:
        data["users"][user_id] = {"points": 0, "perfect_quizzes": 0, "correct_answers": 0, "gifts_bought": 0, "name": get_user_name(message.from_user), "last_quiz": "", "registered": True}
        save_data(data)
    
    # Проверка, не начат ли уже квиз
    if message.chat.id in user_quizzes:
        text = "❌ Вы уже начали квиз! Завершите его, прежде чем начинать новый."
        if not subscribed:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔔 Подписаться на уведомления", callback_data="subscribe"))
            bot.send_message(message.chat.id, text, reply_markup=markup)
        else:
            bot.send_message(message.chat.id, text)
        return
    
    if data["users"][user_id].get("last_quiz") == today:
        text = "❌ Вы уже проходили квиз сегодня! Приходите завтра."
        if not subscribed:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔔 Подписаться на уведомления", callback_data="subscribe"))
            bot.send_message(message.chat.id, text, reply_markup=markup)
        else:
            bot.send_message(message.chat.id, text)
        return
    
    if not daily_quiz or daily_quiz.get("date") != today:
        text = f"⏳ Квиз еще не готов. Квизы генерируются в {GEN_TIME} каждый день."
        if not subscribed:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔔 Подписаться на уведомления", callback_data="subscribe"))
            bot.send_message(message.chat.id, text, reply_markup=markup)
        else:
            bot.send_message(message.chat.id, text)
        return
    
    holiday = daily_quiz["holiday"]
    questions = daily_quiz["questions"]
    
    print(f"\n=== Квиз для пользователя {get_user_name(message.from_user)} ===")
    for i, q in enumerate(questions):
        print(f"{i+1}. {q['q']}")
        print(f"   Правильный ответ: {q['ans']}")
    print("=" * 50 + "\n")
    
    user_quizzes[message.chat.id] = {"questions": questions, "current": 0, "score": 0, "answers": [], "holiday": holiday, "start_date": today}
    bot.send_message(message.chat.id, f"🎉 Сегодня: {holiday}\n\nНачинаем квиз!")
    send_question(message.chat.id)


def send_question(chat_id):
    quiz = user_quizzes[chat_id]
    q = quiz["questions"][quiz["current"]]
    q_type = q.get("type", "multiple_choice")
    
    markup = types.InlineKeyboardMarkup()
    
    if q_type == "multiple_choice":
        for opt in q["opts"]:
            letter = opt[0]
            markup.add(types.InlineKeyboardButton(opt, callback_data=f"ans_{letter}"))
        msg = bot.send_message(chat_id, f"❓ Вопрос {quiz['current']+1}/{len(quiz['questions'])}:\n\n{q['q']}", reply_markup=markup)
    
    elif q_type == "true_false":
        markup.add(
            types.InlineKeyboardButton("✅ Правда", callback_data="ans_Правда"),
            types.InlineKeyboardButton("❌ Ложь", callback_data="ans_Ложь")
        )
        msg = bot.send_message(chat_id, f"❓ Вопрос {quiz['current']+1}/{len(quiz['questions'])}:\n\n{q['q']}", reply_markup=markup)
    
    elif q_type == "matching":
        items_text = "\n".join(q["items"])
        quiz["matching_state"] = {"selections": []}
        
        # Показываем оба столбца кнопок
        markup = types.InlineKeyboardMarkup(row_width=2)
        left_items = [item for item in q["items"] if item[0] in ['1', '2', '3', '4', '5']]
        right_items = [item for item in q["items"] if item[0] in ['A', 'B', 'C', 'D', 'E']]
        
        # Создаем два столбца
        for left, right in zip(left_items, right_items):
            markup.row(
                types.InlineKeyboardButton(f"◻️ {left}", callback_data=f"match_left_{left[0]}"),
                types.InlineKeyboardButton(f"◻️ {right}", callback_data=f"match_right_{right[0]}")
            )
        
        # Если количество элементов не совпадает, добавляем оставшиеся
        if len(left_items) > len(right_items):
            for item in left_items[len(right_items):]:
                markup.add(types.InlineKeyboardButton(f"◻️ {item}", callback_data=f"match_left_{item[0]}"))
        elif len(right_items) > len(left_items):
            for item in right_items[len(left_items):]:
                markup.add(types.InlineKeyboardButton(f"◻️ {item}", callback_data=f"match_right_{item[0]}"))
        
        msg = bot.send_message(chat_id, f"❓ Вопрос {quiz['current']+1}/{len(quiz['questions'])}:\n\n{q['q']}\n{items_text}\n\n👆 Выберите пару (сначала слева, потом справа):", reply_markup=markup)
    
    elif q_type == "sequence":
        items_text = "\n".join(q["items"])
        quiz["sequence_order"] = []
        
        # Показываем все элементы для выбора
        for item in q["items"]:
            if item[0] in ['A', 'B', 'C', 'D', 'E']:
                markup.add(types.InlineKeyboardButton(item, callback_data=f"seq_{item[0]}"))
        
        msg = bot.send_message(chat_id, f"❓ Вопрос {quiz['current']+1}/{len(quiz['questions'])}:\n\n{q['q']}\n{items_text}\n\n👆 Выберите элементы по порядку:", reply_markup=markup)
    
    quiz["last_msg_id"] = msg.message_id


@bot.callback_query_handler(func=lambda call: call.data.startswith('match_'))
def handle_matching(call):
    chat_id = call.message.chat.id
    if chat_id not in user_quizzes:
        try:
            bot.answer_callback_query(call.id, "❌ Квиз не найден")
        except:
            pass
        return
    
    quiz = user_quizzes[chat_id]
    today = get_current_date()
    
    if quiz.get("start_date") != today:
        try:
            bot.answer_callback_query(call.id, "⏰ Время вышло!")
        except:
            pass
        bot.send_message(chat_id, "⏰ Квиз прерван: наступил новый день. Результаты не засчитаны.")
        del user_quizzes[chat_id]
        return
    
    q = quiz["questions"][quiz["current"]]
    state = quiz["matching_state"]
    left_items = [item for item in q["items"] if item[0] in ['1', '2', '3', '4', '5']]
    right_items = [item for item in q["items"] if item[0] in ['A', 'B', 'C', 'D', 'E']]
    
    if call.data.startswith("match_left_"):
        # Выбрали левый элемент
        left_choice = call.data.split("_")[-1]
        state["current_left"] = left_choice
        
        # Обновляем кнопки с желтым квадратом для выбранного левого элемента
        markup = types.InlineKeyboardMarkup(row_width=2)
        
        for left, right in zip(left_items, right_items):
            left_selected = any(sel.startswith(f"{left[0]}-") for sel in state["selections"])
            right_selected = any(sel.endswith(f"-{right[0]}") for sel in state["selections"])
            
            # Желтый квадрат для текущего выбора слева
            if left[0] == left_choice and not left_selected:
                left_icon = "🟨"
            elif left_selected:
                left_icon = "✅"
            else:
                left_icon = "◻️"
            
            right_icon = "✅" if right_selected else "◻️"
            
            markup.row(
                types.InlineKeyboardButton(f"{left_icon} {left}", callback_data=f"match_left_{left[0]}"),
                types.InlineKeyboardButton(f"{right_icon} {right}", callback_data=f"match_right_{right[0]}")
            )
        
        items_text = "\n".join(q["items"])
        bot.edit_message_text(
            f"❓ Вопрос {quiz['current']+1}/{len(quiz['questions'])}:\n\n{q['q']}\n{items_text}\n\nВыбрано: {left_choice}\n👆 Теперь выберите справа:",
            chat_id, call.message.message_id, reply_markup=markup
        )
        try:
            bot.answer_callback_query(call.id, f"Выбрано: {left_choice}. Теперь выберите справа.")
        except:
            pass
    
    elif call.data.startswith("match_right_"):
        # Выбрали правый элемент
        if "current_left" not in state:
            try:
                bot.answer_callback_query(call.id, "⚠️ Сначала выберите элемент слева!")
            except:
                pass
            return
        
        right_choice = call.data.split("_")[-1]
        left_choice = state["current_left"]
        state["selections"].append(f"{left_choice}-{right_choice}")
        del state["current_left"]
        
        # Проверяем, все ли пары выбраны
        left_items = [item for item in q["items"] if item[0] in ['1', '2', '3', '4', '5']]
        if len(state["selections"]) >= len(left_items):
            # Все пары выбраны, проверяем ответ
            user_answer = ", ".join(state["selections"])
            correct = q["ans"].replace(" ", "")
            user_clean = user_answer.replace(" ", "")
            
            quiz["answers"].append(user_answer)
            
            try:
                bot.delete_message(chat_id, call.message.message_id)
            except:
                pass
            
            if user_clean.lower() == correct.lower():
                quiz["score"] += 1
                quiz["points_earned"] = quiz.get("points_earned", 0) + 3  # +2 очка за сложный вопрос + 1 за правильный
                msg = bot.send_message(chat_id, "✅ Правильно! +3 очка")
            else:
                msg = bot.send_message(chat_id, f"❌ Неправильно. Правильный ответ: {q['ans']}")
            
            time.sleep(1)
            try:
                bot.delete_message(chat_id, msg.message_id)
            except:
                pass
            
            quiz["current"] += 1
            
            if quiz["current"] < len(quiz["questions"]):
                send_question(chat_id)
            else:
                finish_quiz(chat_id, call.from_user)
        else:
            # Обновляем кнопки с отметками выбранных
            markup = types.InlineKeyboardMarkup(row_width=2)
            right_items = [item for item in q["items"] if item[0] in ['A', 'B', 'C', 'D', 'E']]
            
            # Создаем два столбца с отметками
            for left, right in zip(left_items, right_items):
                left_selected = any(sel.startswith(f"{left[0]}-") for sel in state["selections"])
                right_selected = any(sel.endswith(f"-{right[0]}") for sel in state["selections"])
                left_icon = "✅" if left_selected else "◻️"
                right_icon = "✅" if right_selected else "◻️"
                markup.row(
                    types.InlineKeyboardButton(f"{left_icon} {left}", callback_data=f"match_left_{left[0]}"),
                    types.InlineKeyboardButton(f"{right_icon} {right}", callback_data=f"match_right_{right[0]}")
                )
            
            # Если количество элементов не совпадает, добавляем оставшиеся
            if len(left_items) > len(right_items):
                for item in left_items[len(right_items):]:
                    is_selected = any(sel.startswith(f"{item[0]}-") for sel in state["selections"])
                    icon = "✅" if is_selected else "◻️"
                    markup.add(types.InlineKeyboardButton(f"{icon} {item}", callback_data=f"match_left_{item[0]}"))
            elif len(right_items) > len(left_items):
                for item in right_items[len(left_items):]:
                    is_selected = any(sel.endswith(f"-{item[0]}") for sel in state["selections"])
                    icon = "✅" if is_selected else "◻️"
                    markup.add(types.InlineKeyboardButton(f"{icon} {item}", callback_data=f"match_right_{item[0]}"))
            
            selections_text = ", ".join(state["selections"])
            items_text = "\n".join(q["items"])
            bot.edit_message_text(
                f"❓ Вопрос {quiz['current']+1}/{len(quiz['questions'])}:\n\n{q['q']}\n{items_text}\n\nВыбрано: {selections_text}\n👆 Выберите следующую пару:",
                chat_id, call.message.message_id, reply_markup=markup
            )
            try:
                bot.answer_callback_query(call.id, f"Пара {left_choice}-{right_choice} добавлена")
            except:
                pass


@bot.callback_query_handler(func=lambda call: call.data.startswith('seq_'))
def handle_sequence(call):
    chat_id = call.message.chat.id
    if chat_id not in user_quizzes:
        try:
            bot.answer_callback_query(call.id, "❌ Квиз не найден")
        except:
            pass
        return
    
    quiz = user_quizzes[chat_id]
    today = get_current_date()
    
    if quiz.get("start_date") != today:
        try:
            bot.answer_callback_query(call.id, "⏰ Время вышло!")
        except:
            pass
        bot.send_message(chat_id, "⏰ Квиз прерван: наступил новый день. Результаты не засчитаны.")
        del user_quizzes[chat_id]
        return
    
    q = quiz["questions"][quiz["current"]]
    choice = call.data.split("_")[-1]
    
    # Добавляем выбор в последовательность
    if choice not in quiz["sequence_order"]:
        quiz["sequence_order"].append(choice)
    
    # Проверяем, все ли элементы выбраны
    items = [item for item in q["items"] if item[0] in ['A', 'B', 'C', 'D', 'E']]
    if len(quiz["sequence_order"]) >= len(items):
        # Все элементы выбраны, проверяем ответ
        user_answer = ", ".join(quiz["sequence_order"])
        correct = q["ans"].replace(" ", "")
        user_clean = user_answer.replace(" ", "")
        
        quiz["answers"].append(user_answer)
        
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except:
            pass
        
        if user_clean.lower() == correct.lower():
            quiz["score"] += 1
            quiz["points_earned"] = quiz.get("points_earned", 0) + 3
            msg = bot.send_message(chat_id, "✅ Правильно! +3 очка")
        else:
            msg = bot.send_message(chat_id, f"❌ Неправильно. Правильный ответ: {q['ans']}")
        
        time.sleep(1)
        try:
            bot.delete_message(chat_id, msg.message_id)
        except:
            pass
        
        quiz["current"] += 1
        
        if quiz["current"] < len(quiz["questions"]):
            send_question(chat_id)
        else:
            finish_quiz(chat_id, call.from_user)
    else:
        # Обновляем сообщение с текущей последовательностью
        markup = types.InlineKeyboardMarkup()
        for item in items:
            if item[0] not in quiz["sequence_order"]:
                markup.add(types.InlineKeyboardButton(item, callback_data=f"seq_{item[0]}"))
        
        sequence_text = " → ".join(quiz["sequence_order"])
        items_text = "\n".join(q["items"])
        bot.edit_message_text(
            f"❓ Вопрос {quiz['current']+1}/{len(quiz['questions'])}:\n\n{q['q']}\n{items_text}\n\nПоследовательность: {sequence_text}\n👆 Выберите следующий элемент:",
            chat_id, call.message.message_id, reply_markup=markup
        )
        try:
            bot.answer_callback_query(call.id)
        except:
            pass


@bot.callback_query_handler(func=lambda call: call.data.startswith('ans_'))
def check_answer(call):
    chat_id = call.message.chat.id
    if chat_id not in user_quizzes:
        try:
            bot.answer_callback_query(call.id, "❌ Квиз не найден")
        except:
            pass
        return
    
    quiz = user_quizzes[chat_id]
    today = get_current_date()
    
    # Проверка смены дня
    if quiz.get("start_date") != today:
        try:
            bot.answer_callback_query(call.id, "⏰ Время вышло! Квиз был на другой день.")
        except:
            pass
        bot.send_message(chat_id, "⏰ Квиз прерван: наступил новый день. Результаты не засчитаны.")
        del user_quizzes[chat_id]
        return
    
    answer = call.data.split('_', 1)[1]
    q = quiz["questions"][quiz["current"]]
    correct = q["ans"]
    
    quiz["answers"].append(answer)
    
    if answer == correct or (len(answer) == 1 and answer == correct[0]):
        quiz["score"] += 1
        quiz["points_earned"] = quiz.get("points_earned", 0) + 1  # +1 очко за правильный ответ
        try:
            bot.answer_callback_query(call.id, "✅ Правильно!")
        except:
            pass
    else:
        try:
            bot.answer_callback_query(call.id, f"❌ Неправильно. Ответ: {correct}")
        except:
            pass
    
    try:
        bot.delete_message(chat_id, quiz["last_msg_id"])
    except:
        pass
    
    quiz["current"] += 1
    
    if quiz["current"] < len(quiz["questions"]):
        send_question(chat_id)
    else:
        finish_quiz(chat_id, call.from_user)


def process_open_answer(message, chat_id):
    if chat_id not in user_quizzes:
        return
    
    quiz = user_quizzes[chat_id]
    today = get_current_date()
    
    # Проверка смены дня
    if quiz.get("start_date") != today:
        bot.send_message(chat_id, "⏰ Квиз прерван: наступил новый день. Результаты не засчитаны.")
        del user_quizzes[chat_id]
        return
    
    q = quiz["questions"][quiz["current"]]
    user_answer = message.text.strip()
    
    # Проверка через LLM
    prompt = f"Вопрос: {q['q']}\nПравильный ответ: {q['ans']}\nОтвет пользователя: {user_answer}\n\nОцени, правильно ли ответил пользователь. Ответь только 'Правильно' или 'Неправильно'."
    messages = [
        {"role": "system", "text": "Ты проверяешь ответы на вопросы квиза."},
        {"role": "user", "text": prompt}
    ]
    
    result = ask_yandex_gpt(messages, FOLDER_ID, API_KEY).strip()
    is_correct = "правильно" in result.lower() and "неправильно" not in result.lower()
    
    # Сохраняем результат проверки вместе с ответом
    quiz["answers"].append({"text": user_answer, "is_correct": is_correct})
    
    # Удаляем сообщения
    try:
        bot.delete_message(chat_id, quiz["last_msg_id"])
    except:
        pass
    try:
        bot.delete_message(chat_id, message.message_id)
    except:
        pass
    
    if is_correct:
        quiz["score"] += 1
        quiz["points_earned"] = quiz.get("points_earned", 0) + 3  # +2 очка за сложный вопрос + 1 за правильный
        msg = bot.send_message(chat_id, "✅ Правильно! +3 очка")
    else:
        msg = bot.send_message(chat_id, f"❌ Неправильно. Правильный ответ: {q['ans']}")
    
    time.sleep(1)
    try:
        bot.delete_message(chat_id, msg.message_id)
    except:
        pass
    
    quiz["current"] += 1
    
    if quiz["current"] < len(quiz["questions"]):
        send_question(chat_id)
    else:
        finish_quiz(chat_id, message.from_user)


def process_matching_answer(message, chat_id):
    if chat_id not in user_quizzes:
        return
    
    quiz = user_quizzes[chat_id]
    today = get_current_date()
    
    # Проверка смены дня
    if quiz.get("start_date") != today:
        bot.send_message(chat_id, "⏰ Квиз прерван: наступил новый день. Результаты не засчитаны.")
        del user_quizzes[chat_id]
        return
    
    q = quiz["questions"][quiz["current"]]
    user_answer = message.text.strip()
    correct = q["ans"].replace(" ", "")
    user_clean = user_answer.replace(" ", "")
    
    quiz["answers"].append(user_answer)
    
    # Удаляем сообщения
    try:
        bot.delete_message(chat_id, quiz["last_msg_id"])
    except:
        pass
    try:
        bot.delete_message(chat_id, message.message_id)
    except:
        pass
    
    if user_clean.lower() == correct.lower():
        quiz["score"] += 1
        quiz["points_earned"] = quiz.get("points_earned", 0) + 3
        msg = bot.send_message(chat_id, "✅ Правильно! +3 очка")
    else:
        msg = bot.send_message(chat_id, f"❌ Неправильно. Правильный ответ: {q['ans']}")
    
    time.sleep(1)
    try:
        bot.delete_message(chat_id, msg.message_id)
    except:
        pass
    
    quiz["current"] += 1
    
    if quiz["current"] < len(quiz["questions"]):
        send_question(chat_id)
    else:
        finish_quiz(chat_id, message.from_user)
        finish_quiz(chat_id, message.from_user)


def process_sequence_answer(message, chat_id):
    if chat_id not in user_quizzes:
        return
    
    quiz = user_quizzes[chat_id]
    today = get_current_date()
    
    # Проверка смены дня
    if quiz.get("start_date") != today:
        bot.send_message(chat_id, "⏰ Квиз прерван: наступил новый день. Результаты не засчитаны.")
        del user_quizzes[chat_id]
        return
    
    q = quiz["questions"][quiz["current"]]
    user_answer = message.text.strip()
    correct = q["ans"].replace(" ", "")
    user_clean = user_answer.replace(" ", "")
    
    quiz["answers"].append(user_answer)
    
    # Удаляем сообщения
    try:
        bot.delete_message(chat_id, quiz["last_msg_id"])
    except:
        pass
    try:
        bot.delete_message(chat_id, message.message_id)
    except:
        pass
    
    if user_clean.lower() == correct.lower():
        quiz["score"] += 1
        quiz["points_earned"] = quiz.get("points_earned", 0) + 3
        msg = bot.send_message(chat_id, "✅ Правильно! +3 очка")
    else:
        msg = bot.send_message(chat_id, f"❌ Неправильно. Правильный ответ: {q['ans']}")
    
    time.sleep(1)
    try:
        bot.delete_message(chat_id, msg.message_id)
    except:
        pass
    
    quiz["current"] += 1
    
    if quiz["current"] < len(quiz["questions"]):
        send_question(chat_id)
    else:
        finish_quiz(chat_id, message.from_user)
        finish_quiz(chat_id, message.from_user)


def finish_quiz(chat_id, user):
    if chat_id not in user_quizzes:
        return
    
    quiz = user_quizzes[chat_id]
    today = get_current_date()
    
    # Проверка смены дня при завершении
    if quiz.get("start_date") != today:
        bot.send_message(chat_id, "⏰ Квиз прерван: наступил новый день. Результаты не засчитаны.")
        del user_quizzes[chat_id]
        return
    
    points_earned = quiz.get("points_earned", 0)
    completion_bonus = 1  # +1 очко за прохождение квиза
    perfect_bonus = 3 if quiz["score"] == len(quiz["questions"]) else 0  # +3 очка за идеальное прохождение
    
    total_points = points_earned + completion_bonus + perfect_bonus
    
    # Сохраняем результаты пользователя для просмотра позже
    data = load_data()
    user_id = str(chat_id)
    
    if user_id not in data["users"]:
        data["users"][user_id] = {"points": 0, "perfect_quizzes": 0, "correct_answers": 0, "gifts_bought": 0, "name": get_user_name(user), "last_quiz": "", "registered": True}
    
    # Сохраняем ответы пользователя для текущего квиза
    data["users"][user_id]["last_quiz_answers"] = {
        "date": today,
        "answers": quiz["answers"],
        "score": quiz["score"],
        "total": len(quiz["questions"])
    }
    
    data["users"][user_id]["name"] = get_user_name(user)
    data["users"][user_id]["correct_answers"] = data["users"][user_id].get("correct_answers", 0) + quiz["score"]
    data["users"][user_id]["last_quiz"] = quiz.get("start_date")
    data["users"][user_id]["points"] += total_points
    
    subscribed = data.get("notifications", {}).get(user_id, True)
    
    # Краткий результат без деталей
    result_text = f"🎊 Квиз завершён!\n\n"
    result_text += f"✅ Правильных ответов: {quiz['score']}/{len(quiz['questions'])}\n\n"
    
    if quiz["score"] == len(quiz["questions"]):
        data["users"][user_id]["perfect_quizzes"] = data["users"][user_id].get("perfect_quizzes", 0) + 1
        save_data(data)
        result_text += f"🎁 Идеально! Вы получили {total_points} очков!\n"
        result_text += f"(+{points_earned} за ответы, +{completion_bonus} за прохождение, +{perfect_bonus} бонус)\n"
        result_text += f"Всего очков: {data['users'][user_id]['points']}"
    else:
        save_data(data)
        result_text += f"💰 Вы получили {total_points} очков!\n"
        result_text += f"(+{points_earned} за ответы, +{completion_bonus} за прохождение)\n"
        result_text += f"Всего очков: {data['users'][user_id]['points']}"
    
    if not subscribed:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔔 Подписаться на уведомления", callback_data="subscribe"))
        bot.send_message(chat_id, result_text, reply_markup=markup)
    else:
        bot.send_message(chat_id, result_text)
    
    del user_quizzes[chat_id]


@bot.message_handler(commands=['balance'])
def balance(message):
    if not check_registration(message):
        return
    data = load_data()
    user_id = str(message.chat.id)
    if user_id not in data["users"]:
        data["users"][user_id] = {"points": 0, "perfect_quizzes": 0, "correct_answers": 0, "gifts_bought": 0, "name": get_user_name(message.from_user), "registered": True}
    data["users"][user_id]["name"] = get_user_name(message.from_user)
    save_data(data)
    user_data = data["users"].get(user_id, {"points": 0, "perfect_quizzes": 0, "correct_answers": 0, "gifts_bought": 0})
    
    subscribed = data.get("notifications", {}).get(user_id, True)
    text = f"💰 Ваш баланс: {user_data.get('points', 0)} очков"
    
    if not subscribed:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔔 Подписаться на уведомления", callback_data="subscribe"))
        bot.send_message(message.chat.id, text, reply_markup=markup)
    else:
        bot.send_message(message.chat.id, text)


def get_admin_markup():
    """Возвращает клавиатуру админ-панели"""
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("➕ Добавить подарок", callback_data="admin_add"))
    markup.add(types.InlineKeyboardButton("📋 Список подарков", callback_data="admin_list"))
    markup.add(types.InlineKeyboardButton("🔄 Сбросить квиз игроку", callback_data="admin_reset"))
    markup.add(types.InlineKeyboardButton("📢 Уведомить о квизе", callback_data="admin_notify"))
    markup.add(types.InlineKeyboardButton("🔄 Пересоздать квиз", callback_data="admin_regenerate"))
    markup.add(types.InlineKeyboardButton("💰 Начислить очки", callback_data="admin_points"))
    markup.add(types.InlineKeyboardButton("📅 Установить дату", callback_data="admin_date"))
    return markup


@bot.message_handler(commands=['admin'])
def admin(message):
    if message.chat.id != ADMIN_ID:
        bot.send_message(message.chat.id, "❌ Доступ запрещён")
        return
    
    bot.send_message(message.chat.id, "🔧 Админ-панель", reply_markup=get_admin_markup())


@bot.callback_query_handler(func=lambda call: call.data == "admin_add")
def admin_add(call):
    if call.message.chat.id != ADMIN_ID:
        return
    try:
        bot.answer_callback_query(call.id)
    except:
        pass
    bot.edit_message_text("Введите данные подарка в формате:\nНазвание|Цена", call.message.chat.id, call.message.message_id)
    bot.register_next_step_handler(call.message, process_add_gift)


@bot.callback_query_handler(func=lambda call: call.data == "admin_notify")
def admin_notify(call):
    if call.message.chat.id != ADMIN_ID:
        return
    try:
        bot.answer_callback_query(call.id)
    except:
        pass
    
    today = get_current_date()
    if not daily_quiz or daily_quiz.get("date") != today:
        bot.edit_message_text("❌ Квиз на сегодня еще не создан. Используйте /generate_quiz для создания.", call.message.chat.id, call.message.message_id)
        return
    
    notify_users()
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("➕ Добавить подарок", callback_data="admin_add"))
    markup.add(types.InlineKeyboardButton("📋 Список подарков", callback_data="admin_list"))
    markup.add(types.InlineKeyboardButton("🔄 Сбросить квиз игроку", callback_data="admin_reset"))
    markup.add(types.InlineKeyboardButton("📢 Уведомить о квизе", callback_data="admin_notify"))
    markup.add(types.InlineKeyboardButton("🔄 Пересоздать квиз", callback_data="admin_regenerate"))
    markup.add(types.InlineKeyboardButton("💰 Начислить очки", callback_data="admin_points"))
    bot.edit_message_text("✅ Уведомления отправлены!\n\n🔧 Админ-панель", call.message.chat.id, call.message.message_id, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == "admin_regenerate")
def admin_regenerate(call):
    if call.message.chat.id != ADMIN_ID:
        return
    try:
        bot.answer_callback_query(call.id, "⏳ Генерирую квиз...")
    except:
        pass
    
    # Очищаем last_quiz у всех пользователей чтобы они могли пройти новый квиз
    data = load_data()
    today = get_current_date()
    for user_id in data["users"]:
        if data["users"][user_id].get("last_quiz") == today:
            data["users"][user_id]["last_quiz"] = ""
    save_data(data)
    
    # Очищаем активные квизы
    user_quizzes.clear()
    
    generate_daily_quiz()
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("➕ Добавить подарок", callback_data="admin_add"))
    markup.add(types.InlineKeyboardButton("📋 Список подарков", callback_data="admin_list"))
    markup.add(types.InlineKeyboardButton("🔄 Сбросить квиз игроку", callback_data="admin_reset"))
    markup.add(types.InlineKeyboardButton("📢 Уведомить о квизе", callback_data="admin_notify"))
    markup.add(types.InlineKeyboardButton("🔄 Пересоздать квиз", callback_data="admin_regenerate"))
    markup.add(types.InlineKeyboardButton("💰 Начислить очки", callback_data="admin_points"))
    bot.edit_message_text("✅ Квиз пересоздан и уведомления отправлены!\n\n🔧 Админ-панель", call.message.chat.id, call.message.message_id, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == "admin_points")
def admin_points(call):
    if call.message.chat.id != ADMIN_ID:
        return
    try:
        bot.answer_callback_query(call.id)
    except:
        pass
    
    data = load_data()
    text = "Выберите пользователя:\n\n"
    for user_id, user_data in data["users"].items():
        name = user_data.get("name", f"ID{user_id}")
        points = user_data.get("points", 0)
        text += f"`{name}` - {points} очков\n"
    
    bot.edit_message_text(text + "\nВведите имя пользователя и количество очков через |:\nПример: Иван Иванов|10", call.message.chat.id, call.message.message_id, parse_mode="Markdown")
    bot.register_next_step_handler(call.message, process_add_points)


@bot.callback_query_handler(func=lambda call: call.data == "admin_date")
def admin_date(call):
    if call.message.chat.id != ADMIN_ID:
        return
    try:
        bot.answer_callback_query(call.id)
    except:
        pass
    
    data = load_data()
    current_date = data.get("override_date", "Автоматически")
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔄 Автоматически", callback_data="date_auto"))
    markup.add(types.InlineKeyboardButton("📝 Установить вручную", callback_data="date_manual"))
    
    bot.edit_message_text(f"📅 Текущая дата: {current_date}\n\nВыберите режим:", call.message.chat.id, call.message.message_id, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == "date_auto")
def date_auto(call):
    if call.message.chat.id != ADMIN_ID:
        return
    try:
        bot.answer_callback_query(call.id)
    except:
        pass
    
    data = load_data()
    if "override_date" in data:
        del data["override_date"]
    save_data(data)
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("➕ Добавить подарок", callback_data="admin_add"))
    markup.add(types.InlineKeyboardButton("📋 Список подарков", callback_data="admin_list"))
    markup.add(types.InlineKeyboardButton("🔄 Сбросить квиз игроку", callback_data="admin_reset"))
    markup.add(types.InlineKeyboardButton("📢 Уведомить о квизе", callback_data="admin_notify"))
    markup.add(types.InlineKeyboardButton("🔄 Пересоздать квиз", callback_data="admin_regenerate"))
    markup.add(types.InlineKeyboardButton("💰 Начислить очки", callback_data="admin_points"))
    markup.add(types.InlineKeyboardButton("📅 Установить дату", callback_data="admin_date"))
    bot.edit_message_text("✅ Дата установлена на автоматическую\n\n🔧 Админ-панель", call.message.chat.id, call.message.message_id, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == "date_manual")
def date_manual(call):
    if call.message.chat.id != ADMIN_ID:
        return
    try:
        bot.answer_callback_query(call.id)
    except:
        pass
    
    bot.edit_message_text("Введите дату в формате ДД.ММ.ГГГГ:\nПример: 21.02.2026", call.message.chat.id, call.message.message_id)
    bot.register_next_step_handler(call.message, process_set_date)


@bot.callback_query_handler(func=lambda call: call.data == "admin_reset")
def admin_reset(call):
    if call.message.chat.id != ADMIN_ID:
        return
    try:
        bot.answer_callback_query(call.id)
    except:
        pass
    
    data = load_data()
    text = "Выберите пользователя:\n\n"
    for user_id, user_data in data["users"].items():
        name = user_data.get("name", f"ID{user_id}")
        last_quiz = user_data.get("last_quiz", "")
        status = "✅ Прошёл сегодня" if last_quiz == datetime.now().strftime("%Y-%m-%d") else "❌ Не проходил"
        text += f"`{name}` - {status}\n"
    
    bot.edit_message_text(text + "\nВведите имя пользователя:", call.message.chat.id, call.message.message_id,
                          parse_mode="Markdown")
    bot.register_next_step_handler(call.message, process_reset_quiz)


@bot.message_handler(commands=['generate_quiz'])
def generate_quiz_cmd(message):
    if message.chat.id != ADMIN_ID:
        bot.send_message(message.chat.id, "❌ Доступ запрещён")
        return
    
    bot.send_message(message.chat.id, "⏳ Генерирую квиз...")
    generate_daily_quiz()
    bot.send_message(message.chat.id, "✅ Квиз создан и уведомления отправлены!")


def process_set_date(message):
    if message.chat.id != ADMIN_ID:
        return
    try:
        from datetime import datetime as dt
        date_str = message.text.strip()
        # Парсим дату в формате ДД.ММ.ГГГГ
        date_obj = dt.strptime(date_str, "%d.%m.%Y")
        formatted_date = date_obj.strftime("%Y-%m-%d")
        
        data = load_data()
        data["override_date"] = formatted_date
        save_data(data)
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("➕ Добавить подарок", callback_data="admin_add"))
        markup.add(types.InlineKeyboardButton("📋 Список подарков", callback_data="admin_list"))
        markup.add(types.InlineKeyboardButton("🔄 Сбросить квиз игроку", callback_data="admin_reset"))
        markup.add(types.InlineKeyboardButton("📢 Уведомить о квизе", callback_data="admin_notify"))
        markup.add(types.InlineKeyboardButton("🔄 Пересоздать квиз", callback_data="admin_regenerate"))
        markup.add(types.InlineKeyboardButton("💰 Начислить очки", callback_data="admin_points"))
        markup.add(types.InlineKeyboardButton("📅 Установить дату", callback_data="admin_date"))
        bot.send_message(message.chat.id, f"✅ Дата установлена: {date_str}\n\n🔧 Админ-панель", reply_markup=markup)
    except:
        bot.send_message(message.chat.id, "❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ")


def process_add_points(message):
    if message.chat.id != ADMIN_ID:
        return
    try:
        name, points_str = message.text.split('|')
        points = int(points_str.strip())
        data = load_data()
        
        found_user_id = None
        for user_id, user_data in data["users"].items():
            if user_data.get("name", "") == name.strip():
                found_user_id = user_id
                break
        
        if found_user_id:
            data["users"][found_user_id]["points"] = data["users"][found_user_id].get("points", 0) + points
            save_data(data)
            
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("➕ Добавить подарок", callback_data="admin_add"))
            markup.add(types.InlineKeyboardButton("📋 Список подарков", callback_data="admin_list"))
            markup.add(types.InlineKeyboardButton("🔄 Сбросить квиз игроку", callback_data="admin_reset"))
            markup.add(types.InlineKeyboardButton("📢 Уведомить о квизе", callback_data="admin_notify"))
            markup.add(types.InlineKeyboardButton("🔄 Пересоздать квиз", callback_data="admin_regenerate"))
            markup.add(types.InlineKeyboardButton("💰 Начислить очки", callback_data="admin_points"))
            bot.send_message(message.chat.id, f"✅ Начислено {points} очков пользователю {name.strip()}. Всего: {data['users'][found_user_id]['points']}\n\n🔧 Админ-панель", reply_markup=markup)
        else:
            bot.send_message(message.chat.id, "❌ Пользователь не найден")
    except:
        bot.send_message(message.chat.id, "❌ Ошибка формата")


def process_add_gift(message):
    if message.chat.id != ADMIN_ID:
        return
    try:
        name, price = message.text.split('|')
        data = load_data()
        data["gifts"].append({"name": name.strip(), "price": int(price.strip())})
        save_data(data)
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("➕ Добавить подарок", callback_data="admin_add"))
        markup.add(types.InlineKeyboardButton("📋 Список подарков", callback_data="admin_list"))
        markup.add(types.InlineKeyboardButton("🔄 Сбросить квиз игроку", callback_data="admin_reset"))
        markup.add(types.InlineKeyboardButton("📢 Уведомить о квизе", callback_data="admin_notify"))
        markup.add(types.InlineKeyboardButton("🔄 Пересоздать квиз", callback_data="admin_regenerate"))
        markup.add(types.InlineKeyboardButton("💰 Начислить очки", callback_data="admin_points"))
        bot.send_message(message.chat.id, f"✅ Подарок '{name}' добавлен за {price} очков\n\n🔧 Админ-панель", reply_markup=markup)
    except:
        bot.send_message(message.chat.id, "❌ Ошибка формата")


def process_reset_quiz(message):
    if message.chat.id != ADMIN_ID:
        return
    try:
        search_name = message.text.strip()
        data = load_data()
        
        found_user_id = None
        for user_id, user_data in data["users"].items():
            if user_data.get("name", "") == search_name:
                found_user_id = user_id
                break
        
        if found_user_id:
            # Очищаем last_quiz чтобы пользователь мог пройти квиз снова
            data["users"][found_user_id]["last_quiz"] = ""
            save_data(data)
            
            # Также удаляем активный квиз если он есть
            if int(found_user_id) in user_quizzes:
                del user_quizzes[int(found_user_id)]
            
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("➕ Добавить подарок", callback_data="admin_add"))
            markup.add(types.InlineKeyboardButton("📋 Список подарков", callback_data="admin_list"))
            markup.add(types.InlineKeyboardButton("🔄 Сбросить квиз игроку", callback_data="admin_reset"))
            markup.add(types.InlineKeyboardButton("📢 Уведомить о квизе", callback_data="admin_notify"))
            markup.add(types.InlineKeyboardButton("🔄 Пересоздать квиз", callback_data="admin_regenerate"))
            markup.add(types.InlineKeyboardButton("💰 Начислить очки", callback_data="admin_points"))
            bot.send_message(message.chat.id, f"✅ Квиз сброшен для пользователя {search_name}\n\n🔧 Админ-панель", reply_markup=markup)
        else:
            bot.send_message(message.chat.id, "❌ Пользователь не найден")
    except:
        bot.send_message(message.chat.id, "❌ Ошибка")


@bot.callback_query_handler(func=lambda call: call.data == "admin_list")
def admin_list(call):
    if call.message.chat.id != ADMIN_ID:
        return
    try:
        bot.answer_callback_query(call.id)
    except:
        pass
    data = load_data()
    if not data["gifts"]:
        text = "📋 Подарков нет"
    else:
        text = "📋 Список подарков:\n\n"
        for i, g in enumerate(data["gifts"]):
            text += f"{i+1}. {g['name']} - {g['price']} очков\n"
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("➕ Добавить подарок", callback_data="admin_add"))
    markup.add(types.InlineKeyboardButton("📋 Список подарков", callback_data="admin_list"))
    markup.add(types.InlineKeyboardButton("🔄 Сбросить квиз игроку", callback_data="admin_reset"))
    markup.add(types.InlineKeyboardButton("📢 Уведомить о квизе", callback_data="admin_notify"))
    markup.add(types.InlineKeyboardButton("🔄 Пересоздать квиз", callback_data="admin_regenerate"))
    markup.add(types.InlineKeyboardButton("💰 Начислить очки", callback_data="admin_points"))
    bot.edit_message_text(text + "\n\n🔧 Админ-панель", call.message.chat.id, call.message.message_id, reply_markup=markup)


@bot.message_handler(commands=['shop'])
def shop(message):
    if not check_registration(message):
        return
    data = load_data()
    user_id = str(message.chat.id)
    if user_id not in data["users"]:
        data["users"][user_id] = {"points": 0, "perfect_quizzes": 0, "correct_answers": 0, "gifts_bought": 0, "name": get_user_name(message.from_user), "registered": True}
    data["users"][user_id]["name"] = get_user_name(message.from_user)
    save_data(data)
    points = data["users"].get(user_id, {}).get("points", 0)
    subscribed = data.get("notifications", {}).get(user_id, True)
    
    if not data["gifts"]:
        text = f"💰 Ваш баланс: {points} очков\n\n🛒 Магазин пуст"
        if not subscribed:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔔 Подписаться на уведомления", callback_data="subscribe"))
            bot.send_message(message.chat.id, text, reply_markup=markup)
        else:
            bot.send_message(message.chat.id, text)
        return
    
    markup = types.InlineKeyboardMarkup()
    for i, g in enumerate(data["gifts"]):
        markup.add(types.InlineKeyboardButton(f"{g['name']} - {g['price']} очков", callback_data=f"buy_{i}"))
    
    if not subscribed:
        markup.add(types.InlineKeyboardButton("🔔 Подписаться на уведомления", callback_data="subscribe"))
    
    bot.send_message(message.chat.id, f"💰 Ваш баланс: {points} очков\n\n🛒 Магазин подарков:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('buy_'))
def buy_gift(call):
    data = load_data()
    gift_id = int(call.data.split('_')[1])
    gift = data["gifts"][gift_id]
    user_id = str(call.message.chat.id)
    
    if user_id not in data["users"]:
        data["users"][user_id] = {"points": 0}
    
    if data["users"][user_id]["points"] >= gift["price"]:
        data["users"][user_id]["points"] -= gift["price"]
        data["users"][user_id]["gifts_bought"] = data["users"][user_id].get("gifts_bought", 0) + 1
        data["users"][user_id]["name"] = get_user_name(call.from_user)
        save_data(data)
        try:
            bot.answer_callback_query(call.id, f"✅ Вы купили {gift['name']}!")
        except:
            pass
        bot.send_message(ADMIN_ID, f"🎁 Пользователь {get_user_name(call.from_user)} купил {gift['name']}")
        bot.send_message(call.message.chat.id, f"✅ Вы купили {gift['name']}!\nОстаток: {data['users'][user_id]['points']} очков")
    else:
        try:
            bot.answer_callback_query(call.id, f"❌ Недостаточно очков. Нужно: {gift['price']}, у вас: {data['users'][user_id]['points']}")
        except:
            pass


def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(60)


schedule.every().day.at(GEN_TIME).do(generate_daily_quiz)

scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
scheduler_thread.start()

# Загрузка квиза из data.json при запуске
data = load_data()
if "daily_quiz" in data and data["daily_quiz"]:
    daily_quiz = data["daily_quiz"]
    print(f"Квиз загружен из data.json: {daily_quiz.get('holiday', 'неизвестно')}")

while True:
    try:
        bot.polling()
        break
    except Exception as e:
        print(f"Exception: {e}")
        time.sleep(1)
