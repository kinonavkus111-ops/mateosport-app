print("БОТ ЗАПУЩЕН ✅")  # лог в консоли при старте бота

import os
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Optional, Set

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, Update, WebAppInfo
from telegram.error import Forbidden, NetworkError, TimedOut
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

APP_URL = "https://kinonavkus111-ops.github.io/mateosport-app/"
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
EVENT_CHAT_ID = int(os.getenv("EVENT_CHAT_ID", "0") or 0)  # общий чат для событий (опционально)
OWNER_ID = 885624428
ADMIN_IDS = {
    int(raw_id.strip())
    for raw_id in os.getenv("ADMIN_IDS", "").split(",")
    if raw_id.strip().isdigit()
}
ADMIN_IDS.add(OWNER_ID)


@dataclass
class EventRecord:
    event_id: str
    title: str
    start_at: datetime
    participants: Set[int] = field(default_factory=set)
    trainer_id: Optional[int] = None
    location: str = ""
    note: str = ""
    invite_link: Optional[str] = None


@dataclass
class UserStat:
    user_id: int
    first_seen_at: datetime
    last_seen_at: datetime
    starts_count: int = 0
    app_open_clicks: int = 0
    actions_count: int = 0
    city: str = ""
    sport: str = ""


@dataclass
class SubscriptionGrant:
    user_id: int
    role: str
    plan: str
    granted_by: int
    granted_at: datetime
    expires_at: datetime


EVENTS: Dict[str, EventRecord] = {}
USER_STATS: Dict[int, UserStat] = {}
CITY_COUNTER: Counter = Counter()
SPORT_COUNTER: Counter = Counter()
USER_COMMAND_LOG: Dict[str, list[datetime]] = {}
SUBSCRIPTIONS: Dict[tuple[int, str], SubscriptionGrant] = {}


def load_local_env() -> None:
    """Minimal .env loader to simplify local запуск without extra deps."""
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        return

    with open(env_path, "r", encoding="utf-8") as env_file:
        for raw in env_file:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def get_bot_token() -> str:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise ValueError(
            "Не задан BOT_TOKEN. Добавь его в переменные окружения или в bot/.env (пример в bot/.env.example)."
        )
    if not re.match(r"^\d{8,}:[A-Za-z0-9_-]{20,}$", token):
        raise ValueError("BOT_TOKEN похож на некорректный формат. Проверь токен из BotFather.")
    return token


def record_user_activity(user_id: int, action: str) -> None:
    now = datetime.now()
    stat = USER_STATS.get(user_id)
    if not stat:
        stat = UserStat(user_id=user_id, first_seen_at=now, last_seen_at=now)
        USER_STATS[user_id] = stat

    stat.last_seen_at = now
    stat.actions_count += 1

    if action == "start":
        stat.starts_count += 1
    if action == "app_open_click":
        stat.app_open_clicks += 1


def get_admin_kpis() -> Dict[str, int]:
    now = datetime.now()
    online_5m = sum(1 for s in USER_STATS.values() if now - s.last_seen_at <= timedelta(minutes=5))
    active_24h = sum(1 for s in USER_STATS.values() if now - s.last_seen_at <= timedelta(hours=24))
    active_7d = sum(1 for s in USER_STATS.values() if now - s.last_seen_at <= timedelta(days=7))
    starts = sum(s.starts_count for s in USER_STATS.values())
    app_open_clicks = sum(s.app_open_clicks for s in USER_STATS.values())
    active_subscriptions = sum(1 for grant in SUBSCRIPTIONS.values() if grant.expires_at > now)
    return {
        "users_total": len(USER_STATS),
        "online_5m": online_5m,
        "active_24h": active_24h,
        "active_7d": active_7d,
        "starts": starts,
        "app_open_clicks": app_open_clicks,
        "active_subscriptions": active_subscriptions,
    }


