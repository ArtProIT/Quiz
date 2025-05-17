import json
import os

LEADERBOARD_FILE = "leaderboard.json"

def load_leaderboard():
    if not os.path.exists(LEADERBOARD_FILE):
        return {}
    with open(LEADERBOARD_FILE, "r", encoding="utf-8") as file:
        try:
            return json.load(file)
        except json.JSONDecodeError:
            return {}

def is_username_taken(category, username):
    leaderboard = load_leaderboard()
    return username in leaderboard.get(category, {})

def save_to_leaderboard(category, username, score):
    leaderboard = load_leaderboard()
    if category not in leaderboard:
        leaderboard[category] = {}
    leaderboard[category][username] = max(score, leaderboard[category].get(username, 0))
    with open(LEADERBOARD_FILE, "w", encoding="utf-8") as file:
        json.dump(leaderboard, file, ensure_ascii=False, indent=2)

def format_leaderboard(category):
    leaderboard = load_leaderboard()
    category_board = leaderboard.get(category, {})
    if not category_board:
        return "Таблица лидеров пуста."

    sorted_board = sorted(category_board.items(), key=lambda x: x[1], reverse=True)
    result_lines = []
    medals = ["🥇", "🥈", "🥉"]

    for idx, (username, score) in enumerate(sorted_board, start=1):
        medal = medals[idx - 1] if idx <= 3 else f"{idx}."
        result_lines.append(f"{medal} {username} - {score} {pluralize_ball(score)}")

    return "\n".join(result_lines)

def pluralize_ball(score):
    if score % 10 == 1 and score % 100 != 11:
        return "балл"
    elif 2 <= score % 10 <= 4 and not 12 <= score % 100 <= 14:
        return "балла"
    else:
        return "баллов"
