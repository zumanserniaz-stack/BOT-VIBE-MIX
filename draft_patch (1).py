# =====================================================================
# ПАТЧ для bot.py: драфт как у KZLP.KZ
#   Готов (подтверждение) -> Я стану капитаном -> выбор игроков -> бан карт
# Как применять: читай комментарии "ШАГ N" и меняй соответствующие места в bot.py
# =====================================================================


# ---------------------------------------------------------------------
# ШАГ 1. Настройки (замени старые PICK_TIMEOUT, CAPTAIN_TIMEOUT, MAPS и функцию pretty)
# ---------------------------------------------------------------------
READY_TIMEOUT = 60       # секунд на кнопку «Готов»
PICK_TIMEOUT = 60        # секунд на пик игрока / бан карты
CAPTAIN_TIMEOUT = 60     # секунд на выбор капитанов

MAPS = ["de_mirage", "de_inferno", "de_dust2", "de_ancient", "de_anubis",
        "de_nuke", "de_overpass", "de_train", "de_vertigo"]   # 9 карт -> 8 банов
MAP_TITLES = {"de_dust2": "Dust 2"}


def pretty(map_name: str) -> str:
    return MAP_TITLES.get(map_name, map_name.replace("de_", "").capitalize())


# ---------------------------------------------------------------------
# ШАГ 2. Удали из bot.py старые: CaptainView, choose_captains, PickView, VetoView, draft
# и вставь вместо них всё, что ниже (до ШАГА 3)
# ---------------------------------------------------------------------
def next_draft_no() -> int:
    n = int(kv_get("draft_no") or 0) + 1
    kv_set("draft_no", n)
    return n


def draft_embed(no: int, description: str, color: int = 0x2B2D31) -> discord.Embed:
    return discord.Embed(title=f"Очередь — FreePick #{no}", description=description, color=color)


def nlist(members) -> str:
    return "\n".join(f"`{n:02d}` {m.mention}" for n, m in enumerate(members, 1)) or "—"


# ---------- 1) Подтверждение готовности ----------
class ReadyView(discord.ui.View):
    def __init__(self, players: list[discord.Member], no: int):
        super().__init__(timeout=READY_TIMEOUT)
        self.players, self.no, self.ready = players, no, set()
        self.until = int(time.time()) + READY_TIMEOUT

    def embed(self) -> discord.Embed:
        e = draft_embed(
            self.no,
            "📌 **Матч собран — подтвердите готовность**\n"
            f"⏳ Осталось времени <t:{self.until}:R>\n\n"
            "Состав набран! Определяем капитанов...")
        lines = [f"`{n:02d}` {m.mention} {'✅' if m.id in self.ready else '🔄'}"
                 for n, m in enumerate(self.players, 1)]
        e.add_field(name=f"Готовы {len(self.ready)} из {len(self.players)}",
                    value="\n".join(lines), inline=False)
        e.set_footer(text="Нажмите «Готов». Не успевшие будут убраны из очереди.")
        return e

    @discord.ui.button(label="Готов", emoji="✅", style=discord.ButtonStyle.success)
    async def ok(self, i: discord.Interaction, b: discord.ui.Button):
        if i.user.id not in {m.id for m in self.players}:
            return await i.response.send_message("Вы не участвуете в этом матче.", ephemeral=True)
        self.ready.add(i.user.id)
        await i.response.edit_message(embed=self.embed(), view=self)
        if len(self.ready) >= len(self.players):
            self.stop()


