/**
 * Preload — runs in an isolated context before the page scripts.
 *
 * Exposes the API origin to the page via contextBridge so the UI can call the
 * proxy even if the port had to change from the default 8787. Secure: only this
 * one read-only value crosses the isolation boundary.
 */
const { contextBridge } = require("electron");

// main.js passes the chosen origin via additionalArguments.
const arg = process.argv.find((a) => a.startsWith("--ai-base="));
const aiBase = arg ? arg.slice("--ai-base=".length) : "http://127.0.0.1:8787";

contextBridge.exposeInMainWorld("DXB_ELECTRON", { aiBase });
