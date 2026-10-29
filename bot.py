"""
KZLP FreePick 5x5: очередь -> капитаны -> пики игроков -> вето карт -> запуск матча на CS2 (MatchZy).
После драфта игроки получают доступ в войс своей команды (Team 1 / Team 2) и перемещаются туда.
Авто-старт: как только набралось нужное число игроков, драфт запускается сам.
"""
print("▶ bot.py v15 загружается...", flush=True)
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

TEST_MODE = os.getenv("TEST_MODE", "0") == "1"  # 1 = тест: хватает одного игрока, без драфта
TEAM_SIZE = 1 if TEST_MODE else 5
NEED = 1 if TEST_MODE else TEAM_SIZE * 2
PICK_TIMEOUT = 30            # секунд на пик/бан, потом выбор случайный
MATCH_MAX_SECONDS = 600 if TEST_MODE else 2 * 3600  # автосброс, если series_end не пришёл
BREAK_SECONDS = int(os.getenv("BREAK_SECONDS", "300"))  # сколько ждём вышедшего игрока, потом матч продолжается

# Канал для результатов матчей (0 = бот сам найдёт канал, в названии которого есть "результаты")
RESULTS_CHANNEL = int(os.getenv("RESULTS_CHANNEL_ID", "1565444339084038314"))

# Бэкап привязок: приватный канал для админов, куда бот кладёт файл с привязками (0 = выключено).
# Нужен, потому что на Render файл базы стирается при каждом обновлении.
BACKUP_CHANNEL = int(os.getenv("BACKUP_CHANNEL_ID", "1565489828706000948"))
# Если подключён Render Disk, укажи DB_PATH=/data/freepick.db
DB_PATH = os.getenv("DB_PATH", "freepick.db")

MAPS = ["de_anubis", "de_mirage", "de_inferno", "de_nuke",
        "de_ancient", "de_dust2", "de_overpass"]

# ----------------------------- БАЗА ДАННЫХ ---------------------------
db = sqlite3.connect(DB_PATH)
db.execute("CREATE TABLE IF NOT EXISTS links ("
           "discord_id INTEGER PRIMARY KEY, steamid64 TEXT NOT NULL UNIQUE)")
db.execute("CREATE TABLE IF NOT EXISTS bans ("
           "discord_id INTEGER PRIMARY KEY, reason TEXT)")
db.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT)")
db.commit()


def get_steam(discord_id: int):
    row = db.execute("SELECT steamid64 FROM links WHERE discord_id=?", (discord_id,)).fetchone()
    return row[0] if row else None