def is_rate_limited(user_id: int, action: str, limit: int, window_seconds: int) -> tuple[bool, int]:
    now = datetime.now()
    key = f"{user_id}:{action}"
    window_start = now - timedelta(seconds=window_seconds)
    bucket = [ts for ts in USER_COMMAND_LOG.get(key, []) if ts >= window_start]

    if len(bucket) >= limit:
        retry_after = max(1, int((bucket[0] + timedelta(seconds=window_seconds) - now).total_seconds()))
        USER_COMMAND_LOG[key] = bucket
        return True, retry_after

    bucket.append(now)
    USER_COMMAND_LOG[key] = bucket
    return False, 0


def set_user_profile(user_id: int, city: str = "", sport: str = "") -> None:
    now = datetime.now()
    stat = USER_STATS.get(user_id)
    if not stat:
        stat = UserStat(user_id=user_id, first_seen_at=now, last_seen_at=now)
        USER_STATS[user_id] = stat

    city = city.strip()
    sport = sport.strip()

    if city:
        if stat.city:
            CITY_COUNTER[stat.city] -= 1
            if CITY_COUNTER[stat.city] <= 0:
                del CITY_COUNTER[stat.city]
        stat.city = city
        CITY_COUNTER[city] += 1

    if sport:
        if stat.sport:
            SPORT_COUNTER[stat.sport] -= 1
            if SPORT_COUNTER[stat.sport] <= 0:
                del SPORT_COUNTER[stat.sport]
        stat.sport = sport
        SPORT_COUNTER[sport] += 1


# ======== HELPERЫ ========
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def parse_dt(value: str) -> datetime:
    # ожидается ISO-строка, например: 2026-03-11T19:00:00
    return datetime.fromisoformat(value.strip())


def app_keyboard(include_admin: bool = False) -> ReplyKeyboardMarkup:
    row = [KeyboardButton("Открыть MateoSport", web_app=WebAppInfo(url=APP_URL))]
    keyboard = [row]
    if include_admin:
        keyboard.append([KeyboardButton("Админ-панель")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def admin_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📊 Статус", callback_data="admin:status")],
            [InlineKeyboardButton("📅 Активные события", callback_data="admin:events")],
            [InlineKeyboardButton("🏙 Топ городов", callback_data="admin:top_cities")],
            [InlineKeyboardButton("🏅 Топ спортов", callback_data="admin:top_sports")],
            [InlineKeyboardButton("🎁 Подписки", callback_data="admin:subs_help")],
            [InlineKeyboardButton("⬅️ В меню", callback_data="admin:menu")],
        ]
    )


def admin_back_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅️ К панели", callback_data="admin:panel")]]
    )


# ======== СТАРТОВОЕ СООБЩЕНИЕ ========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    limited, retry = is_rate_limited(user_id, "start", limit=8, window_seconds=60)
    if limited:
        await update.message.reply_text(f"⏳ Слишком часто. Повтори через {retry} сек.")
        return
    record_user_activity(user_id, "start")
    text = "👇 Нажми кнопку ниже, чтобы открыть приложение MateoSport."
    await update.message.reply_text(
        text,
        reply_markup=app_keyboard(include_admin=is_admin(user_id))
    )
    print(f"[LOG] Пользователь {user_id} открыл /start")


# ======== АДМИН-ПАНЕЛЬ ========
async def open_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    limited, retry = is_rate_limited(user_id, "admin_panel_open", limit=20, window_seconds=60)
    if limited:
        await update.message.reply_text(f"⏳ Слишком часто. Повтори через {retry} сек.")
        return
    record_user_activity(user_id, "admin_panel_open")
    if not is_admin(user_id):
        await update.message.reply_text("⛔ Доступ только для администраторов.")
        return

    await update.message.reply_text(
        "🛠 Панель администратора\nВыбери действие:",
        reply_markup=admin_inline(),
    )


