"""
Z.ai Sidecar — Pure Python (NO Node.js needed)

Uses the z-ai CLI to provide vision, image generation, and web search
as HTTP endpoints that the main bot can call via aiohttp.

Usage:
    python zai_sidecar.py

Endpoints:
    POST /vision     — {"image_b64": "...", "prompt": "..."}
    POST /generate   — {"prompt": "...", "size": "1024x1024"}
    POST /search     — {"query": "...", "num": 5}
    GET  /health     — {"status": "ok"}
"""

import json
import logging
import os
import subprocess
import sys
import tempfile
import base64
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

logger = logging.getLogger("zai_sidecar")
PORT = int(os.environ.get("ZAI_SIDECAR_PORT", 3456))


def _extract_json(text):
    """Extract JSON object or array from CLI output that may contain emoji lines.

    The z-ai CLI prints emoji progress lines (like "🚀 Initializing...")
    mixed with the actual JSON response. The JSON can be multi-line (pretty-printed).
    This function finds the first '[' or '{' and accumulates until the matching
    closing bracket, handling nested structures.
    """
    depth = 0
    start = -1
    in_string = False
    escape_next = False

    for i, ch in enumerate(text):
        if escape_next:
            escape_next = False
            continue
        if ch == '\\' and in_string:
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue

        if ch in ('[', '{'):
            if depth == 0:
                start = i
            depth += 1
        elif ch in (']', '}'):
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    pass

    return None


def run_cli(args, timeout=60):
    """Run a z-ai CLI command and return parsed JSON output."""
    try:
        cmd = ["z-ai"] + args
        logger.info(f"Running CLI: {' '.join(cmd[:4])}...")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            logger.error(f"CLI error (exit {result.returncode}): {result.stderr[:300]}")
            return None

        # Log stdout for debugging (first 500 chars)
        stdout_preview = result.stdout[:500].replace('\n', '\\n')
        logger.debug(f"CLI stdout preview: {stdout_preview}")

        # Try to extract JSON from mixed emoji+JSON output
        parsed = _extract_json(result.stdout)
        if parsed is None:
            logger.error(f"No valid JSON in CLI output. stdout={result.stdout[:300]}")
            return None

        return parsed

    except subprocess.TimeoutExpired:
        logger.error(f"CLI timed out after {timeout}s")
        return None
    except FileNotFoundError:
        logger.error("z-ai CLI not found! Make sure z-ai is installed on the system.")
        return None
    except Exception as e:
        logger.error(f"CLI run error: {e}")
        return None


def handle_vision(data):
    """Analyze an image using z-ai vision CLI."""
    image_b64 = data.get("image_b64")
    image_url = data.get("image_url")
    prompt = data.get("prompt", "Describe this image in detail.")

    if not image_b64 and not image_url:
        return {"error": "Provide image_b64 or image_url"}

    if image_b64:
        tmp_path = None
        try:
            if image_b64.startswith("data:"):
                header, image_b64 = image_b64.split(",", 1)
                mime = header.split(":")[1].split(";")[0]
            else:
                mime = "image/png"
            ext = mime.split("/")[1].replace("jpeg", "jpg")
            with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as f:
                f.write(base64.b64decode(image_b64))
                tmp_path = f.name

            result = run_cli(["vision", "-p", prompt, "-i", tmp_path], timeout=90)
        except Exception as e:
            return {"error": str(e)}
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
    else:
        result = run_cli(["vision", "-p", prompt, "-i", image_url], timeout=90)

    if result and isinstance(result, dict) and "choices" in result:
        content = result["choices"][0].get("message", {}).get("content", "")
        return {"content": content}
    return {"error": "Failed to analyze image", "raw": str(result)[:300] if result else "No response"}


