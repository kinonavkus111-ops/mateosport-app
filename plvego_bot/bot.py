print("Бот MateoSport запущен")

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    WebAppInfo
)
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    ConversationHandler,
    CallbackContext
)

# Этапы регистрации
FULLNAME, AGE, CITY, SPORT, LEVEL, PHOTO = range(6)

# Хранилище пользователей
users = {}

def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "Привет! 👋 Добро пожаловать в MateoSport!\n\n"
        "Давай начнём регистрацию.\n"
        "Напиши своё ФИО:"
    )
    return FULLNAME

def fullname(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    users[user_id] = {
        "fullName": update.message.text
    }
    update.message.reply_text("Сколько тебе лет?")
    return AGE

def age(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    text = update.message.text
    if not text.isdigit():
        update.message.reply_text("Пожалуйста, введи возраст числом.")
        return AGE
    users[user_id]["age"] = text
    update.message.reply_text("Из какого ты города?")
    return CITY

def city(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    users[user_id]["city"] = update.message.text

    keyboard = [
        ["⚽ Футбол", "🏀 Баскетбол", "🏐 Волейбол"],
        ["🏒 Хоккей", "🏋️‍♂️ Фитнес", "💃 Танго"]
    ]

    update.message.reply_text(
        "Выбери вид спорта:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard,
            one_time_keyboard=True,
            resize_keyboard=True
        )
    )
    return SPORT

def sport(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    users[user_id]["sport"] = update.message.text

    keyboard = [
        ["Новичок", "Любитель", "Профессионал"]
    ]

    update.message.reply_text(
        "Какой у тебя уровень игры?",
        reply_markup=ReplyKeyboardMarkup(
            keyboard,
            one_time_keyboard=True,
            resize_keyboard=True
        )
    )
    return LEVEL

def level(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    users[user_id]["level"] = update.message.text

    update.message.reply_text(
        "Отправь, пожалуйста, свою фотографию."
    )
    return PHOTO

def photo(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    photo_file = update.message.photo[-1].get_file()

    # Создаём папку user_photos, если её нет
    import os
    if not os.path.exists('user_photos'):
        os.makedirs('user_photos')

    photo_path = f"user_photos/{user_id}.jpg"
    photo_file.download(photo_path)

    users[user_id]["photo"] = photo_path

    info = users[user_id]
    update.message.reply_text(
        f"✅ Регистрация завершена!\n\n"
        f"ФИО: {info['fullName']}\n"
        f"Возраст: {info['age']}\n"
        f"Город: {info['city']}\n"
        f"Вид спорта: {info['sport']}\n"
        f"Уровень: {info['level']}\n\n"
        "Фото получено и сохранено.\n\n"
        "Ниже 👇 нажми кнопку, чтобы открыть приложение!"
    )

    keyboard = [
        [
            KeyboardButton(
                "🚀 Открыть MateoSport",
                web_app=WebAppInfo(url="https://kinonavkus111-ops.github.io/mateosport-app/")
            )
        ]
    ]

    update.message.reply_text(
        "Открывай приложение:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard,
            resize_keyboard=True
        )
    )

    return ConversationHandler.END

def cancel(update: Update, context: CallbackContext):
    update.message.reply_text("Регистрация отменена.")
    return ConversationHandler.END

def main():
    updater = Updater(
        token="8314812294:AAGjcjdPSz7P9XTg_5QHYIV9N2DQ18IK1-c",
        use_context=True
    )
    dp = updater.dispatcher

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            FULLNAME: [MessageHandler(Filters.text & ~Filters.command, fullname)],
            AGE: [MessageHandler(Filters.text & ~Filters.command, age)],
            CITY: [MessageHandler(Filters.text & ~Filters.command, city)],
            SPORT: [MessageHandler(Filters.text & ~Filters.command, sport)],
            LEVEL: [MessageHandler(Filters.text & ~Filters.command, level)],
            PHOTO: [MessageHandler(Filters.photo, photo)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    dp.add_handler(conv_handler)

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()