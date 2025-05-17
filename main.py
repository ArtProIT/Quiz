import telebot
from telebot import types
from config import TOKEN
from questions import QUESTIONS
from storage import save_to_leaderboard, format_leaderboard, is_username_taken
import random
import time
import threading
from storage import pluralize_ball

bot = telebot.TeleBot(TOKEN)
user_sessions = {}

ANSWER_TIME_LIMIT = 30
TIMER_STEPS = [20, 10, 5]
CATEGORIES = ["История", "Кино и телевидение", "Мифология и религия", "Наука", "Призовая"]


def start_game(chat_id, category):
    markup = types.ReplyKeyboardRemove()
    bot.send_message(chat_id, f"Перед началом укажи своё имя для категории {category}:", reply_markup=markup)
    user_sessions[chat_id] = user_sessions.get(chat_id, {})
    user_sessions[chat_id].update({"awaiting_name": True, "category": category})


def send_start_button(chat_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("Старт"))
    bot.send_message(chat_id, "Нажми Старт, чтобы начать игру!", reply_markup=markup)


def send_main_menu(chat_id):
    reset_session_flags(chat_id)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    buttons = CATEGORIES + ["Таблица лидеров", "Правила игры", "Выход"]
    markup.add(*[types.KeyboardButton(b) for b in buttons])
    bot.send_message(chat_id, "Выбери категорию для игры или действие:", reply_markup=markup)


@bot.message_handler(commands=['start'])
def handle_start(message):
    send_start_button(message.chat.id)


@bot.message_handler(func=lambda message: True)
def universal_handler(message):
    chat_id = message.chat.id
    text = message.text.strip()
    lower_text = text.lower()

    # Создаём сессию если её нет, например после перезапуска
    if chat_id not in user_sessions:
        user_sessions[chat_id] = {}
        send_main_menu(chat_id)
        return

    # Завершение регистрации имени
    if user_sessions[chat_id].get("awaiting_name"):
        if lower_text == "выход":
            bot.send_message(chat_id, "Спасибо за игру! Чтобы начать снова — напиши /start.")
            send_start_button(chat_id)
            del user_sessions[chat_id]
            return
        register_user(chat_id, text)
        return

    # Продолжение после показа приза
    if lower_text in ["🎁 главный приз", "главный приз"]:
        bot.send_message(chat_id, "🏆 Главный приз — это сюрприз! Удачи!")
        return
    elif lower_text == "🚀 продолжить":
        send_question(chat_id)
        return

    # Активная игра
    if "questions" in user_sessions[chat_id]:
        handle_game_answer(chat_id, text)
        return

    # Выбор категории для таблицы лидеров
    if user_sessions[chat_id].get("awaiting_leaderboard_category"):
        category = text.capitalize()
        if category in CATEGORIES:
            board = format_leaderboard(category)
            bot.send_message(chat_id, f"Таблица лидеров для {category}:\n{board}")
            del user_sessions[chat_id]
            send_main_menu(chat_id)
            return
        elif lower_text == "назад":
            del user_sessions[chat_id]
            send_main_menu(chat_id)
            return
        else:
            bot.send_message(chat_id, "Выбери категорию из списка.")
            return

    # Главное меню
    if lower_text == "старт":
        send_main_menu(chat_id)
        return
    elif lower_text == "таблица лидеров":
        show_leaderboard(chat_id)
        return
    elif lower_text in [cat.lower() for cat in CATEGORIES]:
        start_game(chat_id, lower_text.capitalize())
        return
    elif lower_text == "выход":
        bot.send_message(chat_id, "Спасибо за игру! Чтобы начать снова — напиши /start.")
        send_start_button(chat_id)
        user_sessions.pop(chat_id, None)
        return  # ⬅️ Тут остановка, не нужно переобрабатывать
    elif lower_text == "правила игры":
        show_rules(chat_id)
        return

    # Перехват неожиданных ответов
    if any(text in q["options"] for questions in QUESTIONS.values() for q in questions) or lower_text in ["50/50",
                                                                                                          "помощь зала",
                                                                                                          "🎁 50/50",
                                                                                                          "🎁 помощь зала"]:
        recovery_message = (
            "❗ *Ой\\! Похоже, меня только что перезапустили или я пережил обновление\\.*\n\n"
            "🔄 *Пожалуйста, нажми \"Старт\" или напиши /start, чтобы начать игру заново\\.*"
        )
        bot.send_message(chat_id, recovery_message, parse_mode="MarkdownV2")
        send_start_button(chat_id)
        return

    # Неизвестная команда
    bot.send_message(chat_id, "Я не понял команду. Попробуй снова.")


