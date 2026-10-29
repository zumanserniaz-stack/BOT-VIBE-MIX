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

GUILD_ID = 1548371779523837952  # замени
SERVER_IP = "45.86.81.37:55031"
CONNECT_LINK = f"steam://connect/{SERVER_IP}"
MAX_PLAYERS = 10

MAPS = ["Mirage", "Inferno", "Dust 2", "Ancient", "Anubis", "Nuke", "Overpass", "Train", "Vertigo"]

class LobbyView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.queue = []
        self.captains = []
        self.available_maps = MAPS.copy()
        self.banned = []

    @discord.ui.button(label="Присоединиться", style=discord.ButtonStyle.green)
    async def join(self, interaction: discord.Interaction, button: Button):
        user = interaction.user
        if user in self.queue:
            await interaction.response.send_message("Ты уже в очереди", ephemeral=True)
            return
        if len(self.queue) >= MAX_PLAYERS:
            await interaction.response.send_message("Полное", ephemeral=True)
            return

        self.queue.append(user)
        await self.update_embed(interaction)

        if len(self.queue) == MAX_PLAYERS:
            await self.start_captains(interaction)

    async def start_captains(self, interaction):
        self.captains = [self.queue[0], self.queue[1]]
        await interaction.channel.send(
            f"**Капитаны:** {self.captains[0].mention} (CT) и {self.captains[1].mention} (T)\n"
            f"Начинаем бан карт. {self.captains[0].mention} банит первым."
        )
        # Здесь можно добавить Select с картами для бана

    async def update_embed(self, interaction):
        embed = discord.Embed(title="Очередь — FreePick", color=0x2b2d31)
        embed.add_field(name="Игроки", value=f"**{len(self.queue)} из {MAX_PLAYERS}**", inline=False)
        if self.queue:
            embed.add_field(name="В очереди", value="\n".join([p.mention for p in self.queue]), inline=False)
        embed.add_field(name="Подключение", value=f"`connect {SERVER_IP}`", inline=False)
        
        try:
            await interaction.message.edit(embed=embed, view=self)
        except:
            pass
        await interaction.response.defer()

@bot.tree.command(name="lobby", description="Создать FreePick")
async def lobby(interaction: discord.Interaction):
    view = LobbyView()
    embed = discord.Embed(title="Очередь — FreePick", color=0x2b2d31)
    embed.add_field(name="Игроки", value=f"**0 из {MAX_PLAYERS}**", inline=False)
    embed.add_field(name="Подключение", value=f"`connect {SERVER_IP}`", inline=False)
    await interaction.response.send_message(embed=embed, view=view)

@bot.event
async def on_ready():
    print(f"Бот запущен: {bot.user}")
    guild = discord.Object(id=GUILD_ID)
    bot.tree.copy_global_to(guild=guild)
    await bot.tree.sync(guild=guild
@bot.tree.command(name="createvc", description="Создать категорию FreePick с каналами")
@app_commands.describe(number="Номер FreePick")
@app_commands.default_permissions(administrator=True)
async def createvc(interaction: discord.Interaction, number: int = 13):
    # Создаём категорию
    category = await interaction.guild.create_category(f"ПОИСК CS2 FreePick {number}")
    
    # Текстовый канал
    await category.create_text_channel("⚡ · очередь-freepick")
    
    # Голосовые каналы
    await category.create_voice_channel("FreePick", user_limit=10)
    await category.create_voice_channel("Болталка FreePick")
    
    await interaction.response.send_message(
        f"Создана категория **ПОИСК CS2 FreePick {number}**\n"
        f"Каналы: текстовый + FreePick + Болталка",
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
