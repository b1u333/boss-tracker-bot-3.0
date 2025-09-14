import discord
from discord.ext import commands, tasks
import json
import os
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# --- CONFIG ---
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
CONFIG_FILE = "config.json"
BOSSES_FILE = "bosses.json"
UTC8 = timezone(timedelta(hours=8))

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

CONFIG = {}
BOSSES = {}
spawn_times = {}
last_spawn_message = None
last_nextspawn_message = None

# --- CONFIG LOAD/SAVE ---
def save_config():
    with open(CONFIG_FILE, "w") as f:
        json.dump(CONFIG, f, indent=4)
    with open("config_backup.json", "w") as f:
        json.dump(CONFIG, f, indent=4)

def load_config():
    global CONFIG
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                CONFIG = json.load(f)
        elif os.path.exists("config_backup.json"):
            with open("config_backup.json", "r") as f:
                CONFIG = json.load(f)
            save_config()
        else:
            CONFIG = {}
            save_config()
    except Exception as e:
        print(f"⚠️ Failed to load config: {e}")
        CONFIG = {}
        save_config()

# --- BOSSES LOAD/SAVE ---
def save_bosses():
    with open(BOSSES_FILE, "w") as f:
        json.dump(BOSSES, f, indent=4)
    with open("bosses_backup.json", "w") as f:
        json.dump(BOSSES, f, indent=4)

def load_bosses():
    global BOSSES
    try:
        if os.path.exists(BOSSES_FILE):
            with open(BOSSES_FILE, "r") as f:
                BOSSES = json.load(f)
        elif os.path.exists("bosses_backup.json"):
            with open("bosses_backup.json", "r") as f:
                BOSSES = json.load(f)
            save_bosses()
        else:
            BOSSES = {}
            save_bosses()
    except Exception as e:
        print(f"⚠️ Failed to load bosses: {e}")
        BOSSES = {}
        save_bosses()

# --- SPAWN CALCULATIONS ---
def rebuild_spawn_times():
    now = datetime.now(UTC8)
    spawn_times.clear()
    for boss, data in BOSSES.items():
        if data["type"] == "respawn":
            if data.get("last_killed"):
                try:
                    last_kill = datetime.strptime(data["last_killed"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC8)
                    spawn_times[boss] = last_kill + timedelta(hours=data["hours"])
                except Exception:
                    spawn_times[boss] = now + timedelta(hours=data["hours"])
            else:
                spawn_times[boss] = now + timedelta(hours=data["hours"])
        elif data["type"] == "weekly":
            for sched in data["schedule"]:
                day = sched["day"].capitalize()
                t = datetime.strptime(sched["time"], "%H:%M").time()
                days_map = {
                    "Monday": 0, "Tuesday": 1, "Wednesday": 2,
                    "Thursday": 3, "Friday": 4, "Saturday": 5, "Sunday": 6
                }
                target_day = days_map[day]
                days_ahead = (target_day - now.weekday()) % 7
                candidate = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0) + timedelta(days=days_ahead)
                if candidate <= now:
                    candidate += timedelta(days=7)
                if boss not in spawn_times or candidate < spawn_times[boss]:
                    spawn_times[boss] = candidate

