import express from "express";
import cors from "cors";
import fetch from "node-fetch";

const app = express();
app.use(cors());
const PORT = process.env.PORT || 3000;

const YT_HEADERS = {
  "User-Agent":
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
  "Accept-Language": "en-US,en;q=0.9",
  "Accept": "*/*",
  "Connection": "keep-alive"
};

// ----------- PROXY PARA YT-DLP --------------
app.get("/yt", async (req, res) => {
  let url = req.query.url;
  if (!url) return res.status(400).json({ error: "Falta ?url=" });

  try {
    const response = await fetch(url, { headers: YT_HEADERS });

    let contentType = response.headers.get("content-type") || "text/plain";
    res.setHeader("content-type", contentType);

    // devolvemos tal cual pero reescribimos URLs internas para evitar que yt-dlp llame directo a youtube
    let data = await response.text();

    data = data
      .replace(/https:\/\/rr\d*---/g, "https://yt-proxy.onrender.com/yt?url=https://rr")
      .replace(/https:\/\/redirector\.googlevideo\.com/g, "https://yt-proxy.onrender.com/yt?url=https://redirector.googlevideo.com")
      .replace(/https:\/\/youtube\.com/g, "https://yt-proxy.onrender.com/yt?url=https://youtube.com")
      .replace(/https:\/\/www\.youtube\.com/g, "https://yt-proxy.onrender.com/yt?url=https://www.youtube.com");

    res.send(data);
  } catch (err) {
    res.status(500).json({ error: "Proxy fail", details: err.message });
  }
});

// Home
app.get("/", (req, res) => {
  res.send("YT Proxy activo");
});

app.listen(PORT, () => {
  console.log("YT Proxy en el puerto " + PORT);
});
