import logging
import os
import random
import time
from typing import Dict, List, Optional

import vk_api
from requests.exceptions import RequestException
from vk_api.bot_longpoll import VkBotEventType, VkBotLongPoll
from vk_api.exceptions import ApiError
from vk_api.keyboard import VkKeyboard, VkKeyboardColor

from storage import Storage
from trainer_engine import TOPIC_LABELS, choose_topic, make_question, route_text, topics_help_text

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

VK_BOT_TOKEN="vk1.a.L2yJlZdhHFcsD-fXO4ZnwcWH1JdpdzV3XfW5HLsVPJAowB1YPxIEc7D9RvXtt6vgaVKX6RCrDeJQV_UWeF-MUPV9Vm9ddLZ9p6eLDaropDymSwy0zrhXwJ2rnOZZIN6N2JWfgtPiUn6HBGkaaZ-0tRnkO6mPLmRW3ktn0HZbaQlsF8MlHnmAwbSKTbDpj4tD9LJ8kGnwSNH7s6lQRthyjA"
VK_GROUP_ID="237665030"

def _token() -> str:
    token = VK_BOT_TOKEN
    if not token:
        raise RuntimeError("Не задан VK_BOT_TOKEN")
    return token


def _group_id() -> int:
    group_id = VK_GROUP_ID
    if not group_id.isdigit():
        raise RuntimeError("Не задан VK_GROUP_ID (числовой id сообщества VK)")
    return int(group_id)


def main_keyboard() -> str:
    kb = VkKeyboard(one_time=False, inline=False)
    kb.add_button("Все", color=VkKeyboardColor.PRIMARY)
    kb.add_button("Темы", color=VkKeyboardColor.SECONDARY)
    kb.add_line()
    kb.add_button("Диагностика", color=VkKeyboardColor.POSITIVE)
    kb.add_button("Маршрут", color=VkKeyboardColor.SECONDARY)
    kb.add_line()
    kb.add_button("Подборка 10", color=VkKeyboardColor.PRIMARY)
    kb.add_button("Статистика", color=VkKeyboardColor.SECONDARY)
    kb.add_line()
    kb.add_button("Помощь", color=VkKeyboardColor.SECONDARY)
    return kb.get_keyboard()


def answer_keyboard(option_count: int) -> str:
    kb = VkKeyboard(one_time=True, inline=False)
    for idx in range(1, option_count + 1):
        kb.add_button(str(idx), color=VkKeyboardColor.PRIMARY)
        if idx % 4 == 0 and idx != option_count:
            kb.add_line()
    kb.add_line()
    kb.add_button("Стоп", color=VkKeyboardColor.NEGATIVE)
    return kb.get_keyboard()


def send_message(vk, user_id: int, text: str, keyboard: Optional[str] = None) -> None:
    params = {
        "user_id": user_id,
        "message": text,
        "random_id": random.randint(1, 2_000_000_000),
    }
    if keyboard:
        params["keyboard"] = keyboard
    try:
        vk.messages.send(**params)
    except ApiError as exc:
        if getattr(exc, "code", None) == 912 and "keyboard" in params:
            fallback = dict(params)
            fallback.pop("keyboard", None)
            vk.messages.send(**fallback)
            return
        raise


def format_question(payload: Dict) -> str:
    option_count = len(payload["options"])
    prefix = ""
    if payload.get("is_review"):
        prefix = "[Повторение ошибки]\n"
    elif payload.get("mode", {}).get("type") == "diagnostic":
        mode = payload["mode"]
        current = mode["total"] - mode["remaining"] + 1
        prefix = f"[Диагностика {current}/{mode['total']}]\n"

    lines = [
        prefix + f"Тема: {TOPIC_LABELS.get(payload['topic'], payload['topic'])}",
        payload["prompt"],
        "",
    ]
    for idx, option in enumerate(payload["options"], start=1):
        lines.append(f"{idx}) {option}")
    lines.append("")
    lines.append(f"Ответьте числом 1-{option_count}.")
    return "\n".join(lines)


def _diagnostic_plan(total: int = 15) -> List[str]:
    topics = list(TOPIC_LABELS.keys())
    base = total // len(topics)
    rem = total % len(topics)
    plan: List[str] = []
    for idx, topic in enumerate(topics):
        plan.extend([topic] * (base + (1 if idx < rem else 0)))
    random.shuffle(plan)
    return plan


