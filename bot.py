"""
KZLP FreePick 5x5: очередь -> капитаны -> пики игроков -> вето карт -> запуск матча на CS2 (MatchZy).
После драфта игроки получают доступ в войс своей команды (Team 1 / Team 2) и перемещаются туда.
Авто-старт: как только набралось нужное число игроков, драфт запускается сам.
Если во время драфта все игроки вышли из войса очереди, драфт отменяется и очередь сбрасывается.
При Steam-верификации бот определяет FACEIT-уровень игрока и выдаёт роль «FACEIT LVL n».
Результат матча: табло + MVP + ELO + кнопка «Скачать демо».
"""
print("▶ bot.py v28 загружается...", flush=True)
import asyncio
import io
import json
import logging
import os
import random
import re
import secrets
import sqlite3
import time
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
# CS2-сервер (RCON_PASSWORD обязательно задай в Render -> Environment)
SERVER_IP = os.getenv("SERVER_IP", "45.86.81.37").strip()
SERVER_PORT = int(os.getenv("SERVER_PORT", "55031"))
RCON_PASSWORD = os.getenv("RCON_PASSWORD", "ArniAlash22062008Nurlan")
SERVER_PASSWORD = os.getenv("SERVER_PASSWORD", "")

# Веб-сервер бота (его должен видеть CS2-сервер)
WEB_PORT = int(os.getenv("PORT") or os.getenv("WEB_PORT", "55031"))
WEB_BASE_URL = os.getenv("WEB_BASE_URL", "https://bot-vibe-mix.onrender.com").rstrip("/")
EVENT_TOKEN = os.getenv("EVENT_TOKEN") or secrets.token_urlsafe(24)  # секрет для событий MatchZy (если не задан, генерируется сам)

# ID твоего Discord-сервера: команды появятся мгновенно (необязательно)
GUILD_ID = int(os.getenv("GUILD_ID", "1548371779523837952"))

# Голосовые каналы команд (0 = выключено)
TEAM1_VC = int(os.getenv("TEAM1_VC_ID", "1565442747450659038"))
TEAM2_VC = int(os.getenv("TEAM2_VC_ID", "1565442482425041016"))

# Голосовой канал очереди: зашёл в него = встал в очередь, вышел = покинул (0 = только кнопки)
QUEUE_VC = int(os.getenv("QUEUE_VC_ID", "1565440992574705734"))

# Роль, которая выдаётся после Steam-верификации (0 = не выдавать)
VERIFIED_ROLE = int(os.getenv("VERIFIED_ROLE_ID", "1565117832251965653"))

# FACEIT: ключ с https://developers.faceit.com (Server side API key). Пусто = FACEIT-роли выключены.
# Ключ задаётся ТОЛЬКО в Render -> Environment (FACEIT_API_KEY), в коде его не храним.
FACEIT_API_KEY = os.getenv("FACEIT_API_KEY", "590b7ce5-2812-4f48-9628-938aff17dff2").strip()
# 1 = стартовый ELO в FreePick берётся из FACEIT ELO (только для тех, у кого ещё нет рейтинга)
FACEIT_START_ELO = os.getenv("FACEIT_START_ELO", "1:1548371779523837955,2:1548371779523837956,3:1548371779523837957,4;1548371779523837958,5:1548371779523837959,6:1548371779523837960,7:1548371779523837961,8:1548371779528040610,9:1548371779528040611,10:1548371779528040612") == "1"

TEST_MODE = os.getenv("TEST_MODE", "0") == "1"  # 1 = тест: хватает одного игрока, без драфта
TEAM_SIZE = 1 if TEST_MODE else 5
NEED = 1 if TEST_MODE else TEAM_SIZE * 2
PICK_TIMEOUT = 30            # секунд на пик/бан, потом выбор случайный
CAPTAIN_TIMEOUT = 30         # секунд на выбор капитанов (кто не вызвался, назначается случайно)
MATCH_MAX_SECONDS = 600 if TEST_MODE else 2 * 3600  # автосброс, если series_end не пришёл
BREAK_SECONDS = int(os.getenv("BREAK_SECONDS", "300"))  # сколько ждём вышедшего игрока, потом матч продолжается

# Канал для результатов матчей (0 = бот сам найдёт канал, в названии которого есть "результаты")
RESULTS_CHANNEL = int(os.getenv("RESULTS_CHANNEL_ID", "1565444339084038314"))

# Бэкап привязок: приватный канал для админов, куда бот кладёт файл с привязками (0 = выключено).
# Нужен, потому что на Render файл базы стирается при каждом обновлении.
BACKUP_CHANNEL = int(os.getenv("BACKUP_CHANNEL_ID", "1565489828706000948"))
# Если подключён Render Disk, укажи DB_PATH=/data/freepick.db
DB_PATH = os.getenv("DB_PATH", "freepick.db")

# Папка для демо матчей (на Render без диска файлы стираются при деплое; с диском: DEMO_DIR=/data/demos)
DEMO_DIR = os.getenv("DEMO_DIR", "demos")

