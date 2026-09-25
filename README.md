# placeholders

Find template placeholders in emails and text **before you send**: an unfilled `{{first_name}}`, a `[NAME]` that never got replaced, a merge field missing from your data, a `{% if %}` that never closes. Standard library only, Python 3.9+. It reads text; it sends nothing.

Nothing looks worse than an email that starts "Hi {{ first_name }}," or "Dear [NAME]".

```
$ python -m placeholders template.html --data data.json
9 placeholders (9 distinct):
  {{ }}                  {{ first_name|default:"there line 1
  {{ }}                  {{plan}}                     line 2
  [NAME]                 [CODE]                       line 2
  %(name)s               %(order_id)s                 line 2
  {name}                 {0}                          line 2
  {{ }}                  {{ First_Name }}             line 3
  {{ }}                  {{ item.name }}              line 4
  *| |* (Mailchimp)      *|UNSUB|*                    line 6
  %s / %d                %s                           line 6
info  [unused] the data field 'unused_field' is never used in the text
error line 2 [missing] [CODE] uses 'CODE', which is not in the data (the fields are: first_name, items, order_id, plan, unused_field, vip)
error line 3 [case] {{ First_Name }} is not in the data, but 'first_name' is: field names are usually case-sensitive
error line 4 [block] {% for %} is never closed
...

$ echo "Hi {{ first_name }}, welcome" | python -m placeholders - --rendered
error line 1 [unfilled] {{ first_name }} is still in the text ({{ }} syntax)
```

## Usage

```
python -m placeholders FILE [--data FILE] [--rendered] [--allow NAMES] [--json]
```

| Mode | Meaning |
| --- | --- |
| *(default)* | List every placeholder with its syntax and line numbers, and check that `{% if %}`, `{% for %}` and similar blocks are balanced. |
| `--data FILE` | Also check each placeholder against the fields you will fill it with: a JSON object (nested keys as `a.b`), a CSV (its header row) or a `.env` file. A field the text needs but the data lacks is an **error**; a name that differs only by case or spaces is an error with a hint; a data field the text never uses is info. |
| `--rendered` | The text is the **final** email: any placeholder still in it is an error. Use this as the last check before sending, or in CI. |

`--allow` ignores names (or exact placeholder text) that you know are fine, such as a merge tag your sending service fills in. `-` reads standard input. Exit code `1` if there are errors, `2` if a file can't be read.

## Syntaxes recognised

`{{ name }}` (Jinja, Liquid, Handlebars, Django, with filters such as `|default:"x"`), `{{{ name }}}`, `{% if %}...{% endif %}` blocks, `[[name]]`, `*|NAME|*` (Mailchimp), `%%name%%`, `<<name>>` (also HTML-escaped), `${name}`, `%(name)s`, `{name}` and `{0}` (Python format), `[NAME]` (bracketed capitals), and bare `%s` / `%d`. Loop variables from `{% for x in items %}` and names from `{% set %}` are not treated as data fields, and neither are `loop` or `forloop`. CSS such as `body { color: red }` and JSON such as `{"a": 1}` are not mistaken for placeholders.

## What it does not do

- It does not render your template or know your template engine's rules; it looks at text patterns. A `{name}` in an ordinary sentence will be reported, and a placeholder syntax it does not know will be missed.
- Bracketed capitals like `[CODE]` are reported, but words such as `[TODO]`, `[NOTE]` and `[PDF]` are not; use `--allow` for other bracketed labels.
- Positional placeholders (`%s`, `{0}`) cannot be checked against named data, so they get a warning.

## Tests

```
python -m unittest discover -s tests -v
```

MIT licence.