def handle_generate(data):
    """Generate an image using z-ai image CLI."""
    prompt = data.get("prompt", "a beautiful landscape")
    size = data.get("size", "1024x1024")
    valid_sizes = ["1024x1024", "768x1344", "864x1152", "1344x768", "1152x864", "1440x720", "720x1440"]
    if size not in valid_sizes:
        size = "1024x1024"

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp_path = f.name

        logger.info(f"[GENERATE] prompt=\"{prompt[:80]}\", size={size}, output={tmp_path}")
        result = subprocess.run(
            ["z-ai", "image", "-p", prompt, "-o", tmp_path, "-s", size],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            stderr_preview = result.stderr[:300] if result.stderr else "(empty)"
            stdout_preview = result.stdout[:200] if result.stdout else "(empty)"
            logger.error(f"[GENERATE] CLI error (exit {result.returncode}): stderr={stderr_preview}")
            logger.error(f"[GENERATE] CLI stdout: {stdout_preview}")
            return {"error": "Image generation failed", "stderr": stderr_preview}

        if not os.path.exists(tmp_path):
            logger.error(f"[GENERATE] No output file at {tmp_path}")
            return {"error": "Image generation failed — no output file"}
        file_size = os.path.getsize(tmp_path)
        if file_size < 1000:
            os.unlink(tmp_path)
            logger.error(f"[GENERATE] Output file too small: {file_size} bytes")
            return {"error": "Image generation failed — output file too small"}

        logger.info(f"[GENERATE] Success! File size: {file_size} bytes")
        with open(tmp_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        return {"image_b64": b64, "format": "png"}
    except subprocess.TimeoutExpired:
        logger.error("[GENERATE] Timed out after 120s")
        return {"error": "Image generation timed out"}
    except Exception as e:
        logger.error(f"[GENERATE] Exception: {e}")
        return {"error": str(e)}
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def handle_search(data):
    """Search the web using z-ai function CLI."""
    query = data.get("query", "")
    num = min(data.get("num", 5), 10)

    if not query:
        return {"error": "No query provided"}

    args_json = json.dumps({"query": query, "num": num})
    result = run_cli(["function", "-n", "web_search", "-a", args_json], timeout=30)

    if isinstance(result, list):
        cleaned = []
        for item in result[:num]:
            cleaned.append({
                "url": item.get("url", ""),
                "name": item.get("name", ""),
                "snippet": item.get("snippet", ""),
                "host_name": item.get("host_name", ""),
            })
        return {"results": cleaned}
    return {"error": "Search failed", "raw": str(result)[:300] if result else "No response"}


class SidecarHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler for the sidecar."""

    def log_message(self, fmt, *args):
        logger.debug(f"Sidecar: {fmt % args}")

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        body = self.rfile.read(length)
        try:
            return json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self._send_json({"status": "ok"})
        else:
            self._send_json({"error": "Not found"}, 404)

    def do_POST(self):
        try:
            data = self._read_body()
            if self.path == "/vision":
                result = handle_vision(data)
            elif self.path == "/generate":
                result = handle_generate(data)
            elif self.path == "/search":
                result = handle_search(data)
            else:
                result = {"error": f"Unknown endpoint: {self.path}"}
            status = 500 if "error" in result else 200
            self._send_json(result, status)
        except Exception as e:
            logger.error(f"Request error: {e}", exc_info=True)
            self._send_json({"error": str(e)}, 500)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    logger.info(f"Z.ai Sidecar starting on port {PORT} (pure Python, no Node.js)")

    # Verify z-ai CLI
    try:
        result = subprocess.run(["z-ai", "--help"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            logger.info("z-ai CLI found and working")
        else:
            logger.warning(f"z-ai CLI returned exit code {result.returncode}: {result.stderr[:200]}")
    except FileNotFoundError:
        logger.error("z-ai CLI not found! Sidecar endpoints will return errors.")
        logger.error("Install z-ai CLI to enable vision, image gen, and web search features.")
    except Exception as e:
        logger.error(f"z-ai CLI check failed: {e}")

    server = HTTPServer(("127.0.0.1", PORT), SidecarHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Sidecar shutting down")
        server.server_close()


if __name__ == "__main__":
    main()
