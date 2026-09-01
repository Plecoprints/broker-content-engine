"""Test recovery of paragraph structure that trafilatura flattens."""
from bce.articles import extract_paragraphs


ARTICLE = """<html><body><article>
<p>Beam matters more than length when the marina is full in August.</p>
<p>Draft is the constraint nobody mentions until it is far too late.</p>
<p>Guests notice steadiness at anchor long before they notice speed.</p>
</article></body></html>"""


def test_recovers_paragraphs_trafilatura_flattens():
    """The premise: trafilatura extracts multi-paragraph articles as single text.

    This test documents the trafilatura behavior we're fixing. If trafilatura
    ever changes, this test will catch it — we'll know the fix no longer applies.
    """
    import trafilatura
    flat = trafilatura.extract(ARTICLE)
    # Premise: trafilatura flattens the three <p> tags into one unbroken line
    assert len([p for p in flat.split("\n") if p.strip()]) == 1, "premise: trafilatura flattens"
    # Our fix: selectolax recovers all three
    assert len(extract_paragraphs(ARTICLE)) == 3, "selectolax must recover them"


def test_drops_empty_paragraphs():
    assert extract_paragraphs("<article><p>Real text here.</p><p></p><p>  </p></article>") == [
        "Real text here."
    ]


def test_excludes_nav_and_footer_paragraphs():
    html = ("<body><nav><p>Home</p></nav><article><p>The actual article body text.</p>"
            "</article><footer><p>Copyright</p></footer></body>")
    paras = extract_paragraphs(html)
    assert paras == ["The actual article body text."]


def test_handles_a_page_with_no_paragraphs():
    assert extract_paragraphs("<html><body><div>no p tags</div></body></html>") == []
