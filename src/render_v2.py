from pathlib import Path
from graphdeck.assets import render_html_to_image
html = Path(r'.\out\visual_ai-for-small-business_v2.html').read_text(encoding='utf-8')
render_html_to_image(html, r'.\out\visual_ai-for-small-business_v2.png', width=1600, height=900, device_scale=1.5)
