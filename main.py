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

ChromeOptions = webdriver.ChromeOptions()
ChromeOptions.add_argument('no-sandbox')
ChromeOptions.add_argument('-start-maximized')
ChromeOptions.add_argument('-headless')
ChromeOptions.add_argument('--enable-logging')
ChromeOptions.add_argument('--v=1')
ChromeOptions.set_capability('goog:loggingPrefs', {'performance': 'ALL'})

ChromeService = Service(ChromeDriverManager().install())

TOKEN = os.environ.get('TOKEN')
if not TOKEN:
    raise ValueError('Не удалось получить тг-токен')

application = ApplicationBuilder().token(TOKEN).build()

LIST_TAXI = []


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text='''Локальный бот для тестов. Сейчас яндекс-доставка.\
         Отправьте мне или в чат сообщение в котором только ссылка на доставку'''
    )


async def extract_from_dostavka(browser):
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


async def extract_from_go_yandex(browser):
    page = browser.page_source
    if 'Поездка завершена' in page:
        return True, 'Поездка завершена'
    if 'Доставлено' in page:
        return True, 'Доставлено'

    logs = browser.get_log('performance')
    for log in logs[::-1]:
        l = json.loads(log['message'])['message']
        if l['method'] == 'Network.responseReceived':
            logging.info('Есть метод')
            try:
                body = browser.execute_cdp_cmd(
                    'Network.getResponseBody',
                    {'requestId': l['params']['requestId']},
                )
                if 'dostavka' in browser.current_url:
                    if 'summary' in body['body']:
                        body = json.loads(body['body'])
                        info = (
                            body.get('performer').get('name') + '\n' +
                            body.get('performer').get('vehicle_number') + '\n' +
                            body.get('performer').get('vehicle_model') + '\n' +
                            body.get('summary') + '\n'
                        )
                        # if 'Доставлено' in body['body']['summary']:
                        #     return True, info
                        # else:
                        #     return False, info
                        return False, info
                if 'go.yandex' in browser.current_url:
                    if 'distance_left' in body['body'] and 'time_left' in body['body']:
                        body = json.loads(body['body'])
                        info = (
                            body.get('performer').get('name') + '\n' +
                            body.get('performer').get('vehicle_number') + '\n' +
                            body.get('performer').get('vehicle_model') + '\n' +
                            body.get('summary') + '\n'
                        )
                        return False, info

            except WebDriverException:
                continue
            except JSONDecodeError:
                continue
    return False, False


async def processing(url: str, chat_id, message, bot):
    logging.info('такси запущено')
    browser = webdriver.Chrome(service=ChromeService, options=ChromeOptions)
    browser.get(url)
    await asyncio.sleep(5)

    extract = None
    if 'dostavka' in url:
        extract = extract_from_dostavka
    if 'go.yandex' in url:
        extract =  extract_from_go_yandex

    while True:
        state, info = await extract(browser)

        if not (state or info):
            break

        if state:
            logging.info(f'Такси завершено. Отправка результата в чат')
            await message.reply_text(info)
            break

        logging.info(f'Такси в пути. Отправка результата в чат')
        await bot.send_message(chat_id, info)

        await asyncio.sleep(10 * 60)
        browser.refresh()
        await asyncio.sleep(5)

    browser.close()


async def start_taxi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info(
        f'{update.effective_chat.effective_name}::{update.effective_chat.id}::{update.message.text}'
    )
    urls = re.findall(
        r'https?:\/\/dostavka\.yandex\.ru\/route\/\S+',
        update.message.text
    )
    for url in urls:
        await processing(url, update.effective_chat.id, update.message, context.bot)

    urls = re.findall(
        r'https?:\/\/go\.yandex\/route\/\S+',
        update.message.text
    )
    for url in urls:
        await processing(url, update.effective_chat.id, update.message, context.bot)


if __name__ == '__main__':
    application.add_handler(CommandHandler('start', start))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), start_taxi))

    application.run_polling()
