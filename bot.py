"""
VIBE MIX FreePick 5x5: очередь -> готовность -> капитаны -> пики игроков -> вето карт -> запуск матча на CS2 (MatchZy).
После драфта бот САМ создаёт войсы Team 1 / Team 2 и перекидывает туда игроков (после матча войсы удаляются).
Авто-старт матча: как только все игроки зашли на сервер, матч стартует сам; иначе после разминки (4 мин).
Если во время драфта все игроки вышли из войса очереди, драфт отменяется и очередь сбрасывается.
При Steam-верификации бот определяет FACEIT-уровень игрока и выдаёт роль «FACEIT LVL n».
Результат матча: табло (K / D / K/D каждого игрока) на фоне картинки карты + ELO (+30 / -20).

v60: - Как у KZLP: капитаны, пики игроков и вето карт идут в ОДНОМ сообщении (панель очереди), оно обновляется
       на каждом шаге (таймер, «Забанено / Осталось», красные кнопки карт).
     - После вето: «Создаю каналы команд и запускаю сервер...», игроки уходят в войсы команд,
       открывается отдельный чат матча, в котором ТОЛЬКО карточка с connect. Панель возвращается в обычный вид.
v59: - Кнопка «Отмена игры 0/2» под карточкой матча: нужно CANCEL_VOTES голосов игроков (админ отменяет сразу).
       Отмена и /match stop сразу кикают всех игроков с CS2-сервера, без результата и без ELO.
     - Сброс матча быстрее: сообщения, войсы и перемещение игроков обрабатываются параллельно.
v58: - Демо и события: после загрузки матча бот пишет в лог ответ сервера на каждую команду matchzy_*;
       если сервер не знает эти команды, в чат матча приходит предупреждение.
     - /demo/<id> ищет файл на диске и объясняет причину, если демо нет.
     - Бот раз в 4 минуты открывает свой адрес (Render не засыпает).
     - /fp_diag: доступность бота снаружи, число демо на диске, настройки MatchZy через css_cvar (токен скрыт).
     - RCON_PASSWORD в коде больше нет (задаётся только в Render -> Environment).
v57: - Под результатом матча вместо кнопки «Скачать демку» теперь кнопка «vibeproject.kz» (ссылка на SITE_URL).
       Ссылка «Скачать демку» в тексте результата остаётся.
v56: - В результате матча: MVP «ник — K/D/A | ADR | HS%», ELO каждого игрока (стало и изменение, +30 / -20),
       ссылка «Скачать демку» в тексте (кнопка под сообщением тоже остаётся).
     - Плашка сайта (vibeproject.kz) в правом верхнем углу картинки-табло и ссылка на сайт в заголовке результата.
       Адрес сайта: SITE_URL в Render -> Environment (пусто = без плашки).
v55: - В канал результатов уходит табло + короткий текст: только «Победитель (счёт)» и «MVP — ник».
       RESULT_TEXT включён по умолчанию (RESULT_TEXT=0 вернёт только картинку).
v54: - На смене сторон (перерыв между половинами) включается all talk на HALFTIME_TALK_SECONDS (15 сек), потом выключается.
     - Как на FACEIT: игрок вышел с сервера -> авто-пауза, по центру экрана у всех «Игрок X вышел из игры / Техническая пауза 1:30»
       с обратным отсчётом; на время паузы включается all talk (sv_alltalk), после паузы настройки возвращаются.
       Длина паузы: BREAK_SECONDS (по умолчанию 90 = 1:30). Выключить all talk: PAUSE_ALLTALK=0.
v53: - В канал результатов уходит только картинка-табло: без кнопки «Скачать демку» и без текста под картинкой.
v52: - Как на FACEIT: 24 раунда (MR12), смена сторон на перерыве между половинами, овертайм (настройки идут в конфиге матча).
     - После окончания матча бот через 15 сек автоматически кикает всех игроков с CS2-сервера.
     - MVP: если у сервера нет статистики (все нули), в центре табло показывается игрок победившей команды.
     - Тест-режим: карта заканчивается сама через TEST_MAXROUNDS раундов (по умолчанию 4), чтобы пришли map_result и демо.
v51: - Токен событий/демо принимается из заголовка Authorization (с Bearer и без) ИЛИ из ?t= в адресе.
v50: - GOTV включается автоматически: перед загрузкой матча бот ставит tv_enable 1 и перезагружает карту (changelevel).
v49: - В центре табло: аватар и ник MVP (игрок с наибольшим числом убийств), надпись «MVP» вместо «ИТОГ».
v48: - K/D на табло считается надёжно: убийства и смерти берутся из событий player_death.
v47: на табло результата у каждого игрока видно убийства (K), смерти (D) и K/D.
v46: команды /match stop, /match stat, /profile, /mute, /unmute, /clan (create, accept, info, invite,
     kick, leave, list, menu), /clearrole. Статистика матчей, кланы и ELO входят в бэкап.
"""
print("▶ bot.py v60 загружается...", flush=True)
import asyncio
import threading
from collections import deque
import io
import json
import logging
import os
import random
import re
import secrets
import sqlite3
import time
from datetime import timedelta
from urllib.parse import urlencode

import aiohttp
import discord
from aiohttp import web
from discord import app_commands
from discord.ext import commands
from rcon.source import Client as Rcon

try:  # локально читаем .env, на хостинге переменные задаются в панели
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("freepick")

# ----------------------------- НАСТРОЙКИ -----------------------------
# CS2-сервер. RCON_PASSWORD лучше задать в Render -> Environment
SERVER_IP = os.getenv("SERVER_IP", "45.86.81.37").strip()
SERVER_PORT = int(os.getenv("SERVER_PORT", "55031"))
RCON_PASSWORD = os.getenv("RCON_PASSWORD", "ArniAlash22062008Nurlan")
SERVER_PASSWORD = os.getenv("SERVER_PASSWORD", "")

# Веб-сервер бота (его должен видеть CS2-сервер)
WEB_PORT = int(os.getenv("PORT") or os.getenv("WEB_PORT", "55031"))
WEB_BASE_URL = os.getenv("WEB_BASE_URL", "https://bot-vibe-mix-1.onrender.com").rstrip("/")
EVENT_TOKEN = os.getenv("EVENT_TOKEN") or secrets.token_urlsafe(24)  # секрет для событий MatchZy (если не задан, генерируется сам)

# ID твоего Discord-сервера: команды появятся мгновенно (необязательно)
GUILD_ID = int(os.getenv("GUILD_ID", "1548371779523837952"))

# Голосовой канал очереди: зашёл в него = встал в очередь, вышел = покинул (0 = только кнопки)
QUEUE_VC = int(os.getenv("QUEUE_VC_ID", "1565440992574705734"))

# Роль, которая выдаётся после Steam-верификации (0 = не выдавать)
VERIFIED_ROLE = int(os.getenv("VERIFIED_ROLE_ID", "1565117832251965653"))

# FACEIT: ключ с https://developers.faceit.com (Server side API key). Пусто = FACEIT-роли выключены.
FACEIT_API_KEY = os.getenv("FACEIT_API_KEY", "dc718e03-bd86-4430-b54d-f7919c3aaf50").strip()
# 1 = стартовый ELO в FreePick берётся из FACEIT ELO (только для тех, у кого ещё нет рейтинга)
FACEIT_START_ELO = os.getenv("FACEIT_START_ELO", "1") == "1"

TEST_MODE = os.getenv("TEST_MODE", "0") == "1"  # 1 = тест: хватает одного игрока, без драфта
TEAM_SIZE = 1 if TEST_MODE else 5
NEED = 1 if TEST_MODE else TEAM_SIZE * 2
PICK_TIMEOUT = 30            # секунд на пик/бан, потом выбор случайный
CAPTAIN_TIMEOUT = 30         # секунд на выбор капитанов (кто не вызвался, назначается случайно)
READY_TIMEOUT = int(os.getenv("READY_TIMEOUT", "60"))   # секунд на кнопку «Готов»
MATCH_MAX_SECONDS = 600 if TEST_MODE else 2 * 3600  # автосброс, если series_end не пришёл
BREAK_SECONDS = int(os.getenv("BREAK_SECONDS", "90"))  # техпауза как на FACEIT: 1:30, потом матч продолжается
HALFTIME_ALLTALK = os.getenv("HALFTIME_ALLTALK", "1") == "1"   # 1 = при смене сторон (CT <-> T) включать all talk
HALFTIME_TALK_SECONDS = int(os.getenv("HALFTIME_TALK_SECONDS", "15"))  # сколько секунд all talk работает на смене сторон
PAUSE_ALLTALK = os.getenv("PAUSE_ALLTALK", "1") == "1"   # 1 = на время паузы включать all talk (общий голосовой/текстовый чат)

# Формат матча как на FACEIT: 24 раунда (MR12), смена сторон на перерыве, овертайм
CANCEL_VOTES = int(os.getenv("CANCEL_VOTES", "2"))  # сколько игроков должны нажать «Отмена игры»
MAX_ROUNDS = int(os.getenv("MAX_ROUNDS", "24"))
TEST_MAXROUNDS = int(os.getenv("TEST_MAXROUNDS", "4"))  # в тест-режиме карта заканчивается сама через столько раундов
KICK_AFTER_MATCH = os.getenv("KICK_AFTER_MATCH", "1") == "1"   # 0 = не кикать игроков после матча
KICK_DELAY = int(os.getenv("KICK_DELAY", "15"))                # сколько секунд после конца матча ждём перед киком

# Автостарт матча: все зашли на сервер -> через AUTO_START_DELAY сек матч стартует сам
AUTO_START = os.getenv("AUTO_START", "1") == "1"            # 0 = выключить автостарт
AUTO_START_DELAY = 15  # когда все зашли на сервер: разминка 15 сек, потом матч стартует сам
WARMUP_SECONDS = int(os.getenv("WARMUP_SECONDS", "240"))     # разминка 4 минуты, потом матч стартует принудительно

# Канал для результатов матчей (0 = бот сам найдёт канал, в названии которого есть "результаты")
RESULTS_CHANNEL = int(os.getenv("RESULTS_CHANNEL_ID", "1565444339084038314"))

# В результате матча: RESULT_TEXT=1 (по умолчанию) = под картинкой текст (счёт, MVP, ELO, демо); 0 = только картинка.
DEMO_BUTTON = os.getenv("DEMO_BUTTON", "1") == "1"
RESULT_TEXT = os.getenv("RESULT_TEXT", "1") == "1"

# Сайт: плашка в правом верхнем углу картинки результата, ссылка в заголовке и кнопка под результатом (пусто = выключено)
SITE_URL = os.getenv("SITE_URL", "").strip()

# Бэкап привязок: приватный канал для админов, куда бот кладёт файл с привязками (0 = выключено).
BACKUP_CHANNEL = int(os.getenv("BACKUP_CHANNEL_ID", "1565489828706000948"))
# Если подключён Render Disk, укажи DB_PATH=/data/freepick.db
DB_PATH = os.getenv("DB_PATH", "freepick.db")

# Папка для демо матчей (на Render без диска файлы стираются при деплое; с диском: DEMO_DIR=/data/demos)
DEMO_DIR = os.getenv("DEMO_DIR", "demos")

# Картинки карт для фона табло. Свою картинку можно положить в папку maps/ (de_dust2.png / .jpg) — она в приоритете.
MAP_DIR = os.getenv("MAP_DIR", "maps")
MAP_IMAGE_URLS = [u.strip() for u in os.getenv("MAP_IMAGE_URLS", "").split("|") if u.strip()] or [
    "https://raw.githubusercontent.com/ghostcap-gaming/cs2-map-images/main/cs2/{map}.png",
    "https://raw.githubusercontent.com/DigitalFriends/cs2-map-images/main/cs2/{map}.png",
    "https://raw.githubusercontent.com/MurkyYT/cs2-map-icons/main/images/thumbs/{map}_1_png.png",
]

MAPS = ["de_anubis", "de_mirage", "de_inferno", "de_nuke",
        "de_ancient", "de_dust2", "de_overpass", "de_cache"]

# ----------------------------- БАЗА ДАННЫХ ---------------------------
db = sqlite3.connect(DB_PATH)
db.execute("CREATE TABLE IF NOT EXISTS links ("
           "discord_id INTEGER PRIMARY KEY, steamid64 TEXT NOT NULL UNIQUE)")
db.execute("CREATE TABLE IF NOT EXISTS bans ("
           "discord_id INTEGER PRIMARY KEY, reason TEXT)")
db.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT)")
try:  # срок бана (0 = навсегда); для старых баз добавляем колонку
    db.execute("ALTER TABLE bans ADD COLUMN expires INTEGER NOT NULL DEFAULT 0")
except sqlite3.OperationalError:
    pass
db.execute("CREATE TABLE IF NOT EXISTS ban_log ("
           "id INTEGER PRIMARY KEY AUTOINCREMENT, discord_id INTEGER, steamid64 TEXT, name TEXT, avatar TEXT, "
           "reason TEXT, admin_id INTEGER, admin_name TEXT, created INTEGER, "
           "expires INTEGER NOT NULL DEFAULT 0, unbanned_at INTEGER, unban_reason TEXT, unban_by TEXT)")
db.execute("CREATE TABLE IF NOT EXISTS elo ("
           "discord_id INTEGER PRIMARY KEY, elo INTEGER NOT NULL DEFAULT 1000, "
           "wins INTEGER NOT NULL DEFAULT 0, losses INTEGER NOT NULL DEFAULT 0)")
db.commit()

ELO_START = 1000   # стартовый рейтинг
ELO_WIN = 30       # +30 за победу
ELO_LOSS = 20      # -20 за поражение
ELO_MIN = 100      # ниже этого рейтинг не падает


def get_stats(discord_id: int):
    row = db.execute("SELECT elo, wins, losses FROM elo WHERE discord_id=?", (discord_id,)).fetchone()
    return row if row else (ELO_START, 0, 0)


def get_elo(discord_id: int) -> int:
    return get_stats(discord_id)[0]


def get_steam(discord_id: int):
    row = db.execute("SELECT steamid64 FROM links WHERE discord_id=?", (discord_id,)).fetchone()
    return row[0] if row else None


def is_banned(discord_id: int) -> bool:
    row = db.execute("SELECT expires FROM bans WHERE discord_id=?", (discord_id,)).fetchone()
    return bool(row) and (row[0] == 0 or row[0] > time.time())


def kv_set(key: str, value):
    db.execute("INSERT OR REPLACE INTO kv VALUES (?, ?)", (key, str(value)))
    db.commit()


def kv_get(key: str):
    row = db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


# ----------------------------- БЭКАП В DISCORD -----------------------
BACKUP_FILE = "freepick_backup.json"
_backup_pending = False
_restore_done = False  # пока бэкап не прочитан, новый не пишем (иначе можно затереть хороший пустой базой)


def _dump() -> str:
    keys = ("panel_channel", "panel_message", "team_vcs", "match_no")
    data = {
        "links": db.execute("SELECT discord_id, steamid64 FROM links").fetchall(),
        "bans": db.execute("SELECT discord_id, reason, expires FROM bans").fetchall(),
        "ban_log": db.execute("SELECT * FROM ban_log").fetchall(),
        "elo": db.execute("SELECT discord_id, elo, wins, losses FROM elo").fetchall(),
        "kv": {k: kv_get(k) for k in keys if kv_get(k) is not None},
    }
    data.update(dump_extra())  # кланы и статистика матчей
    return json.dumps(data, ensure_ascii=False)


async def _get_backup_channel():
    return bot.get_channel(BACKUP_CHANNEL) or await bot.fetch_channel(BACKUP_CHANNEL)


async def _backup_task():
    global _backup_pending
    await asyncio.sleep(3)  # собираем несколько изменений в один бэкап
    _backup_pending = False
    if not _restore_done:
        await restore_backup(schedule=False)
        if not _restore_done:
            log.error("Бэкап не прочитан: новый не записываем, чтобы не затереть старый")
            return
    try:
        ch = await _get_backup_channel()
        old = [m async for m in ch.history(limit=20)
               if m.author.id == bot.user.id and m.attachments
               and m.attachments[0].filename == BACKUP_FILE]
        await ch.send("💾 Бэкап привязок (обновляется автоматически, не удаляйте)",
                      file=discord.File(io.BytesIO(_dump().encode("utf-8")), filename=BACKUP_FILE))
        for m in old:
            try:
                await m.delete()
            except discord.HTTPException:
                pass
    except discord.HTTPException:
        log.exception("Не удалось сохранить бэкап (проверь канал BACKUP_CHANNEL_ID и права бота)")


def schedule_backup():
    """Вызывать после любого изменения привязок/банов."""
    global _backup_pending
    if not BACKUP_CHANNEL or _backup_pending:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _backup_pending = True
    loop.create_task(_backup_task())


async def restore_backup(schedule: bool = True):
    """При старте: если база пустая (после обновления на Render), поднимаем привязки из Discord."""
    global _restore_done
    if not BACKUP_CHANNEL:
        log.warning("BACKUP_CHANNEL_ID не задан: привязки пропадут при обновлении бота")
        return
    data = None
    for attempt in range(3):  # несколько попыток на случай сбоя сети/лимитов
        try:
            ch = await _get_backup_channel()
            async for m in ch.history(limit=50):
                if m.author.id == bot.user.id and m.attachments and m.attachments[0].filename == BACKUP_FILE:
                    data = json.loads(await m.attachments[0].read())
                    break
            break  # канал прочитан успешно (бэкап есть или его правда нет)
        except (discord.HTTPException, ValueError):
            log.exception("Не удалось прочитать бэкап (попытка %s из 3)", attempt + 1)
            if attempt == 2:
                return  # _restore_done остаётся False: бэкап не перезаписываем
            await asyncio.sleep(5)
    if data:
        for did, sid in data.get("links", []):
            db.execute("INSERT OR IGNORE INTO links VALUES (?, ?)", (int(did), str(sid)))
        for row in data.get("bans", []):
            exp = int(row[2]) if len(row) > 2 else 0
            db.execute("INSERT OR IGNORE INTO bans (discord_id, reason, expires) VALUES (?, ?, ?)",
                       (int(row[0]), row[1], exp))
        for row in data.get("ban_log", []):
            if len(row) == 13:
                db.execute("INSERT OR IGNORE INTO ban_log VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", tuple(row))
        for did, e_, w_, l_ in data.get("elo", []):
            db.execute("INSERT OR IGNORE INTO elo VALUES (?, ?, ?, ?)", (int(did), int(e_), int(w_), int(l_)))
        for k, v in data.get("kv", {}).items():
            if kv_get(k) is None:
                kv_set(k, v)
        restore_extra(data)  # кланы и статистика матчей
        db.commit()
        log.info("Бэкап восстановлен: привязок %s, банов %s",
                 len(data.get("links", [])), len(data.get("bans", [])))
    else:
        log.info("Бэкап в канале не найден, создаём первый")
    _restore_done = True
    if schedule:
        schedule_backup()


STEAM_DM_RE = re.compile(r"Steam привязан: `(\d{17})`")


async def restore_from_dms():
    """Запасной вариант: достаём привязки из личных сообщений бота ("✅ Steam привязан: `...`").
    Работает для всех, у кого есть роль верификации, но нет привязки в базе
    (например, после обновления на Render, когда база стёрлась)."""
    if not VERIFIED_ROLE:
        return
    guild = get_guild()
    role = guild.get_role(VERIFIED_ROLE) if guild else None
    if not role:
        return
    restored = 0
    for member in list(role.members):
        if member.bot or get_steam(member.id):
            continue
        try:
            dm = member.dm_channel or await member.create_dm()
            async for m in dm.history(limit=200):
                if m.author.id != bot.user.id:
                    continue
                found = STEAM_DM_RE.search(m.content or "")
                if found:  # история идёт от новых к старым: берём последнюю привязку
                    cur = db.execute("INSERT OR IGNORE INTO links VALUES (?, ?)",
                                     (member.id, found.group(1)))
                    restored += cur.rowcount
                    break
        except discord.HTTPException:
            log.warning("Не удалось прочитать ЛС с %s", member)
        await asyncio.sleep(0.5)  # не упираемся в лимиты Discord
    db.commit()
    log.info("Восстановлено привязок из ЛС: %s", restored)
    if restored:
        schedule_backup()


# ----------------------------- СОСТОЯНИЕ -----------------------------
class State:
    def __init__(self):
        self.queue: list[discord.Member] = []
        self.phase = "queue"          # queue | draft | playing
        self.panel: discord.Message | None = None
        self.match_id: int | None = None
        self.matches: dict[int, dict] = {}
        self.team_vcs: dict[int, int] = {}             # номер команды -> id временного войса
        self.active_ids: set[int] = set()              # игроки текущего драфта/матча
        self.chat_msgs: list[discord.Message] = []     # сообщения драфта/матча, удаляются при сбросе
        self.match_players: dict[str, tuple[discord.Member, int]] = {}  # steamid64 -> (игрок, номер команды)
        self.captain_ids: set[int] = set()
        self.live = False                              # матч в живой фазе (после ножей)
        self.ever_live = False                         # матч хотя бы раз дошёл до going_live (иначе пустой результат не пишем)
        self.paused = False                            # матч на паузе из-за вышедшего игрока
        self.absent: set[int] = set()                  # игроки, которые вышли с сервера
        self.absent_names: dict[int, str] = {}         # discord id -> ник вышедшего (для надписи на экране)
        self.pause_stop: threading.Event | None = None # останавливает надпись с отсчётом, когда пауза снята
        self.break_channel: discord.TextChannel | None = None
        self.break_task: asyncio.Task | None = None
        self.break_lock = asyncio.Lock()
        self.match_channel: discord.TextChannel | None = None   # отдельный чат матча
        self.draft_task: asyncio.Task | None = None    # задача драфта (чтобы отменить, если все вышли из войса)
        self.draft_check = False                       # идёт проверка «все ли вышли из войса»
        self.connected: set[str] = set()               # steamid игроков матча, которые сейчас на сервере
        self.auto_started = False                      # автостарт уже запущен для этого матча
        self.moving = False                            # идёт перемещение игроков в войсы команд (драфт не отменять)
        self.cancel_votes: set[int] = set()            # кто нажал «Отмена игры»
        self.stage = False                             # идёт драфт/запуск: панель обновляет только драфт
        self.lock = asyncio.Lock()


S = State()
last_round: dict[int, dict] = {}   # match_id -> последнее событие round_end (там статистика игроков)
event_counts: dict = {}            # название события MatchZy -> сколько раз пришло (для /fp_diag)
event_log = deque(maxlen=12)       # последние события MatchZy (для /fp_diag)
events_seen: set[int] = set()      # match_id, от которых сервер уже присылал события (значит, remote log настроен)
snapshots: dict[int, dict] = {}  # match_id -> {steamid64: (игрок, команда)}: чтобы результат пришёл даже после сброса
captains: dict[int, dict] = {}     # match_id -> {1: капитан команды 1, 2: капитан команды 2}
live_stats: dict[int, dict] = {}   # match_id -> {steamid64: {"k","d","a","hs","tk"}}: убийства/смерти, посчитанные по player_death
live_reset: set[int] = set()       # match_id, для которых статистика уже обнулена на going_live (обнуляем только один раз)
death_events: dict[int, int] = {}  # match_id -> сколько событий player_death пришло (для /fp_diag)
user_ids: dict[str, str] = {}      # steamid64 -> userid на сервере (из player_connect): нужен, чтобы кикнуть игрока после матча

# счётчики HTTP-запросов от CS2-сервера (для /fp_diag): принято / отклонено из-за токена
http_hits = {"events": 0, "events_bad": 0, "demo": 0, "demo_bad": 0}


def token_ok(req: web.Request) -> bool:
    """Токен принимается из заголовка Authorization (с «Bearer » или без) ИЛИ из параметра ?t= в адресе."""
    h = (req.headers.get("Authorization") or "").strip()
    if h.lower().startswith("bearer "):
        h = h[7:].strip()
    tok = EVENT_TOKEN.encode()
    return (secrets.compare_digest(h.encode(), tok)
            or secrets.compare_digest(req.query.get("t", "").encode(), tok))


GRENADE_WORDS = ("hegrenade", "grenade", "molotov", "incgrenade", "incendiary", "inferno")


def weapon_name(data: dict) -> str:
    w = data.get("weapon")
    if isinstance(w, dict):
        w = w.get("name") or w.get("id") or ""
    return str(w or "").lower()


def sid_of(p) -> str:
    sid = str((p or {}).get("steamid", "") or "") if isinstance(p, dict) else ""
    return sid if sid and sid != "0" else ""


def is_grenade_tk(data: dict) -> bool:
    """Игрок убил тиммейта гранатой или молотовом."""
    if not data.get("friendly_fire"):
        return False
    atk, vic = sid_of(data.get("attacker")), sid_of(data.get("player"))
    if not atk or atk == vic:
        return False
    return any(w in weapon_name(data) for w in GRENADE_WORDS)


def tally_death(data: dict):
    """Считает убийства, смерти, помощи, хедшоты и убийства тиммейтов по событию player_death."""
    try:
        mid = int(data.get("matchid"))
    except (TypeError, ValueError):
        return
    t = live_stats.setdefault(mid, {})

    def slot(sid):
        return t.setdefault(str(sid), {"k": 0, "d": 0, "a": 0, "hs": 0, "tk": 0})

    victim, attacker = sid_of(data.get("player")), sid_of(data.get("attacker"))
    if victim:
        slot(victim)["d"] += 1
    suicide = bool(data.get("suicide")) or (attacker and attacker == victim)
    if attacker and not suicide:
        if data.get("friendly_fire"):
            slot(attacker)["tk"] += 1   # убийство тиммейта: в киллы не идёт
        else:
            slot(attacker)["k"] += 1
            if data.get("headshot"):
                slot(attacker)["hs"] += 1
    asst = data.get("assist")
    if isinstance(asst, dict) and not asst.get("friendly_fire"):
        ap = sid_of(asst.get("player") if isinstance(asst.get("player"), dict) else asst)
        if ap:
            slot(ap)["a"] += 1


def _server_has_stats(last: dict) -> bool:
    for n in (1, 2):
        for p in (last.get(f"team{n}") or {}).get("players") or []:
            st = p.get("stats") or {}
            if st.get("kills") or st.get("deaths") or st.get("damage"):
                return True
    return False


def build_from_tally(mid: int, players: dict, last: dict) -> dict:
    """Если сервер не прислал статистику игроков (или она пустая), берём ту, что накопили по player_death."""
    last = dict(last or {})
    if _server_has_stats(last):
        return last  # у сервера есть своя статистика (с уроном), её не трогаем
    tally = live_stats.get(mid)
    if not tally:
        return last
    teams = {1: [], 2: []}
    for sid, (m, n) in players.items():
        st = tally.get(str(sid), {})
        teams[n].append({"steamid": str(sid), "name": m.display_name,
                         "stats": {"kills": st.get("k", 0), "deaths": st.get("d", 0), "assists": st.get("a", 0),
                                   "damage": 0, "headshot_kills": st.get("hs", 0), "team_kills": st.get("tk", 0)}})
    for n in (1, 2):
        t = dict(last.get(f"team{n}") or {})
        t["players"] = teams[n]
        last[f"team{n}"] = t
    return last


def save_access():
    kv_set("team_vcs", json.dumps(S.team_vcs))
    schedule_backup()


def load_access():
    raw = kv_get("team_vcs")
    if raw:
        try:
            S.team_vcs = {int(k): int(v) for k, v in json.loads(raw).items()}
        except (ValueError, TypeError):
            S.team_vcs = {}


