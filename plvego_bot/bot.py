print("БОТ ФАЙЛ ЗАПУСТИЛСЯ")

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, ConversationHandler, CallbackContext

FULLNAME, AGE, CITY, ACTIVITY = range(4)

users = {}

def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "Привет! 👋\n"
        "Давай зарегистрируемся.\n\n"
        "Напиши, пожалуйста, своё ФИО:"
    )
    return FULLNAME

def fullname(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    users[user_id] = {'fullName': update.message.text}
    update.message.reply_text("Сколько тебе лет?")
    return AGE

def age(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id

    if not update.message.text.isdigit():
        update.message.reply_text("Пожалуйста, введи возраст цифрами 🙂")
        return AGE

    users[user_id]['age'] = update.message.text
    update.message.reply_text("Теперь введи свой город:")
    return CITY

def city(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    users[user_id]['city'] = update.message.text

    keyboard = [
        ['Футбол', 'Баскетбол', 'Танго'],
        ['Волейбол', 'Фитнес', 'Хоккей']
    ]
    reply_markup = ReplyKeyboardMarkup(
        keyboard,
        one_time_keyboard=True,
        resize_keyboard=True
    )

    update.message.reply_text(
        "Выбери вид спорта:",
        reply_markup=reply_markup
    )
    return ACTIVITY

def activity(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    users[user_id]['activity'] = update.message.text

    update.message.reply_text(
        f"✅ Регистрация завершена!\n\n"
        f"👤 Имя: {users[user_id]['fullName']}\n"
        f"🎂 Возраст: {users[user_id]['age']}\n"
        f"📍 Город: {users[user_id]['city']}\n"
        f"🏅 Вид спорта: {users[user_id]['activity']}\n\n"
        "Теперь ты можешь открыть приложение 👇"
    )

    keyboard = [[
        KeyboardButton(
            "🚀 Открыть MateoApp",
            web_app=WebAppInfo(
                url="https://kinonavkus111-ops.github.io/mateosport-app/"
            )
        )
    ]]

    update.message.reply_text(
        "Нажми кнопку ниже:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard,
            resize_keyboard=True
        )
    )

    update.message.reply_text("👇👇👇")

    return ConversationHandler.END

def cancel(update: Update, context: CallbackContext):
    update.message.reply_text("Регистрация отменена ❌")
    return ConversationHandler.END

def main():
    updater = Updater("8314812294:AAGjcjdPSz7P9XTg_5QHYIV9N2DQ18IK1-c")
    dp = updater.dispatcher

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            FULLNAME: [MessageHandler(Filters.text & ~Filters.command, fullname)],
            AGE: [MessageHandler(Filters.text & ~Filters.command, age)],
            CITY: [MessageHandler(Filters.text & ~Filters.command, city)],
            ACTIVITY: [MessageHandler(Filters.text & ~Filters.command, activity)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    dp.add_handler(conv_handler)

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()