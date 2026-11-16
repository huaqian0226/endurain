"""Fixed-origin, read-only household catalogue transport."""

import json
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from pydantic import ValidationError

from core.exceptions import CatalogueUnavailableError


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HouseholdCatalogue:
    """Read only the configured household user's explicitly allowed assets."""

    def __init__(self, url: str | None, token: str | None, owner_id: int | None):
        self.url = url
        self.token = token
        self.owner_id = owner_id

    def read(self, user_id: int) -> dict:
        """Return the bounded authority envelope without logging credentials."""
        if not self.url or not self.token or user_id != self.owner_id:
            raise CatalogueUnavailableError()
        parsed = urlsplit(self.url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "host.docker.internal"}
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise CatalogueUnavailableError()
        request = Request(self.url.rstrip("/") + "/v1/assets", headers={"Authorization": "Bearer " + self.token})  # noqa: S310 - fixed HTTP host allow-list above
        try:
            with build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=5) as response:
                data = response.read(1_000_001)
            if len(data) > 1_000_000:
                raise ValueError("Catalogue exceeds response limit")
            envelope = json.loads(data)
            if (
                not isinstance(envelope, dict)
                or envelope.get("schema_version") != 1
                or not isinstance(envelope.get("items"), list)
                or len(envelope["items"]) > 50
            ):
                raise ValueError("Invalid catalogue envelope")
            return envelope
        except (OSError, ValueError, ValidationError) as exc:
            raise CatalogueUnavailableError() from exc
