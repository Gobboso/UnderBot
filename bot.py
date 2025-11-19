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

YTDL_FORMAT_PIPELINE = [
    "251",  # Opus 160kbps (común en videos normales)
    "250",  # Opus 70kbps
    "249",  # Opus 50kbps
    "140",  # M4A 128kbps
    "96",   # HLS mp4 1080p
    "95",   # HLS mp4 720p
    "94",   # HLS mp4 480p
    "93",   # HLS mp4 360p
    "92",   # HLS mp4 240p
    "91",   # HLS mp4 144p
    "bestaudio/best"
]

BASE_YTDL_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "default_search": "auto",
    "extract_flat": False,
    "cachedir": False,
    "noplaylist": True,
    "source_address": "0.0.0.0",
    "cookiefile": "cookies.txt",
    "extractor_args": {
        "youtube": {
            "player_client": ["android"],
            "player_skip": ["configs"]
        }
    },
    "prefer_insecure": True,
    "force_ip": "0.0.0.0",
}

FFMPEG_PROTOCOLS = "file,http,https,tcp,tls"
FFMPEG_BASE_BEFORE = (
    "-nostdin -loglevel warning "
    "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
    "-reconnect_at_eof 1 -reconnect_on_network_error 1 "
    "-rw_timeout 15000000 "
    f'-protocol_whitelist \"{FFMPEG_PROTOCOLS}\"'
)

FFMPEG_HLS_BEFORE = f"{FFMPEG_BASE_BEFORE} -allowed_extensions ALL"
FFMPEG_BEFORE_OPTS = FFMPEG_HLS_BEFORE

FFMPEG_OPUS_OPTS = "-vn -compression_level 10 -loglevel warning"
FFMPEG_PCM_OPTS = "-vn -af aresample=48000:async=1:first_pts=0 -threads 1 -loglevel warning"
FFMPEG_HLS_OPTS = "-vn -loglevel warning"

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


def _extract_info(query):
    last_error = None
    for fmt in YTDL_FORMAT_PIPELINE:
        opts = dict(BASE_YTDL_OPTS)
        opts["format"] = fmt
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(query, download=False)
        except DownloadError as error:
            last_error = error
            if "Requested format is not available" in str(error):
                continue
            raise
    raise last_error if last_error else RuntimeError("No se pudo extraer el audio.")


async def extract_ytdl_info(query):
    async with YTDL_SEMAPHORE:
        return await run_blocking(_extract_info, query)


async def _probe_stream_candidates(candidates):
    last_error = None
    for target in candidates:
        try:
            info = await extract_ytdl_info(target)
        except DownloadError as error:
            last_error = error
            continue
        url = info.get("url")
        if url:
            return url, info.get("title", "Audio")
    if last_error:
        print("Error obteniendo audio con yt-dlp:", last_error)
    return None, None


async def obtener_audio_reproducible(video_id, *, title_hint=None):
    candidates = [
        f"https://www.youtube.com/watch?v={video_id}",
        f"https://music.youtube.com/watch?v={video_id}",
    ]
    stream, title = await _probe_stream_candidates(candidates)
    if stream:
        return stream, title
    if title_hint:
        alt_id, alt_title = await buscar_en_youtube(title_hint)
        if alt_id and alt_id != video_id:
            return await obtener_audio_reproducible(
                alt_id,
                title_hint=alt_title or title_hint,
            )
    return None, None


async def obtener_audio_soundcloud(track_url):
    try:
        info = await extract_ytdl_info(track_url)
    except Exception as error:
        print("Error SoundCloud:", error)
        return None, None
    return info.get("url"), info.get("title", "Audio")


async def buscar_en_youtube(query):
    info = await extract_ytdl_info(f"ytsearch1:{query}")
    entries = info.get("entries")
    if not entries:
        raise ValueError("❌ No encontré resultados en YouTube.")
    first = entries[0]
    return first.get("id"), first.get("title", query)


def extract_playlist_id(url):
    parsed = urlparse(url)
    if parsed.query:
        params = parse_qs(parsed.query)
        if "list" in params:
            return params["list"][0]
    if "list=" in url:
        return url.split("list=")[-1].split("&")[0]
    return None


def build_playlist_url(playlist_id, source_url):
    base = (
        "https://music.youtube.com/playlist?list="
        if source_url and "music.youtube.com" in source_url
        else "https://www.youtube.com/playlist?list="
    )
    return f"{base}{playlist_id}"


async def fetch_playlist_entries(raw_url):
    playlist_id = extract_playlist_id(raw_url)
    if not playlist_id:
        raise ValueError("❌ No reconocí esa playlist.")
    info = await extract_ytdl_info(build_playlist_url(playlist_id, raw_url))
    entries = info.get("entries") or []
    tracks = [
        {"id": entry.get("id"), "title": entry.get("title") or "Audio", "source": None}
        for entry in entries
        if entry.get("id")
    ]
    if not tracks:
        raise ValueError("❌ La playlist no tiene canciones válidas.")
    return tracks


def is_hls_stream(url: str) -> bool:
    if not url:
        return False
    lowered = url.lower()
    return (
        ".m3u8" in lowered
        or "cf-hls" in lowered
        or "playlist.m3u8" in lowered
        or "/playlist/" in lowered
    )