# --- HELPERS ---
def format_timedelta(td):
    seconds = int(td.total_seconds())
    h, m = divmod(seconds, 3600)
    m, s = divmod(m, 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    elif m > 0:
        return f"{m}m {s}s"
    else:
        return f"{s}s"

# --- EMBEDS ---
def create_embed():
    now = datetime.now(UTC8)
    embed = discord.Embed(
        title="🕒 Upcoming Boss Spawns",
        description="Shows absolute spawn date/time and how long until each spawn. (Live message — updates automatically)",
        color=0x3498db,
        timestamp=now
    )

    lines = []
    for boss in BOSSES.keys():
        if boss in spawn_times:
            t = spawn_times[boss]
            if t > now:
                remaining = t - now
                lines.append(f"**{boss.upper()}**\n{t.strftime('%Y-%m-%d %H:%M')} — in {format_timedelta(remaining)}")

    if not lines:
        embed.add_field(name="No Spawns", value="⚠️ No upcoming bosses.", inline=False)
    else:
        for i in range(0, len(lines), 10):
            chunk = lines[i:i+10]
            embed.add_field(
                name=f"Bosses {i+1}-{i+len(chunk)}",
                value="\n\n".join(chunk),
                inline=False
            )

    embed.set_footer(text="⏱ Updates every 15s")
    return embed

def create_nextspawn_embed():
    now = datetime.now(UTC8)
    embed = discord.Embed(
        title="🕒 Boss Spawns in Next 24 Hours",
        color=0x3498db,
        timestamp=now
    )

    upcoming = []
    for boss in BOSSES:
        if boss in spawn_times:
            next_time = spawn_times[boss]
            if timedelta(0) <= (next_time - now) <= timedelta(hours=24):
                upcoming.append((boss, next_time))
    upcoming.sort(key=lambda x: x[1])

    if not upcoming:
        embed.add_field(name="No Spawns", value="⚠️ No bosses in next 24h.", inline=False)
    else:
        lines = []
        for boss, t in upcoming:
            if t.date() == now.date():
                lines.append(f"**{boss.upper()}**\n{t.strftime('%I:%M %p')}")
            else:
                lines.append(f"**{boss.upper()}**\nTomorrow, {t.strftime('%I:%M %p')}")
        embed.add_field(name="Upcoming Spawns", value="\n\n".join(lines), inline=False)

    embed.set_footer(text="⏱ Updates every 15s")
    return embed

# --- COMMANDS ---
@bot.command()
async def setup(ctx, channel: discord.TextChannel):
    CONFIG["channel_id"] = channel.id
    save_config()
    await ctx.send(f"✅ Spawn warnings will be sent to {channel.mention}")

@bot.command()
async def setwarningchannel(ctx, channel: discord.TextChannel):
    CONFIG["warning_channel_id"] = channel.id
    save_config()
    await ctx.send(f"✅ Warning channel set to {channel.mention}")

# Removed setwarningrole (no longer needed)

@bot.command()
async def setinterval(ctx, boss: str, hours: int):
    boss = boss.upper()
    BOSSES[boss] = {"type": "respawn", "hours": hours, "last_killed": None, "warned_for": None}
    spawn_times[boss] = datetime.now(UTC8) + timedelta(hours=hours)
    save_bosses()
    await ctx.send(f"✅ Added {boss} with respawn every {hours}h")

@bot.command()
async def setspawn(ctx, boss: str, day: str, hm: str):
    boss = boss.upper()
    day = day.capitalize()
    if boss not in BOSSES:
        BOSSES[boss] = {"type": "weekly", "schedule": []}

    if {"day": day, "time": hm} in BOSSES[boss]["schedule"]:
        await ctx.send(f"⚠️ {boss} already has {day} at {hm} scheduled.")
        return

    BOSSES[boss]["schedule"].append({"day": day, "time": hm})
    save_bosses()
    rebuild_spawn_times()
    await ctx.send(f"✅ Added {boss} spawning every {day} at {hm}")

@bot.command()
async def killed(ctx, boss: str, hm: str = None, date: str = None):
    boss = boss.upper()
    if boss not in BOSSES or BOSSES[boss]["type"] != "respawn":
        try:
            await ctx.message.add_reaction("❌")
        except (discord.Forbidden, discord.HTTPException):
            pass
        return

    if hm and date:
        try:
            kill_time = datetime.strptime(f"{date} {hm}", "%Y-%m-%d %H:%M").replace(tzinfo=UTC8)
        except ValueError:
            await ctx.send("⚠️ Invalid format. Use `!killed <boss> HH:MM YYYY-MM-DD`")
            return
    else:
        kill_time = datetime.now(UTC8)

    next_time = kill_time + timedelta(hours=BOSSES[boss]["hours"])
    BOSSES[boss]["last_killed"] = kill_time.strftime("%Y-%m-%d %H:%M:%S")
    BOSSES[boss]["warned_for"] = None
    spawn_times[boss] = next_time
    save_bosses()

    await ctx.send(
        f"✅ Recorded {boss} kill at {kill_time.strftime('%Y-%m-%d %H:%M')}. "
        f"Next spawn at {next_time.strftime('%Y-%m-%d %H:%M')}."
    )

@bot.command()
async def deleteboss(ctx, boss: str):
    boss = boss.upper()
    if boss not in BOSSES:
        try:
            await ctx.message.add_reaction("❌")
        except (discord.Forbidden, discord.HTTPException):
            pass
        return

    BOSSES.pop(boss, None)
    spawn_times.pop(boss, None)
    save_bosses()
    try:
        await ctx.message.add_reaction("✅")
    except (discord.Forbidden, discord.HTTPException):
        pass

@bot.command()
async def spawn(ctx):
    global last_spawn_message
    if last_spawn_message:
        try:
            await last_spawn_message.delete()
        except (discord.NotFound, discord.Forbidden):
            pass
    embed = create_embed()
    last_spawn_message = await ctx.send(embed=embed)
    CONFIG["last_spawn_message_id"] = last_spawn_message.id
    save_config()

@bot.command()
async def nextspawn(ctx):
    global last_nextspawn_message
    if last_nextspawn_message:
        try:
            await last_nextspawn_message.delete()
        except (discord.NotFound, discord.Forbidden):
            pass
    embed = create_nextspawn_embed()
    last_nextspawn_message = await ctx.send(embed=embed)
    CONFIG["last_nextspawn_message_id"] = last_nextspawn_message.id
    save_config()

@bot.command()
async def listbosses(ctx):
    if not BOSSES:
        await ctx.send("⚠️ No bosses registered yet.")
        return

    embed = discord.Embed(
        title="📜 Registered Bosses",
        color=0x2ecc71,
        timestamp=datetime.now(UTC8)
    )

    interval_bosses = [boss for boss, data in BOSSES.items() if data["type"] == "respawn"]
    weekly_bosses = [boss for boss, data in BOSSES.items() if data["type"] == "weekly"]

    if interval_bosses:
        embed.add_field(
            name="⏱ Interval Spawn Bosses",
            value=", ".join(b.upper() for b in interval_bosses),
            inline=False
        )
    if weekly_bosses:
        embed.add_field(
            name="📅 Weekly Spawn Bosses",
            value=", ".join(b.upper() for b in weekly_bosses),
            inline=False
        )

    embed.set_footer(text="Use !killed [boss] to record kills and update spawns.")
    await ctx.send(embed=embed)

@bot.command()
async def importbosses(ctx):
    try:
        with open("boss time.txt", "r") as f:
            lines = f.readlines()

        imported = 0
        for line in lines:
            parts = line.strip().split()
            if not parts:
                continue

            if parts[0].lower() == "!setinterval" and len(parts) == 3:
                boss = parts[1].upper()
                hours = int(parts[2])
                BOSSES[boss] = {"type": "respawn", "hours": hours, "last_killed": None, "warned_for": None}
                spawn_times[boss] = datetime.now(UTC8) + timedelta(hours=hours)
                imported += 1

            elif parts[0].lower() == "!setspawn" and len(parts) == 4:
                boss = parts[1].upper()
                day = parts[2].capitalize()
                hm = parts[3]
                if boss not in BOSSES:
                    BOSSES[boss] = {"type": "weekly", "schedule": []}
                if {"day": day, "time": hm} not in BOSSES[boss]["schedule"]:
                    BOSSES[boss]["schedule"].append({"day": day, "time": hm})
                imported += 1

        save_bosses()
        rebuild_spawn_times()
        await ctx.send(f"✅ Imported {imported} bosses from file.")

    except Exception as e:
        await ctx.send(f"⚠️ Import failed: {e}")

@bot.command()
async def testwarn(ctx, boss: str):
    boss = boss.upper()
    if boss not in BOSSES:
        await ctx.send(f"⚠️ Boss {boss} not found.")
        return

    now = datetime.now(UTC8)
    test_time = now + timedelta(minutes=5)
    spawn_times[boss] = test_time
    BOSSES[boss]["warned_for"] = None
    save_bosses()

    await ctx.send(f"✅ Test warning set: **{boss}** will 'spawn' at {test_time.strftime('%Y-%m-%d %H:%M')} (in 5m).")

# --- AUTO UPDATE ---
@tasks.loop(seconds=15)
async def update_spawn_message():
    global last_spawn_message, last_nextspawn_message
    if last_spawn_message:
        try:
            await last_spawn_message.edit(embed=create_embed())
        except discord.NotFound:
            try:
                last_spawn_message = await last_spawn_message.channel.send(embed=create_embed())
            except discord.Forbidden:
                pass
    if last_nextspawn_message:
        try:
            await last_nextspawn_message.edit(embed=create_nextspawn_embed())
        except discord.NotFound:
            try:
                last_nextspawn_message = await last_nextspawn_message.channel.send(embed=create_nextspawn_embed())
            except discord.Forbidden:
                pass

    now = datetime.now(UTC8)
    warning_channel_id = CONFIG.get("warning_channel_id")
    if warning_channel_id:
        channel = bot.get_channel(warning_channel_id)
        if channel:
            for boss, t in spawn_times.items():
                seconds_left = (t - now).total_seconds()
                if 240 <= seconds_left <= 300:
                    warned_for = BOSSES[boss].get("warned_for")
                    if warned_for != t.strftime("%Y-%m-%d %H:%M:%S"):
                        try:
                            await channel.send(
                                f"⚠️ **{boss.upper()}** will spawn in ~5 minutes! ({t.strftime('%Y-%m-%d %H:%M')}) @everyone"
                            )
                        except discord.Forbidden:
                            pass
                        BOSSES[boss]["warned_for"] = t.strftime("%Y-%m-%d %H:%M:%S")
                        save_bosses()

# --- EVENTS ---
@bot.event
async def on_ready():
    global last_spawn_message, last_nextspawn_message
    print(f"✅ Logged in as {bot.user}")
    load_config()
    load_bosses()
    rebuild_spawn_times()
    update_spawn_message.start()

    channel_id = CONFIG.get("channel_id")
    if channel_id:
        channel = bot.get_channel(channel_id)
        if channel:
            try:
                if "last_spawn_message_id" in CONFIG:
                    last_spawn_message = await channel.fetch_message(CONFIG["last_spawn_message_id"])
                if "last_nextspawn_message_id" in CONFIG:
                    last_nextspawn_message = await channel.fetch_message(CONFIG["last_nextspawn_message_id"])
            except discord.NotFound:
                try:
                    last_spawn_message = await channel.send(embed=create_embed())
                    CONFIG["last_spawn_message_id"] = last_spawn_message.id
                    last_nextspawn_message = await channel.send(embed=create_nextspawn_embed())
                    CONFIG["last_nextspawn_message_id"] = last_nextspawn_message.id
                    save_config()
                except discord.Forbidden:
                    print("⚠️ Missing permission to send spawn tracker messages.")

# --- RUN ---
if not TOKEN:
    raise RuntimeError("❌ DISCORD_TOKEN environment variable not set!")

bot.run(TOKEN)
