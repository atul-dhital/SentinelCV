#!/bin/bash

################################################################################
# Database Migration Script
# Version: 1.0
# Purpose: Execute database migrations and ensure schema is up-to-date
# Usage: ./database_migration.sh [--rollback] [--seed]
################################################################################

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
BACKUP_DIR="db_backups"
MIGRATION_DIR="backend/database/migrations"
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')

################################################################################
# UTILITY FUNCTIONS
################################################################################

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

log_error() {
    echo -e "${RED}[✗]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[!]${NC} $1"
}

print_section() {
    echo ""
    echo "╔════════════════════════════════════════════════════════════════╗"
    echo "║ $1"
    echo "╚════════════════════════════════════════════════════════════════╝"
}

################################################################################
# BACKUP FUNCTIONS
################################################################################

create_database_backup() {
    print_section "Creating Database Backup"
    
    # Load environment variables
    if [ -f ".env" ]; then
        export $(cat .env | grep -v '^#' | xargs)
    fi
    
    DB_HOST="${DATABASE_URL:-localhost}"
    DB_PORT="${DATABASE_PORT:-5432}"
    DB_USER="${DATABASE_USER:-postgres}"
    DB_NAME="${DATABASE_NAME:-sentinelcv}"
    DB_PASSWORD="${DATABASE_PASSWORD:-}"
    
    # Create backup directory
    mkdir -p "$BACKUP_DIR"
    
    BACKUP_FILE="$BACKUP_DIR/db_backup_${TIMESTAMP}.sql"
    
    log_info "Backing up database: $DB_NAME"
    log_info "Backup location: $BACKUP_FILE"
    
    if [ -n "$DB_PASSWORD" ]; then
        PGPASSWORD="$DB_PASSWORD" pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" > "$BACKUP_FILE"
    else
        pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" > "$BACKUP_FILE"
    fi
    
    log_success "Database backup created successfully"
    echo "$BACKUP_FILE"
}

restore_from_backup() {
    local BACKUP_FILE=$1
    
    print_section "Restoring from Backup"
    
    if [ ! -f "$BACKUP_FILE" ]; then
        log_error "Backup file not found: $BACKUP_FILE"
        exit 1
    fi
    
    # Load environment variables
    if [ -f ".env" ]; then
        export $(cat .env | grep -v '^#' | xargs)
    fi
    
    DB_HOST="${DATABASE_URL:-localhost}"
    DB_PORT="${DATABASE_PORT:-5432}"
    DB_USER="${DATABASE_USER:-postgres}"
    DB_NAME="${DATABASE_NAME:-sentinelcv}"
    DB_PASSWORD="${DATABASE_PASSWORD:-}"
    
    log_warn "This will DROP all data in $DB_NAME and restore from $BACKUP_FILE"
    read -p "Are you sure? (yes/no): " confirm
    
    if [ "$confirm" != "yes" ]; then
        log_info "Restore cancelled"
        return
    fi
    
    log_info "Restoring database from backup..."
    
    if [ -n "$DB_PASSWORD" ]; then
        PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" < "$BACKUP_FILE"
    else
        psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" < "$BACKUP_FILE"
    fi
    
    log_success "Database restored from backup"
}

################################################################################
# MIGRATION FUNCTIONS
################################################################################