def _pick_topic(storage: Storage, user_id: int, mode: Dict) -> (str, bool):
    topic_stats = storage.get_topic_stats(user_id)
    if mode["type"] == "single":
        return mode["topic"], False

    if mode["type"] == "diagnostic":
        index = mode["total"] - mode["remaining"]
        return mode["plan"][index], False

    due_topics = storage.get_due_review_topics(user_id, limit=3)
    if due_topics:
        return random.choice(due_topics), True

    return choose_topic(topic_stats), False


def build_question_payload(storage: Storage, user_id: int, mode: Dict) -> Dict:
    topic_stats = storage.get_topic_stats(user_id)
    topic, is_review = _pick_topic(storage, user_id, mode)
    q = make_question(topic, topic_stats)
    return {
        "mode": mode,
        "topic": q.topic,
        "prompt": q.prompt,
        "options": q.options,
        "answer_index": q.answer_index,
        "explanation": q.explanation,
        "is_review": is_review,
    }


def parse_mode(text: str) -> Optional[Dict]:
    msg = text.strip().lower()

    if msg in {"все", "all"}:
        return {"type": "mixed", "remaining": None}

    if msg.startswith("подборка"):
        parts = msg.split()
        count = 10
        if len(parts) > 1 and parts[1].isdigit():
            count = max(1, min(100, int(parts[1])))
        return {"type": "mixed", "remaining": count}

    if msg.startswith("тема"):
        parts = msg.split(maxsplit=1)
        if len(parts) == 2 and parts[1] in TOPIC_LABELS:
            return {"type": "single", "topic": parts[1], "remaining": None}

    if msg == "диагностика":
        plan = _diagnostic_plan(15)
        return {"type": "diagnostic", "remaining": len(plan), "total": len(plan), "plan": plan}

    return None


def stat_message(storage: Storage, user_id: int) -> str:
    user = storage.get_user_stats(user_id)
    topic_stats = storage.get_topic_stats(user_id)
    total = user.correct + user.wrong
    acc = (user.correct / total * 100) if total else 0.0

    lines = [
        "Ваша статистика:",
        f"- Всего заданий: {total}",
        f"- Верно: {user.correct}",
        f"- Ошибок: {user.wrong}",
        f"- Точность: {acc:.1f}%",
        "",
        route_text(topic_stats),
    ]

    return "\n".join(lines)


def _feedback(active: Dict, choice: int, is_correct: bool) -> str:
    chosen = active["options"][choice]
    correct = active["options"][active["answer_index"]]
    if is_correct:
        return (
            "Верно!\n"
            f"Почему это верно: {active['explanation']}\n"
            f"Мини-совет: запомните шаблон `{correct}` и сравнивайте с похожими случаями."
        )

    return (
        f"Неверно. Правильный ответ: {active['answer_index'] + 1}) {correct}\n"
        f"Ваш вариант `{chosen}` не подходит к правилу этого задания.\n"
        f"Разбор: {active['explanation']}\n"
        "Мини-практика: попробуйте сформулировать правило в 1 предложении и решить ещё 2 похожих вопроса."
    )


def start_mode(vk, storage: Storage, user_id: int, mode: Dict) -> None:
    payload = build_question_payload(storage, user_id, mode)
    storage.set_active_question(user_id, payload)
    send_message(vk, user_id, format_question(payload), keyboard=answer_keyboard(len(payload["options"])))


def _finalize_diagnostic(vk, storage: Storage, user_id: int, text_result: str) -> None:
    storage.set_diagnostic_done(user_id, True)
    topic_stats = storage.get_topic_stats(user_id)
    send_message(
        vk,
        user_id,
        text_result + "\n\nДиагностика завершена!\n" + route_text(topic_stats),
        keyboard=main_keyboard(),
    )


def handle_answer(vk, storage: Storage, user_id: int, text: str, active: Dict) -> None:
    msg = text.strip().lower()
    if msg == "стоп":
        storage.clear_active_question(user_id)
        send_message(vk, user_id, "Тренировка остановлена.", keyboard=main_keyboard())
        return

    max_option = len(active["options"])
    allowed = {str(idx) for idx in range(1, max_option + 1)}
    if msg not in allowed:
        send_message(
            vk,
            user_id,
            f"Нужен ответ 1-{max_option} или команда 'Стоп'.",
            keyboard=answer_keyboard(max_option),
        )
        return

    choice = int(msg) - 1
    is_correct = choice == active["answer_index"]
    storage.update_result(user_id, active["topic"], is_correct)
    text_result = _feedback(active, choice, is_correct)

    mode = active["mode"]
    if mode.get("remaining") is not None:
        mode["remaining"] -= 1
        if mode["remaining"] <= 0:
            storage.clear_active_question(user_id)
            if mode.get("type") == "diagnostic":
                _finalize_diagnostic(vk, storage, user_id, text_result)
                return

            send_message(
                vk,
                user_id,
                text_result + "\n\nПодборка завершена!\n" + stat_message(storage, user_id),
                keyboard=main_keyboard(),
            )
            return

    next_payload = build_question_payload(storage, user_id, mode)
    storage.set_active_question(user_id, next_payload)
    send_message(
        vk,
        user_id,
        text_result + "\n\n" + format_question(next_payload),
        keyboard=answer_keyboard(len(next_payload["options"])),
    )


