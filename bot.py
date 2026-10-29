import asyncio
import logging
import os
import random
import re
import sqlite3
import time
 
import discord
from aiohttp import web
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from rcon.source import Client as Rcon
 
load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("freepick")
 
# ----------------------------- НАСТРОЙКИ -----------------------------
TOKEN = os.environ["DISCORD_TOKEN"]
SERVER_IP = os.getenv("SERVER_IP", "79.143.20.205")
SERVER_PORT = int(os.getenv("SERVER_PORT", "27017"))
RCON_PASSWORD = os.environ["ArniAlash22062008Nurlan"]
SERVER_PASSWORD = os.getenv("SERVER_PASSWORD", "")      # sv_password, если есть
 
# Публичный адрес веб-сервера бота (его должен видеть CS2-сервер), например http://1.2.3.4:8080
WEB_BASE_URL = os.getenv("WEB_BASE_URL", "").rstrip("/")
WEB_PORT = int(os.getenv("WEB_PORT", "8080"))
EVENT_TOKEN = os.getenv("EVENT_TOKEN", "change-me")     # секрет для событий MatchZy
 
# Голосовые каналы команд (необязательно, 0 = выключено)
TEAM1_VC = int(os.getenv("TEAM1_VC_ID", "0"))
TEAM2_VC = int(os.getenv("TEAM2_VC_ID", "0"))
 
TEAM_SIZE = 5
NEED = TEAM_SIZE * 2
PICK_TIMEOUT = 30  # секунд на пик/бан, потом выбор случайный
 
MAPS = ["de_anubis", "de_mirage", "de_inferno", "de_nuke",
        "de_ancient", "de_dust2", "de_overpass"]
 
# ----------------------------- БАЗА ДАННЫХ ---------------------------
db = sqlite3.connect("freepick.db")
db.execute("CREATE TABLE IF NOT EXISTS links ("
           "discord_id INTEGER PRIMARY KEY, steamid64 TEXT NOT NULL UNIQUE)")
db.execute("CREATE TABLE IF NOT EXISTS bans ("
           "discord_id INTEGER PRIMARY KEY, reason TEXT)")
db.commit()
 
 
def get_steam(discord_id: int):
    row = db.execute("SELECT steamid64 FROM links WHERE discord_id=?", (discord_id,)).fetchone()
    return row[0] if row else None
 
 
def is_banned(discord_id: int) -> bool:
    return db.execute("SELECT 1 FROM bans WHERE discord_id=?", (discord_id,)).fetchone() is not None
 
 
# ----------------------------- СОСТОЯНИЕ -----------------------------
class State:
    def __init__(self):
        self.queue: list[discord.Member] = []
        self.phase = "queue"          # queue | draft | playing
        self.panel: discord.Message | None = None
        self.match_id: int | None = None
        self.matches: dict[int, dict] = {}
        self.lock = asyncio.Lock()
 
 
S = State()
 
 
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
            await S.panel.edit(embed=panel_embed(), view=QueueView())
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
                err = "Сначала привяжите Steam: `/link <SteamID64>`"
            elif S.phase != "queue":
                err = "Сейчас идёт набор/матч, дождитесь окончания."
            elif any(m.id == i.user.id for m in S.queue):
                err = "Вы уже в очереди."
            else:
                S.queue.append(i.user)
                if len(S.queue) >= NEED:
                    full = True
                    S.phase = "draft"
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
        return {"name": f"team_{t[0].display_name}",
                "players": {get_steam(m.id): m.display_name for m in t}}
 
    return {
        "matchid": match_id,
        "num_maps": 1,
        "maplist": [map_name],
        "map_sides": ["knife"],
        "players_per_team": TEAM_SIZE,
        "clinch_series": True,
        "team1": team(teams[0]),
        "team2": team(teams[1]),
        "cvars": {"hostname": "KZLP FreePick"},
    }
 
 