def register_user(chat_id, username):
    category = user_sessions[chat_id]["category"]
    if is_username_taken(category, username):
        bot.send_message(chat_id, "Это имя уже занято в этой категории. Попробуй другое.")
        return
    category_questions = QUESTIONS[category]
    user_sessions[chat_id].update({
        "username": username,
        "score": 0,
        "questions": random.sample(category_questions, len(category_questions)),
        "current_index": 0,
        "awaiting_name": False,
        "hints": {"50/50": True, "помощь зала": True},
        "streak": 0,
        "track_bonus_5050": False
    })
    if category == "Призовая":
        show_prize_button(chat_id)
    else:
        send_question(chat_id)


def send_question(chat_id):
    session = user_sessions[chat_id]
    if session["current_index"] >= len(session["questions"]):
        finish_game(chat_id)
        return

    q = session["questions"][session["current_index"]]
    current = session["current_index"] + 1
    total = len(session["questions"])
    question_header = escape_markdown(f"Вопрос {current} из {total}:\n\n")

    # Сообщение о сложности
    difficulty_notice = ""
    if q.get("double_points", False):
        difficulty_notice = escape_markdown("‼️ Это сложный вопрос на 2 балла. Подсказки недоступны.\n\n")

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    options = q["options"]
    for i in range(0, len(options), 2):
        row = [types.KeyboardButton(options[i])]
        if i + 1 < len(options):
            row.append(types.KeyboardButton(options[i + 1]))
        markup.add(*row)

    markup.add(types.KeyboardButton("🚪 Выйти, пора бежать"))

    # Добавление подсказок только если это не double_points вопрос
    if not q.get("double_points", False):
        hint_buttons = []
        if session["hints"]["50/50"]:
            hint_buttons.append(types.KeyboardButton("🎁 50/50"))
        if session["hints"]["помощь зала"]:
            hint_buttons.append(types.KeyboardButton("🎁 Помощь зала"))
        if hint_buttons:
            markup.add(*hint_buttons)

    escaped_question = escape_markdown(q['question'])
    bot.send_message(
        chat_id,
        f"{question_header}{difficulty_notice}*{escaped_question}*",
        reply_markup=markup,
        parse_mode="MarkdownV2"
    )

    session["active_options"] = q["options"]
    session["answered"] = False
    start_question_timer(chat_id, session["current_index"])
    session["question_time"] = time.time()


def handle_game_answer(chat_id, user_answer):
    session = user_sessions[chat_id]

    if user_answer == "🚪 Выйти, пора бежать":
        finish_game(chat_id)
        return

    q = session["questions"][session["current_index"]]
    elapsed = time.time() - session.get("question_time", 0)

    if session.get("answered", False):
        return

    if not q.get("double_points", False):
        if user_answer in ["50/50", "🎁 50/50"] and session["hints"]["50/50"]:
            apply_50_50(chat_id, session)
            return
        if user_answer in ["помощь зала", "🎁 Помощь зала"] and session["hints"]["помощь зала"]:
            apply_audience_help(chat_id, session)
            return

    session["answered"] = True

    if elapsed > ANSWER_TIME_LIMIT:
        bot.send_message(chat_id, f"⏰ Время вышло! Правильный ответ был: {q['answer']}")
        session["current_index"] += 1
        time.sleep(1)
        send_question(chat_id)
        return

    if user_answer not in session.get("active_options", []):
        bot.send_message(chat_id, "Выберите один из предложенных вариантов.")
        session["answered"] = False
        return

    if user_answer == q["answer"]:
        points = 2 if q.get("double_points", False) else 1
        session["score"] += points
        session["streak"] += 1
        bot.send_message(chat_id, f"✅ Верно! {q['answer']} (+{points} балл{'а' if points == 1 else 'ов'})")

        if session.get("track_bonus_5050") and session["streak"] == 3:
            if not session["hints"]["50/50"]:
                session["hints"]["50/50"] = True
                bot.send_message(chat_id, "🎉 Бонус! Ты снова получил подсказку 50/50 за 3 правильных ответа подряд.")
            session["streak"] = 0
    else:
        session["streak"] = 0
        bot.send_message(chat_id, f"❌ Неверно! Правильный ответ: {q['answer']}")

    session["current_index"] += 1
    send_question(chat_id)


def apply_50_50(chat_id, session):
    q = session["questions"][session["current_index"]]
    correct = q["answer"]
    wrong_options = [opt for opt in q["options"] if opt != correct]
    reduced_options = [correct, random.choice(wrong_options)]
    random.shuffle(reduced_options)

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for option in reduced_options:
        markup.add(types.KeyboardButton(option))
    if session["hints"]["помощь зала"]:
        markup.add(types.KeyboardButton("помощь зала"))

    session["hints"]["50/50"] = False
    session["active_options"] = reduced_options
    session["track_bonus_5050"] = True
    session["streak"] = 0

    bot.send_message(chat_id, "Осталось два варианта:", reply_markup=markup)


