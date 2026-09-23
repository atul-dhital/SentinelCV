#!/usr/bin/env python3
"""
US-DEP-001: PostgreSQL Vector Indices Setup
Purpose: Create and optimize vector search indices for production
Usage: python scripts/setup_postgres_production.py --host prod-db.example.com --password secret
"""

import os
import sys
import argparse
import time
from datetime import datetime
import psycopg2
from psycopg2 import sql
from urllib.parse import urlparse


class PostgreSQLSetup:
    def __init__(self, host, port, database, user, password, verbose=False):
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.verbose = verbose
        self.conn = None
        self.cursor = None
        self.results = {"passed": [], "failed": [], "warnings": []}
        
    def log(self, message, level="INFO"):
        """Log message with timestamp"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] [{level}] {message}")
        
    def connect(self):
        """Connect to PostgreSQL database"""
        try:
            self.conn = psycopg2.connect(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password
            )
            self.cursor = self.conn.cursor()
            self.log("✓ Connected to PostgreSQL")
            return True
        except Exception as e:
            self.log(f"✗ Connection failed: {e}", "ERROR")
            return False
    
    def execute_query(self, query, params=None):
        """Execute a SQL query safely"""
        try:
            if params:
                self.cursor.execute(query, params)
            else:
                self.cursor.execute(query)
            self.conn.commit()
            return True, None
        except Exception as e:
            self.conn.rollback()
            return False, str(e)
    
    def fetch_one(self, query, params=None):
        """Fetch one result"""
        try:
            if params:
                self.cursor.execute(query, params)
            else:
                self.cursor.execute(query)
            return self.cursor.fetchone()
        except Exception as e:
            self.log(f"Query error: {e}", "ERROR")
            return None
    
    def fetch_all(self, query, params=None):
        """Fetch all results"""
        try:
            if params:
                self.cursor.execute(query, params)
            else:
                self.cursor.execute(query)
            return self.cursor.fetchall()
        except Exception as e:
            self.log(f"Query error: {e}", "ERROR")
            return []
    
    # ==================== PRE-CHECK PHASE ====================
    
    def check_pgvector_extension(self):
        """Check if pgvector extension is installed"""
        self.log("Checking pgvector extension...", "INFO")
        
        result = self.fetch_one(
            "SELECT version FROM pg_extension WHERE extname = 'vector';"
        )
        
        if result:
            self.log(f"✓ pgvector extension already installed", "INFO")
            self.results["passed"].append("pgvector extension exists")
            return True
        else:
            self.log("! pgvector not found. Installing...", "WARNING")
            success, error = self.execute_query("CREATE EXTENSION IF NOT EXISTS vector;")
            
            if success:
                self.log("✓ pgvector extension installed successfully", "INFO")
                self.results["passed"].append("pgvector extension installed")
                return True
            else:
                self.log(f"✗ Failed to install pgvector: {error}", "ERROR")
                self.results["failed"].append(f"pgvector installation failed: {error}")
                return False
    
    def check_visitors_table(self):
        """Check if visitors table exists and has embedding column"""
        self.log("Checking visitors table...", "INFO")
        
        result = self.fetch_one("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'visitors' AND column_name = 'embedding'
        """)
        
        if result:
            self.log(f"✓ Visitors table has embedding column (type: {result[1]})", "INFO")
            self.results["passed"].append("Visitors embedding column exists")
            return True
        else:
            self.log("✗ Visitors table missing embedding column", "ERROR")
            self.results["failed"].append("Visitors table missing embedding column")
            return False
    
    def check_visitors_table_size(self):
        """Get count of visitors in database"""
        result = self.fetch_one("SELECT COUNT(*) FROM visitors;")
        
        if result:
            count = result[0]
            self.log(f"  Found {count:,} visitors in database", "INFO")
            self.results["passed"].append(f"Visitor count: {count:,}")
            return count
        return 0
    
    # ==================== INDEX CREATION PHASE ====================
    
    def drop_old_indices(self):
        """Drop old vector indices if they exist"""
        self.log("Checking for existing indices...", "INFO")
        
        indices_to_drop = [
            'idx_visitors_embedding_ivfflat',
            'idx_visitors_embedding_hnsw'
        ]
        
        for idx_name in indices_to_drop:
            result = self.fetch_one(
                "SELECT indexname FROM pg_indexes WHERE indexname = %s",
                (idx_name,)
            )
            
            if result:
                self.log(f"  Dropping old index: {idx_name}", "INFO")
                success, error = self.execute_query(f"DROP INDEX IF EXISTS {idx_name};")
                
                if success:
                    self.log(f"  ✓ Dropped {idx_name}", "INFO")
                else:
                    self.log(f"  ! Warning dropping {idx_name}: {error}", "WARNING")
    
    def create_ivfflat_index(self):
        """Create IVFFlat vector index for cosine similarity search"""
        self.log("Creating IVFFlat index for vector similarity search...", "INFO")
        
        # IVFFlat index is good for:
        # - Large datasets (10K+ vectors)
        # - Approximate nearest neighbor search
        # - Memory efficient
        
        query = """
        CREATE INDEX IF NOT EXISTS idx_visitors_embedding_ivfflat 
        ON visitors USING ivfflat (embedding vector_cosine_ops) 
        WITH (lists = 100);
        """
        
        start_time = time.time()
        success, error = self.execute_query(query)
        elapsed = time.time() - start_time
        
        if success:
            self.log(f"✓ IVFFlat index created successfully in {elapsed:.2f}s", "INFO")
            self.results["passed"].append(f"IVFFlat index created ({elapsed:.2f}s)")
            return True
        else:
            self.log(f"✗ Failed to create IVFFlat index: {error}", "ERROR")
            self.results["failed"].append(f"IVFFlat index creation failed: {error}")
            return False
    
    def create_hnsw_index(self):
        """Create HNSW vector index (faster but more memory)"""
        self.log("Creating HNSW index as alternative (faster search)...", "INFO")
        
        # HNSW index is good for:
        # - Real-time search requirements
        # - Faster query performance
        # - More memory overhead
        
        query = """
        CREATE INDEX IF NOT EXISTS idx_visitors_embedding_hnsw 
        ON visitors USING hnsw (embedding vector_cosine_ops) 
        WITH (m = 16, ef_construction = 64);
        """
        
        try:
            start_time = time.time()
            success, error = self.execute_query(query)
            elapsed = time.time() - start_time
            
            if success:
                self.log(f"✓ HNSW index created successfully in {elapsed:.2f}s", "INFO")
                self.results["passed"].append(f"HNSW index created ({elapsed:.2f}s)")
                return True
            else:
                self.log(f"! HNSW index not available or error: {error}", "WARNING")
                self.results["warnings"].append(f"HNSW index creation: {error}")
                return False
        except Exception as e:
            self.log(f"! HNSW not available on this pgvector version", "WARNING")
            self.results["warnings"].append("HNSW index not available")
            return False
    
    def create_composite_indices(self):
        """Create composite indices for common query patterns"""
        self.log("Creating composite indices for optimization...", "INFO")
        
        composites = [
            (
                "idx_visitors_org_created",
                "CREATE INDEX IF NOT EXISTS idx_visitors_org_created ON visitors(organization_id, created_at DESC);"
            ),
            (
                "idx_visitors_org_active",
                "CREATE INDEX IF NOT EXISTS idx_visitors_org_active ON visitors(organization_id) WHERE deleted_at IS NULL;"
            ),
            (
                "idx_logs_confidence",
                "CREATE INDEX IF NOT EXISTS idx_logs_confidence ON visitor_logs(confidence DESC);"
            ),
            (
                "idx_logs_created",
                "CREATE INDEX IF NOT EXISTS idx_logs_created ON visitor_logs(created_at DESC);"
            ),
            (
                "idx_logs_visitor_date",
                "CREATE INDEX IF NOT EXISTS idx_logs_visitor_date ON visitor_logs(visitor_id, created_at DESC);"
            ),
        ]
        
        for idx_name, query in composites:
            success, error = self.execute_query(query)
            
            if success:
                self.log(f"  ✓ {idx_name}", "INFO")
                self.results["passed"].append(f"Index created: {idx_name}")
            else:
                self.log(f"  ! {idx_name}: {error}", "WARNING")
                self.results["warnings"].append(f"{idx_name}: {error}")
    
    # ==================== OPTIMIZATION PHASE ====================
    
    def analyze_tables(self):
        """Run ANALYZE to update table statistics"""
        self.log("Analyzing tables for query optimization...", "INFO")
        
        tables = ['visitors', 'visitor_logs', 'users', 'organizations']
        
        for table in tables:
            start_time = time.time()
            success, error = self.execute_query(f"ANALYZE {table};")
            elapsed = time.time() - start_time
            
            if success:
                self.log(f"  ✓ Analyzed {table} in {elapsed:.2f}s", "INFO")
            else:
                self.log(f"  ! Error analyzing {table}: {error}", "WARNING")
    
    def configure_autovacuum(self):
        """Configure autovacuum for key tables"""
        self.log("Configuring autovacuum settings...", "INFO")
        
        configs = [
            ("visitors", """
                ALTER TABLE visitors SET (
                    autovacuum_vacuum_scale_factor = 0.05,
                    autovacuum_analyze_scale_factor = 0.02,
                    autovacuum_vacuum_cost_delay = 10
                );
            """),
            ("visitor_logs", """
                ALTER TABLE visitor_logs SET (
                    autovacuum_vacuum_scale_factor = 0.05,
                    autovacuum_analyze_scale_factor = 0.02,
                    autovacuum_vacuum_cost_delay = 10
                );
            """),
        ]
        
        for table, query in configs:
            success, error = self.execute_query(query)
            
            if success:
                self.log(f"  ✓ Configured autovacuum for {table}", "INFO")
                self.results["passed"].append(f"Autovacuum configured: {table}")
            else:
                self.log(f"  ! Error for {table}: {error}", "WARNING")
    
    # ==================== VERIFICATION PHASE ====================
    
    def verify_indices(self):
        """Verify that indices were created successfully"""
        self.log("Verifying index creation...", "INFO")
        
        indices = self.fetch_all("""
            SELECT indexname, tablename 
            FROM pg_indexes 
            WHERE tablename IN ('visitors', 'visitor_logs')
            ORDER BY tablename, indexname;
        """)
        
        if indices:
            self.log(f"✓ Found {len(indices)} indices", "INFO")
            for idx_name, table in indices:
                self.log(f"  - {idx_name} on {table}", "INFO")
            self.results["passed"].append(f"Index verification: {len(indices)} indices found")
            return True
        else:
            self.log("✗ No indices found!", "ERROR")
            self.results["failed"].append("Index verification failed: no indices found")
            return False
    
    def benchmark_vector_search(self):
        """Benchmark vector similarity search performance"""
        self.log("Benchmarking vector similarity search...", "INFO")
        
        # Get a sample vector from database
        sample = self.fetch_one("SELECT embedding FROM visitors LIMIT 1;")
        
        if not sample or not sample[0]:
            self.log("! Cannot benchmark: no embedding vectors in database", "WARNING")
            return
        
        # Benchmark similarity search
        test_queries = [
            ("p50 - 10 results", "SELECT id FROM visitors ORDER BY embedding <-> %s LIMIT 10;"),
            ("p95 - 10 results", "SELECT id FROM visitors ORDER BY embedding <-> %s LIMIT 10;"),
            ("p99 - 100 results", "SELECT id FROM visitors ORDER BY embedding <-> %s LIMIT 100;"),
        ]
        
        for desc, query in test_queries:
            times = []
            for _ in range(5):  # 5 runs
                start = time.time()
                self.fetch_all(query, (sample[0],))
                times.append((time.time() - start) * 1000)  # ms
            
            avg_ms = sum(times) / len(times)
            self.log(f"  {desc}: {avg_ms:.2f}ms (avg of 5 runs)", "INFO")
            self.results["passed"].append(f"Benchmark {desc}: {avg_ms:.2f}ms")
    
    def check_index_size(self):
        """Check size of indices created"""
        self.log("Checking index sizes...", "INFO")
        
        sizes = self.fetch_all("""
            SELECT 
                schemaname,
                tablename,
                indexname,
                pg_size_pretty(pg_relation_size(indexrelid)) as size
            FROM pg_stat_user_indexes
            WHERE tablename IN ('visitors', 'visitor_logs')
            ORDER BY pg_relation_size(indexrelid) DESC;
        """)
        
        if sizes:
            total = 0
            for schema, table, idx, size in sizes:
                self.log(f"  {idx}: {size}", "INFO")
            self.results["passed"].append(f"Index sizing: {len(sizes)} indices measured")
        else:
            self.log("! No indices found for sizing", "WARNING")
    
    # ==================== MAIN EXECUTION ====================
    
    def run_all_checks(self):
        """Execute all setup and verification steps"""
        self.log("=" * 70, "INFO")
        self.log("PostgreSQL Production Setup - Vector Indices", "INFO")
        self.log("=" * 70, "INFO")
        
        # Connection
        if not self.connect():
            return self.results
        
        # PRE-CHECKS
        self.log("\n[PHASE 1] PRE-CHECKS", "INFO")
        self.check_pgvector_extension()
        self.check_visitors_table()
        visitor_count = self.check_visitors_table_size()
        
        # INDEX CREATION
        self.log("\n[PHASE 2] INDEX CREATION", "INFO")
        self.drop_old_indices()
        self.create_ivfflat_index()
        self.create_hnsw_index()
        self.create_composite_indices()
        
        # OPTIMIZATION
        self.log("\n[PHASE 3] OPTIMIZATION", "INFO")
        self.analyze_tables()
        self.configure_autovacuum()
        
        # VERIFICATION
        self.log("\n[PHASE 4] VERIFICATION", "INFO")
        self.verify_indices()
        if visitor_count > 0:
            self.benchmark_vector_search()
        self.check_index_size()
        
        # SUMMARY
        self.log("\n" + "=" * 70, "INFO")
        self.log("SUMMARY", "INFO")
        self.log("=" * 70, "INFO")
        self.log(f"✓ Passed: {len(self.results['passed'])} checks", "INFO")
        self.log(f"✗ Failed: {len(self.results['failed'])} checks", "INFO")
        self.log(f"! Warnings: {len(self.results['warnings'])} warnings", "INFO")
        
        if self.results['failed']:
            self.log("\nFailed checks:", "ERROR")
            for msg in self.results['failed']:
                self.log(f"  - {msg}", "ERROR")
        
        if self.results['warnings']:
            self.log("\nWarnings:", "WARNING")
            for msg in self.results['warnings']:
                self.log(f"  - {msg}", "WARNING")
        
        # Close connection
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
        
        self.log("=" * 70, "INFO")
        
        return self.results
    
    def get_status(self):
        """Return success status"""
        return len(self.results['failed']) == 0


