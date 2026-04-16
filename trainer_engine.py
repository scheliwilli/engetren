import random
from dataclasses import dataclass
from typing import Dict, List

TOPIC_LABELS: Dict[str, str] = {
    "n_nn": "Н/НН",
    "punct": "Пунктуация",
    "stress": "Ударение",
    "not_with_word": "НЕ с разными частями речи",
    "paronyms": "Паронимы",
}

FIPI_SOURCES = {
    "demoversions": "https://fipi.ru/ege/demoversii-specifikacii-kodifikatory",
    "open_bank": "https://fipi.ru/ege/otkrytyy-bank-zadaniy-ege",
    "methodical": "https://fipi.ru/ege/analiticheskie-i-metodicheskie-materialy",
}

TOPIC_EGE_MAP = {
    "stress": "Задание 4 (орфоэпические нормы)",
    "paronyms": "Задание 5 (паронимы)",
    "not_with_word": "Задание 13 (слитное/раздельное НЕ)",
    "n_nn": "Задание 15 (Н/НН)",
    "punct": "Задания 16-21 (пунктуация)",
}


@dataclass
class Question:
    topic: str
    prompt: str
    options: List[str]
    answer_index: int
    explanation: str


def question_signature(question: Question) -> str:
    return f"{question.topic}|{question.prompt}"


def topic_reference(topic: str) -> str:
    return TOPIC_EGE_MAP.get(topic, "Тема ЕГЭ по русскому языку")


def sources_text() -> str:
    return (
        "Официальные источники ФИПИ:\n"
        f"- Демоверсии/кодификатор/спецификация: {FIPI_SOURCES['demoversions']}\n"
        f"- Открытый банк заданий ЕГЭ: {FIPI_SOURCES['open_bank']}\n"
        f"- Аналитические и методические материалы: {FIPI_SOURCES['methodical']}\n\n"
        "Привязка тем тренажера:\n"
        f"- {TOPIC_LABELS['stress']}: {TOPIC_EGE_MAP['stress']}\n"
        f"- {TOPIC_LABELS['paronyms']}: {TOPIC_EGE_MAP['paronyms']}\n"
        f"- {TOPIC_LABELS['not_with_word']}: {TOPIC_EGE_MAP['not_with_word']}\n"
        f"- {TOPIC_LABELS['n_nn']}: {TOPIC_EGE_MAP['n_nn']}\n"
        f"- {TOPIC_LABELS['punct']}: {TOPIC_EGE_MAP['punct']}"
    )


def _shuffle_options(options: List[str], correct_text: str) -> (List[str], int):
    random.shuffle(options)
    return options, options.index(correct_text)


def _unique_normalized(items: List[str]) -> List[str]:
    unique: List[str] = []
    seen = set()
    for item in items:
        normalized = " ".join(item.split())
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique


def _build_question(
    topic: str,
    prompt: str,
    correct: str,
    distractors: List[str],
    explanation: str,
) -> Question:
    options = _unique_normalized([correct, *distractors])
    if len(options) < 2:
        options.append("другой вариант")
    options, answer_index = _shuffle_options(options, correct)
    return Question(topic, prompt, options, answer_index, explanation)


def _stress_variants(word: str) -> List[str]:
    vowels = "аеёиоуыэюя"
    lower = word.lower()
    positions = [idx for idx, ch in enumerate(lower) if ch in vowels]

    variants: List[str] = []
    for pos in positions:
        chars = list(lower)
        chars[pos] = chars[pos].upper()
        variants.append("".join(chars))
    return variants


def _difficulty_from_stats(correct: int, wrong: int) -> int:
    total = correct + wrong
    if total < 5:
        return 0
    accuracy = correct / total
    if accuracy >= 0.8:
        return 2
    if accuracy >= 0.55:
        return 1
    return 0


def choose_topic(topic_stats: Dict[str, Dict[str, int]]) -> str:
    route = build_route(topic_stats)
    roll = random.random()
    if route["weak"] and roll < 0.7:
        return random.choice(route["weak"])
    if route["medium"] and roll < 0.9:
        return random.choice(route["medium"])
    if route["strong"]:
        return random.choice(route["strong"])
    return random.choice(list(TOPIC_LABELS.keys()))


