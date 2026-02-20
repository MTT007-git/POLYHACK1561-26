import telebot
import requests
import dotenv
import os
import json
from datetime import datetime
from telebot import types
import threading
import time

dotenv.load_dotenv(".env")

user_histories = {}
user_quizzes = {}
bot = telebot.TeleBot(os.getenv("TOKEN"))
FOLDER_ID = os.getenv("FOLDER_ID")
API_KEY = os.getenv("API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

with open('praz.json', 'r', encoding='utf-8') as f:
    holidays = json.load(f)


def load_data():
    try:
        with open('data.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {"users": {}, "gifts": []}


def save_data(data):
    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_user_name(user):
    if user.username:
        return f"@{user.username}"
    return user.first_name or f"ID{user.id}"


def get_today_holiday():
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
    bot.send_message(message.chat.id, "Это бот для праздничных квизов.\n/quiz - квиз про сегодняшний праздник\n/shop - магазин подарков\n/balance - ваш баланс\n/leaderboard - топ игроков")


@bot.message_handler(commands=['leaderboard'])
def leaderboard(message):
    data = load_data()
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("💰 Очки", callback_data="lb_points"),
        types.InlineKeyboardButton("🎁 Подарки", callback_data="lb_gifts")
    )
    markup.add(
        types.InlineKeyboardButton("🏆 5/5 квизы", callback_data="lb_perfect"),
        types.InlineKeyboardButton("✅ Ответы", callback_data="lb_answers")
    )
    
    bot.send_message(message.chat.id, "📊 Выберите категорию:", reply_markup=markup)


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
    bot.answer_callback_query(call.id)


@bot.message_handler(commands=['quiz'])
def quiz(message):
    data = load_data()
    user_id = str(message.chat.id)
    today = datetime.now().strftime("%Y-%m-%d")
    
    if user_id not in data["users"]:
        data["users"][user_id] = {"points": 0, "perfect_quizzes": 0, "correct_answers": 0, "gifts_bought": 0, "name": get_user_name(message.from_user), "last_quiz": ""}
    
    if data["users"][user_id].get("last_quiz") == today:
        bot.send_message(message.chat.id, "❌ Вы уже проходили квиз сегодня! Приходите завтра.")
        return
    
    holiday, date = get_today_holiday()
    loading_msg = bot.send_message(message.chat.id, "Генерирую квиз...")
    
    stop_animation = threading.Event()
    
    def animate():
        dots = [".", "..", "..."]
        i = 0
        while not stop_animation.is_set():
            try:
                time.sleep(0.5)
                bot.edit_message_text(f"Генерирую квиз{dots[i % 3]}", message.chat.id, loading_msg.message_id)
                i += 1
            except:
                pass
    
    animation_thread = threading.Thread(target=animate)
    animation_thread.start()
    
    prompt = f"Сегодня {date}, праздник: {holiday}. Придумай 5 интересных вопросов про этот праздник (НЕ про дату празднования). Каждый вопрос в формате:\nВопрос?\nA) вариант\nB) вариант\nC) вариант\nD) вариант\nОтвет: буква\n\nМежду вопросами пустая строка."
    
    messages = [
        {"role": "system", "text": "Ты создаёшь интересные квизы про праздники. Не задавай вопросы про дату празднования."},
        {"role": "user", "text": prompt}
    ]
    
    quiz_text = ask_yandex_gpt(messages, FOLDER_ID, API_KEY)
    
    stop_animation.set()
    animation_thread.join()
    bot.delete_message(message.chat.id, loading_msg.message_id)
    questions = parse_quiz(quiz_text)
    
    if questions:
        print(f"\n=== Квиз для пользователя {get_user_name(message.from_user)} ===")
        for i, q in enumerate(questions):
            print(f"{i+1}. {q['q']}")
            print(f"   Правильный ответ: {q['ans']}")
        print("=" * 50 + "\n")
        
        user_quizzes[message.chat.id] = {"questions": questions, "current": 0, "score": 0, "answers": [], "holiday": holiday}
        bot.send_message(message.chat.id, f"🎉 Сегодня: {holiday}\n\nНачинаем квиз!")
        send_question(message.chat.id)
    else:
        bot.send_message(message.chat.id, f"🎉 Сегодня: {holiday}\n\n{quiz_text}")


def send_question(chat_id):
    quiz = user_quizzes[chat_id]
    q = quiz["questions"][quiz["current"]]
    
    markup = types.InlineKeyboardMarkup()
    for opt in q["opts"]:
        letter = opt[0]
        markup.add(types.InlineKeyboardButton(opt, callback_data=f"ans_{letter}"))
    
    msg = bot.send_message(chat_id, f"❓ Вопрос {quiz['current']+1}/5:\n\n{q['q']}", reply_markup=markup)
    quiz["last_msg_id"] = msg.message_id


@bot.callback_query_handler(func=lambda call: call.data.startswith('ans_'))
def check_answer(call):
    chat_id = call.message.chat.id
    answer = call.data.split('_')[1]
    quiz = user_quizzes[chat_id]
    correct = quiz["questions"][quiz["current"]]["ans"]
    
    quiz["answers"].append(answer)
    
    if answer == correct:
        quiz["score"] += 1
        bot.answer_callback_query(call.id, "✅ Правильно!")
    else:
        bot.answer_callback_query(call.id, f"❌ Неправильно. Ответ: {correct}")
    
    try:
        bot.delete_message(chat_id, quiz["last_msg_id"])
    except:
        pass
    
    quiz["current"] += 1
    
    if quiz["current"] < len(quiz["questions"]):
        send_question(chat_id)
    else:
        result_text = f"🎊 Квиз завершён!\nВаш результат: {quiz['score']}/5\n\n"
        
        for i, q in enumerate(quiz["questions"]):
            user_ans = quiz["answers"][i]
            correct_ans = q["ans"]
            status = "✅" if user_ans == correct_ans else "❌"
            result_text += f"{status} {i+1}. {q['q']}\n"
            result_text += f"Ваш ответ: {user_ans}) {[o for o in q['opts'] if o[0] == user_ans][0][3:]}\n"
            result_text += f"Правильный: {correct_ans}) {[o for o in q['opts'] if o[0] == correct_ans][0][3:]}\n\n"
        
        if quiz["score"] == 5:
            data = load_data()
            user_id = str(chat_id)
            today = datetime.now().strftime("%Y-%m-%d")
            if user_id not in data["users"]:
                data["users"][user_id] = {"points": 0, "perfect_quizzes": 0, "correct_answers": 0, "gifts_bought": 0, "name": get_user_name(call.from_user), "last_quiz": ""}
            data["users"][user_id]["name"] = get_user_name(call.from_user)
            data["users"][user_id]["points"] += 1
            data["users"][user_id]["perfect_quizzes"] = data["users"][user_id].get("perfect_quizzes", 0) + 1
            data["users"][user_id]["correct_answers"] = data["users"][user_id].get("correct_answers", 0) + quiz["score"]
            data["users"][user_id]["last_quiz"] = today
            save_data(data)
            result_text += f"🎁 Вы получили 1 очко! Всего очков: {data['users'][user_id]['points']}"
        else:
            data = load_data()
            user_id = str(chat_id)
            today = datetime.now().strftime("%Y-%m-%d")
            if user_id not in data["users"]:
                data["users"][user_id] = {"points": 0, "perfect_quizzes": 0, "correct_answers": 0, "gifts_bought": 0, "name": get_user_name(call.from_user), "last_quiz": ""}
            data["users"][user_id]["name"] = get_user_name(call.from_user)
            data["users"][user_id]["correct_answers"] = data["users"][user_id].get("correct_answers", 0) + quiz["score"]
            data["users"][user_id]["last_quiz"] = today
            save_data(data)
        
        bot.send_message(chat_id, result_text)
        del user_quizzes[chat_id]


@bot.message_handler(commands=['balance'])
def balance(message):
    data = load_data()
    user_id = str(message.chat.id)
    if user_id not in data["users"]:
        data["users"][user_id] = {"points": 0, "perfect_quizzes": 0, "correct_answers": 0, "gifts_bought": 0, "name": get_user_name(message.from_user)}
    data["users"][user_id]["name"] = get_user_name(message.from_user)
    save_data(data)
    user_data = data["users"].get(user_id, {"points": 0, "perfect_quizzes": 0, "correct_answers": 0, "gifts_bought": 0})
    bot.send_message(message.chat.id, f"💰 Ваш баланс: {user_data.get('points', 0)} очков")


@bot.message_handler(commands=['admin'])
def admin(message):
    if message.chat.id != ADMIN_ID:
        bot.send_message(message.chat.id, "❌ Доступ запрещён")
        return
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("➕ Добавить подарок", callback_data="admin_add"))
    markup.add(types.InlineKeyboardButton("📋 Список подарков", callback_data="admin_list"))
    markup.add(types.InlineKeyboardButton("🔄 Сбросить квиз игроку", callback_data="admin_reset"))
    bot.send_message(message.chat.id, "🔧 Админ-панель", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == "admin_add")
