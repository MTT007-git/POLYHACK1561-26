import telebot
import requests
import dotenv
import os

dotenv.load_dotenv(".env")

user_histories = {}
bot = telebot.TeleBot(os.getenv("TOKEN"))
FOLDER_ID = os.getenv("FOLDER_ID")
API_KEY = os.getenv("API_KEY")


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
            "temperature": 0.6,
            "maxTokens": 2000
        },
        "messages": messages  # Теперь отправляем всю историю!
    }

    response = requests.post(url, headers=headers, json=data)
    result = response.json()

    return result["result"]["alternatives"][0]["message"]["text"]


MAX_HISTORY = 10  # Храним последние 10 сообщений (5 вопросов + 5 ответов)


@bot.message_handler(content_types=['text'])
def handle_message(message):
    user_id = message.chat.id
    user_text = message.text

    if user_id not in user_histories:
        user_histories[user_id] = [
            {
                "role": "system",
                "text": "Ты - учитель математики. Отвечай просто и понятно, используй примеры."
            }
        ]

    # Добавляем новое сообщение
    user_histories[user_id].append({
        "role": "user",
        "text": user_text
    })

    # Ограничиваем историю последними MAX_HISTORY сообщениями
    if len(user_histories[user_id]) > MAX_HISTORY:
        user_histories[user_id] = user_histories[user_id][-MAX_HISTORY:]

    # Отправляем запрос
    answer = ask_yandex_gpt(user_histories[user_id], FOLDER_ID, API_KEY)

    # Добавляем ответ в историю
    user_histories[user_id].append({
        "role": "assistant",
        "text": answer
    })

    # Снова проверяем длину
    if len(user_histories[user_id]) > MAX_HISTORY:
        user_histories[user_id] = user_histories[user_id][-MAX_HISTORY:]

    bot.send_message(user_id, answer)


@bot.message_handler(commands=['clear'])
def clear_history(message):
    user_id = message.chat.id
    user_histories[user_id] = []
    bot.send_message(user_id, "История диалога очищена! Начнем сначала.")


@bot.message_handler(commands=['start', "info"])
def start(message):
    user_id = message.chat.id
    user_histories[user_id] = [
    {
        "role": "system",
        "text": "Ты - учитель математики. Отвечай просто и понятно, используй примеры."
    }
    ]
    bot.send_message(user_id, "Это бот для праздничных квизов")


while True:
    try:
        bot.polling()
        break
    except Exception as e:
        print(f"Exception: {e}")