def build_route(topic_stats: Dict[str, Dict[str, int]]) -> Dict[str, List[str]]:
    scored = []
    for topic in TOPIC_LABELS:
        stats = topic_stats.get(topic, {"correct": 0, "wrong": 0})
        solved = stats["correct"] + stats["wrong"]
        error_rate = (stats["wrong"] / solved) if solved else 0.5
        confidence_penalty = 1 / (solved + 1)
        scored.append((error_rate + confidence_penalty, topic))

    scored.sort(reverse=True)
    ordered = [topic for _, topic in scored]
    return {
        "weak": ordered[:2],
        "medium": ordered[2:4],
        "strong": ordered[4:],
    }


def route_text(topic_stats: Dict[str, Dict[str, int]]) -> str:
    route = build_route(topic_stats)
    weak = ", ".join(TOPIC_LABELS[t] for t in route["weak"]) or "—"
    medium = ", ".join(TOPIC_LABELS[t] for t in route["medium"]) or "—"
    strong = ", ".join(TOPIC_LABELS[t] for t in route["strong"]) or "—"
    return (
        "Ваш маршрут подготовки:\n"
        f"- Слабые темы (70% задач): {weak}\n"
        f"- Средние темы (20% задач): {medium}\n"
        f"- Сильные темы (10% задач): {strong}"
    )


def make_question(topic: str, topic_stats: Dict[str, Dict[str, int]]) -> Question:
    stats = topic_stats.get(topic, {"correct": 0, "wrong": 0})
    difficulty = _difficulty_from_stats(stats["correct"], stats["wrong"])

    if topic == "n_nn":
        return _gen_n_nn(difficulty)
    if topic == "punct":
        return _gen_punct(difficulty)
    if topic == "stress":
        return _gen_stress(difficulty)
    if topic == "not_with_word":
        return _gen_not_with_word(difficulty)
    if topic == "paronyms":
        return _gen_paronyms(difficulty)

    raise ValueError(f"Unknown topic: {topic}")


def _gen_n_nn(difficulty: int) -> Question:
    words_simple = [
        ("карти..ый", "нн", "В прилагательном 'картинный' пишется НН (суффикс -инн-)."),
        ("дли..ый", "нн", "В слове 'длинный' пишется НН."),
        ("ветре..ый", "н", "Исключение: 'ветреный' пишется с одной Н."),
        ("деревя..ый", "нн", "'Деревянный' пишется с НН как исключение."),
    ]
    words_hard = [
        ("организова..ый", "нн", "Страдательное причастие прошедшего времени обычно пишется с НН."),
        ("краше..ый", "н", "Отглагольное прилагательное без зависимых слов: одна Н."),
        ("реше..ый вопрос", "н", "Краткое причастие: одна Н."),
        ("соверше..о верно", "н", "Краткая форма наречия от прилагательного: одна Н."),
    ]
    source = words_simple if difficulty == 0 else words_simple + words_hard
    word, correct, explanation = random.choice(source)
    prompt = f"Выберите вариант, который правильно заполняет пропуск: {word}"
    distractors = ["н" if correct == "нн" else "нн"]
    return _build_question("n_nn", prompt, correct, distractors, explanation)


def _gen_punct(difficulty: int) -> Question:
    tasks = [
        (
            "Когда наступил вечер мы вышли на набережную.",
            "Когда наступил вечер, мы вышли на набережную.",
            "Запятая разделяет придаточное и главное предложения.",
        ),
        (
            "Он улыбаясь смотрел в окно.",
            "Он, улыбаясь, смотрел в окно.",
            "Деепричастный оборот выделяется запятыми.",
        ),
        (
            "Я знаю что ты вернёшься.",
            "Я знаю, что ты вернёшься.",
            "Перед 'что' в СПП нужна запятая.",
        ),
        (
            "Солнце село и стало прохладно.",
            "Солнце село, и стало прохладно.",
            "Между частями сложносочинённого предложения нужна запятая.",
        ),
    ]
    if difficulty == 2:
        tasks.append(
            (
                "Он сказал что если будет время то зайдёт вечером.",
                "Он сказал, что, если будет время, то зайдёт вечером.",
                "Сложноподчинённая конструкция с вложенным придаточным.",
            )
        )

    raw, correct_sentence, explanation = random.choice(tasks)
    prompt = "Выберите вариант с правильной пунктуацией:\n" + raw
    distractors = [
        raw,
        correct_sentence.replace(",", ""),
        correct_sentence.replace(" то ", " "),
        correct_sentence.replace(", и", " и"),
    ]
    return _build_question("punct", prompt, correct_sentence, distractors, explanation)


