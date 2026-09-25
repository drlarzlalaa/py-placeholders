import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import placeholders as ph
from placeholders.__main__ import main

TEMPLATE = os.path.join(HERE, "data", "template.html")
DATA = os.path.join(HERE, "data", "data.json")


def names(text):
    return [(f["syntax"], f["name"]) for f in ph.scan(text)]


def rules(text, data=None, **kw):
    return sorted((f.level, f.rule) for f in ph.check(text, data, **kw)[0])


class Scan(unittest.TestCase):
    def test_each_syntax(self):
        cases = {
            "Hi {{ first_name }}": ("{{ }}", "first_name"), "Hi {{first_name}}": ("{{ }}", "first_name"), "{{{ html }}}": ("{{{ }}}", "html"),
            "{{ user.name|upper }}": ("{{ }}", "user.name"), "Hi [[first_name]]": ("[[ ]]", "first_name"), "Hi *|FNAME|*": ("*| |* (Mailchimp)", "FNAME"),
            "Hi %%first_name%%": ("%% %%", "first_name"), "Hi <<first_name>>": ("<< >>", "first_name"), "Hi &lt;&lt;first_name&gt;&gt;": ("<< >>", "first_name"),
            "Hi ${first_name}": ("${ }", "first_name"), "Hi %(name)s": ("%(name)s", "name"), "Hi {name}": ("{name}", "name"), "Hi {0}": ("{name}", "0"),
            "Hi [FIRST_NAME]": ("[NAME]", "FIRST_NAME"), "Hi [First Name]": None, "Hi %s": ("%s / %d", ""), "You have %d items": ("%s / %d", ""),
        }
        for text, expected in cases.items():
            got = names(text)
            self.assertEqual(got, [expected] if expected else [], text)

    def test_things_that_are_not_placeholders(self):
        for text in ("body { color: red } a{color:blue}", '{"a": 1, "b": {"c": 2}}', "100%s of us", "50% off", "%20 in a URL", "[TODO] fix", "[NOTE]", "array[0]", "[x]", "a {} b", "{ }",
                     "price ${5}", "$5", "{% if x %}"):
            found = names(text)
            if text == "price ${5}":
                self.assertEqual(found, [], text)
            else:
                self.assertEqual([f for f in found if f[0] != "{name}" or f[1]], [] if text != "price ${5}" else [], text)

    def test_lines_are_reported(self):
        f = ph.scan("one\ntwo {{ a }}\nthree {{ b }}")
        self.assertEqual([(x["name"], x["line"]) for x in f], [("a", 2), ("b", 3)])

    def test_overlaps_prefer_the_longer_syntax(self):
        self.assertEqual(names("{{{ x }}}"), [("{{{ }}}", "x")])


class Blocks(unittest.TestCase):
    def test_balanced(self):
        self.assertEqual(ph.blocks("{% if a %}x{% else %}y{% endif %}{% for i in l %}{{ i }}{% endfor %}"), [])

    def test_unclosed_and_stray(self):
        self.assertEqual([(f.rule, f.line) for f in ph.blocks("a\n{% if a %}\nb")], [("block", 2)])
        self.assertEqual([(f.rule, f.line) for f in ph.blocks("{% endif %}")], [("block", 1)])
        self.assertEqual(len(ph.blocks("{% if a %}{% for i in l %}{% endif %}{% endfor %}")), 2)          # the misplaced endif, and the if that never closed

    def test_whitespace_control(self):
        self.assertEqual(ph.blocks("{%- if a -%}x{%- endif -%}"), [])


