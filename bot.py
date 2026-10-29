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
MAX_PLAYERS = 1

class JoinView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.queue = []

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
        
        embed = discord.Embed(title="Очередь — FreePick (тест)", color=0x2b2d31)
        embed.add_field(name="Настройки", value=(
            "**Формат:** 5x5 | BO1\n"
            "**Капитаны:** Доброволец\n"
            "**Карты:** Вето"
        ), inline=False)
        embed.add_field(name="Игроки", value=f"**{len(self.queue)} из {MAX_PLAYERS}**", inline=False)
        
        if self.queue:
            players = "\n".join([p.mention for p in self.queue])
            embed.add_field(name="В очереди", value=players, inline=False)

        embed.add_field(name="Подключение", value=f"`connect {SERVER_IP}`", inline=False)

        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message(f"Ты зашёл в очередь ({len(self.queue)}/{MAX_PLAYERS})", ephemeral=True)

        if len(self.queue) == MAX_PLAYERS:
            connect_view = View()
            connect_view.add_item(Button(label="Зайти на сервер", style=discord.ButtonStyle.green, url=CONNECT_LINK))
            await interaction.channel.send("**Лобби готово!** Заходи на сервер:", view=connect_view)

@bot.tree.command(name="lobby", description="Создать очередь FreePick")
async def lobby(interaction: discord.Interaction):
    view = JoinView()
    embed = discord.Embed(title="Очередь — FreePick (тест)", color=0x2b2d31)
    embed.add_field(name="Настройки", value=(
        "**Формат:** 5x5 | BO1\n"
        "**Капитаны:** Доброволец\n"
        "**Карты:** Вето"
    ), inline=False)
    embed.add_field(name="Игроки", value=f"**0 из {MAX_PLAYERS}**", inline=False)
    embed.add_field(name="Подключение", value=f"`connect {SERVER_IP}`", inline=False)
    
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name="createvc", description="Создать категорию FreePick")
@app_commands.describe(number="Номер FreePick")
@app_commands.default_permissions(administrator=True)
async def createvc(interaction: discord.Interaction, number: int = 13):
    category = await interaction.guild.create_category(f"ПОИСК CS2 FreePick {number}")
    await category.create_text_channel("⚡ · очередь-freepick")
    await category.create_voice_channel("FreePick", user_limit=10)
    await category.create_voice_channel("Болталка FreePick")
    
    await interaction.response.send_message(
        f"Создана категория **ПОИСК CS2 FreePick {number}**",
        ephemeral=True
    )

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
