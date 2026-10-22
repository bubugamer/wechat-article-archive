// Delegate authentication to the installed weread-omni SDK. Never emit identity or tokens.
import { pathToFileURL } from "node:url";
import { dirname, join } from "node:path";

const send = (value) => process.stdout.write(JSON.stringify(value) + "\n");
const controller = new AbortController();
process.on("SIGTERM", () => controller.abort());
process.on("SIGINT", () => controller.abort());

try {
  const cliPath = process.argv[2];
  const { runAccountCli } = await import(pathToFileURL(cliPath).href);
  const { AccountManager } = await import(pathToFileURL(join(dirname(cliPath), "index.js")).href);
  const code = await runAccountCli(["node", "weread-omni", "login", "--json"], {
    accountManager: new AccountManager(),
    signal: controller.signal,
    isTTY: false,
    renderQr: async (url) => {
      send({ event: "qr", url });
      return "";
    },
    stdout: { write() {} },
    stderr: {
      write(text) {
        const line = String(text).trim();
        if (/\bscanned\b/.test(line)) send({ event: "status", status: "scanned" });
        if (/\bconfirmed\b/.test(line)) send({ event: "status", status: "confirmed" });
        try {
          const value = JSON.parse(line);
          if (value.error) {
            const message = String(value.error);
            const reason = /expired|timed out/i.test(message) ? "expired"
              : /declined/i.test(message) ? "declined"
              : /network|transport|fetch|ticket|qrconnect/i.test(message) ? "network"
              : "failed";
            send({ event: "error", reason });
          }
        } catch { /* Diagnostic prose is intentionally not relayed. */ }
      },
    },
  });
  send({ event: "done", ok: code === 0 });
  process.exitCode = code;
} catch {
  send({ event: "error", reason: "failed" });
  process.exitCode = 1;
}
