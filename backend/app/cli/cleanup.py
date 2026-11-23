import argparse
import asyncio

from app.db.session import SessionFactory
from app.services.cleanup import run_cleanup


async def _run() -> int:
    async with SessionFactory() as session:
        counts = await run_cleanup(session)
        await session.commit()
    print("cleanup done:", counts)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli.cleanup")
    parser.parse_args(argv)
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())