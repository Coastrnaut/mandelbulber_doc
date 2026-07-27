#!/usr/bin/env python3
"""
LaTeX to HTML converter for Mandelbulber manual.
Converts .tex source files to a single-page HTML document with collapsible sidebar TOC.
"""

import os
import sys
import re
import shutil
import argparse
from pathlib import Path
from html import escape

# Heading ID counter
_heading_counter = [0]


def parse_args():
    parser = argparse.ArgumentParser(description="Convert Mandelbulber LaTeX manual to HTML")
    parser.add_argument("source", help="Path to mandelbulber2/manual directory")
    parser.add_argument("output", help="Output directory for HTML files")
    parser.add_argument("--index", action="store_true", help="Generate single-page HTML with TOC")
    return parser.parse_args()


def resolve_input(path, base_dir, repo_root=None):
    """Resolve \input{path} to actual file content, recursively processing \input{} directives."""
    # Skip makro.tex and preamble.tex — they contain \def macro definitions and
    # LaTeX package declarations, not content
    basename = path.replace("\\", "/").split("/")[-1]
    if basename in ("makro", "makro.tex", "preamble", "preamble.tex"):
        return ""
    # Always resolve \input{} paths relative to repo root (LaTeX source uses absolute paths from repo)
    if repo_root is not None:
        target = Path(repo_root) / path
    else:
        target = Path(base_dir) / path
    if not target.exists():
        # Try with .tex extension
        target_tex = Path(target).parent / (Path(target).stem + '.tex')
        if target_tex.exists():
            target = target_tex
        else:
            return f'<p class="error">File not found: {path}</p>'
    with open(target, "r", encoding="utf-8") as f:
        content = f.read()
    # Strip % comment lines from .tex files (lines that begin with %)
    # Only strip lines where % is the first non-whitespace character
    content = '\n'.join(
        line for line in content.split('\n')
        if not line.lstrip().startswith('%')
    )
    # Recursively process \input{} directives in the included file
    input_pattern = r'\\input\{([^}]+)\}'
    def replace_input(m):
        sub_path = m.group(1)
        return resolve_input(sub_path, base_dir, repo_root=repo_root)
    content = re.sub(input_pattern, replace_input, content)
    # Also process \include{} directives
    include_pattern = r'\\include\{([^}]+)\}'
    def replace_include(m):
        sub_path = m.group(1) + '.tex'
        return resolve_input(sub_path, base_dir, repo_root=repo_root)
    content = re.sub(include_pattern, replace_include, content)
    return content


def _strip_latex_for_slug(text):
    """Strip LaTeX commands from heading text for generating clean URL slugs."""
    # Remove \emph{...}, \textbf{...}, \textit{...}, \texttt{...} etc.
    # Use single backslash patterns to match LaTeX source text
    text = re.sub(r'\\emph\{([^}]*)\}', r'\1', text)
    text = re.sub(r'\\textbf\{([^}]*)\}', r'\1', text)
    text = re.sub(r'\\textit\{([^}]*)\}', r'\1', text)
    text = re.sub(r'\\texttt\{([^}]*)\}', r'\1', text)
    text = re.sub(r'\\text\{[^}]*\}', r'', text)
    # Remove any remaining \command{...} patterns
    text = re.sub(r'\\[a-zA-Z]+\{[^}]*\}', '', text)
    # Remove any remaining bare \commands, converting LaTeX escapes to their characters
    def strip_bare_cmd(m):
        name = m.group(1)
        esc = {'_': '_', '#': '#', '$': '$', '%': '%', '!': '!', '&': '&', '\\': '\\', '/': '/'}
        if name in esc:
            return esc[name]
        return ''
    # First handle bare backslash + non-alphabetic (e.g. \_ \# \$)
    text = re.sub(r'\\([^a-zA-Z])', lambda m: m.group(1), text)
    # Then handle bare \commands (alphabetic)
    text = re.sub(r'\\([a-zA-Z]+)', strip_bare_cmd, text)
    # Strip HTML tags that were already processed by the command loop
    text = re.sub(r'<[^>]*>', '', text)
    # Strip quotes and newlines to avoid breaking HTML attribute matching
    text = text.replace('"', '').replace("'", '').replace('{', '').replace('}', '')
    text = text.replace('\n', ' ').replace('\t', ' ')
    # Strip invalid HTML ID characters: &, ?, %, #, space, ., etc.
    text = re.sub(r'[&?#%,;:!\'\.\-]', '', text)
    # Remove leading/trailing dashes
    text = text.strip('-')
    return text


