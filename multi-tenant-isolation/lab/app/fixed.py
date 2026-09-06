"""The same service with both isolation decisions made deliberately.

The difference from vulnerable.py is two predicates. Everything else - the
routes, the queries' shape, the login - is identical, which is the point: the
defect is not a missing feature, it is a missing clause.
"""
from __future__ import annotations

from common import TENANT_ID, BaseHandler, read_token, run


class Handler(BaseHandler):

    def accept_session(self, token: str) -> dict | None:
        session = read_token(token)
        # A valid signature says the token was issued by someone holding the
        # key. It does not say it was issued for *this* tenant. With per-tenant
        # secrets the signature check already fails; this second test is what
        # holds the line on the day someone reuses a key by accident.
        if session is None or session.get("tenant") != TENANT_ID:
            return None
        return session

    def fetch_entry(self, entry_id: int, session: dict) -> tuple | None:
        # The tenant predicate belongs in the query, not in a check after it.
        # A row that is not this tenant's is not found, rather than found and
        # then withheld, so there is no ordering to get wrong later.
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT id, tenant_id, worker, hours, note FROM entries"
                " WHERE id = %s AND tenant_id = %s", (entry_id, TENANT_ID))
            return cur.fetchone()


if __name__ == "__main__":
    run(Handler)
