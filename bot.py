import asyncio
import base64
import json
import os
from functools import partial
from urllib.parse import parse_qs, urlparse

import discord
from discord import FFmpegPCMAudio, FFmpegOpusAudio
from discord.ext import commands
from dotenv import load_dotenv
import yt_dlp
from yt_dlp.utils import DownloadError

load_dotenv()


def cargar_token():
    try:
        with open(".sys_token_1492.cfg", "r", encoding="utf-8") as file:
            token_b64 = file.read().strip()
            return base64.b64decode(token_b64).decode("utf-8")
    except Exception as error:
        print("Error cargando token:", error)
        return None


TOKEN = cargar_token()
if not TOKEN:
    raise RuntimeError("No pude cargar el token.")

with open("radios.json", "r", encoding="utf-8") as file:
    RADIOS = json.load(file)

BASE_YTDL_OPTS = {
    "quiet": False,
    "no_warnings": True,
    "skip_download": True,
    "noplaylist": True,
    "geo_bypass": True,
    "nocheckcertificate": True,
}

EXTRACTION_STRATEGIES = [
    {
        "name": "web+cookies",
        "opts": {
            "cookiefile": "cookies.txt",
            "extractor_args": {"youtube": {"player_client": ["web"]}},
        },
        "formats": ["91", "92", "93", "worst"],
    },
]

FFMPEG_BEFORE_OPTS = (
    '-nostdin -reconnect 1 -reconnect_streamed 1 '
    '-reconnect_delay_max 5 -rw_timeout 15000000 '
    '-protocol_whitelist "file,http,https,tcp,tls,crypto" '
    '-user_agent "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" '
    '-headers "Referer: https://www.youtube.com/" '
    '-http_persistent 0'
)

FFMPEG_OPUS_OPTS = "-vn -loglevel warning"
FFMPEG_PCM_OPTS = "-vn -loglevel warning"

YTDL_SEMAPHORE = asyncio.Semaphore(2)
IDLE_TIMEOUT = 300

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix="-", intents=intents)

queues = {}
playing = {}
queue_locks = {}
idle_tasks = {}


def get_queue(gid):
    return queues.setdefault(gid, [])


def get_playing(gid):
    return playing.setdefault(gid, False)


def set_playing(gid, value):
    playing[gid] = value


def get_lock(gid):
    return queue_locks.setdefault(gid, asyncio.Lock())


def cancel_idle_timer(gid):
    task = idle_tasks.pop(gid, None)
    if task and not task.done():
        task.cancel()


def schedule_idle_timer(ctx):
    voice = ctx.guild.voice_client
    if not voice:
        cancel_idle_timer(ctx.guild.id)
        return
    cancel_idle_timer(ctx.guild.id)
    idle_tasks[ctx.guild.id] = bot.loop.create_task(
        disconnect_if_idle(ctx, IDLE_TIMEOUT)
    )


async def disconnect_if_idle(ctx, delay):
    gid = ctx.guild.id
    try:
        await asyncio.sleep(delay)
        voice = ctx.guild.voice_client
        if voice and not voice.is_playing() and not get_queue(gid):
            await voice.disconnect()
            set_playing(gid, False)
            await ctx.send("Me desconecté tras 5 minutos sin uso.")
    except asyncio.CancelledError:
        pass
    finally:
        idle_tasks.pop(gid, None)


async def ensure_deafened(voice_client):
    if not voice_client or not voice_client.guild:
        return
    member = voice_client.guild.me
    if not member:
        return
    voice_state = getattr(member, "voice", None)
    if voice_state and voice_state.self_deaf and not voice_state.self_mute:
        return
    try:
        await member.edit(deafen=True, mute=False)
    except discord.Forbidden:
        pass


async def run_blocking(func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))


def _extract_info(query, format_string=None, extra_opts=None):
    opts = BASE_YTDL_OPTS.copy()
    if extra_opts:
        for key, value in extra_opts.items():
            if key == "extractor_args" and key in opts:
                opts[key].update(value)
            else:
                opts[key] = value
    if format_string:
        opts["format"] = format_string
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(query, download=False)


async def extract_ytdl_info(query, format_string=None, extra_opts=None):
    async with YTDL_SEMAPHORE:
        return await run_blocking(_extract_info, query, format_string, extra_opts)


