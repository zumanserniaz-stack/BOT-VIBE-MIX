import os
import asyncio
import aiohttp
import io
import random
import collections
import discord
import traceback
from flask import Flask
from threading import Thread
import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, View
# --------------------------------------------------
# WEB SERVER FOR RENDER 24/7
# --------------------------------------------------
app = Flask('')

@app.route('/')
def home():
    return "ALASH PROJECT BOT is Alive!"

def run_web():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web, daemon=True)
    t.start()

keep_alive()

# ===== Discord Bot =====
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ================== ВСТАВЬ ID СВОЕГО СЕРВЕРА ==================
GUILD_ID = 1548371779523837952  # замени на свой
# =============================================================

SERVER_IP = "45.86.81.37:55031"
CONNECT_LINK = f"steam://connect/{SERVER_IP}"
MAX_PLAYERS = 10
MAPS = ["Mirage", "Inferno", "Dust 2", "Ancient", "Anubis", "Nuke", "Overpass", "Train", "Vertigo"]

class SetupView(View):
    def __init__(self):
        super().__init__(timeout=300)
        self.format = "5x5"
        self.bo = "BO1"
        self.map_method = "Вето"

    @discord.ui.button(label="5x5", style=discord.ButtonStyle.primary, row=0)
    async def btn_5x5(self, interaction: discord.Interaction, button: Button):
        self.format = "5x5"
        await self.update(interaction)

    @discord.ui.button(label="4x4", style=discord.ButtonStyle.secondary, row=0)
    async def btn_4x4(self, interaction: discord.Interaction, button: Button):
        self.format = "4x4"
        await self.update(interaction)

    @discord.ui.button(label="3x3", style=discord.ButtonStyle.secondary, row=0)
    async def btn_3x3(self, interaction: discord.Interaction, button: Button):
        self.format = "3x3"
        await self.update(interaction)

    @discord.ui.button(label="BO1", style=discord.ButtonStyle.primary, row=1)
    async def btn_bo1(self, interaction: discord.Interaction, button: Button):
        self.bo = "BO1"
        await self.update(interaction)

    @discord.ui.button(label="Вето", style=discord.ButtonStyle.primary, row=1)
    async def btn_veto(self, interaction: discord.Interaction, button: Button):
        self.map_method = "Вето"
        await self.update(interaction)

    @discord.ui.button(label="Создать своё лобби", style=discord.ButtonStyle.success, row=3)
    async def create_lobby(self, interaction: discord.Interaction, button: Button):
        lobby_view = LobbyView(self.format, self.bo, self.map_method)
        embed = discord.Embed(title="Очередь — FreePick", color=0x2b2d31)
        embed.add_field(name="Настройки матча", value=(
            f"**Режим:** Соревновательный\n"
            f"**Выбор игроков:** Капитаны\n"
            f"**Выбор капитанов:** Добровольно\n"
            f"**Выбор карт:** {self.map_method}\n"
            f"**Формат:** {self.bo}"
        ), inline=False)
        embed.add_field(name="Игроки", value=f"**0 из {MAX_PLAYERS}**\nОжидаем игроков...", inline=False)
        
        await interaction.response.send_message(embed=embed, view=lobby_view)
        self.stop()

    async def update(self, interaction):
        embed = discord.Embed(title="Настройки создания своего лобби", color=0x2b2d31)
        embed.description = (
            f"**Тип очереди:** Капитаны\n"
            f"**Формат:** {self.format} | {self.bo}\n"
            f"**Капитаны:** Доброволец (первый пикнувший игрока)\n"
            f"**Видимость:** Очередь доступна для всех\n"
            f"**Доступ забаненным:** Запрещён\n"
            f"**Метод выбора карт:** {self.map_method}\n"
            f"**Карты ({len(MAPS)}):** {', '.join(MAPS)}"
        )
        await interaction.response.edit_message(embed=embed, view=self)

class LobbyView(View):
    def __init__(self, format_, bo, map_method):
        super().__init__(timeout=None)
        self.queue = []
        self.format = format_
        self.bo = bo
        self.map_method = map_method

    @discord.ui.button(label="Присоединиться", style=discord.ButtonStyle.green)
    async def join(self, interaction: discord.Interaction, button: Button):
        user = interaction.user
        if user in self.queue:
            await interaction.response.send_message("Ты уже в очереди", ephemeral=True)
            return
        if len(self.queue) >= MAX_PLAYERS:
            await interaction.response.send_message("Лобби полное", ephemeral=True)
            return

        self.queue.append(user)
        
        embed = discord.Embed(title="Очередь — FreePick", color=0x2b2d31)
        embed.add_field(name="Настройки матча", value=(
            f"**Режим:** Соревновательный\n"
            f"**Выбор игроков:** Капитаны\n"
            f"**Выбор капитанов:** Добровольно\n"
            f"**Выбор карт:** {self.map_method}\n"
            f"**Формат:** {self.bo}"
        ), inline=False)
        embed.add_field(name="Игроки", value=f"**{len(self.queue)} из {MAX_PLAYERS}**\nОжидаем игроков...", inline=False)
        
        if self.queue:
            players = "\n".join([p.mention for p in self.queue])
            embed.add_field(name="В очереди", value=players, inline=False)

        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message(f"Ты зашёл ({len(self.queue)}/{MAX_PLAYERS})", ephemeral=True)

        if len(self.queue) == MAX_PLAYERS:
            captains = [self.queue[0], self.queue[1]]
            await interaction.channel.send(
                f"**Капитаны:** {captains[0].mention} (CT) и {captains[1].mention} (T)\n"
                f"Начинаем бан карт и пик игроков."
            )
            connect_view = View()
            connect_view.add_item(Button(label="Зайти на сервер", style=discord.ButtonStyle.green, url=CONNECT_LINK))
            await interaction.channel.send("**Лобби готово!** Заходите:", view=connect_view)

@bot.tree.command(name="create", description="Создать своё лобби")
async def create(interaction: discord.Interaction):
    view = SetupView()
    embed = discord.Embed(title="Создать своё лобби", color=0x2b2d31)
    embed.description = "Нажмите кнопку ниже, чтобы создать своё лобби с вашими кастомными настройками."
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@bot.event
async def on_ready():
    print(f"Бот запущен: {bot.user}")
    guild = discord.Object(id=GUILD_ID)
    bot.tree.copy_global_to(guild=guild)
    synced = await bot.tree.sync(guild=guild)
    print(f"Синхронизировано {len(synced)} команд")
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
