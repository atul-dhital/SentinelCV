import os
import sys
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Add backend to path so we can import db and models
sys.path.append(os.path.join(os.getcwd(), 'backend'))

from db.base import Base, engine, SQLALCHEMY_DATABASE_URL
from models import models # Import models to register them with Base

def reset_database():
    print(f"Connecting to {SQLALCHEMY_DATABASE_URL}...")
    
    # Check if SQLite and delete file if it exists (simplest way to clean SQLite)
    if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
        db_path = SQLALCHEMY_DATABASE_URL.replace("sqlite:///", "")
        if os.path.exists(db_path):
            print(f"Deleting SQLite database file: {db_path}")
            try:
                # Close connections if possible (though this script is a fresh process)
                os.remove(db_path)
                print("Database file deleted.")
            except Exception as e:
                print(f"Error deleting file: {e}")
                print("Falling back to table dropping...")
    
    print("Dropping all tables...")
    Base.metadata.drop_all(bind=engine)
    
    print("Creating all tables...")
    Base.metadata.create_all(bind=engine)
    
    print("Database cleaned and reset successfully.")

if __name__ == "__main__":
    reset_database()
