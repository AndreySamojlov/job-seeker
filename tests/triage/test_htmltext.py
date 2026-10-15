from job_machine.triage.htmltext import strip_html


def test_strip_html_unescapes_and_removes_tags():
    raw = "&lt;p&gt;Senior &lt;b&gt;QA&lt;/b&gt; Lead&lt;/p&gt;&lt;ul&gt;&lt;li&gt;10+ yrs&lt;/li&gt;&lt;/ul&gt;"
    assert strip_html(raw) == "Senior QA Lead 10+ yrs"


def test_strip_html_collapses_whitespace():
    assert strip_html("a\n\n   b\t c") == "a b c"


def test_strip_html_handles_empty():
    assert strip_html("") == ""
    assert strip_html(None) == ""
