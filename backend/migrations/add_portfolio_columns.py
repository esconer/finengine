"""
Database migration to add quantity and buy_price columns to portfolio_positions table
"""

import sqlite3
from pathlib import Path

def migrate_database():
    """Add new columns to portfolio_positions table"""
    
    # Database path
    db_path = Path(__file__).parent.parent / "data" / "daisy.db"
    
    if not db_path.exists():
        print(f"Database not found at {db_path}")
        return False
    
    print(f"Connecting to database: {db_path}")
    
    try:
        # Connect to database
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # Check if columns already exist
        cursor.execute("PRAGMA table_info(portfolio_positions)")
        columns = [column[1] for column in cursor.fetchall()]
        
        print(f"Current columns: {columns}")
        
        # Add quantity column if it doesn't exist
        if 'quantity' not in columns:
            print("Adding 'quantity' column...")
            cursor.execute("ALTER TABLE portfolio_positions ADD COLUMN quantity REAL DEFAULT 0.0")
            print("✓ Added 'quantity' column")
        else:
            print("✓ 'quantity' column already exists")
        
        # Add buy_price column if it doesn't exist
        if 'buy_price' not in columns:
            print("Adding 'buy_price' column...")
            cursor.execute("ALTER TABLE portfolio_positions ADD COLUMN buy_price REAL DEFAULT 0.0")
            print("✓ Added 'buy_price' column")
        else:
            print("✓ 'buy_price' column already exists")
        
        # Update existing records with reasonable defaults
        print("Updating existing records...")
        cursor.execute("""
            UPDATE portfolio_positions 
            SET quantity = 100.0, buy_price = market_value / 100.0 
            WHERE quantity IS NULL OR quantity = 0.0
        """)
        
        updated_count = cursor.rowcount
        print(f"✓ Updated {updated_count} records with default values")
        
        # Commit changes
        conn.commit()
        print("✓ Migration completed successfully!")
        
        # Verify the changes
        cursor.execute("PRAGMA table_info(portfolio_positions)")
        final_columns = [column[1] for column in cursor.fetchall()]
        print(f"Final columns: {final_columns}")
        
        return True
        
    except Exception as e:
        print(f"✗ Migration failed: {e}")
        return False
        
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    print("Starting database migration...")
    success = migrate_database()
    if success:
        print("Migration completed successfully!")
    else:
        print("Migration failed!")
        exit(1)