class Data(unittest.TestCase):
    def test_load_json_csv_env(self):
        self.assertEqual(ph.load_data('{"a": 1, "b": {"c": 2}}'), {"a", "b", "b.c"})
        self.assertEqual(ph.load_data("name,email,plan\nA,a@x.org,pro\n"), {"name", "email", "plan"})
        self.assertEqual(ph.load_data("# comment\nFIRST=1\nLAST=2\n"), {"FIRST", "LAST"})

    def test_missing_case_and_unused(self):
        data = {"first_name", "plan", "extra"}
        self.assertEqual(rules("Hi {{ first_name }}, {{ plan }}", data), [("info", "unused")])
        self.assertEqual(rules("Hi {{ nope }}", data), [("error", "missing"), ("info", "unused"), ("info", "unused"), ("info", "unused")])
        self.assertEqual(rules("Hi {{ First_Name }} {{ plan }} {{ extra }}", data), [("error", "case")])
        self.assertEqual(rules("Hi [[first name]]", {"first_name"}), [("error", "case")])

    def test_filters_and_dotted_names(self):
        self.assertEqual(rules('{{ name|default:"x" }} {{ user.email }}', {"name", "user.email"}), [])
        self.assertEqual(rules("{{ user.email }}", {"user"}), [])                                # a field of a known object

    def test_loop_variables_are_not_data(self):
        self.assertEqual(rules("{% for item in items %}{{ item.name }} {{ loop.index }}{% endfor %}", {"items"}), [])
        self.assertEqual(rules("{% for item in items %}{{ other }}{% endfor %}", {"items"}), [("error", "missing")])
        self.assertEqual(rules("{% set greeting = 'hi' %}{{ greeting }}", set()), [])

    def test_positional(self):
        self.assertEqual(rules("Order %s and {0}", {"a"}), [("info", "unused"), ("warn", "positional"), ("warn", "positional")])

    def test_allow(self):
        self.assertEqual(rules("{{ unsub_url }}", set(), allow={"unsub_url"}), [])
        self.assertEqual(rules("{{ unsub_url }}", set(), allow={"{{ unsub_url }}"}), [])


class Rendered(unittest.TestCase):
    def test_any_placeholder_is_a_leak(self):
        self.assertEqual(rules("Hi Ada, your plan is pro.", rendered=True), [])
        self.assertEqual(rules("Hi {{ first_name }}, [CODE]", rendered=True), [("error", "unfilled"), ("error", "unfilled")])
        self.assertEqual(rules("Hi {{ first_name }}", rendered=True, allow={"first_name"}), [])


class Cli(unittest.TestCase):
    def run_cli(self, *argv, stdin=None):
        out, err = io.StringIO(), io.StringIO()
        old = sys.stdin
        try:
            if stdin is not None:
                sys.stdin = io.StringIO(stdin)
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(list(argv))
        finally:
            sys.stdin = old
        return code, out.getvalue(), err.getvalue()

    def test_inventory_only(self):
        code, out, _ = self.run_cli(TEMPLATE)
        self.assertEqual(code, 1)                                                            # the unclosed {% for %} is an error
        self.assertIn("placeholders (", out)
        self.assertIn("*| |* (Mailchimp)", out)

    def test_with_data(self):
        code, out, _ = self.run_cli(TEMPLATE, "--data", DATA)
        self.assertEqual(code, 1)
        self.assertIn("error line 3 [case] {{ First_Name }} is not in the data, but 'first_name' is", out)
        self.assertIn("error line 4 [block] {% for %} is never closed", out)
        self.assertNotIn("[missing] {{ item.name }}", out)
        self.assertIn("info  [unused] the data field 'unused_field' is never used in the text", out)

    def test_rendered_and_stdin(self):
        self.assertEqual(self.run_cli("-", "--rendered", stdin="Hi Ada")[:2], (0, "no placeholders found\n"))
        code, out, _ = self.run_cli("-", "--rendered", stdin="Hi {{ first_name }}")
        self.assertEqual(code, 1)
        self.assertIn("error line 1 [unfilled] {{ first_name }} is still in the text ({{ }} syntax)", out)

    def test_json_output_and_errors(self):
        data = json.loads(self.run_cli(TEMPLATE, "--json")[1])
        self.assertTrue(any(p["text"] == "{{plan}}" for p in data["placeholders"]))
        self.assertEqual(self.run_cli("/no/such.html")[0], 2)
        with tempfile.TemporaryDirectory() as d:
            bad = os.path.join(d, "bad.json")
            with open(bad, "w") as fh:
                fh.write("{oops")
            code, _, err = self.run_cli(TEMPLATE, "--data", bad)
            self.assertEqual(code, 2)
            self.assertIn("cannot read the data file", err)


if __name__ == "__main__":
    unittest.main()
