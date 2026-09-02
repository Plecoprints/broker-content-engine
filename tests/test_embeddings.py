"""Embedding client for Gate 1's corpus-wide uniqueness check (spec §10.3).

Mirrors `bce.llm.ProfileClient` / `bce.angles.AngleClient` exactly: a lazily
constructed client (so importing the module and running the whole suite
needs no `VOYAGE_API_KEY`), an injectable fake, and every failure -- a
Voyage API error, an empty/blank input -- degrading to `None` rather than
raising. No test here may touch the network.
"""
import voyageai

from bce.embeddings import MODEL, EmbeddingClient


class FakeEmbed:
    def __init__(self, vector=None, raises=None):
        self.vector = vector if vector is not None else [0.1, 0.2, 0.3]
        self.raises = raises
        self.calls = []

    def embed(self, texts, **kwargs):
        self.calls.append({"texts": texts, **kwargs})
        if self.raises is not None:
            raise self.raises
        return type("R", (), {"embeddings": [self.vector for _ in texts]})()


class FakeClient:
    def __init__(self, vector=None, raises=None):
        self.embed_fn = FakeEmbed(vector=vector, raises=raises)

    def embed(self, texts, **kwargs):
        return self.embed_fn.embed(texts, **kwargs)


def test_model_is_voyage_4():
    assert MODEL == "voyage-4"


def test_embed_returns_the_vector():
    fake = FakeClient(vector=[1.0, 2.0, 3.0])
    got = EmbeddingClient(client=fake).embed("some draft body")
    assert got == [1.0, 2.0, 3.0]


def test_embed_sends_the_configured_model():
    fake = FakeClient()
    EmbeddingClient(client=fake).embed("text")
    sent = fake.embed_fn.calls[0]
    assert sent["model"] == MODEL
    assert sent["texts"] == ["text"]


def test_embed_with_empty_text_makes_no_api_call():
    fake = FakeClient()
    assert EmbeddingClient(client=fake).embed("") is None
    assert EmbeddingClient(client=fake).embed(None) is None
    assert fake.embed_fn.calls == []


def test_embed_returns_none_on_api_error():
    err = voyageai.error.APIConnectionError()
    fake = FakeClient(raises=err)
    assert EmbeddingClient(client=fake).embed("text") is None


def test_embed_returns_none_when_no_embeddings_come_back():
    fake = FakeClient()
    fake.embed_fn.embed = lambda texts, **kw: type("R", (), {"embeddings": []})()
    assert EmbeddingClient(client=fake).embed("text") is None


def test_client_is_lazily_constructed():
    """No `voyageai.Client()` is built (and therefore no key is required)
    until `.embed()` is actually called with non-empty text.
    """
    client = EmbeddingClient()
    assert client._client is None
    # Calling with empty text must not construct a client either.
    client.embed("")
    assert client._client is None
