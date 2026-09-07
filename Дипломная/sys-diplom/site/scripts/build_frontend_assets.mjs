import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const root = path.resolve(__dirname, "..");
const vendorDir = path.join(root, "app", "static", "vendor");

mkdirSync(vendorDir, { recursive: true });

const copies = [
  ["node_modules/htmx.org/dist/htmx.min.js", "htmx.min.js"],
  ["node_modules/alpinejs/dist/cdn.min.js", "alpine.min.js"],
  ["node_modules/chart.js/dist/chart.umd.js", "chart.umd.js"],
  ["node_modules/chartjs-plugin-zoom/dist/chartjs-plugin-zoom.min.js", "chartjs-plugin-zoom.min.js"],
];

for (const [sourceRelative, targetName] of copies) {
  const sourcePath = path.join(root, sourceRelative);
  const targetPath = path.join(vendorDir, targetName);
  if (!existsSync(sourcePath)) {
    throw new Error(`Missing frontend asset: ${sourceRelative}`);
  }
  copyFileSync(sourcePath, targetPath);
}
