import express from "express";
import cors from "cors";
import { spawn } from "child_process";

const app = express();
app.use(cors());

app.get("/proxy", async (req, res) => {
  const url = req.query.url;
  if (!url) return res.status(400).json({ error: "Missing url" });

  // Ejecutar yt-dlp para obtener el audio
  const ytdlp = spawn("yt-dlp", [
    "-f", "bestaudio",
    "-o", "-",
    url
  ]);

  // headers correctos para audio
  res.setHeader("Content-Type", "audio/mpeg");

  ytdlp.stdout.pipe(res);

  ytdlp.stderr.on("data", (data) => {
    console.error("yt-dlp error:", data.toString());
  });

  ytdlp.on("close", (code) => {
    if (code !== 0) {
      console.error("yt-dlp exited with code", code);
      res.end();
    }
  });
});

app.listen(10000, () => {
  console.log("YT Proxy running on port 10000");
});