def pretty(map_name: str) -> str:
    return map_name.replace("de_", "").capitalize()


def panel_embed() -> discord.Embed:
    e = discord.Embed(title="Очередь — FreePick", color=0x2B2D31)
    e.add_field(
        name="Настройки матча",
        value=("Режим: Соревновательный\nВыбор игроков: Капитаны\n"
               "Выбор капитанов: Добровольно (кнопка «Стать капитаном»)\n"
               "Выбор карт: Вето\nФормат: BO1"),
        inline=False,
    )
    if S.phase == "queue":
        if QUEUE_VC:
            e.add_field(name="Как играть",
                        value=f"Зайдите в голосовой канал <#{QUEUE_VC}> (нужна Steam-верификация).\n"
                              f"Когда наберётся {NEED} игроков, матч стартует автоматически.",
                        inline=False)
        lines = [f"{n}. {m.mention} · {get_elo(m.id)}" for n, m in enumerate(S.queue, 1)]
        e.add_field(name=f"Игроков {len(S.queue)} из {NEED}",
                    value="\n".join(lines) or "Ожидаем игроков...", inline=False)
    elif S.phase == "draft":
        e.add_field(name="Статус", value="Идёт драфт: капитаны выбирают игроков и карту...", inline=False)
    else:
        e.add_field(name="Статус",
                    value=f"Матч #{S.match_id} идёт. Очередь откроется после его окончания.",
                    inline=False)
    return e


async def refresh_panel():
    if S.panel and not S.stage:
        try:
            await S.panel.edit(embed=panel_embed(), view=None if QUEUE_VC else QueueView())
        except discord.HTTPException:
            log.exception("Не удалось обновить панель")


# ----------------------------- ОЧЕРЕДЬ -------------------------------
class QueueView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # кнопки живут постоянно

    @discord.ui.button(label="Играть", emoji="✅", style=discord.ButtonStyle.success, custom_id="fp:join")
    async def join(self, i: discord.Interaction, b: discord.ui.Button):
        err = None
        full = False
        async with S.lock:
            if is_banned(i.user.id):
                err = "⛔ Вам запрещено играть в FreePick."
            elif not get_steam(i.user.id):
                err = "Сначала пройдите Steam-верификацию (кнопка «Верификация»)"
            elif S.phase != "queue":
                err = "Сейчас идёт набор/матч, дождитесь окончания."
            elif any(m.id == i.user.id for m in S.queue):
                err = "Вы уже в очереди."
            else:
                S.queue.append(i.user)
                if len(S.queue) >= NEED:
                    full = True
                    S.phase = "draft"  # АВТО-СТАРТ: очередь полная
        if err:
            return await i.response.send_message(err, ephemeral=True)
        S.panel = i.message
        await i.response.edit_message(embed=panel_embed(), view=self)
        if full:
            asyncio.create_task(run_match(i.channel, list(S.queue)))

    @discord.ui.button(label="Выйти", emoji="🚪", style=discord.ButtonStyle.danger, custom_id="fp:leave")
    async def leave(self, i: discord.Interaction, b: discord.ui.Button):
        err = None
        async with S.lock:
            if S.phase != "queue":
                err = "Сейчас выйти нельзя: идёт драфт или матч."
            elif not any(m.id == i.user.id for m in S.queue):
                err = "Вас нет в очереди."
            else:
                S.queue = [m for m in S.queue if m.id != i.user.id]
        if err:
            return await i.response.send_message(err, ephemeral=True)
        S.panel = i.message
        await i.response.edit_message(embed=panel_embed(), view=self)


# ----------------------------- ГОТОВНОСТЬ ----------------------------
class ReadyView(discord.ui.View):
    """Когда набрано 10 игроков, каждый должен нажать «Готов». Кто не нажал, выбывает из очереди."""

    def __init__(self, players: list[discord.Member]):
        super().__init__(timeout=READY_TIMEOUT)
        self.players = players
        self.ids = {m.id for m in players}
        self.ready: set[int] = set()

    def embed(self, title: str = "Матч найден!", color: int = 0x57F287) -> discord.Embed:
        lines = [f"{'✅' if m.id in self.ready else '⏳'} {m.mention}" for m in self.players]
        e = discord.Embed(title=title, color=color,
                          description=f"Нажмите **Готов** в течение {READY_TIMEOUT} сек.\n\n" + "\n".join(lines))
        e.set_footer(text=f"Готовы: {len(self.ready)} из {len(self.players)}")
        return e

    @discord.ui.button(label="Готов", emoji="✅", style=discord.ButtonStyle.success)
    async def ok(self, i: discord.Interaction, b: discord.ui.Button):
        if i.user.id not in self.ids:
            return await i.response.send_message("Вы не участвуете в этом матче.", ephemeral=True)
        self.ready.add(i.user.id)
        if len(self.ready) == len(self.players):
            await i.response.edit_message(embed=self.embed(), view=None)
            self.stop()
        else:
            await i.response.edit_message(embed=self.embed(), view=self)


async def ready_check(channel, players: list[discord.Member]) -> bool:
    """True, если все нажали «Готов». Иначе матч отменяется, не нажавшие убираются из очереди."""
    view = ReadyView(players)
    msg = await track_send(channel, " ".join(m.mention for m in players),
                           embed=view.embed(), view=view)
    await view.wait()
    if len(view.ready) == len(players):
        return True

    # ---- не все готовы: отмена ----
    absent = [m for m in players if m.id not in view.ready]
    ready_players = [m for m in players if m.id in view.ready]
    try:
        await msg.edit(embed=view.embed("Матч отменён", 0xED4245), view=None)
    except discord.HTTPException:
        pass

    async def _kick_from_queue(m):
        if QUEUE_VC and m.voice and m.voice.channel and m.voice.channel.id == QUEUE_VC:
            try:
                await m.move_to(None)  # убираем из войса очереди
            except discord.HTTPException:
                pass
        try:
            await m.send("⏰ Вы не нажали «Готов» и были убраны из очереди. Зайдите снова, когда будете готовы.")
        except discord.HTTPException:
            pass

    await asyncio.gather(*(_kick_from_queue(m) for m in absent), return_exceptions=True)
    async with S.lock:
        S.phase = "queue"
        S.queue = ready_players          # готовые остаются в очереди
        S.active_ids.clear()
        S.draft_task = None
    for m in absent:  # авто-бан за неготовность
        await auto_ban(m, "ready", READY_REASON)
    await clear_chat()
    try:
        await channel.send("⏰ Не все нажали «Готов». Не нажавшие убраны, остальные остались в очереди: "
                           + ", ".join(m.mention for m in absent),
                           delete_after=30, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        pass
    await refresh_panel()
    await sync_queue()
    return False


# ----------------------------- ПИКИ И ВЕТО ---------------------------
def ts_left(sec: int) -> str:
    """Живой таймер Discord: «через N сек»."""
    return f"<t:{int(time.time()) + sec}:R>"


class CaptainView(discord.ui.View):
    """Игроки сами вызываются в капитаны: первые двое нажавших становятся капитанами."""

    def __init__(self, players: list[discord.Member], no: int):
        super().__init__(timeout=CAPTAIN_TIMEOUT)
        self.players, self.no = players, no
        self.caps: list[discord.Member] = []
        self.end = int(time.time()) + CAPTAIN_TIMEOUT

    def embed(self) -> discord.Embed:
        have = ", ".join(m.mention for m in self.caps) or "пока никого"
        e = discord.Embed(title=f"Очередь — FreePick #{self.no}", color=0x2B2D31)
        e.description = (f"**Выбор капитанов** — нажмите кнопку, нужно двое.\n"
                         f"⏳ Закончится <t:{self.end}:R>\n👑 Капитаны: {have}")
        return e

    @discord.ui.button(label="Стать капитаном", emoji="👑", style=discord.ButtonStyle.success)
    async def take(self, i: discord.Interaction, b: discord.ui.Button):
        member = next((m for m in self.players if m.id == i.user.id), None)
        if not member:
            return await i.response.send_message("Вы не участвуете в этом матче.", ephemeral=True)
        if member in self.caps:
            return await i.response.send_message("Вы уже вызвались капитаном.", ephemeral=True)
        self.caps.append(member)
        done = len(self.caps) >= 2
        await i.response.edit_message(embed=self.embed(), view=None if done else self)
        if done:
            self.stop()


async def choose_captains(msg: discord.Message, no: int, players: list[discord.Member]) -> list[discord.Member]:
    view = CaptainView(players, no)
    await msg.edit(embed=view.embed(), view=view)
    await view.wait()
    caps = view.caps[:2]
    if len(caps) < 2:  # не хватило добровольцев: добираем случайно
        rest = [m for m in players if m not in caps]
        caps += random.sample(rest, 2 - len(caps))
    return caps


def next_match_no() -> int:
    n = int(kv_get("match_no") or 0) + 1
    kv_set("match_no", n)
    schedule_backup()
    return n


def draft_embed(no: int, teams, pool, cap=None, done: bool = False, last: str = "") -> discord.Embed:
    """Табло драфта: две команды + свободные игроки."""
    e = discord.Embed(title=f"Очередь — FreePick #{no}", color=0x2B2D31)
    if done:
        e.description = "**Драфт завершён** — команды собраны."
    elif cap:
        e.description = (f"**Выбор игроков** — ходит капитан {cap.mention}\n"
                         f"⏳ Ход закончится {ts_left(PICK_TIMEOUT)}")
    for t in teams:
        e.add_field(name=f"team_{t[0].display_name}"[:256],
                    value="\n".join(f"`{n:02d}` {m.mention}" for n, m in enumerate(t, 1)), inline=True)
    if pool:
        e.add_field(name=f"Свободные игроки: {len(pool)}",
                    value="\n".join(f"`{n:02d}` {m.mention}" for n, m in enumerate(pool, 1)), inline=False)
    if last:
        e.set_footer(text=last)
    return e


def veto_embed(no: int, maps: list, banned: list, cap=None, final: str = "", last: str = "") -> discord.Embed:
    """Табло вето карт: забанено / осталось, ход капитана и таймер."""
    e = discord.Embed(title=f"Очередь — FreePick #{no}", color=0x2B2D31)
    if final:
        e.description = f"**Карта выбрана** — играем на **{pretty(final)}**."
    else:
        e.description = (f"**Выбор карт** — надо убрать ещё **{len(maps) - 1}** карт.\n"
                         f"👤 Ходит капитан {cap.mention}\n⏳ Ход закончится {ts_left(PICK_TIMEOUT)}")
    e.add_field(name=f"🚫 Забанено: {len(banned)}",
                value="\n".join(f"✖ ~~{pretty(m)}~~ · {c.display_name}" for m, c in banned)[:1024] or "—",
                inline=True)
    e.add_field(name=f"▸ Осталось: {len(maps)} из {len(MAPS)}",
                value="\n".join(pretty(m) for m in maps), inline=True)
    if last:
        e.set_footer(text=last)
    return e


def launch_embed(no: int, teams, status: str) -> discord.Embed:
    """Этап «создаю каналы и запускаю сервер»: те же команды + статус."""
    e = discord.Embed(title=f"Очередь — FreePick #{no}", description=status, color=0x2B2D31)
    for t in teams:
        if t:
            e.add_field(name=f"team_{t[0].display_name}"[:256],
                        value="\n".join(f"`{n:02d}` {m.mention}" for n, m in enumerate(t, 1)), inline=True)
    return e


class PickView(discord.ui.View):
    """Кнопка на каждого свободного игрока: «ник | ELO: 1000»."""

    def __init__(self, cap: discord.Member, pool: list[discord.Member]):
        super().__init__(timeout=PICK_TIMEOUT)
        self.cap, self.pool, self.picked = cap, pool, None
        for m in pool:
            btn = discord.ui.Button(label=f"{m.display_name[:55]} | ELO: {get_elo(m.id)}",
                                    style=discord.ButtonStyle.secondary)
            btn.callback = self._make_cb(m)
            self.add_item(btn)

    def _make_cb(self, member: discord.Member):
        async def cb(i: discord.Interaction):
            if i.user.id != self.cap.id:
                return await i.response.send_message("Сейчас выбирает другой капитан.", ephemeral=True)
            self.picked = member
            await i.response.defer()
            self.stop()
        return cb


class VetoView(discord.ui.View):
    def __init__(self, cap: discord.Member, maps: list[str]):
        super().__init__(timeout=PICK_TIMEOUT)
        self.cap, self.banned = cap, None
        for m in maps:
            btn = discord.ui.Button(label=pretty(m), style=discord.ButtonStyle.danger)
            btn.callback = self._make_cb(m)
            self.add_item(btn)

    def _make_cb(self, map_name: str):
        async def cb(i: discord.Interaction):
            if i.user.id != self.cap.id:
                return await i.response.send_message("Сейчас банит другой капитан.", ephemeral=True)
            self.banned = map_name
            await i.response.defer()
            self.stop()
        return cb


# ----------------------------- МАТЧ ----------------------------------
# Огонь по своим: пули по тиммейтам не проходят, гранаты и молотов ранят. Штраф за убийство тиммейта.
GRENADE_FF = os.getenv("GRENADE_FF", "1") == "1"
TK_PENALTY = int(os.getenv("TK_PENALTY", "300"))


def ff_cvars() -> dict:
    if not GRENADE_FF:
        return {"mp_friendlyfire": "0"}
    return {
        "mp_friendlyfire": "1",
        "ff_damage_reduction_bullets": "0",
        "ff_damage_reduction_grenade": "1",
        "ff_damage_reduction_grenade_self": "1",
        "ff_damage_reduction_other": "1",
        "cash_player_killed_teammate": str(-TK_PENALTY),
    }


def format_cvars() -> dict:
    """Формат как на FACEIT: MR12 (24 раунда), смена сторон на перерыве между половинами, овертайм.
    В тест-режиме карта короткая: заканчивается сама, поэтому приходят map_result и демо."""
    return {
        "mp_maxrounds": str(TEST_MAXROUNDS if TEST_MODE else MAX_ROUNDS),
        "mp_halftime": "1",
        "mp_overtime_enable": "0" if TEST_MODE else "1",
    }


def build_match(match_id: int, teams: list[list[discord.Member]], map_name: str) -> dict:
    def team(t):
        name = f"team_{t[0].display_name}" if t else "team_test"
        return {"name": name,
                "players": {get_steam(m.id): m.display_name for m in t}}

    return {
        "matchid": match_id,
        "num_maps": 1,
        "maplist": [map_name],
        "map_sides": ["team1_ct"] if TEST_MODE else ["knife"],
        "players_per_team": TEAM_SIZE,
        "min_players_to_ready": 1 if TEST_MODE else TEAM_SIZE,
        "clinch_series": True,
        "team1": team(teams[0]),
        "team2": team(teams[1]),
        "cvars": {"hostname": "VIBE MIX FreePick", **format_cvars(), **ff_cvars()},
    }


def _fix_text(s: str) -> str:
    """Ответ CS2 приходит в UTF-8, а читается как latin-1: возвращаем нормальные буквы."""
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def _rcon_run(c, cmd: str):
    """Команды только из ASCII отправляем как latin-1, команды с русским текстом (say ...) как UTF-8.
    Ответ сервера (UTF-8) читаем побайтно и декодируем, чтобы не было ни ошибок, ни кракозябр."""
    enc = "latin-1" if cmd.isascii() else "utf-8"
    try:
        resp = c.run(cmd, encoding=enc)
    except TypeError:  # старая версия библиотеки без параметра encoding
        try:
            return c.run(cmd)
        except (UnicodeDecodeError, UnicodeEncodeError):
            return ""
    except UnicodeDecodeError:
        return ""
    return _fix_text(resp) if enc == "latin-1" else resp


def load_on_server(match_id: int, map_name: str = ""):
    """Блокирующая функция: отправляет команды на CS2-сервер по RCON.
    Сначала включает GOTV и перезагружает карту (CS2 применяет tv_enable только при смене карты),
    потом задаёт настройки и грузит матч.
    Значения со ссылками обязательно в кавычках: иначе консоль CS2 считает «//» комментарием и режет URL до «https:».
    Токен дублируется в адресе (?t=): если сервер не передаст заголовок Authorization, бот всё равно примет запрос."""
    cmds = [
        f'matchzy_remote_log_url "{WEB_BASE_URL}/events?t={EVENT_TOKEN}"',
        'matchzy_remote_log_header_key "Authorization"',
        f'matchzy_remote_log_header_value "{EVENT_TOKEN}"',
        'matchzy_chat_prefix {PURPLE}VIBE MIX{Default}',
        # GOTV должен быть включён, иначе демо не записывается
        'tv_enable 1',
        'tv_delay 0',
        # запись демо: в имени файла обязательно {MATCH_ID}, по нему кнопка «Скачать демку» находит файл
        'matchzy_demo_recording_enabled true',
        'matchzy_demo_path "MatchZy/"',
        'matchzy_demo_name_format "{TIME}_{MATCH_ID}_{MAP}"',
        # загрузка демо матча на веб-сервер бота (приходит после окончания карты)
        f'matchzy_demo_upload_url "{WEB_BASE_URL}/demo?t={EVENT_TOKEN}"',
        'matchzy_demo_upload_header_key "Authorization"',
        f'matchzy_demo_upload_header_value "{EVENT_TOKEN}"',
    ]
    cmds += [f"{k} {v}" for k, v in format_cvars().items()]  # 24 раунда, смена сторон, овертайм
    cmds += [f"{k} {v}" for k, v in ff_cvars().items()]  # огонь по своим от гранат + штраф за убийство тиммейта
    cmds.append(f'matchzy_loadmatch_url "{WEB_BASE_URL}/match/{match_id}.json"')

    # 1) сбросить прошлый матч (иначе MatchZy не загрузит новый) и включить GOTV
    with Rcon(SERVER_IP, SERVER_PORT, passwd=RCON_PASSWORD, timeout=10) as c:
        _rcon_run(c, "get5_endmatch")
        time.sleep(1)
        _rcon_run(c, "tv_enable 1")
        _rcon_run(c, "tv_delay 0")

    # 2) перезагрузка карты, чтобы GOTV реально включился
    if map_name and map_name != "?":
        try:
            with Rcon(SERVER_IP, SERVER_PORT, passwd=RCON_PASSWORD, timeout=10) as c:
                _rcon_run(c, f"changelevel {map_name}")
        except Exception:
            pass  # сервер может оборвать соединение при смене карты
        time.sleep(10)
        for _ in range(10):  # ждём, пока RCON снова ответит
            try:
                with Rcon(SERVER_IP, SERVER_PORT, passwd=RCON_PASSWORD, timeout=5) as c:
                    _rcon_run(c, "status")
                break
            except Exception:
                time.sleep(3)

    # 3) настройки и загрузка матча
    last = ""
    with Rcon(SERVER_IP, SERVER_PORT, passwd=RCON_PASSWORD, timeout=10) as c:
        for cmd in cmds:
            last = _rcon_run(c, cmd) or ""
            if cmd.startswith("matchzy_") and "unknown" in last.lower():
                log.warning("RCON: сервер не знает команду %s", cmd.split()[0])
    return last  # ответ сервера на matchzy_loadmatch_url (последняя команда)


def set_event_cvars():
    """Блокирующая функция: заново ставит адрес для событий и загрузки демо уже ПОСЛЕ загрузки матча
    (MatchZy мог сбросить эти настройки при loadmatch). Возвращает ответ сервера на запрос remote_log_url;
    если какие-то matchzy_* команды сервер не знает, дописывает их в конец после «НЕИЗВЕСТНО:»."""
    cmds = [
        f'matchzy_remote_log_url "{WEB_BASE_URL}/events?t={EVENT_TOKEN}"',
        'matchzy_remote_log_header_key "Authorization"',
        f'matchzy_remote_log_header_value "{EVENT_TOKEN}"',
        f'matchzy_demo_upload_url "{WEB_BASE_URL}/demo?t={EVENT_TOKEN}"',
        'matchzy_demo_upload_header_key "Authorization"',
        f'matchzy_demo_upload_header_value "{EVENT_TOKEN}"',
        'matchzy_demo_recording_enabled true',
        'matchzy_demo_path "MatchZy/"',
        'matchzy_demo_name_format "{TIME}_{MATCH_ID}_{MAP}"',
    ]
    cmds += [f"{k} {v}" for k, v in ff_cvars().items()]  # MatchZy мог вернуть свои значения при загрузке матча
    unknown = []
    with Rcon(SERVER_IP, SERVER_PORT, passwd=RCON_PASSWORD, timeout=10) as c:
        for cmd in cmds:
            resp = _rcon_run(c, cmd) or ""
            log.info("RCON %s -> %r", cmd.split()[0], resp.strip()[:100])  # токен в лог не пишем
            if "unknown" in resp.lower():
                unknown.append(cmd.split()[0])
        cur = _rcon_run(c, "css_cvar matchzy_remote_log_url") or _rcon_run(c, "matchzy_remote_log_url") or ""
    if unknown:
        cur += " | НЕИЗВЕСТНО: " + ", ".join(sorted(set(unknown)))
    return cur


def rcon_gamestate():
    """Блокирующая функция: спрашивает у MatchZy состояние матча (get5_status)."""
    with Rcon(SERVER_IP, SERVER_PORT, passwd=RCON_PASSWORD, timeout=10) as c:
        resp = _rcon_run(c, "get5_status") or ""
    m = re.search(r'"gamestate"\s*:\s*"(\w+)"', resp)
    return m.group(1) if m else None


def rcon_scores():
    """Блокирующая функция: счёт текущей карты из get5_status (если события MatchZy не доходят до бота)."""
    with Rcon(SERVER_IP, SERVER_PORT, passwd=RCON_PASSWORD, timeout=10) as c:
        raw = _rcon_run(c, "get5_status") or ""
    try:
        j = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
        return ((j.get("team1") or {}).get("current_map_score"),
                (j.get("team2") or {}).get("current_map_score"))
    except Exception:
        return None


def rcon_kick(user_id, steamid: str):
    """Блокирующая функция: кикает игрока с CS2-сервера (по userid из события MatchZy)."""
    target = str(user_id) if user_id not in (None, "") else steamid
    with Rcon(SERVER_IP, SERVER_PORT, passwd=RCON_PASSWORD, timeout=10) as c:
        _rcon_run(c, f"kickid {target}")


def rcon_kick_many(targets: list):
    """Блокирующая функция: кикает сразу нескольких игроков (userid или SteamID)."""
    with Rcon(SERVER_IP, SERVER_PORT, passwd=RCON_PASSWORD, timeout=10) as c:
        for t in targets:
            _rcon_run(c, f"kickid {t}")


async def kick_everyone(targets: list, delay: int = KICK_DELAY):
    """После матча кикает всех игроков с сервера (даём несколько секунд посмотреть табло)."""
    if not KICK_AFTER_MATCH or not targets:
        return
    if delay:
        await asyncio.sleep(delay)
    try:
        await asyncio.to_thread(rcon_kick_many, targets)
        log.info("После матча кикнуто игроков: %s", len(targets))
    except Exception:
        log.exception("Не удалось кикнуть игроков после матча")


def rcon_pause(pause: bool):
    """Блокирующая функция: ставит матч на паузу или снимает её (админская пауза MatchZy)."""
    primary = "css_forcepause" if pause else "css_forceunpause"
    fallback = "mp_pause_match" if pause else "mp_unpause_match"
    with Rcon(SERVER_IP, SERVER_PORT, passwd=RCON_PASSWORD, timeout=10) as c:
        resp = _rcon_run(c, primary) or ""
        if "unknown command" in resp.lower():
            _rcon_run(c, fallback)


def _fmt_mmss(sec: int) -> str:
    sec = max(0, int(sec))
    return f"{sec // 60}:{sec % 60:02d}"


_overlay_mode = None  # какой способ показа надписи по центру экрана работает на сервере: "hsay" | "script"


def _send_overlay(c, text: str):
    """Надпись по центру экрана у всех игроков. Пробуем css_hsay (CS2-SimpleAdmin), затем VScript."""
    global _overlay_mode
    text = text.replace('"', "'")
    for mode in ([_overlay_mode] if _overlay_mode else ["hsay", "script"]):
        if mode == "hsay":
            resp = _rcon_run(c, f"css_hsay {text}") or ""
        else:
            resp = _rcon_run(c, f'script ScriptPrintMessageCenterAll("{text}")') or ""
        if "unknown command" not in resp.lower():
            _overlay_mode = mode
            return
    _overlay_mode = None  # ни один способ не сработал: останется только сообщение в чат


def rcon_pause_overlay(get_names, seconds: int, stop: threading.Event):
    """Блокирующая функция (запускать в потоке): пока идёт техпауза, раз в секунду обновляет надпись
    «Игрок X вышел из игры / Техническая пауза M:SS» и держит включённым all talk. По окончании возвращает all talk."""
    old_alltalk = "0"
    with Rcon(SERVER_IP, SERVER_PORT, passwd=RCON_PASSWORD, timeout=10) as c:
        try:
            if PAUSE_ALLTALK:
                m = re.search(r'=\s*"?(\d)"?', _rcon_run(c, "sv_alltalk") or "")
                old_alltalk = m.group(1) if m else "0"
                _rcon_run(c, "sv_alltalk 1")
            _rcon_run(c, f"say [ПАУЗА] Игрок {get_names()} вышел из игры. "
                         f"Техническая пауза {_fmt_mmss(seconds)}" + (". All talk включён" if PAUSE_ALLTALK else ""))
            left = seconds
            while left >= 0 and not stop.is_set():
                _send_overlay(c, f"Игрок {get_names()} вышел из игры | Техническая пауза {_fmt_mmss(left)}")
                if stop.wait(1):
                    break
                left -= 1
        finally:
            if PAUSE_ALLTALK:
                try:
                    _rcon_run(c, f"sv_alltalk {old_alltalk}")
                except Exception:
                    pass


def rcon_set_alltalk(value: str):
    """Блокирующая функция: включает/выключает all talk на сервере."""
    with Rcon(SERVER_IP, SERVER_PORT, passwd=RCON_PASSWORD, timeout=10) as c:
        _rcon_run(c, f"sv_alltalk {value}")


_halftime_busy = False


async def halftime_talk():
    """Смена сторон: все игроки (обе команды) могут говорить друг с другом, после перерыва all talk выключается."""
    global _halftime_busy
    if _halftime_busy:
        return
    _halftime_busy = True
    try:
        await asyncio.to_thread(rcon_set_alltalk, "1")
        try:
            await asyncio.to_thread(rcon_raw, "say [СМЕНА СТОРОН] All talk включён на перерыв")
        except Exception:
            pass
        await asyncio.sleep(HALFTIME_TALK_SECONDS)
    except Exception:
        log.exception("all talk на смене сторон не сработал")
    finally:
        _halftime_busy = False
        if not S.paused:  # если идёт техпауза, all talk вернёт она сама
            try:
                await asyncio.to_thread(rcon_set_alltalk, "0")
            except Exception:
                log.exception("Не удалось выключить all talk")


def rcon_force_start() -> str:
    """Блокирующая функция: принудительный старт матча MatchZy (как админская команда .start)."""
    with Rcon(SERVER_IP, SERVER_PORT, passwd=RCON_PASSWORD, timeout=10) as c:
        return _rcon_run(c, "css_start") or ""


def rcon_force_ready() -> str:
    """Запасной вариант старта: все игроки сразу «готовы» (как .forceready)."""
    with Rcon(SERVER_IP, SERVER_PORT, passwd=RCON_PASSWORD, timeout=10) as c:
        return _rcon_run(c, "css_forceready") or ""


def rcon_players():
    """Блокирующая функция: (SteamID64 игроков из status, число людей на сервере).
    CS2 в status не показывает SteamID, поэтому главное число людей из строки «players : N humans»."""
    with Rcon(SERVER_IP, SERVER_PORT, passwd=RCON_PASSWORD, timeout=10) as c:
        resp = _rcon_run(c, "status") or ""
    ids = {str(76561197960265728 + int(a)) for a in re.findall(r"\[U:1:(\d+)\]", resp)}
    m = re.search(r"players\s*:\s*(\d+)\s+humans", resp)
    humans = int(m.group(1)) if m else 0
    global _status_logged
    if not m and not _status_logged:
        _status_logged = True
        log.info("RCON status: не найдена строка с числом игроков, ответ сервера: %r", resp[:400])
    return ids, humans


_status_logged = False


def rcon_raw(cmd: str) -> str:
    """Блокирующая функция: выполняет любую RCON-команду и возвращает ответ (для /fp_diag)."""
    with Rcon(SERVER_IP, SERVER_PORT, passwd=RCON_PASSWORD, timeout=10) as c:
        return _rcon_run(c, cmd) or ""


def rcon_cvar(name: str) -> str:
    """Блокирующая функция: читает настройку плагина. Сначала css_cvar (CounterStrikeSharp), потом обычная команда."""
    with Rcon(SERVER_IP, SERVER_PORT, passwd=RCON_PASSWORD, timeout=10) as c:
        r = _rcon_run(c, f"css_cvar {name}") or ""
        if not r.strip() or "unknown" in r.lower():
            r = _rcon_run(c, name) or ""
    return r


def rcon_say(text: str):
    """Блокирующая функция: сообщение в общий чат сервера."""
    text = re.sub(r"[;\"\r\n]", " ", text)[:200]
    with Rcon(SERVER_IP, SERVER_PORT, passwd=RCON_PASSWORD, timeout=10) as c:
        _rcon_run(c, f"say {text}")


async def announce_tk(data: dict):
    """Игрок убил тиммейта гранатой/молотовом: пишем об этом в чат сервера (штраф снимает сама игра)."""
    atk = (data.get("attacker") or {}).get("name") or "?"
    vic = (data.get("player") or {}).get("name") or "?"
    try:
        await asyncio.to_thread(rcon_say, f"[TK] {atk} убил тиммейта {vic} гранатой: штраф -${TK_PENALTY}")
    except Exception:
        log.exception("Не удалось отправить сообщение о TK на сервер")


# ----------------------------- ВОЙСЫ КОМАНД --------------------------
async def move_to_voice(guild: discord.Guild, teams):
    """Создаёт категорию «VIBE — team_A VS team_B» с двумя войсами (по одному на команду) и перекидывает туда игроков."""
    await clear_voice_access()  # на случай, если остались войсы от прошлого матча
    names = [f"team_{t[0].display_name}" if t else f"team_{n}" for n, t in enumerate(teams, 1)]
    cat_name = f"VIBE MIX — {names[0]} VS {names[1]}"[:100]
    base_cat = S.panel.channel.category if S.panel else None
    category = None
    try:
        category = await guild.create_category(
            cat_name,
            overwrites={
                guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=False),
                guild.me: discord.PermissionOverwrite(view_channel=True, connect=True,
                                                      move_members=True, manage_channels=True),
            },
            reason="FreePick: категория матча")
        S.team_vcs[0] = category.id  # ключ 0 = категория
        save_access()
    except discord.HTTPException:
        log.exception("Не удалось создать категорию матча (нужно право Manage Channels)")
    for n, team in enumerate(teams, 1):
        if not team:
            continue
        ow = {
            guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, connect=True,
                                                  move_members=True, manage_channels=True),
        }
        for m in team:
            mem = guild.get_member(m.id)
            if mem:
                ow[mem] = discord.PermissionOverwrite(view_channel=True, connect=True, speak=True)
        try:
            ch = await guild.create_voice_channel(names[n - 1][:100], overwrites=ow,
                                                  category=category or base_cat,
                                                  reason="FreePick: войс команды")
        except discord.HTTPException:
            log.exception("Не удалось создать войс Team %s (нужны права Manage Channels и Move Members)", n)
            continue
        S.team_vcs[n] = ch.id
        save_access()  # сохраняем сразу: если бот упадёт, войс удалится при следующем старте
        for m in team:
            mem = guild.get_member(m.id)
            if mem and mem.voice:
                try:
                    await mem.move_to(ch)
                except discord.HTTPException:
                    log.exception("Не удалось переместить %s", mem)
    save_access()