async def ready_check(channel, players: list[discord.Member], no: int) -> bool:
    """True = все нажали «Готов». Иначе не успевших выкидывает из войса очереди и возвращает очередь в набор."""
    view = ReadyView(players, no)
    msg = await track_send(channel, content=" ".join(m.mention for m in players),
                           embed=view.embed(), view=view)
    await view.wait()
    missing = [m for m in players if m.id not in view.ready]
    if not missing:
        await msg.edit(embed=draft_embed(no, "✅ Все игроки подтвердили готовность!", 0x57F287), view=None)
        return True

    missing_ids = {m.id for m in missing}
    for m in missing:  # убираем из войса очереди, иначе sync_queue сразу вернёт их обратно
        if QUEUE_VC and m.voice and m.voice.channel and m.voice.channel.id == QUEUE_VC:
            try:
                await m.move_to(None, reason="FreePick: не подтвердил готовность")
            except discord.HTTPException:
                pass
    try:
        await channel.send("⚠ Не все подтвердили готовность. Убраны из очереди: "
                           + ", ".join(m.mention for m in missing), delete_after=30,
                           allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        pass
    await clear_chat()
    async with S.lock:
        S.phase = "queue"
        S.queue = [m for m in S.queue if m.id not in missing_ids]
        S.active_ids.clear()
        S.draft_task = None
    await refresh_panel()
    await sync_queue()  # если в войсе остались/зашли другие, набор продолжится
    return False


# ---------- 2) Капитаны ----------
class CaptainView(discord.ui.View):
    def __init__(self, players: list[discord.Member], no: int):
        super().__init__(timeout=CAPTAIN_TIMEOUT)
        self.players, self.no, self.caps = players, no, []
        self.until = int(time.time()) + CAPTAIN_TIMEOUT

    def embed(self) -> discord.Embed:
        e = draft_embed(
            self.no,
            "Состав набран! Капитаны выбираются **добровольно**.\n"
            f"Нажмите «Я стану капитаном» — нужно ещё **{2 - len(self.caps)}** из 2.\n"
            f"⏳ Через <t:{self.until}:R> недостающих выберу случайно.")
        e.add_field(name=f"Капитаны — {len(self.caps)} из 2", value=nlist(self.caps), inline=False)
        return e

    @discord.ui.button(label="Я стану капитаном", style=discord.ButtonStyle.primary)
    async def take(self, i: discord.Interaction, b: discord.ui.Button):
        member = next((m for m in self.players if m.id == i.user.id), None)
        if not member:
            return await i.response.send_message("Вы не участвуете в этом матче.", ephemeral=True)
        if member in self.caps:
            return await i.response.send_message("Вы уже вызвались капитаном.", ephemeral=True)
        self.caps.append(member)
        await i.response.edit_message(embed=self.embed(), view=self)
        if len(self.caps) >= 2:
            self.stop()


# ---------- 3) Выбор игроков ----------
class PickView(discord.ui.View):
    def __init__(self, cap: discord.Member, pool: list[discord.Member]):
        super().__init__(timeout=PICK_TIMEOUT)
        self.cap, self.pool, self.picked = cap, pool, None
        self.until = int(time.time()) + PICK_TIMEOUT
        for m in pool:
            btn = discord.ui.Button(label=f"{m.display_name[:60]} | ELO: {get_elo(m.id)}",
                                    style=discord.ButtonStyle.secondary)
            btn.callback = self._make_cb(m)
            self.add_item(btn)

    def _make_cb(self, m: discord.Member):
        async def cb(i: discord.Interaction):
            if i.user.id != self.cap.id:
                return await i.response.send_message("Сейчас выбирает другой капитан.", ephemeral=True)
            self.picked = m
            await i.response.defer()
            self.stop()
        return cb


def pick_embed(no, caps, teams, pool, cap, until) -> discord.Embed:
    e = draft_embed(no, f"Ход капитана {cap.mention} — выберите игрока кнопками ниже.\n"
                        f"⏳ Ход закончится <t:{until}:R>")
    for c, t in zip(caps, teams):
        e.add_field(name=f"team_{c.display_name}", value=nlist(t))
    e.add_field(name=f"Свободные игроки: {len(pool)}", value=nlist(pool), inline=False)
    return e


# ---------- 4) Бан карт ----------
class VetoView(discord.ui.View):
    def __init__(self, cap: discord.Member, maps: list[str]):
        super().__init__(timeout=PICK_TIMEOUT)
        self.cap, self.banned = cap, None
        self.until = int(time.time()) + PICK_TIMEOUT
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


def veto_embed(no, cap, maps, banned, last, until) -> discord.Embed:
    e = draft_embed(
        no,
        f"**Выбор карт** — надо убрать ещё **{len(maps) - 1}** карт.\n"
        f"👤 Ходит капитан {cap.mention}\n"
        f"⏳ Ход закончится <t:{until}:R>\n\n"
        "Капитаны набрали составы. Переходим к бану карт.\n"
        f"Последний игрок {last.mention} ушёл в состав автоматически.")
    e.add_field(name=f"🚫 Забанено: {len(banned)}",
                value="\n".join(f"~~{pretty(m)}~~" for m in banned) or "Пока ничего.")
    e.add_field(name=f"▸ Осталось: {len(maps)} из {len(MAPS)}",
                value="\n".join(pretty(m) for m in maps))
    return e


# ---------- Весь драфт: ОДНО сообщение, которое редактируется на каждом этапе ----------
async def draft(channel, players, no: int):
    # капитаны
    cview = CaptainView(players, no)
    msg = await track_send(channel, embed=cview.embed(), view=cview)
    await cview.wait()
    caps = cview.caps[:2]
    if len(caps) < 2:  # не хватило добровольцев: добираем случайно
        rest = [m for m in players if m not in caps]
        caps += random.sample(rest, 2 - len(caps))
    pool = [m for m in players if m not in caps]
    teams = [[caps[0]], [caps[1]]]

    # пики игроков (по очереди)
    turn = 0
    while len(pool) > 1:
        cap = caps[turn]
        view = PickView(cap, pool)
        await msg.edit(embed=pick_embed(no, caps, teams, pool, cap, view.until), view=view)
        await view.wait()
        picked = view.picked or random.choice(pool)
        pool.remove(picked)
        teams[turn].append(picked)
        turn ^= 1
    last = pool[0]
    teams[turn].append(last)  # последний игрок достаётся автоматически

    # бан карт
    maps, banned, turn = MAPS.copy(), [], 0
    while len(maps) > 1:
        cap = caps[turn]
        view = VetoView(cap, maps)
        await msg.edit(embed=veto_embed(no, cap, maps, banned, last, view.until), view=view)
        await view.wait()
        b = view.banned or random.choice(maps)
        maps.remove(b)
        banned.append(b)
        turn ^= 1
    map_name = maps[0]

    e = draft_embed(no, f"✅ Выбрана карта: **{pretty(map_name)}**", 0x57F287)
    for c, t in zip(caps, teams):
        e.add_field(name=f"team_{c.display_name}", value=nlist(t))
    await msg.edit(embed=e, view=None)
    return teams, map_name


# ---------------------------------------------------------------------
# ШАГ 3. В run_match() замени начало (до "# ---- запуск на сервере ----") на это:
# ---------------------------------------------------------------------
async def run_match(channel: discord.abc.Messageable, players: list[discord.Member]):
    origin = channel  # общий канал очереди: туда пишем ошибки
    S.draft_task = asyncio.current_task()
    try:
        S.active_ids = {m.id for m in players}
        no = next_draft_no()

        # --- кнопка «Готов» в канале очереди (в тесте пропускаем)
        if not TEST_MODE:
            if not await ready_check(channel, players, no):
                return

        chat = await open_match_chat(channel, players)
        if chat:
            channel = chat  # драфт и карточка матча идут в отдельный чат
        # (если хочешь, чтобы драфт шёл прямо в канале очереди, как у KZLP:
        #  удали две строки выше про open_match_chat/channel = chat)

        if TEST_MODE:
            teams = [players[:1], []]
            map_name = random.choice(MAPS)
            await track_send(channel, f"🧪 Тестовый режим: {players[0].mention}, карта {pretty(map_name)}")
        else:
            teams, map_name = await draft(channel, players, no)

        # ... дальше весь код "# ---- запуск на сервере ----" остаётся БЕЗ изменений ...


# ---------------------------------------------------------------------
# ШАГ 4. Результаты (как у KZLP): мелкие правки
# ---------------------------------------------------------------------
# 4.1  в demo_view():       label="Скачать демо"  ->  label="Скачать демку"
# 4.2  в post_result():     (Счёт: ...)           ->  (Счет: ...)
# 4.3  в post_result(), вызов render_result_card:  ("TEAM 1", "TEAM 2")  ->  ("TEAM A", "TEAM B")
# ELO в результатах уже считается (apply_elo) и пишется полем «📈 ELO» под табло.

# ---------------------------------------------------------------------
# ШАГ 5. Бэкап счётчика матчей: в _dump() замени
#   keys = ("panel_channel", "panel_message", "team_access")
# на
#   keys = ("panel_channel", "panel_message", "team_access", "draft_no")
# ---------------------------------------------------------------------
