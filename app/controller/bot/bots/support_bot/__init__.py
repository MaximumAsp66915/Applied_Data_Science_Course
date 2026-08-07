"""
SUT Music support bot.

A plain Telegram Bot API bot (aiogram, long polling) that gives people a
lightweight, chat-based front door to SUT Music without needing to open the
Mini App:

    * free-text search over tracks & artists (never users)
    * a button that opens the real Mini App (https://t.me/SUTMusic_Bot?startapp)
    * a report/bug menu that forwards straight to the project admin
    * Terms & Privacy, Contributors and About pages

It is deliberately independent from the bot in ``controller/bot/bots/
SUT_Music_bot.py`` (the Telethon userbot that scrapes/ingests tracks) and
from the database layer entirely -- see ``api_client.py``. It only ever
talks to the already-running FastAPI webapp over HTTP, the same way any
other client of that API would. That keeps it safe to develop, deploy and
restart on its own, independent of the bot/webapp/frontend stack in
``deploy/start.sh``.
"""
