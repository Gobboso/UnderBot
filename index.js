import express from "express";
import cors from "cors";
import fetch from "node-fetch";

const app = express();
app.use(cors());

app.get("/audio", async (req, res) => {
  const id = req.query.id;
  if (!id) return res.status(400).json({ error: "Video ID requerido" });

  try {
    const watchUrl = `https://www.youtube.com/watch?v=${id}`;

    const response = await fetch(watchUrl, {
      headers: {
        "User-Agent":
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/121 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
      },
    });

    const html = await response.text();

    // Buscar el objeto ytInitialPlayerResponse
    const jsonMatch = html.match(/ytInitialPlayerResponse\s*=\s*(\{.*?\});/);

    if (!jsonMatch) {
      return res.status(500).json({ error: "No se encontró playerResponse" });
    }

    const player = JSON.parse(jsonMatch[1]);

    // Extraer solo formatos de audio
    const formats = [
      ...(player.streamingData?.adaptiveFormats || []),
      ...(player.streamingData?.formats || [])
    ].filter(f => f.mimeType && f.mimeType.includes("audio"));

    if (formats.length === 0) {
      return res.status(500).json({ error: "No hay formatos de audio (DRM)" });
    }

    // Elegir el mejor audio disponible
    const best = formats
      .filter(f => f.bitrate)
      .sort((a, b) => b.bitrate - a.bitrate)[0];

    if (!best || !best.url) {
      return res.status(500).json({ error: "No se pudo extraer URL" });
    }

    return res.json({
      title: player?.videoDetails?.title || "Audio",
      url: best.url
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
