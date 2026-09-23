#!/bin/bash

################################################################################
# Production Deployment Script
# Version: 1.0
# Purpose: Execute full production deployment with health checks and rollback
# Usage: ./deploy.sh [--dry-run] [--skip-tests] [--skip-backup]
################################################################################

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
DEPLOYMENT_LOG="deployments/deployment_${TIMESTAMP}.log"
BACKUP_DIR="db_backups"
START_TIME=$(date +%s)

# Flags
DRY_RUN=false
SKIP_TESTS=false
SKIP_BACKUP=false

################################################################################
# UTILITY FUNCTIONS
################################################################################

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1" | tee -a "$DEPLOYMENT_LOG"
}

log_success() {
    echo -e "${GREEN}[✓]${NC} $1" | tee -a "$DEPLOYMENT_LOG"
}

log_error() {
    echo -e "${RED}[✗]${NC} $1" | tee -a "$DEPLOYMENT_LOG"
}

log_warn() {
    echo -e "${YELLOW}[!]${NC} $1" | tee -a "$DEPLOYMENT_LOG"
}

print_section() {
    echo "" | tee -a "$DEPLOYMENT_LOG"
    echo "╔════════════════════════════════════════════════════════════════╗" | tee -a "$DEPLOYMENT_LOG"
    echo "║ $1" | tee -a "$DEPLOYMENT_LOG"
    echo "╚════════════════════════════════════════════════════════════════╝" | tee -a "$DEPLOYMENT_LOG"
}

elapsed_time() {
    local END_TIME=$(date +%s)
    local DURATION=$((END_TIME - START_TIME))
    echo "$((DURATION / 60))m $((DURATION % 60))s"
}

dry_run_warning() {
    if [ "$DRY_RUN" = true ]; then
        log_warn "DRY RUN MODE: No actual changes will be made"
    fi
}

################################################################################
# PRE-DEPLOYMENT CHECKS
################################################################################

check_prerequisites() {
    print_section "Pre-Deployment Checks"
    
    local checks_failed=0
    
    # Check if we're in the correct directory
    if [ ! -f "requirements.txt" ]; then
        log_error "requirements.txt not found. Run from project root."
        exit 1
    fi
    
    # Check git status
    if [ -n "$(git status --porcelain)" ] && [ "$DRY_RUN" = false ]; then
        log_warn "Uncommitted changes detected in git"
        read -p "Continue anyway? (yes/no): " confirm
        if [ "$confirm" != "yes" ]; then
            log_info "Deployment cancelled"
            exit 1
        fi
    fi
    
    # Check environment configuration
    if [ ! -f ".env" ]; then
        log_error ".env file not found"
        exit 1
    fi
    
    log_success "All prerequisite checks passed"
}

################################################################################
# BUILD STAGE
################################################################################

build_backend() {
    print_section "Building Backend"
    
    log_info "Installing Python dependencies..."
    
    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would run: pip install -r requirements.txt"
        return
    fi
    
    # Activate virtual environment
    if [ -d "venv" ]; then
        source venv/bin/activate 2>/dev/null || . venv/Scripts/activate 2>/dev/null || true
    fi
    
    pip install -r requirements.txt --quiet
    log_success "Backend dependencies installed"
}

build_frontend() {
    print_section "Building Frontend"
    
    if [ ! -d "frontend" ]; then
        log_warn "Frontend directory not found, skipping frontend build"
        return
    fi
    
    log_info "Installing frontend dependencies..."
    
    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would run: npm install in frontend/"
        log_info "[DRY RUN] Would run: npm run build in frontend/"
        return
    fi
    
    cd frontend
    
    if [ ! -f "package.json" ]; then
        log_warn "package.json not found in frontend/"
        cd ..
        return
    fi
    
    npm install --quiet
    log_info "Running frontend build..."
    npm run build
    
    cd ..
    log_success "Frontend build completed"
}

################################################################################
# TEST STAGE
################################################################################

run_tests() {
    if [ "$SKIP_TESTS" = true ]; then
        log_warn "Skipping tests (--skip-tests flag set)"
        return
    fi
    
    print_section "Running Tests"
    
    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would run: pytest tests/"
        return
    fi
    
    # Activate virtual environment
    if [ -d "venv" ]; then
        source venv/bin/activate 2>/dev/null || . venv/Scripts/activate 2>/dev/null || true
    fi
    
    log_info "Running unit tests..."
    
    if ! pytest tests/unit -v --tb=short; then
        log_error "Unit tests failed"
        return 1
    fi
    
    log_info "Running integration tests..."
    
    if ! pytest tests/integration -v --tb=short; then
        log_error "Integration tests failed"
        return 1
    fi
    
    log_success "All tests passed"
}

################################################################################
# DATABASE STAGE
################################################################################

backup_database() {
    if [ "$SKIP_BACKUP" = true ]; then
        log_warn "Skipping database backup (--skip-backup flag set)"
        return
    fi
    
    print_section "Backing Up Database"
    
    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would create database backup"
        return
    fi
    
    if [ -f "scripts/database_migration.sh" ]; then
        bash scripts/database_migration.sh
    else
        log_warn "Database migration script not found"
    fi
}

run_migrations() {
    print_section "Running Migrations"
    
    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would run database migrations"
        return
    fi
    
    if [ -f "scripts/database_migration.sh" ]; then
        bash scripts/database_migration.sh
    else
        log_warn "Database migration script not found"
    fi
}

################################################################################
# DEPLOYMENT STAGE
################################################################################

