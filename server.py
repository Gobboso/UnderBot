import yt_dlp
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

# Opciones yt-dlp anti-DRM
YDL_OPTS = {
    "quiet": True,
    "skip_download": True,
    "geo_bypass": True,
    "nocheckcertificate": True,
    "extract_flat": False,

    # ⚠️ PROXY para evitar formatos 'DRM'
    "proxy": "http://pipedproxy.kavin.rocks",

    "format": (
        "bestaudio[acodec=opus][vcodec=none]/"
        "bestaudio[ext=webm][vcodec=none]/"
        "bestaudio[ext=m4a][vcodec=none]/"
        "bestaudio/best"
    ),

    # ⚠️ Evitar DASH/HLS (causa DRM en hostings)
    "extractor_args": {
        "youtube": {
            "player_client": ["web"],
            "skip": ["dash", "hls"]
        }
    }
}


@app.get("/audio")
def get_audio(id: str):
    if not id:
        raise HTTPException(400, "ID requerido")

    url = f"https://www.youtube.com/watch?v={id}"

    try:
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            info = ydl.extract_info(url, download=False)

        # URL final limpia sin DRM
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
