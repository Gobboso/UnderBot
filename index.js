import express from "express";
import cors from "cors";
import ytdl from "@distube/ytdl-core";

const app = express();
app.use(cors());

app.get("/audio", async (req, res) => {
  const id = req.query.id;
  if (!id) return res.status(400).json({ error: "Video ID requerido" });

  const maxRetries = 3;
  let lastError = null;

  for (let attempt = 0; attempt < maxRetries; attempt++) {
    try {
      const videoUrl = `https://www.youtube.com/watch?v=${id}`;
      
      // Opciones para evitar rate limiting
      const options = {
        requestOptions: {
          headers: {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
          },
        },
      };
      
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

      return res.json({
        title: info.videoDetails?.title || "Audio",
        url: bestFormat.url
      });

    } catch (e) {
      lastError = e;
      const errorMsg = e.toString();
      
      // Si es error 429 (rate limit), esperar antes de reintentar
      if (errorMsg.includes("429") || errorMsg.includes("Status code: 429")) {
        if (attempt < maxRetries - 1) {
          // Esperar progresivamente más tiempo (1s, 2s, 3s)
          const waitTime = (attempt + 1) * 1000;
          await new Promise(resolve => setTimeout(resolve, waitTime));
          continue;
        }
        return res.status(429).json({ 
          error: "Rate limit excedido. Intenta de nuevo en unos momentos." 
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

app.get("/", (req, res) => {
  res.send("YT proxy funcionando sin DRM 😉");
});

app.listen(10000, () => {
  console.log("Servidor activo en puerto 10000");
});
