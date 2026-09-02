"""Embedding client for Gate 1's corpus-wide uniqueness check (spec §10.3).

Mirrors `bce.llm.ProfileClient` / `bce.angles.AngleClient` / `bce.draft.
DraftClient` exactly: the client is injectable and lazily constructed, so
importing this module and running the whole suite needs no `VOYAGE_API_KEY`
and touches no network, and any failure -- a Voyage API error, or simply
having nothing to embed -- degrades to `None`, never raises. A caller that
cannot verify uniqueness must not treat that as a pass (see
`bce.originality.check_uniqueness`); this module's job is only to report the
vector, or that it could not get one.

**Model: `voyage-4`.** 32k-token context -- a 2,300-word pillar draft is
roughly 3k tokens, comfortably inside a single call with no chunking.
"""
import voyageai

MODEL = "voyage-4"


class EmbeddingClient:
    def __init__(self, client=None):
        self._client = client

    @property
    def client(self):
        if self._client is None:
            self._client = voyageai.Client()
        return self._client

    def embed(self, text: str) -> list[float] | None:
        """The embedding vector for `text`, or `None` on any failure.

        No call is made for empty/blank text -- there is nothing to embed,
        mirroring `ProfileClient.classify`'s "no articles, no API call"
        contract. `voyageai.error.VoyageError` is the base class for every
        error the SDK raises (auth, connection, rate limit, server errors);
        catching it here, not a narrower subclass, keeps this degrade-to-
        None regardless of which one occurs -- an unverifiable draft must
        not silently look identical to a verified-unique one.
        """
        if not text:
            return None
        try:
            result = self.client.embed([text], model=MODEL)
        except voyageai.error.VoyageError:
            return None
        embeddings = getattr(result, "embeddings", None)
        if not embeddings:
            return None
        return embeddings[0]