MAPS = ["de_anubis", "de_mirage", "de_inferno", "de_nuke",
        "de_ancient", "de_dust2", "de_overpass"]

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
ELO_K = 30         # сила изменения за матч
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
    keys = ("panel_channel", "panel_message", "team_access")
    data = {
        "links": db.execute("SELECT discord_id, steamid64 FROM links").fetchall(),
        "bans": db.execute("SELECT discord_id, reason, expires FROM bans").fetchall(),
        "ban_log": db.execute("SELECT * FROM ban_log").fetchall(),
        "elo": db.execute("SELECT discord_id, elo, wins, losses FROM elo").fetchall(),
        "kv": {k: kv_get(k) for k in keys if kv_get(k) is not None},
    }
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
        self.team_access: list[tuple[int, int]] = []   # (id канала, id игрока) с выданным доступом
        self.active_ids: set[int] = set()              # игроки текущего драфта/матча
        self.chat_msgs: list[discord.Message] = []     # сообщения драфта/матча, удаляются при сбросе
        self.match_players: dict[str, tuple[discord.Member, int]] = {}  # steamid64 -> (игрок, номер команды)
        self.captain_ids: set[int] = set()
        self.live = False                              # матч в живой фазе (после ножей)
        self.paused = False                            # матч на паузе из-за вышедшего игрока
        self.absent: set[int] = set()                  # игроки, которые вышли с сервера
        self.break_channel: discord.TextChannel | None = None
        self.break_task: asyncio.Task | None = None
        self.break_lock = asyncio.Lock()
        self.match_channel: discord.TextChannel | None = None   # отдельный чат матча
        self.draft_task: asyncio.Task | None = None    # задача драфта (чтобы отменить, если все вышли из войса)
        self.draft_check = False                       # идёт проверка «все ли вышли из войса»
        self.lock = asyncio.Lock()


S = State()


def save_access():
    kv_set("team_access", json.dumps(S.team_access))
    schedule_backup()


def load_access():
    raw = kv_get("team_access")
    if raw:
        try:
            S.team_access = [tuple(x) for x in json.loads(raw)]
        except (ValueError, TypeError):
            S.team_access = []


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
    if S.panel:
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


# ----------------------------- ПИКИ И ВЕТО ---------------------------
class CaptainView(discord.ui.View):
    """Игроки сами вызываются в капитаны: первые двое нажавших становятся капитанами."""

    def __init__(self, players: list[discord.Member]):
        super().__init__(timeout=CAPTAIN_TIMEOUT)
        self.players = players
        self.caps: list[discord.Member] = []

    def text(self) -> str:
        have = ", ".join(m.mention for m in self.caps) or "пока никого"
        return (f"👑 **Выбор капитанов.** Нажмите кнопку, чтобы стать капитаном "
                f"({CAPTAIN_TIMEOUT} сек). Нужно двое.\nКапитаны: {have}")

    @discord.ui.button(label="Стать капитаном", emoji="👑", style=discord.ButtonStyle.success)
    async def take(self, i: discord.Interaction, b: discord.ui.Button):
        member = next((m for m in self.players if m.id == i.user.id), None)
        if not member:
            return await i.response.send_message("Вы не участвуете в этом матче.", ephemeral=True)
        if member in self.caps:
            return await i.response.send_message("Вы уже вызвались капитаном.", ephemeral=True)
        self.caps.append(member)
        if len(self.caps) >= 2:
            await i.response.edit_message(content=self.text(), view=None)
            self.stop()
        else:
            await i.response.edit_message(content=self.text(), view=self)


async def choose_captains(channel, players: list[discord.Member]) -> list[discord.Member]:
    view = CaptainView(players)
    msg = await track_send(channel, view.text(), view=view)
    await view.wait()
    caps = view.caps[:2]
    if len(caps) < 2:  # не хватило добровольцев: добираем случайно
        rest = [m for m in players if m not in caps]
        caps += random.sample(rest, 2 - len(caps))
    try:
        await msg.edit(content=f"👑 Капитаны: {caps[0].mention} и {caps[1].mention}", view=None)
    except discord.HTTPException:
        pass
    return caps


class PickView(discord.ui.View):
    def __init__(self, cap: discord.Member, pool: list[discord.Member]):
        super().__init__(timeout=PICK_TIMEOUT)
        self.cap, self.pool, self.picked = cap, pool, None
        self.select = discord.ui.Select(
            placeholder="Выберите игрока",
            options=[discord.SelectOption(label=f"{m.display_name[:80]} · ELO {get_elo(m.id)}", value=str(m.id)) for m in pool],
        )
        self.select.callback = self.on_pick
        self.add_item(self.select)

    async def on_pick(self, i: discord.Interaction):
        if i.user.id != self.cap.id:
            return await i.response.send_message("Сейчас выбирает другой капитан.", ephemeral=True)
        self.picked = next(m for m in self.pool if str(m.id) == self.select.values[0])
        await i.response.defer()
        self.stop()


class VetoView(discord.ui.View):
    def __init__(self, cap: discord.Member, maps: list[str]):
        super().__init__(timeout=PICK_TIMEOUT)
        self.cap, self.banned = cap, None
        for m in maps:
            btn = discord.ui.Button(label=pretty(m), style=discord.ButtonStyle.secondary)
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
        "cvars": {"hostname": "KZLP FreePick"},
    }


def _rcon_run(c, cmd: str):
    """Ответ CS2 иногда содержит не-UTF-8 байты: команда при этом уже выполнена, ошибку игнорируем."""
    try:
        return c.run(cmd, encoding="latin-1")
    except TypeError:  # старая версия библиотеки без параметра encoding
        try:
            return c.run(cmd)
        except UnicodeDecodeError:
            return ""
    except UnicodeDecodeError:
        return ""


def load_on_server(match_id: int):
    """Блокирующая функция: отправляет команды на CS2-сервер по RCON."""
    cmds = [
        f'matchzy_remote_log_url "{WEB_BASE_URL}/events"',
        'matchzy_remote_log_header_key "Authorization"',
        f'matchzy_remote_log_header_value "{EVENT_TOKEN}"',
        # загрузка демо матча на веб-сервер бота (приходит после окончания карты)
        f'matchzy_demo_upload_url "{WEB_BASE_URL}/demo"',
        'matchzy_demo_upload_header_key "Authorization"',
        f'matchzy_demo_upload_header_value "{EVENT_TOKEN}"',
        f'matchzy_loadmatch_url "{WEB_BASE_URL}/match/{match_id}.json"',
    ]
    with Rcon(SERVER_IP, SERVER_PORT, passwd=RCON_PASSWORD, timeout=10) as c:
        _rcon_run(c, "get5_endmatch")  # сбросить прошлый матч, иначе MatchZy не загрузит новый
        time.sleep(1)
        for cmd in cmds:
            _rcon_run(c, cmd)


