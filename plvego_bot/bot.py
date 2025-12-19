print("БОТ ФАЙЛ ЗАПУСТИЛСЯ")

import json
import os

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, ConversationHandler, CallbackContext

FULLNAME, CITY, ACTIVITY, AGE, LEVEL = range(5)

USERS_FILE = 'users_data.json'

# Загрузка пользователей из файла
if os.path.exists(USERS_FILE):
    with open(USERS_FILE, 'r', encoding='utf-8') as f:
        users = json.load(f)
else:
    users = {}

def save_users():
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

levels = ['Новичок', 'Средний', 'Продвинутый']

def start(update: Update, context: CallbackContext):
    update.message.reply_text("Привет! Давай зарегистрируемся.\nНапиши, пожалуйста, своё ФИО:")
    return FULLNAME

def fullname(update: Update, context: CallbackContext):
    user_id = str(update.message.from_user.id)
    users[user_id] = {'fullName': update.message.text}
    save_users()
    update.message.reply_text("Теперь введи свой город:")
    return CITY

def city(update: Update, context: CallbackContext):
    user_id = str(update.message.from_user.id)
    users[user_id]['city'] = update.message.text
    save_users()

    keyboard = [['Футбол', 'Баскетбол', 'Танго', 'Волейбол', 'Тренажерный зал', 'Хоккей']]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    update.message.reply_text("Выбери вид спорта:", reply_markup=reply_markup)
    return ACTIVITY

def activity(update: Update, context: CallbackContext):
    user_id = str(update.message.from_user.id)
    users[user_id]['activity'] = update.message.text
    save_users()
    update.message.reply_text("Теперь введи свой возраст (число):")
    return AGE

def age(update: Update, context: CallbackContext):
    user_id = str(update.message.from_user.id)
    age_text = update.message.text

    if not age_text.isdigit():
        update.message.reply_text("Пожалуйста, введи возраст числом.")
        return AGE

    users[user_id]['age'] = int(age_text)
    save_users()

    keyboard = [levels]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    update.message.reply_text("Выбери уровень игры:", reply_markup=reply_markup)
    return LEVEL

def level(update: Update, context: CallbackContext):
    user_id = str(update.message.from_user.id)
    level_text = update.message.text

    if level_text not in levels:
        update.message.reply_text("Пожалуйста, выбери уровень из списка.")
        return LEVEL

    users[user_id]['level'] = level_text
    users[user_id]['username'] = update.message.from_user.username or ""
    save_users()

    update.message.reply_text(
        f"Спасибо за регистрацию, {users[user_id]['fullName']}!\n"
        f"Город: {users[user_id]['city']}\n"
        f"Вид спорта: {users[user_id]['activity']}\n"
        f"Возраст: {users[user_id]['age']}\n"
        f"Уровень: {users[user_id]['level']}\n\n"
        "Теперь ты можешь открыть приложение для поиска партнёров."
    )

    keyboard = [[KeyboardButton("Открыть PLVEGO", web_app=WebAppInfo(url='https://plvego.netlify.app/'))]]
    update.message.reply_text("Нажми кнопку ниже:", reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True))

    return ConversationHandler.END

def cancel(update: Update, context: CallbackContext):
    update.message.reply_text("Регистрация отменена.")
    return ConversationHandler.END

def webapp_data_handler(update: Update, context: CallbackContext):
    user_id = str(update.message.from_user.id)
    query_data = update.web_app_data.data

    if user_id not in users:
        update.message.reply_text("Сначала зарегистрируйся командой /start.")
        return

    try:
        data = json.loads(query_data)
    except:
        update.message.reply_text(f"Неправильные данные: {query_data}")
        return

    if data.get('command') == 'search_partner':
        search_city = data.get('city') or users[user_id]['city']
        search_activity = users[user_id]['activity']

        matches = []
        for uid, info in users.items():
            if uid != user_id and info.get('city', '').lower() == search_city.lower() and info.get('activity') == search_activity:
                matches.append({
                    'fullName': info.get('fullName'),
                    'city': info.get('city'),
                    'activity': info.get('activity'),
                    'age': info.get('age', ''),
                    'level': info.get('level', ''),
                    'username': info.get('username', '')
                })

        response = json.dumps({'type': 'search_results', 'users': matches}, ensure_ascii=False)
        update.message.reply_text(response)

    elif data.get('command') == 'get_profile':
        info = users[user_id]
        profile = {
            'fullName': info.get('fullName', ''),
            'city': info.get('city', ''),
            'activity': info.get('activity', ''),
            'age': info.get('age', ''),
            'level': info.get('level', ''),
            'username': info.get('username', '')
        }
        response = json.dumps({'type': 'profile', 'profile': profile}, ensure_ascii=False)
        update.message.reply_text(response)

    else:
        update.message.reply_text(f"Неизвестная команда: {query_data}")

def main():
    updater = Updater("8278155418:AAE1iE792rkRUHo9Ye9aFZ64OMLJ6AJXmaM")
    dp = updater.dispatcher

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            FULLNAME: [MessageHandler(Filters.text & ~Filters.command, fullname)],
            CITY: [MessageHandler(Filters.text & ~Filters.command, city)],
            ACTIVITY: [MessageHandler(Filters.text & ~Filters.command, activity)],
            AGE: [MessageHandler(Filters.text & ~Filters.command, age)],
            LEVEL: [MessageHandler(Filters.text & ~Filters.command, level)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    dp.add_handler(conv_handler)
    dp.add_handler(MessageHandler(Filters.status_update.web_app_data, webapp_data_handler))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()