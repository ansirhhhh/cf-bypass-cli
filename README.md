# cf-bypass-cli

Progressive Cloudflare WAF bypass CLI tool.

A local command-line tool that uses **progressive fallback strategies** to automatically bypass Cloudflare anti-bot challenges. Starts with lightweight methods and escalates to full browser automation when needed.

## Features

- **Progressive bypass** — L1 (cloudscraper) → L2 (curl_cffi) → L3 (playwright+stealth) → L4 (nodriver)
- **Cookie persistence** — Validated cookies are cached per domain for instant reuse
- **Enhanced stealth** — Differentiated fingerprints across L3/L4 with JS evasion patches
- **Turnstile solver** — Automatic captcha resolution via capsolver/2captcha API integration
- **Smart challenge polling** — Exponential backoff polling replaces fixed waits in L4
- **Proxy health checks** — Pre-flight proxy validation with geo-verification
- **Manual intervention** — Headed mode auto-pauses for manual challenge completion
- **HTTP API mode** — Start a local server (`cf-bypass serve`) for programmatic access
- **Batch processing** — Process URL lists and export results to CSV
- **Proxy support** — Route requests through HTTP/SOCKS proxies with quality grading

## Installation

```bash
# Clone and enter the project
cd cf-bypass-cli

# Create a virtual environment (recommended)
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # Linux/macOS

# Install the package
pip install -e .

# Install browser engines
playwright install chromium
```

## Quick Start

```bash
# Bypass a single URL (prints HTML)
cf-bypass https://example.com

# Get cookies only
cf-bypass --cookie-only https://example.com

# Start the HTTP API server
cf-bypass serve --port 8191

# Check stored cookies
cf-bypass status

# Clear cache
cf-bypass clear

# Batch process
cf-bypass batch urls.txt -o results.csv
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `cf-bypass <url>` | Bypass a single URL, print HTML |
| `cf-bypass --cookie-only <url>` | Print cookies as JSON |
| `cf-bypass serve` | Start HTTP API server |
| `cf-bypass status` | Show stored cookies |
| `cf-bypass clear` | Clear cached cookies |
| `cf-bypass batch <file>` | Process URLs from file → CSV |

## HTTP API

```
POST http://localhost:8191/bypass
Content-Type: application/json

{
    "url": "https://example.com",
    "cookie_only": false,
    "timeout": 60,
    "proxy": "http://user:pass@proxy:8080"
}
```

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/bypass` | Bypass a URL |
| GET | `/health` | Health check |
| GET | `/cookies` | List stored cookies |
| DELETE | `/cookies/{domain}` | Delete domain cookies |

## Configuration

Edit `~/.cf-bypass/config.yaml`:

```yaml
timeout: 60
headless: false          # headed mode recommended for CF

strategies:
  - cloudscraper
  - curl_cffi
  - playwright
  - nodriver

proxy:
  enabled: false
  url: ""

storage:
  path: "~/.cf-bypass/cookies"
```

## Strategy Levels

| Level | Engine | Speed | Success Rate |
|-------|--------|-------|-------------|
| L1 | cloudscraper | < 1s | Low (basic JS challenge) |
| L2 | curl_cffi | 1-2s | Medium (TLS fingerprint) |
| L3 | playwright + stealth | 5-15s | High (full browser) |
| L4 | nodriver | 5-15s | Highest (CDP-level stealth) |

## License

MIT