async def admin_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    if not is_admin(user_id):
        await query.edit_message_text("⛔ Доступ только для администраторов.")
        return

    if query.data == "admin:status":
        kpis = get_admin_kpis()
        await query.edit_message_text(
            f"📊 Состояние:\n"
            f"• Пользователей всего: {kpis['users_total']}\n"
            f"• Онлайн (5 мин): {kpis['online_5m']}\n"
            f"• Активны за 24ч: {kpis['active_24h']}\n"
            f"• Активны за 7д: {kpis['active_7d']}\n"
            f"• /start нажатий: {kpis['starts']}\n"
            f"• Кнопка «Открыть MateoSport»: {kpis['app_open_clicks']}\n"
            f"• Событий в памяти: {len(EVENTS)}\n"
            f"• Активных подписок: {kpis['active_subscriptions']}\n"
            f"• EVENT_CHAT_ID: {EVENT_CHAT_ID or 'не задан'}",
            reply_markup=admin_back_inline(),
        )
        return

    if query.data == "admin:events":
        if not EVENTS:
            await query.edit_message_text("📅 Активных событий пока нет.")
            return
        lines = ["📅 Активные события:"]
        for record in EVENTS.values():
            lines.append(
                f"• {record.event_id}: {record.title} | {record.start_at:%d.%m %H:%M} | участников: {len(record.participants)}"
            )
        await query.edit_message_text("\n".join(lines), reply_markup=admin_back_inline())
        return

    if query.data == "admin:top_cities":
        if not CITY_COUNTER:
            await query.edit_message_text("🏙 Пока нет данных по городам.")
            return
        top = CITY_COUNTER.most_common(10)
        lines = ["🏙 Топ городов:"]
        lines.extend([f"{idx + 1}. {city} — {count}" for idx, (city, count) in enumerate(top)])
        await query.edit_message_text("\n".join(lines), reply_markup=admin_back_inline())
        return

    if query.data == "admin:top_sports":
        if not SPORT_COUNTER:
            await query.edit_message_text("🏅 Пока нет данных по видам спорта.")
            return
        top = SPORT_COUNTER.most_common(10)
        lines = ["🏅 Топ спортов:"]
        lines.extend([f"{idx + 1}. {sport} — {count}" for idx, (sport, count) in enumerate(top)])
        await query.edit_message_text("\n".join(lines), reply_markup=admin_back_inline())
        return

    if query.data == "admin:subs_help":
        await query.edit_message_text(
            "🎁 Управление подписками\n"
            "Выдать: /grant_subscription user_id|player/trainer|plan|days\n"
            "Проверить: /subscription_status user_id\n"
            "Снять: /revoke_subscription user_id|player/trainer",
            reply_markup=admin_back_inline(),
        )
        return

    if query.data == "admin:panel":
        await query.edit_message_text(
            "🛠 Панель администратора\nВыбери действие:",
            reply_markup=admin_inline(),
        )
        return

    if query.data == "admin:menu":
        await query.message.reply_text(
            "Меню",
            reply_markup=app_keyboard(include_admin=True),
        )
        await query.edit_message_text("✅ Возврат в меню выполнен.")