deploy_with_docker() {
    print_section "Deploying with Docker Compose"
    
    if [ ! -f "docker-compose.yml" ]; then
        log_warn "docker-compose.yml not found, skipping Docker deployment"
        return
    fi
    
    log_info "Starting Docker containers..."
    
    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would run: docker-compose up -d"
        return
    fi
    
    docker-compose down || true
    docker-compose up -d
    
    log_info "Waiting for services to start (30 seconds)..."
    sleep 30
    
    log_success "Docker deployment completed"
}

################################################################################
# HEALTH CHECKS
################################################################################

health_check() {
    print_section "Performing Health Checks"
    
    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would perform health checks"
        return
    fi
    
    # Load environment
    if [ -f ".env" ]; then
        export $(cat .env | grep -v '^#' | xargs)
    fi
    
    API_URL="${API_URL:-http://localhost:8000}"
    HEALTH_CHECK_TIMEOUT=60
    ELAPSED=0
    
    log_info "Checking API health at $API_URL"
    
    while [ $ELAPSED -lt $HEALTH_CHECK_TIMEOUT ]; do
        if curl -s "${API_URL}/api/health" > /dev/null 2>&1; then
            log_success "API health check passed"
            
            # Additional health checks
            if curl -s "${API_URL}/api/health/deep" > /dev/null 2>&1; then
                log_success "Deep health check passed"
            else
                log_warn "Deep health check failed (non-critical)"
            fi
            
            return 0
        fi
        
        ELAPSED=$((ELAPSED + 5))
        log_info "Waiting for API to respond... ($ELAPSED/${HEALTH_CHECK_TIMEOUT}s)"
        sleep 5
    done
    
    log_error "Health check failed after ${HEALTH_CHECK_TIMEOUT}s"
    return 1
}

check_database_health() {
    print_section "Checking Database Health"
    
    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would check database health"
        return
    fi
    
    # Load environment
    if [ -f ".env" ]; then
        export $(cat .env | grep -v '^#' | xargs)
    fi
    
    DB_HOST="${DATABASE_URL:-localhost}"
    DB_PORT="${DATABASE_PORT:-5432}"
    DB_USER="${DATABASE_USER:-postgres}"
    
    if command -v psql &> /dev/null; then
        if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -c "SELECT 1" &> /dev/null; then
            log_success "Database connection successful"
        else
            log_error "Database connection failed"
            return 1
        fi
    fi
}

################################################################################
# ROLLBACK FUNCTIONS
################################################################################

rollback() {
    print_section "Rolling Back Deployment"
    
    log_warn "Starting rollback..."
    
    if [ -f "scripts/rollback.sh" ]; then
        bash scripts/rollback.sh
    else
        log_warn "Rollback script not found"
        
        log_info "Manual rollback steps:"
        log_info "1. Restore database from latest backup in db_backups/"
        log_info "2. Restart application: docker-compose restart"
        log_info "3. Verify health: curl http://localhost:8000/api/health"
    fi
}

################################################################################
# POST-DEPLOYMENT
################################################################################

create_deployment_record() {
    print_section "Recording Deployment"
    
    mkdir -p deployments
    
    cat >> "deployments/deployment_history.log" <<EOF
================================================================================
Deployment: $TIMESTAMP
Duration: $(elapsed_time)
Status: SUCCESS
Flags: DRY_RUN=$DRY_RUN, SKIP_TESTS=$SKIP_TESTS, SKIP_BACKUP=$SKIP_BACKUP
Git Branch: $(git rev-parse --abbrev-ref HEAD)
Git Commit: $(git rev-parse --short HEAD)
================================================================================

EOF
    
    log_success "Deployment recorded in deployments/deployment_history.log"
}

################################################################################
# MAIN EXECUTION
################################################################################

main() {
    print_section "SentinelCV Production Deployment"
    
    mkdir -p deployments
    
    log_info "Deployment started at $(date)"
    log_info "Timestamp: $TIMESTAMP"
    log_info "Log file: $DEPLOYMENT_LOG"
    
    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --dry-run)
                DRY_RUN=true
                shift
                ;;
            --skip-tests)
                SKIP_TESTS=true
                shift
                ;;
            --skip-backup)
                SKIP_BACKUP=true
                shift
                ;;
            *)
                log_error "Unknown option: $1"
                exit 1
                ;;
        esac
    done
    
    dry_run_warning
    
    # Execute deployment stages
    if ! check_prerequisites; then
        log_error "Prerequisite checks failed"
        exit 1
    fi
    
    if ! build_backend; then
        log_error "Backend build failed"
        rollback
        exit 1
    fi
    
    if ! build_frontend; then
        log_warn "Frontend build encountered issues (continuing)"
    fi
    
    if ! run_tests; then
        log_error "Tests failed"
        rollback
        exit 1
    fi
    
    if ! backup_database; then
        log_error "Database backup failed"
        exit 1
    fi
    
    if ! run_migrations; then
        log_error "Database migrations failed"
        rollback
        exit 1
    fi
    
    if ! deploy_with_docker; then
        log_error "Docker deployment failed"
        rollback
        exit 1
    fi
    
    if ! health_check; then
        log_error "Health checks failed"
        rollback
        exit 1
    fi
    
    if ! check_database_health; then
        log_error "Database health check failed"
        rollback
        exit 1
    fi
    
    create_deployment_record
    
    print_section "Deployment Complete"
    log_success "Deployment completed successfully!"
    log_info "Total time: $(elapsed_time)"
    log_info "View logs: tail -f $DEPLOYMENT_LOG"
}

main "$@"