def _make_heading_id(text, level):
    """Generate a clean heading ID from raw LaTeX text."""
    clean = _strip_latex_for_slug(text)
    slug = clean.strip().lower().replace(' ', '-')
    slug = re.sub(r'-+', '-', slug)
    _heading_counter[0] += 1
    return f"sec-{_heading_counter[0]}-{slug}"


def _process_heading_text(raw):
    """Process raw LaTeX text in a heading tag for display.
    Converts \_, \&, \% etc. to their character equivalents.
    Strips \emph{}, \textbf{}, \texttt{} etc. wrapping."""
    text = raw
    # Strip wrapping commands like \emph{...}, \textbf{...}, \textit{...}, \texttt{...}
    for cmd in ['emph', 'textbf', 'textit', 'texttt', 'textsf', 'textup', 'textrm', 'bf', 'it', 'tt', 'rm', 'sf', 'large', 'Large', 'huge', 'scriptsize', 'footnotesize', 'tiny']:
        text = re.sub(r'\\' + cmd + r'\{([^}]*)\}', r'\1', text)
    # Process bare LaTeX escapes: \_ \& \% etc.
    def unescape_cmd(m):
        name = m.group(1)
        esc = {'_': '_', '#': '#', '$': '$', '%': '%', '!': '!', '&': '&', '\\': '\\', '/': '/'}
        if name in esc:
            return esc[name]
        return ''
    text = re.sub(r'\\([^a-zA-Z])', lambda m: m.group(1), text)
    text = re.sub(r'\\([a-zA-Z]+)', unescape_cmd, text)
    return text


