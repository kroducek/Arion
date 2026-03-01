import discord
import os
import json
import logging
from discord.ext import commands
from dotenv import load_dotenv

# ====== LOAD ENV ======
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    print("❌ DISCORD_TOKEN nebyl nalezen v .env!")
    exit(1)

# ====== LOGGING ======
logging.basicConfig(level=logging.INFO)

# ====== CONFIG LOAD ======
def load_config():
    try:
        with open('config.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print("❌ Chyba: config.json nenalezen!")
        exit(1)
    except json.JSONDecodeError:
        print("❌ Chyba: config.json má špatný formát!")
        exit(1)

config = load_config()

class ArionBot(commands.Bot):
    def __init__(self):
        self.config = config

        try:
            self.color = int(self.config['embed_color'], 16)
        except Exception:
            print("⚠️ Neplatná barva v configu, používám fallback.")
            self.color = 0xFF0000

        self.wiki_url = self.config['wiki_url']

        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

        super().__init__(
            command_prefix=config['prefix'],
            intents=intents,
            help_command=None
        )

    async def setup_hook(self):
        print("--- 🐾 Načítám Cogs ---")

        for filename in os.listdir('./src/cogs'):
            if filename.endswith('.py') and not filename.startswith('_'):
                try:
                    await self.load_extension(f'src.cogs.{filename[:-3]}')
                    print(f'   ✅ {filename} načten.')
                except Exception as e:
                    print(f'   ❌ {filename} selhal: {e}')

        print("🔄 Synchronizuji slash commandy...")
        synced = await self.tree.sync()
        print(f"✅ Synced {len(synced)} commandů.")

    async def on_ready(self):
        print(f'🚀 Arion je online jako {self.user}')

# ====== RUN ======
if __name__ == "__main__":
    bot = ArionBot()
    bot.run(TOKEN)