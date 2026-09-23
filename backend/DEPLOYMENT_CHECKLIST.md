# SentinelCV Deployment Checklist
## Quick Reference for THIS WEEK (April 1-5, 2026)

---

## ✅ PRE-DEPLOYMENT TASKS

### Production-Ready Optimizations (Completed June 8, 2026)

**Performance & Architecture** ✅
- [x] N+1 Query Prevention: 43 Organization relationships hardened with `lazy="raise"`
- [x] Memory Leak Prevention: WebSocket sessions have 1-hour TTL + automatic cleanup
- [x] Query Bounds: 110 ORM queries bounded with `.limit()` (prevents OOM on large result sets)
- [x] Frontend Modularization: 7 modular service files with ~60% bundle reduction
- [x] Performance Testing: Infrastructure for memory profiling and latency measurement
- [x] SQL Safety: 2 raw SQL queries verified safe with proper bounds

**Verification**:
```powershell
# Verify optimizations
python backend/scripts/audit_raw_sql.py         # SQL safety check
python backend/scripts/performance_test.py      # Performance baseline
```

### Monday, April 1
```
TASK 1: PostgreSQL Setup (9:00 AM - 12:00 PM)
  [x] Pull production database backup
  [x] Run: python scripts/setup_postgres_production.py --host [DB_HOST] --password [PWD]
  [x] Verify: SELECT COUNT(*) FROM pg_indexes WHERE indexname LIKE 'idx_visitors_embedding%';
  [x] Verify latency: < 200ms for vector search

TASK 2: Environment Configuration (1:00 PM - 3:00 PM)
  [x] Copy: cp .env.production.example .env.production
  [x] Edit .env.production with production values
  [x] Run: python scripts/validate_env.py --env-file .env.production
  [x] Verify: All checks pass (exit code 0)

TASK 3: Connection Pool (3:00 PM - 4:30 PM)
  [x] Check: grep -n "pool_size\|max_overflow" backend/db/base.py
  [x] Verify: pool_size=20, max_overflow=10
  [x] Status: Already configured ✓
```

### Tuesday, April 2
```
TASK 4: Secrets Management (Full Day - 8 Hours)
  [ ] Option A - Encrypted .env:
        [ ] python scripts/manage_encrypted_env.py generate-key --out .env.key
        [ ] python scripts/manage_encrypted_env.py encrypt --in .env.production --out .env.production.encrypted --key-file .env.key
        [ ] Store key safely (AWS Secrets Manager/Vault/SENTINELCV_ENV_KEY)
        [ ] Verify decrypt: python scripts/manage_encrypted_env.py decrypt --in .env.production.encrypted --out .env.production --key-file .env.key
        [ ] Set runtime vars: SENTINELCV_ENCRYPTED_ENV_FILE=.env.production.encrypted and SENTINELCV_ENV_KEY_FILE=.env.key
  
  [ ] Option B - HashiCorp Vault:
        [ ] docker run -d -p 8200:8200 vault
        [ ] vault operator init -key-shares=1 -key-threshold=1
        [ ] vault kv put secret/sentinelcv/prod DATABASE_URL="..." SECRET_KEY="..."
        [ ] Update backend to read from Vault

  [ ] Verify: grep -r "password=" backend/ → should return 0 matches
```

### Wednesday, April 3
```
TASK 5: Pre-Deployment Checks (Full Day - 6 Hours)
  [ ] Make script executable: chmod +x scripts/pre_deployment_check.sh
  [ ] Run: bash scripts/pre_deployment_check.sh
  [ ] All checks should PASS
  [ ] Summary: PASSED: 45/45, FAILED: 0/45, WARNINGS: 0/0
  [ ] Exit code should be 0
```

### Thursday, April 4
```
TASK 6: Load Testing (Full Day - 6 Hours)
  [ ] Install: pip install locust
  [ ] Ensure backend running locally or on staging
  [ ] Run: locust -f scripts/load_test.py \
              --host=http://localhost:8000 \
              --users=100 \
              --spawn-rate=10 \
              --run-time=10m \
              --headless
  [ ] Verify Results:
      [ ] p95 latency < 500ms
      [ ] Throughput > 50 req/sec
      [ ] Error rate < 0.5%
      [ ] No connection pool exhaustion
  [ ] Save report: backend/load_test_results_[TIMESTAMP].json
```