def apply_audience_help(chat_id, session):
    q = session["questions"][session["current_index"]]
    votes = generate_audience_votes(q["options"], q["answer"])
    vote_results = "\n".join([f"{opt}: {percent}%" for opt, percent in votes.items()])

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for option in q["options"]:
        markup.add(types.KeyboardButton(option))
    if session["hints"]["50/50"]:
        markup.add(types.KeyboardButton("50/50"))

    session["hints"]["помощь зала"] = False
    session["active_options"] = q["options"]

    bot.send_message(chat_id, "Помощь зала распределила голоса:\n\n" + vote_results, reply_markup=markup)


def generate_audience_votes(options, correct_answer):
    votes = {}
    remaining = 100
    shuffled_options = options.copy()
    random.shuffle(shuffled_options)

    for option in shuffled_options:
        if option == correct_answer:
            continue
        vote = random.randint(5, 25)
        votes[option] = vote
        remaining -= vote

    votes[correct_answer] = remaining
    return dict(sorted(votes.items(), key=lambda item: item[1], reverse=True))


def start_question_timer(chat_id, question_index):
    def timer_action():
        msg = bot.send_message(chat_id, f"⏳ {ANSWER_TIME_LIMIT} секунд осталось...")
        message_id = msg.message_id

        for remaining in TIMER_STEPS:
            time.sleep(ANSWER_TIME_LIMIT - remaining)
            session = user_sessions.get(chat_id)
            if not session or session.get("current_index") != question_index or session.get("answered", False):
                return
            try:
                bot.edit_message_text(f"⏳ {remaining} секунд осталось...", chat_id, message_id)
            except Exception:
                pass

        time.sleep(TIMER_STEPS[-1])
        session = user_sessions.get(chat_id)
        if session and session.get("current_index") == question_index and not session.get("answered", False):
            q = session["questions"][question_index]
            try:
                bot.edit_message_text("⏰ Время вышло!", chat_id, message_id)
            except Exception:
                pass
            bot.send_message(chat_id, f"Правильный ответ был: {q['answer']}")
            session["current_index"] += 1
            send_question(chat_id)

    threading.Thread(target=timer_action).start()


def escape_markdown(text):
    escape_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for ch in escape_chars:
        text = text.replace(ch, f'\\{ch}')
    return text


def show_rules(chat_id):
    rules_text = (
        f"📜 Правила игры:\n\n"
        f"1️⃣ У тебя есть {ANSWER_TIME_LIMIT} секунд на каждый вопрос. Если не успеешь ответить — засчитывается как неправильный.\n"
        "2️⃣ Доступны две подсказки:\n"
        "   🎁 50/50 — убирает два неверных варианта.\n"
        "   🎁 Помощь зала — показывает голосование зрителей.\n"
        "3️⃣ За 3 правильных ответа подряд ты получаешь бонус 50/50 снова.\n\n"
        "Готов? Жми Начать играть!"
    )
    bot.send_message(chat_id, escape_markdown(rules_text), parse_mode="MarkdownV2")


def reset_session_flags(chat_id):
    if chat_id not in user_sessions:
        user_sessions[chat_id] = {}
    preserved = {k: v for k, v in user_sessions[chat_id].items() if k in ["username", "category"]}
    user_sessions[chat_id] = preserved


def finish_game(chat_id):
    session = user_sessions.pop(chat_id, None)
    if not session:
        send_main_menu(chat_id)
        return

    score = session['score']
    category = session['category']
    save_to_leaderboard(category, session["username"], score)

    bot.send_message(chat_id, f"Игра окончена! Ты набрал {score} {pluralize_ball(score)} в категории {category}.")

    # Сбрасываем состояния перед возвратом в меню
    reset_session_flags(chat_id)
    send_main_menu(chat_id)


def show_leaderboard(chat_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    buttons = CATEGORIES + ["Назад"]
    markup.add(*[types.KeyboardButton(b) for b in buttons])
    bot.send_message(chat_id, "Выбери категорию для просмотра таблицы лидеров:", reply_markup=markup)

    # НЕ перезаписывать сессию, а дополнять
    if chat_id not in user_sessions:
        user_sessions[chat_id] = {}
    user_sessions[chat_id]["awaiting_leaderboard_category"] = True


def show_prize_button(chat_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("🎁 Главный приз"))
    markup.add(types.KeyboardButton("🚀 Продолжить"))
    bot.send_message(chat_id, "Ты участвуешь за Главный приз! Хочешь узнать подробнее?", reply_markup=markup)


if __name__ == "__main__":
    print("Бот запущен...")
    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=60)
        except Exception as e:
            print(f"Произошла ошибка: {e}")
            time.sleep(5)