async def clear_voice_access():
    """После матча удаляет войсы и категорию (игроков из войсов возвращает в войс очереди)."""
    if not S.team_vcs:
        return
    vcs, S.team_vcs = dict(S.team_vcs), {}  # обнуляем сразу, чтобы on_voice_state_update не гнал игроков обратно
    queue_ch = bot.get_channel(QUEUE_VC) if QUEUE_VC else None
    order = [v for k, v in vcs.items() if k != 0] + ([vcs[0]] if 0 in vcs else [])  # категория удаляется последней
    for cid in order:
        ch = bot.get_channel(cid)
        if not ch:
            continue
        if queue_ch and isinstance(ch, discord.VoiceChannel):
            await asyncio.gather(*(m.move_to(queue_ch) for m in list(ch.members)), return_exceptions=True)
        try:
            await ch.delete(reason="FreePick: матч окончен")
        except discord.HTTPException:
            log.exception("Не удалось удалить войс/категорию матча")
    save_access()


async def open_match_chat(origin, players: list[discord.Member]):
    """Когда сервер готов: открывает отдельный чат только для игроков матча (в нём одна карточка с connect).
    Ссылка на чат уходит каждому игроку в личные сообщения."""
    guild = getattr(origin, "guild", None)
    if not guild:
        return None
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                              read_message_history=True),
    }
    for m in players:
        overwrites[m] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True)
    try:
        ch = await guild.create_text_channel(
            "матч-freepick",
            overwrites=overwrites,
            category=getattr(origin, "category", None),
            reason="FreePick: матч готов")
    except discord.HTTPException:
        log.exception("Не удалось создать чат матча (нужно право Manage Channels), используем общий канал")
        return None
    S.match_channel = ch

    # ---- уведомление в ЛС каждому игроку ----
    text = (f"🎯 Матч готов! Подключение к серверу в отдельном чате: "
            f"{ch.jump_url}")
    closed = []
    for m in players:
        try:
            await m.send(text)
        except discord.HTTPException:
            closed.append(m)  # ЛС закрыты
    # у кого ЛС закрыты — предупреждаем в общем канале на 30 секунд
    if closed:
        try:
            await origin.send(
                " ".join(m.mention for m in closed) +
                f" ваши ЛС закрыты. Подключение здесь: {ch.mention}",
                delete_after=30)
        except discord.HTTPException:
            pass
    return ch


async def close_match_chat():
    ch, S.match_channel = S.match_channel, None
    if ch:
        try:
            await ch.delete(reason="FreePick: матч окончен")
        except discord.HTTPException:
            pass


def get_guild() -> discord.Guild | None:
    if GUILD_ID:
        g = bot.get_guild(GUILD_ID)
        if g:
            return g
    return S.panel.guild if S.panel and S.panel.guild else None


class BreakView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Продолжить матч", emoji="▶️", style=discord.ButtonStyle.success)
    async def resume(self, i: discord.Interaction, b: discord.ui.Button):
        is_admin = isinstance(i.user, discord.Member) and i.user.guild_permissions.administrator
        if i.user.id not in S.captain_ids and not is_admin:
            return await i.response.send_message("Продолжить матч могут только капитаны и администрация.",
                                                 ephemeral=True)
        if not S.paused:
            return await i.response.send_message("Матч уже продолжается.", ephemeral=True)
        await i.response.defer()
        await resume_match(f"{i.user.mention} продолжил матч")


class MatchView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="Подключиться", url=f"{WEB_BASE_URL}/connect"))

    @discord.ui.button(label=f"Отмена игры 0/{CANCEL_VOTES}", emoji="⛔", style=discord.ButtonStyle.danger)
    async def cancel(self, i: discord.Interaction, b: discord.ui.Button):
        if S.phase != "playing":
            return await i.response.send_message("Матч уже сброшен.", ephemeral=True)
        is_admin = isinstance(i.user, discord.Member) and i.user.guild_permissions.administrator
        player_ids = {m.id for m, _ in S.match_players.values()}
        if i.user.id not in player_ids and not is_admin:
            return await i.response.send_message("Вы не участвуете в этом матче.", ephemeral=True)
        if i.user.id in S.cancel_votes:
            S.cancel_votes.discard(i.user.id)   # повторное нажатие = снять голос
        else:
            S.cancel_votes.add(i.user.id)
        if is_admin or len(S.cancel_votes) >= CANCEL_VOTES:
            await i.response.send_message("⛔ Игра отменена, все выкинуты с сервера.", ephemeral=True)
            await cancel_match()
            return
        b.label = f"Отмена игры {len(S.cancel_votes)}/{CANCEL_VOTES}"
        await i.response.edit_message(view=self)

    @discord.ui.button(label="Матч закончен", emoji="🏁", style=discord.ButtonStyle.secondary)
    async def finish(self, i: discord.Interaction, b: discord.ui.Button):
        is_admin = isinstance(i.user, discord.Member) and i.user.guild_permissions.administrator
        if i.user.id not in S.captain_ids and not is_admin:
            return await i.response.send_message("Завершить матч могут только капитаны и администрация.",
                                                 ephemeral=True)
        if S.phase != "playing":
            return await i.response.send_message("Матч уже сброшен.", ephemeral=True)
        await i.response.send_message("🏁 Матч завершён, очередь открывается.", ephemeral=True)
        await reset_to_queue()


async def cancel_match():
    """Отмена игры: без результата и без ELO, всех сразу кикаем с CS2-сервера."""
    if S.phase != "playing":
        return
    if S.match_id:
        posted_results.add(S.match_id)   # результат не публикуем, ELO не меняем
    try:
        await asyncio.to_thread(rcon_raw, "get5_endmatch")
    except Exception:
        log.exception("get5_endmatch не удался")
    await reset_to_queue(kick_delay=0)


async def handle_disconnect(steamid: str):
    """Игрок вышел с сервера во время матча: пауза + отдельный чат для перерыва."""
    info = S.match_players.get(steamid)
    if not info or not S.live or S.phase != "playing":
        return
    member, team_n = info
    S.absent.add(member.id)
    S.absent_names[member.id] = member.display_name
    first = not S.paused
    if first:
        S.paused = True  # ставим флаг сразу, чтобы второй выход не запускал паузу повторно
        try:
            await asyncio.to_thread(rcon_pause, True)
        except Exception:
            log.exception("Не удалось поставить матч на паузу")
        S.break_task = asyncio.create_task(break_timer())
        S.pause_stop = threading.Event()  # надпись с отсчётом на экране + all talk, как на FACEIT
        asyncio.create_task(asyncio.to_thread(
            rcon_pause_overlay, lambda: ", ".join(S.absent_names.values()) or "?", BREAK_SECONDS, S.pause_stop))

    guild = get_guild()
    async with S.break_lock:
        if S.break_channel is None and guild:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            }
            for m, _ in S.match_players.values():
                overwrites[m] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True)
            try:
                S.break_channel = await guild.create_text_channel(
                    f"перерыв-матч-{S.match_id}",
                    overwrites=overwrites,
                    category=S.panel.channel.category if S.panel else None,
                    reason="FreePick: перерыв из-за вышедшего игрока")
            except discord.HTTPException:
                log.exception("Не удалось создать чат перерыва (нужно право Manage Channels)")
        target = S.break_channel or (S.panel.channel if S.panel else None)

    if target:
        names = ", ".join(m.mention for m, _ in S.match_players.values() if m.id in S.absent)
        await target.send(
            f"⏸ **Матч #{S.match_id} на паузе.** Вышел с сервера: {names} (Team {team_n}).\n"
            f"Игрок, вернитесь на сервер: {WEB_BASE_URL}/connect\n"
            f"Если игрок не вернётся за {_fmt_mmss(BREAK_SECONDS)}, матч продолжится автоматически. "
            "Капитаны и администрация могут продолжить раньше кнопкой ниже.",
            view=BreakView())
    try:
        await member.send(f"⏸ Вы вышли с сервера, матч #{S.match_id} стоит на паузе. "
                          f"Возвращайтесь: {WEB_BASE_URL}/connect")
    except discord.HTTPException:
        pass


async def handle_return(data: dict):
    """Игрок вернулся на сервер во время паузы: он больше не считается вышедшим."""
    player = data.get("player") or {}
    info = S.match_players.get(str(player.get("steamid", "")))
    if not info or not S.paused:
        return
    S.absent.discard(info[0].id)
    S.absent_names.pop(info[0].id, None)
    if not S.absent:
        await resume_match("Все игроки вернулись на сервер")


# SteamID, которым можно заходить на сервер во время матча без привязки (админы, комментаторы), через запятую
ADMIN_STEAMIDS = {x.strip() for x in os.getenv("ADMIN_STEAMIDS", "").split(",") if x.strip()}


async def handle_connect(data: dict):
    """Игрок зашёл на сервер: если его Steam-аккаунта нет в матче (зашёл с другого аккаунта), кикаем."""
    player = data.get("player") or {}
    if player.get("is_bot"):
        return
    sid = str(player.get("steamid", ""))
    if not sid or sid == "0" or sid in S.match_players or sid in ADMIN_STEAMIDS:
        return
    try:
        await asyncio.to_thread(rcon_kick, player.get("user_id"), sid)
    except Exception:
        log.exception("Не удалось кикнуть %s", sid)
        return
    log.warning("Кикнут игрок %s (%s): аккаунта нет в матче", player.get("name"), sid)
    owner = db.execute("SELECT discord_id FROM links WHERE steamid64=?", (sid,)).fetchone()
    who = f" (привязан к <@{owner[0]}>)" if owner else " (аккаунт не привязан к Discord)"
    ch = S.match_channel or (S.panel.channel if S.panel else None)
    if ch:
        try:
            await ch.send(f"🚫 Игрок **{player.get('name', '?')}** (`{sid}`){who} зашёл с аккаунта, которого нет "
                          f"в матче, и был кикнут. Заходите только с привязанного Steam: {WEB_BASE_URL}/connect",
                          delete_after=60, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            pass


# ----------------------------- АВТОСТАРТ -----------------------------
async def wait_loaded(match_id: int):
    """Ждёт до 30 сек, пока сервер не покажет наш matchid (после loadmatch сервер может менять карту).
    Возвращает (True/False, описание). Если get5_status не распознан, матч не блокируем."""
    info = "нет ответа от сервера"
    for _ in range(15):
        await asyncio.sleep(2)
        try:
            raw = await asyncio.to_thread(rcon_raw, "get5_status")
        except Exception as exc:  # во время смены карты RCON может быть недоступен
            info = type(exc).__name__
            continue
        st = re.search(r'"gamestate"\s*:\s*"(\w+)"', raw)
        mi = re.search(r'"matchid"\s*:\s*"?(\w+)"?', raw)
        if not st and not mi:
            return True, "get5_status не распознан"
        if mi and mi.group(1) == str(match_id) and st and st.group(1) != "none":
            return True, ""
        info = f"gamestate={st.group(1) if st else '?'}, matchid={mi.group(1) if mi else '?'}"
    return False, info


async def verify_load(match_id: int, load_resp: str):
    """Через 8 сек спрашивает у сервера, загрузился ли матч. Если нет, пишет причину в чат матча."""
    await asyncio.sleep(8)
    if S.phase != "playing" or S.match_id != match_id:
        return
    try:
        raw = await asyncio.to_thread(rcon_raw, "get5_status")
    except Exception as exc:
        raw = f"{type(exc).__name__}: {exc}"
    st = re.search(r'"gamestate"\s*:\s*"(\w+)"', raw)
    mi = re.search(r'"matchid"\s*:\s*"?(\w+)"?', raw)
    state, loaded = (st.group(1) if st else None), (mi.group(1) if mi else None)
    log.info("Проверка загрузки матча %s: gamestate=%s, matchid на сервере=%s", match_id, state, loaded)
    if state not in (None, "none") and loaded == str(match_id):
        return
    ch = match_chat()
    if ch:
        try:
            await ch.send(f"⚠ Сервер не загрузил матч #{match_id} (gamestate: `{state}`, matchid на сервере: `{loaded}`).\n"
                          f"Ответ на loadmatch: `{(load_resp or '—').strip()[:200]}`\n"
                          "Проверьте, что карта есть на сервере, и откройте ссылку матча в браузере: "
                          f"{WEB_BASE_URL}/match/{match_id}.json")
        except discord.HTTPException:
            pass


STARTED_STATES = {"knife", "waiting_for_knife_decision", "going_live", "live", "pending_restore"}


def match_chat():
    return S.match_channel or (S.panel.channel if S.panel else None)


async def force_start(match_id: int, reason: str) -> bool:
    """Принудительно стартует матч (без .ready). True = матч стартовал (или уже идёт)."""
    if S.phase != "playing" or S.match_id != match_id or S.live or S.auto_started:
        return True
    S.auto_started = True
    ch = match_chat()
    if ch:
        try:
            await ch.send(f"✅ {reason}. Матч стартует, писать .ready не нужно.", delete_after=60)
        except discord.HTTPException:
            pass
    resp = resp2 = ""
    state = None
    failed = False
    try:
        state0 = await asyncio.to_thread(rcon_gamestate)
        if state0 in STARTED_STATES:  # матч уже идёт
            S.ever_live = True
            return True
        resp = await asyncio.to_thread(rcon_force_start)
        await asyncio.sleep(6)
        state = await asyncio.to_thread(rcon_gamestate)
        if state is not None and state not in STARTED_STATES:  # css_start не помог: пробуем forceready
            resp2 = await asyncio.to_thread(rcon_force_ready)
            await asyncio.sleep(6)
            state = await asyncio.to_thread(rcon_gamestate)
        log.info("Автостарт матча %s: состояние %s, css_start=%r, css_forceready=%r",
                 match_id, state, resp[:200], resp2[:200])
    except Exception as exc:
        failed = True
        resp = f"{type(exc).__name__}: {exc}"
        log.exception("Не удалось автоматически стартовать матч")
    if not failed and (state in STARTED_STATES or state is None):
        if state in STARTED_STATES:
            S.ever_live = True
        return True
    S.auto_started = False
    if ch:
        try:
            await ch.send(f"⚠ Автостарт не сработал. Состояние матча на сервере: `{state}`.\n"
                          f"Ответ css_start: `{resp[:150] or '—'}`\nОтвет css_forceready: `{resp2[:150] or '—'}`\n"
                          "Админ может нажать /fp_start или проверить сервер командой /fp_diag.",
                          delete_after=180)
        except discord.HTTPException:
            pass
    return False


async def track_connect(data: dict):
    """Игрок зашёл на сервер: если на сервере уже все игроки матча, запускаем автостарт."""
    player = data.get("player") or {}
    sid = str(player.get("steamid", ""))
    if player.get("is_bot") or sid not in S.match_players:
        return
    S.connected.add(sid)
    log.info("На сервере %s из %s игроков матча", len(S.connected), len(S.match_players))
    if AUTO_START and not S.auto_started and not S.live and len(S.connected) >= len(S.match_players):
        mid = S.match_id
        await asyncio.sleep(AUTO_START_DELAY)  # даём всем догрузиться
        if S.match_id == mid and len(S.connected) >= len(S.match_players):
            await force_start(mid, "Все игроки на сервере")


async def warmup_timer(match_id: int):
    """Каждые 3 сек спрашивает у сервера (RCON status), кто на нём сидит, и не зависит от событий MatchZy.
    Все игроки на сервере -> старт через AUTO_START_DELAY. Иначе через WARMUP_SECONDS после первого входа."""
    t0 = None          # когда зашёл первый игрок
    full_since = None  # когда на сервере стали все
    tries = 0
    reported = set()
    said = set()
    first = True
    warned_events = False
    while S.phase == "playing" and S.match_id == match_id and not S.live and not S.auto_started:
        await asyncio.sleep(3)
        try:
            present, humans = await asyncio.to_thread(rcon_players)
        except Exception as exc:
            msg = f"{type(exc).__name__}: {exc}"
            log.warning("RCON status не удался: %s", msg)
            if msg not in reported:  # сообщаем в чат матча один раз для каждой ошибки
                reported.add(msg)
                ch = match_chat()
                if ch:
                    try:
                        await ch.send(f"⚠ Бот не может связаться с CS2-сервером по RCON (`{msg}`). "
                                      "Проверьте RCON_PASSWORD, SERVER_IP и SERVER_PORT в Render.",
                                      delete_after=300)
                    except discord.HTTPException:
                        pass
            continue
        S.connected = {sid for sid in S.match_players if sid in present}
        if first:
            first = False
            log.info("RCON status: людей на сервере %s (SteamID в status: %s)", humans, len(present))
        need = len(S.match_players)
        n_here = max(len(S.connected), humans)  # сколько людей на сервере
        if n_here and t0 is None:
            t0 = time.time()
        if t0 and not warned_events and time.time() - t0 >= 30 and match_id not in events_seen:
            warned_events = True
            wch = match_chat()
            if wch:
                try:
                    await wch.send("⚠ От сервера не приходят события MatchZy: результат и демо автоматически не появятся. "
                                   "Админу: проверьте /fp_diag (matchzy_remote_log_url) и что "
                                   f"{WEB_BASE_URL}/events доступен с CS2-сервера.", delete_after=300)
                except discord.HTTPException:
                    pass
        reason = None
        if AUTO_START and need and n_here >= need:
            if full_since is None:
                full_since = time.time()
                log.info("Все %s игроков на сервере, старт через %s сек", need, AUTO_START_DELAY)
                try:  # сообщение прямо в игру
                    await asyncio.to_thread(rcon_raw, f"say Все игроки на сервере. Матч начнётся через {AUTO_START_DELAY} сек")
                except Exception:
                    pass
            elif time.time() - full_since >= AUTO_START_DELAY:
                reason = "Все игроки на сервере"
            if full_since is not None:  # обратный отсчёт в чат игры
                left = AUTO_START_DELAY - (time.time() - full_since)
                for mark in (10, 5):
                    if left <= mark and mark not in said:
                        said.add(mark)
                        try:
                            await asyncio.to_thread(rcon_raw, f"say Матч начнётся через {mark} сек")
                        except Exception:
                            pass
        else:
            full_since = None
            said.clear()
        if not reason and t0 and time.time() - t0 >= WARMUP_SECONDS:
            reason = "Разминка закончилась"
        if reason:
            if await force_start(match_id, reason):
                return
            tries += 1
            if tries >= 3:
                return
            full_since = None
            await asyncio.sleep(20)


async def break_timer():
    await asyncio.sleep(BREAK_SECONDS)
    if S.paused:
        await resume_match("Время ожидания вышло, матч продолжается")


async def resume_match(reason: str):
    """Снимает паузу и закрывает чат перерыва."""
    if not S.paused:
        return
    leavers = [m for m, _ in S.match_players.values() if m.id in S.absent]  # кто так и не вернулся
    S.paused = False
    S.absent.clear()
    S.absent_names.clear()
    if S.pause_stop:
        S.pause_stop.set()  # убрать надпись и вернуть all talk
        S.pause_stop = None
    if S.break_task and S.break_task is not asyncio.current_task():
        S.break_task.cancel()
    S.break_task = None
    try:
        await asyncio.to_thread(rcon_pause, False)
    except Exception:
        log.exception("Не удалось снять паузу")
    ch = S.break_channel or (S.panel.channel if S.panel else None)
    if ch:
        try:
            await ch.send(f"▶️ {reason}. Пауза снята. Этот чат закроется через 30 секунд.")
        except discord.HTTPException:
            pass
    asyncio.create_task(close_break(delay=30))
    for m in leavers:  # авто-бан за выход из матча
        await auto_ban(m, "leave", LEAVE_REASON)


async def close_break(delay: int = 0):
    """Удаляет отдельный чат перерыва."""
    if delay:
        await asyncio.sleep(delay)
    if S.break_task and S.break_task is not asyncio.current_task():
        S.break_task.cancel()
        S.break_task = None
    ch, S.break_channel = S.break_channel, None
    if ch:
        try:
            await ch.delete(reason="FreePick: перерыв закончен")
        except discord.HTTPException:
            pass


async def notify_players(teams, map_name: str, match_id: int):
    """Личное сообщение каждому игроку: его команда и Steam-аккаунт, с которого нужно зайти."""
    for n, team in enumerate(teams, 1):
        for m in team:
            sid = get_steam(m.id)
            text = (
                f"🎮 **Матч #{match_id}** ({pretty(map_name)}). Вы в **Team {n}**.\n"
                f"Заходите на сервер **только с Steam-аккаунта, который привязан к вам**: "
                f"https://steamcommunity.com/profiles/{sid}\n"
                "Команда и сторона выдаются автоматически именно по этому аккаунту. "
                "С другого аккаунта вы не попадёте в свою команду.\n"
                f"Подключиться: {WEB_BASE_URL}/connect"
            )
            try:
                await m.send(text)
            except discord.HTTPException:
                pass  # ЛС закрыты


async def track_send(channel, *args, **kwargs) -> discord.Message:
    """Отправляет сообщение и запоминает его, чтобы удалить при сбросе матча."""
    msg = await channel.send(*args, **kwargs)
    S.chat_msgs.append(msg)
    return msg


async def clear_chat():
    """Удаляет сообщения драфта и матча из чата (все сразу)."""
    msgs, S.chat_msgs = S.chat_msgs, []
    await asyncio.gather(*(m.delete() for m in msgs), return_exceptions=True)


async def reset_to_queue(kick_delay: int = KICK_DELAY):
    # если сервер не прислал результат (ручной сброс, таймер), пишем итог, но только если матч реально стартовал
    if S.match_id and S.phase == "playing" and S.match_id not in posted_results and S.ever_live:
        try:  # завершаем матч на сервере: он выгрузит демо и пришлёт последние события
            await asyncio.to_thread(rcon_raw, "get5_endmatch")
        except Exception:
            log.exception("get5_endmatch не удался")
        await asyncio.sleep(3)  # даём серверу прислать последние события
        if S.match_id not in posted_results:  # map_result мог прийти за эти секунды
            await post_fallback_result(S.match_id, dict(S.match_players))
    # матч окончен: кикаем всех игроков матча с CS2-сервера (сразу при отмене, иначе через KICK_DELAY)
    if S.phase == "playing" and S.match_players:
        targets = [user_ids.get(sid) or sid for sid in S.match_players if sid not in ADMIN_STEAMIDS]
        asyncio.create_task(kick_everyone(targets, kick_delay))
    await asyncio.gather(clear_voice_access(), clear_chat(), close_match_chat(), close_break(),
                         return_exceptions=True)
    S.live = False
    S.ever_live = False
    S.paused = False
    S.absent.clear()
    S.absent_names.clear()
    S.cancel_votes = set()
    if S.pause_stop:
        S.pause_stop.set()
        S.pause_stop = None
    S.match_players = {}
    S.captain_ids = set()
    S.connected = set()
    S.auto_started = False
    S.moving = False
    S.stage = False  # панель снова обновляется как обычно
    async with S.lock:
        S.phase = "queue"
        S.queue.clear()
        S.match_id = None
        S.active_ids.clear()
        S.draft_task = None
    await sync_queue()
    await refresh_panel()


async def sync_queue():
    """Очередь = те, кто сидит в голосовом канале очереди. Когда набралось NEED игроков — авто-старт."""
    if not QUEUE_VC:
        return
    ch = bot.get_channel(QUEUE_VC)
    if not ch:
        return
    players = None
    # куда писать, если панели нет (например, после обновления бота): в текстовый чат самого войса очереди
    origin = S.panel.channel if S.panel else ch
    async with S.lock:
        if S.phase != "queue":
            return
        present = [m for m in ch.members
                   if not m.bot and not is_banned(m.id) and get_steam(m.id)]
        ids = {m.id for m in present}
        keep = [m for m in S.queue if m.id in ids]
        kept = {m.id for m in keep}
        S.queue = keep + [m for m in present if m.id not in kept]
        log.info("Очередь: %s из %s (в войсе %s)", len(S.queue), NEED, len(ch.members))
        if len(S.queue) >= NEED:
            S.queue = S.queue[:NEED]
            S.phase = "draft"  # АВТО-СТАРТ: очередь полная
            players = list(S.queue)
    await refresh_panel()
    if players:
        log.info("Авто-старт: набрано %s игроков", len(players))
        asyncio.create_task(run_match(origin, players))


async def check_draft_empty():
    """Во время драфта: если все игроки вышли из войса очереди, драфт отменяется и очередь сбрасывается."""
    if S.draft_check or S.moving:
        return
    S.draft_check = True
    try:
        await asyncio.sleep(5)  # даём шанс переподключиться
        if S.phase != "draft" or not QUEUE_VC or S.moving:
            return
        ch = bot.get_channel(QUEUE_VC)
        if not ch or any(m.id in S.active_ids for m in ch.members):
            return
        log.warning("Все игроки вышли из войса очереди во время драфта: сброс")
        task = S.draft_task
        if task and not task.done() and task is not asyncio.current_task():
            task.cancel()
        if S.panel:
            try:
                await S.panel.channel.send("⚠ Все игроки вышли из войса, драфт отменён. Очередь сброшена.",
                                           delete_after=30)
            except discord.HTTPException:
                pass
        await reset_to_queue()
    finally:
        S.draft_check = False


async def watch_match(match_id: int):
    """Страховка: если событие series_end не дошло до бота, узнаём у сервера, что матч закончился."""
    await asyncio.sleep(90)
    active = {"warmup", "pre_veto", "veto", "knife", "waiting_for_knife_decision",
              "going_live", "live", "pending_restore"}
    seen_active = False
    ended = 0
    while S.phase == "playing" and S.match_id == match_id:
        try:
            state = await asyncio.to_thread(rcon_gamestate)
        except Exception:
            state = None
        if state in active:
            seen_active = True
            ended = 0
            if state in STARTED_STATES:
                S.ever_live = True  # матч реально идёт, даже если события MatchZy не доходят до бота
        elif state == "post_game" or (state == "none" and seen_active):
            ended += 1
        else:
            ended = 0
        if ended >= 3:  # три проверки подряд (около минуты)
            log.warning("Матч %s завершён по данным get5_status (%s)", match_id, state)
            await reset_to_queue()
            return
        await asyncio.sleep(20)


async def auto_reset(match_id: int):
    """Страховка: если series_end не пришёл, сбрасываем матч по таймеру."""
    await asyncio.sleep(MATCH_MAX_SECONDS)
    if S.phase == "playing" and S.match_id == match_id:
        log.warning("Матч %s сброшен по таймеру", match_id)
        await reset_to_queue()


async def draft(msg: discord.Message, players):
    """Капитаны, пики и вето идут в ОДНОМ сообщении (панель очереди), оно обновляется на каждом шаге."""
    no = next_match_no()
    caps = await choose_captains(msg, no, players)  # капитаны вызываются сами
    pool = [m for m in players if m not in caps]
    teams = [[caps[0]], [caps[1]]]

    # ---- пики игроков ----
    turn, last = 0, ""
    while len(pool) > 1:
        cap = caps[turn]
        view = PickView(cap, pool)
        await msg.edit(embed=draft_embed(no, teams, pool, cap, last=last), view=view)
        await view.wait()
        picked = view.picked or random.choice(pool)  # не успел: случайный игрок
        pool.remove(picked)
        teams[turn].append(picked)
        last = f"{cap.display_name} выбрал {picked.display_name}"
        turn ^= 1
    teams[turn].append(pool[0])  # последний игрок достаётся автоматически
    await msg.edit(embed=draft_embed(no, teams, [], done=True, last=last), view=None)

    # ---- вето карт ----
    maps, banned_list, turn, last = MAPS.copy(), [], 0, ""
    while len(maps) > 1:
        cap = caps[turn]
        view = VetoView(cap, maps)
        await msg.edit(embed=veto_embed(no, maps, banned_list, cap, last=last), view=view)
        await view.wait()
        banned = view.banned or random.choice(maps)
        maps.remove(banned)
        banned_list.append((banned, cap))
        last = f"{cap.display_name} забанил карту {pretty(banned)}"
        turn ^= 1
    map_name = maps[0]
    await msg.edit(embed=veto_embed(no, maps, banned_list, final=map_name, last=last), view=None)
    return teams, map_name, no


async def run_match(channel: discord.abc.Messageable, players: list[discord.Member]):
    origin = channel  # общий канал очереди
    S.draft_task = asyncio.current_task()  # чтобы драфт можно было отменить, если все вышли из войса
    try:
        S.active_ids = {m.id for m in players}
        if not TEST_MODE and not await ready_check(channel, players):
            return  # не все нажали «Готов»: очередь уже сброшена внутри ready_check

        # ---- всё табло в ОДНОМ сообщении: панель очереди ----
        pmsg = S.panel
        if pmsg is None:
            pmsg = await origin.send(embed=discord.Embed(title="Очередь — FreePick"))
            S.panel = pmsg
        S.stage = True  # пока идёт драфт и запуск, панель обновляет только драфт
        if TEST_MODE:
            teams, map_name, no = [players[:1], []], random.choice(MAPS), next_match_no()
        else:
            teams, map_name, no = await draft(pmsg, players)

        # ---- этап «создаю каналы команд и запускаю сервер» ----
        S.moving = True
        await pmsg.edit(embed=launch_embed(no, teams, "⏳ Создаю каналы команд и запускаю CS2-сервер..."), view=None)
        if getattr(origin, "guild", None):
            await move_to_voice(origin.guild, teams)  # войсы команд + перемещение игроков

        match_id = int(time.time())
        S.matches[match_id] = build_match(match_id, teams, map_name)
        S.match_players = {get_steam(m.id): (m, n) for n, t in enumerate(teams, 1) for m in t}
        S.captain_ids = {t[0].id for t in teams if t}
        snapshots[match_id] = dict(S.match_players)
        captains[match_id] = {n: t[0] for n, t in enumerate(teams, 1) if t}  # капитаны команд для табло результата
        live_stats.pop(match_id, None)
        live_reset.discard(match_id)
        user_ids.clear()  # userid игроков прошлого матча больше не нужны
        S.live = False
        S.ever_live = False
        S.match_id = match_id
        S.cancel_votes = set()
        S.connected = set()
        S.auto_started = False

        await pmsg.edit(embed=launch_embed(no, teams, f"⏳ Поднимаю карту **{pretty(map_name)}**..."), view=None)
        load_resp = await asyncio.to_thread(load_on_server, match_id, map_name)
        log.info("Ответ сервера на loadmatch: %r", (load_resp or "")[:300])

        # честная проверка: если сервер матч не принял, не говорим «Матч готов»
        loaded, info = await wait_loaded(match_id)
        if not loaded:
            raise RuntimeError(f"сервер не загрузил матч ({info}). Ответ: {(load_resp or '—').strip()[:150]}")
        cur = ""
        try:  # события и демо: ставим заново после загрузки матча
            cur = await asyncio.to_thread(set_event_cvars)
            log.info("matchzy_remote_log_url после загрузки матча: %r", cur.strip()[:200])
        except Exception:
            log.exception("Не удалось повторно задать адрес событий MatchZy")

        # ---- отдельный чат матча: ТОЛЬКО карточка с connect ----
        chat = await open_match_chat(origin, players)
        target = chat or origin
        if "НЕИЗВЕСТНО" in cur:
            try:
                await target.send("⚠ CS2-сервер не знает команды MatchZy для событий/демо "
                                  f"(`{cur.split('НЕИЗВЕСТНО:')[1].strip()[:150]}`). "
                                  "Результат и демо автоматически не придут: обновите MatchZy на сервере.",
                                  delete_after=300)
            except discord.HTTPException:
                pass

        S.phase = "playing"
        S.moving = False
        S.stage = False
        S.queue.clear()
        await refresh_panel()  # панель возвращается в обычный вид: «Матч идёт»
        asyncio.create_task(auto_reset(match_id))
        asyncio.create_task(watch_match(match_id))
        asyncio.create_task(warmup_timer(match_id))
        asyncio.create_task(verify_load(match_id, load_resp))
        asyncio.create_task(ensure_map_image(map_name))  # заранее готовим картинку карты для табло результата

        connect = f"connect {SERVER_IP}:{SERVER_PORT}"
        if SERVER_PASSWORD:
            connect += f"; password {SERVER_PASSWORD}"
        e = discord.Embed(title=f"Матч #{match_id} готов — {pretty(map_name)}", color=0x2B2D31)
        for n, t in enumerate(teams, 1):
            e.add_field(name=f"Team {n}" + (f" ({t[0].display_name})" if t else ""),
                        value="\n".join(m.mention for m in t) or "—")
        e.add_field(name="Подключение (консоль CS2)", value=f"```{connect}```", inline=False)
        await track_send(target, embed=e, view=MatchView())
        asyncio.create_task(notify_players(teams, map_name, match_id))

    except Exception as exc:  # любая ошибка: возвращаем систему в очередь
        log.exception("Ошибка при запуске матча")
        try:
            await origin.send(f"❌ Не удалось запустить матч: `{exc}`\nОчередь сброшена, зайдите в войс очереди заново.")
        except discord.HTTPException:
            pass
        await reset_to_queue()


# ----------------------------- КАРТОЧКА РЕЗУЛЬТАТА -------------------
FONT_DIR = "fonts"
FONT_URLS = {
    "bold": "https://raw.githubusercontent.com/dejavu-fonts/dejavu-fonts/master/ttf/DejaVuSans-Bold.ttf",
    "regular": "https://raw.githubusercontent.com/dejavu-fonts/dejavu-fonts/master/ttf/DejaVuSans.ttf",
}
FONT_SYSTEM = {
    "bold": ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
             "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
             "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
             "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
             "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"],
    "regular": ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/TTF/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"],
}