def rcon_gamestate():
    """Блокирующая функция: спрашивает у MatchZy состояние матча (get5_status)."""
    with Rcon(SERVER_IP, SERVER_PORT, passwd=RCON_PASSWORD, timeout=10) as c:
        resp = _rcon_run(c, "get5_status") or ""
    m = re.search(r'"gamestate"\s*:\s*"(\w+)"', resp)
    return m.group(1) if m else None


def rcon_kick(user_id, steamid: str):
    """Блокирующая функция: кикает игрока с CS2-сервера (по userid из события MatchZy)."""
    target = str(user_id) if user_id not in (None, "") else steamid
    with Rcon(SERVER_IP, SERVER_PORT, passwd=RCON_PASSWORD, timeout=10) as c:
        _rcon_run(c, f"kickid {target}")


def rcon_pause(pause: bool):
    """Блокирующая функция: ставит матч на паузу или снимает её (админская пауза MatchZy)."""
    primary = "css_forcepause" if pause else "css_forceunpause"
    fallback = "mp_pause_match" if pause else "mp_unpause_match"
    with Rcon(SERVER_IP, SERVER_PORT, passwd=RCON_PASSWORD, timeout=10) as c:
        resp = _rcon_run(c, primary) or ""
        if "unknown command" in resp.lower():
            _rcon_run(c, fallback)


# ----------------------------- ВОЙСЫ КОМАНД --------------------------
async def move_to_voice(guild: discord.Guild, teams):
    """Выдаёт игрокам доступ в войс их команды (Team 1 / Team 2) и перекидывает их туда."""
    await clear_voice_access()  # на случай, если остались доступы от прошлого матча
    for vc_id, team in ((TEAM1_VC, teams[0]), (TEAM2_VC, teams[1])):
        if not vc_id:
            continue
        ch = guild.get_channel(vc_id)
        if not ch:
            log.warning("Голосовой канал %s не найден", vc_id)
            continue
        for m in team:
            member = guild.get_member(m.id)
            if not member:
                continue
            # 1) доступ в канал
            try:
                await ch.set_permissions(member, view_channel=True, connect=True, speak=True,
                                         reason="FreePick: игрок матча")
                S.team_access.append((vc_id, member.id))
            except discord.HTTPException:
                log.exception("Не удалось выдать доступ %s в войс %s", member, vc_id)
                continue
            # 2) перекидываем, если он сейчас в любом войсе
            if member.voice:
                try:
                    await member.move_to(ch)
                except discord.HTTPException:
                    log.exception("Не удалось переместить %s", member)
    save_access()


async def clear_voice_access():
    """Забирает доступ в командные войсы после матча."""
    if not S.team_access:
        return
    for vc_id, member_id in list(S.team_access):
        ch = bot.get_channel(vc_id)
        if not ch:
            continue
        member = ch.guild.get_member(member_id)
        if not member:
            try:
                member = await ch.guild.fetch_member(member_id)
            except discord.HTTPException:
                continue  # игрока уже нет на сервере
        try:
            await ch.set_permissions(member, overwrite=None, reason="FreePick: матч окончен")
        except discord.HTTPException:
            log.exception("Не удалось забрать доступ в войс")
    S.team_access.clear()
    save_access()


async def open_match_chat(origin, players: list[discord.Member]):
    """Когда набрано 10 игроков: открывает отдельный чат только для них (драфт и матч идут там).
    Уведомление о наборе уходит каждому игроку в личные сообщения."""
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
            reason="FreePick: набрано полное количество игроков")
    except discord.HTTPException:
        log.exception("Не удалось создать чат матча (нужно право Manage Channels), используем общий канал")
        return None
    S.match_channel = ch

    # ---- уведомление в ЛС каждому игроку ----
    text = (f"🎯 Набрано {NEED} игроков! Драфт и матч проходят в отдельном чате: "
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
                f" ваши ЛС закрыты. Драфт проходит здесь: {ch.mention}",
                delete_after=30)
        except discord.HTTPException:
            pass

    await track_send(ch, "🎮 " + " ".join(m.mention for m in players) +
                     "\nЭтот чат только для игроков матча. Он удалится, когда матч закончится.")
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


async def handle_disconnect(steamid: str):
    """Игрок вышел с сервера во время матча: пауза + отдельный чат для перерыва."""
    info = S.match_players.get(steamid)
    if not info or not S.live or S.phase != "playing":
        return
    member, team_n = info
    S.absent.add(member.id)
    first = not S.paused
    if first:
        S.paused = True  # ставим флаг сразу, чтобы второй выход не запускал паузу повторно
        try:
            await asyncio.to_thread(rcon_pause, True)
        except Exception:
            log.exception("Не удалось поставить матч на паузу")
        S.break_task = asyncio.create_task(break_timer())

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
            f"Если игрок не вернётся за {BREAK_SECONDS // 60} мин, матч продолжится автоматически. "
            "Капитаны и администрация могут продолжить раньше кнопкой ниже.",
            view=BreakView())
    try:
        await member.send(f"⏸ Вы вышли с сервера, матч #{S.match_id} стоит на паузе. "
                          f"Возвращайтесь: {WEB_BASE_URL}/connect")
    except discord.HTTPException:
        pass


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