run_migrations() {
    print_section "Running Database Migrations"
    
    if [ ! -d "$MIGRATION_DIR" ]; then
        log_warn "Migration directory not found: $MIGRATION_DIR"
        log_info "Using Alembic for migrations..."
        run_alembic_migrations
        return
    fi
    
    log_info "Executing migration scripts from $MIGRATION_DIR"
    
    # Execute all .sql files in order
    for migration_file in $(ls -v "$MIGRATION_DIR"/*.sql 2>/dev/null | sort); do
        log_info "Executing: $(basename "$migration_file")"
        
        # Load environment variables
        if [ -f ".env" ]; then
            export $(cat .env | grep -v '^#' | xargs)
        fi
        
        DB_HOST="${DATABASE_URL:-localhost}"
        DB_PORT="${DATABASE_PORT:-5432}"
        DB_USER="${DATABASE_USER:-postgres}"
        DB_NAME="${DATABASE_NAME:-sentinelcv}"
        DB_PASSWORD="${DATABASE_PASSWORD:-}"
        
        if [ -n "$DB_PASSWORD" ]; then
            PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" -f "$migration_file"
        else
            psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" -f "$migration_file"
        fi
        
        log_success "Migration completed: $(basename "$migration_file")"
    done
}

run_alembic_migrations() {
    if ! command -v alembic &> /dev/null; then
        log_error "Alembic not installed. Install with: pip install alembic"
        return 1
    fi
    
    log_info "Running Alembic migrations..."
    
    # Activate virtual environment if it exists
    if [ -d "venv" ]; then
        source venv/bin/activate 2>/dev/null || . venv/Scripts/activate 2>/dev/null || true
    fi
    
    if [ -d "alembic" ]; then
        cd alembic
        alembic upgrade head
        cd ..
        log_success "Alembic migrations completed"
    else
        log_warn "Alembic directory not found"
    fi
}

seed_database() {
    print_section "Seeding Database with Test Data"
    
    log_info "Checking for seed script..."
    
    if [ -f "backend/database/seeds/seed_data.py" ]; then
        log_info "Found seed script: backend/database/seeds/seed_data.py"
        
        # Activate virtual environment if it exists
        if [ -d "venv" ]; then
            source venv/bin/activate 2>/dev/null || . venv/Scripts/activate 2>/dev/null || true
        fi
        
        python3 backend/database/seeds/seed_data.py
        log_success "Database seeding completed"
    else
        log_warn "Seed script not found at backend/database/seeds/seed_data.py"
    fi
}

################################################################################
# VERIFICATION FUNCTIONS
################################################################################

verify_migrations() {
    print_section "Verifying Database Schema"
    
    # Load environment variables
    if [ -f ".env" ]; then
        export $(cat .env | grep -v '^#' | xargs)
    fi
    
    DB_HOST="${DATABASE_URL:-localhost}"
    DB_PORT="${DATABASE_PORT:-5432}"
    DB_USER="${DATABASE_USER:-postgres}"
    DB_NAME="${DATABASE_NAME:-sentinelcv}"
    DB_PASSWORD="${DATABASE_PASSWORD:-}"
    
    log_info "Checking database tables..."
    
    # Count tables
    if [ -n "$DB_PASSWORD" ]; then
        TABLE_COUNT=$(PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" -t -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';")
    else
        TABLE_COUNT=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" -t -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';")
    fi
    
    if [ -z "$TABLE_COUNT" ] || [ "$TABLE_COUNT" -lt 1 ]; then
        log_error "No tables found in database"
        return 1
    fi
    
    log_success "Database contains $TABLE_COUNT tables"
    
    # Verify critical tables
    CRITICAL_TABLES=("users" "visitors" "cameras" "videos" "liveness_detections")
    
    for table in "${CRITICAL_TABLES[@]}"; do
        if [ -n "$DB_PASSWORD" ]; then
            TABLE_EXISTS=$(PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" -t -c "SELECT to_regclass('public.$table');")
        else
            TABLE_EXISTS=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" -t -c "SELECT to_regclass('public.$table');")
        fi
        
        if [ -n "$TABLE_EXISTS" ] && [ "$TABLE_EXISTS" != "" ]; then
            log_success "Table exists: $table"
        else
            log_warn "Table not found: $table"
        fi
    done
}

################################################################################
# ROLLBACK FUNCTIONS
################################################################################

rollback_migrations() {
    print_section "Rolling Back Migrations"
    
    LATEST_BACKUP=$(ls -t "$BACKUP_DIR"/db_backup_*.sql 2>/dev/null | head -1)
    
    if [ -z "$LATEST_BACKUP" ]; then
        log_error "No backup files found in $BACKUP_DIR"
        return 1
    fi
    
    log_info "Latest backup: $LATEST_BACKUP"
    restore_from_backup "$LATEST_BACKUP"
}

################################################################################
# MAIN EXECUTION
################################################################################

main() {
    print_section "SentinelCV Database Migration Tool"
    
    # Parse arguments
    SHOULD_ROLLBACK=false
    SHOULD_SEED=false
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            --rollback)
                SHOULD_ROLLBACK=true
                shift
                ;;
            --seed)
                SHOULD_SEED=true
                shift
                ;;
            *)
                log_error "Unknown option: $1"
                exit 1
                ;;
        esac
    done
    
    # Check prerequisites
    if ! command -v psql &> /dev/null; then
        log_error "PostgreSQL client (psql) not found. Install PostgreSQL tools."
        exit 1
    fi
    
    # Create backup
    BACKUP_FILE=$(create_database_backup)
    
    # Run migrations or rollback
    if [ "$SHOULD_ROLLBACK" = true ]; then
        rollback_migrations
    else
        run_migrations
        verify_migrations
        
        if [ "$SHOULD_SEED" = true ]; then
            seed_database
        fi
    fi
    
    print_section "Migration Complete"
    log_success "Database migration completed successfully"
    log_info "Backup saved to: $BACKUP_FILE"
}

main "$@"