def _find_font(kind: str):
    env = os.getenv("FONT_PATH_BOLD" if kind == "bold" else "FONT_PATH", "")
    for path in [env, f"{FONT_DIR}/{kind}.ttf", *FONT_SYSTEM[kind]]:
        if path and os.path.exists(path):
            return path
    return None


def get_font(size: int, kind: str = "bold"):
    from PIL import ImageFont
    path = _find_font(kind)
    if path:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


async def ensure_fonts():
    """Если на хостинге нет шрифта с кириллицей, скачиваем DejaVu один раз."""
    os.makedirs(FONT_DIR, exist_ok=True)
    for kind, url in FONT_URLS.items():
        if _find_font(kind):
            continue
        try:
            async with aiohttp.ClientSession() as ses:
                async with ses.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
                    if r.status == 200:
                        with open(f"{FONT_DIR}/{kind}.ttf", "wb") as f:
                            f.write(await r.read())
                        log.info("Шрифт %s скачан", kind)
        except Exception:
            log.warning("Не удалось скачать шрифт %s (задай FONT_PATH / FONT_PATH_BOLD)", kind)


# ---- картинки карт для фона табло
def find_map_image(map_name: str):
    for ext in ("png", "jpg", "jpeg", "webp"):
        path = os.path.join(MAP_DIR, f"{map_name}.{ext}")
        if os.path.exists(path):
            return path
    return None


async def ensure_map_image(map_name: str):
    """Возвращает путь к картинке карты. Если её нет в папке maps/, скачивает из открытых репозиториев."""
    path = find_map_image(map_name)
    if path or not map_name or map_name == "?":
        return path
    os.makedirs(MAP_DIR, exist_ok=True)
    for tpl in MAP_IMAGE_URLS:
        url = tpl.format(map=map_name)
        try:
            async with aiohttp.ClientSession() as ses:
                async with ses.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
                    if r.status != 200:
                        continue
                    body = await r.read()
            if len(body) > 8_000_000 or not (body.startswith(b"\x89PNG") or body.startswith(b"\xff\xd8")):
                continue  # это не картинка
            ext = "png" if body.startswith(b"\x89PNG") else "jpg"
            path = os.path.join(MAP_DIR, f"{map_name}.{ext}")
            with open(path, "wb") as f:
                f.write(body)
            log.info("Картинка карты %s скачана: %s", map_name, url)
            return path
        except Exception:
            log.warning("Не удалось скачать картинку карты %s с %s", map_name, url)
    log.warning("Картинка карты %s не найдена: положите её в папку %s/ (например %s.png)", map_name, MAP_DIR, map_name)
    return None


async def prefetch_map_images():
    for m in MAPS:
        await ensure_map_image(m)


def render_result_card(map_name: str, s1, s2, team_rows: dict, has_stats: bool,
                       center: dict | None, names: tuple) -> bytes:
    """Рисует картинку-табло матча на фоне картинки карты. У каждого игрока три колонки: K (убийства), D (смерти), K/D.
    В центре: аватар и ник MVP (больше всех убийств), надпись «MVP». В правом верхнем углу плашка сайта (SITE_URL).
    Блокирующая: вызывать через to_thread."""
    from PIL import Image, ImageDraw, ImageFilter, ImageEnhance

    W, H = 1300, 540
    BLUE, ORANGE, GOLD = (76, 142, 255), (255, 176, 32), (255, 205, 60)

    # --- фон: картинка карты (maps/de_xxx.png|jpg) или тёмный градиент
    bg = None
    path = find_map_image(map_name)
    if path:
        try:
            src = Image.open(path).convert("RGB")
            k = max(W / src.width, H / src.height)
            src = src.resize((int(src.width * k) + 1, int(src.height * k) + 1))
            l, t = (src.width - W) // 2, (src.height - H) // 2
            bg = src.crop((l, t, l + W, t + H)).filter(ImageFilter.GaussianBlur(2))
            bg = ImageEnhance.Brightness(bg).enhance(0.62)
        except Exception:
            bg = None
    if bg is None:
        bg = Image.new("RGB", (W, H))
        px = ImageDraw.Draw(bg)
        for y in range(H):
            f = y / H
            px.line([(0, y), (W, y)], fill=(int(22 - 12 * f), int(28 - 14 * f), int(48 - 24 * f)))
    img = bg.convert("RGBA")
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)

    PW, PY0, PY1 = 480, 40, 500
    panels = {1: 30, 2: W - 30 - PW}
    colors = {1: BLUE, 2: ORANGE}
    for n, x0 in panels.items():
        od.rounded_rectangle((x0, PY0, x0 + PW, PY1), 18, fill=(8, 12, 26, 175), outline=colors[n] + (170,), width=2)
        od.rounded_rectangle((x0 + 90, PY0 + 12, x0 + PW - 90, PY0 + 56), 10, fill=(6, 10, 22, 225),
                             outline=colors[n] + (255,), width=2)
    img = Image.alpha_composite(img, ov)
    d = ImageDraw.Draw(img)

    f_head, f_name, f_stat, f_lab = get_font(26), get_font(24), get_font(23), get_font(17)
    gray, white = (210, 215, 228), (245, 247, 252)
    GOOD, BAD = (110, 225, 140), (255, 120, 120)
    COLS = (170, 105, 22)  # правый край колонок K, D, K/D (отступ от правого края панели)

    def fit(text: str, font, max_w: int) -> str:
        if d.textlength(text, font=font) <= max_w:
            return text
        while text and d.textlength(text + "…", font=font) > max_w:
            text = text[:-1]
        return text + "…"

    for n, x0 in panels.items():
        col = colors[n]
        d.text((x0 + PW // 2, PY0 + 34), names[n - 1], font=f_head, fill=col, anchor="mm")
        for dx, lab in zip(COLS, ("K", "D", "K/D")):  # подписи колонок
            d.text((x0 + PW - dx, PY0 + 76), lab, font=f_lab, fill=col, anchor="rm")
        y = PY0 + 90
        for r in team_rows.get(n, [])[:5]:
            cy = y + 32
            d.ellipse((x0 + 22, cy - 8, x0 + 38, cy + 8), fill=col)
            d.text((x0 + 52, cy), fit(r["name"], f_name, 200), font=f_name, fill=white, anchor="lm")
            if not has_stats:  # статистики нет: прочерки
                for dx in COLS:
                    d.text((x0 + PW - dx, cy), "–", font=f_stat, fill=gray, anchor="rm")
            else:
                kd = r["k"] / r["d"] if r["d"] else float(r["k"])
                d.text((x0 + PW - COLS[0], cy), str(r["k"]), font=f_stat, fill=white, anchor="rm")
                d.text((x0 + PW - COLS[1], cy), str(r["d"]), font=f_stat, fill=gray, anchor="rm")
                d.text((x0 + PW - COLS[2], cy), f"{kd:.2f}", font=f_stat, fill=GOOD if kd >= 1 else BAD, anchor="rm")
            d.line((x0 + 18, y + 66, x0 + PW - 18, y + 66), fill=(70, 80, 106), width=1)
            y += 70

    # --- центр: аватар MVP (или игрока победившей команды), «MVP», его ник, счёт, карта
    cx = W // 2
    R = 78
    ring = Image.new("RGBA", (2 * R + 12, 2 * R + 12), (0, 0, 0, 0))
    rd = ImageDraw.Draw(ring)
    rd.ellipse((0, 0, 2 * R + 11, 2 * R + 11), fill=GOLD + (255,))
    av = None
    if center and center.get("avatar"):
        try:
            av = Image.open(io.BytesIO(center["avatar"])).convert("RGBA").resize((2 * R, 2 * R))
        except Exception:
            av = None
    if av is None:
        av = Image.new("RGBA", (2 * R, 2 * R), (40, 48, 72, 255))
        ImageDraw.Draw(av).text((R, R), ((center["name"][:1] if center else "") or "?").upper(),
                                font=get_font(70), fill=white, anchor="mm")
    mask = Image.new("L", (2 * R, 2 * R), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, 2 * R - 1, 2 * R - 1), fill=255)
    ring.paste(av, (6, 6), mask)
    img.alpha_composite(ring, (cx - R - 6, 62))
    d = ImageDraw.Draw(img)
    d.text((cx, 258), "MVP" if center else "ИТОГ", font=get_font(50), fill=GOLD, anchor="mm")
    d.text((cx, 304), fit(center["name"] if center else "Матч завершён", get_font(24), 250),
           font=get_font(24), fill=white, anchor="mm")
    if center and "k" in center:  # убийства / смерти / K/D самого MVP под ником
        ckd = center["k"] / center["d"] if center["d"] else float(center["k"])
        d.text((cx, 336), f"{center['k']} / {center['d']}  ·  K/D {ckd:.2f}",
               font=get_font(20, "regular"), fill=gray, anchor="mm")
    f_score = get_font(72)
    d.text((cx - 78, 395), str(s1) if s1 is not None else "–", font=f_score, fill=BLUE, anchor="mm")
    d.text((cx, 395), "–", font=get_font(40), fill=gray, anchor="mm")
    d.text((cx + 78, 395), str(s2) if s2 is not None else "–", font=f_score, fill=ORANGE, anchor="mm")
    d.text((cx, 470), f"КАРТА: {map_name.replace('de_', '').upper()}", font=get_font(24), fill=gray, anchor="mm")

    # --- плашка сайта в правом верхнем углу (как «voin-cs.kz ↗»)
    if SITE_URL:
        label = SITE_URL.replace("https://", "").replace("http://", "").strip("/") + " ↗"
        f_site = get_font(17)
        tw = d.textlength(label, font=f_site)
        x1 = W - 30
        x0 = x1 - tw - 28
        d.rounded_rectangle((x0, 7, x1, 35), 8, fill=(30, 32, 38, 235), outline=(84, 88, 100, 255), width=1)
        d.text(((x0 + x1) / 2, 21), label, font=f_site, fill=white, anchor="mm")

    out = io.BytesIO()
    img.convert("RGB").save(out, "PNG")
    return out.getvalue()


# ----------------------------- РЕЗУЛЬТАТЫ МАТЧА ----------------------
def find_results_channel():
    g = get_guild()
    if not g:
        return None
    if RESULTS_CHANNEL:
        ch = g.get_channel(RESULTS_CHANNEL)
        if ch:
            return ch
    for ch in g.text_channels:
        if "результаты" in ch.name.lower():
            return ch
    return None


posted_results: set[int] = set()  # матчи, результат которых уже опубликован

# ---- демо матчей
demo_urls: dict[int, str] = {}                 # match_id -> ссылка на демо
result_msgs: dict[int, discord.Message] = {}   # match_id -> сообщение с результатом


def site_view() -> discord.ui.View:
    """Кнопка под результатом: ссылка на сайт."""
    v = discord.ui.View()
    v.add_item(discord.ui.Button(label="vibeproject.kz", emoji="🌐", url=SITE_URL))
    return v


def apply_elo(players: dict, win_n: int) -> dict:
    """Победителям +ELO_WIN (30), проигравшим -ELO_LOSS (20). Возвращает {discord_id: (было, стало)}."""
    teams = {1: [], 2: []}
    for m, n in players.values():
        teams[n].append(m.id)
    if not teams[1] and not teams[2]:
        return {}
    changes = {}
    for n, ids in teams.items():
        won = 1 if n == win_n else 0
        delta = ELO_WIN if won else -ELO_LOSS
        for i in ids:
            old = get_elo(i)
            new = max(ELO_MIN, old + delta)
            db.execute(
                "INSERT INTO elo (discord_id, elo, wins, losses) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(discord_id) DO UPDATE SET elo=?, wins=wins+?, losses=losses+?",
                (i, new, won, 1 - won, new, won, 1 - won))
            changes[i] = (old, new)
    db.commit()
    schedule_backup()
    return changes


async def post_result(data: dict, players: dict, match_id, note: str = ""):
    """Публикует итог матча в канале результатов: карточка-табло на фоне карты (в центре MVP, справа вверху плашка сайта).
    По умолчанию (RESULT_TEXT=1) над картинкой текст в стиле сайта: «Счёт | Победитель», MVP «ник — K/D/A | ADR | HS%»,
    ELO каждого игрока (стало и изменение) и ссылка «Скачать демку». Под сообщением кнопка «vibeproject.kz» (SITE_URL).
    Без картинки пишет простой список составов (с текущим ELO игроков).
    note: непустая строка = победитель неизвестен (ELO не меняется)."""
    try:
        mid = int(match_id)
    except (TypeError, ValueError):
        return
    if mid in posted_results:
        return
    posted_results.add(mid)  # ставим сразу, чтобы результат не ушёл дважды
    ch = find_results_channel()
    if not ch:
        log.warning("Канал результатов не найден (задай RESULTS_CHANNEL_ID)")
        posted_results.discard(mid)
        return
    # у map_result может не быть статистики игроков: берём её из последнего round_end
    if not _server_has_stats(data):
        lr = last_round.get(mid) or {}
        if _server_has_stats(lr):
            data = dict(data)
            for _n in ("team1", "team2"):
                _t = dict(data.get(_n) or {})
                _t["players"] = (lr.get(_n) or {}).get("players") or []
                if _t.get("score") is None:
                    _t["score"] = (lr.get(_n) or {}).get("score")
                data[_n] = _t
    data = build_from_tally(mid, players, data)  # если у сервера нет статистики игроков, берём свою (по player_death)
    t1, t2 = data.get("team1") or {}, data.get("team2") or {}
    s1, s2 = t1.get("score"), t2.get("score")
    win = (data.get("winner") or {}).get("team")
    cfg = S.matches.get(mid) or {}
    raw_map = (cfg.get("maplist") or ["?"])[0]
    total_rounds = (s1 or 0) + (s2 or 0)
    await ensure_map_image(raw_map)  # картинка карты для фона табло

    # ELO меняем только если известен победитель
    changes = {}
    if win in ("team1", "team2") and not note:
        changes = apply_elo(players, 1 if win == "team1" else 2)

    # --- строки статистики по командам
    team_rows = {}
    for n, t in ((1, t1), (2, t2)):
        rows = []
        for p in t.get("players") or []:
            st = p.get("stats") or {}
            info = players.get(str(p.get("steamid", "")))
            member = info[0] if info else None
            k, d, a = st.get("kills", 0), st.get("deaths", 0), st.get("assists", 0)
            rounds = st.get("rounds_played") or total_rounds or 1
            rows.append({
                "name": member.display_name if member else p.get("name", "?"),
                "member": member, "k": k, "d": d, "a": a,
                "adr": round(st.get("damage", 0) / rounds),
                "hs": round(st.get("headshot_kills", 0) * 100 / k) if k else 0,
                "tk": st.get("team_kills", 0) or 0,
            })
        rows.sort(key=lambda r: (-r["k"], -r["adr"]))
        team_rows[n] = rows
    all_rows = team_rows[1] + team_rows[2]
    save_match(mid, raw_map, s1, s2, win, team_rows, players)  # статистика для /profile и /match stat

    # --- MVP: игрок с наибольшим числом убийств (при равенстве: меньше смертей, потом выше ADR)
    mvp = max(all_rows, key=lambda r: (r["k"], -r["d"], r["adr"])) if all_rows else None
    if mvp and not (mvp["k"] or mvp["d"]):
        mvp = None  # статистики нет (все нули): MVP по убийствам не назначаем

    # --- центр табло: аватар и ник MVP
    center = None
    if mvp:
        mav = None
        if mvp["member"]:
            try:
                mav = await mvp["member"].display_avatar.replace(size=256, static_format="png").read()
            except discord.HTTPException:
                pass
        center = {"name": mvp["name"], "avatar": mav, "k": mvp["k"], "d": mvp["d"]}
    if not center:  # статистики нет: в центре игрок победившей команды (без цифр K/D)
        wn = {"team1": 1, "team2": 2}.get(win)
        cand = [m for m, tn in players.values() if wn and tn == wn]
        if cand:
            try:
                cav = await cand[0].display_avatar.replace(size=256, static_format="png").read()
            except discord.HTTPException:
                cav = None
            center = {"name": cand[0].display_name, "avatar": cav}

    # --- картинка-табло
    card = None
    card_rows = team_rows if all_rows else {
        n: [{"name": m.display_name, "member": m, "k": 0, "d": 0, "a": 0, "adr": 0, "hs": 0}
            for m, tn in players.values() if tn == n] for n in (1, 2)}
    if card_rows[1] or card_rows[2]:
        try:
            card = await asyncio.to_thread(render_result_card, raw_map, s1, s2, card_rows,
                                           bool(all_rows), center, ("TEAM A", "TEAM B"))
        except Exception:
            log.exception("Не удалось нарисовать карточку (установлен ли Pillow?)")

    if card:
        names = [(cfg.get(f"team{n}") or {}).get("name", f"Team {n}") for n in (1, 2)]
        lines = []
        if win in ("team1", "team2"):
            wn = 1 if win == "team1" else 2
            ws, ls = (s1, s2) if wn == 1 else (s2, s1)
            lines.append(f"**Счёт:** {ws} : {ls} | **Победитель:** 🏆 {names[wn - 1]}")
        elif s1 is not None and s2 is not None:
            lines.append(f"**Матч завершён** (Счёт: {s1} : {s2})")
        else:
            lines.append("**Матч завершён**")
        e = discord.Embed(title=f"Матч #{mid} завершён", description="\n".join(lines), color=0xF1C40F,
                          url=SITE_URL or None)
        if mvp:
            e.add_field(name="🏅 MVP",
                        value=f"{mvp['name']} — {mvp['k']}/{mvp['d']}/{mvp['a']} | {mvp['adr']} ADR | {mvp['hs']}% HS",
                        inline=False)
        if changes:  # ELO каждого игрока: стало (изменение)
            for n in (1, 2):
                part = []
                for m, tn in players.values():
                    if tn == n and m.id in changes:
                        old, new = changes[m.id]
                        part.append(f"{m.display_name}: **{new}** ({new - old:+d})")
                if part:
                    e.add_field(name=f"ELO — {names[n - 1]}"[:256], value="\n".join(part)[:1024], inline=True)
        e.add_field(name="Демо", value=f"[Скачать демку]({WEB_BASE_URL}/demo/{mid})", inline=False)
        e.set_image(url="attachment://result.png")
        if RESULT_TEXT:
            kwargs = {"embed": e, "file": discord.File(io.BytesIO(card), filename="result.png")}
        else:  # только картинка-табло
            kwargs = {"file": discord.File(io.BytesIO(card), filename="result.png")}
    else:
        # запасной вариант без картинки (нет статистики или Pillow не установлен)
        def elo_tag(did: int) -> str:
            if did in changes:
                old, new = changes[did]
                return f" · ELO {new} ({new - old:+d})"
            return f" · ELO {get_elo(did)}"  # изменения нет: показываем текущий рейтинг

        lines = []
        if s1 is not None and s2 is not None:
            lines.append(f"**Team 1  {s1} : {s2}  Team 2**")
        if win in ("team1", "team2"):
            lines.append("🏆 Победитель: **" + ("Team 1" if win == "team1" else "Team 2") + "**")
        e = discord.Embed(title=f"Результат матча #{mid} — {pretty(raw_map)}", color=0x57F287,
                          url=SITE_URL or None)
        e.description = "\n".join(lines) or "Матч завершён."
        for n in (1, 2):
            rows = [(r["k"], f"{r['member'].mention if r['member'] else r['name']}: "
                             f"**{r['k']}/{r['d']}/{r['a']}**"
                             + (f" · ADR {r['adr']}" if r["adr"] else "")
                             + f"{elo_tag(r['member'].id) if r['member'] else ''}")
                    for r in team_rows[n]]
            if not rows:  # статистики нет: показываем хотя бы состав команды
                rows = [(0, m.mention + elo_tag(m.id)) for m, tn in players.values() if tn == n]
            t = (t1, t2)[n - 1]
            title = f"Team {n}" + (f" ({t.get('score')})" if t.get("score") is not None else "")
            e.add_field(name=title, value="\n".join(r[1] for r in rows) or "—", inline=False)
        e.add_field(name="Демо", value=f"[Скачать демку]({WEB_BASE_URL}/demo/{mid})", inline=False)
        kwargs = {"embed": e}
    try:
        if SITE_URL:
            kwargs["view"] = site_view()  # кнопка «vibeproject.kz» под результатом
        msg = await ch.send(**kwargs)
        result_msgs[mid] = msg
        live_stats.pop(mid, None)  # убийства/смерти уже в результате
        log.info("Результат матча %s опубликован в #%s", mid, ch.name)
    except discord.HTTPException:
        posted_results.discard(mid)
        log.exception("Не удалось отправить результат (права бота: Send Messages, Embed Links, Attach Files)")


async def post_fallback_result(mid: int, players: dict):
    """map_result не пришёл: берём статистику из последнего round_end (а убийства/смерти при необходимости из
    player_death). Если событий нет совсем, спрашиваем счёт у сервера по RCON (get5_status).
    Победителем считается тот, кто ведёт по счёту: ELO начисляется (+30 / -20). При ничьей ELO не меняется."""
    data = dict(last_round.get(mid) or {})
    note = "manual"
    if not data:  # события не дошли: пробуем узнать счёт у самого сервера
        try:
            sc = await asyncio.to_thread(rcon_scores)
        except Exception:
            sc = None
        if sc and sc[0] is not None and sc[1] is not None:
            data = {"team1": {"score": sc[0]}, "team2": {"score": sc[1]}}
    if data:
        s1 = (data.get("team1") or {}).get("score") or 0
        s2 = (data.get("team2") or {}).get("score") or 0
        if s1 != s2:  # побеждает тот, кто ведёт по счёту (ничья: ELO не меняется)
            data["winner"] = {"team": "team1" if s1 > s2 else "team2"}
            note = ""
    await post_result(data, players, mid, note=note)


# ----------------------------- БАНЫ (лог в Discord + сайт) -----------
import html as _html

BAN_LOG_CHANNEL = int(os.getenv("BAN_LOG_CHANNEL_ID", "1566199370024620233"))  # 0 = канал, в названии которого есть "баны"

_UNITS = {"m": 60, "min": 60, "м": 60, "мин": 60, "минут": 60,
          "h": 3600, "ч": 3600, "час": 3600, "часа": 3600, "часов": 3600,
          "d": 86400, "д": 86400, "дн": 86400, "дня": 86400, "дней": 86400,
          "w": 604800, "н": 604800, "нед": 604800, "недели": 604800, "недель": 604800}


def parse_duration(text: str):
    """'30m', '12h', '3d', '1w', '1d12h', 'perm' -> секунды (0 = навсегда). Ошибка -> None."""
    t = (text or "").strip().lower()
    if t in ("", "perm", "permanent", "forever", "навсегда", "0"):
        return 0
    parts = re.findall(r"(\d+)\s*([a-zа-я]*)", t)
    if not parts or "".join(f"{n}{u}" for n, u in parts) != re.sub(r"\s+", "", t):
        return None
    total = 0
    for n, u in parts:
        mult = _UNITS.get(u or "d")  # число без буквы = дни
        if mult is None:
            return None
        total += int(n) * mult
    return total or None


def fmt_dur(sec: int) -> str:
    sec, parts = int(sec), []
    for name, n in (("д.", 86400), ("ч.", 3600), ("мин.", 60)):
        if sec >= n:
            parts.append(f"{sec // n} {name}")
            sec %= n
        if len(parts) == 2:
            break
    return " ".join(parts) or "1 мин."


def find_ban_channel():
    g = get_guild()
    if not g:
        return None
    if BAN_LOG_CHANNEL:
        ch = g.get_channel(BAN_LOG_CHANNEL)
        if ch:
            return ch
    for ch in g.text_channels:
        n = ch.name.lower()
        if "баны" in n or "bans" in n or "наказани" in n:
            return ch
    return None


class BanLogView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="Список банов", url=f"{WEB_BASE_URL}/bans"))

    @discord.ui.button(label="Посмотреть SteamID", style=discord.ButtonStyle.secondary,
                       custom_id="fp:banlog_steam")
    async def steam(self, i: discord.Interaction, b: discord.ui.Button):
        field = i.message.embeds[0].fields[0].value if i.message and i.message.embeds and i.message.embeds[0].fields else ""
        m = re.search(r"(\d{17,20})", field)
        if not m:
            return await i.response.send_message("Не удалось определить игрока.", ephemeral=True)
        did = int(m.group(1))
        sid = get_steam(did)
        if not sid:
            row = db.execute("SELECT steamid64 FROM ban_log WHERE discord_id=? AND steamid64 IS NOT NULL "
                             "ORDER BY id DESC LIMIT 1", (did,)).fetchone()
            sid = row[0] if row else None
        if not sid:
            return await i.response.send_message("У игрока нет привязанного Steam.", ephemeral=True)
        await i.response.send_message(f"SteamID: `{sid}`\nhttps://steamcommunity.com/profiles/{sid}",
                                      ephemeral=True)