def load_on_server(match_id: int):
    """Блокирующая функция: отправляет команды на CS2-сервер по RCON."""
    if not WEB_BASE_URL:
        raise RuntimeError("Не задан WEB_BASE_URL (публичный адрес веб-сервера бота)")
    cmds = [
        f'matchzy_remote_log_url "{WEB_BASE_URL}/events"',
        'matchzy_remote_log_header_key "Authorization"',
        f'matchzy_remote_log_header_value "{EVENT_TOKEN}"',
        f'matchzy_loadmatch_url "{WEB_BASE_URL}/match/{match_id}.json"',
    ]
    with Rcon(SERVER_IP, SERVER_PORT, passwd=RCON_PASSWORD, timeout=10) as c:
        for cmd in cmds:
            c.run(cmd)
 
 
async def move_to_voice(guild: discord.Guild, teams):
    for vc_id, team in ((TEAM1_VC, teams[0]), (TEAM2_VC, teams[1])):
        if not vc_id:
            continue
        ch = guild.get_channel(vc_id)
        for m in team:
            member = guild.get_member(m.id)
            if ch and member and member.voice:
                try:
                    await member.move_to(ch)
                except discord.HTTPException:
                    pass
 
 
async def reset_to_queue():
    async with S.lock:
        S.phase = "queue"
        S.queue.clear()
        S.match_id = None
    await refresh_panel()
 
 
async def run_match(channel: discord.abc.Messageable, players: list[discord.Member]):
    try:
        caps = players[:2]
        pool = players[2:]
        teams = [[caps[0]], [caps[1]]]
        await channel.send(f"🎯 Набрано {NEED} игроков! Капитаны: {caps[0].mention} и {caps[1].mention}")
 
        # ---- пики игроков (по очереди) ----
        turn = 0
        while len(pool) > 1:
            cap = caps[turn]
            view = PickView(cap, pool)
            msg = await channel.send(f"{cap.mention}, выберите игрока ({PICK_TIMEOUT} сек)", view=view)
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
            msg = await channel.send(f"{cap.mention}, забаньте карту ({PICK_TIMEOUT} сек)", view=view)
            await view.wait()
            banned = view.banned or random.choice(maps)
            maps.remove(banned)
            await msg.edit(content=f"{cap.mention} забанил **{pretty(banned)}**", view=None)
            turn ^= 1
        map_name = maps[0]
 
        # ---- запуск на сервере ----
        match_id = int(time.time())
        S.matches[match_id] = build_match(match_id, teams, map_name)
        S.match_id = match_id
        await asyncio.to_thread(load_on_server, match_id)
 
        S.phase = "playing"
        S.queue.clear()
        await refresh_panel()
 
        connect = f"connect {SERVER_IP}:{SERVER_PORT}"
        if SERVER_PASSWORD:
            connect += f"; password {SERVER_PASSWORD}"
        e = discord.Embed(title=f"Матч #{match_id} готов — {pretty(map_name)}", color=0x57F287)
        e.add_field(name=f"Команда {teams[0][0].display_name}",
                    value="\n".join(m.mention for m in teams[0]))
        e.add_field(name=f"Команда {teams[1][0].display_name}",
                    value="\n".join(m.mention for m in teams[1]))
        e.add_field(name="Подключение (консоль CS2)", value=f"```{connect}```", inline=False)
        link_view = discord.ui.View()
        link_view.add_item(discord.ui.Button(label="Подключиться", url=f"{WEB_BASE_URL}/connect"))
        await channel.send(embed=e, view=link_view)
 
        if hasattr(channel, "guild") and channel.guild:
            await move_to_voice(channel.guild, teams)
 
    except Exception as exc:  # любая ошибка: возвращаем систему в очередь
        log.exception("Ошибка при запуске матча")
        await channel.send(f"❌ Не удалось запустить матч: `{exc}`\nОчередь сброшена, нажмите «Играть» заново.")
        await reset_to_queue()
 
 
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
        return web.Response(status=401)
    try:
        data = await req.json()
    except Exception:
        return web.Response(status=400)
    if (data.get("event") == "series_end" and S.phase == "playing"
            and str(data.get("matchid")) == str(S.match_id)):
        asyncio.create_task(reset_to_queue())
    return web.Response(text="ok")
 
 
