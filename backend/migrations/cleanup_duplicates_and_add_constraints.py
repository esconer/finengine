"""
Database cleanup migration script to remove duplicate records and add constraints
"""

import sqlite3
import logging
from datetime import datetime
import os

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DatabaseCleanupManager:
    """Manager for database cleanup and schema updates"""
    
    def __init__(self, db_path: str = "data/daisy.db"):
        self.db_path = db_path
        self.backup_dir = "data/backups"
        os.makedirs(self.backup_dir, exist_ok=True)
    
    def create_backup(self) -> str:
        """Create a backup of the current database"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"daisy_backup_{timestamp}.db"
        backup_path = os.path.join(self.backup_dir, backup_filename)
        
        # Use SQLite backup API
        with sqlite3.connect(self.db_path) as source:
            with sqlite3.connect(backup_path) as backup:
                source.backup(backup)
        
        logger.info(f"Database backup created: {backup_path}")
        return backup_path
    
    def analyze_duplicates(self) -> dict:
        """Analyze current duplicate situation"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Count total records before cleanup
            cursor.execute("SELECT COUNT(*) FROM stock_timeseries")
            total_records = cursor.fetchone()[0]
            
            # Find duplicates
            cursor.execute("""
                SELECT ticker, date, COUNT(*) as duplicate_count 
                FROM stock_timeseries 
                GROUP BY ticker, date 
                HAVING COUNT(*) > 1 
                ORDER BY duplicate_count DESC 
            """)
            duplicates = cursor.fetchall()
            
            # Count total duplicate records (extra copies)
            cursor.execute("""
                SELECT SUM(cnt - 1) as total_duplicate_records
                FROM (
                    SELECT ticker, date, COUNT(*) as cnt
                    FROM stock_timeseries 
                    GROUP BY ticker, date
                    HAVING cnt > 1
                ) as duplicates
            """)
            total_duplicates = cursor.fetchone()[0] or 0
            
            # Find unique combinations
            cursor.execute("""
                SELECT COUNT(DISTINCT ticker || '-' || date) as unique_combinations
                FROM stock_timeseries
            """)
            unique_combinations = cursor.fetchone()[0]
            
            return {
                "total_records": total_records,
                "duplicate_combinations": len(duplicates),
                "total_duplicate_records": total_duplicates,
                "unique_combinations": unique_combinations,
                "duplicate_details": duplicates[:10]  # Top 10 for display
            }
    
    def cleanup_duplicates(self) -> dict:
        """Clean up duplicate records, keeping the latest one"""
        logger.info("Starting duplicate cleanup...")
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Find records to keep (latest id per ticker/date combination)
            cursor.execute("""
                DELETE FROM stock_timeseries 
                WHERE id NOT IN (
                    SELECT MAX(id)
                    FROM stock_timeseries 
                    GROUP BY ticker, date
                )
            """)
            
            deleted_count = cursor.rowcount
            
            # Get updated stats
            cursor.execute("SELECT COUNT(*) FROM stock_timeseries")
            remaining_count = cursor.fetchone()[0]
            
            conn.commit()
            
            logger.info(f"Cleaned up {deleted_count} duplicate records")
            logger.info(f"Remaining records: {remaining_count}")
            
            return {
                "deleted_records": deleted_count,
                "remaining_records": remaining_count
            }
    
    def add_unique_constraints(self) -> bool:
        """Add UNIQUE constraints to prevent future duplicates"""
        logger.info("Adding UNIQUE constraints...")
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Add UNIQUE constraint on (ticker, date) for stock_timeseries
                cursor.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_stock_timeseries_unique_ticker_date 
                    ON stock_timeseries(ticker, date)
                """)
                
                # Add UNIQUE constraint on (ticker, metric_name, calculation_date) for analytics_cache
                cursor.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_analytics_cache_unique 
                    ON analytics_cache(ticker, metric_name, calculation_date)
                """)
                
                # Add constraint to prevent future duplicates at table level if possible
                # Note: SQLite supports adding constraints in newer versions
                try:
                    cursor.execute("""
                        ALTER TABLE stock_timeseries 
                        ADD CONSTRAINT uk_stock_timeseries_ticker_date 
                        UNIQUE (ticker, date)
                    """)
                except sqlite3.OperationalError:
                    # Constraint might already exist or not be supported
                    logger.info("Table-level UNIQUE constraint not added (may already exist or not supported)")
                
                conn.commit()
                logger.info("UNIQUE constraints added successfully")
                return True
                
        except Exception as e:
            logger.error(f"Error adding constraints: {e}")
            return False
    
    def validate_cleanup(self) -> dict:
        """Validate that cleanup was successful"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Check for remaining duplicates
            cursor.execute("""
                SELECT COUNT(*) as remaining_duplicates
                FROM (
                    SELECT ticker, date, COUNT(*) as cnt
                    FROM stock_timeseries 
                    GROUP BY ticker, date
                    HAVING cnt > 1
                ) as duplicates
            """)
            remaining_duplicates = cursor.fetchone()[0]
            
            # Verify constraint works
            try:
                cursor.execute("""
                    INSERT OR IGNORE INTO stock_timeseries 
                    (ticker, date, open, high, low, close, adj_close, volume, source_used, fetch_status)
                    VALUES ('TEST', '2025-01-01', 100, 101, 99, 100.5, 100.5, 1000, 'test', 'test')
                """)
                cursor.execute("""
                    INSERT OR IGNORE INTO stock_timeseries 
                    (ticker, date, open, high, low, close, adj_close, volume, source_used, fetch_status)
                    VALUES ('TEST', '2025-01-01', 100, 101, 99, 100.5, 100.5, 1000, 'test', 'test')
                """)
                
                cursor.execute("SELECT COUNT(*) FROM stock_timeseries WHERE ticker = 'TEST'")
                test_count = cursor.fetchone()[0]
                
                # Clean up test data
                cursor.execute("DELETE FROM stock_timeseries WHERE ticker = 'TEST'")
                
                constraint_works = (test_count == 1)
            except Exception as e:
                logger.error(f"Constraint validation failed: {e}")
                constraint_works = False
            
            return {
                "remaining_duplicates": remaining_duplicates,
                "constraint_works": constraint_works,
                "cleanup_successful": (remaining_duplicates == 0 and constraint_works)
            }
    
    def run_full_cleanup(self) -> dict:
        """Run the complete cleanup process"""
        logger.info("=" * 60)
        logger.info("DATABASE CLEANUP AND CONSTRAINT UPDATE")
        logger.info("=" * 60)
        
        # Step 1: Analyze current state
        logger.info("Step 1: Analyzing current duplicate situation...")
        before_stats = self.analyze_duplicates()
        logger.info(f"Before cleanup: {before_stats['total_records']} total records")
        logger.info(f"Duplicate combinations: {before_stats['duplicate_combinations']}")
        logger.info(f"Duplicate records to remove: {before_stats['total_duplicate_records']}")
        
        # Step 2: Create backup
        logger.info("Step 2: Creating database backup...")
        backup_path = self.create_backup()
        
        # Step 3: Clean up duplicates
        logger.info("Step 3: Cleaning up duplicate records...")
        cleanup_result = self.cleanup_duplicates()
        
        # Step 4: Add constraints
        logger.info("Step 4: Adding UNIQUE constraints...")
        constraints_added = self.add_unique_constraints()
        
        # Step 5: Validate results
        logger.info("Step 5: Validating cleanup...")
        validation = self.validate_cleanup()
        
        # Step 6: Final analysis
        logger.info("Step 6: Final analysis...")
        after_stats = self.analyze_duplicates()
        
        result = {
            "backup_created": backup_path,
            "before_cleanup": before_stats,
            "cleanup_result": cleanup_result,
            "constraints_added": constraints_added,
            "validation": validation,
            "after_cleanup": after_stats,
            "success": validation["cleanup_successful"],
            "timestamp": datetime.now().isoformat()
        }
        
        logger.info("=" * 60)
        if result["success"]:
            logger.info("✅ CLEANUP SUCCESSFUL")
            logger.info(f"✅ Removed {cleanup_result['deleted_records']} duplicate records")
            logger.info("✅ Added UNIQUE constraints")
            logger.info("✅ Database integrity restored")
        else:
            logger.error("❌ CLEANUP FAILED")
            logger.error(f"❌ Remaining duplicates: {validation['remaining_duplicates']}")
            logger.error(f"❌ Constraint validation: {'passed' if validation['constraint_works'] else 'failed'}")
        logger.info("=" * 60)
        
        return result


def main():
    """Main function to run the cleanup"""
    cleanup_manager = DatabaseCleanupManager()
    result = cleanup_manager.run_full_cleanup()
    
    if result["success"]:
        print("\n🎉 Database cleanup completed successfully!")
        print(f"📊 Records removed: {result['cleanup_result']['deleted_records']}")
        print(f"💾 Backup created: {result['backup_created']}")
        print("🔒 UNIQUE constraints added")
        print("✅ Database is now ready for production use")
    else:
        print("\n❌ Database cleanup failed!")
        print(f"❌ Issues found: {result['validation']}")
        print("💡 Please review the logs and address any issues")
    
    return result


if __name__ == "__main__":
    main()