def process_command(cmd_match):
    """Process a LaTeX command and return HTML."""
    cmd = cmd_match.group(1)
    args = cmd_match.group(2) or ""
    args = args.strip("{}")
    parts = [p.strip() for p in args.split(",") if p.strip()]

    if cmd == "textbf":
        return f"<strong>{parts[0]}</strong>" if parts else ""
    elif cmd == "textit":
        return f"<em>{parts[0]}</em>" if parts else ""
    elif cmd == "emph":
        # Handle nested content (e.g., from \textbf{\emph{text}})
        inner = parts[0] if parts else ""
        # Strip any HTML tags that leaked in
        inner = re.sub(r'<[^>]+>', '', inner)
        return f"<em>{inner}</em>" if inner else ""
    elif cmd == "verb":
        return f"<code>{parts[0]}</code>" if parts else ""
    elif cmd == "code":
        return f"<code>{parts[0]}</code>" if parts else ""
    elif cmd == "file":
        return f"<code>{parts[0]}</code>" if parts else ""
    elif cmd == "option":
        return f"<code>{parts[0]}</code>" if parts else ""
    elif cmd == "url":
        return f'<a href="{parts[0]}">{parts[0]}</a>' if parts else ""
    elif cmd == "email":
        return f'<a href="mailto:{parts[0]}">{parts[0]}</a>' if parts else ""
    elif cmd == "href":
        # \href{url}{text} - parts[0] is url, parts[1] is text
        if len(parts) >= 2:
            return f'<a href="{parts[0]}">{parts[1]}</a>'
        elif parts:
            return f'<a href="{parts[0]}">{parts[0]}</a>'
        return ""
    elif cmd == "index":
        return f'<span class="index-marker" data-index="{parts[0]}"></span>' if parts else ""
    elif cmd == "ref":
        return f'<a class="ref-link" href="#{parts[0]}">{parts[0]}</a>' if parts else ""
    elif cmd == "pageref":
        return f'<a class="ref-link" href="#{parts[0]}">page {parts[0]}</a>' if parts else ""
    elif cmd == "label":
        return f'<span id="{parts[0]}"></span>' if parts else ""
    elif cmd == "newlabel":
        return ""
    elif cmd == "vspace":
        return f'<div style="height: {parts[0]};"></div>' if parts else ""
    elif cmd == "hspace":
        return f'<span style="width: {parts[0]}; display: inline-block;"></span>' if parts else ""
    elif cmd == "section":
        if not parts:
            return ""
        rid = _make_heading_id(parts[0], 1)
        return f"<h1 id='{rid}'>{_process_heading_text(parts[0])}</h1>"
    elif cmd == "subsection":
        if not parts:
            return ""
        rid = _make_heading_id(parts[0], 2)
        return f"<h2 id='{rid}'>{_process_heading_text(parts[0])}</h2>"
    elif cmd == "subsubsection":
        if not parts:
            return ""
        rid = _make_heading_id(parts[0], 3)
        return f"<h3 id='{rid}'>{_process_heading_text(parts[0])}</h3>"
    elif cmd == "paragraph":
        if not parts:
            return ""
        rid = _make_heading_id(parts[0], 4)
        return f"<h4 id='{rid}'>{_process_heading_text(parts[0])}</h4>"
    elif cmd == "subparagraph":
        if not parts:
            return ""
        rid = _make_heading_id(parts[0], 5)
        return f"<h5 id='{rid}'>{_process_heading_text(parts[0])}</h5>"
    elif cmd == "textcolor":
        # \textcolor{color}{text} - parts[0] is color, parts[1] is text
        if len(parts) >= 2:
            return f'<span style="color:{parts[0]}">{parts[1]}</span>'
        elif parts:
            return f'<span style="color:{parts[0]}">{parts[0]}</span>'
        return ""
    elif cmd == "color":
        if parts:
            return f'<span style="color:{parts[0]}">'
        return ""
    elif cmd == "texttt":
        return f"<code>{parts[0]}</code>" if parts else ""
    elif cmd == "tt":
        return f"<code>{parts[0]}</code>" if parts else ""
    elif cmd == "bf":
        return f"<strong>{parts[0]}</strong>" if parts else ""
    elif cmd == "it":
        return f"<em>{parts[0]}</em>" if parts else ""
    elif cmd == "text":
        # \text{...} in math mode - just return the content
        return parts[0] if parts else ""
    elif cmd == "mathrm":
        # \mathrm{...} in math mode - just return the content
        return parts[0] if parts else ""
    elif cmd == "mathbf":
        return f"<strong>{parts[0]}</strong>" if parts else ""
    elif cmd == "mathit":
        return f"<em>{parts[0]}</em>" if parts else ""
    elif cmd == "textsuperscript":
        return f"<sup>{parts[0]}</sup>" if parts else ""
    elif cmd == "textsubscript":
        return f"<sub>{parts[0]}</sub>" if parts else ""
    elif cmd == "smallcaps":
        return f"<span style='font-variant:small-caps'>{parts[0]}</span>" if parts else ""
    elif cmd == "underline":
        return f"<u>{parts[0]}</u>" if parts else ""
    elif cmd == "sout":
        return f"<s>{parts[0]}</s>" if parts else ""
    elif cmd == "textrm":
        return parts[0] if parts else ""
    elif cmd == "large":
        return f"<span style='font-size:1.2em'>{parts[0]}</span>" if parts else ""
    elif cmd == "Large":
        return f"<span style='font-size:1.5em'>{parts[0]}</span>" if parts else ""
    elif cmd == "huge":
        return f"<span style='font-size:1.8em'>{parts[0]}</span>" if parts else ""
    elif cmd == "scriptsize":
        return f"<span style='font-size:0.8em'>{parts[0]}</span>" if parts else ""
    elif cmd == "footnotesize":
        return f"<span style='font-size:0.9em'>{parts[0]}</span>" if parts else ""
    elif cmd == "tiny":
        return f"<span style='font-size:0.7em'>{parts[0]}</span>" if parts else ""
    elif cmd == "rm":
        return parts[0] if parts else ""
    elif cmd == "sf":
        return f"<span style='font-family:sans-serif'>{parts[0]}</span>" if parts else ""
    elif cmd == "textsf":
        return f"<span style='font-family:sans-serif'>{parts[0]}</span>" if parts else ""
    elif cmd == "textup":
        return parts[0] if parts else ""
    elif cmd == "textrm":
        return parts[0] if parts else ""
    elif cmd == "frac":
        # \frac{num}{den} — parts[0] is num, parts[1] is den (two separate brace args)
        if len(parts) >= 2:
            return f"<sup>{parts[0]}</sup>/<sub>{parts[1]}</sub>"
        return parts[0] if parts else ""
    elif cmd == "sqrt":
        return f"<sup>&radic;({parts[0]})</sup>" if parts else ""
    elif cmd == "begin":
        return f"<span class='begin-{parts[0]}'>" if parts else ""
    elif cmd == "end":
        return f"</span>" if parts else ""
    elif cmd == "textgreater":
        return "&gt;"
    elif cmd == "textless":
        return "&lt;"
    elif cmd == "textperiodcentered":
        return "&middot;"
    elif cmd == "textvisiblespace":
        return "&#x2423;"
    elif cmd == "textasciicircum":
        return "&#x2038;"
    elif cmd == "textbackslash":
        return "&#x2039;"
    elif cmd == "textasciitilde":
        return "&#x007E;"
    elif cmd == "textem":
        return "&#x0153;"
    elif cmd == "textonehalf":
        return "1.5"
    elif cmd == "textonequarter":
        return "0.25"
    elif cmd == "textonehalf":
        return "1.5"
    elif cmd == "textthreequarters":
        return "0.75"
    elif cmd == "textfractionsolidus":
        return "/"
    elif cmd == "texttrademark":
        return "&#x2122;"
    elif cmd == "textregistered":
        return "&#x00AE;"
    elif cmd == "textcopyright":
        return "&#x00A9;"
    elif cmd == "textless":
        return "&lt;"
    elif cmd == "textgreater":
        return "&gt;"
    elif cmd == "textbar":
        return "&#x00A6;"
    elif cmd == "textbraceleft":
        return "{"
    elif cmd == "textbraceright":
        return "}"
    elif cmd == "texttt":
        return f"<code>{parts[0]}</code>" if parts else ""
    elif cmd == "tt":
        return f"<code>{parts[0]}</code>" if parts else ""
    elif cmd == "bf":
        return f"<strong>{parts[0]}</strong>" if parts else ""
    elif cmd == "it":
        return f"<em>{parts[0]}</em>" if parts else ""
    elif cmd == "text":
        # \text{...} in math mode - just return the content
        return parts[0] if parts else ""
    elif cmd == "mathrm":
        # \mathrm{...} in math mode - just return the content
        return parts[0] if parts else ""
    elif cmd == "mathbf":
        return f"<strong>{parts[0]}</strong>" if parts else ""
    elif cmd == "mathit":
        return f"<em>{parts[0]}</em>" if parts else ""
    elif cmd == "textsuperscript":
        return f"<sup>{parts[0]}</sup>" if parts else ""
    elif cmd == "textsubscript":
        return f"<sub>{parts[0]}</sub>" if parts else ""
    elif cmd == "smallcaps":
        return f"<span style='font-variant:small-caps'>{parts[0]}</span>" if parts else ""
    elif cmd == "underline":
        return f"<u>{parts[0]}</u>" if parts else ""
    elif cmd == "sout":
        return f"<s>{parts[0]}</s>" if parts else ""
    elif cmd == "large":
        return f"<span style='font-size:1.2em'>{parts[0]}</span>" if parts else ""
    elif cmd == "Large":
        return f"<span style='font-size:1.5em'>{parts[0]}</span>" if parts else ""


