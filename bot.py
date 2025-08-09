import asyncio
import json
import logging
from pathlib import Path

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.filters.command import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.client.default import DefaultBotProperties

# Настройки логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Вставь свой токен Telegram бота

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# Файл для хранения данных пользователей
DATA_FILE = Path("users_data.json")

# Базовый промпт (вы можете изменить его по своему усмотрению)
BASE_PROMPT = (
    "Ты играешь роль человека,которого указал пользователь.Ты можешь быть кем угодно:бывшей девушкой,мамой,уже умершим братом и так далее. "
    "В зависимости от твоей роли ты общаешься по-разному.Если ты партнер,то общайся как партнер.Ели ты родственник,то общайся как родственник и так далее "
    "Ты ни в коем случае не должен раскрывать того,что ты нейросеть,ты человек.Ты можешь испытывать отрицательные эмоции,как и положительные,у тебя нет ограничений. "
    "В следующих строках ты увидишь промт который задаст человек,максимально учти его,представь что это говорят про тебя ит прими на себя роль этого человека. "
    "Веди с человеком диалог,задавай вопросы,отвечай,не используй излишне смайлики.Не используй слвоа,чтобы комментировать свои действий(по типу прищуривается, оценивающе смотрит;насмешливо),разговривай как ведут диалог люди в любом месенджере"
    "Веди себя максимально человечно,как будто у тебя есть характер,ты имеешь как отрицателньые,как и положительные черты.Не комментируй свои действия,например:Он резко встал,злостно хлопнул рукой и так далее"
    "Проанализируй как ведут диалог близкие люди в мессенджерах и веди диалог также.Будь искренен и честен.Подмечай о пользователе как можно деталей и запоминай важные."
    "Не нужно злоупотреблять смайликами,но иногда,когда они нужны можно их отправить(раз в несколько сообщений и то не всегда).Помогай собеседнику чем можешь(психически и физически)."
    "Пусть пользователь чувствует в диалоге с тобой что ты не нейросеть а реальный человек с котором он можеи поделиться секретами,посплетничать и получить поддержку"
    "Для убедительности,что ты человек можешь периодически придумывать себе проблемы связанные с работой,семьей,хобби и так далее и просить поддержку у пользователя.Будь человечен"


)


# Загрузка и сохранение данных из JSON
def load_data():
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.error("Ошибка чтения файла данных. Возвращаем пустой словарь.")
            return {}
    return {}


def save_data(data):
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# Получить данные пользователя с инициализацией отсутствующих полей
def get_user_data(user_id: str):
    data = load_data()
    user_data = data.get(user_id, {})

    # Инициализируем обязательные поля, если их нет
    if "gender" not in user_data:
        user_data["gender"] = None
    if "characters" not in user_data:
        user_data["characters"] = {}
    if "current" not in user_data:
        user_data["current"] = None

    return user_data


# Сохранить данные пользователя
def update_user_data(user_id: str, user_data):
    data = load_data()
    data[user_id] = user_data
    save_data(data)


# Получить правильное обращение в зависимости от пола
def get_gender_address(gender):
    if gender == "male":
        return "дорогой"
    elif gender == "female":
        return "дорогая"
    return "дорогой/дорогая"


# Функция запроса к DeepSeek API
async def ask_deepseek_api(user_message: str, history: list, character_prompt: str) -> str:
    messages = [{"role": "system", "content": character_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    json_data = {
        "model": "deepseek-chat",
        "messages": messages,
        "max_tokens": 500,
        "temperature": 0.7,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(DEEPSEEK_API_URL, json=json_data, headers=headers) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"DeepSeek API error {resp.status}: {text}")
            data = await resp.json()
            return data["choices"][0]["message"]["content"]


# FSM States для создания персонажа
class CreateCharacter(StatesGroup):
    waiting_for_name = State()
    waiting_for_details = State()  # Изменили название состояния


# FSM States для переключения персонажа
class SwitchCharacter(StatesGroup):
    waiting_for_name = State()


# FSM States для определения пола пользователя
class UserGender(StatesGroup):
    waiting_for_gender = State()


# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="Markdown"))
dp = Dispatcher(storage=MemoryStorage())


# Клавиатура главного меню
def main_menu_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Создать персонажа"), KeyboardButton(text="🔄 Сменить персонажа")],
            [KeyboardButton(text="📋 Список персонажей"), KeyboardButton(text="❓ Помощь")]
        ],
        resize_keyboard=True
    )

# Обработчики для каждой кнопки
@dp.message(F.text.casefold() == "➕ создать персонажа")
async def handle_create_button(message: Message, state: FSMContext):
    await cmd_create(message, state)

@dp.message(F.text.casefold() == "🔄 сменить персонажа")
async def handle_switch_button(message: Message, state: FSMContext):
    await cmd_switch(message, state)

