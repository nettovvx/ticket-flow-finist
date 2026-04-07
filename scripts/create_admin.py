from app.db.session import SessionLocal
from app.services.bootstrap import ensure_bootstrap_admin


def main() -> None:
    with SessionLocal() as db:
        ensure_bootstrap_admin(db)
    print("Bootstrap admin ensured.")


if __name__ == "__main__":
    main()
