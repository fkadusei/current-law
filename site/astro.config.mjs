import { defineConfig } from "astro/config";

export default defineConfig({
  site: "https://fkadusei.github.io",
  base: process.env.SITE_BASE || "/",
  trailingSlash: "ignore",
  build: { format: "directory" },
});