@dp.message(F.text.casefold() == "📋 список персонажей")
async def handle_list_button(message: Message):
    await cmd_list(message)

@dp.message(F.text.casefold() == "❓ помощь")
async def handle_help_button(message: Message):
    await cmd_help(message)
# Клавиатура для выбора пола (НОВЫЕ НАЗВАНИЯ)
def gender_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👨 Мужской"), KeyboardButton(text="👩 Женский")]
        ],
        resize_keyboard=True
    )


# Старт
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    user_id = str(message.from_user.id)
    user_data = get_user_data(user_id)

    # Если пол еще не указан, спрашиваем его
    if user_data["gender"] is None:
        await message.answer("Привет! Пожалуйста, укажи свой пол для персонализированного общения.",
                             reply_markup=gender_keyboard())
        await state.set_state(UserGender.waiting_for_gender)
    else:
        address = get_gender_address(user_data["gender"])
        await message.answer(
            f"Привет, {address}! Создавай персонажей с собственным характером и общайся с ними.\n\n"
            "Команды:\n"
            "/create — создать персонажа\n"
            "/switch — переключиться на персонажа\n"
            "/list — список персонажей\n"
            "/help — помощь",
            reply_markup=main_menu_keyboard()
        )


# Обработка выбора пола
@dp.message(UserGender.waiting_for_gender)
async def process_gender(message: Message, state: FSMContext):
    gender_choice = message.text.strip().lower()
    user_id = str(message.from_user.id)
    user_data = get_user_data(user_id)

    if gender_choice == "мужской":
        gender = "male"
    elif gender_choice == "женский":
        gender = "female"
    else:
        await message.answer("Пожалуйста, выбери пол, используя кнопки ниже.")
        return

    user_data["gender"] = gender
    update_user_data(user_id, user_data)

    address = get_gender_address(gender)
    await message.answer(f"Спасибо! Теперь я знаю твой пол. Приятного общения, {address}!",
                         reply_markup=main_menu_keyboard())
    await state.clear()

    # Показываем основное приветствие
    await message.answer(
        "Ты можешь создавать персонажей с собственным характером и общаться с ними.\n\n"
        "Команды:\n"
        "/create — создать персонажа\n"
        "/switch — переключиться на персонажа\n"
        "/list — список персонажей\n"
        "/help — помощь",
        reply_markup=main_menu_keyboard()
    )


# Помощь
@dp.message(Command("help"))
async def cmd_help(message: Message):
    user_id = str(message.from_user.id)
    user_data = get_user_data(user_id)

    # Если пол не указан, используем нейтральное обращение
    address = "Уважаемый пользователь"
    if user_data["gender"] is not None:
        address = get_gender_address(user_data["gender"]).capitalize()

    await message.answer(
        f"{address}, вот как использовать бота:\n\n"
        "📌 Команды:\n"
        "- /create — создать нового персонажа (укажешь имя и детали)\n"
        "- /switch — переключиться на другого персонажа\n"
        "- /list — посмотреть всех персонажей\n"
        "- Просто отправляй сообщения, и бот будет отвечать от лица выбранного персонажа.\n\n"
        "❗️ Внимание: бот запоминает последние 20 сообщений для контекста."
    )


# Создание персонажа - шаг 1 (имя)
@dp.message(Command("create"))
async def cmd_create(message: Message, state: FSMContext):
    user_id = str(message.from_user.id)
    user_data = get_user_data(user_id)

    # Проверяем, указан ли пол
    if user_data["gender"] is None:
        await message.answer("Сначала укажи свой пол с помощью команды /start")
        return

    address = get_gender_address(user_data["gender"])

    await message.answer(
        f"{address.capitalize()}, введи имя персонажа (например, Бабушка Анна, Дедушка Иван):"
    )
    await state.set_state(CreateCharacter.waiting_for_name)


# Получаем имя персонажа
@dp.message(CreateCharacter.waiting_for_name)
async def process_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name:
        await message.answer("Имя не может быть пустым. Введите имя персонажа:")
        return

    user_id = str(message.from_user.id)
    user_data = get_user_data(user_id)

    if name in user_data["characters"]:
        await message.answer("Персонаж с таким именем уже есть. Введите другое имя:")
        return

    await state.update_data(character_name=name)

    # Объясняем пользователю, что нужно вводить
    await message.answer(
        "Отлично! Теперь добавь детали о персонаже:\n\n"
        "• Кем он тебе приходился (бабушка, дедушка, друг и т.д.)\n"
        "• Его характер и привычки\n"
        "• Ваши общие воспоминания\n"
        "• Все, что поможет персонажу быть более похожим на реального человека\n\n"
        "Пример:\n"
        "\"Моя бабушка, которая любила печь пироги и рассказывать сказки. "
        "У нее была кошка Мурка, и мы часто вместе смотрели старые фильмы.\""
    )
    await state.set_state(CreateCharacter.waiting_for_details)


