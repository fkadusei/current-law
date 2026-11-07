import { defineConfig } from "astro/config";

export default defineConfig({
  site: process.env.SITE_URL || "https://example.com",
  base: process.env.SITE_BASE || "/",
  trailingSlash: "ignore",
  build: { format: "directory" },
});