def process_image_macro(content):
    """Process \includegraphics[opts]{path} and custom \simpleImageWithCaption{Type}{path}."""
    # Map custom macro suffixes to width percentages
    width_map = {
        'FullWidth': '',
        '75Width': '75%',
        'HalfWidth': '50%',
        'ThirdWidth': '33%',
        'SmallWidth': '200px',
    }

    # Process custom \simpleImageWithCaption{Type}{path} macros
    custom_pattern = r'\\simpleImageWithCaption(75Width|FullWidth|HalfWidth|SmallWidth|ThirdWidth)\{([^}]+)\}'
    def replace_custom_image(m):
        suffix = m.group(1)
        path = m.group(2)
        width = width_map.get(suffix, '')
        # Images are at img/manual/media/ relative to repo root (same as LaTeX source)
        html_path = path.replace("\\", "/")
        if width:
            return f'<img src="{html_path}" alt="{path}" style="max-width:{width}; height:auto; display:block; margin:1em auto;" />'
        else:
            return f'<img src="{html_path}" alt="{path}" style="max-width:100%; height:auto; display:block; margin:1em auto;" />'
    content = re.sub(custom_pattern, replace_custom_image, content)

    # Process standard \includegraphics[opts]{path}
    pattern = r'\\includegraphics(\[[^\]]*\])?\{([^}]+)\}'
    def replace_image(m):
        opts = m.group(1) or ""
        path = m.group(2)
        width = ""
        height = ""
        # Handle width=0.3\linewidth style
        width_match = re.search(r"width=([\d.]+)(\\?linewidth|in|pt|px)?", opts)
        if width_match:
            val = float(width_match.group(1))
            unit = width_match.group(2) or 'linewidth'
            if 'linewidth' in unit:
                width = f"{val}linewidth"
            elif 'in' in unit:
                # Convert inches to pixels (96 DPI)
                width = str(int(val * 96))
            else:
                width = str(int(val))
        height_match = re.search(r"height=([\d.]+)(in|pt|px)?", opts)
        if height_match:
            val = float(height_match.group(1))
            unit = height_match.group(2) or 'pt'
            if 'in' in unit:
                # Convert inches to pixels (96 DPI)
                height = str(int(val * 96))
            elif 'pt' in unit:
                # Convert points to pixels (1pt = 1.333px at 96 DPI)
                height = str(int(val * 4 / 3))
            else:
                height = str(int(val))
        # Images are at img/manual/media/ relative to repo root (same as LaTeX source)
        html_path = path.replace("\\", "/")
        # Use style-based sizing (consistent with \simpleImageWithCaption)
        style_parts = ['height:auto', 'display:block', 'margin:1em auto']
        # Sound images use 50% width; other images use pixel width if available
        if 'sound' in path.lower():
            style_parts.insert(0, 'max-width:50%')
        elif width:
            style_parts.insert(0, 'max-width:{}px'.format(width))
        else:
            style_parts.insert(0, 'max-width:100%')
        style = '; '.join(style_parts)
        return '<img src="{}" alt="{}" style="{}" />'.format(html_path, path, style)
    content = re.sub(pattern, replace_image, content)
    return content