### Friday, April 5 - DEPLOYMENT DAY
```
MORNING: Blue-Green Deployment (9:00 AM - 10:45 AM)
  [ ] Pre-flight checks:
        [ ] Backup blue database: pg_dump $DATABASE_URL > backup_blue_$(date +%s).sql
        [ ] Verify 50GB+ disk space available
        [ ] Verify docker images available
  
  [ ] Run deployment:
        [ ] chmod +x scripts/deploy_blue_green.sh
        [ ] bash scripts/deploy_blue_green.sh
  
  [ ] Monitor deployment:
        [ ] Watch logs: docker logs -f sentinelcv_backend_green
        [ ] Check metrics: curl http://localhost:9090/api/v1/query?query=http_requests_total
        [ ] Verify error rate during switch: < 5% for 1 min
  
  [ ] Deployment complete time: __________ (should be < 37 min)

MID-MORNING: Verification (10:45 AM - 12:00 PM)
  [ ] Run verification:
        [ ] python scripts/post_deployment_verify.py \
              --api-url https://sentinelcv.com \
              --save-report docs/deployment_verification_[DATE].json
  
  [ ] Check Results:
        [ ] ✓ Health endpoint OK
        [ ] ✓ Database connected
        [ ] ✓ API endpoints responding
        [ ] ✓ WebSocket working (or ⊘ skipped if not configured)
        [ ] ✓ HTTPS/SSL valid
        [ ] All Critical APIs: PASS

AFTERNOON: Continuous Monitoring (12:00 PM - 5:00 PM)
  [ ] Monitor error rates:
        [ ] docker logs sentinelcv_backend | grep ERROR
        [ ] curl http://localhost:9090/api/v1/query?query='rate(http_requests_total{status="500"}[1m])'
  
  [ ] Monitor latency:
        [ ] tail -f /var/log/postgresql/postgresql.log | grep duration
        [ ] curl http://localhost:9090/api/v1/query?query=histogram_quantile
  
  [ ] Monitor resources:
        [ ] docker stats sentinelcv_backend
        [ ] df -h | grep /var/lib/postgresql
        [ ] redis-cli INFO memory | grep used_memory_human
  
  [ ] If issues:
        [ ] Execute: bash scripts/rollback_blue.sh
        [ ] Investigate root cause
        [ ] Log in: docs/deployment_report_[TIMESTAMP].md
        [ ] Prepare for retry next week

SIGN-OFF (End of Day)
  [ ] Tech Lead approval: __________ (Date/Time)
  [ ] QA Lead approval: __________ (Date/Time)
  [ ] Product Owner approval: __________ (Date/Time)
  [ ] Announce to team
  [ ] Log completion
```

---

## 🚨 EMERGENCY ROLLBACK

If green deployment fails or shows critical issues:
```bash
bash scripts/rollback_blue.sh
# Expected time: < 1 minute
# Result: Blue environment restored as live
```

---

## 📊 SUCCESS CRITERIA

After deployment, verify all metrics:

| Metric | Target | Status |
|--------|--------|--------|
| Vector search latency (p95) | <200ms | [ ] |
| API response latency (p95) | <500ms | [ ] |
| Error rate | <0.5% | [ ] |
| Database pool size | 20 | [ ] |
| Deployment time | <37 min | [ ] |
| Downtime | 0 min | [ ] |
| Rollback time | <1 min | [ ] |
| Health check pass | 100% | [ ] |
| Post-deploy tests | All pass | [ ] |

---

## 📞 CONTACTS

**During Deployment Keep These Handy:**
- Lead DevOps: ________________
- DB Admin: ________________
- Backend Lead: ________________
- On-Call: ________________

**If Escalation Needed:**
- Manager: ________________
- VP Engineering: ________________

---

## 📋 REFERENCE DOCUMENTS

| Document | Purpose | Location |
|----------|---------|----------|
| Day-by-Day Guide | Detailed execution plan | `THIS_WEEK_IMPLEMENTATION_GUIDE.md` |
| Full Summary | Complete overview | `THIS_WEEK_SUMMARY_READY_TO_EXECUTE.md` |
| Progress Tracker | 367-hour roadmap | `IMPLEMENTATION_PROGRESS_TRACKER.md` |
| Architecture | System design | `DEVELOPMENT_STATUS.md` |
| Operations | Standard procedures | `OPERATIONAL_RUNBOOK.md` |

---

## ✅ SIGN-OFF

```
Deployment Team Lead: ________________     Date: ____________

QA Lead: ________________                  Date: ____________

Product Owner: ________________            Date: ____________

Notes:
_________________________________________________________________
_________________________________________________________________
_________________________________________________________________
```

---

**This Week Complete? Mark Today's Date: ______________**

**Ready for Q2 (May 2026)? YES ☐  NO ☐**

Next phase: YOLO11 Upgrade (32 hours, May 2026)
