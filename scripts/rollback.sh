#!/bin/bash

################################################################################
# Rollback Script
# Version: 1.0
# Purpose: Safely rollback to previous version in case of deployment failure
# Usage: ./rollback.sh [--full] [--db-only] [--app-only]
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
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
ROLLBACK_LOG="deployments/rollback_${TIMESTAMP}.log"

# Flags
FULL_ROLLBACK=false
DB_ONLY=false
APP_ONLY=false

################################################################################
# UTILITY FUNCTIONS
################################################################################

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1" | tee -a "$ROLLBACK_LOG"
}

log_success() {
    echo -e "${GREEN}[✓]${NC} $1" | tee -a "$ROLLBACK_LOG"
}

log_error() {
    echo -e "${RED}[✗]${NC} $1" | tee -a "$ROLLBACK_LOG"
}

log_warn() {
    echo -e "${YELLOW}[!]${NC} $1" | tee -a "$ROLLBACK_LOG"
}

print_section() {
    echo "" | tee -a "$ROLLBACK_LOG"
    echo "╔════════════════════════════════════════════════════════════════╗" | tee -a "$ROLLBACK_LOG"
    echo "║ $1" | tee -a "$ROLLBACK_LOG"
    echo "╚════════════════════════════════════════════════════════════════╝" | tee -a "$ROLLBACK_LOG"
}

confirm_action() {
    local prompt=$1
    read -p "$(echo -e ${YELLOW})$prompt$(echo -e ${NC}) (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        log_info "Action cancelled"
        return 1
    fi
    return 0
}

################################################################################
# DATABASE ROLLBACK
################################################################################

rollback_database() {
    print_section "Rolling Back Database"
    
    if [ "$APP_ONLY" = true ]; then
        log_info "Skipping database rollback (--app-only flag set)"
        return
    fi
    
    if [ ! -d "$BACKUP_DIR" ]; then
        log_error "Backup directory not found: $BACKUP_DIR"
        return 1
    fi
    
    # Find latest backup
    LATEST_BACKUP=$(ls -t "$BACKUP_DIR"/db_backup_*.sql 2>/dev/null | head -1)
    
    if [ -z "$LATEST_BACKUP" ]; then
        log_error "No backup files found in $BACKUP_DIR"
        return 1
    fi
    
    log_info "Latest backup: $LATEST_BACKUP"
    log_info "Backup date: $(ls -l "$LATEST_BACKUP" | awk '{print $6, $7, $8}')"
    
    if ! confirm_action "Restore database from $LATEST_BACKUP?"; then
        return 1
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
    
    log_info "Stopping active connections to database..."
    
    if [ -n "$DB_PASSWORD" ]; then
        PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -c "
        SELECT pg_terminate_backend(pg_stat_activity.pid)
        FROM pg_stat_activity
        WHERE pg_stat_activity.datname = '$DB_NAME' AND pid <> pg_backend_pid();" 2>/dev/null || true
    else
        psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -c "
        SELECT pg_terminate_backend(pg_stat_activity.pid)
        FROM pg_stat_activity
        WHERE pg_stat_activity.datname = '$DB_NAME' AND pid <> pg_backend_pid();" 2>/dev/null || true
    fi
    
    log_info "Restoring database from backup..."
    
    if [ -n "$DB_PASSWORD" ]; then
        PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" < "$LATEST_BACKUP"
    else
        psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" < "$LATEST_BACKUP"
    fi
    
    log_success "Database rollback completed"
}

################################################################################
# APPLICATION ROLLBACK
################################################################################

rollback_application() {
    print_section "Rolling Back Application"
    
    if [ "$DB_ONLY" = true ]; then
        log_info "Skipping application rollback (--db-only flag set)"
        return
    fi
    
    log_info "Stopping Docker containers..."
    
    if ! command -v docker-compose &> /dev/null && ! command -v docker &> /dev/null; then
        log_warn "Docker not found, cannot rollback application"
        return
    fi
    
    if [ -f "docker-compose.yml" ]; then
        docker-compose down || true
        log_success "Docker containers stopped"
    else
        log_warn "docker-compose.yml not found"
    fi
    
    # Git rollback (if FULL_ROLLBACK is set)
    if [ "$FULL_ROLLBACK" = true ]; then
        print_section "Git Rollback"
        
        log_info "Current branch: $(git rev-parse --abbrev-ref HEAD)"
        log_info "Current commit: $(git rev-parse --short HEAD)"
        
        log_info "Recent commits:"
        git log --oneline -5 | tee -a "$ROLLBACK_LOG"
        
        if confirm_action "Reset to previous commit?"; then
            log_info "Resetting to HEAD~1..."
            git reset --hard HEAD~1
            log_success "Git reset completed"
        fi
    fi
    
    log_info "Restarting Docker containers..."
    
    if [ -f "docker-compose.yml" ]; then
        docker-compose up -d || true
        
        log_info "Waiting for containers to start (30 seconds)..."
        sleep 30
        
        log_success "Docker containers restarted"
    fi
}

