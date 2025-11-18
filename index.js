import express from "express";
import cors from "cors";
import fetch from "node-fetch";

const app = express();
app.use(cors());

// === YouTube STREAM FIX ===
// Forzar player=web → evita DRM
const YT_PLAYER_URL =
  "https://www.youtube.com/get_video_info?html5=1&c=WEB&cver=2.20210721.00.00&video_id=";

app.get("/audio", async (req, res) => {
  const id = req.query.id;
  if (!id) return res.status(400).json({ error: "Video ID requerido" });

  try {
    const infoURL = YT_PLAYER_URL + id;

    const response = await fetch(infoURL, {
      headers: {
        "User-Agent":
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
      },
    });

    const text = await response.text();

    if (!text.includes("adaptive_fmts")) {
      return res
        .status(500)
        .json({ error: "YouTube no devolvió formatos (DRM o bloqueo)" });
    }

    // Buscar la mejor URL de audio
    const match = text.match(/https:[^,]+mime=audio[^,]+/g);

    if (!match || !match[0]) {
      return res.status(500).json({ error: "No se encontró audio" });
    }

    let audioURL = decodeURIComponent(match[0]);

    // Limpiar parámetros rotos
    audioURL = audioURL.replace(/\\u0026/g, "&");

    return res.json({
      url: audioURL,
      title: "Audio Stream",
    });
  } catch (e) {
    return res.status(500).json({ error: e.toString() });
  }
});

app.get("/", (req, res) => {
  res.send("YT proxy funcionando 😉");
});

const PORT = process.env.PORT || 10000;
app.listen(PORT, () => console.log("Servidor activo en puerto " + PORT));