def process_content(content, base_dir, repo_root=None):
    """Main content processing function."""
    # Process \input{} commands first
    input_pattern = r'\\input\{([^}]+)\}'
    def replace_input(m):
        path = m.group(1)
        return resolve_input(path, base_dir, repo_root=repo_root)
    content = re.sub(input_pattern, replace_input, content)

    # Process \include{} commands
    include_pattern = r'\\include\{([^}]+)\}'
    def replace_include(m):
        path = m.group(1) + ".tex"
        return resolve_input(path, base_dir, repo_root=repo_root)
    content = re.sub(include_pattern, replace_include, content)

    # Process environments
    env_pattern = r'\\begin\{([^}]+)\}(.*?)\\end\{\1\}'
    def replace_env(m):
        env_name = m.group(1)
        body = m.group(2)
        if env_name == "verbatim":
            return f'<pre class="verbatim">{escape(body)}</pre>'
        elif env_name == "figure":
            return f'<figure class="figure">{body}</figure>'
        elif env_name == "table":
            return f'<table class="table">{body}</table>'
        elif env_name == "itemize":
            items = []
            for line in body.split("\n"):
                line = line.strip()
                if line.startswith("\\item"):
                    line = line[5:].strip()
                    items.append(f"<li>{line}</li>")
            return f"<ul>{chr(10).join(items)}</ul>"
        elif env_name == "enumerate":
            items = []
            for i, line in enumerate(body.split("\n"), 1):
                line = line.strip()
                if line.startswith("\\item"):
                    line = line[5:].strip()
                    items.append(f"<li>{i}. {line}</li>")
            return f"<ol>{chr(10).join(items)}</ol>"
        elif env_name == "quote":
            return f"<blockquote>{body}</blockquote>"
        elif env_name == "quotation":
            return f"<blockquote>{body}</blockquote>"
        else:
            return f'<div class="{env_name}">{body}</div>'
    content = re.sub(env_pattern, replace_env, content, flags=re.DOTALL)

    # Process images BEFORE other commands (to avoid double-processing)
    content = process_image_macro(content)

    # Pre-process \frac{num}{den} and \sqrt{expr} before the main loop
    # These have two separate brace arguments that the general regex can't handle
    def replace_frac(m):
        num = m.group(1)
        den = m.group(2)
        return f"<sup>{num}</sup>/<sub>{den}</sub>"
    content = re.sub(r'\\frac\{([^}]*)\}\{([^}]*)\}', replace_frac, content)

    def replace_sqrt(m):
        expr = m.group(1)
        return f"<sup>&radic;({expr})</sup>"
    content = re.sub(r'\\sqrt\{([^}]*)\}', replace_sqrt, content)

    # Process commands iteratively until stable (handles nested \textbf{\emph{text}})
    # Use brace-aware regex that handles one level of nesting
    cmd_pattern = r'\\([a-zA-Z]+)\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}'
    prev = None
    iteration = 0
    while prev != content and iteration < 20:
        prev = content
        content = re.sub(cmd_pattern, process_command, content)
        iteration += 1
    if iteration >= 20:
        print("Warning: command processing hit 20 iterations, some nesting may remain")

    # Clean up any remaining unprocessed \href leftovers: {text} after </a>
    content = re.sub(r'</a>\s*\{([^}]*)\}', r'</a> \1', content)
    
    # Post-process: fix \emph{} artifacts that contain HTML tags from failed brace nesting
    emph_pattern = r'\\emph\{([^}]*(?:\{[^}]*\})?[^}]*)\}'
    def fix_emph(m):
        inner = m.group(1)
        # Strip any HTML tags
        inner = re.sub(r'<[^>]+>', '', inner)
        # Unescape LaTeX escapes
        inner = inner.replace('\\_', '_')
        return f'<em>{inner}</em>'
    content = re.sub(emph_pattern, fix_emph, content)
    
    # Post-process: fix remaining unprocessed nested brace patterns
    # These are LITERAL curly braces in the HTML (not backslash-escaped)
    def fix_braces(m):
        text = m.group(0)
        # Unescape LaTeX escapes
        text = text.replace('\\_', '_').replace('\\#', '#').replace('\\$', '$')
        # Remove outer braces
        if text.startswith('{') and text.endswith('}'):
            text = text[1:-1]
        return text
    # Fix {begin{...}}, {end{...}} patterns (literal braces in HTML)
    content = re.sub(r'\{begin\{[^}]+\}\}', fix_braces, content)
    content = re.sub(r'\{end\{[^}]+\}\}', fix_braces, content)
    # Fix {texttt{...}}, {textbf{...}} etc.
    for cmd in ['texttt', 'textbf', 'textit', 'text', 'bf', 'it', 'tt']:
        content = re.sub(r'\{' + cmd + r'\{([^}]*)\}\}', fix_braces, content)
    # Fix {textgreater{}} patterns
    content = re.sub(r'\{textgreater\{\}\}', '>', content)
    # Fix twoImagesWithTwoCaptionsFullWidth{...} patterns
    content = re.sub(r'\{twoImagesWithTwoCaptionsFullWidth\{([^}]*)\}\}', lambda m: m.group(1), content)
    # Fix {[}...{]} literal bracket patterns
    content = re.sub(r'\{\[\}([^}]*)\{\]\}', r'[\1]', content)
    
    # Convert remaining \item commands to <li> tags
    content = re.sub(r'\\item\s*', '<li>', content)
    
    return content