# ======== СОБЫТИЯ И НАПОМИНАНИЯ ========
async def event_created(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Формат:
    /event_created <event_id>|<title>|<start_iso>|<participants_csv>|<trainer_id>|<location>|<note>
    Пример:
    /event_created ev42|Футбол 5x5|2026-03-11T19:00:00|111,222|999|Тольятти|Сбор за 15 мин
    """
    user_id = update.effective_user.id
    limited, retry = is_rate_limited(user_id, "event_created", limit=5, window_seconds=300)
    if limited:
        await update.message.reply_text(f"⏳ Лимит создания событий. Повтори через {retry} сек.")
        return
    record_user_activity(user_id, "event_created")
    if not is_admin(user_id):
        await update.message.reply_text("⛔ Только администратор может регистрировать события.")
        return

    payload = " ".join(context.args).strip()
    parts = [part.strip() for part in payload.split("|")]
    if len(parts) < 4:
        await update.message.reply_text("❌ Неверный формат. Используй: /event_created id|title|start_iso|user1,user2|trainer_id|location|note")
        return

    event_id = parts[0]
    title = parts[1]
    start_at = parse_dt(parts[2])
    participants = {int(x) for x in parts[3].split(",") if x.strip().isdigit()}
    trainer_id = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else None
    location = parts[5] if len(parts) > 5 else ""
    note = parts[6] if len(parts) > 6 else ""

    record = EventRecord(
        event_id=event_id,
        title=title,
        start_at=start_at,
        participants=participants,
        trainer_id=trainer_id,
        location=location,
        note=note,
    )
    EVENTS[event_id] = record

    await announce_event(context, record)
    schedule_event_reminder(context, record)

    await update.message.reply_text(
        f"✅ Событие {event_id} сохранено. Участников: {len(participants)}. Напоминание за 6 часов запланировано."
    )


async def announce_event(context: ContextTypes.DEFAULT_TYPE, record: EventRecord):
    text = (
        f"🏟 Событие: {record.title}\n"
        f"🆔 ID: {record.event_id}\n"
        f"🕒 Старт: {record.start_at:%d.%m.%Y %H:%M}\n"
        f"📍 Локация: {record.location or 'не указана'}\n"
        f"📝 {record.note or 'Без дополнительных комментариев.'}"
    )

    # Бот не может сам «добавить» пользователя в группу по ID, поэтому отправляем инвайт-ссылку
    # на заранее заданный EVENT_CHAT_ID, если он настроен и бот там админ.
    invite_link = None
    if EVENT_CHAT_ID:
        try:
            link_obj = await context.bot.create_chat_invite_link(chat_id=EVENT_CHAT_ID, member_limit=100)
            invite_link = link_obj.invite_link
            record.invite_link = invite_link
            await context.bot.send_message(chat_id=EVENT_CHAT_ID, text=f"📢 Новое событие\n\n{text}")
        except Exception as exc:
            print(f"[WARN] Не удалось создать/отправить инвайт в EVENT_CHAT_ID: {exc}")

    for participant_id in record.participants:
        msg = text
        if invite_link:
            msg += f"\n\n💬 Чат события: {invite_link}"
        try:
            await context.bot.send_message(
                chat_id=participant_id,
                text=msg,
                reply_markup=app_keyboard(include_admin=is_admin(participant_id)),
            )
        except Forbidden:
            print(f"[WARN] Нельзя отправить сообщение пользователю {participant_id}.")


async def event_ready(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/event_ready <event_id> — отправить участникам финальное напоминание и опрос Иду/Не иду"""
    user_id = update.effective_user.id
    limited, retry = is_rate_limited(user_id, "event_ready", limit=10, window_seconds=300)
    if limited:
        await update.message.reply_text(f"⏳ Слишком часто. Повтори через {retry} сек.")
        return
    record_user_activity(user_id, "event_ready")
    if not is_admin(user_id):
        await update.message.reply_text("⛔ Только администратор может запускать подтверждение участия.")
        return

    if not context.args:
        await update.message.reply_text("❌ Укажи event_id: /event_ready ev42")
        return

    event_id = context.args[0].strip()
    record = EVENTS.get(event_id)
    if not record:
        await update.message.reply_text("⚠️ Событие не найдено.")
        return

    info_text = (
        f"📣 Подтверждение участия\n"
        f"🏟 Событие: {record.title}\n"
        f"🕒 Время: {record.start_at:%d.%m.%Y %H:%M}\n"
        f"📍 Место: {record.location or 'не указано'}\n"
        f"📝 {record.note or 'Без комментариев.'}"
    )

    sent = 0
    for participant_id in record.participants:
        try:
            await context.bot.send_message(chat_id=participant_id, text=info_text)
            await context.bot.send_poll(
                chat_id=participant_id,
                question=f"{record.title}: подтверждаешь участие?",
                options=["Иду", "Не иду"],
                is_anonymous=False,
            )
            sent += 1
        except Forbidden:
            print(f"[WARN] Нельзя отправить опрос пользователю {participant_id}.")

    await update.message.reply_text(f"✅ Напоминание и опрос отправлены {sent} участникам события {event_id}.")


def schedule_event_reminder(context: ContextTypes.DEFAULT_TYPE, record: EventRecord):
    reminder_time = record.start_at - timedelta(hours=6)
    now = datetime.now()
    if reminder_time <= now:
        return

    context.job_queue.run_once(
        send_event_reminder,
        when=(reminder_time - now).total_seconds(),
        data={"event_id": record.event_id},
        name=f"event_reminder_{record.event_id}",
    )


async def send_event_reminder(context: ContextTypes.DEFAULT_TYPE):
    event_id = context.job.data["event_id"]
    record = EVENTS.get(event_id)
    if not record:
        return

    text = (
        f"⏰ Напоминание: через 6 часов событие «{record.title}».\n"
        f"🕒 {record.start_at:%d.%m.%Y %H:%M}\n"
        f"📍 {record.location or 'Локация не указана'}"
    )

    for participant_id in record.participants:
        try:
            await context.bot.send_message(chat_id=participant_id, text=text)
        except Forbidden:
            print(f"[WARN] Нельзя отправить напоминание пользователю {participant_id}.")


async def event_finished(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/event_finished <event_id>"""
    user_id = update.effective_user.id
    limited, retry = is_rate_limited(user_id, "event_finished", limit=10, window_seconds=300)
    if limited:
        await update.message.reply_text(f"⏳ Слишком часто. Повтори через {retry} сек.")
        return
    record_user_activity(user_id, "event_finished")
    if not is_admin(user_id):
        await update.message.reply_text("⛔ Только администратор может завершать события.")
        return

    if not context.args:
        await update.message.reply_text("❌ Укажи event_id: /event_finished ev42")
        return

    event_id = context.args[0].strip()
    record = EVENTS.pop(event_id, None)
    if not record:
        await update.message.reply_text("⚠️ Событие не найдено.")
        return

    # Полностью удалить чат бот не может. Закрываем цикл и уведомляем участников.
    end_text = f"✅ Событие «{record.title}» завершено. Чат события больше неактуален."
    if EVENT_CHAT_ID:
        try:
            await context.bot.send_message(chat_id=EVENT_CHAT_ID, text=end_text)
        except Exception as exc:
            print(f"[WARN] Не удалось отправить завершение в EVENT_CHAT_ID: {exc}")

    for participant_id in record.participants:
        try:
            await context.bot.send_message(chat_id=participant_id, text=end_text)
        except Forbidden:
            pass

    await update.message.reply_text(f"🧹 Событие {event_id} закрыто и удалено из памяти.")


# ======== ЗАЯВКИ К ТРЕНЕРУ ========
async def training_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Формат:
    /training_request <trainer_id>|<athlete_id>|<sport>|<when_text>
    Пример:
    /training_request 999|111|Теннис|12.03 19:30
    """
    user_id = update.effective_user.id
    limited, retry = is_rate_limited(user_id, "training_request", limit=10, window_seconds=300)
    if limited:
        await update.message.reply_text(f"⏳ Слишком часто. Повтори через {retry} сек.")
        return
    record_user_activity(user_id, "training_request")
    if not is_admin(user_id):
        await update.message.reply_text("⛔ Только администратор/бэкенд может отправлять заявки тренеру.")
        return

    payload = " ".join(context.args).strip()
    parts = [part.strip() for part in payload.split("|")]
    if len(parts) < 4 or not parts[0].isdigit() or not parts[1].isdigit():
        await update.message.reply_text("❌ Формат: /training_request trainer_id|athlete_id|sport|when")
        return

    trainer_id = int(parts[0])
    athlete_id = int(parts[1])
    sport = parts[2]
    when_text = parts[3]
    SPORT_COUNTER[sport] += 1

    trainer_text = (
        f"📩 Новая заявка на тренировку\n"
        f"👤 Игрок: {athlete_id}\n"
        f"🏅 Вид спорта: {sport}\n"
        f"🕒 Когда: {when_text}"
    )
    athlete_text = (
        f"✅ Заявка тренеру {trainer_id} отправлена.\n"
        f"🏅 Вид спорта: {sport}\n"
        f"🕒 Когда: {when_text}"
    )

    try:
        await context.bot.send_message(chat_id=trainer_id, text=trainer_text)
    except Forbidden:
        await update.message.reply_text(f"⚠️ Не удалось отправить тренеру {trainer_id}: бот не может написать первым.")
        return

    try:
        await context.bot.send_message(chat_id=athlete_id, text=athlete_text)
    except Forbidden:
        print(f"[WARN] Не удалось уведомить игрока {athlete_id}.")

    await update.message.reply_text("✅ Уведомление тренеру отправлено.")


async def track_user_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/track_user_profile <user_id>|<city>|<sport>"""
    user_id = update.effective_user.id
    limited, retry = is_rate_limited(user_id, "track_user_profile", limit=20, window_seconds=300)
    if limited:
        await update.message.reply_text(f"⏳ Слишком часто. Повтори через {retry} сек.")
        return
    record_user_activity(user_id, "track_user_profile")
    if not is_admin(user_id):
        await update.message.reply_text("⛔ Только администратор может обновлять профильные данные.")
        return

    payload = " ".join(context.args).strip()
    parts = [part.strip() for part in payload.split("|")]
    if len(parts) < 3 or not parts[0].isdigit():
        await update.message.reply_text("❌ Формат: /track_user_profile user_id|city|sport")
        return

    target_user_id = int(parts[0])
    city = parts[1]
    sport = parts[2]
    set_user_profile(target_user_id, city=city, sport=sport)
    await update.message.reply_text(f"✅ Профиль {target_user_id} обновлен: {city} / {sport}")


def parse_subscription_role(raw_role: str) -> Optional[str]:
    role = raw_role.strip().lower()
    if role in {"player", "trainer"}:
        return role
    return None


def format_subscription_line(grant: SubscriptionGrant) -> str:
    return (
        f"{grant.role}: {grant.plan} | до {grant.expires_at:%d.%m.%Y} "
        f"(выдано {grant.granted_at:%d.%m %H:%M})"
    )


async def cleanup_expired_subscriptions(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    expired = [grant for grant in list(SUBSCRIPTIONS.values()) if grant.expires_at <= now]
    if not expired:
        return

    for grant in expired:
        SUBSCRIPTIONS.pop((grant.user_id, grant.role), None)
        try:
            await context.bot.send_message(
                chat_id=grant.user_id,
                text=(
                    f"ℹ️ Подписка {grant.plan} ({grant.role}) завершилась.\n"
                    "Чтобы вернуть привилегии, продлите подписку в приложении."
                ),
            )
        except Forbidden:
            print(f"[WARN] Не удалось уведомить пользователя {grant.user_id} об окончании подписки.")


async def grant_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/grant_subscription <user_id>|<player/trainer>|<plan>|<days>"""
    user_id = update.effective_user.id
    limited, retry = is_rate_limited(user_id, "grant_subscription", limit=25, window_seconds=300)
    if limited:
        await update.message.reply_text(f"⏳ Слишком часто. Повтори через {retry} сек.")
        return
    record_user_activity(user_id, "grant_subscription")
    if not is_admin(user_id):
        await update.message.reply_text("⛔ Только администратор может выдавать подписки.")
        return

    payload = " ".join(context.args).strip()
    parts = [part.strip() for part in payload.split("|")]
    if len(parts) < 4 or not parts[0].isdigit() or not parts[3].isdigit():
        await update.message.reply_text("❌ Формат: /grant_subscription user_id|player/trainer|plan|days")
        return

    target_user_id = int(parts[0])
    role = parse_subscription_role(parts[1])
    if not role:
        await update.message.reply_text("❌ Роль должна быть player или trainer.")
        return

    plan = parts[2].strip()
    if not plan:
        await update.message.reply_text("❌ Укажи название плана подписки.")
        return

    days = int(parts[3])
    if days <= 0 or days > 3660:
        await update.message.reply_text("❌ Срок должен быть от 1 до 3660 дней.")
        return

    now = datetime.now()
    grant = SubscriptionGrant(
        user_id=target_user_id,
        role=role,
        plan=plan,
        granted_by=user_id,
        granted_at=now,
        expires_at=now + timedelta(days=days),
    )
    SUBSCRIPTIONS[(target_user_id, role)] = grant

    await update.message.reply_text(
        f"✅ Подписка выдана: {target_user_id} → {format_subscription_line(grant)}"
    )

    try:
        await context.bot.send_message(
            chat_id=target_user_id,
            text=(
                f"🎉 Вам выдана подписка {plan} ({role}) на {days} дн.\n"
                f"Срок действия до {grant.expires_at:%d.%m.%Y}."
            ),
        )
    except Forbidden:
        print(f"[WARN] Не удалось уведомить пользователя {target_user_id} о подписке.")


async def revoke_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/revoke_subscription <user_id>|<player/trainer>"""
    user_id = update.effective_user.id
    limited, retry = is_rate_limited(user_id, "revoke_subscription", limit=25, window_seconds=300)
    if limited:
        await update.message.reply_text(f"⏳ Слишком часто. Повтори через {retry} сек.")
        return
    record_user_activity(user_id, "revoke_subscription")
    if not is_admin(user_id):
        await update.message.reply_text("⛔ Только администратор может отзывать подписки.")
        return

    payload = " ".join(context.args).strip()
    parts = [part.strip() for part in payload.split("|")]
    if len(parts) < 2 or not parts[0].isdigit():
        await update.message.reply_text("❌ Формат: /revoke_subscription user_id|player/trainer")
        return

    target_user_id = int(parts[0])
    role = parse_subscription_role(parts[1])
    if not role:
        await update.message.reply_text("❌ Роль должна быть player или trainer.")
        return

    removed = SUBSCRIPTIONS.pop((target_user_id, role), None)
    if not removed:
        await update.message.reply_text("⚠️ Активная подписка не найдена.")
        return

    await update.message.reply_text(f"🧹 Подписка снята: {target_user_id} ({role}).")


async def subscription_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/subscription_status <user_id>"""
    user_id = update.effective_user.id
    limited, retry = is_rate_limited(user_id, "subscription_status", limit=30, window_seconds=300)
    if limited:
        await update.message.reply_text(f"⏳ Слишком часто. Повтори через {retry} сек.")
        return
    record_user_activity(user_id, "subscription_status")
    if not is_admin(user_id):
        await update.message.reply_text("⛔ Только администратор может смотреть подписки.")
        return

    if not context.args or not context.args[0].strip().isdigit():
        await update.message.reply_text("❌ Формат: /subscription_status user_id")
        return

    target_user_id = int(context.args[0].strip())
    now = datetime.now()
    rows = []
    for key, grant in list(SUBSCRIPTIONS.items()):
        if grant.expires_at <= now:
            SUBSCRIPTIONS.pop(key, None)
            continue
        if grant.user_id == target_user_id:
            rows.append(format_subscription_line(grant))

    if not rows:
        await update.message.reply_text(f"ℹ️ У пользователя {target_user_id} нет активных подписок.")
        return

    await update.message.reply_text(
        f"🎟 Подписки пользователя {target_user_id}:\n" + "\n".join(f"• {row}" for row in rows)
    )


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    print(f"[ERROR] {context.error}")


# ======== MAIN ========
def main():
    load_local_env()
    token = get_bot_token()

    app = ApplicationBuilder().token(token).build()
    app.job_queue.run_repeating(cleanup_expired_subscriptions, interval=3600, first=10, name="cleanup_subscriptions")

    app.add_handler(CommandHandler("start", start))

    app.add_handler(MessageHandler(filters.Regex("^Админ-панель$"), open_admin_panel))
    app.add_handler(CallbackQueryHandler(admin_callbacks, pattern=r"^admin:"))

    app.add_handler(CommandHandler("event_created", event_created))
    app.add_handler(CommandHandler("event_ready", event_ready))
    app.add_handler(CommandHandler("event_finished", event_finished))
    app.add_handler(CommandHandler("training_request", training_request))
    app.add_handler(CommandHandler("track_user_profile", track_user_profile))
    app.add_handler(CommandHandler("grant_subscription", grant_subscription))
    app.add_handler(CommandHandler("revoke_subscription", revoke_subscription))
    app.add_handler(CommandHandler("subscription_status", subscription_status))

    app.add_error_handler(on_error)

    print("[INFO] Запускаем long-polling Telegram API...")
    while True:
        try:
            app.run_polling(
                allowed_updates=Update.ALL_TYPES,
                bootstrap_retries=5,
                drop_pending_updates=False,
                close_loop=False,
            )
            break
        except TimedOut:
            print("[WARN] Telegram API timeout при запуске/опросе. Повтор через 5 сек...")
            time.sleep(5)
        except NetworkError as err:
            print(f"[WARN] Ошибка сети Telegram API: {err}. Повтор через 5 сек...")
            time.sleep(5)


if __name__ == "__main__":
    main()