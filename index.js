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

    // Extraer URL del player.js
    const extractPlayerScriptUrl = (html) => {
      const patterns = [
        /<script[^>]*src="([^"]*\/base\.js[^"]*)"/,
        /"jsUrl":"([^"]*\/base\.js[^"]*)"/,
        /"PLAYER_JS_URL":"([^"]*\/base\.js[^"]*)"/,
      ];

      for (const pattern of patterns) {
        const match = html.match(pattern);
        if (match) {
          const url = match[1].replace(/\\\//g, '/');
          return url.startsWith('http') ? url : `https://www.youtube.com${url}`;
        }
      }
      return null;
    };

    // Extraer y ejecutar función de descifrado
    const extractDecipherFunction = async (playerScriptUrl) => {
      if (!playerScriptUrl) return null;

      try {
        const response = await fetch(playerScriptUrl, {
          headers: {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
          },
        });
        const script = await response.text();

        // Buscar función de descifrado (múltiples patrones)
        const patterns = [
          /function\s+(\w+)\(a\)\{a=a\.split\(""\);[\s\S]{1,2000}return\s+a\.join\(""\)\}/,
          /var\s+(\w+)\s*=\s*function\s*\(a\)\{a=a\.split\(""\);[\s\S]{1,2000}return\s+a\.join\(""\)\}/,
        ];

        for (const pattern of patterns) {
          const match = script.match(pattern);
          if (match) {
            const funcName = match[1];
            const funcBody = match[0];

            // Buscar el mapeo de funciones (ej: var b={funcName:funcName})
            const mappingMatch = script.match(
              new RegExp(`var\\s+\\w+\\s*=\\s*\\{[^}]*"${funcName}"[^}]*\\}`)
            );

            if (mappingMatch) {
              // Extraer operaciones del cuerpo de la función
              const operations = [];
              const lines = funcBody.split(';');

              for (const line of lines) {
                if (line.includes('.reverse()')) {
                  operations.push({ type: 'reverse' });
                } else if (line.includes('.splice(')) {
                  const spliceMatch = line.match(/\.splice\((\d+)/);
                  if (spliceMatch) {
                    operations.push({ 
                      type: 'splice', 
                      index: parseInt(spliceMatch[1]) 
                    });
                  }
                } else if (line.includes('a[0]') && line.includes('a[')) {
                  const swapMatch = line.match(/a\[(\d+)\s*%\s*a\.length\]/);
                  if (swapMatch) {
                    operations.push({ 
                      type: 'swap', 
                      index: parseInt(swapMatch[1]) 
                    });
                  }
                }
              }

              return operations.length > 0 ? operations : null;
            }
          }
        }
      } catch (e) {
        // Error al obtener script
      }
      return null;
    };

    // Descifrar firma usando operaciones extraídas
    const decipherSignature = (sig, operations) => {
      if (!operations || operations.length === 0) return sig;

      let result = sig.split('');
      for (const op of operations) {
        if (op.type === 'reverse') {
          result = result.reverse();
        } else if (op.type === 'splice') {
          result = result.slice(op.index);
        } else if (op.type === 'swap') {
          const idx = op.index % result.length;
          const temp = result[0];
          result[0] = result[idx];
          result[idx] = temp;
        }
      }
      return result.join('');
    };

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

    let finalUrl = best.url;

    // Si tiene signatureCipher, parsearlo y construir URL
    if (!finalUrl && best.signatureCipher) {
      try {
        // Parsear signatureCipher (formato: "url=...&sp=...&s=...")
        const params = new URLSearchParams(best.signatureCipher);
        const baseUrl = params.get('url');
        const signature = params.get('s');
        const sp = params.get('sp') || 'signature';

        if (!baseUrl) {
          return res.status(500).json({ 
            error: "No se pudo extraer URL base de signatureCipher" 
          });
        }

        // Intentar obtener función de descifrado
        const playerScriptUrl = extractPlayerScriptUrl(html);
        let decipheredSig = signature;

        if (signature && playerScriptUrl) {
          const operations = await extractDecipherFunction(playerScriptUrl);
          if (operations) {
            decipheredSig = decipherSignature(signature, operations);
          }
        }

        finalUrl = `${baseUrl}&${sp}=${encodeURIComponent(decipheredSig)}`;
      } catch (e) {
        return res.status(500).json({ 
          error: `Error procesando signatureCipher: ${e.message}` 
        });
      }
    }

    if (!finalUrl) {
      return res.status(500).json({ 
        error: "No se pudo obtener URL del formato" 
      });
    }

    return res.json({
      title: player?.videoDetails?.title || "Audio",
      url: finalUrl
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
