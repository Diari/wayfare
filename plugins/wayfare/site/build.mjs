// Build for ChatGPT Sites: copy the worker modules to dist/server and the
// hosting link to dist/.openai. No dependencies and no bundler: the worker is
// plain ES modules (index.js imports page.js and data.js).
import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";

rmSync("dist", { recursive: true, force: true });
mkdirSync("dist/server", { recursive: true });
cpSync("worker", "dist/server", { recursive: true });
if (existsSync(".openai")) cpSync(".openai", "dist/.openai", { recursive: true });
if (existsSync("migrations")) cpSync("migrations", "dist/migrations", { recursive: true });
for (const f of ["index.js", "page.js", "data.js"]) {
  if (!existsSync(`dist/server/${f}`)) {
    console.error(`missing worker/${f}: run wayfare.py site-bundle first`);
    process.exit(1);
  }
}
console.log("Built dist/server (worker) and dist/.openai (hosting link).");
