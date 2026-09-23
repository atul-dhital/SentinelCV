#!/bin/bash

################################################################################
# Pre-Deployment Health Check Script
# Version: 1.0
# Purpose: Verify system readiness before deployment
# Usage: ./pre_deployment_check.sh
################################################################################

##############################################################################
# SentinelCV Pre-Deployment Validation Checklist (ENHANCED)
# Purpose: Run 15 critical checks before production deployment
# Usage: bash scripts/pre_deployment_check.sh
##############################################################################

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PASSED=0
FAILED=0
WARNINGS=0

################################################################################
# UTILITY FUNCTIONS
################################################################################

log_pass() {
    echo -e "${GREEN}✓ $1${NC}"
    ((PASSED++))
}

log_fail() {
    echo -e "${RED}✗ $1${NC}"
    ((FAILED++))
}

log_warn() {
    echo -e "${YELLOW}! $1${NC}"
    ((WARNINGS++))
}

log_info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

section_header() {
    echo ""
    echo "══════════════════════════════════════════════════════════════════"
    echo -e "${BLUE}$1${NC}"
    echo "══════════════════════════════════════════════════════════════════"
}

################################################################################
# SYSTEM CHECKS
################################################################################

check_system_requirements() {
    section_header "System Requirements"
    
    # Check OS
    if [[ "$OSTYPE" == "linux-gnu"* ]] || [[ "$OSTYPE" == "darwin"* ]] || [[ "$OSTYPE" == "msys" ]]; then
        log_pass "Operating System compatible"
    else
        log_fail "Operating System not supported: $OSTYPE"
    fi
    
    # Check disk space (require at least 5GB)
    AVAILABLE_DISK=$(df / | tail -1 | awk '{print $4}')
    if [ "$AVAILABLE_DISK" -gt 5242880 ]; then
        log_pass "Disk space available: $(($AVAILABLE_DISK / 1024 / 1024))GB"
    else
        log_fail "Insufficient disk space. Required: 5GB, Available: $(($AVAILABLE_DISK / 1024 / 1024))GB"
    fi
    
    # Check available memory (require at least 2GB)
    AVAILABLE_MEM=$(free -m | awk 'NR==2{print $7}')
    if [ "$AVAILABLE_MEM" -gt 2048 ]; then
        log_pass "Available memory: ${AVAILABLE_MEM}MB"
    else
        log_warn "Low available memory: ${AVAILABLE_MEM}MB (recommended: 2048MB+)"
    fi
}

check_dependencies() {
    section_header "Dependency Checks"
    
    # Python
    if command -v python3 &> /dev/null; then
        PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
        log_pass "Python 3 installed: $PYTHON_VERSION"
    else
        log_fail "Python 3 not found"
        return
    fi
    
    # Docker
    if command -v docker &> /dev/null; then
        DOCKER_VERSION=$(docker --version | awk '{print $3}' | sed 's/,//')
        log_pass "Docker installed: $DOCKER_VERSION"
    else
        log_warn "Docker not found (required for containerized deployment)"
    fi
    
    # Docker Compose
    if command -v docker-compose &> /dev/null; then
        COMPOSE_VERSION=$(docker-compose --version | awk '{print $3}' | sed 's/,//')
        log_pass "Docker Compose installed: $COMPOSE_VERSION"
    else
        log_warn "Docker Compose not found (required for multi-container deployment)"
    fi
    
    # PostgreSQL client (for database checks)
    if command -v psql &> /dev/null; then
        log_pass "PostgreSQL client installed"
    else
        log_warn "PostgreSQL client not found (psql)"
    fi
    
    # Git
    if command -v git &> /dev/null; then
        log_pass "Git installed"
    else
        log_warn "Git not found"
    fi
}

check_application_setup() {
    section_header "Application Setup"
    
    # Check if we're in the correct directory
    if [ -f "requirements.txt" ]; then
        log_pass "requirements.txt found"
    else
        log_fail "requirements.txt not found. Run from project root."
        return
    fi
    
    # Check Python virtual environment
    if [ -d "venv" ]; then
        log_pass "Python virtual environment exists"
    else
        log_warn "Python virtual environment not found. Run: python3 -m venv venv"
    fi
    
    # Check .env file
    if [ -f ".env" ]; then
        log_pass ".env configuration file found"
    else
        log_warn ".env file not found. Create from .env.example"
    fi
    
    # Check key directories
    if [ -d "backend" ]; then
        log_pass "Backend directory found"
    else
        log_fail "Backend directory not found"
    fi
    
    if [ -d "frontend" ]; then
        log_pass "Frontend directory found"
    else
        log_fail "Frontend directory not found"
    fi
    
    if [ -d "tests" ]; then
        log_pass "Tests directory found"
    else
        log_fail "Tests directory not found"
    fi
}

