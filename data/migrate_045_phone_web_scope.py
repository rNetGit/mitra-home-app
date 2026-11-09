"""Apply migration 045 to data/family.db (idempotent): phones paired before 0.104 get the `web` scope.

0.104 added the scope "Open the full app on the home Wi-Fi" (on by default for every role), but only phones paired
from then on had it; the phone app (0.105) needs it to open the web app. Every live phone without it gets it once.
An adult can still turn it off per phone in Settings > Phones.
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
n = c.execute("UPDATE devices SET scopes = CASE WHEN COALESCE(scopes, '') = '' THEN 'web' ELSE scopes || ',web' END "
              "WHERE revoked_at IS NULL AND (',' || COALESCE(scopes, '') || ',') NOT LIKE '%,web,%'").rowcount
c.commit()
print(f"migration 045 ok; {n} phone(s) can now open the full app")