async def break_timer():
    await asyncio.sleep(BREAK_SECONDS)
    if S.paused:
        await resume_match("Время ожидания вышло, матч продолжается")


async def resume_match(reason: str):
    """Снимает паузу и закрывает чат перерыва."""
    if not S.paused:
        return
    S.paused = False
    S.absent.clear()
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
    """Удаляет сообщения драфта и матча из чата."""
    msgs, S.chat_msgs = S.chat_msgs, []
    for msg in msgs:
        try:
            await msg.delete()
        except discord.HTTPException:
            pass  # уже удалено или нет прав


async def reset_to_queue():
    # если сервер не прислал результат (ручной сброс, таймер), всё равно пишем итог в канал результатов
    if S.match_id and S.phase == "playing" and S.match_id not in posted_results:
        await post_result({}, dict(S.match_players), S.match_id, note="manual")
    await clear_voice_access()
    await clear_chat()
    await close_match_chat()
    await close_break()
    S.live = False
    S.paused = False
    S.absent.clear()
    S.match_players = {}
    S.captain_ids = set()
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
    if S.draft_check:
        return
    S.draft_check = True
    try:
        await asyncio.sleep(5)  # даём шанс переподключиться
        if S.phase != "draft" or not QUEUE_VC:
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


async def draft(channel, players):
    caps = await choose_captains(channel, players)  # капитаны вызываются сами
    pool = [m for m in players if m not in caps]
    teams = [[caps[0]], [caps[1]]]

    # ---- пики игроков (по очереди) ----
    turn = 0
    while len(pool) > 1:
        cap = caps[turn]
        view = PickView(cap, pool)
        msg = await track_send(channel, f"{cap.mention}, выберите игрока ({PICK_TIMEOUT} сек)", view=view)
        await view.wait()
        picked = view.picked or random.choice(pool)
        pool.remove(picked)
        teams[turn].append(picked)
        await msg.edit(content=f"{cap.mention} выбрал {picked.mention}", view=None)
        turn ^= 1
    teams[turn].append(pool[0])  # последний игрок достаётся автоматически

    # ---- вето карт ----
    maps = MAPS.copy()
    turn = 0
    while len(maps) > 1:
        cap = caps[turn]
        view = VetoView(cap, maps)
        left = ", ".join(pretty(m) for m in maps)
        msg = await track_send(
            channel,
            f"🗺 {cap.mention}, забаньте карту ({PICK_TIMEOUT} сек)\nОсталось: {left}",
            view=view)
        await view.wait()
        banned = view.banned or random.choice(maps)
        maps.remove(banned)
        await msg.edit(content=f"❌ {cap.mention} забанил **{pretty(banned)}**", view=None)
        turn ^= 1
    map_name = maps[0]
    await track_send(channel, f"✅ Выбрана карта: **{pretty(map_name)}**")
    return teams, map_name


async def run_match(channel: discord.abc.Messageable, players: list[discord.Member]):
    origin = channel  # общий канал очереди: туда пишем ошибки
    S.draft_task = asyncio.current_task()  # чтобы драфт можно было отменить, если все вышли из войса
    try:
        S.active_ids = {m.id for m in players}
        chat = await open_match_chat(channel, players)
        if chat:
            channel = chat  # драфт, вето и карточка матча идут в отдельный чат
        else:
            # чат создать не удалось: сообщаем о наборе в общем канале и в ЛС
            await track_send(channel, f"🎯 Набрано {NEED} игроков! " +
                             " ".join(m.mention for m in players))
        if TEST_MODE:
            teams = [players[:1], []]
            map_name = random.choice(MAPS)
            await track_send(channel, f"🧪 Тестовый режим: {players[0].mention}, карта {pretty(map_name)}")
        else:
            teams, map_name = await draft(channel, players)

        # ---- запуск на сервере ----
        match_id = int(time.time())
        S.matches[match_id] = build_match(match_id, teams, map_name)
        S.match_players = {get_steam(m.id): (m, n) for n, t in enumerate(teams, 1) for m in t}
        S.captain_ids = {t[0].id for t in teams if t}
        S.live = False
        S.match_id = match_id
        await asyncio.to_thread(load_on_server, match_id)

        S.phase = "playing"
        S.queue.clear()
        await refresh_panel()
        asyncio.create_task(auto_reset(match_id))
        asyncio.create_task(watch_match(match_id))

        connect = f"connect {SERVER_IP}:{SERVER_PORT}"
        if SERVER_PASSWORD:
            connect += f"; password {SERVER_PASSWORD}"
        e = discord.Embed(title=f"Матч #{match_id} готов — {pretty(map_name)}", color=0x2B2D31)
        for n, t in enumerate(teams, 1):
            e.add_field(name=f"Team {n}" + (f" ({t[0].display_name})" if t else ""),
                        value="\n".join(m.mention for m in t) or "—")
        e.add_field(name="Важно",
                    value="Заходите с **привязанного Steam-аккаунта**: команда выдаётся автоматически по SteamID. "
                          "Подробности пришли вам в личные сообщения.",
                    inline=False)
        e.add_field(name="Подключение (консоль CS2)", value=f"```{connect}```", inline=False)
        link_view = MatchView()
        await track_send(channel, embed=e, view=link_view)
        asyncio.create_task(notify_players(teams, map_name, match_id))

        # ---- доступ в войсы Team 1 / Team 2 и перемещение ----
        if hasattr(channel, "guild") and channel.guild:
            await move_to_voice(channel.guild, teams)

    except Exception as exc:  # любая ошибка: возвращаем систему в очередь
        log.exception("Ошибка при запуске матча")
        await origin.send(f"❌ Не удалось запустить матч: `{exc}`\nОчередь сброшена, нажмите «Играть» заново.")
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


