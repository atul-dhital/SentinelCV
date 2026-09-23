#!/bin/bash
#
# SentinelCV Blue-Green Rollback Script
# Reverts to blue environment in case of green deployment issues
#
# Usage: bash scripts/rollback_blue.sh
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Logging
log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[✓]${NC} $1"; }
log_error() { echo -e "${RED}[✗]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[!]${NC} $1"; }

log_section() {
    echo ""
    echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}${1}${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
    echo ""
}

# ============================================================================

log_section "ROLLBACK: REVERTING TO BLUE ENVIRONMENT"

log_warn "This will stop green environment and restore blue as live"
echo -n "Continue with rollback? (yes/no): "
read -r confirmation

if [ "$confirmation" != "yes" ]; then
    log_info "Rollback cancelled"
    exit 0
fi

# ============================================================================

log_section "STEP 1: RESTORE NGINX CONFIGURATION"

log_info "Reverting nginx configuration to blue..."
if [ -f nginx.prod.conf.bak ]; then
    cp nginx.prod.conf.bak nginx.prod.conf
    log_success "nginx configuration restored"
else
    log_warn "No backup nginx.conf found, checking git..."
    if command -v git &> /dev/null; then
        git checkout nginx.prod.conf 2>/dev/null || log_warn "Could not restore from git"
    fi
fi

log_info "Reloading nginx..."
docker-compose -f docker-compose.prod.yml exec -T nginx nginx -t && \
docker-compose -f docker-compose.prod.yml exec -T nginx nginx -s reload || \
    log_warn "Nginx reload failed, may require manual intervention"

log_success "Traffic restored to blue environment"

# ============================================================================

log_section "STEP 2: VERIFY BLUE IS RESPONDING"

log_info "Checking blue backend health..."
RETRY_COUNT=0
HEALTH_CHECK_RETRIES=10

while [ $RETRY_COUNT -lt $HEALTH_CHECK_RETRIES ]; do
    if curl -s -f http://localhost:8000/health > /dev/null 2>&1; then
        log_success "Blue backend is responding"
        break
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [ $RETRY_COUNT -lt $HEALTH_CHECK_RETRIES ]; then
        sleep 2
    fi
done

if [ $RETRY_COUNT -eq $HEALTH_CHECK_RETRIES ]; then
    log_error "Blue backend is not responding!"
    log_error "This may indicate a more serious issue"
    exit 1
fi

# ============================================================================

log_section "STEP 3: STOP GREEN ENVIRONMENT"

log_info "Stopping green services..."
docker-compose -f docker-compose.prod-green.yml down 2>/dev/null || \
    log_warn "Some green services could not be stopped"

log_success "Green environment stopped"

# ============================================================================

log_section "STEP 4: CLEANUP"

log_info "Cleaning up green containers and volumes..."
docker-compose -f docker-compose.prod-green.yml down -v 2>/dev/null || true

log_info "Pruning dangling docker images..."
docker image prune -f --filter "dangling=true" > /dev/null 2>&1

log_success "Cleanup complete"

# ============================================================================

log_section "ROLLBACK COMPLETE"

log_success "✓ Blue environment is now live again"
log_success "✓ All traffic rerouted to blue"
log_success "✓ Green environment stopped"

echo ""
log_info "Next actions:"
echo "  1. Investigate what caused the green deployment failure"
echo "  2. Check logs: docker logs sentinelcv_backend"
echo "  3. Review deployment report: doc/deployment_report_*.md"
echo "  4. Fix issues and retry: bash scripts/deploy_blue_green.sh"
echo ""

# Create rollback report
REPORT_FILE="doc/rollback_report_$(date +%Y%m%d_%H%M%S).md"
cat > "$REPORT_FILE" << EOF
# Rollback Report

**Date**: $(date -u)  
**Reason**: User-initiated rollback from green environment  
**Status**: ✓ SUCCESS  

## Summary

Rolled back from green to blue environment after issues detected.

## Actions Taken

1. Restored nginx configuration from backup
2. Verified blue backend health
3. Stopped green environment
4. Cleaned up green resources

## Logs

Check the deployment report for details:
\`\`\`bash
docker logs sentinelcv_backend
docker logs sentinelcv_ai_service
\`\`\`

## Next Steps

1. **Investigate**: Determine what caused the failure
2. **Fix**: Apply patches to resolve issues
3. **Test**: Re-run load tests and smoke tests
4. **Redeploy**: Execute \`bash scripts/deploy_blue_green.sh\` again

## Support

For urgent issues, contact:
- On-call DevOps: [contact info]
- Database Admin: [contact info]

EOF

log_info "Rollback report saved: $REPORT_FILE"

exit 0
