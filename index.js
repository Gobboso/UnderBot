import express from "express";
import cors from "cors";
import ytdl from "@distube/ytdl-core";

const app = express();
app.use(cors());

app.get("/audio", async (req, res) => {
  const id = req.query.id;
  if (!id) return res.status(400).json({ error: "Video ID requerido" });

  try {
    const videoUrl = `https://www.youtube.com/watch?v=${id}`;
    
    // Obtener información del video
    const info = await ytdl.getInfo(videoUrl);
    
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
    return res.status(500).json({ error: e.toString() });
  }
});

app.get("/", (req, res) => {
  res.send("YT proxy funcionando sin DRM 😉");
});

app.listen(10000, () => {
  console.log("Servidor activo en puerto 10000");
});