def render_result_card(map_name: str, s1, s2, team_rows: dict, mvp: dict,
                       mvp_avatar: bytes | None, names: tuple) -> bytes:
    """Рисует картинку-табло матча (как в популярных ботах). Блокирующая: вызывать через to_thread."""
    from PIL import Image, ImageDraw, ImageFilter, ImageEnhance

    W, H = 1300, 540
    BLUE, ORANGE, GOLD = (76, 142, 255), (255, 176, 32), (255, 205, 60)

    # --- фон: картинка карты (maps/de_xxx.jpg) или тёмный градиент
    bg = None
    for ext in ("jpg", "jpeg", "png", "webp"):
        path = f"maps/{map_name}.{ext}"
        if os.path.exists(path):
            try:
                src = Image.open(path).convert("RGB")
                k = max(W / src.width, H / src.height)
                src = src.resize((int(src.width * k) + 1, int(src.height * k) + 1))
                l, t = (src.width - W) // 2, (src.height - H) // 2
                bg = src.crop((l, t, l + W, t + H)).filter(ImageFilter.GaussianBlur(3))
                bg = ImageEnhance.Brightness(bg).enhance(0.42)
            except Exception:
                bg = None
            break
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
        od.rounded_rectangle((x0, PY0, x0 + PW, PY1), 18, fill=(8, 12, 26, 195), outline=colors[n] + (160,), width=2)
        od.rounded_rectangle((x0 + 90, PY0 + 12, x0 + PW - 90, PY0 + 56), 10, fill=(6, 10, 22, 220),
                             outline=colors[n] + (255,), width=2)
    img = Image.alpha_composite(img, ov)
    d = ImageDraw.Draw(img)

    f_head, f_name, f_stat = get_font(26), get_font(24), get_font(22, "regular")
    gray, white = (200, 206, 220), (245, 247, 252)

    def fit(text: str, font, max_w: int) -> str:
        if d.textlength(text, font=font) <= max_w:
            return text
        while text and d.textlength(text + "…", font=font) > max_w:
            text = text[:-1]
        return text + "…"

    for n, x0 in panels.items():
        col = colors[n]
        d.text((x0 + PW // 2, PY0 + 34), names[n - 1], font=f_head, fill=col, anchor="mm")
        y = PY0 + 70
        for r in team_rows.get(n, [])[:5]:
            cy = y + 34
            d.ellipse((x0 + 22, cy - 8, x0 + 38, cy + 8), fill=col)
            d.text((x0 + 52, cy), fit(r["name"], f_name, 205), font=f_name, fill=white, anchor="lm")
            kd = r["k"] / r["d"] if r["d"] else float(r["k"])
            d.text((x0 + PW - 150, cy), f"{r['k']}-{r['d']}", font=f_stat, fill=gray, anchor="rm")
            d.text((x0 + PW - 85, cy), f"{kd:.2f}", font=f_stat, fill=gray, anchor="rm")
            d.text((x0 + PW - 20, cy), f"{r['hs']}%", font=f_stat, fill=gray, anchor="rm")
            d.line((x0 + 18, y + 71, x0 + PW - 18, y + 71), fill=(60, 70, 96), width=1)
            y += 76

    # --- центр: аватар MVP, счёт, карта
    cx = W // 2
    R = 78
    ring = Image.new("RGBA", (2 * R + 12, 2 * R + 12), (0, 0, 0, 0))
    rd = ImageDraw.Draw(ring)
    rd.ellipse((0, 0, 2 * R + 11, 2 * R + 11), fill=GOLD + (255,))
    av = None
    if mvp_avatar:
        try:
            av = Image.open(io.BytesIO(mvp_avatar)).convert("RGBA").resize((2 * R, 2 * R))
        except Exception:
            av = None
    if av is None:
        av = Image.new("RGBA", (2 * R, 2 * R), (40, 48, 72, 255))
        ImageDraw.Draw(av).text((R, R), (mvp["name"][:1] or "?").upper(), font=get_font(70), fill=white, anchor="mm")
    mask = Image.new("L", (2 * R, 2 * R), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, 2 * R - 1, 2 * R - 1), fill=255)
    ring.paste(av, (6, 6), mask)
    img.alpha_composite(ring, (cx - R - 6, 62))
    d = ImageDraw.Draw(img)
    d.text((cx, 258), "MVP", font=get_font(50), fill=GOLD, anchor="mm")
    d.text((cx, 304), fit(mvp["name"], get_font(24), 250), font=get_font(24), fill=white, anchor="mm")
    f_score = get_font(72)
    d.text((cx - 78, 380), str(s1), font=f_score, fill=BLUE, anchor="mm")
    d.text((cx, 380), "–", font=get_font(40), fill=gray, anchor="mm")
    d.text((cx + 78, 380), str(s2), font=f_score, fill=ORANGE, anchor="mm")
    d.text((cx, 462), f"КАРТА: {map_name.replace('de_', '').upper()}", font=get_font(24), fill=gray, anchor="mm")

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
result_msgs: dict[int, discord.Message] = {}   # match_id -> сообщение с результатом (чтобы добавить кнопку демо позже)


def demo_view(url: str) -> discord.ui.View:
    v = discord.ui.View()
    v.add_item(discord.ui.Button(label="Скачать демо", emoji="⬇️", url=url))
    return v


def apply_elo(players: dict, win_n: int) -> dict:
    """Пересчитывает ELO по среднему рейтингу команд. Возвращает {discord_id: (было, стало)}."""
    teams = {1: [], 2: []}
    for m, n in players.values():
        teams[n].append(m.id)
    if not teams[1] or not teams[2]:
        return {}
    avg = {n: sum(get_elo(i) for i in ids) / len(ids) for n, ids in teams.items()}
    changes = {}
    for n, ids in teams.items():
        expected = 1 / (1 + 10 ** ((avg[3 - n] - avg[n]) / 400))
        won = 1 if n == win_n else 0
        delta = round(ELO_K * (won - expected))
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
    """Публикует итог матча в канал результатов: карточка-табло + MVP + ELO + демо.
    Без статистики сервера пишет простой список составов (с текущим ELO игроков).
    note: непустая строка = матч завершён вручную/по таймеру (ELO не меняется, на экран ничего не выводится)."""
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
    t1, t2 = data.get("team1") or {}, data.get("team2") or {}
    s1, s2 = t1.get("score"), t2.get("score")
    win = (data.get("winner") or {}).get("team")
    cfg = S.matches.get(mid) or {}
    raw_map = (cfg.get("maplist") or ["?"])[0]
    total_rounds = (s1 or 0) + (s2 or 0)

    # ELO меняем только если известен победитель (при ручном завершении рейтинг не трогаем)
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
            })
        rows.sort(key=lambda r: (-r["k"], -r["adr"]))
        team_rows[n] = rows
    all_rows = team_rows[1] + team_rows[2]

    # --- картинка-табло
    card, mvp = None, None
    if all_rows:
        mvp = max(all_rows, key=lambda r: (r["k"], r["adr"]))
        avatar = None
        if mvp["member"]:
            try:
                avatar = await mvp["member"].display_avatar.replace(size=256, static_format="png").read()
            except discord.HTTPException:
                pass
        try:
            card = await asyncio.to_thread(render_result_card, raw_map, s1 or 0, s2 or 0,
                                           team_rows, mvp, avatar, ("TEAM 1", "TEAM 2"))
        except Exception:
            log.exception("Не удалось нарисовать карточку (установлен ли Pillow?)")

    if card and mvp:
        names = [(cfg.get(f"team{n}") or {}).get("name", f"Team {n}") for n in (1, 2)]
        lines = []
        if win in ("team1", "team2"):
            wn = 1 if win == "team1" else 2
            ws, ls = (s1, s2) if wn == 1 else (s2, s1)
            lines.append(f"**Победитель:** 🏆 {names[wn - 1]} (Счёт: {ws}-{ls})")
        elif s1 is not None and s2 is not None:
            lines.append(f"**Матч завершён** (Счёт: {s1}-{s2})")
        lines.append("")
        lines.append(f"🏅 **MVP — {mvp['name']}** · {mvp['k']}/{mvp['d']}/{mvp['a']} · "
                     f"{mvp['adr']} ADR · {mvp['hs']}% HS")
        e = discord.Embed(title=f"Match #{mid} — РЕЗУЛЬТАТЫ", description="\n".join(lines), color=0xF1C40F)
        e.set_image(url="attachment://result.png")
        if changes:
            elo_lines = [f"{m.mention}: {changes[m.id][1]} ({changes[m.id][1] - changes[m.id][0]:+d})"
                         for m, n in sorted(players.values(), key=lambda x: x[1]) if m.id in changes]
            e.add_field(name="📈 ELO", value="\n".join(elo_lines)[:1024], inline=False)
        e.set_footer(text=f"Карта: {raw_map} · Сыграно раундов: {total_rounds}")
        kwargs = {"embed": e, "file": discord.File(io.BytesIO(card), filename="result.png")}
    else:
        # запасной вариант без картинки (нет статистики или Pillow не установлен)
        def elo_tag(did: int) -> str:
            if did in changes:
                old, new = changes[did]
                return f" · ELO {new} ({new - old:+d})"
            return f" · ELO {get_elo(did)}"  # изменения нет (матч завершён вручную): показываем текущий рейтинг

        lines = []
        if s1 is not None and s2 is not None:
            lines.append(f"**Team 1  {s1} : {s2}  Team 2**")
        if win in ("team1", "team2"):
            lines.append("🏆 Победитель: **" + ("Team 1" if win == "team1" else "Team 2") + "**")
        e = discord.Embed(title=f"Результат матча #{mid} — {pretty(raw_map)}", color=0x57F287)
        e.description = "\n".join(lines) or "Матч завершён."
        for n in (1, 2):
            rows = [(r["k"], f"{r['member'].mention if r['member'] else r['name']}: "
                             f"**{r['k']}/{r['d']}/{r['a']}** · ADR {r['adr']}"
                             f"{elo_tag(r['member'].id) if r['member'] else ''}")
                    for r in team_rows[n]]
            if not rows:  # статистики нет: показываем хотя бы состав команды
                rows = [(0, m.mention + elo_tag(m.id)) for m, tn in players.values() if tn == n]
            t = (t1, t2)[n - 1]
            title = f"Team {n}" + (f" ({t.get('score')})" if t.get("score") is not None else "")
            e.add_field(name=title, value="\n".join(r[1] for r in rows) or "—", inline=False)
        kwargs = {"embed": e}
    try:
        if mid in demo_urls:  # демо уже успело прийти
            kwargs["view"] = demo_view(demo_urls[mid])
        msg = await ch.send(**kwargs)
        result_msgs[mid] = msg
        log.info("Результат матча %s опубликован в #%s", mid, ch.name)
    except discord.HTTPException:
        posted_results.discard(mid)
        log.exception("Не удалось отправить результат (права бота: Send Messages, Embed Links, Attach Files)")


