import re, pathlib

ROOT = pathlib.Path("frontend")

# 1. Strip emojis / decorative symbols from all JSX + index.html
EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\u2139\uFE0F\u200D]+ ?")
for f in list(ROOT.glob("src/**/*.jsx")) + [ROOT / "index.html"]:
    s = f.read_text(encoding="utf8")
    s = EMOJI.sub("", s)
    s = s.replace("\u2190 ", "").replace("\u21ba ", "")          # "<- Back", reset arrow
    s = re.sub(r" \u2192(['<\s])", r"\1", s)                       # "Start Analysis ->"
    s = s.replace(">REQUIRED<", ">Required<").replace(">OPTIONAL<", ">Optional<")
    s = s.replace("ResumeIQ \u2014 AI-Powered Resume Analysis", "ResumeX | Resume analysis")
    f.write_text(s, encoding="utf8")

# 2. Remap hard-coded dark/indigo colours to the white + olive palette
MAP = {
    "99, 102, 241": "85, 107, 47", "99,102,241": "85,107,47",
    "168, 85, 247": "85, 107, 47", "139, 92, 246": "85, 107, 47",
    "6, 182, 212": "107, 142, 35", "34, 211, 238": "107, 142, 35",
    "52, 211, 153": "61, 122, 58", "248, 113, 113": "180, 35, 24",
    "251, 191, 36": "183, 121, 31", "96, 165, 250": "47, 102, 144",
    "148, 163, 184": "110, 116, 100", "255, 255, 255": "31, 36, 24",
    "255,255,255": "31,36,24", "6, 9, 15": "255, 255, 255",
    "15, 23, 42": "255, 255, 255", "30, 41, 59": "246, 247, 242",
}
HEX = {
    "#0f172a": "#ffffff", "#1e293b": "#f6f7f2", "#334155": "#dcdfd2",
    "#475569": "#6e7464", "#64748b": "#6e7464", "#94a3b8": "#6e7464",
    "#cbd5e1": "#4a5040", "#e2e8f0": "#1f2418", "#f8fafc": "#1f2418",
    "#6366f1": "#556b2f", "#818cf8": "#6b8e23", "#4f46e5": "#3f5122",
    "#a78bfa": "#556b2f", "#8b5cf6": "#556b2f", "#a855f7": "#556b2f",
    "#06b6d4": "#6b8e23", "#22d3ee": "#6b8e23", "#a5b4fc": "#556b2f",
    "#34d399": "#3d7a3a", "#fbbf24": "#b7791f", "#f97316": "#b7791f",
    "#f87171": "#b42318", "#ef4444": "#b42318", "#60a5fa": "#2f6690",
}
def remap(s):
    for a, b in MAP.items(): s = s.replace(a, b)
    for a, b in HEX.items(): s = re.sub(a, b, s, flags=re.I)
    return s

for f in ROOT.glob("src/**/*.jsx"):
    if f.name == "ResumeEditor.jsx":   # paper preview keeps its own print colours
        continue
    f.write_text(remap(f.read_text(encoding="utf8")), encoding="utf8")

# 3. Rewrite index.css: new tokens, no glass/glow, new fonts
css_path = ROOT / "src/index.css"
css = css_path.read_text(encoding="utf8")
main, sep, print_css = css.partition("@media print")
TOKENS = """:root {
  --bg-primary: #ffffff;
  --bg-secondary: #f6f7f2;
  --bg-card: #ffffff;
  --bg-card-solid: #ffffff;
  --bg-card-hover: #fafbf7;
  --bg-glass: #ffffff;
  --bg-input: #ffffff;
  --bg-surface: #f6f7f2;

  --text-primary: #1f2418;
  --text-secondary: #4a5040;
  --text-muted: #6e7464;
  --text-heading: #1a1f14;
  --text-accent: #556b2f;

  --accent-primary: #556b2f;
  --accent-primary-light: #6b8e23;
  --accent-primary-dark: #3f5122;
  --accent-glow: transparent;
  --accent-cyan: #6b8e23;
  --accent-violet: #556b2f;

  --accent-success: #3d7a3a;
  --accent-success-bg: #eef5ec;
  --accent-warning: #b7791f;
  --accent-warning-bg: #fbf4e6;
  --accent-danger: #b42318;
  --accent-danger-bg: #fcefed;
  --accent-info: #2f6690;
  --accent-info-bg: #edf3f8;

  --gradient-primary: #556b2f;
  --gradient-accent: #556b2f;
  --gradient-card: #ffffff;
  --gradient-hero: #ffffff;
  --gradient-score-good: #3d7a3a;
  --gradient-score-mid: #b7791f;
  --gradient-score-bad: #b42318;
  --gradient-mesh: none;

  --border-color: #dcdfd2;
  --border-subtle: #e8eae1;
  --border-glow: #556b2f;

  --shadow-sm: 0 1px 2px rgba(31, 36, 24, 0.06);
  --shadow-md: 0 2px 6px rgba(31, 36, 24, 0.08);
  --shadow-lg: 0 6px 18px rgba(31, 36, 24, 0.10);
  --shadow-glow: none;
  --shadow-glow-strong: none;
"""
main = re.sub(r":root\s*\{.*?--shadow-glow-strong:[^;]*;\n", TOKENS, main, count=1, flags=re.S)
main = re.sub(r"@import url\([^)]*\);",
  "@import url('https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;500;600;700&family=Source+Serif+4:opsz,wght@8..60,500;8..60,600&family=JetBrains+Mono:wght@400;500&display=swap');", main, count=1)
main = main.replace("'Inter'", "'Source Sans 3'")
main = re.sub(r"\s*-?(webkit-)?backdrop-filter:[^;]*;", "", main)
main = re.sub(r"\s*text-shadow:[^;]*;", "", main)
main = remap(main)
main += """
/* ResumeX professional theme overrides */
h1, h2, h3 { font-family: 'Source Serif 4', Georgia, serif; font-weight: 600; letter-spacing: -0.01em; }
body { background: var(--bg-secondary); background-image: none; }
.gradient-text, [class*="gradient-text"] { background: none !important; -webkit-text-fill-color: currentColor !important; color: var(--accent-primary) !important; }
.btn-primary { background: var(--accent-primary) !important; color: #fff !important; box-shadow: none !important; }
.btn-primary:hover { background: var(--accent-primary-dark) !important; transform: none !important; }
.card, .glass-card { background: #fff; border: 1px solid var(--border-color); box-shadow: var(--shadow-sm); }
*:focus-visible { outline: 2px solid var(--accent-primary); outline-offset: 2px; }
@media (prefers-reduced-motion: reduce) { * { animation: none !important; transition: none !important; } }
"""
css_path.write_text(main + sep + print_css, encoding="utf8")
print("Restyle done.")