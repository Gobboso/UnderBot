import express from "express";
import cors from "cors";
import fetch from "node-fetch";

const app = express();
app.use(cors());

// NEW: endpoint moderno que evita DRM (innerTube web client)
const PLAYER_API =
  "https://www.youtube.com/youtubei/v1/player?key=AIzaSyC7YkP2…"; // clave oficial anonima pública

const bodyBase = {
  context: {
    client: {
      clientName: "WEB",
      clientVersion: "2.20230101.00.00"
    }
  }
};

app.get("/audio", async (req, res) => {
  const id = req.query.id;
  if (!id) {
    return res.status(400).json({ error: "Video ID requerido" });
  }

  try {
    const response = await fetch(PLAYER_API, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
      },
      body: JSON.stringify({
        ...bodyBase,
        videoId: id
      })
    });

    const json = await response.json();

    const fmts =
      json.streamingData?.adaptiveFormats?.filter((f) =>
        f.mimeType.includes("audio")
      ) || [];

    if (!fmts.length) {
      return res
        .status(500)
        .json({ error: "YouTube bloqueó el audio o devolvió DRM" });
    }

    const best = fmts.sort((a, b) => b.bitrate - a.bitrate)[0];

    return res.json({
      url: best.url,
      title: json.videoDetails?.title || "Audio Stream"
    });
  } catch (e) {
    return res.status(500).json({ error: e.toString() });
  }
});

app.get("/", (req, res) => {
  res.send("YT proxy funcionando 😉");
});

// *** IMPORTANTE: USAR PUERTO DE RENDER ***
const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log("Servidor activo en puerto " + PORT));
