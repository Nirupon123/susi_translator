import { defineConfig } from "@rsbuild/core";
import { pluginReact } from "@rsbuild/plugin-react";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const srcPath = path.resolve(__dirname, "./src");

export default defineConfig({
  plugins: [pluginReact()],

  source: {
    entry: {
      index: "./src/index.js",
    },
  },

  html: {
    template: "./public/index.html",
  },

  server: {
    port: 3000,
    proxy: {
      "/auth": {
        target: "http://127.0.0.1:5040",
        changeOrigin: true,
      },
      "/session": {
        target: "http://127.0.0.1:5040",
        changeOrigin: true,
      },
      "/stop_event": {
        target: "http://127.0.0.1:5040",
        changeOrigin: true,
      },
      "/api": {
        target: "http://127.0.0.1:5040",
        changeOrigin: true,
      },
      "/ws": {
        target: "ws://127.0.0.1:5040",
        changeOrigin: true,
        ws: true,
      },
      "/transcripts": {
        target: "http://127.0.0.1:5040",
        changeOrigin: true,
      },
    },
  },

  output: {
    distPath: {
      root: "build",
    },
  },

  tools: {
    rspack: {
      resolve: {
        alias: {
          "@": srcPath,
        },
      },
    },
  },
});
