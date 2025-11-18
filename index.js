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

    // Función para extraer JSON balanceando llaves
    const extractJSON = (text, pattern) => {
      const match = text.match(pattern);
      if (!match) return null;
      
      const startIndex = match.index + match[0].indexOf('{');
      let braceCount = 0;
      let inString = false;
      let escapeNext = false;
      
      for (let i = startIndex; i < text.length; i++) {
        const char = text[i];
        
        if (escapeNext) {
          escapeNext = false;
          continue;
        }
        
        if (char === '\\') {
          escapeNext = true;
          continue;
        }
        
        if (char === '"' && !escapeNext) {
          inString = !inString;
          continue;
        }
        
        if (!inString) {
          if (char === '{') braceCount++;
          if (char === '}') {
            braceCount--;
            if (braceCount === 0) {
              const jsonStr = text.substring(startIndex, i + 1);
              try {
                return JSON.parse(jsonStr);
              } catch (e) {
                return null;
              }
            }
          }
        }
      }
      return null;
    };

    // Intentar múltiples patrones
    let player = null;
    const patterns = [
      /var\s+ytInitialPlayerResponse\s*=\s*/,
      /window\["ytInitialPlayerResponse"\]\s*=\s*/,
      /ytInitialPlayerResponse\s*=\s*/
    ];

    for (const pattern of patterns) {
      player = extractJSON(html, pattern);
      if (player) break;
    }

    if (!player) {
      return res.status(500).json({ error: "No se encontró playerResponse" });
    }

    // Verificar que streamingData existe
    if (!player.streamingData) {
      return res.status(500).json({ 
        error: "YouTube no devolvió formatos (DRM o bloqueo)" 
      });
    }

    // Extraer solo formatos de audio
    const formats = [
      ...(player.streamingData.adaptiveFormats || []),
      ...(player.streamingData.formats || [])
    ].filter(f => f && f.mimeType && f.mimeType.includes("audio"));

    if (formats.length === 0) {
      return res.status(500).json({ 
        error: "YouTube no devolvió formatos (DRM o bloqueo)" 
      });
    }

    // Elegir el mejor audio disponible (con URL directa o signatureCipher)
    const best = formats
      .filter(f => f.bitrate && (f.url || f.signatureCipher))
      .sort((a, b) => b.bitrate - a.bitrate)[0];

    if (!best) {
      return res.status(500).json({ 
        error: "YouTube no devolvió formatos (DRM o bloqueo)" 
      });
    }

    // Si tiene signatureCipher, necesitaríamos descifrarlo (complejo)
    // Por ahora solo devolvemos URLs directas
    if (!best.url) {
      return res.status(500).json({ 
        error: "Formato requiere descifrado (signatureCipher)" 
      });
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
