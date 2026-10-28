"""Real SQL privilege probes on an explicitly supplied isolated test schema; all rollback."""

import json
import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from app.runtime_grants import TABLE_PRIVILEGES


def main():
    url = make_url(os.environ["TEST_DATABASE_URL"])
    if not (url.database or "").startswith("esc_m1_test_m2"):
        raise RuntimeError("Explicit isolated M2 test database required")
    engine = create_engine(url, hide_parameters=True)
    checks = []

    def probe(table, operation, sql, allowed):
        with engine.connect() as connection:
            transaction = connection.begin()
            code, succeeded = None, False
            try:
                connection.execute(text(sql))
                succeeded = True
            except OperationalError as exc:
                code = getattr(exc.orig, "args", [None])[0]
            finally:
                transaction.rollback()
        checks.append(
            {
                "table": table,
                "operation": operation,
                "expected": "ALLOW" if allowed else "DENY",
                "status": "PASS"
                if (succeeded if allowed else not succeeded and code in {1142, 1143})
                else "FAIL",
                "mysql_error": code,
            }
        )

    try:
        with engine.connect() as connection:
            version = connection.scalar(text("SELECT VERSION()"))
        for table, privileges in TABLE_PRIVILEGES.items():
            quoted = f"`{table}`"
            columns = [
                column["name"]
                for column in inspect(engine).get_columns(table)
                if not column.get("computed")
            ]
            fields = ", ".join(f"`{column}`" for column in columns)
            probe(table, "SELECT", f"SELECT {fields} FROM {quoted} LIMIT 1", True)
            probe(
                table,
                "INSERT",
                f"INSERT INTO {quoted} ({fields}) SELECT {fields} FROM {quoted} WHERE 1=0",
                "INSERT" in privileges,
            )
            update = next((value for value in privileges if value.startswith("UPDATE")), None)
            column = (
                update.split("(")[1].split(",")[0].strip(" )")
                if update and "(" in update
                else columns[0]
            )
            probe(
                table,
                "UPDATE",
                f"UPDATE {quoted} SET `{column}`=`{column}` WHERE 1=0",
                update is not None,
            )
            probe(table, "DELETE", f"DELETE FROM {quoted} WHERE 1=0", False)
        for table, field in [
            ("users", "id"),
            ("stored_objects", "sha256"),
            ("close_evidence", "amount"),
        ]:
            probe(
                table,
                "UPDATE_IMMUTABLE_" + field,
                f"UPDATE `{table}` SET `{field}`=`{field}` WHERE 1=0",
                False,
            )
        print(
            json.dumps(
                {
                    "mysql_version": version,
                    "checks": checks,
                    "all_passed": all(item["status"] == "PASS" for item in checks),
                }
            )
        )
        return 0 if all(item["status"] == "PASS" for item in checks) else 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