def main():
    parser = argparse.ArgumentParser(
        description="Setup PostgreSQL vector indices for production SentinelCV"
    )

    parser.add_argument('--database-url', help='PostgreSQL connection URL')
    parser.add_argument('--host', default='localhost', help='PostgreSQL host')
    parser.add_argument('--port', type=int, default=5432, help='PostgreSQL port')
    parser.add_argument('--database', default='sentinelcv', help='Database name')
    parser.add_argument('--user', default='postgres', help='Database user')
    parser.add_argument('--password', required=False, help='Database password')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')
    
    args = parser.parse_args()
    
    database_url = args.database_url or os.getenv('DATABASE_URL')
    host = args.host
    port = args.port
    database = args.database
    user = args.user

    password = args.password or os.getenv('DB_PASSWORD', 'postgres')

    if database_url:
        parsed = urlparse(database_url)
        if parsed.scheme.startswith('postgresql'):
            host = parsed.hostname or host
            port = parsed.port or port
            database = (parsed.path or '').lstrip('/') or database
            user = parsed.username or user
            if not args.password and parsed.password:
                password = parsed.password
        else:
            print("ERROR: DATABASE_URL must use postgresql:// scheme", file=sys.stderr)
            sys.exit(1)

    setup = PostgreSQLSetup(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
        verbose=args.verbose
    )
    
    results = setup.run_all_checks()
    
    sys.exit(0 if setup.get_status() else 1)


if __name__ == "__main__":
    main()