async def obtener_audio_reproducible(video_id, *, title_hint=None, get_url_only=False):
    url_base = f"https://www.youtube.com/watch?v={video_id}"
    
    for strategy in EXTRACTION_STRATEGIES:
        strategy_name = strategy["name"]
        extra_opts = strategy["opts"]
        formats = strategy["formats"]
        
        for fmt in formats:
            try:
                info = await extract_ytdl_info(url_base, format_string=fmt, extra_opts=extra_opts)
                if not info or not isinstance(info, dict):
                    print(f"  -> Formato {fmt}: no devolvió dict")
                    continue
                
                url = info.get("url")
                title = info.get("title", "Audio")
                
                if url:
                    if get_url_only:
                        return url
                    print(f"✓ Éxito: {strategy_name} + {fmt}")
                    return url, title
                else:
                    print(f"  -> Formato {fmt}: sin URL. Keys: {list(info.keys())[:10]}")
            except Exception as e:
                print(f"  -> Formato {fmt}: excepción {type(e).__name__}: {str(e)[:80]}")
                continue
    
    if title_hint and not get_url_only:
        try:
            search_opts = {"cookiefile": "cookies.txt"}
            alt_info = await extract_ytdl_info(f"ytsearch1:{title_hint}", extra_opts=search_opts)
            if isinstance(alt_info, dict):
                entries = alt_info.get("entries", [])
                if entries and isinstance(entries[0], dict):
                    alt_id = entries[0].get("id")
                    if alt_id and alt_id != video_id:
                        alt_title = entries[0].get("title")
                        return await obtener_audio_reproducible(alt_id, title_hint=alt_title)
        except Exception:
            pass
    
    return None if get_url_only else (None, None)


async def buscar_en_youtube(query):
    search_opts = {"cookiefile": "cookies.txt"}
    info = await extract_ytdl_info(f"ytsearch1:{query}", extra_opts=search_opts)
    if not isinstance(info, dict):
        raise ValueError("❌ Error en la búsqueda.")
    entries = info.get("entries")
    if not entries:
        raise ValueError("❌ No encontré resultados.")
    return entries[0].get("id"), entries[0].get("title", query)


def extract_playlist_id(url):
    parsed = urlparse(url)
    if parsed.query:
        params = parse_qs(parsed.query)
        if "list" in params:
            return params["list"][0]
    return None


async def fetch_playlist_entries(raw_url):
    playlist_id = extract_playlist_id(raw_url)
    if not playlist_id:
        raise ValueError("❌ No reconocí esa playlist.")
    base = "https://music.youtube.com" if "music.youtube.com" in raw_url else "https://www.youtube.com"
    playlist_opts = {"cookiefile": "cookies.txt"}
    info = await extract_ytdl_info(f"{base}/playlist?list={playlist_id}", extra_opts=playlist_opts)
    if not isinstance(info, dict):
        raise ValueError("❌ Error cargando playlist.")
    entries = info.get("entries") or []
    return [
        {"id": e.get("id"), "title": e.get("title", "Audio")}
        for e in entries if e.get("id")
    ]


async def build_audio_source(stream_url):
    if ".m3u8" in stream_url or "manifest.googlevideo.com" in stream_url:
        return FFmpegPCMAudio(
            stream_url,
            before_options=FFMPEG_BEFORE_OPTS,
            options=FFMPEG_PCM_OPTS,
        )
    try:
        return await FFmpegOpusAudio.from_probe(
            stream_url,
            before_options=FFMPEG_BEFORE_OPTS,
            options=FFMPEG_OPUS_OPTS,
        )
    except Exception:
        return FFmpegPCMAudio(
            stream_url,
            before_options=FFMPEG_BEFORE_OPTS,
            options=FFMPEG_PCM_OPTS,
        )


def parse_youtube_id(raw_url):
    if "youtube.com/watch" in raw_url:
        return raw_url.split("v=")[-1].split("&")[0]
    if "youtu.be/" in raw_url:
        return raw_url.rsplit("/", 1)[-1].split("?")[0]
    return None


async def play_next(ctx):
    gid = ctx.guild.id
    async with get_lock(gid):
        queue = get_queue(gid)
        if not queue:
            set_playing(gid, False)
            schedule_idle_timer(ctx)
            return
        set_playing(gid, True)
        item = queue.pop(0)
    cancel_idle_timer(gid)

    voice = ctx.voice_client
    if not voice:
        if not ctx.author.voice:
            set_playing(gid, False)
            schedule_idle_timer(ctx)
            await ctx.send("Necesito un canal de voz para seguir.")
            return
        voice = await ctx.author.voice.channel.connect(self_deaf=True, self_mute=False)
    await ensure_deafened(voice)

    # Siempre obtener URL fresca para evitar expiración de HLS
    stream_url = await obtener_audio_reproducible(item["id"], title_hint=item["title"], get_url_only=True)
    if not stream_url:
        await ctx.send("❌ Error con la canción, saltando.")
        return await play_next(ctx)

    try:
        audio_source = await build_audio_source(stream_url)
    except Exception as error:
        await ctx.send(f"Error al preparar audio: `{error}`")
        return await play_next(ctx)

    def _after_playback(ffmpeg_error):
        if ffmpeg_error:
            print(f"FFmpeg error: {ffmpeg_error}")
        bot.loop.call_soon_threadsafe(lambda: asyncio.create_task(play_next(ctx)))

    voice.play(audio_source, after=_after_playback)
    await ctx.send(f"▶️ **Reproduciendo:** {item['title']}")


