"""Find template placeholders ("Hi {{first_name}},") in text, compare them with the data that fills them, and flag ones left unfilled."""
import csv
import io
import json
import re

# (syntax name, pattern, group holding the variable name). Earlier patterns win overlaps.
SYNTAXES = [
    ("{{{ }}}", re.compile(r"\{\{\{\s*([A-Za-z_][\w.\-]*)[^}]*\}\}\}"), 1),
    ("{{ }}", re.compile(r"\{\{\s*([A-Za-z_][\w.\-]*)[^{}]*\}\}"), 1),
    ("[[ ]]", re.compile(r"\[\[\s*([A-Za-z_][\w. \-]*?)\s*\]\]"), 1),
    ("*| |* (Mailchimp)", re.compile(r"\*\|([A-Za-z_][\w:.\-]*)\|\*"), 1),
    ("%% %%", re.compile(r"%%([A-Za-z_][\w.\-]*)%%"), 1),
    ("<< >>", re.compile(r"&lt;&lt;\s*([A-Za-z_][\w.\-]*)\s*&gt;&gt;|<<\s*([A-Za-z_][\w.\-]*)\s*>>"), 0),
    ("${ }", re.compile(r"\$\{\s*([A-Za-z_][\w.\-]*)\s*\}"), 1),
    ("%(name)s", re.compile(r"%\(([A-Za-z_]\w*)\)[sdif]"), 1),
    ("{name}", re.compile(r"(?<![{\w$])\{([A-Za-z_][\w.\-]*|\d+)\}(?!\})"), 1),
    ("[NAME]", re.compile(r"\[([A-Z][A-Z0-9_ ]{2,})\]"), 1),
    ("%s / %d", re.compile(r"(?<![\w%])%[sd](?![\w])"), 0),
]
LOCALS = re.compile(r"\{%-?\s*(?:for\s+(\w+)(?:\s*,\s*(\w+))?\s+in|(?:set|assign|with)\s+(\w+)\s*=|(?:capture)\s+(\w+))")
BLOCK = re.compile(r"\{%-?\s*(end)?(if|for|unless|block|with|capture|case|comment|raw)\b[^%]*-?%\}")
NOT_PLACEHOLDERS = {"TODO", "FIXME", "NOTE", "XXX", "PDF", "IMG", "GIF", "EMAIL PROTECTED"}      # bracketed words that are usually just words


class Finding:
    def __init__(self, level, line, rule, message):
        self.level, self.line, self.rule, self.message = level, line, rule, message

    def __repr__(self):
        return "%s line %d [%s] %s" % (self.level, self.line, self.rule, self.message)


def line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def scan(text):
    """Returns a list of dicts {syntax, name, text, line, pos} for every placeholder found, in order of position."""
    found, taken = [], []
    for syntax, rx, group in SYNTAXES:
        for m in rx.finditer(text):
            if any(m.start() < b and a < m.end() for a, b in taken):
                continue
            name = m.group(group) if group else (m.group(1) or m.group(2) if syntax == "<< >>" else None)
            if syntax == "[NAME]" and name.strip() in NOT_PLACEHOLDERS:
                continue
            if syntax == "%s / %d" and re.match(r"\d", text[m.end():m.end() + 1] or "x"):
                continue
            taken.append((m.start(), m.end()))
            found.append({"syntax": syntax, "name": (name or "").strip(), "text": m.group(0), "line": line_of(text, m.start()), "pos": m.start()})
    return sorted(found, key=lambda f: f["pos"])


def blocks(text):
    """Findings for unbalanced {% if %}/{% endif %}-style blocks."""
    out, stack = [], []
    for m in BLOCK.finditer(text):
        end, kind = bool(m.group(1)), m.group(2)
        line = line_of(text, m.start())
        if not end:
            stack.append((kind, line))
        elif stack and stack[-1][0] == kind:
            stack.pop()
        else:
            out.append(Finding("error", line, "block", "{%% end%s %%} closes nothing (the innermost open block is %s)" % (kind, "{% " + stack[-1][0] + " %}" + " from line %d" % stack[-1][1] if stack else "none")))
    for kind, line in stack:
        out.append(Finding("error", line, "block", "{%% %s %%} is never closed" % kind))
    return out


def load_data(text):
    """Field names from a JSON object (nested keys as a.b), a CSV header line, or a .env file."""
    text = text.lstrip("﻿")
    s = text.lstrip()
    if s.startswith("{"):
        obj = json.loads(s)
        names = set()

        def walk(o, prefix=""):
            if isinstance(o, dict):
                for k, v in o.items():
                    names.add(prefix + k)
                    walk(v, prefix + k + ".")
        walk(obj)
        return names
    first_line = next((l for l in text.split("\n") if l.strip() and not l.lstrip().startswith("#")), "")
    if re.match(r"^\s*(?:export\s+)?[A-Za-z_][\w]*\s*=", first_line) and "," not in first_line:
        return {line.split("=", 1)[0].replace("export ", "").strip() for line in text.split("\n") if "=" in line and not line.lstrip().startswith("#")}
    return {c.strip() for c in next(csv.reader(io.StringIO(text)))}


def check(text, data=None, rendered=False, allow=()):
    """Findings for the placeholders in text. data: a set of available field names or None; rendered: any placeholder is a leak."""
    found = [f for f in scan(text) if f["text"] not in allow and f["name"] not in allow]
    findings = blocks(text)
    if rendered:
        for f in found:
            findings.append(Finding("error", f["line"], "unfilled", "%s is still in the text (%s syntax)" % (f["text"], f["syntax"])))
        return findings, found
    if data is not None:
        lower = {d.lower(): d for d in data}
        used = set()
        local_names = {g for m in LOCALS.finditer(text) for g in m.groups() if g} | {"loop", "forloop"}     # loop variables and {% set %} names are not data fields
        for tag in re.findall(r"\{%-?(.*?)-?%\}", text, re.S):                                            # a field named inside a tag ({% for x in items %}) counts as used
            used |= {w for w in re.findall(r"[A-Za-z_][\w.]*", tag) if w in data}
        for f in found:
            name = f["name"]
            if name and name.split(".")[0].split("|")[0].strip() in local_names:
                continue
            if not name or name.isdigit():
                findings.append(Finding("warn", f["line"], "positional", "%s is a positional placeholder; it cannot be checked against named data" % f["text"]))
                continue
            key = name.split("|")[0].strip()
            if key in data or key.split(".")[0] in data:
                used.add(key if key in data else key.split(".")[0])
            elif key.lower() in lower:
                findings.append(Finding("error", f["line"], "case", "%s is not in the data, but %r is: field names are usually case-sensitive" % (f["text"], lower[key.lower()])))
                used.add(lower[key.lower()])
            elif key.replace(" ", "_").lower() in lower:
                findings.append(Finding("error", f["line"], "case", "%s is not in the data, but %r is" % (f["text"], lower[key.replace(" ", "_").lower()])))
                used.add(lower[key.replace(" ", "_").lower()])
            else:
                findings.append(Finding("error", f["line"], "missing", "%s uses %r, which is not in the data (the fields are: %s)" % (f["text"], key, ", ".join(sorted(data)) or "none")))
        for d in sorted(data - used):
            findings.append(Finding("info", 0, "unused", "the data field %r is never used in the text" % d))
    return sorted(findings, key=lambda f: (f.line, f.rule)), found
