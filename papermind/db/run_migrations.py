import asyncio
import os
from pathlib import Path

from loguru import logger

# Import the existing db_connection from Open Notebook
from open_notebook.database.repository import db_connection

async def run_migrations():
    """
    Reads .surql files from the migrations directory and executes them
    against the configured SurrealDB connection.
    """
    migrations_dir = Path(__file__).parent / "migrations"
    if not migrations_dir.exists():
        logger.info("No migrations directory found, skipping.")
        return

    # Collect and sort migration files
    migration_files = sorted([f for f in migrations_dir.iterdir() if f.suffix == ".surql"])
    if not migration_files:
        logger.info("No .surql migration files found.")
        return

    async with db_connection() as db:
        for file_path in migration_files:
            logger.info(f"Running migration: {file_path.name}")
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
                
            try:
                # Execute the raw query
                await db.query(content)
                logger.info(f"Successfully applied {file_path.name}")
            except Exception as e:
                logger.error(f"Failed to apply {file_path.name}: {e}")
                raise

if __name__ == "__main__":
    asyncio.run(run_migrations())