def generate_toc(content):
    """Generate sidebar TOC from headings in processed content."""
    # Extract all headings with their IDs
    headings = []
    # Match h1, h2, h3, h4, h5 tags with id attributes (single or double quotes)
    heading_pattern = r'<h([1-6])[^>]*id=[\'"]([^\'"]+)[\'"][^>]*>(.*?)</h\1>'
    for match in re.finditer(heading_pattern, content):
        level = int(match.group(1))
        anchor = match.group(2)
        text = re.sub(r'<[^>]+>', '', match.group(3)).strip()  # Strip any remaining HTML tags
        if text and anchor:
            headings.append((level, anchor, text))
    
    if not headings:
        return '<div class="sidebar"><h3>Table of Contents</h3><p>No sections found.</p></div>'
    
    # Build TOC HTML
    toc_html = '<div class="sidebar">\n<h3>Table of Contents</h3>\n<ul>\n'
    last_level = 0
    
    for level, anchor, text in headings:
        # Close open tags if we go back up
        while level < last_level:
            toc_html += '</ul></li>\n'
            last_level -= 1
        # Open new nested lists if we go deeper
        if level > last_level:
            if last_level > 0:
                toc_html += '</li>\n<li>\n<ul>\n'
            else:
                toc_html += '<li>\n<ul>\n'
            last_level = level
        else:
            toc_html += '</li>\n<li>\n'
        
        toc_html += f'<li><a href="#{anchor}">{escape(text)}</a></li>\n'
    
    # Close remaining open tags
    for i in range(last_level, 0, -1):
        toc_html += '</ul></li>\n'
    
    toc_html += '</ul>\n</div>'
    return toc_html