def handle_idle_message(vk, storage: Storage, user_id: int, text: str) -> None:
    msg = text.strip().lower()

    if msg in {"start", "начать", "/start", "привет"}:
        tip = ""
        if not storage.is_diagnostic_done(user_id):
            tip = "\nРекомендуемый первый шаг: команда `диагностика` (15 вопросов)."

        send_message(
            vk,
            user_id,
            "Привет, это ЕГЭ-тренер по русскому и я уже готов к работе.\n"
            "Чтобы начать тренировку выберите режим: `все`, `подборка 10`, `тема <id>`.\n"
            "Для того чтобы получить диагностику своего уровня подготовки напишите: 'диагностика'`.\n"
            "Команда `темы` покажет список тем." + tip,
            keyboard=main_keyboard(),
        )
        return

    if msg in {"помощь", "help"}:
        send_message(
            vk,
            user_id,
            "Команды:\n"
            "- `диагностика` - стартовый тест 15 заданий\n"
            "- `маршрут` - персональный план по темам\n"
            "- `все` - бесконечная смешанная тренировка\n"
            "- `подборка N` - N - номер задания\n"
            "- `тема <id>` - тренировка по конкретной теме\n"
            "- `статистика` - ваш прогресс\n"
            "- `стоп` - остановить текущую тренировку",
            keyboard=main_keyboard(),
        )
        return

    if msg == "темы":
        send_message(vk, user_id, topics_help_text(), keyboard=main_keyboard())
        return

    if msg == "маршрут":
        send_message(vk, user_id, route_text(storage.get_topic_stats(user_id)), keyboard=main_keyboard())
        return

    if msg == "статистика":
        send_message(vk, user_id, stat_message(storage, user_id), keyboard=main_keyboard())
        return

    mode = parse_mode(msg)
    if mode:
        start_mode(vk, storage, user_id, mode)
        return

    send_message(
        vk,
        user_id,
        "Не понял команду. Напишите `помощь` или нажмите кнопку меню.",
        keyboard=main_keyboard(),
    )


def _build_vk_clients(token: str, group_id: int):
    vk_session = vk_api.VkApi(token=token)
    vk_session.http.trust_env = False
    vk_session.http.proxies.clear()
    vk = vk_session.get_api()
    longpoll = VkBotLongPoll(vk_session, group_id)
    return vk, longpoll


def run() -> None:
    storage = Storage()
    token = _token()
    group_id = _group_id()

    logging.info("VK ЕГЭ-тренер запущен")

    while True:
        try:
            vk, longpoll = _build_vk_clients(token, group_id)
            for event in longpoll.listen():
                if event.type != VkBotEventType.MESSAGE_NEW:
                    continue

                msg_obj = event.object.get("message", {})
                if msg_obj.get("from_id", 0) <= 0:
                    continue

                user_id = msg_obj["from_id"]
                text = (msg_obj.get("text") or "").strip()
                if not text:
                    continue

                storage.ensure_user(user_id)
                active = storage.get_active_question(user_id)

                try:
                    if active is not None:
                        handle_answer(vk, storage, user_id, text, active)
                    else:
                        handle_idle_message(vk, storage, user_id, text)
                except Exception as exc:
                    logging.exception("Ошибка обработки сообщения")
                    send_message(
                        vk,
                        user_id,
                        "Произошла ошибка при обработке запроса. Попробуйте ещё раз.",
                        keyboard=main_keyboard(),
                    )
                    if isinstance(exc, RuntimeError):
                        raise

        except KeyboardInterrupt:
            logging.info("Бот остановлен.")
            break
        except RequestException as exc:
            logging.warning("Сетевая ошибка LongPoll: %s. Переподключение через 5 секунд.", exc)
            time.sleep(5)
        except Exception:
            logging.exception("Критическая ошибка цикла бота. Перезапуск через 5 секунд.")
            time.sleep(5)


if __name__ == "__main__":
    run()
