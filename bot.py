import os
import asyncio
import aiohttp
import io
import random
import collections
import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import Button, View
from discord.ui import View, Button, Modal, TextInput, UserSelect
from flask import Flask
from threading import Thread
import yt_dlp
import traceback
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

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ================== ВСТАВЬ ID СВОЕГО СЕРВЕРА ==================
GUILD_ID = 123456789012345678  # замени на свой
# =============================================================

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
        if len(self.queue) >= 10:
            await interaction.response.send_message("Лобби полное (10/10)", ephemeral=True)
            return

        self.queue.append(user)
        
        embed = discord.Embed(title="Очередь — FreePick", color=0x2b2d31)
        embed.add_field(name="Настройки", value=(
            "**Формат:** 5x5 | BO1\n"
            "**Капитаны:** Доброволец\n"
            "**Карты:** Вето"
        ), inline=False)
        embed.add_field(name="Игроки", value=f"**{len(self.queue)} из 10**", inline=False)
        
        if self.queue:
            players = "\n".join([p.mention for p in self.queue])
            embed.add_field(name="В очереди", value=players, inline=False)

        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message(f"Ты зашёл в очередь ({len(self.queue)}/10)", ephemeral=True)

@bot.tree.command(name="lobby", description="Создать очередь FreePick")
async def lobby(interaction: discord.Interaction):
    view = JoinView()
    embed = discord.Embed(title="Очередь — FreePick", color=0x2b2d31)
    embed.add_field(name="Настройки", value=(
        "**Формат:** 5x5 | BO1\n"
        "**Капитаны:** Доброволец\n"
        "**Карты:** Вето"
    ), inline=False)
    embed.add_field(name="Игроки", value="**0 из 10**", inline=False)
    
    await interaction.response.send_message(embed=embed, view=view)

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
