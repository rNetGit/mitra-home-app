import sqlite3
import pathlib

here = pathlib.Path(__file__).parent
import paths  # noqa: E402
con = sqlite3.connect(paths.DB)
con.executescript((here / "schema.sql").read_text())
con.commit()
print([r[0] for r in con.execute("select name from sqlite_master where type='table'")])
