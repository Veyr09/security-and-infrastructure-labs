"""The timesheet service as it is usually first written.

Two isolation decisions are wrong here, and neither is visible from the login
screen. Both tenants authenticate correctly; both see only their own rows on
/entries. The service looks isolated until someone changes a number in a URL.
"""
from __future__ import annotations

from common import BaseHandler, read_token, run


class Handler(BaseHandler):

    def accept_session(self, token: str) -> dict | None:
        # Checks that the token is signed, and nothing else. If the two tenants
        # are deployed with the same SESSION_SECRET - the default when one
        # .env is copied between them - then a token minted by tenant A is a
        # valid token here, because it was signed by the same key.
        return read_token(token)

    def fetch_entry(self, entry_id: int, session: dict) -> tuple | None:
        # Looks the row up by primary key alone. The id space is global, so this
        # returns whatever row has that id, whoever it belongs to.
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT id, tenant_id, worker, hours, note FROM entries"
                " WHERE id = %s", (entry_id,))
            return cur.fetchone()


if __name__ == "__main__":
    run(Handler)