@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user}")


@bot.command()
async def emisoras(ctx):
    lista = "\n".join([f"• **{n}**" for n in RADIOS])
    await ctx.send(f"**Tenemos:**\n{lista}")


@bot.command()
async def radio(ctx, emisora: str):
    emisora = emisora.lower()
    if emisora not in RADIOS:
        return await ctx.send("Esa emisora no existe.")
    if not ctx.author.voice:
        return await ctx.send("Métete a un canal de voz primero.")

    voice = ctx.voice_client or await ctx.author.voice.channel.connect(self_deaf=True, self_mute=False)
    await ensure_deafened(voice)
    cancel_idle_timer(ctx.guild.id)
    if voice.is_playing():
        voice.stop()
    voice.play(await build_audio_source(RADIOS[emisora]))
    await ctx.send(f"📻 Sonando **{emisora}**")


@bot.command()
async def play(ctx, *, search: str):
    gid = ctx.guild.id
    if not ctx.author.voice:
        return await ctx.send("Métete a un canal de voz primero.")

    query = search.strip()

    if query.startswith("http") and extract_playlist_id(query):
        try:
            playlist_entries = await fetch_playlist_entries(query)
        except ValueError as error:
            return await ctx.send(str(error))
        if playlist_entries:
            first = playlist_entries[0]
            first_url, first_title = await obtener_audio_reproducible(first["id"], title_hint=first["title"])
            if not first_url:
                return await ctx.send("❌ No pude preparar la primera canción.")
            if first_title:
                first["title"] = first_title
            async with get_lock(gid):
                get_queue(gid).extend(playlist_entries)
                cancel_idle_timer(gid)
                if not get_playing(gid):
                    bot.loop.create_task(play_next(ctx))
            return await ctx.send(f"📃 Playlist añadida ({len(playlist_entries)} temas).")

    video_id = parse_youtube_id(query)
    title = None

    if not video_id:
        try:
            video_id, title = await buscar_en_youtube(query)
        except ValueError as error:
            return await ctx.send(str(error))

    if not video_id:
        return await ctx.send("❌ No encontré resultados.")

    result = await obtener_audio_reproducible(video_id, title_hint=title or query)
    if not result or not result[0]:
        return await ctx.send("❌ No pude preparar esa canción.")
    
    _, resolved_title = result
    display_title = resolved_title or title or query
    async with get_lock(gid):
        get_queue(gid).append({"id": video_id, "title": display_title})
        cancel_idle_timer(gid)
        if not get_playing(gid):
            bot.loop.create_task(play_next(ctx))
        else:
            await ctx.send(f"➕ **Añadida:** {display_title}")


@bot.command()
async def queue(ctx):
    q = get_queue(ctx.guild.id)
    if not q:
        return await ctx.send("La cola está vacía.")
    await ctx.send("📝 **Cola:**\n" + "\n".join([f"{i+1}. {item['title']}" for i, item in enumerate(q)]))


@bot.command()
async def skip(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send("⏭️ Saltando...")
    else:
        await ctx.send("No hay nada sonando.")


@bot.command()
async def pause(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send("⏸️ Pausado.")
    else:
        await ctx.send("Nada para pausar.")


@bot.command()
async def resume(ctx):
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        cancel_idle_timer(ctx.guild.id)
        await ctx.send("▶️ Reanudado.")
    else:
        await ctx.send("No está pausado.")


@bot.command()
async def stop(ctx):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        gid = ctx.guild.id
        async with get_lock(gid):
            queues[gid] = []
            set_playing(gid, False)
        cancel_idle_timer(gid)
        await ctx.send("Paré esa vuelta.")
    else:
        await ctx.send("No estoy en un canal de voz.")


@bot.command(name="remove")
async def remove_queue_entry(ctx, index: int):
    gid = ctx.guild.id
    async with get_lock(gid):
        queue = get_queue(gid)
        if not queue:
            return await ctx.send("La cola está vacía.")
        if index < 1 or index > len(queue):
            return await ctx.send("Número fuera de rango.")
        removed = queue.pop(index - 1)
    await ctx.send(f"🗑️ Eliminada: {removed['title']}")


@bot.command(name="clearqueue", aliases=("clearq", "clear"))
async def clear_queue(ctx):
    gid = ctx.guild.id
    async with get_lock(gid):
        queue = get_queue(gid)
        if not queue and not get_playing(gid):
            return await ctx.send("No hay nada que limpiar.")
        queue.clear()
        set_playing(gid, False)
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
    cancel_idle_timer(gid)
    await ctx.send("🗂️ Cola eliminada.")


bot.run(TOKEN)