################################################################################
# VERIFICATION
################################################################################

verify_rollback() {
    print_section "Verifying Rollback"
    
    # Load environment
    if [ -f ".env" ]; then
        export $(cat .env | grep -v '^#' | xargs)
    fi
    
    API_URL="${API_URL:-http://localhost:8000}"
    
    log_info "Checking API health at $API_URL"
    
    if curl -s "${API_URL}/api/health" > /dev/null 2>&1; then
        log_success "API is responding"
        
        # Get API version/status
        if command -v curl &> /dev/null; then
            STATUS=$(curl -s "${API_URL}/api/health" | grep -o '"status":"[^"]*"' | head -1)
            log_info "API status: $STATUS"
        fi
    else
        log_warn "API is not responding (it may still be starting)"
    fi
    
    # Database check
    DB_HOST="${DATABASE_URL:-localhost}"
    DB_PORT="${DATABASE_PORT:-5432}"
    DB_USER="${DATABASE_USER:-postgres}"
    
    if command -v psql &> /dev/null; then
        if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -c "SELECT 1" &> /dev/null; then
            log_success "Database connection successful"
        else
            log_warn "Database connection failed"
        fi
    fi
}

################################################################################
# CLEANUP
################################################################################

cleanup_old_backups() {
    print_section "Backup Management"
    
    log_info "Checking backup directory size..."
    
    BACKUP_SIZE=$(du -sh "$BACKUP_DIR" 2>/dev/null | awk '{print $1}')
    log_info "Backup directory size: $BACKUP_SIZE"
    
    # Keep only last 7 backups
    BACKUP_COUNT=$(ls -1 "$BACKUP_DIR"/db_backup_*.sql 2>/dev/null | wc -l)
    
    if [ "$BACKUP_COUNT" -gt 7 ]; then
        log_warn "More than 7 backups found. Removing oldest backups..."
        
        ls -t "$BACKUP_DIR"/db_backup_*.sql | tail -n +8 | while read backup; do
            log_info "Removing: $(basename "$backup")"
            rm "$backup"
        done
        
        log_success "Old backups cleaned up"
    fi
}

################################################################################
# REPORT
################################################################################

create_rollback_report() {
    print_section "Creating Rollback Report"
    
    mkdir -p deployments
    
    cat >> "deployments/rollback_history.log" <<EOF
================================================================================
Rollback: $TIMESTAMP
Flags: FULL_ROLLBACK=$FULL_ROLLBACK, DB_ONLY=$DB_ONLY, APP_ONLY=$APP_ONLY
Git Branch: $(git rev-parse --abbrev-ref HEAD)
Git Commit: $(git rev-parse --short HEAD)
Timestamp: $(date)
================================================================================

EOF
    
    log_success "Rollback report created"
}

################################################################################
# MAIN EXECUTION
################################################################################

main() {
    mkdir -p deployments
    
    print_section "SentinelCV Rollback Script"
    
    log_info "Rollback started at $(date)"
    log_info "Timestamp: $TIMESTAMP"
    log_info "Log file: $ROLLBACK_LOG"
    
    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --full)
                FULL_ROLLBACK=true
                shift
                ;;
            --db-only)
                DB_ONLY=true
                shift
                ;;
            --app-only)
                APP_ONLY=true
                shift
                ;;
            *)
                log_error "Unknown option: $1"
                exit 1
                ;;
        esac
    done
    
    # Confirmation
    log_warn "⚠️  ROLLBACK OPERATION ⚠️"
    log_warn "This will restore your system to a previous state"
    log_info "Flags: FULL_ROLLBACK=$FULL_ROLLBACK, DB_ONLY=$DB_ONLY, APP_ONLY=$APP_ONLY"
    
    if ! confirm_action "Do you want to proceed with rollback?"; then
        log_info "Rollback cancelled"
        exit 0
    fi
    
    # Execute rollback stages
    if [ "$APP_ONLY" = false ]; then
        if ! rollback_database; then
            log_error "Database rollback failed"
            exit 1
        fi
    fi
    
    if [ "$DB_ONLY" = false ]; then
        if ! rollback_application; then
            log_error "Application rollback failed"
            exit 1
        fi
    fi
    
    verify_rollback
    cleanup_old_backups
    create_rollback_report
    
    print_section "Rollback Complete"
    log_success "Rollback completed successfully!"
    log_info "View logs: tail -f $ROLLBACK_LOG"
}

main "$@"
