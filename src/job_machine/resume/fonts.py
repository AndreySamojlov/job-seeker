"""Self-hosted Spectral/Public Sans embedding for the résumé PDF template.

Base64 data-URI @font-face — no live Google Fonts fetch at render time
(determinism: PDF rendering must not depend on network availability).
Single Public Sans file covers the whole 400-700 weight range (variable-font
instancing — validated to render distinct weights in Chromium via a manual
test during design); Spectral is embedded at weight 600 only, the only
weight the template uses.
"""
import base64
from pathlib import Path

_ASSETS_DIR = Path(__file__).parent / "assets" / "fonts"


def _b64(filename: str) -> str:
    return base64.b64encode((_ASSETS_DIR / filename).read_bytes()).decode("ascii")


FONT_FACES_CSS = f"""
@font-face {{
  font-family:'Public Sans';
  font-weight:400 700;
  font-style:normal;
  src:url(data:font/woff2;base64,{_b64('public-sans-latin.woff2')}) format('woff2');
}}
@font-face {{
  font-family:'Spectral';
  font-weight:600;
  font-style:normal;
  src:url(data:font/woff2;base64,{_b64('spectral-600-latin.woff2')}) format('woff2');
}}
"""