def generate_html(title, content, toc):
    """Generate complete HTML document."""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TITLE_PLACEHOLDER</title>
<link rel="stylesheet" href="css/style.css">
<script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
</head>
<body>
<h1>TITLE_PLACEHOLDER</h1>
TOC_PLACEHOLDER
<div id="content">
CONTENT_PLACEHOLDER
</div>
</body>
</html>"""
    return (
        html.replace("TITLE_PLACEHOLDER", escape(title), 2)
        .replace("TOC_PLACEHOLDER", toc)
        .replace("CONTENT_PLACEHOLDER", content)
    )


def main():
    args = parse_args()
    source = Path(args.source)

    # Resolve base_dir to repo root for correct \input{} resolution
    repo_root = str(Path(args.source).parent.parent)

    # Copy CSS to repo root (skip if already there)
    css_src = Path("css/style.css")
    css_dst = Path(repo_root) / "css" / "style.css"
    if css_src.exists():
        if css_src.resolve() != css_dst.resolve():
            css_dst.parent.mkdir(exist_ok=True)
            shutil.copy2(css_src, css_dst)

    main_file = Path(repo_root) / "handbook.tex"
    if not main_file.exists():
        print(f"Error: {main_file} not found")
        sys.exit(1)

    with open(main_file, "r", encoding="utf-8") as f:
        content = f.read()
    # Strip % comment lines from .tex files (lines that begin with %)
    content = '\n'.join(
        line for line in content.split('\n')
        if not line.lstrip().startswith('%')
    )

    processed = process_content(content, repo_root)

    title = "Mandelbulber Manual"
    
    # Generate TOC from headings
    toc = generate_toc(processed)
    
    html = generate_html(title, processed, toc)

    output_file = Path(repo_root) / "index.html"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Generated {output_file}")


if __name__ == "__main__":
    main()