def admin_add(call):
    if call.message.chat.id != ADMIN_ID:
        return
    bot.answer_callback_query(call.id)
    bot.edit_message_text("Введите данные подарка в формате:\nНазвание|Цена", call.message.chat.id, call.message.message_id)
    bot.register_next_step_handler(call.message, process_add_gift)


@bot.callback_query_handler(func=lambda call: call.data == "admin_reset")
def admin_reset(call):
    if call.message.chat.id != ADMIN_ID:
        return
    bot.answer_callback_query(call.id)
    
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
            data["users"][found_user_id]["last_quiz"] = ""
            save_data(data)
            
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("➕ Добавить подарок", callback_data="admin_add"))
            markup.add(types.InlineKeyboardButton("📋 Список подарков", callback_data="admin_list"))
            markup.add(types.InlineKeyboardButton("🔄 Сбросить квиз игроку", callback_data="admin_reset"))
            bot.send_message(message.chat.id, f"✅ Квиз сброшен для пользователя {search_name}\n\n🔧 Админ-панель", reply_markup=markup)
        else:
            bot.send_message(message.chat.id, "❌ Пользователь не найден")
    except:
        bot.send_message(message.chat.id, "❌ Ошибка")


@bot.callback_query_handler(func=lambda call: call.data == "admin_list")
def admin_list(call):
    if call.message.chat.id != ADMIN_ID:
        return
    bot.answer_callback_query(call.id)
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
    bot.edit_message_text(text + "\n\n🔧 Админ-панель", call.message.chat.id, call.message.message_id, reply_markup=markup)