# ----------------------------- БАНЫ (лог в Discord + сайт) -----------
import html as _html

BAN_LOG_CHANNEL = int(os.getenv("BAN_LOG_CHANNEL_ID", "0"))  # 0 = канал, в названии которого есть "баны"

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


# ---- страница со списком банов (/bans)
BANS_PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Список наказаний — KZLP FreePick</title>
<style>
:root{color-scheme:dark}*{box-sizing:border-box}
body{margin:0;min-height:100vh;font-family:Inter,system-ui,"Segoe UI",Roboto,Arial,sans-serif;color:#e8e6f2;
background:radial-gradient(1100px 600px at 15% -10%,#2b1252 0%,transparent 60%),
radial-gradient(900px 600px at 95% 5%,#14244f 0%,transparent 55%),#090613}
.wrap{max-width:1280px;margin:0 auto;padding:32px 20px;display:grid;grid-template-columns:320px 1fr;gap:20px;align-items:start}
@media(max-width:900px){.wrap{grid-template-columns:1fr}}
.card{background:rgba(18,14,34,.86);border:1px solid rgba(255,255,255,.07);border-radius:16px;padding:20px}
h2{margin:0 0 14px;font-size:18px}h3{margin:18px 0 10px;font-size:13px;color:#9a97b0;font-weight:500}
.tag{display:inline-block;background:#5b21d6;color:#fff;border-radius:8px;padding:8px 18px;font-weight:600;font-size:14px;margin-right:6px}
input{width:100%;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.08);border-radius:10px;
color:#e8e6f2;padding:11px 12px;font-size:14px;outline:none}input:focus{border-color:#7c3aed}
.stat{display:flex;justify-content:space-between;padding:11px 12px;border-radius:8px;background:rgba(255,255,255,.04);margin-bottom:8px;font-size:14px}
.stat b{color:#fff}
.tw{overflow-x:auto}
table{width:100%;border-collapse:separate;border-spacing:0 6px;min-width:640px}
th{text-align:left;font-size:12px;color:#9a97b0;padding:6px 12px;font-weight:500}
td{background:rgba(255,255,255,.035);padding:10px 12px;font-size:14px}
td:first-child{border-radius:10px 0 0 10px;width:44px;text-align:center}td:last-child{border-radius:0 10px 10px 0}
.pl{display:flex;align-items:center;gap:10px}
.pl img{width:30px;height:30px;border-radius:8px;object-fit:cover;background:#2a2640}
.b{padding:3px 10px;border-radius:6px;font-size:12px;font-weight:600;white-space:nowrap}
.perm{background:rgba(237,66,69,.16);color:#ff5a5f}
.done{background:rgba(87,242,135,.12);color:#57f287;text-decoration:line-through}
.act{background:rgba(255,176,32,.16);color:#ffb020}
.unb{background:#4b1fb8;color:#d9ccff}
.empty{padding:30px;text-align:center;color:#9a97b0}
</style></head><body><div class="wrap">
<div class="card"><h2>Инфо</h2><span class="tag">Баны</span><span class="tag" style="background:#1f3a8a">FreePick</span>
<h3>Найти нарушителя</h3><input id="q" placeholder="Ник, причина или админ" autocomplete="off">
<h3>Статистика наказаний</h3>
<div class="stat"><span>Всего банов</span><b>__TOTAL__</b></div>
<div class="stat"><span>Активных банов</span><b>__ACTIVE__</b></div>
<div class="stat"><span>Перманентных банов</span><b>__PERM__</b></div></div>
<div class="card"><h2>Список наказаний</h2><div class="tw"><table><thead><tr>
<th>Тип</th><th>Игрок</th><th>Причина</th><th>Срок</th><th>Админ</th></tr></thead><tbody id="rows">__ROWS__</tbody></table>
__EMPTY__</div></div></div>
<script>
const q=document.getElementById('q');
q.addEventListener('input',()=>{const v=q.value.toLowerCase();
document.querySelectorAll('#rows tr').forEach(r=>{r.style.display=r.textContent.toLowerCase().includes(v)?'':'none'})});
</script></body></html>"""


def render_bans_page(rows: list, now: int) -> str:
    esc = _html.escape
    total = len(rows)
    active = sum(1 for r in rows if r[7] is None and (r[6] == 0 or r[6] > now))
    perm = sum(1 for r in rows if r[7] is None and r[6] == 0)
    out = []
    for did, name, avatar, reason, admin, created, expires, unbanned in rows:
        if unbanned:
            badge = '<span class="b unb">Разбанен</span>'
        elif expires == 0:
            badge = '<span class="b perm">Навсегда</span>'
        elif expires <= now:
            badge = f'<span class="b done">{esc(fmt_dur(expires - created))}</span>'
        else:
            badge = f'<span class="b act">{esc(fmt_dur(expires - now))}</span>'
        img = (f'<img src="{esc(avatar, quote=True)}" alt="" loading="lazy" '
               f'onerror="this.style.visibility=\'hidden\'">') if avatar else ""
        out.append(f'<tr><td>🚫</td><td><div class="pl">{img}<span>{esc(name or str(did))}</span></div></td>'
                   f'<td>{esc(reason or "—")}</td><td>{badge}</td><td>{esc(admin or "—")}</td></tr>')
    empty = '' if out else '<div class="empty">Наказаний пока нет</div>'
    return (BANS_PAGE.replace("__TOTAL__", str(total)).replace("__ACTIVE__", str(active))
            .replace("__PERM__", str(perm)).replace("__ROWS__", "".join(out)).replace("__EMPTY__", empty))


async def h_bans(req: web.Request):
    rows = db.execute("SELECT discord_id, name, avatar, reason, admin_name, created, expires, unbanned_at "
                      "FROM ban_log ORDER BY created DESC LIMIT 500").fetchall()
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
    """Принимает файл демо от MatchZy (POST, тело = .dem), сохраняет и добавляет кнопку в сообщение с результатом."""
    if req.headers.get("Authorization") != EVENT_TOKEN:
        log.warning("Загрузка демо отклонена: неверный заголовок Authorization")
        return web.Response(status=401)
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
    try:
        mid = int(req.headers.get("MatchZy-MatchId", ""))
    except ValueError:
        mid = None
    if mid:
        demo_urls[mid] = url
        msg = result_msgs.get(mid)
        if msg:  # результат уже опубликован: добавляем кнопку к нему
            try:
                await msg.edit(view=demo_view(url))
            except discord.HTTPException:
                log.exception("Не удалось добавить кнопку демо к результату")
    return web.Response(text="ok")


async def h_events(req: web.Request):
    if req.headers.get("Authorization") != EVENT_TOKEN:
        log.warning("Событие MatchZy отклонено: неверный заголовок Authorization")
        return web.Response(status=401)
    try:
        data = await req.json()
    except Exception:
        return web.Response(status=400)
    log.info("MatchZy event: %s (matchid=%s)", data.get("event"), data.get("matchid"))
    ev = data.get("event")
    same = S.phase == "playing" and str(data.get("matchid")) == str(S.match_id)
    if ev == "series_end" and same:
        asyncio.create_task(reset_to_queue())
    elif same and ev == "going_live":
        S.live = True            # матч пошёл (после ножей): теперь выход игрока = перерыв
    elif same and ev == "map_result":
        S.live = False           # карта закончилась: выходы игроков больше не считаем
        # снимок игроков берём сразу: series_end может сбросить матч раньше, чем отправится результат
        asyncio.create_task(post_result(data, dict(S.match_players), S.match_id))
    elif same and ev == "player_connect":
        asyncio.create_task(handle_connect(data))
    elif same and ev == "player_disconnect":
        player = data.get("player") or {}
        if not player.get("is_bot"):
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
class FreePickBot(commands.Bot):
    async def setup_hook(self):
        self.add_view(QueueView())
        self.add_view(VerifyView())
        self.add_view(BanLogView())
        await ensure_fonts()  # шрифт с кириллицей для картинки результата

        os.makedirs(DEMO_DIR, exist_ok=True)
        app = web.Application(client_max_size=1024 ** 3)  # демо CS2 может весить сотни МБ
        app.add_routes([
            web.get("/", lambda r: web.Response(text="ok")),  # health check
            web.get(r"/match/{mid:\d+}.json", h_match),
            web.get("/connect", h_connect),
            web.get("/bans", h_bans),
            web.post("/events", h_events),
            web.post("/demo", h_demo),
            web.static("/demos", DEMO_DIR),
            web.get("/auth/steam", h_auth),
            web.get("/auth/steam/callback", h_auth_callback),
        ])
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", WEB_PORT).start()
        log.info("Веб-сервер слушает порт %s", WEB_PORT)

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
@admin
async def fp_link_cmd(i: discord.Interaction, member: discord.Member, steamid64: str):
    steamid64 = steamid64.strip()
    if not re.fullmatch(r"7656119\d{10}", steamid64):
        return await i.response.send_message("Неверный SteamID64.", ephemeral=True)
    row = db.execute("SELECT discord_id FROM links WHERE steamid64=?", (steamid64,)).fetchone()
    if row and row[0] != member.id:
        return await i.response.send_message("Этот SteamID уже привязан к другому аккаунту.", ephemeral=True)
    await i.response.defer(ephemeral=True)
    db.execute("INSERT OR REPLACE INTO links VALUES (?, ?)", (member.id, steamid64))
    db.commit()
    schedule_backup()
    await give_role(member)
    fc = await apply_faceit(member, steamid64)
    await i.followup.send(
        f"✅ {member.mention}: Steam `{steamid64}` привязан."
        + (f" FACEIT LVL {fc['level']}." if fc else ""), ephemeral=True)


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
    await reset_to_queue()
    await i.followup.send("Очередь сброшена, доступы в войсы команд забраны.", ephemeral=True)


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
    # Если бот перезапустился во время матча, а матча уже нет — снимаем старые доступы
    if S.team_access and S.phase != "playing":
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
        vc_id = (TEAM1_VC if team_n == 1 else TEAM2_VC) if team_n else 0
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
    say(f"▶ FACEIT: {'ключ задан' if FACEIT_API_KEY else 'FACEIT_API_KEY не задан (FACEIT-роли выключены)'}")
    say(f"▶ Демо сохраняются в: {DEMO_DIR}")
    if not token:
        say("❌ Не задана переменная DISCORD_TOKEN (Render -> Environment)")
        raise SystemExit(1)
    if not BACKUP_CHANNEL:
        say("⚠ BACKUP_CHANNEL_ID не задан: привязки Steam пропадут при обновлении бота на Render")
    if not RCON_PASSWORD:
        say("⚠ RCON_PASSWORD не задан: запуск матчей на сервере не сработает (задай в Render -> Environment)")
    if not os.getenv("EVENT_TOKEN"):
        say("ℹ EVENT_TOKEN не задан в окружении: создан временный токен (бот сам передаёт его серверу при запуске матча)")
    try:
        bot.run(token)
    except discord.errors.LoginFailure:
        say("❌ Неверный DISCORD_TOKEN. Пересоздайте токен в Discord Developer Portal -> Bot -> Reset Token.")
        raise SystemExit(1)
    except discord.errors.PrivilegedIntentsRequired:
        say("❌ Не включён Server Members Intent: Developer Portal -> Bot -> Privileged Gateway Intents.")
        raise SystemExit(1)
    except Exception as exc:
        import traceback
        say(f"❌ Бот упал: {exc!r}")
        traceback.print_exc()
        raise SystemExit(1)
    say("⚠ bot.run() завершился без ошибки")


if __name__ == "__main__":
    main()