async def build_audio_source(stream_url):
    if is_hls_stream(stream_url):
        return FFmpegPCMAudio(
            stream_url,
            before_options=FFMPEG_HLS_BEFORE,
            options=FFMPEG_HLS_OPTS,
        )
    try:
        return await FFmpegOpusAudio.from_probe(
            stream_url,
            method="fallback",
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


def is_soundcloud_url(text):
    return "soundcloud.com" in text


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
        voice = await ctx.author.voice.channel.connect(
            self_deaf=True,
            self_mute=False,
        )
    await ensure_deafened(voice)

    stream_url = item.get("source")
    if stream_url is None:
        if item.get("provider") == "soundcloud":
            stream_url, _ = await obtener_audio_soundcloud(item["id"])
        else:
            stream_url, _ = await obtener_audio_reproducible(
                item["id"],
                title_hint=item["title"],
            )
        if stream_url is None:
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
        bot.loop.call_soon_threadsafe(
            lambda: asyncio.create_task(play_next(ctx))
        )

    voice.play(audio_source, after=_after_playback)
    await ctx.send(f"▶️ **Reproduciendo:** {item['title']}")


@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user}")


@bot.command()
async def emisoras(ctx):
    lista = "\n".join([f"• **{nombre}**" for nombre in RADIOS])
    await ctx.send(f"**Tenemos:**\n{lista}")


@bot.command()
async def radio(ctx, emisora: str):
    emisora = emisora.lower()
    if emisora not in RADIOS:
        return await ctx.send("Esa emisora no existe.")
    if not ctx.author.voice:
        return await ctx.send("Métete a un canal de voz primero.")

    voice = ctx.voice_client
    if not voice:
        voice = await ctx.author.voice.channel.connect(
            self_deaf=True,
            self_mute=False,
        )
    await ensure_deafened(voice)
    cancel_idle_timer(ctx.guild.id)

    if voice.is_playing():
        voice.stop()

    source = await build_audio_source(RADIOS[emisora])
    voice.play(source)
    await ctx.send(f"📻 Sonando **{emisora}**")


@bot.command()
async def play(ctx, *, search: str):
    gid = ctx.guild.id
    if not ctx.author.voice:
        return await ctx.send("Métete a un canal de voz primero.")

    query = search.strip()
    playlist_entries = None

    if query.startswith("http") and extract_playlist_id(query):
        try:
            playlist_entries = await fetch_playlist_entries(query)
        except ValueError as error:
            return await ctx.send(str(error))
        except Exception as error:
            return await ctx.send(f"❌ Error leyendo la playlist: {error}")

    if playlist_entries:
        first_entry = playlist_entries[0]
        stream_url, resolved_title = await obtener_audio_reproducible(
            first_entry["id"],
            title_hint=first_entry["title"],
        )
        if not stream_url:
            return await ctx.send("❌ No pude preparar la primera canción.")
        first_entry["source"] = stream_url
        if resolved_title:
            first_entry["title"] = resolved_title
        added = len(playlist_entries)
        async with get_lock(gid):
            queue = get_queue(gid)
            queue.extend(playlist_entries)
            cancel_idle_timer(gid)
            if not get_playing(gid):
                bot.loop.create_task(play_next(ctx))
        return await ctx.send(
            f"📃 Playlist añadida ({added} temas). "
            f"▶️ Sonando ahora: **{first_entry['title']}**"
        )

    if query.startswith("http") and is_soundcloud_url(query):
        stream_url, title = await obtener_audio_soundcloud(query)
        if not stream_url:
            return await ctx.send("❌ No pude preparar esa canción de SoundCloud.")
        async with get_lock(gid):
            queue = get_queue(gid)
            queue.append(
                {
                    "id": query,
                    "title": title or "SoundCloud",
                    "source": stream_url,
                    "provider": "soundcloud",
                }
            )
            cancel_idle_timer(gid)
            if not get_playing(gid):
                bot.loop.create_task(play_next(ctx))
            else:
                await ctx.send(f"➕ **Añadida a la cola:** {title or 'SoundCloud'}")
        return

    video_id = parse_youtube_id(query)
    title = None

    if not video_id:
        try:
            video_id, title = await buscar_en_youtube(query)
        except ValueError as error:
            return await ctx.send(str(error))
        except Exception as error:
            return await ctx.send(f"❌ Error buscando en YouTube: {error}")

    if not video_id:
        return await ctx.send("❌ No encontré resultados en YouTube.")

    stream_url, resolved_title = await obtener_audio_reproducible(
        video_id,
        title_hint=title or query,
    )
    if not stream_url:
        return await ctx.send("❌ No pude preparar esa canción.")
    if resolved_title:
        title = resolved_title
    display_title = title or query

    async with get_lock(gid):
        queue = get_queue(gid)
        queue.append(
            {
                "id": video_id,
                "title": display_title,
                "source": stream_url,
            }
        )
        cancel_idle_timer(gid)
        if not get_playing(gid):
            bot.loop.create_task(play_next(ctx))
        else:
            await ctx.send(f"➕ **Añadida a la cola:** {display_title}")


@bot.command()
async def queue(ctx):
    gid = ctx.guild.id
    q = get_queue(gid)
    if not q:
        return await ctx.send("La cola está vacía.")
    texto = "\n".join(
        [f"{idx + 1}. {item['title']}" for idx, item in enumerate(q)]
    )
    await ctx.send(f"📝 **Cola:**\n{texto}")


@bot.command()
async def skip(ctx):
    voice = ctx.voice_client
    if voice and voice.is_playing():
        voice.stop()
        await ctx.send("⏭️ Saltando...")
    else:
        await ctx.send("No hay nada sonando.")


@bot.command()
async def pause(ctx):
    voice = ctx.voice_client
    if voice and voice.is_playing():
        voice.pause()
        await ctx.send("⏸️ Pausado.")
    else:
        await ctx.send("Nada para pausar.")


@bot.command()
async def resume(ctx):
    voice = ctx.voice_client
    if voice and voice.is_paused():
        voice.resume()
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
    await ctx.send(f"🗑️ Eliminada de la cola: {removed['title']}")


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
    await ctx.send("🗂️ Cola eliminada por completo.")


bot.run(TOKEN)