@bot.message_handler(commands=['shop'])
def shop(message):
    data = load_data()
    user_id = str(message.chat.id)
    if user_id not in data["users"]:
        data["users"][user_id] = {"points": 0, "perfect_quizzes": 0, "correct_answers": 0, "gifts_bought": 0, "name": get_user_name(message.from_user)}
    data["users"][user_id]["name"] = get_user_name(message.from_user)
    save_data(data)
    points = data["users"].get(user_id, {}).get("points", 0)
    
    if not data["gifts"]:
        bot.send_message(message.chat.id, f"💰 Ваш баланс: {points} очков\n\n🛒 Магазин пуст")
        return
    
    markup = types.InlineKeyboardMarkup()
    for i, g in enumerate(data["gifts"]):
        markup.add(types.InlineKeyboardButton(f"{g['name']} - {g['price']} очков", callback_data=f"buy_{i}"))
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
        bot.answer_callback_query(call.id, f"✅ Вы купили {gift['name']}!")
        bot.send_message(ADMIN_ID, f"🎁 Пользователь {get_user_name(call.from_user)} купил {gift['name']}")
        bot.send_message(call.message.chat.id, f"✅ Вы купили {gift['name']}!\nОстаток: {data['users'][user_id]['points']} очков")
    else:
        bot.answer_callback_query(call.id, f"❌ Недостаточно очков. Нужно: {gift['price']}, у вас: {data['users'][user_id]['points']}")


while True:
    try:
        bot.polling()
        break
    except Exception as e:
        print(f"Exception: {e}")
