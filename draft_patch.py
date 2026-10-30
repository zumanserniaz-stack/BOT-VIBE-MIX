"""
ПАТЧ для bot.py v26: 1) кнопка «Готов» (ready-check), 2) пики игроков кнопками как на скриншоте.

Что сделать в bot.py (4 шага):

ШАГ 1. В блок настроек (рядом с PICK_TIMEOUT) добавьте:
    READY_TIMEOUT = int(os.getenv("READY_TIMEOUT", "60"))   # секунд на кнопку «Готов»

ШАГ 2. В _dump() добавьте "match_no" в кортеж keys, чтобы номер матча не сбрасывался при деплое:
    keys = ("panel_channel", "panel_message", "team_access", "match_no")

ШАГ 3. Класс PickView и функцию draft() в bot.py ЗАМЕНИТЕ целиком кодом из блока «ЗАМЕНИТЬ» ниже.
        Блок «ДОБАВИТЬ» вставьте перед функцией run_match().

ШАГ 4. В run_match() после строки  S.active_ids = {m.id for m in players}  добавьте:
        if not TEST_MODE and not await ready_check(channel, players):
            return
"""

# =====================================================================
#  ДОБАВИТЬ (перед run_match): кнопка «Готов»
# =====================================================================
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
    for m in absent:
        if QUEUE_VC and m.voice and m.voice.channel and m.voice.channel.id == QUEUE_VC:
            try:
                await m.move_to(None)  # убираем из войса очереди
            except discord.HTTPException:
                pass
        try:
            await m.send("⏰ Вы не нажали «Готов» и были убраны из очереди. Зайдите снова, когда будете готовы.")
        except discord.HTTPException:
            pass
    async with S.lock:
        S.phase = "queue"
        S.queue = ready_players          # готовые остаются в очереди
        S.active_ids.clear()
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


# =====================================================================
#  ЗАМЕНИТЬ: PickView + draft()
# =====================================================================
def next_match_no() -> int:
    n = int(kv_get("match_no") or 0) + 1
    kv_set("match_no", n)
    schedule_backup()
    return n


def draft_embed(no: int, teams, pool, cap=None, done: bool = False) -> discord.Embed:
    """Табло драфта: две команды + свободные игроки (как на скриншоте)."""
    e = discord.Embed(title=f"Очередь — FreePick #{no}", color=0x2B2D31)
    if done:
        e.description = "✅ Драфт завершён."
    elif cap:
        e.description = f"Ход капитана {cap.mention} — выберите игрока кнопками ниже."
    for t in teams:
        lines = [f"`{n:02d}` {m.mention}" for n, m in enumerate(t, 1)]
        e.add_field(name=f"team_{t[0].display_name}"[:256], value="\n".join(lines), inline=True)
    if pool:
        free = [f"`{n:02d}` {m.mention}" for n, m in enumerate(pool, 1)]
        e.add_field(name=f"Свободные игроки: {len(pool)}", value="\n".join(free), inline=False)
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


async def draft(channel, players):
    no = next_match_no()
    caps = await choose_captains(channel, players)  # капитаны вызываются сами
    pool = [m for m in players if m not in caps]
    teams = [[caps[0]], [caps[1]]]

    # ---- пики игроков: одно сообщение, которое обновляется после каждого выбора ----
    turn = 0
    msg = None
    while len(pool) > 1:
        cap = caps[turn]
        view = PickView(cap, pool)
        emb = draft_embed(no, teams, pool, cap)
        if msg is None:
            msg = await track_send(channel, embed=emb, view=view)
        else:
            await msg.edit(embed=emb, view=view)
        await view.wait()
        picked = view.picked or random.choice(pool)  # не успел: случайный игрок
        pool.remove(picked)
        teams[turn].append(picked)
        turn ^= 1
    teams[turn].append(pool[0])  # последний игрок достаётся автоматически
    await msg.edit(embed=draft_embed(no, teams, [], done=True), view=None)

    # ---- вето карт (без изменений) ----
    maps = MAPS.copy()
    turn = 0
    while len(maps) > 1:
        cap = caps[turn]
        view = VetoView(cap, maps)
        left = ", ".join(pretty(m) for m in maps)
        vmsg = await track_send(
            channel,
            f"🗺 {cap.mention}, забаньте карту ({PICK_TIMEOUT} сек)\nОсталось: {left}",
            view=view)
        await view.wait()
        banned = view.banned or random.choice(maps)
        maps.remove(banned)
        await vmsg.edit(content=f"❌ {cap.mention} забанил **{pretty(banned)}**", view=None)
        turn ^= 1
    map_name = maps[0]
    await track_send(channel, f"✅ Выбрана карта: **{pretty(map_name)}**")
    return teams, map_name