def _gen_stress(difficulty: int) -> Question:
    words = [
        ("звонит", "звонИт"),
        ("красивее", "красИвее"),
        ("торты", "тОрты"),
        ("диспансер", "диспансЕр"),
        ("каталог", "каталОг"),
        ("баловать", "баловАть"),
        ("жалюзи", "жалюзИ"),
    ]
    if difficulty == 0:
        words = words[:4]

    word, correct = random.choice(words)
    variants = _stress_variants(word)
    if correct not in variants:
        variants.append(correct)

    distractors = [variant for variant in variants if variant != correct]
    prompt = f"Укажите вариант с правильным ударением: {word}"
    explanation = f"Норма: {correct}."
    return _build_question("stress", prompt, correct, distractors, explanation)


def _gen_not_with_word(difficulty: int) -> Question:
    tasks = [
        ("(не)правда", "неправда", "Можно заменить синонимом 'ложь' => слитно."),
        ("вовсе (не)интересный", "вовсе не интересный", "С усилителем отрицания 'вовсе' пишется раздельно."),
        ("(не)дочитать книгу", "недочитать книгу", "Приставка НЕДО- со значением недостаточности => слитно."),
        ("(не)смотря на дождь", "несмотря на дождь", "Производный предлог пишется слитно."),
    ]
    if difficulty > 0:
        tasks.extend(
            [
                ("ничем (не)заменимая вещь", "ничем не заменимая вещь", "Есть зависимое слово => раздельно."),
                ("(не)сделанное вовремя задание", "не сделанное вовремя задание", "Причастие с зависимым словом => раздельно."),
            ]
        )

    raw, correct, explanation = random.choice(tasks)
    prompt = f"Выберите правильное написание:\n{raw}"
    distractors = [
        raw.replace("(", "").replace(")", ""),
        raw.replace("(не)", "не "),
        raw.replace("(не)", "ни "),
        raw.replace("(не)", "не-"),
    ]
    return _build_question("not_with_word", prompt, correct, distractors, explanation)


def _gen_paronyms(difficulty: int) -> Question:
    tasks = [
        (
            "На собрании директор произнёс ____ речь.",
            "эффектную",
            ["эффектную", "эффективную", "эффектнуюю", "эффектовную"],
            "Эффектный = производящий впечатление; эффективный = действенный.",
        ),
        (
            "Для решения задачи нужен ____ метод.",
            "эффективный",
            ["эффективный", "эффектный", "эффективичный", "эффектовый"],
            "Эффективный означает результативный.",
        ),
        (
            "Он получил ____ билет в театр.",
            "абонемент",
            ["абонемент", "абонент", "абанемент", "абонентт"],
            "Абонемент - документ на право пользования услугой.",
        ),
        (
            "Оператор быстро ответил каждому ____.",
            "абоненту",
            ["абоненту", "абонементу", "абонентому", "абонему"],
            "Абонент - лицо, пользующееся услугой связи.",
        ),
    ]
    if difficulty == 2:
        tasks.append(
            (
                "Нужно представить ____ данные за квартал.",
                "статистические",
                ["статистические", "статичные", "статистичные", "статические"],
                "Статистический связан со статистикой; статический - неподвижный.",
            )
        )

    prompt, correct, options, explanation = random.choice(tasks)
    distractors = [option for option in options if option != correct]
    return _build_question("paronyms", prompt, correct, distractors, explanation)


def topics_help_text() -> str:
    lines = ["Темы тренажёра:"]
    for key, label in TOPIC_LABELS.items():
        lines.append(f"- {label}: `тема {key}` или `выбрать тему {label.lower()}`")
    lines.append("- Диагностика уровня: `диагностика`")
    lines.append("- Персональный маршрут: `мой план`")
    lines.append("- Смешанный режим: `тренировка`")
    lines.append("- Подборка: `быстрый тест 10` (любое число)")
    lines.append("- Официальные ссылки: `источники`")
    return "\n".join(lines)
