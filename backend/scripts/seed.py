"""Reset the demo tenants to the fixture state. Usage: python scripts/seed.py"""

from app.core.clock import now_utc
from app.db.seed import FIXTURE_VERSION, seed
from app.db.session import transaction


def main() -> None:
    with transaction() as session:
        seed(session, now_utc())
    print(f"seeded demo fixtures {FIXTURE_VERSION}")


if __name__ == "__main__":
    main()
