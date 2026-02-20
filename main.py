import telebot
import requests
import dotenv
import os
import json
from datetime import datetime

dotenv.load_dotenv(".env")

user_histories = {}
bot = telebot.TeleBot(os.getenv("TOKEN"))
FOLDER_ID = os.getenv("FOLDER_ID")
API_KEY = os.getenv("API_KEY")

with open('praz.json', 'r', encoding='utf-8') as f:
    holidays = json.load(f)


def get_today_holiday():
    now = datetime.now()
    month = str(now.month)
    day = str(now.day)
    return holidays.get(month, {}).get(day, "День без праздника")


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
        "messages": messages
    }
    response = requests.post(url, headers=headers, json=data)
    result = response.json()
    return result["result"]["alternatives"][0]["message"]["text"]


@bot.message_handler(commands=['start', 'info'])
def start(message):
    bot.send_message(message.chat.id, "Это бот для праздничных квизов. Используй /quiz для получения квиза про сегодняшний праздник!")


@bot.message_handler(commands=['quiz'])
def quiz(message):
    holiday = get_today_holiday()
    prompt = f"Сегодня праздник: {holiday}. Придумай интересный квиз из 5 вопросов с вариантами ответов про этот праздник. Формат: вопрос, 4 варианта ответа (A, B, C, D), правильный ответ в конце."
    
    messages = [
        {"role": "system", "text": "Ты создаёшь интересные квизы про праздники."},
        {"role": "user", "text": prompt}
    ]
    
    quiz_text = ask_yandex_gpt(messages, FOLDER_ID, API_KEY)
    bot.send_message(message.chat.id, f"🎉 Сегодня: {holiday}\n\n{quiz_text}")


while True:
    try:
        bot.polling()
        break
    except Exception as e:
        print(f"Exception: {e}")