# ----------------------------- БОТ -----------------------------------
class FreePickBot(commands.Bot):
    async def setup_hook(self):
        self.add_view(QueueView())
        app = web.Application()
        app.add_routes([
            web.get(r"/match/{mid:\d+}.json", h_match),
            web.get("/connect", h_connect),
            web.post("/events", h_events),
        ])
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", WEB_PORT).start()
        await self.tree.sync()
 
 
bot = FreePickBot(command_prefix="!", intents=discord.Intents.default())
admin = app_commands.checks.has_permissions(administrator=True)
 
 
@bot.tree.command(name="setup", description="Отправить панель очереди FreePick в этот канал")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@admin
async def setup_cmd(i: discord.Interaction):
    S.panel = await i.channel.send(embed=panel_embed(), view=QueueView())
    await i.response.send_message("Панель отправлена.", ephemeral=True)
 
 
@bot.tree.command(name="link", description="Привязать свой SteamID64")
@app_commands.describe(steamid64="17 цифр, начинается с 7656119")
async def link_cmd(i: discord.Interaction, steamid64: str):
    steamid64 = steamid64.strip()
    if not re.fullmatch(r"7656119\d{10}", steamid64):
        return await i.response.send_message("Неверный SteamID64. Пример: `76561198000000000`.", ephemeral=True)
    try:
        db.execute("INSERT OR REPLACE INTO links VALUES (?, ?)", (i.user.id, steamid64))
        db.commit()
    except sqlite3.IntegrityError:
        return await i.response.send_message("Этот SteamID уже привязан к другому аккаунту.", ephemeral=True)
    await i.response.send_message(f"✅ Steam привязан: `{steamid64}`", ephemeral=True)
 
 
@bot.tree.command(name="fp_ban", description="Забанить игрока в FreePick")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@admin
async def ban_cmd(i: discord.Interaction, member: discord.Member, reason: str = "—"):
    db.execute("INSERT OR REPLACE INTO bans VALUES (?, ?)", (member.id, reason))
    db.commit()
    async with S.lock:
        S.queue = [m for m in S.queue if m.id != member.id] if S.phase == "queue" else S.queue
    await refresh_panel()
    await i.response.send_message(f"{member.mention} забанен: {reason}", ephemeral=True)
 
 
@bot.tree.command(name="fp_unban", description="Разбанить игрока в FreePick")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@admin
async def unban_cmd(i: discord.Interaction, member: discord.Member):
    db.execute("DELETE FROM bans WHERE discord_id=?", (member.id,))
    db.commit()
    await i.response.send_message(f"{member.mention} разбанен.", ephemeral=True)
 
 
@bot.tree.command(name="endmatch", description="Принудительно сбросить матч и очередь")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@admin
async def endmatch_cmd(i: discord.Interaction):
    await reset_to_queue()
    await i.response.send_message("Очередь сброшена.", ephemeral=True)
 
 
@bot.event
async def on_ready():
    log.info("Бот запущен как %s", bot.user)
# --------------------------------------------------
# RUN BOT WITH SAFE TOKEN CHECK
# --------------------------------------------------
raw_token = os.getenv("DISCORD_TOKEN")

if not raw_token:
    print("❌ КРИТИЧЕСКАЯ ОШИБКА: Переменная DISCORD_TOKEN не найдена в Environment на Render!")
else:
    token = raw_token.strip().strip('"').strip("'")
    try:
        bot.run(token)
    except discord.errors.LoginFailure:
        print("❌ ОШИБКА АВТОРИЗАЦИИ: Неверный DISCORD_TOKEN! Пересоздайте токен в Discord Developer Portal.")
    except Exception as e:
        print(f"❌ НЕИЗВЕСТНАЯ ОШИБКА ПРИ ЗАПУСКЕ: {e}")
