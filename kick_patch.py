"""
ПАТЧ для bot.py: после окончания матча все игроки кикаются с CS2-сервера.

ШАГ 1. В блок настроек (рядом с BREAK_SECONDS) добавьте:
    KICK_AFTER_MATCH = os.getenv("KICK_AFTER_MATCH", "1") == "1"   # 0 = выключить кик
    KICK_DELAY = int(os.getenv("KICK_DELAY", "20"))                # секунд до кика (чтобы увидеть табло)

ШАГ 2. Вставьте функции ниже (например, после rcon_pause).

ШАГ 3. В reset_to_queue() добавьте две строки:
    - в самое начало функции:
          was_playing = S.phase == "playing"
    - в самый конец функции (после await refresh_panel()):
          if KICK_AFTER_MATCH and was_playing:
              asyncio.create_task(kick_everyone())

reset_to_queue() вызывается при series_end, по кнопке «Матч закончен», по /endmatch и по таймерам,
поэтому кик сработает во всех случаях окончания матча.
"""


# =====================================================================
#  ВСТАВИТЬ (после rcon_pause)
# =====================================================================
def rcon_kick_all() -> int:
    """Блокирующая функция: кикает всех живых игроков (ботов не трогает). Возвращает число кикнутых."""
    with Rcon(SERVER_IP, SERVER_PORT, passwd=RCON_PASSWORD, timeout=10) as c:
        status = _rcon_run(c, "status") or ""
        # строки игроков CS2: "  3    00:35   23    0     active 786432 1.2.3.4:27005 'Name'"
        ids = set(re.findall(
            r"^\s*(\d+)\s+(?:\d+:)?\d{1,2}:\d{2}\s+\d+\s+\d+\s+(?:active|spawning|connected)",
            status, re.M))
        for uid in ids:
            _rcon_run(c, f"kickid {uid}")
    return len(ids)


async def kick_everyone():
    """Через KICK_DELAY секунд после конца матча кикает всех с сервера."""
    try:
        await asyncio.to_thread(_say_kick_notice)
    except Exception:
        log.exception("Не удалось отправить предупреждение на сервер")
    await asyncio.sleep(KICK_DELAY)
    if S.phase == "playing":  # за это время уже начался новый матч: не трогаем
        return
    try:
        n = await asyncio.to_thread(rcon_kick_all)
        log.info("Матч окончен: кикнуто игроков: %s", n)
    except Exception:
        log.exception("Не удалось кикнуть игроков после матча")


def _say_kick_notice():
    with Rcon(SERVER_IP, SERVER_PORT, passwd=RCON_PASSWORD, timeout=10) as c:
        _rcon_run(c, f"say Match finished. Server will be cleared in {KICK_DELAY} sec.")
