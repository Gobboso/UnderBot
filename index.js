import express from "express";
import cors from "cors";
import ytdl from "@distube/ytdl-core";
import fetch from "node-fetch";

const app = express();
app.use(cors());

// Cache simple en memoria (expira después de 1 hora)
const cache = new Map();
const CACHE_TTL = 60 * 60 * 1000; // 1 hora

// Limpiar cache periódicamente
setInterval(() => {
  const now = Date.now();
  for (const [key, value] of cache.entries()) {
    if (now - value.timestamp > CACHE_TTL) {
      cache.delete(key);
    }
  }
}, 10 * 60 * 1000); // Cada 10 minutos

app.get("/audio", async (req, res) => {
  const id = req.query.id;
  if (!id) return res.status(400).json({ error: "Video ID requerido" });

  // Verificar cache primero
  const cached = cache.get(id);
  if (cached && Date.now() - cached.timestamp < CACHE_TTL) {
    return res.json(cached.data);
  }

  const maxRetries = 2;
  let lastError = null;

  for (let attempt = 0; attempt < maxRetries; attempt++) {
    try {
      const videoUrl = `https://www.youtube.com/watch?v=${id}`;
      
      // Opciones mejoradas para evitar rate limiting
      const options = {
        requestOptions: {
          headers: {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
          },
        },
      };
      
      // Delay aleatorio antes de la petición (0-2 segundos)
      if (attempt > 0) {
        const delay = Math.random() * 2000;
        await new Promise(resolve => setTimeout(resolve, delay));
      }
      
      // Obtener información del video con opciones
      const info = await ytdl.getInfo(videoUrl, options);
      
      // Buscar el mejor formato de audio disponible
      const audioFormats = ytdl.filterFormats(info.formats, "audioonly");
      
      if (audioFormats.length === 0) {
        return res.status(500).json({ 
          error: "No se encontraron formatos de audio disponibles" 
        });
      }
      
      // Elegir el mejor formato (mayor bitrate)
      const bestFormat = audioFormats
        .filter(f => f.hasAudio && !f.hasVideo)
        .sort((a, b) => (b.audioBitrate || 0) - (a.audioBitrate || 0))[0];
      
      if (!bestFormat || !bestFormat.url) {
        return res.status(500).json({ 
          error: "No se pudo obtener URL del formato de audio" 
        });
      }

      const result = {
        title: info.videoDetails?.title || "Audio",
        url: bestFormat.url
      };

      // Guardar en cache
      cache.set(id, {
        data: result,
        timestamp: Date.now()
      });

      return res.json(result);

    } catch (e) {
      lastError = e;
      const errorMsg = e.toString();
      
      // Si es error 429 (rate limit), intentar método alternativo
      if (errorMsg.includes("429") || errorMsg.includes("Status code: 429")) {
        if (attempt < maxRetries - 1) {
          // Esperar más tiempo antes de reintentar
          const waitTime = (attempt + 1) * 3000; // 3s, 6s
          await new Promise(resolve => setTimeout(resolve, waitTime));
          continue;
        }
        
        // Último intento: método alternativo directo
        try {
          const altResult = await getAudioAlternative(id);
          if (altResult) {
            cache.set(id, {
              data: altResult,
              timestamp: Date.now()
            });
            return res.json(altResult);
          }
        } catch (altError) {
          // Si el método alternativo también falla, devolver error
        }
        
        return res.status(429).json({ 
          error: "Rate limit excedido. YouTube está bloqueando las peticiones. Intenta más tarde." 
        });
      }
      
      // Si no es 429, devolver error inmediatamente
      return res.status(500).json({ 
        error: errorMsg.includes("Status code") 
          ? `Error de YouTube: ${errorMsg}` 
          : errorMsg 
      });
    }
  }

  // Si llegamos aquí, todos los reintentos fallaron
  return res.status(500).json({ 
    error: lastError ? lastError.toString() : "Error desconocido" 
  });
});

// Método alternativo usando fetch directo (fallback)
async function getAudioAlternative(videoId) {
  try {
    const watchUrl = `https://www.youtube.com/watch?v=${videoId}`;
    
    const response = await fetch(watchUrl, {
      headers: {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
      },
    });

    const html = await response.text();
    
    // Buscar ytInitialPlayerResponse
    const match = html.match(/var ytInitialPlayerResponse = ({.+?});/s);
    if (!match) return null;
    
    const player = JSON.parse(match[1]);
    const formats = [
      ...(player.streamingData?.adaptiveFormats || []),
      ...(player.streamingData?.formats || [])
    ].filter(f => f.mimeType && f.mimeType.includes("audio"));
    
    if (formats.length === 0) return null;
    
    const best = formats
      .filter(f => f.bitrate && f.url)
      .sort((a, b) => b.bitrate - a.bitrate)[0];
    
    if (!best || !best.url) return null;
    
    return {
      title: player?.videoDetails?.title || "Audio",
      url: best.url
    };
  } catch (e) {
    return null;
  }
}

app.get("/", (req, res) => {
  res.send("YT proxy funcionando sin DRM 😉");
});

app.listen(10000, () => {
  console.log("Servidor activo en puerto 10000");
});
