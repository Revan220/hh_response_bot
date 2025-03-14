import sqlite3
import aiohttp
import asyncio
import requests
import json
from aiogram import Bot, Dispatcher, types, Router, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Загрузка конфигурации из config.json
with open("config.json", "r") as f:
    config = json.load(f)

# Токен Telegram бота
TELEGRAM_TOKEN = config["TELEGRAM_TOKEN"]

# Учетные данные для API HeadHunter
HH_ACCESS_TOKEN = config["HH_ACCESS_TOKEN"]
CLIENT_ID = config["CLIENT_ID"]
CLIENT_SECRET = config["CLIENT_SECRET"]
AUTH_CODE = config["AUTH_CODE"]
REFRESH_TOKEN = config["REFRESH_TOKEN"]

# Проверка наличия токена HH
if not HH_ACCESS_TOKEN:
    raise ValueError("Ошибка: HH_ACCESS_TOKEN не задан! Проверь config.json.")

# Функция обновления access_token через refresh_token
def refresh_access_token():
    global HH_ACCESS_TOKEN, REFRESH_TOKEN
    url = "https://hh.ru/oauth/token"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }
    response = requests.post(url, data=data)
    if response.status_code == 200:
        tokens = response.json()
        HH_ACCESS_TOKEN = tokens["access_token"]
        REFRESH_TOKEN = tokens["refresh_token"]
        
        # Обновляем config.json
        config["HH_ACCESS_TOKEN"] = HH_ACCESS_TOKEN
        config["REFRESH_TOKEN"] = REFRESH_TOKEN
        with open("config.json", "w") as f:
            json.dump(config, f, indent=4)
        
        logging.info(f"✅ Access token обновлён: {HH_ACCESS_TOKEN[:10]}...")
        asyncio.sleep(1)  # Даем время на обновление
    else:
        logging.error("❌ Ошибка обновления access token!")

# Настройка базы данных
def setup_db():
    with sqlite3.connect("jobs.db") as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vacancy_id TEXT UNIQUE,
                company_id TEXT,
                status TEXT
            )
        ''')

# Получение вакансий с API HeadHunter
async def fetch_vacancies():
    url = "https://api.hh.ru/vacancies"
    params = {"text": "Python разработчик", "area": 1, "per_page": 10}
    headers = {"Authorization": f"Bearer {HH_ACCESS_TOKEN}"}
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as response:
            if response.status == 401:
                logging.error("Ошибка 401: Токен HH устарел. Обновляем...")
                refresh_access_token()
                return await fetch_vacancies()
            elif response.status != 200:
                logging.error(f"Ошибка API HH: {response.status}")
                return []
            
            data = await response.json()
            return data.get("items", [])

# Проверка, был ли уже отправлен отклик на вакансию
def is_already_applied(vacancy_id):
    with sqlite3.connect("jobs.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM applications WHERE vacancy_id = ?", (vacancy_id,))
        result = cursor.fetchone()
    return result is not None

# Отклик на вакансию
async def apply_to_vacancy(vacancy_id):
    if is_already_applied(vacancy_id):
        return False
    
    url = "https://api.hh.ru/negotiations"
    headers = {"Authorization": f"Bearer {HH_ACCESS_TOKEN}"}
    data = {"vacancy_id": vacancy_id}
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=data) as response:
            if response.status == 401:
                logging.error("Ошибка 401: Токен HH устарел. Обновляем...")
                refresh_access_token()
                return await apply_to_vacancy(vacancy_id)
            elif response.status == 201:
                with sqlite3.connect("jobs.db") as conn:
                    cursor = conn.cursor()
                    cursor.execute("INSERT INTO applications (vacancy_id, company_id, status) VALUES (?, ?, ?)", (vacancy_id, "", "applied"))
                    conn.commit()
                return True
            else:
                logging.error(f"Ошибка при отклике на вакансию: {response.status}")
                return False

# Настройка Telegram бота
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
router = Router()

dp.include_router(router)

@router.message(Command("start"))
async def start(message: types.Message):
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(KeyboardButton("🔍 Найти вакансии"))
    await message.answer("Привет! Я бот для автоотклика на вакансии.", reply_markup=keyboard)

@router.message(F.text == "🔍 Найти вакансии")
async def search_vacancies(message: types.Message):
    vacancies = await fetch_vacancies()
    applied_count = 0
    failed_count = 0
    
    for vacancy in vacancies:
        vacancy_id = vacancy["id"]
        if await apply_to_vacancy(vacancy_id):
            applied_count += 1
        else:
            failed_count += 1  # Считаем неудачные отклики
        await asyncio.sleep(2)  # Избегаем лимитов
    
    await message.answer(f"✅ Успешно отправлено: {applied_count} \n❌ Ошибок при отправке: {failed_count}")

async def main():
    setup_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