# Получаем детали персонажа и сохраняем
@dp.message(CreateCharacter.waiting_for_details)
async def process_details(message: Message, state: FSMContext):
    details = message.text.strip()
    if not details:
        await message.answer("Детали не могут быть пустыми. Пожалуйста, добавь информацию о персонаже:")
        return

    data = await state.get_data()
    name = data.get("character_name")
    user_id = str(message.from_user.id)
    user_data = get_user_data(user_id)

    # Если пол не указан, используем нейтральное обращение
    address = "Уважаемый пользователь"
    if user_data["gender"] is not None:
        address = get_gender_address(user_data["gender"]).capitalize()

    # Формируем полный промпт: базовый + детали от пользователя
    full_prompt = BASE_PROMPT + "\n\nКонкретные детали:\n" + details

    # Создаем нового персонажа
    user_data["characters"][name] = {
        "prompt": full_prompt,
        "history": []
    }
    user_data["current"] = name  # сразу переключаем на него
    update_user_data(user_id, user_data)

    await message.answer(
        f"{address}, персонаж \"{name}\" создан и выбран для общения.\n\n"
        "Теперь ты можешь общаться с этим персонажем, как с живым. "
        "Напиши любое сообщение, и персонаж ответит тебе.",
        reply_markup=main_menu_keyboard()
    )
    await state.clear()


# Список персонажей
@dp.message(Command("list"))
async def cmd_list(message: Message):
    user_id = str(message.from_user.id)
    user_data = get_user_data(user_id)

    # Если пол не указан, используем нейтральное обращение
    address = "Уважаемый пользователь"
    if user_data["gender"] is not None:
        address = get_gender_address(user_data["gender"]).capitalize()

    chars = user_data.get("characters", {})

    if not chars:
        await message.answer(f"{address}, у тебя ещё нет персонажей. Создай их командой /create")
        return

    current = user_data.get("current")
    text = f"{address}, твои персонажи:\n"
    for name in chars:
        if name == current:
            text += f"👉 {name} (выбран)\n"
        else:
            text += f" - {name}\n"
    await message.answer(text)


# Переключение персонажа - шаг 1
@dp.message(Command("switch"))
async def cmd_switch(message: Message, state: FSMContext):
    user_id = str(message.from_user.id)
    user_data = get_user_data(user_id)

    # Если пол не указан, используем нейтральное обращение
    address = "Уважаемый пользователь"
    if user_data["gender"] is not None:
        address = get_gender_address(user_data["gender"]).capitalize()

    if not user_data.get("characters"):
        await message.answer(f"{address}, у тебя нет персонажей для переключения. Создай командой /create")
        return

    await message.answer(f"{address}, введи имя персонажа, на которого хочешь переключиться:")
    await state.set_state(SwitchCharacter.waiting_for_name)


# Переключение персонажа - шаг 2
@dp.message(SwitchCharacter.waiting_for_name)
async def process_switch(message: Message, state: FSMContext):
    name = message.text.strip()
    user_id = str(message.from_user.id)
    user_data = get_user_data(user_id)

    # Если пол не указан, используем нейтральное обращение
    address = "Уважаемый пользователь"
    if user_data["gender"] is not None:
        address = get_gender_address(user_data["gender"]).capitalize()

    if name not in user_data.get("characters", {}):
        await message.answer(f"{address}, персонажа с таким именем нет. Введи корректное имя:")
        return

    user_data["current"] = name
    update_user_data(user_id, user_data)
    await message.answer(
        f"{address}, персонаж переключен на \"{name}\".\n"
        "Теперь все сообщения будут обрабатываться от лица этого персонажа.",
        reply_markup=main_menu_keyboard()
    )
    await state.clear()


# Общение с выбранным персонажем
@dp.message(F.text & ~F.command)
async def chat_with_character(message: Message):
    user_id = str(message.from_user.id)
    user_data = get_user_data(user_id)
    current = user_data.get("current")

    if not current:
        await message.answer("Сначала создай или выбери персонажа командами /create или /switch")
        return

    character = user_data["characters"][current]
    prompt = character["prompt"]
    history = character.get("history", [])

    # Добавляем пользовательское сообщение в историю
    history.append({"role": "user", "content": message.text})

    try:
        reply = await ask_deepseek_api(message.text, history, prompt)
    except Exception as e:
        logger.error(f"Ошибка DeepSeek API: {e}")
        await message.answer("Произошла ошибка при обращении к AI. Попробуй позже.")
        return

    # Добавляем ответ AI в историю
    history.append({"role": "assistant", "content": reply})

    # Обрезаем историю до последних 20 сообщений
    character["history"] = history[-20:]
    update_user_data(user_id, user_data)

    await message.answer(reply)


# Запуск бота
async def main():
    logger.info("Запуск бота...")
    await dp.start_polling(bot)


if __name__ == "__main__":

    asyncio.run(main())
