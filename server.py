import yt_dlp
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI()

# Permitir peticiones desde cualquier parte (para tu bot)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------
# INSTANCIAS PIPED (PROXY Fallback)
# -----------------------------
PIPED_PROXIES = [
    "https://pipedapi.tokhmi.xyz",
    "https://api-piped.mha.fi",
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.moomoo.me",
]

def obtener_proxy_activo():
    """Devuelve el primer proxy Piped que esté funcionando"""
    for proxy in PIPED_PROXIES:
        try:
            r = requests.get(proxy, timeout=2)
            if r.status_code == 200:
                print(f"[OK] Proxy activo → {proxy}")
                return proxy
        except:
            continue
    print("[ALERTA] Ningún proxy Piped respondió, usando conexión directa")
    return None


def get_ydl_options():
    """Genera opciones para yt-dlp con proxy dinámico."""
    proxy_url = obtener_proxy_activo()

    opts = {
        "quiet": True,
        "skip_download": True,
        "geo_bypass": True,
        "nocheckcertificate": True,
        "extract_flat": False,

        "format": (
            "bestaudio[acodec=opus][vcodec=none]/"
            "bestaudio[ext=webm][vcodec=none]/"
            "bestaudio[ext=m4a][vcodec=none]/"
            "bestaudio/best"
        ),

        "extractor_args": {
            "youtube": {
                "player_client": ["web"],
                "skip": ["dash", "hls"]
            }
        }
    }

    if proxy_url:
        opts["proxy"] = proxy_url

    return opts


# -------------------------------------
#              ENDPOINT /audio
# -------------------------------------
@app.get("/audio")
def get_audio(id: str):
    if not id:
        raise HTTPException(400, "ID requerido")

    url = f"https://www.youtube.com/watch?v={id}"

    ydl_opts = get_ydl_options()

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        audio_url = info.get("url")
        title = info.get("title")

        if not audio_url:
            raise HTTPException(500, "No se pudo obtener audio sin DRM.")

        return {
            "url": audio_url,
            "title": title
        }

    except Exception as e:
        raise HTTPException(500, f"Error: {str(e)}")


# Para correr localmente
if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8080)
