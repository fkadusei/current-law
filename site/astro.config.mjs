import { defineConfig } from "astro/config";

export default defineConfig({
  site: process.env.SITE_URL || "https://usacurrentlaw.org",
  base: process.env.SITE_BASE || "/",
  trailingSlash: "ignore",
  build: { format: "directory" },
});
