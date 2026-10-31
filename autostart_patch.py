"""
ПАТЧ для bot.py: матч стартует сам, когда все игроки зашли на CS2-сервер (никто не пишет .ready).
Заодно меняет префикс [VIBE] в чате MatchZy на [VIBE MIX].

ШАГ 1. В блок настроек (рядом с BREAK_SECONDS) добавьте:
    AUTO_START = os.getenv("AUTO_START", "1") == "1"            # 0 = выключить автостарт
    AUTO_START_DELAY = int(os.getenv("AUTO_START_DELAY", "15")) # сек. ждём, пока все прогрузятся
    CHAT_PREFIX = os.getenv("CHAT_PREFIX", "[{PURPLE}VIBE MIX{Default}] ")

ШАГ 2. В класс State, в __init__, добавьте две строки:
    self.connected: set[str] = set()     # steamid игроков матча, которые сейчас на сервере
    self.auto_started = False            # автостарт уже запущен для этого матча

ШАГ 3. В run_match(), прямо перед строкой  await asyncio.to_thread(load_on_server, match_id)  добавьте:
    S.connected = set()
    S.auto_started = False

ШАГ 4. В load_on_server() в список cmds добавьте строку:
    f'matchzy_chat_prefix "{CHAT_PREFIX}"',

ШАГ 5. В h_events() замените две ветки player_connect / player_disconnect на код из блока «ЗАМЕНИТЬ».

ШАГ 6. Вставьте функции из блока «ВСТАВИТЬ» (например, после handle_connect).
"""

# =====================================================================
#  ЗАМЕНИТЬ в h_events(): ветки player_connect и player_disconnect
# =====================================================================
#     elif same and ev == "player_connect":
#         asyncio.create_task(handle_connect(data))
#         asyncio.create_task(track_connect(data))
#     elif same and ev == "player_disconnect":
#         player = data.get("player") or {}
#         if not player.get("is_bot"):
#             S.connected.discard(str(player.get("steamid", "")))
#             asyncio.create_task(handle_disconnect(str(player.get("steamid", ""))))


# =====================================================================
#  ВСТАВИТЬ (после handle_connect)
# =====================================================================
def rcon_force_start() -> str:
    """Блокирующая функция: принудительный старт матча MatchZy (как админская команда .start)."""
    with Rcon(SERVER_IP, SERVER_PORT, passwd=RCON_PASSWORD, timeout=10) as c:
        return _rcon_run(c, "css_start") or ""


async def track_connect(data: dict):
    """Игрок зашёл на сервер: если на сервере уже все игроки матча, запускаем автостарт."""
    player = data.get("player") or {}
    sid = str(player.get("steamid", ""))
    if player.get("is_bot") or sid not in S.match_players:
        return
    S.connected.add(sid)
    log.info("На сервере %s из %s игроков матча", len(S.connected), len(S.match_players))
    if (AUTO_START and not S.auto_started and not S.live
            and len(S.connected) >= len(S.match_players)):
        S.auto_started = True
        asyncio.create_task(auto_start(S.match_id))


async def auto_start(match_id: int):
    ch = S.match_channel or (S.panel.channel if S.panel else None)
    if ch:
        try:
            await ch.send(f"✅ Все игроки на сервере. Матч стартует через {AUTO_START_DELAY} сек, "
                          "писать .ready не нужно.", delete_after=60)
        except discord.HTTPException:
            pass
    await asyncio.sleep(AUTO_START_DELAY)  # даём всем догрузиться
    if S.phase != "playing" or S.match_id != match_id or S.live:
        return
    if len(S.connected) < len(S.match_players):  # кто-то вышел за время ожидания
        S.auto_started = False
        return
    try:
        state = await asyncio.to_thread(rcon_gamestate)
        if state not in ("warmup", None):  # матч уже идёт (например, начали вручную) — не вмешиваемся
            return
        resp = await asyncio.to_thread(rcon_force_start)
        log.info("Автостарт матча %s, ответ сервера: %r", match_id, resp[:200])
    except Exception:
        S.auto_started = False
        log.exception("Не удалось автоматически стартовать матч")
