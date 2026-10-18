const fs = require("fs");
const path = require("path");

const url = (process.env.API_URL || process.env.VITE_API_URL || "").trim().replace(/\/$/, "");
const production = process.env.CONTEXT === "production" || process.env.NETLIFY === "true";
if (!url && production) {
  console.error("Set API_URL to the Render backend URL before publishing the frontend.");
  process.exit(1);
}
const file = path.join(__dirname, "..", "config.js");
fs.writeFileSync(file, `window.JOBFINDER_API = ${JSON.stringify(url)};\n`);
console.log(url ? "Wrote frontend API URL." : "Wrote an empty API URL for same-origin use.");