async def send_ban_log(embed: discord.Embed):
    ch = find_ban_channel()
    if not ch:
        log.warning("Канал банов не найден (создай канал с «баны» в названии или задай BAN_LOG_CHANNEL_ID)")
        return
    try:
        await ch.send(embed=embed, view=BanLogView(), allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        log.exception("Не удалось отправить лог бана (права: Send Messages, Embed Links)")


async def do_ban(member: discord.Member, reason: str, duration: int, admin):
    now = int(time.time())
    expires = now + duration if duration else 0
    db.execute("UPDATE ban_log SET unbanned_at=?, unban_reason='Заменён новым баном', unban_by='Система' "
               "WHERE discord_id=? AND unbanned_at IS NULL", (now, member.id))
    db.execute("INSERT OR REPLACE INTO bans (discord_id, reason, expires) VALUES (?, ?, ?)",
               (member.id, reason, expires))
    db.execute("INSERT INTO ban_log (discord_id, steamid64, name, avatar, reason, admin_id, admin_name, "
               "created, expires) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
               (member.id, get_steam(member.id), member.display_name, member.display_avatar.url,
                reason, admin.id, admin.display_name, now, expires))
    db.commit()
    schedule_backup()
    async with S.lock:
        if S.phase == "queue":
            S.queue = [m for m in S.queue if m.id != member.id]
    if QUEUE_VC and member.voice and member.voice.channel and member.voice.channel.id == QUEUE_VC:
        try:
            await member.move_to(None)
        except discord.HTTPException:
            pass
    await refresh_panel()

    e = discord.Embed(title="🚫 Бан выдан", color=0xED4245, timestamp=discord.utils.utcnow())
    e.add_field(name="Игрок", value=f"<@{member.id}>\n`{member.id}`")
    e.add_field(name="Разбан", value=f"<t:{expires}:R>" if expires else "Никогда")
    e.add_field(name="Причина", value=reason[:1000])
    e.set_thumbnail(url=member.display_avatar.url)
    e.set_footer(text=f"Администратор: {admin.display_name} • {admin.id}")
    await send_ban_log(e)


async def do_unban(did: int, reason: str, by: str | None = None) -> bool:
    """by=None означает автоматический разбан по истечении срока."""
    if not db.execute("SELECT 1 FROM bans WHERE discord_id=?", (did,)).fetchone():
        return False
    now = int(time.time())
    db.execute("DELETE FROM bans WHERE discord_id=?", (did,))
    last = db.execute("SELECT id, avatar, reason, admin_id FROM ban_log WHERE discord_id=? "
                      "AND unbanned_at IS NULL ORDER BY id DESC LIMIT 1", (did,)).fetchone()
    if last:
        db.execute("UPDATE ban_log SET unbanned_at=?, unban_reason=?, unban_by=? WHERE id=?",
                   (now, reason, by or "Автоматически", last[0]))
    db.commit()
    schedule_backup()

    e = discord.Embed(title="✅ Бан снят", color=0x57F287, timestamp=discord.utils.utcnow())
    e.add_field(name="Игрок", value=f"<@{did}>\n`{did}`")
    e.add_field(name="Причина разбана", value=reason[:1000])
    if last:
        e.add_field(name="За что был бан", value=f"Причина: {last[2]}\nВыдал: `{last[3]}`", inline=False)
        if last[1]:
            e.set_thumbnail(url=last[1])
    e.set_footer(text="Автоматически · истёк срок наказания" if by is None else f"Администратор: {by}")
    await send_ban_log(e)
    return True


# ---- АВТО-БАН: не нажал «Готов» / вышел из матча. Срок растёт при повторах (за последние 30 дней).
AUTOBAN = os.getenv("AUTOBAN", "0") == "1"   # 0 = выключить авто-бан
AUTOBAN_LADDERS = {
    "ready": os.getenv("AUTOBAN_READY_LADDER", "10m,30m,2h,1d"),
    "leave": os.getenv("AUTOBAN_LEAVE_LADDER", "30m,2h,1d,3d,7d"),
}
AUTOBAN_WINDOW = 30 * 86400
READY_REASON = "не нажал «Готов» при подборе матча"
LEAVE_REASON = "вышел из матча и не вернулся"


async def auto_ban(member, kind: str, reason: str):
    """Автоматический бан от имени «Авто-бан». Администраторов не банит."""
    from types import SimpleNamespace
    if not AUTOBAN or not isinstance(member, discord.Member) or member.bot:
        return
    if member.guild_permissions.administrator or is_banned(member.id):
        return
    steps = [x for x in (parse_duration(v) for v in AUTOBAN_LADDERS[kind].split(",")) if x is not None] or [1800]
    full = f"Авто-бан: {reason}"
    n = db.execute("SELECT COUNT(*) FROM ban_log WHERE discord_id=? AND admin_id=0 AND reason=? AND created>?",
                   (member.id, full, int(time.time()) - AUTOBAN_WINDOW)).fetchone()[0]
    dur = steps[min(n, len(steps) - 1)]
    try:
        await do_ban(member, full, dur, SimpleNamespace(id=0, display_name="Авто-бан"))
    except Exception:
        log.exception("Не удалось выдать авто-бан %s", member)
        return
    log.info("Авто-бан %s: %s (%s)", member, reason, "навсегда" if not dur else fmt_dur(dur))
    try:
        await member.send(f"⛔ Вы получили авто-бан в FreePick ({'навсегда' if not dur else fmt_dur(dur)}): {reason}. "
                          "При повторных нарушениях срок будет больше.")
    except discord.HTTPException:
        pass
    return dur


_ban_loop_started = False


async def ban_expiry_loop():
    """Раз в минуту снимает баны, у которых истёк срок."""
    while True:
        try:
            now = int(time.time())
            for (did,) in db.execute("SELECT discord_id FROM bans WHERE expires>0 AND expires<=?",
                                     (now,)).fetchall():
                await do_unban(did, "Истекло время наказания")
        except Exception:
            log.exception("Ошибка в цикле снятия банов")
        await asyncio.sleep(60)


# ---- страница со списком банов (/bans, /punishment): в стиле сайта vibeproject.kz
BANS_PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Наказания | VIBE MIX FreePick</title>
<style>
:root{color-scheme:dark;--bg:#090613;--card:rgba(18,14,34,.88);--line:rgba(255,255,255,.07);--mut:#9a97b0;--pur:#7c1fff}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;font-family:Inter,system-ui,"Segoe UI",Roboto,Arial,sans-serif;color:#e8e6f2;
background:radial-gradient(1100px 600px at 15% -10%,#2b1252 0%,transparent 60%),
radial-gradient(900px 600px at 95% 5%,#14244f 0%,transparent 55%),var(--bg)}
.top{max-width:1280px;margin:0 auto;padding:18px 20px 0;display:flex;align-items:center;gap:14px}
.logo{font-weight:800;letter-spacing:.5px;font-size:18px}.logo span{color:#a66bff}
.nav{margin-left:auto;font-size:13px;color:var(--mut)}
.wrap{max-width:1280px;margin:0 auto;padding:20px;display:grid;grid-template-columns:320px 1fr;gap:20px;align-items:start}
@media(max-width:900px){.wrap{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:20px}
h2{margin:0 0 14px;font-size:18px}h3{margin:20px 0 10px;font-size:13px;color:var(--mut);font-weight:500}
.tabs{display:flex;background:rgba(255,255,255,.05);border-radius:10px;padding:4px;gap:4px;flex-wrap:wrap}
.tabs button{flex:1;min-width:70px;border:0;border-radius:8px;padding:9px 8px;background:transparent;color:#c9c6dd;
font-size:13px;font-weight:600;cursor:pointer}
.tabs button.on{background:var(--pur);color:#fff}
input{width:100%;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.08);border-radius:10px;
color:#e8e6f2;padding:11px 12px;font-size:14px;outline:none}input:focus{border-color:#7c3aed}
.stat{display:flex;justify-content:space-between;padding:11px 12px;border-radius:8px;background:rgba(255,255,255,.04);margin-bottom:8px;font-size:14px}
.stat b{color:#fff}
.tw{overflow-x:auto}
table{width:100%;border-collapse:separate;border-spacing:0 6px;min-width:680px}
th{text-align:left;font-size:12px;color:var(--mut);padding:6px 12px;font-weight:500}
td{background:rgba(255,255,255,.035);padding:10px 12px;font-size:14px}
tr.r{cursor:pointer}tr.r:hover td{background:rgba(124,31,255,.12)}
td:first-child{border-radius:10px 0 0 10px;width:44px;text-align:center}td:last-child{border-radius:0 10px 10px 0}
.pl{display:flex;align-items:center;gap:10px}
.pl img,.av{width:30px;height:30px;border-radius:8px;object-fit:cover;background:#2a2640;flex:none}
.b{padding:3px 10px;border-radius:6px;font-size:12px;font-weight:600;white-space:nowrap;display:inline-block}
.perm{background:rgba(237,66,69,.16);color:#ff5a5f}
.done{background:rgba(87,242,135,.12);color:#57f287;text-decoration:line-through}
.act{background:rgba(255,176,32,.16);color:#ffb020}
.unb{background:#4b1fb8;color:#d9ccff}
.empty{padding:30px;text-align:center;color:var(--mut)}
.more{display:block;margin:12px auto 0;background:rgba(255,255,255,.06);border:1px solid var(--line);color:#e8e6f2;
border-radius:10px;padding:10px 22px;cursor:pointer;font-size:14px}.more:hover{background:rgba(124,31,255,.2)}
.modal{position:fixed;inset:0;background:rgba(0,0,0,.65);display:none;align-items:center;justify-content:center;padding:16px;z-index:9}
.modal.on{display:flex}
.box{background:#120e22;border:1px solid var(--line);border-radius:16px;padding:22px;max-width:520px;width:100%;max-height:90vh;overflow:auto}
.box h2{display:flex;justify-content:space-between;align-items:center}
.x{background:none;border:0;color:var(--mut);font-size:22px;cursor:pointer}
.kv{display:grid;grid-template-columns:140px 1fr;gap:8px 12px;font-size:14px}.kv div:nth-child(odd){color:var(--mut)}
.kv a{color:#a66bff;text-decoration:none;word-break:break-all}
code{background:rgba(255,255,255,.06);padding:2px 6px;border-radius:6px;font-size:12px}
</style></head><body>
<div class="top"><div class="logo">VIBE <span>MIX</span> · FreePick</div><div class="nav">Блокировки</div></div>
<div class="wrap">
<div class="card"><h2>Инфо</h2>
<h3>Фильтр наказаний</h3>
<div class="tabs" id="tabs">
<button data-f="all" class="on">Все</button><button data-f="active">Активные</button>
<button data-f="perm">Навсегда</button><button data-f="ended">Снятые</button></div>
<h3>Найти нарушителя</h3><input id="q" placeholder="Ник, SteamID, причина или админ" autocomplete="off">
<h3>Статистика наказаний</h3>
<div class="stat"><span>Всего банов</span><b id="s_total">0</b></div>
<div class="stat"><span>Активных банов</span><b id="s_active">0</b></div>
<div class="stat"><span>Перманентных банов</span><b id="s_perm">0</b></div>
<div class="stat"><span>Снятых банов</span><b id="s_ended">0</b></div></div>
<div class="card"><h2>Список наказаний</h2><div class="tw"><table><thead><tr>
<th>Тип</th><th>Игрок</th><th>Причина</th><th>Срок</th><th>Админ</th></tr></thead><tbody id="rows"></tbody></table>
<div class="empty" id="empty" style="display:none">Наказаний не найдено</div>
<button class="more" id="more" style="display:none">Показать ещё</button></div></div></div>
<div class="modal" id="modal"><div class="box"><h2><span>Подробности наказания</span><button class="x" id="close">×</button></h2>
<div class="kv" id="kv"></div></div></div>
<script>
const D=__DATA__, NOW0=__NOW__, T0=Date.now();
const now=()=>NOW0+Math.floor((Date.now()-T0)/1000);
const st={f:'all',q:'',n:50};
const $=id=>document.getElementById(id);
function el(t,c,x){const e=document.createElement(t);if(c)e.className=c;if(x!==undefined)e.textContent=x;return e}
function status(r){if(r.unbanned)return'unb';if(r.expires===0)return'perm';if(r.expires<=now())return'done';return'act'}
function dur(s){const p=[];for(const[n,k]of[['д.',86400],['ч.',3600],['мин.',60]]){if(s>=k){p.push(Math.floor(s/k)+' '+n);s%=k}if(p.length==2)break}return p.join(' ')||'1 мин.'}
function dt(t){return t?new Date(t*1000).toLocaleString('ru-RU'):'—'}
function badge(r){const s=status(r),b=el('span','b '+s);
 b.textContent=s=='unb'?'Разбанен':s=='perm'?'Навсегда':s=='done'?dur(r.expires-r.created):dur(r.expires-now());return b}
function match(r){const q=st.q.toLowerCase(),s=status(r);
 if(st.f=='active'&&!(s=='act'||s=='perm'))return false;
 if(st.f=='perm'&&s!='perm')return false;
 if(st.f=='ended'&&!(s=='done'||s=='unb'))return false;
 if(!q)return true;
 return[r.name,r.steam,r.reason,r.admin,String(r.did)].some(v=>(v||'').toLowerCase().includes(q))}
function row(r){const tr=el('tr','r');
 tr.append(el('td','',status(r)=='unb'?'✅':'🚫'));
 const p=el('td'),w=el('div','pl');
 if(r.avatar&&/^https:\\/\\//.test(r.avatar)){const i=new Image();i.src=r.avatar;i.loading='lazy';i.onerror=()=>{i.style.visibility='hidden'};w.append(i)}else w.append(el('div','av'));
 w.append(el('span','',r.name||String(r.did)));p.append(w);tr.append(p);
 tr.append(el('td','',r.reason||'—'));
 const t=el('td');t.append(badge(r));tr.append(t);
 tr.append(el('td','',r.admin||'—'));
 tr.onclick=()=>open(r);return tr}
function render(){
 const all=D,m=all.filter(match);
 $('s_total').textContent=all.length;
 $('s_active').textContent=all.filter(r=>{const s=status(r);return s=='act'||s=='perm'}).length;
 $('s_perm').textContent=all.filter(r=>status(r)=='perm').length;
 $('s_ended').textContent=all.filter(r=>{const s=status(r);return s=='done'||s=='unb'}).length;
 const body=$('rows');body.replaceChildren(...m.slice(0,st.n).map(row));
 $('empty').style.display=m.length?'none':'block';
 $('more').style.display=m.length>st.n?'block':'none'}
function open(r){const kv=$('kv');kv.replaceChildren();
 const add=(k,v)=>{kv.append(el('div','',k));const d=el('div');if(v instanceof Node)d.append(v);else d.textContent=v;kv.append(d)};
 add('Игрок',r.name||'—');add('Discord ID',r.did);
 if(r.steam){const a=el('a','',r.steam);a.href='https://steamcommunity.com/profiles/'+encodeURIComponent(r.steam);a.target='_blank';a.rel='noopener';add('SteamID',a)}
 add('Причина',r.reason||'—');add('Статус',badge(r));
 add('Выдан',dt(r.created));add('Истекает',r.expires?dt(r.expires):'Никогда');
 add('Администратор',r.admin||'—');
 if(r.unbanned){add('Разбанен',dt(r.unbanned));add('Кем',r.unban_by||'—');add('Причина разбана',r.unban_reason||'—')}
 $('modal').classList.add('on')}
$('close').onclick=()=>$('modal').classList.remove('on');
$('modal').onclick=e=>{if(e.target.id=='modal')$('modal').classList.remove('on')};
document.addEventListener('keydown',e=>{if(e.key=='Escape')$('modal').classList.remove('on')});
$('q').oninput=e=>{st.q=e.target.value;st.n=50;render()};
$('more').onclick=()=>{st.n+=50;render()};
document.querySelectorAll('#tabs button').forEach(b=>b.onclick=()=>{
 document.querySelectorAll('#tabs button').forEach(x=>x.classList.remove('on'));b.classList.add('on');
 st.f=b.dataset.f;st.n=50;render()});
render();setInterval(render,60000);
</script></body></html>"""


def render_bans_page(rows: list, now: int) -> str:
    data = [{"did": did, "name": name, "avatar": avatar, "reason": reason, "admin": admin,
             "created": created or 0, "expires": expires or 0, "unbanned": unbanned,
             "steam": steam, "unban_reason": unban_reason, "unban_by": unban_by}
            for (did, name, avatar, reason, admin, created, expires, unbanned,
                 steam, unban_reason, unban_by) in rows]
    payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return BANS_PAGE.replace("__DATA__", payload).replace("__NOW__", str(int(now)))


async def h_bans(req: web.Request):
    rows = db.execute("SELECT discord_id, name, avatar, reason, admin_name, created, expires, unbanned_at, "
                      "steamid64, unban_reason, unban_by FROM ban_log ORDER BY created DESC LIMIT 1000").fetchall()
    return web.Response(text=render_bans_page(rows, int(time.time())), content_type="text/html")


# ----------------------------- ВЕБ-СЕРВЕР ----------------------------
async def h_match(req: web.Request):
    cfg = S.matches.get(int(req.match_info["mid"]))
    return web.json_response(cfg) if cfg else web.Response(status=404)


async def h_connect(req: web.Request):
    url = f"steam://connect/{SERVER_IP}:{SERVER_PORT}"
    if SERVER_PASSWORD:
        url += f"/{SERVER_PASSWORD}"
    html = (f'<meta http-equiv="refresh" content="0;url={url}">'
            f'<meta charset="utf-8"><a href="{url}">Подключиться к серверу</a>')
    return web.Response(text=html, content_type="text/html")


async def h_demo(req: web.Request):
    """Принимает файл демо от MatchZy (POST, тело = .dem) и сохраняет его. Скачать демо можно по ссылке /demo/<id>."""
    log.info("Запрос на /demo: MatchZy-FileName=%s, MatchId=%s, Content-Length=%s",
             req.headers.get("MatchZy-FileName"), req.headers.get("MatchZy-MatchId"),
             req.headers.get("Content-Length"))
    if not token_ok(req):
        http_hits["demo_bad"] += 1
        log.warning("Загрузка демо отклонена: неверный токен")
        return web.Response(status=401)
    http_hits["demo"] += 1
    fname = re.sub(r"[^\w.\-]", "_", os.path.basename(
        req.headers.get("MatchZy-FileName") or f"match_{int(time.time())}.dem"))
    os.makedirs(DEMO_DIR, exist_ok=True)
    path = os.path.join(DEMO_DIR, fname)
    try:
        with open(path, "wb") as f:
            async for chunk in req.content.iter_chunked(1 << 20):
                f.write(chunk)
    except Exception:
        log.exception("Не удалось сохранить демо %s", fname)
        return web.Response(status=500)
    url = f"{WEB_BASE_URL}/demos/{fname}"
    log.info("Демо сохранено: %s", fname)
    mid = None
    try:
        mid = int(req.headers.get("MatchZy-MatchId", ""))
    except ValueError:
        found = re.search(r"(\d{10})", fname)  # из имени файла {TIME}_{MATCH_ID}_{MAP}
        if found:
            mid = int(found.group(1))
    if mid:
        demo_urls[mid] = url
    return web.Response(text="ok")


async def h_demo_get(req: web.Request):
    """Скачивание демо по номеру матча: ищем файл с этим номером в DEMO_DIR."""
    mid = req.match_info["mid"]
    if os.path.isdir(DEMO_DIR):
        for f in sorted(os.listdir(DEMO_DIR), reverse=True):
            if mid in f and ".dem" in f:
                raise web.HTTPFound(f"{WEB_BASE_URL}/demos/{f}")
    if http_hits["demo"] == 0:
        why = "С момента запуска бота сервер не присылал ни одного демо."
    else:
        why = "Демо этого матча не найдено (могло стереться при перезапуске бота, если не подключён Render Disk)."
    return page("Демо ещё не готово", why + " Если матч только что закончился, попробуйте через минуту.", False)


async def h_events(req: web.Request):
    if not token_ok(req):
        http_hits["events_bad"] += 1
        log.warning("Событие MatchZy отклонено: неверный токен (заголовок: %r)",
                    (req.headers.get("Authorization") or "")[:8])
        return web.Response(status=401)
    http_hits["events"] += 1
    try:
        data = await req.json()
    except Exception:
        return web.Response(status=400)
    log.info("MatchZy event: %s (matchid=%s)", data.get("event"), data.get("matchid"))
    ev = data.get("event")
    event_counts[ev] = event_counts.get(ev, 0) + 1  # счётчик для /fp_diag
    if ev in ("player_death", "round_end") and event_counts[ev] == 1:
        log.info("RAW %s: %s", ev, json.dumps(data, ensure_ascii=False)[:700])  # формат события, чтобы подогнать разбор
    try:
        events_seen.add(int(data.get("matchid")))
    except (TypeError, ValueError):
        pass
    same = S.phase == "playing" and str(data.get("matchid")) == str(S.match_id)
    if ev != "player_death":  # смерти приходят очень часто, в журнал диагностики их не пишем
        event_log.append(f"{time.strftime('%H:%M:%S')} {ev} match={data.get('matchid')} {'ok' if same else 'не текущий матч'}")
    if ev == "series_end" and same:
        asyncio.create_task(reset_to_queue())
    elif ev == "going_live":
        try:
            gmid = int(data.get("matchid"))
        except (TypeError, ValueError):
            gmid = None
        if gmid in snapshots and gmid not in live_reset:
            live_reset.add(gmid)
            live_stats[gmid] = {}    # нож/разминка отбрасываются, но только один раз (повторный going_live не стирает киллы)
        if same:
            S.live = True            # матч пошёл (после ножей): теперь выход игрока = перерыв
            S.ever_live = True       # матч реально стартовал: если его сбросят вручную, результат опубликуем
    elif ev == "player_death":
        try:
            dmid = int(data.get("matchid"))
        except (TypeError, ValueError):
            dmid = None
        if dmid in snapshots:        # считаем смерти любого нашего матча, не зависим от S.live/same
            death_events[dmid] = death_events.get(dmid, 0) + 1
            tally_death(data)
            if same and is_grenade_tk(data):
                asyncio.create_task(announce_tk(data))
    elif ev == "round_end":
        try:
            if data.get("team1"):
                last_round[int(data.get("matchid"))] = data  # статистика на случай, если map_result не придёт
                if same and HALFTIME_ALLTALK:  # середина карты = смена сторон CT <-> T
                    _played = int((data.get("team1") or {}).get("score") or 0) + int((data.get("team2") or {}).get("score") or 0)
                    if _played == (TEST_MAXROUNDS if TEST_MODE else MAX_ROUNDS) // 2:
                        asyncio.create_task(halftime_talk())
        except (TypeError, ValueError):
            pass
    elif ev == "map_result":
        if same:
            S.live = False       # карта закончилась: выходы игроков больше не считаем
        try:
            mid = int(data.get("matchid"))
        except (TypeError, ValueError):
            mid = None
        snap = snapshots.get(mid)  # снимок игроков сохранён при старте: результат придёт, даже если матч уже сброшен
        if snap and mid not in posted_results:
            asyncio.create_task(post_result(data, dict(snap), mid))
        else:
            log.warning("map_result для матча %s: нет снимка игроков или результат уже опубликован", mid)
    elif same and ev == "player_connect":
        _p = data.get("player") or {}
        if _p.get("user_id") not in (None, ""):
            user_ids[str(_p.get("steamid", ""))] = str(_p["user_id"])  # запоминаем для кика после матча
        asyncio.create_task(handle_connect(data))
        asyncio.create_task(track_connect(data))
        asyncio.create_task(handle_return(data))
    elif same and ev == "player_disconnect":
        player = data.get("player") or {}
        if not player.get("is_bot"):
            S.connected.discard(str(player.get("steamid", "")))
            asyncio.create_task(handle_disconnect(str(player.get("steamid", ""))))
    return web.Response(text="ok")


# ----------------------------- STEAM-ВЕРИФИКАЦИЯ ---------------------
VERIFY_TTL = 300  # ссылка живёт 5 минут
STEAM_OPENID = "https://steamcommunity.com/openid/login"
CLAIMED_RE = re.compile(r"^https://steamcommunity\.com/openid/id/(\d{17})$")
pending: dict[str, dict] = {}


def new_token(discord_id: int, guild_id: int) -> str:
    now = time.time()
    for t in [t for t, v in pending.items() if v["exp"] < now]:
        pending.pop(t, None)
    token = secrets.token_urlsafe(24)
    pending[token] = {"discord_id": discord_id, "guild_id": guild_id, "exp": now + VERIFY_TTL}
    return token


async def give_role(member):
    if not VERIFIED_ROLE or not member:
        return
    role = member.guild.get_role(VERIFIED_ROLE)
    if role and role not in member.roles:
        try:
            await member.add_roles(role, reason="Steam verified")
        except discord.HTTPException:
            log.exception("Не удалось выдать роль (роль бота должна быть выше выдаваемой)")


# ----------------------------- FACEIT --------------------------------
async def fetch_faceit(steamid: str):
    """Уровень и ELO на FACEIT по SteamID64. None, если аккаунта нет или ключ не задан."""
    if not FACEIT_API_KEY:
        return None
    headers = {"Authorization": f"Bearer {FACEIT_API_KEY}"}
    for game in ("cs2", "csgo"):
        try:
            async with aiohttp.ClientSession() as ses:
                async with ses.get("https://open.faceit.com/data/v4/players",
                                   params={"game": game, "game_player_id": steamid},
                                   headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status != 200:
                        continue
                    data = await r.json()
        except Exception:
            log.exception("FACEIT API недоступен")
            return None
        g = (data.get("games") or {}).get(game)
        if g and g.get("skill_level"):
            return {"level": int(g["skill_level"]),
                    "elo": int(g.get("faceit_elo") or 0),
                    "nickname": data.get("nickname")}
    return None


async def give_faceit_role(member: discord.Member, level: int):
    """Выдаёт роль «FACEIT LVL n» (создаёт, если её нет) и снимает старые FACEIT-роли."""
    if not member:
        return
    guild = member.guild
    wanted = f"FACEIT LVL {level}"
    old = [r for r in member.roles if r.name.startswith("FACEIT LVL ") and r.name != wanted]
    try:
        role = discord.utils.get(guild.roles, name=wanted)
        if not role:
            role = await guild.create_role(name=wanted, reason="FACEIT уровень")
        if old:
            await member.remove_roles(*old, reason="FACEIT уровень изменился")
        if role not in member.roles:
            await member.add_roles(role, reason="FACEIT уровень")
    except discord.HTTPException:
        log.exception("Не удалось выдать FACEIT-роль (нужно право Manage Roles, роль бота выше)")


async def apply_faceit(member, steamid: str):
    """Тянет FACEIT-данные, выдаёт роль уровня и (по желанию) стартовый ELO. Возвращает данные или None."""
    fc = await fetch_faceit(steamid)
    if not fc:
        return None
    if isinstance(member, discord.Member):
        await give_faceit_role(member, fc["level"])
    if FACEIT_START_ELO and member and fc["elo"]:
        db.execute("INSERT OR IGNORE INTO elo (discord_id, elo) VALUES (?, ?)",
                   (member.id, max(ELO_MIN, fc["elo"])))
        db.commit()
        schedule_backup()
    return fc


async def remove_faceit_roles(member):
    """Снимает все роли «FACEIT LVL n» (при отвязке Steam)."""
    if not isinstance(member, discord.Member):
        return
    old = [r for r in member.roles if r.name.startswith("FACEIT LVL ")]
    if old:
        try:
            await member.remove_roles(*old, reason="Steam отвязан")
        except discord.HTTPException:
            log.exception("Не удалось снять FACEIT-роли")


class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Верификация", style=discord.ButtonStyle.success, custom_id="fp:verify")
    async def verify(self, i: discord.Interaction, b: discord.ui.Button):
        if get_steam(i.user.id):
            return await i.response.send_message(
                "Вы уже верифицированы. Чтобы привязать другой Steam, нажмите «Отвязать Steam».",
                ephemeral=True)
        if not WEB_BASE_URL:
            return await i.response.send_message("Не настроен WEB_BASE_URL бота.", ephemeral=True)
        token = new_token(i.user.id, i.guild_id or 0)
        link = discord.ui.View()
        link.add_item(discord.ui.Button(label="Войти через Steam",
                                        url=f"{WEB_BASE_URL}/auth/steam?t={token}"))
        await i.response.send_message("Ваша персональная ссылка (действует 5 минут):",
                                      view=link, ephemeral=True)

    @discord.ui.button(label="Обновить роли", style=discord.ButtonStyle.secondary, custom_id="fp:roles")
    async def roles(self, i: discord.Interaction, b: discord.ui.Button):
        sid = get_steam(i.user.id)
        if not sid:
            return await i.response.send_message("Сначала пройдите верификацию.", ephemeral=True)
        await i.response.defer(ephemeral=True)
        await give_role(i.user)
        fc = await apply_faceit(i.user, sid)
        text = "✅ Роли обновлены."
        if fc:
            text += f" FACEIT: уровень {fc['level']} (ELO {fc['elo']})"
        await i.followup.send(text, ephemeral=True)

    @discord.ui.button(label="Отвязать Steam", style=discord.ButtonStyle.danger, custom_id="fp:unlink")
    async def unlink(self, i: discord.Interaction, b: discord.ui.Button):
        if not get_steam(i.user.id):
            return await i.response.send_message("У вас нет привязанного Steam.", ephemeral=True)
        if i.user.id in S.active_ids or any(m.id == i.user.id for m in S.queue):
            return await i.response.send_message(
                "Сейчас отвязать нельзя: вы в очереди, драфте или матче. Выйдите из очереди и попробуйте снова.",
                ephemeral=True)
        await i.response.send_message(
            f"Отвязать Steam `{get_steam(i.user.id)}`? Роль верификации будет снята, "
            "и вы сможете пройти верификацию заново с другим аккаунтом.",
            view=UnlinkConfirm(i.user.id), ephemeral=True)


class UnlinkConfirm(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=60)
        self.user_id = user_id

    @discord.ui.button(label="Да, отвязать", style=discord.ButtonStyle.danger)
    async def yes(self, i: discord.Interaction, b: discord.ui.Button):
        if i.user.id != self.user_id:
            return await i.response.send_message("Это не ваша кнопка.", ephemeral=True)
        if i.user.id in S.active_ids:
            return await i.response.edit_message(
                content="Сейчас отвязать нельзя: вы в драфте или матче.", view=None)
        async with S.lock:
            S.queue = [m for m in S.queue if m.id != i.user.id]
        db.execute("DELETE FROM links WHERE discord_id=?", (i.user.id,))
        db.commit()
        schedule_backup()
        # снимаем роль верификации
        if VERIFIED_ROLE and isinstance(i.user, discord.Member):
            role = i.user.guild.get_role(VERIFIED_ROLE)
            if role and role in i.user.roles:
                try:
                    await i.user.remove_roles(role, reason="Steam отвязан пользователем")
                except discord.HTTPException:
                    log.exception("Не удалось снять роль верификации")
            await remove_faceit_roles(i.user)  # FACEIT-роль относилась к старому Steam
            # если сидит в голосе очереди, выкидываем оттуда
            if QUEUE_VC and i.user.voice and i.user.voice.channel and i.user.voice.channel.id == QUEUE_VC:
                try:
                    await i.user.move_to(None)
                except discord.HTTPException:
                    pass
        await i.response.edit_message(
            content="✅ Steam отвязан. Нажмите «Верификация», чтобы привязать новый аккаунт.", view=None)
        await refresh_panel()

    @discord.ui.button(label="Отмена", style=discord.ButtonStyle.secondary)
    async def no(self, i: discord.Interaction, b: discord.ui.Button):
        if i.user.id != self.user_id:
            return await i.response.send_message("Это не ваша кнопка.", ephemeral=True)
        await i.response.edit_message(content="Отменено.", view=None)


def page(title: str, text: str, ok: bool = True) -> web.Response:
    color = "#57F287" if ok else "#ED4245"
    html = ('<!doctype html><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{title}</title>'
            '<body style="background:#0b0b0d;color:#eee;font-family:sans-serif;display:flex;'
            'align-items:center;justify-content:center;height:100vh;margin:0">'
            f'<div style="text-align:center;max-width:420px;padding:24px"><h1 style="color:{color}">{title}</h1>'
            f'<p>{text}</p></div></body>')
    return web.Response(text=html, content_type="text/html")


async def h_auth(req: web.Request):
    token = req.query.get("t", "")
    rec = pending.get(token)
    if not rec or rec["exp"] < time.time():
        return page("Ссылка истекла", "Вернитесь в Discord и нажмите «Верификация» ещё раз.", False)
    params = {
        "openid.ns": "http://specs.openid.net/auth/2.0",
        "openid.mode": "checkid_setup",
        "openid.return_to": f"{WEB_BASE_URL}/auth/steam/callback?t={token}",
        "openid.realm": WEB_BASE_URL,
        "openid.identity": "http://specs.openid.net/auth/2.0/identifier_select",
        "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier_select",
    }
    raise web.HTTPFound(f"{STEAM_OPENID}?{urlencode(params)}")


async def h_auth_callback(req: web.Request):
    token = req.query.get("t", "")
    rec = pending.get(token)
    if not rec or rec["exp"] < time.time():
        return page("Ссылка истекла", "Вернитесь в Discord и нажмите «Верификация» ещё раз.", False)
    q = dict(req.query)
    m = CLAIMED_RE.match(q.get("openid.claimed_id", ""))
    expected = f"{WEB_BASE_URL}/auth/steam/callback?t={token}"
    if not m or q.get("openid.mode") != "id_res" or q.get("openid.return_to") != expected:
        return page("Ошибка", "Steam не подтвердил вход. Попробуйте ещё раз.", False)

    data = {k: v for k, v in q.items() if k.startswith("openid.")}
    data["openid.mode"] = "check_authentication"
    try:
        async with aiohttp.ClientSession() as ses:
            async with ses.post(STEAM_OPENID, data=data, timeout=aiohttp.ClientTimeout(total=10)) as r:
                body = await r.text()
    except Exception:
        log.exception("Steam OpenID недоступен")
        return page("Ошибка Steam", "Steam сейчас недоступен, попробуйте позже.", False)
    if "is_valid:true" not in body:
        return page("Ошибка", "Не удалось проверить ответ Steam.", False)

    steamid, did = m.group(1), rec["discord_id"]
    pending.pop(token, None)
    row = db.execute("SELECT discord_id FROM links WHERE steamid64=?", (steamid,)).fetchone()
    if row and row[0] != did:
        return page("Steam уже привязан", "Этот Steam-аккаунт привязан к другому Discord.", False)
    old = get_steam(did)
    if old and old != steamid:
        return page("Уже привязан другой Steam",
                    "Сначала нажмите «Отвязать Steam» на панели верификации в Discord.", False)
    db.execute("INSERT OR REPLACE INTO links VALUES (?, ?)", (did, steamid))
    db.commit()
    schedule_backup()

    guild = bot.get_guild(rec["guild_id"])
    member = guild.get_member(did) if guild else None
    await give_role(member)
    fc = await apply_faceit(member, steamid)  # роль «FACEIT LVL n» по уровню на FACEIT
    try:
        user = member or await bot.fetch_user(did)
        text = f"✅ Steam привязан: `{steamid}`. Роли выданы, можно заходить в очередь FreePick."
        if fc:
            text += f"\n🎯 Ваш FACEIT: уровень {fc['level']} (ELO {fc['elo']})"
        await user.send(text)
    except discord.HTTPException:
        pass
    return page("Готово", "Steam привязан. Закройте страницу и вернитесь в Discord.")


# ----------------------------- БОТ -----------------------------------
async def keepalive_loop():
    """Раз в 4 минуты открывает собственный публичный адрес, чтобы Render не усыплял бота."""
    await asyncio.sleep(60)
    while True:
        try:
            async with aiohttp.ClientSession() as ses:
                async with ses.get(WEB_BASE_URL + "/", timeout=aiohttp.ClientTimeout(total=15)) as r:
                    await r.read()
        except Exception:
            log.warning("keepalive: не удалось открыть %s", WEB_BASE_URL)
        await asyncio.sleep(240)


class FreePickBot(commands.Bot):
    async def setup_hook(self):
        self.add_view(QueueView())
        self.add_view(VerifyView())
        self.add_view(BanLogView())
        await ensure_fonts()  # шрифт с кириллицей для картинки результата
        asyncio.create_task(prefetch_map_images())  # картинки карт для фона табло

        os.makedirs(DEMO_DIR, exist_ok=True)
        app = web.Application(client_max_size=1024 ** 3)  # демо CS2 может весить сотни МБ
        app.add_routes([
            web.get("/", lambda r: web.Response(text="ok")),  # health check
            web.get(r"/match/{mid:\d+}.json", h_match),
            web.get("/connect", h_connect),
            web.get("/bans", h_bans),
            web.get("/punishment", h_bans),
            web.post("/events", h_events),
            web.post("/demo", h_demo),
            web.get(r"/demo/{mid:\d+}", h_demo_get),
            web.static("/demos", DEMO_DIR),
            web.get("/auth/steam", h_auth),
            web.get("/auth/steam/callback", h_auth_callback),
        ])
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", WEB_PORT).start()
        log.info("Веб-сервер слушает порт %s", WEB_PORT)
        asyncio.create_task(keepalive_loop())  # Render не должен засыпать

        # Синхронизация слэш-команд
        if GUILD_ID:
            g = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=g)
            await self.tree.sync(guild=g)
            log.info("Команды синхронизированы с сервером %s", GUILD_ID)
        else:
            await self.tree.sync()
            log.info("Команды синхронизированы глобально (может занять до часа)")


intents = discord.Intents.default()
intents.members = True  # включите Server Members Intent в Developer Portal
intents.message_content = os.getenv("AUTOBAN_CHAT", "1") == "1"  # для авто-бана в чате: включите Message Content Intent (или AUTOBAN_CHAT=0)
bot = FreePickBot(command_prefix="!", intents=intents)
admin = app_commands.checks.has_permissions(administrator=True)


@bot.tree.command(name="setup", description="Отправить панель очереди FreePick в этот канал")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@admin
async def setup_cmd(i: discord.Interaction):
    S.panel = await i.channel.send(embed=panel_embed(), view=None if QUEUE_VC else QueueView())
    kv_set("panel_channel", S.panel.channel.id)
    kv_set("panel_message", S.panel.id)
    schedule_backup()
    await sync_queue()
    await i.response.send_message("Панель отправлена.", ephemeral=True)


def verify_embed() -> discord.Embed:
    e = discord.Embed(title="Верификация", color=0xE8D44D)
    e.description = (
        "**Как пройти верификацию**\n"
        "1. Нажмите «Верификация» — бот пришлёт персональную ссылку, она действует 5 минут\n"
        "2. Войдите в Steam и подтвердите вход — роли выдадутся автоматически\n"
        "3. Подтверждение придёт в личные сообщения\n\n"
        "**Важно**\n"
        "• Один Discord — один Steam. Чтобы сменить Steam, нажмите «Отвязать Steam» и пройдите верификацию заново\n"
        "• Ссылка истекла или не пришла — просто нажмите «Верификация» ещё раз\n"
        "• Если роли не выдались — нажмите «Обновить роли» или откройте тикет\n"
        "• Отвязать Steam нельзя, пока вы в очереди, драфте или матче"
    )
    return e


async def refresh_verify_panels():
    """Обновляет уже отправленные панели верификации (добавляет кнопку «Отвязать Steam» и новый текст)."""
    g = get_guild()
    if not g:
        return
    for ch in g.text_channels:
        if "верификация" not in ch.name.lower():
            continue
        try:
            async for m in ch.history(limit=30):
                if (m.author.id == bot.user.id and m.embeds
                        and (m.embeds[0].title or "") == "Верификация"):
                    await m.edit(embed=verify_embed(), view=VerifyView())
                    log.info("Панель верификации обновлена в #%s", ch.name)
        except discord.HTTPException:
            log.warning("Не удалось обновить панель верификации в #%s", ch.name)


@bot.tree.command(name="verify_setup", description="Отправить панель Steam-верификации в этот канал")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@admin
async def verify_setup_cmd(i: discord.Interaction):
    e = verify_embed()
    await i.channel.send(embed=e, view=VerifyView())
    await i.response.send_message("Панель верификации отправлена.", ephemeral=True)


@bot.tree.command(name="fp_steam", description="Показать, какой Steam-аккаунт привязан к вам")
@app_commands.guild_only()
async def fp_steam_cmd(i: discord.Interaction):
    sid = get_steam(i.user.id)
    if not sid:
        return await i.response.send_message("У вас нет привязанного Steam. Нажмите «Верификация».", ephemeral=True)
    await i.response.send_message(
        f"Ваш Steam: `{sid}`\nhttps://steamcommunity.com/profiles/{sid}\n"
        "В CS2 нужно заходить именно с этого аккаунта. Если это не тот аккаунт, нажмите «Отвязать Steam» "
        "на панели верификации и привяжите нужный.",
        ephemeral=True)


@bot.tree.command(name="fp_link", description="(админ) Привязать SteamID64 игроку вручную")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.describe(member="Кому привязать Steam",
                       steamid64="SteamID64 (17 цифр, начинается с 7656119)",
                       transfer="Steam уже привязан к другому Discord (потерян): перенести его сюда вместе с ELO")
@admin
async def fp_link_cmd(i: discord.Interaction, member: discord.Member, steamid64: str, transfer: bool = False):
    steamid64 = steamid64.strip()
    if not re.fullmatch(r"7656119\d{10}", steamid64):
        return await i.response.send_message("Неверный SteamID64.", ephemeral=True)
    row = db.execute("SELECT discord_id FROM links WHERE steamid64=?", (steamid64,)).fetchone()
    old_owner = row[0] if row and row[0] != member.id else None
    if old_owner and not transfer:
        return await i.response.send_message(
            f"Этот SteamID уже привязан к <@{old_owner}> (`{old_owner}`).\n"
            "Если тот Discord-аккаунт потерян, повторите команду с параметром `transfer: True`: "
            "привязка и ELO перейдут к новому аккаунту.",
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
    if old_owner and (old_owner in S.active_ids or member.id in S.active_ids):
        return await i.response.send_message(
            "Сейчас идёт драфт или матч с участием одного из аккаунтов. Повторите после матча.", ephemeral=True)
    await i.response.defer(ephemeral=True)
    moved = ""
    if old_owner:
        db.execute("DELETE FROM links WHERE discord_id=?", (old_owner,))
        old_elo = db.execute("SELECT 1 FROM elo WHERE discord_id=?", (old_owner,)).fetchone()
        new_elo = db.execute("SELECT 1 FROM elo WHERE discord_id=?", (member.id,)).fetchone()
        if old_elo and not new_elo:  # ELO и статистика переходят к новому аккаунту
            db.execute("UPDATE elo SET discord_id=? WHERE discord_id=?", (member.id, old_owner))
            try:
                db.execute("UPDATE match_stats SET discord_id=? WHERE discord_id=?", (member.id, old_owner))
            except sqlite3.IntegrityError:
                log.warning("Не удалось перенести match_stats с %s на %s", old_owner, member.id)
            moved = " ELO и статистика перенесены."
        old_member = i.guild.get_member(old_owner)  # старый аккаунт ещё на сервере: снимаем роли
        if old_member:
            if VERIFIED_ROLE:
                role = i.guild.get_role(VERIFIED_ROLE)
                if role and role in old_member.roles:
                    try:
                        await old_member.remove_roles(role, reason="Steam перенесён на другой аккаунт")
                    except discord.HTTPException:
                        pass
            await remove_faceit_roles(old_member)
    db.execute("INSERT OR REPLACE INTO links VALUES (?, ?)", (member.id, steamid64))
    db.commit()
    schedule_backup()
    await give_role(member)
    fc = await apply_faceit(member, steamid64)
    await i.followup.send(
        f"✅ {member.mention}: Steam `{steamid64}` привязан."
        + (f" Снят с <@{old_owner}>." if old_owner else "") + moved
        + (f" FACEIT LVL {fc['level']}." if fc else ""),
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="fp_unlink", description="(админ) Сбросить привязку Steam игрока")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@admin
async def fp_unlink_cmd(i: discord.Interaction, member: discord.Member):
    db.execute("DELETE FROM links WHERE discord_id=?", (member.id,))
    db.commit()
    schedule_backup()
    await remove_faceit_roles(member)
    await i.response.send_message(f"Привязка {member.mention} сброшена, он может пройти верификацию заново.",
                                  ephemeral=True)


@bot.tree.command(name="elo", description="Показать ELO игрока")
@app_commands.guild_only()
async def elo_cmd(i: discord.Interaction, member: discord.Member = None):
    member = member or i.user
    e, w, l = get_stats(member.id)
    total = w + l
    wr = round(w * 100 / total) if total else 0
    await i.response.send_message(
        f"{member.mention}: **ELO {e}** · Побед {w} · Поражений {l} · Винрейт {wr}%", ephemeral=True)


@bot.tree.command(name="top", description="Таблица лидеров по ELO")
@app_commands.guild_only()
async def top_cmd(i: discord.Interaction):
    rows = db.execute("SELECT discord_id, elo, wins, losses FROM elo "
                      "ORDER BY elo DESC, wins DESC LIMIT 10").fetchall()
    if not rows:
        return await i.response.send_message("Пока нет сыгранных матчей.", ephemeral=True)
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = [f"{medals.get(n, f'{n}.')} <@{did}> — **{e}** ({w}W / {l}L)"
             for n, (did, e, w, l) in enumerate(rows, 1)]
    emb = discord.Embed(title="Топ игроков FreePick", description="\n".join(lines), color=0xFEE75C)
    await i.response.send_message(embed=emb, allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="fp_elo_set", description="(админ) Установить ELO игроку")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@admin
async def fp_elo_set_cmd(i: discord.Interaction, member: discord.Member, value: int):
    value = max(ELO_MIN, value)
    db.execute("INSERT INTO elo (discord_id, elo) VALUES (?, ?) "
               "ON CONFLICT(discord_id) DO UPDATE SET elo=?", (member.id, value, value))
    db.commit()
    schedule_backup()
    await i.response.send_message(f"{member.mention}: ELO = {value}", ephemeral=True)


@bot.tree.command(name="fp_ban", description="Забанить игрока в FreePick (срок: 30m, 12h, 3d, 1w, perm)")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@admin
async def ban_cmd(i: discord.Interaction, member: discord.Member, reason: str = "—", duration: str = "perm"):
    seconds = parse_duration(duration)
    if seconds is None:
        return await i.response.send_message(
            "Неверный срок. Примеры: `30m`, `12h`, `3d`, `1w`, `1d12h`, `perm` (навсегда).", ephemeral=True)
    await i.response.defer(ephemeral=True)
    await do_ban(member, reason, seconds, i.user)
    await i.followup.send(f"{member.mention} забанен ({'навсегда' if not seconds else fmt_dur(seconds)}): {reason}",
                          ephemeral=True)


@bot.tree.command(name="fp_unban", description="Разбанить игрока в FreePick")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@admin
async def unban_cmd(i: discord.Interaction, member: discord.User, reason: str = "Снят администратором"):
    await i.response.defer(ephemeral=True)
    if await do_unban(member.id, reason, by=i.user.display_name):
        await i.followup.send(f"{member.mention} разбанен.", ephemeral=True)
    else:
        await i.followup.send("Этот игрок не в бане.", ephemeral=True)


@bot.tree.command(name="endmatch", description="Принудительно сбросить матч и очередь")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@admin
async def endmatch_cmd(i: discord.Interaction):
    await i.response.defer(ephemeral=True)
    await reset_to_queue(kick_delay=0)
    await i.followup.send("Очередь сброшена, временные войсы команд удалены.", ephemeral=True)


@bot.tree.command(name="fp_start", description="(админ) Принудительно стартовать текущий матч на сервере")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@admin
async def fp_start_cmd(i: discord.Interaction):
    if S.phase != "playing" or not S.match_id:
        return await i.response.send_message("Сейчас нет матча на сервере.", ephemeral=True)
    await i.response.defer(ephemeral=True)
    S.auto_started = False
    ok = await force_start(S.match_id, f"{i.user.display_name} запустил матч")
    await i.followup.send("✅ Команда старта отправлена." if ok else "⚠ Сервер не стартовал матч, смотрите сообщение в чате матча.",
                          ephemeral=True)


@bot.tree.command(name="fp_diag", description="(админ) Проверить связь с CS2-сервером (RCON)")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@admin
async def fp_diag_cmd(i: discord.Interaction):
    await i.response.defer(ephemeral=True)
    parts = [f"Сервер: `{SERVER_IP}:{SERVER_PORT}`, RCON_PASSWORD: {'задан' if RCON_PASSWORD else 'НЕ ЗАДАН'}",
             f"Матч: `{S.match_id}`, фаза `{S.phase}`, игроков матча {len(S.match_players)}"]
    if S.match_id:
        tl = live_stats.get(S.match_id) or {}
        parts.append(f"Статистика по player_death: событий {death_events.get(S.match_id, 0)}, "
                     f"убийств {sum(v['k'] for v in tl.values())}, смертей {sum(v['d'] for v in tl.values())}, "
                     f"TK {sum(v.get('tk', 0) for v in tl.values())}")
    parts.append(f"HTTP от сервера: events ок={http_hits['events']}, отклонено={http_hits['events_bad']}; "
                 f"demo ок={http_hits['demo']}, отклонено={http_hits['demo_bad']}")
    parts.append("Счётчик событий: " + (", ".join(f"{k}={v}" for k, v in event_counts.items()) or "—"))
    parts.append("**События MatchZy (последние)**\n```" + ("\n".join(list(event_log)[-8:]) or "ничего не приходило") + "```")
    # доступен ли бот снаружи (так его видит CS2-сервер)
    try:
        async with aiohttp.ClientSession() as ses:
            async with ses.get(WEB_BASE_URL + "/", timeout=aiohttp.ClientTimeout(total=10)) as r:
                parts.append(f"Бот по {WEB_BASE_URL}: HTTP {r.status}")
    except Exception as exc:
        parts.append(f"Бот по {WEB_BASE_URL} НЕ открывается: `{type(exc).__name__}`")
    try:
        demos = [f for f in os.listdir(DEMO_DIR) if ".dem" in f] if os.path.isdir(DEMO_DIR) else []
        parts.append(f"Демо в `{DEMO_DIR}`: {len(demos)}" + (f", последнее `{sorted(demos)[-1][:60]}`" if demos else ""))
    except Exception:
        pass
    for cv in ("matchzy_remote_log_url", "matchzy_demo_upload_url", "matchzy_demo_recording_enabled"):
        try:
            resp = await asyncio.to_thread(rcon_cvar, cv)
            resp = re.sub(r"t=[\w\-]+", "t=***", resp)  # токен в чат не показываем
            parts.append(f"`{cv}`: `{resp.strip()[:90] or '(пусто)'}`")
        except Exception as exc:
            parts.append(f"`{cv}`: ошибка `{type(exc).__name__}`")
    for cv in ("tv_enable", "mp_maxrounds", "mp_halftime", "mp_friendlyfire",
               "ff_damage_reduction_bullets", "cash_player_killed_teammate"):
        try:
            resp = await asyncio.to_thread(rcon_raw, cv)
            parts.append(f"`{cv}`: `{resp.strip()[:90] or '(пусто)'}`")
        except Exception as exc:
            parts.append(f"`{cv}`: ошибка `{type(exc).__name__}`")
    for cmd in ("status", "get5_status"):
        try:
            resp = await asyncio.to_thread(rcon_raw, cmd)
            parts.append(f"**{cmd}**\n```{resp.strip()[:300] or '(пусто)'}```")
        except Exception as exc:
            parts.append(f"**{cmd}**: ошибка `{type(exc).__name__}: {exc}`")
    await i.followup.send("\n".join(parts)[:1990], ephemeral=True)


async def find_panel():
    """Если панель потерялась (стёрлась база), ищем в канале очереди сообщение бота с панелью."""
    g = get_guild()
    if not g:
        return None
    for ch in g.text_channels:
        if "очередь" not in ch.name.lower():
            continue
        try:
            async for m in ch.history(limit=30):
                if (m.author.id == bot.user.id and m.embeds
                        and (m.embeds[0].title or "").startswith("Очередь")):
                    return m
        except discord.HTTPException:
            continue
    return None


@bot.event
async def on_ready():
    log.info("Бот запущен как %s", bot.user)
    await restore_backup()  # привязки не должны пропадать при обновлении бота
    global _ban_loop_started
    if not _ban_loop_started:  # автоматическое снятие банов по сроку
        _ban_loop_started = True
        asyncio.create_task(ban_expiry_loop())
    asyncio.create_task(restore_from_dms())  # доберём тех, кого нет в бэкапе (из ЛС бота)
    load_access()
    # Если бот перезапустился во время матча, а матча уже нет — удаляем старые войсы команд
    if S.team_vcs and S.phase != "playing":
        await clear_voice_access()
    # Восстанавливаем панель после перезапуска
    ch_id, msg_id = kv_get("panel_channel"), kv_get("panel_message")
    if ch_id and msg_id and not S.panel:
        try:
            ch = bot.get_channel(int(ch_id)) or await bot.fetch_channel(int(ch_id))
            S.panel = await ch.fetch_message(int(msg_id))
            await refresh_panel()
        except discord.HTTPException:
            log.warning("Не удалось восстановить панель, отправьте /setup заново")
    await refresh_verify_panels()  # старые панели верификации получают кнопку «Отвязать Steam»
    if not S.panel:
        S.panel = await find_panel()
        if S.panel:
            kv_set("panel_channel", S.panel.channel.id)
            kv_set("panel_message", S.panel.id)
            await refresh_panel()
            log.info("Панель найдена автоматически")
    await sync_queue()


@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if member.bot:
        return

    # Во время матча игрока, зашедшего в любой войс, сразу перекидываем в войс его команды
    if after.channel and S.phase == "playing":
        team_n = next((n for m, n in S.match_players.values() if m.id == member.id), None)
        vc_id = S.team_vcs.get(team_n, 0) if team_n else 0
        if vc_id and after.channel.id != vc_id:
            target = member.guild.get_channel(vc_id)
            if target:
                try:
                    await member.move_to(target, reason="FreePick: игрок матча")
                except discord.HTTPException:
                    log.exception("Не удалось переместить %s в войс команды", member)
            return

    if not QUEUE_VC:
        return
    was = bool(before.channel and before.channel.id == QUEUE_VC)
    now = bool(after.channel and after.channel.id == QUEUE_VC)
    if was == now:
        return
    # Во время драфта: если все игроки вышли из войса очереди, драфт отменяется (проверка с задержкой)
    if was and not now and S.phase == "draft":
        asyncio.create_task(check_draft_empty())
    if now:
        err = None
        if is_banned(member.id):
            err = "⛔ Вам запрещено играть в FreePick."
        elif not get_steam(member.id):
            err = "Сначала пройдите Steam-верификацию (кнопка «Верификация»), затем зайдите снова."
        if err:
            try:
                await member.move_to(None)  # выкидываем из канала очереди
            except discord.HTTPException:
                pass
            try:
                await member.send(err)  # сообщение в личку
            except discord.HTTPException:
                # ЛС закрыты: пишем в канал, чтобы игрок всё равно узнал причину
                if S.panel:
                    await S.panel.channel.send(f"{member.mention} {err}", delete_after=20)
            return
    await sync_queue()


# ----------------------------- АВТО-БАН В ЧАТЕ -----------------------
# Спам = бан 5 мин, оскорбление = бан 10 мин. Бан FreePick + тайм-аут в Discord на тот же срок.
AUTOBAN_CHAT = os.getenv("AUTOBAN_CHAT", "1") == "1"       # 0 = выключить проверку чата
SPAM_COUNT = int(os.getenv("SPAM_COUNT", "5"))              # столько сообщений ...
SPAM_SECONDS = int(os.getenv("SPAM_SECONDS", "6"))          # ... за столько секунд = спам
SPAM_SAME = int(os.getenv("SPAM_SAME", "3"))                # столько одинаковых сообщений за 20 сек = спам
AUTOBAN_LADDERS["spam"] = os.getenv("AUTOBAN_SPAM_LADDER", "5m")
AUTOBAN_LADDERS["insult"] = os.getenv("AUTOBAN_INSULT_LADDER", "10m")
SPAM_REASON = "спам в чате"
INSULT_REASON = "оскорбление в чате"
AUTOBAN_IGNORE = {int(x) for x in os.getenv("AUTOBAN_IGNORE_CHANNELS", "").split(",") if x.strip().isdigit()}
AUTOBAN_EXTRA = [w.strip().lower() for w in os.getenv("AUTOBAN_WORDS", "").split(",") if w.strip()]  # свои слова (корни)

_PRE = r"(?:на|по|за|до|вы|раз|рас|от|при|под|пере|съ|объ|с|у|не|ни|о|в)?"
_PREFIXED = [r"ху[йяеи]", r"пизд", r"пезд", r"еба[лнт]", r"ебл[аоуи]", r"ебу[чт]", r"ебис", r"ебн[ую]", r"ебак", r"ебал"]
_STAND = [r"бляд", r"блят", r"блэт", r"сук[аиуе]$", r"сукин", r"сучк", r"сучар", r"мудак", r"мудил", r"мудозвон",
          r"пидор", r"пидар", r"пидр", r"педик", r"педераст", r"гандон", r"гондон", r"(?:долб|далб)[ао]?еб",
          r"дебил", r"дибил", r"идиот", r"кретин", r"имбецил", r"ублюд", r"выродок", r"мразь", r"мразот",
          r"шлюх", r"шалав", r"залуп", r"чмо$", r"чмошн", r"даун$", r"уебок", r"уебан", r"урод$", r"уроды$",
          r"тварь$", r"твари$", r"гнида", r"падла", r"паскуд", r"сволоч", r"скотин", r"говнюк", r"хуесос",
          r"fuck", r"shit", r"bitch", r"retard", r"cunt", r"whore", r"slut", r"faggot"]
_EXACT = {"бля", "еб", "ебать", "хуй", "нахуй", "нах", "пох", "похуй", "пиздец", "хер", "нахер"}
for _w in AUTOBAN_EXTRA:
    _PREFIXED.append(re.escape(_w))
_RE_PRE = re.compile("^" + _PRE + "(?:" + "|".join(_PREFIXED) + ")")
_RE_STAND = re.compile("^(?:" + "|".join(_STAND) + ")")
_LAT2CYR = str.maketrans({"a": "а", "e": "е", "o": "о", "p": "р", "c": "с", "x": "х", "y": "у",
                          "k": "к", "m": "м", "t": "т", "h": "н", "b": "в", "0": "о"})


def _collapse(s: str) -> str:
    return re.sub(r"(.)\1+", r"\1", s)  # «пиииздец» -> «пиздец»


def is_insult(text: str) -> bool:
    """Мат и оскорбления: учитывает буквы-двойники (латиница), растянутые буквы и слова через пробел."""
    text = text.lower().replace("ё", "е")
    raw = re.findall(r"[a-zа-я0-9]+", text)
    toks, buf = [], ""
    for t in raw:
        if len(t) == 1:
            buf += t
        else:
            if len(buf) >= 3:
                toks.append(buf)
            buf = ""
            toks.append(t)
    if len(buf) >= 3:
        toks.append(buf)
    for t in toks:
        for v in {_collapse(t), _collapse(t.translate(_LAT2CYR))}:
            if v in _EXACT or _RE_PRE.match(v) or _RE_STAND.match(v):
                return True
    return False


_chat_hist: dict[int, deque] = {}  # user_id -> последние сообщения (время, текст, сообщение)


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild or not AUTOBAN or not AUTOBAN_CHAT:
        return
    member = message.author
    if not isinstance(member, discord.Member) or message.channel.id in AUTOBAN_IGNORE:
        return
    perms = member.guild_permissions
    if perms.administrator or perms.manage_messages:  # админов и модераторов не трогаем
        return
    now_t = time.time()
    hist = _chat_hist.setdefault(member.id, deque(maxlen=20))
    text = (message.content or "").strip().lower()
    hist.append((now_t, text, message))

    kind = reason = None
    if text and is_insult(text):
        kind, reason = "insult", INSULT_REASON
        to_delete = [message]
    else:
        recent = [x for x in hist if now_t - x[0] <= SPAM_SECONDS]
        same = [x for x in hist if text and x[1] == text and now_t - x[0] <= 20]
        if len(recent) >= SPAM_COUNT or len(same) >= SPAM_SAME:
            kind, reason = "spam", SPAM_REASON
            to_delete = [x[2] for x in hist if now_t - x[0] <= 20]
    if not kind:
        return
    hist.clear()
    for m in to_delete:
        try:
            await m.delete()
        except discord.HTTPException:
            pass
    dur = await auto_ban(member, kind, reason)
    if dur is None:
        return
    try:  # тайм-аут в Discord на тот же срок (нужно право Moderate Members)
        await member.timeout(timedelta(seconds=min(dur or 28 * 86400, 28 * 86400)), reason=f"Авто-бан: {reason}")
    except discord.HTTPException:
        log.warning("Не удалось выдать тайм-аут %s (нужно право Moderate Members, роль бота выше)", member)
    try:
        await message.channel.send(f"🚫 {member.mention} получил бан на {fmt_dur(dur) if dur else 'навсегда'}: {reason}.",
                                   delete_after=15, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        pass


# =====================================================================
#  КОМАНДЫ: /match, /profile, /mute, /unmute, /clearrole, /clan
# =====================================================================
CLAN_MAX = int(os.getenv("CLAN_MAX_MEMBERS", "10"))   # максимум игроков в клане
CLAN_INVITE_TTL = 3 * 86400                            # приглашение действует 3 дня

# ---- таблицы (создаются при запуске) ----
db.execute("CREATE TABLE IF NOT EXISTS clans ("
           "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE, "
           "tag TEXT NOT NULL, tag_key TEXT NOT NULL UNIQUE, owner_id INTEGER NOT NULL, created INTEGER NOT NULL)")
db.execute("CREATE TABLE IF NOT EXISTS clan_members ("
           "discord_id INTEGER PRIMARY KEY, clan_id INTEGER NOT NULL, role TEXT NOT NULL DEFAULT 'member', "
           "joined INTEGER NOT NULL)")
db.execute("CREATE TABLE IF NOT EXISTS clan_invites ("
           "clan_id INTEGER NOT NULL, discord_id INTEGER NOT NULL, inviter_id INTEGER NOT NULL, "
           "created INTEGER NOT NULL, PRIMARY KEY (clan_id, discord_id))")
db.execute("CREATE TABLE IF NOT EXISTS matches ("
           "match_id INTEGER PRIMARY KEY, map TEXT, score1 INTEGER, score2 INTEGER, winner TEXT, created INTEGER)")
db.execute("CREATE TABLE IF NOT EXISTS match_stats ("
           "match_id INTEGER NOT NULL, discord_id INTEGER NOT NULL, team INTEGER, kills INTEGER, deaths INTEGER, "
           "assists INTEGER, adr INTEGER, hs INTEGER, won INTEGER, has_stats INTEGER NOT NULL DEFAULT 1, "
           "PRIMARY KEY (match_id, discord_id))")
db.commit()


# ---- сохранение статистики матча + бэкап новых таблиц ----
def save_match(mid, map_name, s1, s2, win, team_rows, players):
    """Вызывается из post_result: пишет итог матча и статистику каждого игрока."""
    try:
        db.execute("INSERT OR REPLACE INTO matches (match_id, map, score1, score2, winner, created) "
                   "VALUES (?,?,?,?,?,?)", (mid, map_name, s1 or 0, s2 or 0, win or "", int(time.time())))
        saved = set()
        for n in (1, 2):
            won = 1 if win == f"team{n}" else 0
            for r in team_rows.get(n, []):
                m = r.get("member")
                if not m:
                    continue
                db.execute("INSERT OR REPLACE INTO match_stats VALUES (?,?,?,?,?,?,?,?,?,1)",
                           (mid, m.id, n, r["k"], r["d"], r["a"], r["adr"], r["hs"], won))
                saved.add(m.id)
        for m, n in players.values():  # игроки без статистики сервера: только факт участия
            if m.id not in saved:
                won = 1 if win == f"team{n}" else 0
                db.execute("INSERT OR REPLACE INTO match_stats VALUES (?,?,?,0,0,0,0,0,?,0)", (mid, m.id, n, won))
        db.commit()
        schedule_backup()
    except Exception:
        log.exception("Не удалось сохранить статистику матча %s", mid)


def dump_extra() -> dict:
    return {
        "clans": db.execute("SELECT id,name,name_key,tag,tag_key,owner_id,created FROM clans").fetchall(),
        "clan_members": db.execute("SELECT discord_id,clan_id,role,joined FROM clan_members").fetchall(),
        "matches": db.execute("SELECT match_id,map,score1,score2,winner,created FROM matches").fetchall(),
        "match_stats": db.execute("SELECT match_id,discord_id,team,kills,deaths,assists,adr,hs,won,has_stats "
                                  "FROM match_stats").fetchall(),
    }


def restore_extra(data: dict):
    for r in data.get("clans", []):
        db.execute("INSERT OR IGNORE INTO clans (id,name,name_key,tag,tag_key,owner_id,created) "
                   "VALUES (?,?,?,?,?,?,?)", tuple(r))
    for r in data.get("clan_members", []):
        db.execute("INSERT OR IGNORE INTO clan_members (discord_id,clan_id,role,joined) VALUES (?,?,?,?)", tuple(r))
    for r in data.get("matches", []):
        db.execute("INSERT OR IGNORE INTO matches (match_id,map,score1,score2,winner,created) "
                   "VALUES (?,?,?,?,?,?)", tuple(r))
    for r in data.get("match_stats", []):
        db.execute("INSERT OR IGNORE INTO match_stats (match_id,discord_id,team,kills,deaths,assists,adr,hs,won,"
                   "has_stats) VALUES (?,?,?,?,?,?,?,?,?,?)", tuple(r))


def is_admin_user(i: discord.Interaction) -> bool:
    return isinstance(i.user, discord.Member) and i.user.guild_permissions.administrator


# ---- единый обработчик ошибок слэш-команд (чтобы не было «приложение не отвечает») ----
@bot.tree.error
async def on_app_command_error(i: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        msg = "⛔ Недостаточно прав для этой команды."
    else:
        log.error("Ошибка команды /%s", getattr(i.command, "qualified_name", "?"), exc_info=error)
        msg = "❌ Ошибка при выполнении команды."
    try:
        if i.response.is_done():
            await i.followup.send(msg, ephemeral=True)
        else:
            await i.response.send_message(msg, ephemeral=True)
    except discord.HTTPException:
        pass


# =====================================================================
#  /match stop, /match stat
# =====================================================================
match_group = app_commands.Group(name="match", description="Матчи FreePick", guild_only=True)


@match_group.command(name="stop", description="(админ) Остановить текущий матч или драфт")
@app_commands.describe(publish="Опубликовать итог матча и начислить ELO (по умолчанию нет)")
async def match_stop(i: discord.Interaction, publish: bool = False):
    if not is_admin_user(i):
        return await i.response.send_message("⛔ Эта команда только для администраторов.", ephemeral=True)
    if S.phase == "queue":
        return await i.response.send_message("Сейчас нет активного матча или драфта.", ephemeral=True)
    await i.response.defer(ephemeral=True)
    was = S.phase
    if was == "draft":
        t = S.draft_task
        if t and not t.done():
            t.cancel()
    else:
        if not publish and S.match_id:
            posted_results.add(S.match_id)  # без итога и без изменения ELO
        try:  # останавливаем матч на самом CS2-сервере
            await asyncio.to_thread(rcon_raw, "get5_endmatch")
        except Exception:
            log.exception("Не удалось остановить матч на сервере")
    await reset_to_queue(kick_delay=0)   # игроков кикаем с сервера сразу
    await i.followup.send("🛑 Драфт отменён, очередь сброшена." if was == "draft"
                          else "🛑 Матч остановлен, очередь сброшена.", ephemeral=True)


@match_group.command(name="stat", description="Статистика матча или последние матчи игрока")
@app_commands.describe(match_id="Номер матча (из канала результатов). Пусто = последние матчи игрока",
                       member="Игрок (по умолчанию вы)")
async def match_stat(i: discord.Interaction, match_id: int = None, member: discord.Member = None):
    if match_id:
        m = db.execute("SELECT map, score1, score2, winner, created FROM matches WHERE match_id=?",
                       (match_id,)).fetchone()
        if not m:
            return await i.response.send_message(
                "Матч не найден. Статистика сохраняется только для матчей, сыгранных после обновления бота.",
                ephemeral=True)
        rows = db.execute("SELECT discord_id, team, kills, deaths, assists, adr, hs, won, has_stats "
                          "FROM match_stats WHERE match_id=? ORDER BY team, kills DESC", (match_id,)).fetchall()
        mp, s1, s2, win, created = m
        e = discord.Embed(title=f"Матч #{match_id} — {pretty(mp or '?')}", color=0xF1C40F)
        head = f"**Team 1  {s1} : {s2}  Team 2**"
        if win in ("team1", "team2"):
            head += f"\n🏆 Победитель: **{'Team 1' if win == 'team1' else 'Team 2'}**"
        e.description = head
        for n in (1, 2):
            lines = []
            for did, team, k, d, a, adr, hs, won, has in rows:
                if team != n:
                    continue
                kd = k / d if d else float(k)
                st = (f" `{k}/{d}/{a}` · K/D {kd:.2f}" + (f" · ADR {adr}" if adr else "") + f" · HS {hs}%") if has else ""
                lines.append(f"<@{did}>{st}")
            e.add_field(name=f"Team {n}", value="\n".join(lines)[:1024] or "—", inline=False)
        e.set_footer(text=f"Сыграно: {time.strftime('%d.%m.%Y %H:%M', time.localtime(created or 0))}")
        return await i.response.send_message(embed=e)

    member = member or i.user
    rows = db.execute(
        "SELECT s.match_id, x.map, x.score1, x.score2, x.winner, s.team, s.kills, s.deaths, s.assists, s.has_stats "
        "FROM match_stats s LEFT JOIN matches x ON x.match_id=s.match_id "
        "WHERE s.discord_id=? ORDER BY s.match_id DESC LIMIT 5", (member.id,)).fetchall()
    if not rows:
        return await i.response.send_message(f"У {member.mention} пока нет сохранённых матчей.", ephemeral=True,
                                             allowed_mentions=discord.AllowedMentions.none())
    lines = []
    for mid, mp, s1, s2, win, team, k, d, a, has in rows:
        res = "➖" if win not in ("team1", "team2") else ("✅" if win == f"team{team}" else "❌")
        kda = f" · `{k}/{d}/{a}`" if has else ""
        lines.append(f"`#{mid}` {res} {pretty(mp or '?')} {s1}:{s2}{kda}")
    e = discord.Embed(title=f"Последние матчи — {member.display_name}", description="\n".join(lines), color=0xF1C40F)
    e.set_footer(text="Подробности матча: /match stat match_id:<номер>")
    await i.response.send_message(embed=e)


bot.tree.add_command(match_group)


# =====================================================================
#  /profile
# =====================================================================
@bot.tree.command(name="profile", description="Профиль игрока FreePick")
@app_commands.guild_only()
@app_commands.describe(member="Игрок (по умолчанию вы)")
async def profile_cmd(i: discord.Interaction, member: discord.Member = None):
    member = member or i.user
    elo, w, l = get_stats(member.id)
    rank = db.execute("SELECT COUNT(*) FROM elo WHERE elo > ?", (elo,)).fetchone()[0] + 1
    n, k, d, a, adr, hs = db.execute(
        "SELECT COUNT(*), COALESCE(SUM(kills),0), COALESCE(SUM(deaths),0), COALESCE(SUM(assists),0), "
        "COALESCE(AVG(adr),0), COALESCE(AVG(hs),0) FROM match_stats WHERE discord_id=? AND has_stats=1",
        (member.id,)).fetchone()
    total = w + l
    wr = round(w * 100 / total) if total else 0
    e = discord.Embed(title=f"Профиль — {member.display_name}", color=0x2B2D31)
    e.set_thumbnail(url=member.display_avatar.url)
    e.add_field(name="ELO", value=f"**{elo}**\nМесто в топе: #{rank}", inline=True)
    e.add_field(name="Матчи", value=f"{w}W / {l}L\nВинрейт {wr}%", inline=True)
    if n:
        kd = k / d if d else float(k)
        e.add_field(name="Статистика", value=f"K/D {kd:.2f}" + (f" · ADR {adr:.0f}" if adr else "") + f" · HS {hs:.0f}%\n"
                                              f"Убийств {k} · Смертей {d} · Помощей {a}", inline=False)
    else:
        e.add_field(name="Статистика", value="Пока нет данных по убийствам", inline=False)
    c = get_clan(member.id)
    if c:
        e.add_field(name="Клан", value=f"[{c[2]}] {c[1]}" + (" 👑" if c[3] == member.id else ""), inline=True)
    sid = get_steam(member.id)
    e.add_field(name="Steam", value=f"[Профиль](https://steamcommunity.com/profiles/{sid})" if sid
                else "не привязан", inline=True)
    fc = next((r.name for r in member.roles if r.name.startswith("FACEIT LVL ")), None)
    if fc:
        e.add_field(name="FACEIT", value=fc.replace("FACEIT ", ""), inline=True)
    flags = []
    if is_banned(member.id):
        flags.append("⛔ бан FreePick")
    if member.is_timed_out():
        flags.append("🔇 мут")
    if flags:
        e.add_field(name="Статус", value=", ".join(flags), inline=False)
    await i.response.send_message(embed=e)


# =====================================================================
#  /mute, /unmute  (тайм-аут Discord)
# =====================================================================
@bot.tree.command(name="mute", description="(модератор) Выдать мут (тайм-аут) участнику")
@app_commands.guild_only()
@app_commands.default_permissions(moderate_members=True)
@app_commands.describe(member="Кого замутить", duration="Срок: 10m, 2h, 3d (максимум 28 дней)", reason="Причина")
async def mute_cmd(i: discord.Interaction, member: discord.Member, duration: str = "10m", reason: str = "—"):
    perms = i.user.guild_permissions
    if not (perms.moderate_members or perms.administrator):
        return await i.response.send_message("⛔ Нужно право «Управлять участниками» (Moderate Members).", ephemeral=True)
    if member.bot or member.id == i.user.id:
        return await i.response.send_message("Нельзя замутить бота или самого себя.", ephemeral=True)
    if member.guild_permissions.administrator:
        return await i.response.send_message("Администраторов мутить нельзя.", ephemeral=True)
    if i.user.id != i.guild.owner_id and member.top_role >= i.user.top_role:
        return await i.response.send_message("Роль этого участника выше или равна вашей.", ephemeral=True)
    sec = parse_duration(duration)
    if sec is None:
        return await i.response.send_message("Неверный срок. Примеры: `10m`, `2h`, `3d`, `1w`.", ephemeral=True)
    sec = min(sec or 28 * 86400, 28 * 86400)  # Discord: максимум 28 дней
    try:
        await member.timeout(timedelta(seconds=sec), reason=f"{i.user}: {reason}"[:500])
    except discord.Forbidden:
        return await i.response.send_message("❌ У бота нет прав: нужна роль бота выше участника и право "
                                             "Moderate Members.", ephemeral=True)
    except discord.HTTPException:
        return await i.response.send_message("❌ Не удалось выдать мут.", ephemeral=True)
    await i.response.send_message(f"🔇 {member.mention} замучен на {fmt_dur(sec)}: {reason}", ephemeral=True,
                                  allowed_mentions=discord.AllowedMentions.none())
    until = int(time.time()) + sec
    e = discord.Embed(title="🔇 Мут выдан", color=0xFEE75C, timestamp=discord.utils.utcnow())
    e.add_field(name="Игрок", value=f"<@{member.id}>\n`{member.id}`")
    e.add_field(name="Снимется", value=f"<t:{until}:R>")
    e.add_field(name="Причина", value=reason[:1000])
    e.set_thumbnail(url=member.display_avatar.url)
    e.set_footer(text=f"Модератор: {i.user.display_name} • {i.user.id}")
    await send_ban_log(e)


@bot.tree.command(name="unmute", description="(модератор) Снять мут с участника")
@app_commands.guild_only()
@app_commands.default_permissions(moderate_members=True)
async def unmute_cmd(i: discord.Interaction, member: discord.Member):
    perms = i.user.guild_permissions
    if not (perms.moderate_members or perms.administrator):
        return await i.response.send_message("⛔ Нужно право «Управлять участниками» (Moderate Members).", ephemeral=True)
    if not member.is_timed_out():
        return await i.response.send_message("У этого участника нет мута.", ephemeral=True)
    try:
        await member.timeout(None, reason=f"Мут снят: {i.user}")
    except discord.HTTPException:
        return await i.response.send_message("❌ Не удалось снять мут (проверьте права бота).", ephemeral=True)
    await i.response.send_message(f"🔊 Мут с {member.mention} снят.", ephemeral=True,
                                  allowed_mentions=discord.AllowedMentions.none())


# =====================================================================
#  /clearrole
# =====================================================================
def _role_problem(i: discord.Interaction, role: discord.Role):
    g = i.guild
    if role.is_default():
        return "Роль @everyone трогать нельзя."
    if role.managed:
        return "Это служебная роль (бот/интеграция), её нельзя снять вручную."
    if role >= g.me.top_role:
        return "Роль выше или равна роли бота: поднимите роль бота выше в настройках сервера."
    if i.user.id != g.owner_id and role >= i.user.top_role:
        return "Эта роль выше или равна вашей высшей роли."
    return None


class ClearRoleConfirm(discord.ui.View):
    def __init__(self, user_id: int, role: discord.Role):
        super().__init__(timeout=60)
        self.user_id, self.role = user_id, role

    @discord.ui.button(label="Да, снять у всех", style=discord.ButtonStyle.danger)
    async def yes(self, i: discord.Interaction, b: discord.ui.Button):
        if i.user.id != self.user_id:
            return await i.response.send_message("Это не ваша кнопка.", ephemeral=True)
        members = list(self.role.members)
        await i.response.edit_message(content=f"⏳ Снимаю роль **{self.role.name}** у {len(members)} участников...",
                                      view=None)
        done = fail = 0
        for m in members:
            try:
                await m.remove_roles(self.role, reason=f"/clearrole от {i.user}")
                done += 1
            except discord.HTTPException:
                fail += 1
            await asyncio.sleep(0.4)  # не упираемся в лимиты Discord
        await i.edit_original_response(
            content=f"✅ Роль **{self.role.name}** снята у {done} участников" + (f", ошибок: {fail}" if fail else "") + ".")

    @discord.ui.button(label="Отмена", style=discord.ButtonStyle.secondary)
    async def no(self, i: discord.Interaction, b: discord.ui.Button):
        if i.user.id != self.user_id:
            return await i.response.send_message("Это не ваша кнопка.", ephemeral=True)
        await i.response.edit_message(content="Отменено.", view=None)


@bot.tree.command(name="clearrole", description="(админ) Снять роль у участника или у всех, у кого она есть")
@app_commands.guild_only()
@app_commands.default_permissions(manage_roles=True)
@app_commands.describe(role="Какую роль снять", member="С кого снять (пусто = у всех, у кого есть эта роль)")
async def clearrole_cmd(i: discord.Interaction, role: discord.Role, member: discord.Member = None):
    perms = i.user.guild_permissions
    if not (perms.manage_roles or perms.administrator):
        return await i.response.send_message("⛔ Нужно право «Управлять ролями» (Manage Roles).", ephemeral=True)
    problem = _role_problem(i, role)
    if problem:
        return await i.response.send_message(f"❌ {problem}", ephemeral=True)
    if member:
        if role not in member.roles:
            return await i.response.send_message(f"У {member.mention} нет роли **{role.name}**.", ephemeral=True,
                                                 allowed_mentions=discord.AllowedMentions.none())
        try:
            await member.remove_roles(role, reason=f"/clearrole от {i.user}")
        except discord.HTTPException:
            return await i.response.send_message("❌ Не удалось снять роль (проверьте права бота).", ephemeral=True)
        return await i.response.send_message(f"✅ Роль **{role.name}** снята у {member.mention}.", ephemeral=True,
                                             allowed_mentions=discord.AllowedMentions.none())
    count = len(role.members)
    if not count:
        return await i.response.send_message(f"Роль **{role.name}** сейчас ни у кого нет.", ephemeral=True)
    await i.response.send_message(
        f"⚠ Снять роль **{role.name}** у **{count}** участников? Действие нельзя отменить.",
        view=ClearRoleConfirm(i.user.id, role), ephemeral=True)


# =====================================================================
#  /clan ...
# =====================================================================
NAME_RE = re.compile(r"^[\w\- ]{3,24}$")
TAG_RE = re.compile(r"^[A-Za-z0-9А-Яа-яЁё]{2,5}$")


def get_clan(did: int):
    """(id, name, tag, owner_id, created) клана игрока или None."""
    return db.execute("SELECT c.id, c.name, c.tag, c.owner_id, c.created FROM clan_members m "
                      "JOIN clans c ON c.id=m.clan_id WHERE m.discord_id=?", (did,)).fetchone()


def clan_by_name(name: str):
    key = (name or "").strip().casefold()
    return db.execute("SELECT id, name, tag, owner_id, created FROM clans WHERE name_key=? OR tag_key=?",
                      (key, key)).fetchone()


def clan_count(cid: int) -> int:
    return db.execute("SELECT COUNT(*) FROM clan_members WHERE clan_id=?", (cid,)).fetchone()[0]


def clan_embed(c) -> discord.Embed:
    cid, name, tag, owner_id, created = c
    mem = db.execute(
        "SELECT m.discord_id, m.role, COALESCE(e.elo, ?), COALESCE(e.wins, 0), COALESCE(e.losses, 0) "
        "FROM clan_members m LEFT JOIN elo e ON e.discord_id=m.discord_id WHERE m.clan_id=? "
        "ORDER BY (m.role='owner') DESC, e.elo DESC", (ELO_START, cid)).fetchall()
    avg = round(sum(x[2] for x in mem) / len(mem)) if mem else 0
    wins, losses = sum(x[3] for x in mem), sum(x[4] for x in mem)
    e = discord.Embed(title=f"[{tag}] {name}", color=0x2B2D31)
    e.add_field(name="Лидер", value=f"<@{owner_id}>", inline=True)
    e.add_field(name="Участники", value=f"{len(mem)}/{CLAN_MAX}", inline=True)
    e.add_field(name="Средний ELO", value=str(avg), inline=True)
    e.add_field(name="Победы / поражения", value=f"{wins}W / {losses}L", inline=True)
    e.add_field(name="Создан", value=f"<t:{created}:D>", inline=True)
    lines = [f"{'👑' if role == 'owner' else '•'} <@{did}> · ELO {elo} · {w}W/{l}L" for did, role, elo, w, l in mem]
    e.add_field(name="Состав", value="\n".join(lines)[:1024] or "—", inline=False)
    return e


def clan_create_do(user, name: str, tag: str):
    name, tag = " ".join((name or "").split()), (tag or "").strip()
    if get_clan(user.id):
        return False, "Вы уже состоите в клане. Сначала выйдите: `/clan leave`."
    if not NAME_RE.fullmatch(name):
        return False, "Название клана: 3–24 символа (буквы, цифры, пробел, дефис, подчёркивание)."
    if not TAG_RE.fullmatch(tag):
        return False, "Тег клана: 2–5 символов (только буквы и цифры)."
    try:
        cur = db.execute("INSERT INTO clans (name, name_key, tag, tag_key, owner_id, created) VALUES (?,?,?,?,?,?)",
                         (name, name.casefold(), tag, tag.casefold(), user.id, int(time.time())))
    except sqlite3.IntegrityError:
        return False, "Клан с таким названием или тегом уже существует."
    db.execute("INSERT INTO clan_members (discord_id, clan_id, role, joined) VALUES (?,?,?,?)",
               (user.id, cur.lastrowid, "owner", int(time.time())))
    db.commit()
    schedule_backup()
    return True, f"✅ Клан **[{tag}] {name}** создан. Вы — лидер. Приглашайте игроков: `/clan invite`."


async def clan_invite_flow(inviter, target):
    c = get_clan(inviter.id)
    if not c:
        return False, "Вы не состоите в клане."
    if c[3] != inviter.id:
        return False, "Приглашать может только лидер клана."
    if target.bot or target.id == inviter.id:
        return False, "Нельзя пригласить бота или самого себя."
    if get_clan(target.id):
        return False, f"{target.mention} уже состоит в клане."
    if clan_count(c[0]) >= CLAN_MAX:
        return False, f"В клане максимум {CLAN_MAX} участников."
    db.execute("INSERT OR REPLACE INTO clan_invites (clan_id, discord_id, inviter_id, created) VALUES (?,?,?,?)",
               (c[0], target.id, inviter.id, int(time.time())))
    db.commit()
    try:
        await target.send(f"📨 {inviter.display_name} приглашает вас в клан **[{c[2]}] {c[1]}**.\n"
                          f"Чтобы вступить, напишите на сервере `/clan accept` (приглашение действует 3 дня).")
    except discord.HTTPException:
        pass  # ЛС закрыты: игрок увидит приглашение в /clan menu
    return True, f"📨 Приглашение отправлено {target.mention}. Пусть напишет `/clan accept`."


def clan_accept_do(user, name: str = None):
    if get_clan(user.id):
        return False, "Вы уже состоите в клане."
    rows = db.execute("SELECT c.id, c.name, c.tag FROM clan_invites v JOIN clans c ON c.id=v.clan_id "
                      "WHERE v.discord_id=? AND v.created>?", (user.id, int(time.time()) - CLAN_INVITE_TTL)).fetchall()
    if not rows:
        return False, "У вас нет действующих приглашений."
    if name:
        key = name.strip().casefold()
        rows = [r for r in rows if key in (r[1].casefold(), r[2].casefold())]
        if not rows:
            return False, "Приглашения от этого клана нет."
    elif len(rows) > 1:
        return False, "У вас несколько приглашений, укажите клан: " + ", ".join(f"**{r[1]}**" for r in rows)
    cid, cname, ctag = rows[0]
    if clan_count(cid) >= CLAN_MAX:
        return False, "В клане уже нет свободных мест."
    db.execute("INSERT INTO clan_members (discord_id, clan_id, role, joined) VALUES (?,?,?,?)",
               (user.id, cid, "member", int(time.time())))
    db.execute("DELETE FROM clan_invites WHERE discord_id=?", (user.id,))
    db.commit()
    schedule_backup()
    return True, f"✅ Вы вступили в клан **[{ctag}] {cname}**."


def clan_kick_do(owner, target_id: int):
    c = get_clan(owner.id)
    if not c:
        return False, "Вы не состоите в клане."
    if c[3] != owner.id:
        return False, "Исключать может только лидер клана."
    if target_id == owner.id:
        return False, "Себя исключить нельзя. Чтобы выйти, используйте `/clan leave`."
    tc = get_clan(target_id)
    if not tc or tc[0] != c[0]:
        return False, "Этот игрок не состоит в вашем клане."
    db.execute("DELETE FROM clan_members WHERE discord_id=?", (target_id,))
    db.commit()
    schedule_backup()
    return True, f"👢 <@{target_id}> исключён из клана."


def clan_disband_do(owner):
    c = get_clan(owner.id)
    if not c or c[3] != owner.id:
        return False, "Распустить клан может только его лидер."
    db.execute("DELETE FROM clan_members WHERE clan_id=?", (c[0],))
    db.execute("DELETE FROM clan_invites WHERE clan_id=?", (c[0],))
    db.execute("DELETE FROM clans WHERE id=?", (c[0],))
    db.commit()
    schedule_backup()
    return True, f"🗑 Клан **[{c[2]}] {c[1]}** распущен."


def clan_leave_do(user):
    c = get_clan(user.id)
    if not c:
        return False, "Вы не состоите в клане."
    if c[3] == user.id:
        nxt = db.execute("SELECT discord_id FROM clan_members WHERE clan_id=? AND discord_id<>? "
                         "ORDER BY joined LIMIT 1", (c[0], user.id)).fetchone()
        if not nxt:  # лидер один в клане: клан распускается
            return clan_disband_do(user)
        db.execute("UPDATE clans SET owner_id=? WHERE id=?", (nxt[0], c[0]))
        db.execute("UPDATE clan_members SET role='owner' WHERE discord_id=?", (nxt[0],))
        db.execute("DELETE FROM clan_members WHERE discord_id=?", (user.id,))
        db.commit()
        schedule_backup()
        return True, f"🚪 Вы покинули клан **[{c[2]}] {c[1]}**. Лидерство передано <@{nxt[0]}>."
    db.execute("DELETE FROM clan_members WHERE discord_id=?", (user.id,))
    db.commit()
    schedule_backup()
    return True, f"🚪 Вы покинули клан **[{c[2]}] {c[1]}**."


clan_group = app_commands.Group(name="clan", description="Кланы FreePick", guild_only=True)


@clan_group.command(name="create", description="Создать клан")
@app_commands.describe(name="Название клана (3–24 символа)", tag="Тег клана (2–5 символов)")
async def clan_create(i: discord.Interaction, name: app_commands.Range[str, 3, 24], tag: app_commands.Range[str, 2, 5]):
    ok, msg = clan_create_do(i.user, name, tag)
    await i.response.send_message(msg, ephemeral=not ok)


@clan_group.command(name="invite", description="Пригласить игрока в клан (только лидер)")
async def clan_invite(i: discord.Interaction, member: discord.Member):
    await i.response.defer(ephemeral=True)
    ok, msg = await clan_invite_flow(i.user, member)
    await i.followup.send(msg, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@clan_group.command(name="accept", description="Принять приглашение в клан")
@app_commands.describe(clan="Клан, из которого пришло приглашение (если оно одно, можно не указывать)")
async def clan_accept(i: discord.Interaction, clan: str = None):
    ok, msg = clan_accept_do(i.user, clan)
    await i.response.send_message(msg, ephemeral=not ok)


@clan_accept.autocomplete("clan")
async def clan_accept_ac(i: discord.Interaction, current: str):
    rows = db.execute("SELECT c.name, c.tag FROM clan_invites v JOIN clans c ON c.id=v.clan_id "
                      "WHERE v.discord_id=? AND v.created>?", (i.user.id, int(time.time()) - CLAN_INVITE_TTL)).fetchall()
    cur = (current or "").casefold()
    return [app_commands.Choice(name=f"[{t}] {n}"[:100], value=n) for n, t in rows
            if cur in n.casefold() or cur in t.casefold()][:25]


async def clan_name_ac(i: discord.Interaction, current: str):
    like = f"%{(current or '').casefold()}%"
    rows = db.execute("SELECT name, tag FROM clans WHERE name_key LIKE ? OR tag_key LIKE ? "
                      "ORDER BY name_key LIMIT 25", (like, like)).fetchall()
    return [app_commands.Choice(name=f"[{t}] {n}"[:100], value=n) for n, t in rows]


@clan_group.command(name="info", description="Информация о клане")
@app_commands.describe(name="Название или тег клана (пусто = ваш клан)")
@app_commands.autocomplete(name=clan_name_ac)
async def clan_info(i: discord.Interaction, name: str = None):
    c = clan_by_name(name) if name else get_clan(i.user.id)
    if not c:
        return await i.response.send_message("Клан не найден." if name else "Вы не состоите в клане.",
                                             ephemeral=True)
    await i.response.send_message(embed=clan_embed(c))


@clan_group.command(name="kick", description="Исключить игрока из клана (только лидер)")
async def clan_kick(i: discord.Interaction, member: discord.User):
    ok, msg = clan_kick_do(i.user, member.id)
    await i.response.send_message(msg, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@clan_group.command(name="leave", description="Покинуть клан")
async def clan_leave(i: discord.Interaction):
    ok, msg = clan_leave_do(i.user)
    await i.response.send_message(msg, ephemeral=True)


@clan_group.command(name="list", description="Топ кланов по среднему ELO")
async def clan_list(i: discord.Interaction):
    rows = db.execute(
        "SELECT c.name, c.tag, COUNT(m.discord_id) AS n, AVG(COALESCE(e.elo, ?)) AS avg_elo "
        "FROM clans c JOIN clan_members m ON m.clan_id=c.id LEFT JOIN elo e ON e.discord_id=m.discord_id "
        "GROUP BY c.id ORDER BY avg_elo DESC, n DESC LIMIT 15", (ELO_START,)).fetchall()
    if not rows:
        return await i.response.send_message("Кланов пока нет. Создайте первый: `/clan create`.", ephemeral=True)
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = [f"{medals.get(n, f'`{n}.`')} **[{t}] {nm}** · {cnt}/{CLAN_MAX} игроков · ELO {round(avg)}"
             for n, (nm, t, cnt, avg) in enumerate(rows, 1)]
    await i.response.send_message(embed=discord.Embed(title="Топ кланов FreePick", description="\n".join(lines),
                                                      color=0xFEE75C))


class ClanCreateModal(discord.ui.Modal, title="Создать клан"):
    name = discord.ui.TextInput(label="Название (3–24 символа)", min_length=3, max_length=24)
    tag = discord.ui.TextInput(label="Тег (2–5 символов)", min_length=2, max_length=5)

    async def on_submit(self, i: discord.Interaction):
        ok, msg = clan_create_do(i.user, str(self.name), str(self.tag))
        await i.response.send_message(msg, ephemeral=True)


class ClanDisbandConfirm(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=60)
        self.user_id = user_id

    @discord.ui.button(label="Да, распустить", style=discord.ButtonStyle.danger)
    async def yes(self, i: discord.Interaction, b: discord.ui.Button):
        if i.user.id != self.user_id:
            return await i.response.send_message("Это не ваша кнопка.", ephemeral=True)
        ok, msg = clan_disband_do(i.user)
        await i.response.edit_message(content=msg, view=None)

    @discord.ui.button(label="Отмена", style=discord.ButtonStyle.secondary)
    async def no(self, i: discord.Interaction, b: discord.ui.Button):
        if i.user.id != self.user_id:
            return await i.response.send_message("Это не ваша кнопка.", ephemeral=True)
        await i.response.edit_message(content="Отменено.", view=None)


class ClanMenu(discord.ui.View):
    """Меню клана с кнопками. Для игрока без клана: создание клана и список приглашений."""

    def __init__(self, user_id: int, clan):
        super().__init__(timeout=180)
        self.user_id = user_id
        if clan:
            self._add("Информация", discord.ButtonStyle.primary, self.on_info, "📋")
            if clan[3] == user_id:
                self._add("Пригласить", discord.ButtonStyle.success, self.on_invite, "📨")
            self._add("Покинуть клан", discord.ButtonStyle.secondary, self.on_leave, "🚪")
            if clan[3] == user_id:
                self._add("Распустить клан", discord.ButtonStyle.danger, self.on_disband, "🗑")
        else:
            self._add("Создать клан", discord.ButtonStyle.success, self.on_create, "➕")

    def _add(self, label, style, cb, emoji):
        b = discord.ui.Button(label=label, style=style, emoji=emoji)
        b.callback = cb
        self.add_item(b)

    async def interaction_check(self, i: discord.Interaction) -> bool:
        if i.user.id != self.user_id:
            await i.response.send_message("Это меню другого игрока. Откройте своё: `/clan menu`.", ephemeral=True)
            return False
        return True

    async def on_info(self, i: discord.Interaction):
        c = get_clan(i.user.id)
        if not c:
            return await i.response.send_message("Вы уже не состоите в клане.", ephemeral=True)
        await i.response.send_message(embed=clan_embed(c), ephemeral=True)

    async def on_invite(self, i: discord.Interaction):
        sel = discord.ui.UserSelect(placeholder="Кого пригласить?", min_values=1, max_values=1)

        async def picked(ii: discord.Interaction):
            await ii.response.defer(ephemeral=True)
            ok, msg = await clan_invite_flow(ii.user, sel.values[0])
            await ii.followup.send(msg, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

        sel.callback = picked
        v = discord.ui.View(timeout=60)
        v.add_item(sel)
        await i.response.send_message("Выберите игрока:", view=v, ephemeral=True)

    async def on_leave(self, i: discord.Interaction):
        ok, msg = clan_leave_do(i.user)
        await i.response.send_message(msg, ephemeral=True)

    async def on_disband(self, i: discord.Interaction):
        await i.response.send_message("⚠ Распустить клан? Это нельзя отменить.",
                                      view=ClanDisbandConfirm(i.user.id), ephemeral=True)

    async def on_create(self, i: discord.Interaction):
        await i.response.send_modal(ClanCreateModal())


@clan_group.command(name="menu", description="Меню клана")
async def clan_menu(i: discord.Interaction):
    c = get_clan(i.user.id)
    if c:
        emb = clan_embed(c)
    else:
        inv = db.execute("SELECT c.name, c.tag FROM clan_invites v JOIN clans c ON c.id=v.clan_id "
                         "WHERE v.discord_id=? AND v.created>?",
                         (i.user.id, int(time.time()) - CLAN_INVITE_TTL)).fetchall()
        text = "Вы не состоите в клане. Создайте свой кнопкой ниже или примите приглашение."
        if inv:
            text += "\n\n**Ваши приглашения:**\n" + "\n".join(f"• **[{t}] {n}** — `/clan accept clan:{n}`" for n, t in inv)
        emb = discord.Embed(title="Кланы FreePick", description=text, color=0x2B2D31)
    await i.response.send_message(embed=emb, view=ClanMenu(i.user.id, c), ephemeral=True)


bot.tree.add_command(clan_group)


# ----------------------------- ЗАПУСК --------------------------------
def say(msg: str):
    print(msg, flush=True)


def main():
    say("▶ Старт бота...")
    raw_token = os.getenv("DISCORD_TOKEN", "")
    token = raw_token.strip().strip('"').strip("'")
    say(f"▶ DISCORD_TOKEN: {'задан, длина ' + str(len(token)) if token else 'НЕ ЗАДАН'}")
    say(f"▶ Порт веб-сервера: {WEB_PORT}, WEB_BASE_URL: {WEB_BASE_URL}")
    say(f"▶ TEST_MODE={TEST_MODE}, QUEUE_VC_ID={QUEUE_VC}, GUILD_ID={GUILD_ID}")
    say(f"▶ Формат: {TEST_MAXROUNDS if TEST_MODE else MAX_ROUNDS} раундов, смена сторон на перерыве; "
        f"кик после матча: {'вкл, через ' + str(KICK_DELAY) + ' сек' if KICK_AFTER_MATCH else 'выкл'}; "
        f"голосов для отмены игры: {CANCEL_VOTES}")
    say(f"▶ Авто-бан: {'вкл' if AUTOBAN else 'выкл'}")
    say(f"▶ Автостарт: {'вкл' if AUTO_START else 'выкл'}, разминка {WARMUP_SECONDS} сек")
    say(f"▶ FACEIT: {'ключ задан' if FACEIT_API_KEY else 'FACEIT_API_KEY не задан (FACEIT-роли выключены)'}")
    say(f"▶ Результат матча: {'картинка + текст (счёт, MVP, ELO, демо)' if RESULT_TEXT else 'только картинка'}, "
        f"кнопка под результатом: {'vibeproject.kz' if SITE_URL else 'выкл'}, сайт: {SITE_URL or 'выкл'}")
    say(f"▶ Демо сохраняются в: {DEMO_DIR}, картинки карт: {MAP_DIR}")
    if not token:
        say("❌ Не задана переменная DISCORD_TOKEN (Render -> Environment)")
        raise SystemExit(1)
    if not BACKUP_CHANNEL:
        say("⚠ BACKUP_CHANNEL_ID не задан: привязки Steam пропадут при обновлении бота на Render")
    if not RCON_PASSWORD:
        say("❌ RCON_PASSWORD не задан: запуск матчей на сервере не сработает (задай в Render -> Environment)")
    if not os.getenv("EVENT_TOKEN"):
        say("ℹ EVENT_TOKEN не задан в окружении: создан временный токен (бот сам передаёт его серверу при запуске матча)")
    try:
        bot.run(token)
    except discord.errors.LoginFailure:
        say("❌ Неверный DISCORD_TOKEN. Пересоздайте токен в Discord Developer Portal -> Bot -> Reset Token.")
        raise SystemExit(1)
    except discord.errors.PrivilegedIntentsRequired:
        say("❌ Не включены привилегированные Intents: Developer Portal -> Bot -> Privileged Gateway Intents -> включите Server Members Intent и Message Content Intent (либо задайте AUTOBAN_CHAT=0 в Render).")
        raise SystemExit(1)
    except Exception as exc:
        import traceback
        say(f"❌ Бот упал: {exc!r}")
        traceback.print_exc()
        raise SystemExit(1)
    say("⚠ bot.run() завершился без ошибки")


if __name__ == "__main__":
    main()
