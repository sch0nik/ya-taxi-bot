import asyncio
import json
import logging
import os
import re
from json import JSONDecodeError

from dotenv import load_dotenv
from selenium import webdriver
from selenium.common import WebDriverException
from selenium.webdriver.chrome.service import Service
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
from webdriver_manager.chrome import ChromeDriverManager


logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
)

load_dotenv()

TOKEN = os.environ.get('TOKEN')
if not TOKEN:
    raise ValueError('Не удалось получить тг-токен')

ChromeOptions = webdriver.ChromeOptions()
ChromeOptions.add_argument('no-sandbox')
ChromeOptions.add_argument('-start-maximized')
ChromeOptions.add_argument('-headless')
ChromeOptions.add_argument('--enable-logging')
ChromeOptions.add_argument('--v=1')
ChromeOptions.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
ChromeService = Service(ChromeDriverManager().install())

application = ApplicationBuilder().token(TOKEN).build()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=('''Локальный бот для тестов. Сейчас яндекс-доставка.'''
              '''Отправьте мне или в чат сообщение в котором только ссылка на доставку''')
    )


async def extract_info(browser):
    logs = browser.get_log('performance')
    for log in logs:
        l = json.loads(log['message'])['message']
        if l['method'] == 'Network.responseReceived':
            try:
                body = browser.execute_cdp_cmd(
                    'Network.getResponseBody',
                    {'requestId': l['params']['requestId']},
                )
                if 'summary' in body['body']:
                    body['body'] = json.loads(body['body'])
                    info = (
                            body['body'].get('performer').get('name') + '\n' +
                            body['body'].get('performer').get('vehicle_model') + '\n' +
                            body['body'].get('performer').get('vehicle_number') + '\n' +
                            body['body'].get('summary') + '\n'
                    )
                    if 'Доставлено' in body['body']['summary']:
                        return True, info
                    else:
                        return False, info
            except WebDriverException:
                continue
            except JSONDecodeError:
                continue
    return False, False


def find_id(url: str):
    _ = url.split('/')
    return _[-1] if url[-1] != '/' else _[-2]


async def processing(url: str, chat_id, message, bot):
    id_taxi = url.split('/')
    logging.info(f'Процесс такси-{id_taxi} запущен')
    browser = webdriver.Chrome(service=ChromeService, options=ChromeOptions)
    browser.get(url)
    await asyncio.sleep(5)

    while True:
        state, info = await extract_info(browser)
        logging.info(f'Такси-{id_taxi}, {state=}, {info=}')
        if not (state or info):
            break
        await bot.send_message(chat_id, info)
        if state:
            message.reply_text(info)
            break
        await asyncio.sleep(10 * 60)
        browser.refresh()
        await asyncio.sleep(5)
    browser.close()


async def start_taxi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    urls = re.findall(
        r'https?:\/\/dostavka\.yandex\.ru\/route\/\S+',
        update.message.text
    )
    logging.info(
        f'{update.effective_chat.effective_name}::{update.effective_chat.id}::{update.message.text}'
    )
    for url in urls:
        await processing(url, update.effective_chat.id, update.message, context.bot)
    # list_taxi = [processing(url, update.effective_chat.id, update.message, context.bot) for url in urls]
    # await asyncio.gather(*list_taxi)


if __name__ == '__main__':
    application.add_handler(CommandHandler('start', start))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), start_taxi))

    application.run_polling()