def is_banned(discord_id: int) -> bool:
    return db.execute("SELECT 1 FROM bans WHERE discord_id=?", (discord_id,)).fetchone() is not None


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
        "bans": db.execute("SELECT discord_id, reason FROM bans").fetchall(),
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
        for did, reason in data.get("bans", []):
            db.execute("INSERT OR IGNORE INTO bans VALUES (?, ?)", (int(did), reason))
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
    e = discord.Embed(title="Очередь — FreePick", color=0x5865F2)
    e.add_field(
        name="Настройки матча",
        value=("Режим: Соревновательный\nВыбор игроков: Капитаны\n"
               "Выбор капитанов: Добровольно (первые двое в очереди)\n"
               "Выбор карт: Вето\nФормат: BO1"),
        inline=False,
    )
    if S.phase == "queue":
        if QUEUE_VC:
            e.add_field(name="Как играть",
                        value=f"Зайдите в голосовой канал <#{QUEUE_VC}> (нужна Steam-верификация).\n"
                              f"Когда наберётся {NEED} игроков, матч стартует автоматически.",
                        inline=False)
        lines = [f"{n}. {m.mention}{' 👑' if n <= 2 else ''}" for n, m in enumerate(S.queue, 1)]
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
class PickView(discord.ui.View):
    def __init__(self, cap: discord.Member, pool: list[discord.Member]):
        super().__init__(timeout=PICK_TIMEOUT)
        self.cap, self.pool, self.picked = cap, pool, None
        self.select = discord.ui.Select(
            placeholder="Выберите игрока",
            options=[discord.SelectOption(label=m.display_name[:100], value=str(m.id)) for m in pool],
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
    async with S.lock:
        if S.phase != "queue":
            return
        present = [m for m in ch.members
                   if not m.bot and not is_banned(m.id) and get_steam(m.id)]
        ids = {m.id for m in present}
        keep = [m for m in S.queue if m.id in ids]
        kept = {m.id for m in keep}
        S.queue = keep + [m for m in present if m.id not in kept]
        if len(S.queue) >= NEED and S.panel:
            S.queue = S.queue[:NEED]
            S.phase = "draft"  # АВТО-СТАРТ: очередь полная
            players = list(S.queue)
    await refresh_panel()
    if players:
        asyncio.create_task(run_match(S.panel.channel, players))


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
    caps = players[:2]
    pool = players[2:]
    teams = [[caps[0]], [caps[1]]]
    await track_send(channel, f"🎯 Капитаны: {caps[0].mention} и {caps[1].mention}")

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
        e = discord.Embed(title=f"Матч #{match_id} готов — {pretty(map_name)}", color=0x57F287)
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


async def post_result(data: dict, players: dict, match_id):
    """Публикует итог карты (счёт и статистику игроков) в канал результатов."""
    ch = find_results_channel()
    if not ch:
        log.warning("Канал результатов не найден (задай RESULTS_CHANNEL_ID)")
        return
    t1, t2 = data.get("team1") or {}, data.get("team2") or {}
    s1, s2 = t1.get("score", 0), t2.get("score", 0)
    win = (data.get("winner") or {}).get("team")
    winner = "Team 1" if win == "team1" else "Team 2" if win == "team2" else "ничья"
    try:
        map_name = pretty((S.matches.get(int(match_id)) or {}).get("maplist", ["?"])[0])
    except (TypeError, ValueError):
        map_name = "?"
    e = discord.Embed(title=f"Результат матча #{match_id} — {map_name}", color=0x57F287)
    e.description = f"**Team 1  {s1} : {s2}  Team 2**\n🏆 Победитель: **{winner}**"
    for n, t in ((1, t1), (2, t2)):
        rows = []
        for p in t.get("players") or []:
            st = p.get("stats") or {}
            info = players.get(str(p.get("steamid", "")))
            name = info[0].mention if info else p.get("name", "?")
            k, d, a = st.get("kills", 0), st.get("deaths", 0), st.get("assists", 0)
            rounds = st.get("rounds_played") or (s1 + s2) or 1
            adr = round(st.get("damage", 0) / rounds)
            rows.append((k, f"{name}: **{k}/{d}/{a}** · ADR {adr}"))
        rows.sort(key=lambda r: -r[0])
        e.add_field(name=f"Team {n} ({t.get('score', 0)})",
                    value="\n".join(r[1] for r in rows) or "—", inline=False)
    e.set_footer(text="K/D/A · ADR")
    try:
        await ch.send(embed=e)
    except discord.HTTPException:
        log.exception("Не удалось отправить результат (проверь права бота в канале результатов)")


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
        if not get_steam(i.user.id):
            return await i.response.send_message("Сначала пройдите верификацию.", ephemeral=True)
        await give_role(i.user)
        await i.response.send_message("✅ Роли обновлены.", ephemeral=True)

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
    try:
        user = member or await bot.fetch_user(did)
        await user.send(f"✅ Steam привязан: `{steamid}`. Роли выданы, можно заходить в очередь FreePick.")
    except discord.HTTPException:
        pass
    return page("Готово", "Steam привязан. Закройте страницу и вернитесь в Discord.")


# ----------------------------- БОТ -----------------------------------
class FreePickBot(commands.Bot):
    async def setup_hook(self):
        self.add_view(QueueView())
        self.add_view(VerifyView())

        app = web.Application()
        app.add_routes([
            web.get("/", lambda r: web.Response(text="ok")),  # health check
            web.get(r"/match/{mid:\d+}.json", h_match),
            web.get("/connect", h_connect),
            web.post("/events", h_events),
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


@bot.tree.command(name="verify_setup", description="Отправить панель Steam-верификации в этот канал")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@admin
async def verify_setup_cmd(i: discord.Interaction):
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
    db.execute("INSERT OR REPLACE INTO links VALUES (?, ?)", (member.id, steamid64))
    db.commit()
    schedule_backup()
    await give_role(member)
    await i.response.send_message(f"✅ {member.mention}: Steam `{steamid64}` привязан.", ephemeral=True)


@bot.tree.command(name="fp_unlink", description="(админ) Сбросить привязку Steam игрока")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@admin
async def fp_unlink_cmd(i: discord.Interaction, member: discord.Member):
    db.execute("DELETE FROM links WHERE discord_id=?", (member.id,))
    db.commit()
    schedule_backup()
    await i.response.send_message(f"Привязка {member.mention} сброшена, он может пройти верификацию заново.",
                                  ephemeral=True)


@bot.tree.command(name="fp_ban", description="Забанить игрока в FreePick")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@admin
async def ban_cmd(i: discord.Interaction, member: discord.Member, reason: str = "—"):
    db.execute("INSERT OR REPLACE INTO bans VALUES (?, ?)", (member.id, reason))
    db.commit()
    schedule_backup()
    async with S.lock:
        if S.phase == "queue":
            S.queue = [m for m in S.queue if m.id != member.id]
    await refresh_panel()
    await i.response.send_message(f"{member.mention} забанен: {reason}", ephemeral=True)


@bot.tree.command(name="fp_unban", description="Разбанить игрока в FreePick")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@admin
async def unban_cmd(i: discord.Interaction, member: discord.Member):
    db.execute("DELETE FROM bans WHERE discord_id=?", (member.id,))
    db.commit()
    schedule_backup()
    await i.response.send_message(f"{member.mention} разбанен.", ephemeral=True)


@bot.tree.command(name="endmatch", description="Принудительно сбросить матч и очередь")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@admin
async def endmatch_cmd(i: discord.Interaction):
    await i.response.defer(ephemeral=True)
    await reset_to_queue()
    await i.followup.send("Очередь сброшена, доступы в войсы команд забраны.", ephemeral=True)


@bot.event
async def on_ready():
    log.info("Бот запущен как %s", bot.user)
    await restore_backup()  # привязки не должны пропадать при обновлении бота
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
    await sync_queue()


@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if not QUEUE_VC or member.bot:
        return
    was = bool(before.channel and before.channel.id == QUEUE_VC)
    now = bool(after.channel and after.channel.id == QUEUE_VC)
    if was == now:
        return
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
