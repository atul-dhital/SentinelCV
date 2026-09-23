#!/usr/bin/env python3
"""
SentinelCV PostgreSQL Development Setup Helper.

This script helps set up PostgreSQL + pgvector for development,
replacing the default SQLite configuration.

Usage:
    python setup_postgres_dev.py [--migrate] [--seed]
    
    Options:
    --migrate  : Migrate data from existing SQLite database (if any)
    --seed     : Seed the database with test data after setup
    --docker   : Use Docker Compose to start PostgreSQL
"""

import os
import sys
import subprocess
import time
import argparse
from pathlib import Path
from typing import Optional

# Script lives in scripts/, so project root is one level up.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_ROOT = PROJECT_ROOT / "backend"
if BACKEND_ROOT not in [Path(p) for p in sys.path]:
    sys.path.insert(0, str(BACKEND_ROOT))


def print_section(title: str):
    """Print section header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_info(msg: str):
    """Print info message."""
    print(f"[*] {msg}")


def print_success(msg: str):
    """Print success message."""
    print(f"[✓] {msg}")


def print_error(msg: str):
    """Print error message."""
    print(f"[✗] {msg}")


def run_command(cmd: list, description: str = "") -> bool:
    """Run shell command and return success status."""
    if description:
        print_info(description)
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        if result.stdout:
            print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print_error(f"Command failed: {' '.join(cmd)}")
        if e.stderr:
            print(f"Error: {e.stderr}")
        return False
    except FileNotFoundError:
        print_error(f"Command not found: {cmd[0]}")
        return False


def check_docker() -> bool:
    """Check if Docker is installed and running."""
    try:
        subprocess.run(
            ["docker", "ps"],
            check=True,
            capture_output=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def check_postgres_connection(
    host: str = "localhost",
    port: int = 5432,
    user: str = "postgres",
    password: str = "postgres",
    db: str = "visitor_db",
) -> bool:
    """Check if PostgreSQL is accessible."""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=db,
        )
        conn.close()
        return True
    except (ImportError, Exception):
        return False


def start_postgres_docker() -> bool:
    """Start PostgreSQL using docker-compose."""
    print_info("Starting PostgreSQL with docker-compose...")
    
    # Check if docker is available
    if not check_docker():
        print_error("Docker is not running. Please start Docker and try again.")
        return False
    
    # Project root (one level up from scripts/)
    project_root = PROJECT_ROOT

    cmd = ["docker-compose", "up", "-d", "db"]
    if not run_command(cmd, "Bringing up PostgreSQL container..."):
        return False
    
    # Wait for PostgreSQL to be ready
    print_info("Waiting for PostgreSQL to be ready...")
    max_attempts = 30
    for attempt in range(max_attempts):
        if check_postgres_connection():
            print_success("PostgreSQL is ready!")
            return True
        time.sleep(1)
        if (attempt + 1) % 5 == 0:
            print_info(f"  Still waiting... ({attempt + 1}s)")
    
    print_error("PostgreSQL did not become ready in time")
    return False


def enable_pgvector_extension() -> bool:
    """Enable pgvector extension in PostgreSQL."""
    print_info("Enabling pgvector extension...")
    
    try:
        import psycopg2
        conn = psycopg2.connect(
            host="localhost",
            port=5432,
            user="postgres",
            password="postgres",
            database="visitor_db",
        )
        cur = conn.cursor()
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        conn.commit()
        cur.close()
        conn.close()
        print_success("pgvector extension enabled")
        return True
    except Exception as e:
        print_error(f"Failed to enable pgvector: {e}")
        return False


def create_database_schema() -> bool:
    """Create database schema using SQLAlchemy models."""
    print_info("Creating database schema...")
    
    try:
        os.environ["DATABASE_URL"] = (
            "postgresql://postgres:postgres@localhost:5432/visitor_db"
        )
        
        # Import after setting DATABASE_URL so models bind to the correct engine.
        from db.base import engine, Base
        from models import models as _models  # noqa: F401
        
        Base.metadata.create_all(bind=engine)
        print_success("Database schema created")
        return True
    except Exception as e:
        print_error(f"Failed to create schema: {e}")
        import traceback
        traceback.print_exc()
        return False


def migrate_from_sqlite(sqlite_db: Optional[str] = None) -> bool:
    """Migrate data from SQLite to PostgreSQL."""
    if sqlite_db is None:
        sqlite_db = "sentinelcv.db"
    
    sqlite_path = Path(sqlite_db)
    if not sqlite_path.exists():
        print_info(f"No SQLite database found at {sqlite_db}, skipping migration")
        return True
    
    print_info(f"Migrating data from {sqlite_db}...")
    
    try:
        os.environ["DATABASE_URL"] = (
            "postgresql://postgres:postgres@localhost:5432/visitor_db"
        )
        
        # Import migration script
        sys.path.insert(0, str(BACKEND_ROOT))
        from migrate_to_postgres import run_migration
        
        success = run_migration(str(sqlite_path))
        if success:
            print_success("Migration completed")
            return True
        else:
            print_error("Migration failed")
            return False
    except Exception as e:
        print_error(f"Migration error: {e}")
        import traceback
        traceback.print_exc()
        return False


def seed_database() -> bool:
    """Seed database with test data."""
    print_info("Seeding database with test data...")
    
    try:
        # Try to find and run seed script
        seed_script = BACKEND_ROOT / "seed_production_data.py"
        if seed_script.exists():
            os.environ["DATABASE_URL"] = (
                "postgresql://postgres:postgres@localhost:5432/visitor_db"
            )
            result = subprocess.run(
                [sys.executable, str(seed_script)],
                cwd=str(BACKEND_ROOT.parent),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                print_success("Database seeded with test data")
                return True
            else:
                print_error(f"Seeding failed: {result.stderr}")
                return False
        else:
            print_info(f"Seed script not found at {seed_script}")
            return True
    except Exception as e:
        print_error(f"Seeding error: {e}")
        return False


def setup_env_file() -> bool:
    """Create/update .env file for PostgreSQL development."""
    print_info("Setting up .env file for PostgreSQL...")
    
    env_file = PROJECT_ROOT / ".env"
    env_dev_file = PROJECT_ROOT / ".env.dev"
    
    # Use .env.dev as template if it exists
    if env_dev_file.exists():
        print_info(f"Using {env_dev_file} as template")
        with open(env_dev_file, 'r') as f:
            env_content = f.read()
    else:
        # Create basic .env content
        env_content = """DATABASE_URL=postgresql://postgres:postgres@localhost:5432/visitor_db
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=sentinelcv-dev-secret-key-change-in-production
AI_SERVICE_URL=http://localhost:8001
FRONTEND_URL=http://localhost:3001
DEBUG=true
"""
    
    # Write to .env if it doesn't exist
    if not env_file.exists():
        with open(env_file, 'w') as f:
            f.write(env_content)
        print_success(f"Created {env_file}")
    else:
        print_info(f"{env_file} already exists, skipping")
    
    return True


def main():
    """Main setup flow."""
    parser = argparse.ArgumentParser(
        description="Setup PostgreSQL + pgvector for SentinelCV development"
    )
    parser.add_argument(
        "--migrate",
        action="store_true",
        help="Migrate data from SQLite database if it exists",
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Seed the database with test data",
    )
    parser.add_argument(
        "--docker",
        action="store_true",
        help="Use Docker Compose to start PostgreSQL",
    )
    args = parser.parse_args()
    
    print_section("SentinelCV PostgreSQL Development Setup")
    
    # Step 1: Start PostgreSQL (if using Docker)
    if args.docker:
        if not start_postgres_docker():
            print_error("Failed to start PostgreSQL")
            return False
    else:
        print_info("Assuming PostgreSQL is already running...")
        if not check_postgres_connection():
            print_error("Could not connect to PostgreSQL at localhost:5432")
            print_info("Please ensure PostgreSQL is running, or use --docker flag")
            return False
        print_success("Connected to PostgreSQL")
    
    # Step 2: Setup .env file
    if not setup_env_file():
        print_error("Failed to setup .env file")
        return False
    
    # Step 3: Enable pgvector
    if not enable_pgvector_extension():
        print_error("Failed to enable pgvector extension")
        return False
    
    # Step 4: Create database schema
    if not create_database_schema():
        print_error("Failed to create database schema")
        return False
    
    # Step 5: Migrate from SQLite (optional)
    if args.migrate:
        if not migrate_from_sqlite():
            print_error("Migration failed (but schema is ready)")
    
    # Step 6: Seed database (optional)
    if args.seed:
        if not seed_database():
            print_error("Seeding failed (but schema is ready)")
    
    print_section("Setup Complete!")
    print_success("PostgreSQL + pgvector is ready for development")
    print_info("Next steps:")
    print_info("  1. Start the backend: cd backend && python -m uvicorn main:app --reload")
    print_info("  2. Check the dashboard at http://localhost:8000/docs")
    print_info("  3. Access pgAdmin at http://localhost:5050 (if using docker-compose)")
    
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