check_database_connectivity() {
    section_header "Database Connectivity"
    
    # Load .env if it exists
    if [ -f ".env" ]; then
        export $(cat .env | grep -v '^#' | xargs)
    fi
    
    DB_HOST="${DATABASE_URL:-localhost}"
    DB_PORT="${DATABASE_PORT:-5432}"
    DB_USER="${DATABASE_USER:-postgres}"
    
    if command -v psql &> /dev/null; then
        if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -c "SELECT 1" &> /dev/null; then
            log_pass "Database connection successful ($DB_HOST:$DB_PORT)"
        else
            log_warn "Cannot connect to database at $DB_HOST:$DB_PORT"
        fi
    else
        log_info "PostgreSQL client not available, skipping database test"
    fi
}

check_python_packages() {
    section_header "Python Package Checks"
    
    if [ ! -d "venv" ]; then
        log_warn "Virtual environment not activated. Cannot check packages."
        return
    fi
    
    # Activate venv
    source venv/bin/activate 2>/dev/null || . venv/Scripts/activate 2>/dev/null || true
    
    # Check critical packages
    PACKAGES=("fastapi" "sqlalchemy" "pytest" "pydantic")
    
    for package in "${PACKAGES[@]}"; do
        if python3 -c "import $package" 2>/dev/null; then
            VERSION=$(python3 -c "import $package; print(getattr($package, '__version__', 'unknown'))" 2>/dev/null)
            log_pass "$package installed (version: $VERSION)"
        else
            log_warn "$package not installed"
        fi
    done
}

check_network_connectivity() {
    section_header "Network Connectivity"
    
    # Check internet connectivity
    if ping -c 1 8.8.8.8 &> /dev/null; then
        log_pass "Internet connectivity available"
    else
        log_warn "No internet connectivity (may affect package downloads)"
    fi
    
    # Check DNS
    if nslookup google.com &> /dev/null; then
        log_pass "DNS resolution working"
    else
        log_warn "DNS resolution issues detected"
    fi
}

check_port_availability() {
    section_header "Port Availability"
    
    PORTS=(8000 8001 5432 3000 3001 9090 3306)
    
    for port in "${PORTS[@]}"; do
        if lsof -i ":$port" &> /dev/null 2>&1 || nc -z localhost "$port" &> /dev/null 2>&1; then
            log_warn "Port $port is already in use"
        else
            log_pass "Port $port is available"
        fi
    done
}

check_deployment_files() {
    section_header "Deployment Files"
    
    # Check for docker-compose files
    if [ -f "docker-compose.yml" ]; then
        log_pass "docker-compose.yml found"
    else
        log_warn "docker-compose.yml not found"
    fi
    
    # Check for deployment scripts
    if [ -f "scripts/database_migration.sh" ]; then
        log_pass "Database migration script found"
    else
        log_warn "Database migration script not found"
    fi
    
    # Check documentation
    if [ -f "doc/PHASE_6_DEPLOYMENT_SCRIPTS.md" ]; then
        log_pass "Deployment documentation found"
    else
        log_warn "Deployment documentation not found"
    fi
}

################################################################################
# MAIN EXECUTION
################################################################################

main() {
    echo ""
    echo "╔════════════════════════════════════════════════════════════════╗"
    echo "║           SentinelCV Pre-Deployment Health Check               ║"
    echo "║                    $(date '+%Y-%m-%d %H:%M:%S')                    ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    
    check_system_requirements
    check_dependencies
    check_application_setup
    check_database_connectivity
    check_python_packages
    check_network_connectivity
    check_port_availability
    check_deployment_files
    
    # Summary
    section_header "Summary"
    echo ""
    echo -e "Checks Passed:  ${GREEN}$CHECKS_PASSED${NC}"
    echo -e "Checks Failed:  ${RED}$CHECKS_FAILED${NC}"
    echo -e "Warnings:       ${YELLOW}$WARNINGS${NC}"
    echo ""
    
    if [ $CHECKS_FAILED -eq 0 ]; then
        echo -e "${GREEN}✓ System is ready for deployment!${NC}"
        return 0
    else
        echo -e "${RED}✗ System is NOT ready for deployment. Please fix the above issues.${NC}"
        return 1
    fi
}

main "$@"
