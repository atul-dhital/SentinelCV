# SentinelCV — All Features Green Roadmap

## Purpose

This document converts the current SentinelCV feature audit into an implementation roadmap. The goal is to move every module from **implemented, partial, experimental, runtime-dependent, or misconfigured** to a verifiable **green** status.

A feature must not be marked green simply because a page, API route, database table, or service class exists. It becomes green only after the full workflow works from the UI to the backend, database, AI runtime, storage, security controls, tests, and production configuration.

---

# 1. Definition of Green

A module can be marked **GREEN** only when all applicable items below are complete.

- [ ] Frontend page exists and is accessible to the correct role.
- [ ] Frontend calls the correct active backend endpoint.
- [ ] Backend route is mounted in the default production configuration.
- [ ] Authentication and role authorization are enforced in the backend.
- [ ] Organization or tenant isolation is verified.
- [ ] Request validation and useful error messages are implemented.
- [ ] Required database tables and Alembic migrations exist.
- [ ] Required AI model or external service is available.
- [ ] The feature fails safely when its dependency is unavailable.
- [ ] Files and biometric media are stored and served securely.
- [ ] Audit logs are written for sensitive operations.
- [ ] Unit tests pass.
- [ ] Integration tests pass.
- [ ] End-to-end UI testing passes.
- [ ] Performance is measured for the expected workload.
- [ ] Health and readiness endpoints report the real feature state.
- [ ] Documentation matches the current code.
- [ ] No fake, synthetic, random, or weak fallback is used in production.

---

# 2. Status Labels to Use During Development

| Status | Meaning |
|---|---|
| RED | Missing, broken, unsafe, or not connected |
| ORANGE | Partially implemented or major dependency missing |
| YELLOW | Works locally but has incomplete tests, security, or production configuration |
| GREEN | Fully implemented and verified using the green definition |

---

# 3. Recommended Work Order

Complete the work in this sequence.

1. **Phase 0 — Establish project truth and testing baseline**
2. **Phase 1 — Fix production-critical security and configuration issues**
3. **Phase 2 — Complete and verify all core modules**
4. **Phase 3 — Complete runtime-dependent AI modules**
5. **Phase 4 — Complete experimental Phase 3 modules**
6. **Phase 5 — Production validation, performance, UAT, and documentation**

Do not start by completing every experimental AI feature. First make the core visitor tracking system stable, secure, testable, and production-ready.

---

# 4. Phase 0 — Establish Project Truth and Baseline

## 4.1 Create one canonical feature registry

Create a new file:

```text
docs/project-truth/feature-status.md
```

For every feature, record:

- Feature name
- Frontend page
- Frontend API service
- Backend route file
- Database tables
- External dependencies
- Required environment variables
- Current status
- Test coverage
- Known issues
- Green acceptance criteria

### Required action

- [ ] Stop using archived documents as current truth.
- [ ] Treat `docs/project-truth/` as the only canonical documentation location.
- [ ] Mark every route as core, optional, experimental, deprecated, or duplicated.
- [ ] Mark which features are enabled in the default production configuration.

### Green acceptance criteria

- [ ] Every visible navigation item maps to a mounted backend route.
- [ ] Every backend feature has a documented owner file and test file.
- [ ] No archived document is being used as the current implementation source.

---

## 4.2 Create a full automated test baseline

Run and record the current results before changing functionality.

Suggested commands from the `Code` directory:

```bash
python -m pytest backend/tests -q
```

```bash
cd frontend
npm ci
npm run lint
npm test -- --runInBand
npm run build
```

If the exact frontend test script differs, use the scripts defined in `frontend/package.json`.

### Required action

- [ ] Save the initial failing-test list.
- [ ] Group failures by module.
- [ ] Do not hide or delete failing tests without replacing them.
- [ ] Add CI jobs for backend tests, frontend tests, lint, type checking, and production build.

### Green acceptance criteria

- [ ] Backend tests pass.
- [ ] Frontend tests pass.
- [ ] Frontend production build passes.
- [ ] CI blocks merging when any required check fails.

---

# 5. Phase 1 — Production-Critical Fixes

## 5.1 Fix navigation and backend route mismatches

### Current problem

Some normal navigation pages call Phase 3 endpoints that are disabled by default. This can create a visible page that always returns `404 Not Found`.

Affected pages include:

- Sentiment Analysis / Emotion and Action Recognition
- Security page using Phase 3 security endpoints

### Required action

Choose one approach for each page.

#### Preferred approach for incomplete features

- [ ] Move the page into the **AI Lab** navigation group.
- [ ] Add an `Experimental` badge.
- [ ] Hide the page unless the matching feature flag is enabled.
- [ ] Show a dependency status panel before allowing use.

#### Preferred approach for core security features

Refactor the Security page to use stable core routes:

- LDAP: `/api/v1/ldap/...`
- GDPR and retention: `/api/v1/compliance/...` or the selected canonical GDPR API
- Audit report: `/api/v1/reports/audit/pdf` or the selected stable report endpoint
- Encryption verification: `/api/v1/compliance/encryption-verify`

### Files to review

```text
frontend/src/components/Navbar.tsx
frontend/src/app/emotion/page.tsx
frontend/src/app/security/page.tsx
frontend/src/services/api.ts
backend/main.py
backend/api/phase3_complete_api_scaffold.py
```

### Green acceptance criteria

- [ ] No visible page calls an unmounted route.
- [ ] Feature flags control both frontend visibility and backend mounting.
- [ ] Disabled features show a clear unavailable state instead of a generic 404.
- [ ] Route-mapping integration tests cover every main navigation page.

---

## 5.2 Enforce real face recognition in production

### Current problem

The face engine can fall back to a weak grayscale-pixel embedding when real ArcFace, AdaFace, or another valid recognition backend is unavailable.

### Required action

Production environment:

```env
SENTINELCV_STRICT_RECOGNITION=1
```

Also add a production-startup guard:

- [ ] Read the recognition-engine health status.
- [ ] Fail readiness when `real_recognition` is false.
- [ ] Do not allow face enrolment when the engine is degraded.
- [ ] Do not allow recognition jobs to process using the weak fallback.
- [ ] Display the active recognition backend in the admin health panel.

### Files to review

```text
ai_services/face_engine.py
ai_services/processor.py
backend/main.py
backend/api/models_api.py
frontend/src/app/page.tsx
```

### Green acceptance criteria

- [ ] Production refuses to start or becomes unready without a real recognition backend.
- [ ] New visitor enrolment fails closed when the real model is unavailable.
- [ ] Health response identifies ArcFace, AdaFace, ViT, or approved ensemble.
- [ ] No fallback embedding is stored in the production gallery.
- [ ] Tests verify strict and non-strict modes.

---

## 5.3 Secure all internal service endpoints

### Required action

Review all routes intended for AI services, background workers, and devices.

Examples:

- Internal log ingestion
- Internal notification creation
- Visitor embedding search
- Edge-device events
- Heartbeats
- Embedding synchronization

Implement:

- [ ] Required `X-Internal-API-Key` or dedicated service-token authentication.
- [ ] Constant-time secret comparison.
- [ ] Key rotation support.
- [ ] Rate limiting.
- [ ] Organization validation.
- [ ] Audit logging.
- [ ] Clear 401 or 403 responses for missing or invalid credentials.
- [ ] Clear startup error when the required service secret is missing.

### Green acceptance criteria

- [ ] No internal-write endpoint is anonymously callable.
- [ ] Missing internal secrets fail startup or readiness.
- [ ] Tests verify valid, invalid, missing, expired, and rotated keys.

---

## 5.4 Select one canonical API for duplicated modules

### Duplicated or overlapping areas

- `camera.py` and `cameras.py`
- `sso.py` and `sso_api.py`
- `compliance.py` and `gdpr_api.py`
- Core integrations and Phase 3 integrations
- Core LDAP and Phase 3 security LDAP configuration

### Required action

For each duplicate pair:

- [ ] Select the canonical route family.
- [ ] Update the frontend to use only the canonical route.
- [ ] Add deprecation warnings to the old route.
- [ ] Add compatibility redirects only when safe.
- [ ] Remove the deprecated route after all callers and tests are migrated.
- [ ] Update project-truth documentation.

### Green acceptance criteria

- [ ] One clear API route family exists per business function.
- [ ] No frontend service calls a deprecated API.
- [ ] Duplicate models and schemas are removed or clearly separated.

---

## 5.5 Lock production database behavior

### Required action

- [ ] Use PostgreSQL in production.
- [ ] Install and verify `pgvector`.
- [ ] Add and verify the vector index for face embeddings.
- [ ] Run all Alembic migrations.
- [ ] Prevent silent fallback to SQLite in production.
- [ ] Add database backup and restore procedures.
- [ ] Add tenant-isolation integration tests.
- [ ] Test all analytics and reports on PostgreSQL, not only SQLite.

Suggested production guard:

```env
SENTINELCV_ENV=production
ENFORCE_TENANT_FILTER=1
```

### Green acceptance criteria

- [ ] Production readiness fails when PostgreSQL is unavailable.
- [ ] Production readiness fails when pgvector is unavailable.
- [ ] Vector-search performance is measured with realistic data volume.
- [ ] Backup restore is tested.
- [ ] Cross-organization access tests all fail as expected.

---

# 6. Phase 2 — Complete and Verify Core Modules

# 6.1 Authentication and session management

## Required work

- [ ] Verify login, registration, refresh, logout, forgot password, and reset password.
- [ ] Verify refresh-token rotation and reuse detection.
- [ ] Revoke all sessions after password reset when required.
- [ ] Add account lockout or increasing delay after repeated failed attempts.
- [ ] Add session-management UI showing active sessions.
- [ ] Allow an administrator or user to revoke a selected session.
- [ ] Verify secure cookie settings in HTTPS production.
- [ ] Add tests for token expiry, rotation, revocation, and replay.

## Green acceptance criteria

- [ ] No access token is stored in local storage.
- [ ] Refresh cookie is HttpOnly, Secure, and correctly scoped.
- [ ] A rotated or revoked refresh token cannot be reused.
- [ ] Password-reset emails work in the deployment environment.

---

# 6.2 Role-based access control

## Required work

Create a permission matrix covering:

- Admin
- Staff
- Optional reviewer
- Optional auditor
- Edge device
- Internal service

Then verify every backend route.

- [ ] Add centralized permission helpers.
- [ ] Do not rely on frontend role checks.
- [ ] Add negative authorization tests for every mutation route.
- [ ] Verify users cannot modify another organization.
- [ ] Decide whether staff may list all organization users.

## Green acceptance criteria

- [ ] Every sensitive route has a documented permission.
- [ ] All unauthorized-role tests return 403.
- [ ] All cross-tenant tests return 404 or 403 without leaking existence.

---

# 6.3 Organization management

## Required work

- [ ] Validate organization name uniqueness.
- [ ] Complete settings for threshold, retention, notifications, and timezone.
- [ ] Add organization usage statistics.
- [ ] Add organization export and deletion workflow.
- [ ] Test organization-level settings in AI matching and data cleanup.

## Green acceptance criteria

- [ ] Updating an organization setting changes actual runtime behavior.
- [ ] Threshold changes affect recognition decisions.
- [ ] Retention changes affect cleanup scheduling.

---

# 6.4 User management

## Required work

- [ ] User list, create, edit, activate, deactivate, and delete.
- [ ] Invite-user email workflow.
- [ ] Password-set or password-reset workflow for invited users.
- [ ] Prevent last-admin deletion or deactivation.
- [ ] Add role-change audit logs.
- [ ] Add pagination and search.

## Green acceptance criteria

- [ ] Last active administrator cannot be removed.
- [ ] Invite and activation flow works end to end.
- [ ] All user mutations are audited.

---

# 6.5 Visitor management

## Required work

- [ ] Verify create, read, update, deactivate, delete, search, export, and bulk import.
- [ ] Validate email and phone formats.
- [ ] Resolve `visitor_metadata` and API `metadata` naming drift.
- [ ] Add duplicate-visitor detection.
- [ ] Define hard-delete versus soft-delete rules.
- [ ] Confirm deletion removes linked media and embeddings.
- [ ] Add import preview, validation report, and failed-row download.

## Green acceptance criteria

- [ ] Bulk import never partially corrupts visitor data.
- [ ] Visitor deletion follows retention and legal rules.
- [ ] Duplicate detection gives a review option before creation.
- [ ] Search remains fast at the target visitor count.

---

# 6.6 Face enrolment

## Required work

- [ ] Verify single-image enrolment.
- [ ] Verify multi-image enrolment.
- [ ] Verify webcam capture.
- [ ] Verify enrolment-video frame extraction.
- [ ] Verify face-angle labels.
- [ ] Add minimum face-size validation.
- [ ] Add brightness, occlusion, and pose validation.
- [ ] Prevent multiple faces in one enrolment image.
- [ ] Add duplicate-face detection across visitors.
- [ ] Add progress UI for asynchronous jobs.
- [ ] Delete stored files when DB writes fail.
- [ ] Delete DB rows when file storage fails.

## Green acceptance criteria

- [ ] Only valid, real-model embeddings are saved.
- [ ] Failed enrolment leaves no orphaned file or DB record.
- [ ] Every enrolled image has quality, angle, model, and timestamp metadata.
- [ ] Duplicate identity enrolment produces a warning.

---

# 6.7 Camera registry and RTSP

## Required work

- [ ] Verify add, edit, delete, group, test, health, and snapshot.
- [ ] Encrypt camera credentials.
- [ ] Mask RTSP passwords in logs and UI.
- [ ] Validate allowed RTSP schemes.
- [ ] Add configurable reconnection policy.
- [ ] Add timeout and exponential backoff.
- [ ] Add offline alerts.
- [ ] Test multiple simultaneous cameras.
- [ ] Add camera FPS and resolution monitoring.
- [ ] Add stream latency metrics.

## Green acceptance criteria

- [ ] Camera passwords never appear in logs or API responses.
- [ ] A disconnected camera reconnects automatically.
- [ ] Offline state appears in the dashboard and alert system.
- [ ] Target concurrent-camera count passes soak testing.

---

# 6.8 Uploaded-video processing

## Required work

- [ ] Validate file type using file content, not extension alone.
- [ ] Add maximum upload size and duration checks.
- [ ] Extract and store video metadata.
- [ ] Add queue retry, timeout, cancel, and dead-letter behavior.
- [ ] Add progress percentage.
- [ ] Add idempotency to prevent duplicate jobs.
- [ ] Clean temporary files after completion or failure.
- [ ] Verify in-process and Redis queue modes.

## Green acceptance criteria

- [ ] Failed jobs can be retried safely.
- [ ] Duplicate submissions do not duplicate detection logs.
- [ ] User can see queued, running, completed, failed, and cancelled states.
- [ ] Temporary files are removed according to policy.

---

# 6.9 Person detection and tracking

## Required work

- [ ] Select and freeze the production YOLO model.
- [ ] Store model name and version in every processing job.
- [ ] Benchmark CPU and GPU performance.
- [ ] Test ByteTrack under occlusion and re-entry.
- [ ] Tune confidence, IoU, and tracking thresholds.
- [ ] Add recorded benchmark videos.
- [ ] Compare YOLOv8, YOLO11, or selected production model.
- [ ] Remove unsupported model names from production configuration.

## Green acceptance criteria

- [ ] Detection precision and recall meet documented targets.
- [ ] Tracking ID-switch rate is measured.
- [ ] Processing FPS meets the deployment target.
- [ ] Health endpoint reports the exact loaded detector and tracker.

---

# 6.10 Face recognition

## Required work

- [ ] Select the official recognition model: ArcFace, AdaFace, ViT, or approved ensemble.
- [ ] Freeze model artifact and checksum.
- [ ] Store embedding model version with each embedding.
- [ ] Block matching embeddings from incompatible model versions.
- [ ] Create migration or re-enrolment strategy when changing model.
- [ ] Benchmark true-positive and false-positive rates.
- [ ] Tune thresholds using a validation dataset.
- [ ] Test demographic and lighting variation.
- [ ] Add top-K candidate review to manual review UI.

## Green acceptance criteria

- [ ] False-accept and false-reject rates are documented.
- [ ] Thresholds are based on test data, not guesses.
- [ ] Every recognition result records model version and threshold.
- [ ] Weak fallback mode is impossible in production.

---

# 6.11 Detection logs and manual review

## Required work

- [ ] Verify log list, detail, filtering, export, assignment, confirmation, and create-visitor flow.
- [ ] Define log immutability rules.
- [ ] Separate raw detection facts from reviewer decisions.
- [ ] Keep a complete review-history table.
- [ ] Record before and after values.
- [ ] Add bulk review actions.
- [ ] Add reason codes for correction.
- [ ] Add top recognition candidates.

## Green acceptance criteria

- [ ] Raw detection evidence cannot be silently overwritten.
- [ ] Every correction is attributable to a user and timestamp.
- [ ] Manual correction can optionally create an approved learning signal.

---

# 6.12 Realtime dashboard and WebSocket

## Required work

- [ ] Verify token-based WebSocket authentication.
- [ ] Verify organization scoping.
- [ ] Add reconnect backoff.
- [ ] Add heartbeat and stale-connection cleanup.
- [ ] Prevent duplicate realtime events.
- [ ] Add event ordering or event IDs.
- [ ] Add WebSocket load tests.

## Green acceptance criteria

- [ ] A user never receives another organization’s event.
- [ ] Reconnection does not duplicate events.
- [ ] Stale sessions are removed automatically.
- [ ] Dashboard remains responsive at the target event rate.

---

# 6.13 Alerts and notifications

## Required work

- [ ] Verify rule CRUD and activation.
- [ ] Add conditions for unknown person, spoof attempt, camera offline, watchlist match, repeated access, and system failure.
- [ ] Add delivery channels: in-app, email, webhook, and optional SMS.
- [ ] Add delivery retries and failure logs.
- [ ] Add notification deduplication and cooldown.
- [ ] Add user preferences.
- [ ] Add alert acknowledgement and resolution workflow.

## Green acceptance criteria

- [ ] Test events produce the expected alert exactly once.
- [ ] Failed external delivery is retried and recorded.
- [ ] Users can acknowledge and resolve alerts.

---

# 6.14 Analytics

## Required work

- [ ] Define every metric and its calculation.
- [ ] Verify organization filters in all analytics queries.
- [ ] Add timezone handling.
- [ ] Add empty-data states.
- [ ] Add date-range comparison.
- [ ] Add query performance tests.
- [ ] Cache expensive aggregates safely.
- [ ] Separate verified metrics from experimental analytics.

## Green acceptance criteria

- [ ] Analytics totals match direct database queries.
- [ ] Timezone and date-range results are correct.
- [ ] Core analytics do not depend on experimental services.

---

# 6.15 Reports and exports

## Required work

- [ ] Verify visitor, analytics, audit, and liveness PDFs.
- [ ] Add organization name and report generation metadata.
- [ ] Add applied filters to the report.
- [ ] Add page numbers and consistent layout.
- [ ] Verify Unicode and long text.
- [ ] Verify large exports.
- [ ] Add background report generation for large datasets.

## Green acceptance criteria

- [ ] Report totals match the UI and database.
- [ ] Reports contain no cross-organization data.
- [ ] Generated files open correctly and have readable formatting.

---

# 6.16 Audit logging

## Required work

- [ ] Define mandatory audited actions.
- [ ] Include user, organization, IP, user agent, action, entity, timestamp, and details.
- [ ] Prevent audit-log modification by normal users.
- [ ] Add append-only external storage or SIEM forwarding.
- [ ] Add audit-log export.
- [ ] Add retention rules that do not remove legally required records.

## Green acceptance criteria

- [ ] Every sensitive operation has an audit entry.
- [ ] Audit records cannot be edited using normal application APIs.
- [ ] External append-only audit copy is verified.

---

# 6.17 Compliance, GDPR, consent, and retention

## Required work

- [ ] Select one canonical GDPR API.
- [ ] Implement data export with all visitor-linked records.
- [ ] Implement verified deletion workflow.
- [ ] Add legal-hold support.
- [ ] Add consent version, source, timestamp, and withdrawal.
- [ ] Add scheduled retention cleanup.
- [ ] Add deletion preview and audit report.
- [ ] Verify deletion of files, embeddings, logs, and derived artifacts according to policy.

## Green acceptance criteria

- [ ] Export includes all applicable personal data.
- [ ] Deletion removes or anonymizes all required data.
- [ ] Legal holds prevent prohibited deletion.
- [ ] Consent withdrawal changes future processing behavior.

---

# 6.18 Webhooks and API keys

## Required work

- [ ] Hash stored API keys.
- [ ] Show a new key secret only once.
- [ ] Add scopes and expiration.
- [ ] Add key rotation.
- [ ] Sign webhook payloads.
- [ ] Add delivery retries and dead-letter handling.
- [ ] Add webhook event versioning.
- [ ] Prevent SSRF to unsafe targets.

## Green acceptance criteria

- [ ] Stored API keys cannot be recovered from the database.
- [ ] Webhook receiver can verify the signature.
- [ ] Failed deliveries can be inspected and replayed.

---

# 6.19 System health and observability

## Required work

Health must report:

- Backend status
- Database status
- pgvector status
- Redis status
- Queue status
- Storage status
- AI service status
- Detector model
- Tracker model
- Recognition model
- Recognition degraded status
- Liveness model and fallback status
- SMTP status
- Webhook worker status

Also implement:

- [ ] Prometheus metrics.
- [ ] Structured logs.
- [ ] Correlation IDs.
- [ ] Error tracking.
- [ ] Alerting for service failure.

## Green acceptance criteria

- [ ] Readiness becomes unhealthy when a required production dependency fails.
- [ ] Optional dependencies are reported as degraded, not hidden.
- [ ] Admin can see the exact active model and artifact version.

---

# 7. Phase 3 — Runtime-Dependent AI Modules

# 7.1 Liveness and anti-spoofing

## Required work

- [ ] Decide whether liveness is passive, active challenge-based, or both.
- [ ] Add a real tested ONNX liveness model.
- [ ] Keep texture, motion, chrominance, spectral, and Moiré analysis as supporting signals.
- [ ] Clearly report when CNN inference is unavailable.
- [ ] Create a spoof test dataset containing print, phone replay, tablet replay, mask, low light, blur, and partial face.
- [ ] Calibrate thresholds.
- [ ] Test false rejection of real users.
- [ ] Add challenge expiry and replay protection.

## Green acceptance criteria

- [ ] Real, print, replay, and mask test results are documented.
- [ ] UI identifies which liveness method produced the result.
- [ ] Missing CNN model causes degraded or unavailable state, not a false “deep learning active” label.

---

# 7.2 Data quality

## Required work

- [ ] Complete face-quality scoring.
- [ ] Detect blur, brightness, occlusion, multiple faces, small face, extreme angle, corrupt media, and duplicate images.
- [ ] Store audit jobs and progress.
- [ ] Add downloadable remediation report.
- [ ] Add automated recommendations.

## Green acceptance criteria

- [ ] Data-quality report identifies real problematic records.
- [ ] Recommended fixes link directly to affected visitors or media.

---

# 7.3 Model management and retraining

## Required work

- [ ] Define training dataset creation.
- [ ] Add dataset versioning.
- [ ] Add training job queue.
- [ ] Add model artifact storage.
- [ ] Add experiment tracking.
- [ ] Add benchmark gates before activation.
- [ ] Add model approval and rollback.
- [ ] Add checksum verification.
- [ ] Add deployment history.

## Green acceptance criteria

- [ ] A new model cannot activate without benchmark approval.
- [ ] Rollback restores the previous working model.
- [ ] Active model version is visible in health and logs.

---

# 7.4 Edge devices

## Required work

- [ ] Select supported devices.
- [ ] Test heartbeat, event upload, embedding sync, model download, deployment, rollback, and offline buffering.
- [ ] Sign model artifacts.
- [ ] Encrypt device tokens.
- [ ] Add token revocation.
- [ ] Add partial and resumable sync.
- [ ] Test version compatibility.
- [ ] Benchmark ONNX and quantized models on real hardware.

## Green acceptance criteria

- [ ] At least one real supported edge device passes end-to-end testing.
- [ ] Offline events sync without duplication.
- [ ] Invalid or revoked device tokens are rejected.
- [ ] Failed deployment rolls back safely.

---

# 8. Phase 4 — Complete Experimental Features

Before completing each feature, add a separate feature flag and dependency health check. Experimental modules must remain hidden from normal users until they meet the green definition.

# 8.1 Emotion recognition

## Required work

- [ ] Select and package a real emotion model.
- [ ] Remove dependence on user-entered server file paths.
- [ ] Accept secure uploaded media or existing detection-log media IDs.
- [ ] Validate face ownership and organization.
- [ ] Store model version and confidence.
- [ ] Add uncertainty handling.
- [ ] Add fairness and privacy assessment.
- [ ] Add tests using labelled images.

## Green acceptance criteria

- [ ] Endpoint is mounted in production only when the model is available.
- [ ] UI uses secure media selection instead of raw file paths.
- [ ] Accuracy is measured and documented.

---

# 8.2 Action and gesture recognition

## Required work

- [ ] Replace heuristic-only inference with a trained temporal pose model, or clearly classify it as rules-based.
- [ ] Implement video upload or detection-log selection.
- [ ] Store detected action, confidence, model version, and time range.
- [ ] Add labelled test videos.
- [ ] Prevent claims beyond the model’s trained classes.

## Green acceptance criteria

- [ ] Supported action classes are documented.
- [ ] Test accuracy is measured.
- [ ] Unknown action returns `unknown`, not a forced label.

---

# 8.3 Cross-camera Re-identification

## Required work

- [ ] Select a Re-ID model.
- [ ] Create person appearance embeddings separate from face embeddings.
- [ ] Store camera transitions.
- [ ] Add time and location constraints.
- [ ] Handle unidentified visitors.
- [ ] Add duplicate-transition prevention.
- [ ] Build movement timeline UI.
- [ ] Test using multi-camera recordings.

## Green acceptance criteria

- [ ] Transition accuracy and ID-switch rate are measured.
- [ ] Cross-camera movement can be reviewed and corrected.

---

# 8.4 Multimodal recognition

## Required work

- [ ] Confirm supported modalities: face, voice, text, sensor.
- [ ] Package a real voice feature extractor.
- [ ] Package a real text embedding model.
- [ ] Store each modality separately with consent.
- [ ] Implement missing-modality handling.
- [ ] Validate fusion weights.
- [ ] Remove synthetic biometric fallback from production.
- [ ] Add privacy and consent controls for voice biometrics.

## Green acceptance criteria

- [ ] Every biometric modality fails closed when its real backend is unavailable.
- [ ] Fusion accuracy is compared with face-only accuracy.
- [ ] User consent is recorded for each biometric modality.

---

# 8.5 3D face recognition

## Required work

- [ ] Select supported depth hardware or file format.
- [ ] Implement real depth-map and point-cloud ingestion.
- [ ] Store 3D face records.
- [ ] Implement matching using tested geometry features.
- [ ] Add 3D liveness evaluation.
- [ ] Build a real capture workflow.
- [ ] Test with supported depth camera hardware.

## Green acceptance criteria

- [ ] A supported device captures and matches 3D faces end to end.
- [ ] Feature is hidden when supported hardware is not configured.

---

# 8.6 Vision Transformer recognition

## Required work

- [ ] Package a trained ViT model.
- [ ] Define whether it replaces or complements ArcFace.
- [ ] Store compatible embedding version.
- [ ] Implement attention visualization using real model output.
- [ ] Benchmark against ArcFace.
- [ ] Add model loading health checks.

## Green acceptance criteria

- [ ] ViT inference is real, not a placeholder.
- [ ] Model artifact and checksum are versioned.
- [ ] Accuracy and latency are compared with the core model.

---

# 8.7 Multispectral and thermal recognition

## Required work

- [ ] Select supported hardware and image formats.
- [ ] Implement calibrated visible, NIR, SWIR, and thermal ingestion.
- [ ] Align multispectral frames.
- [ ] Implement feature extraction and fusion.
- [ ] Store sensor metadata and calibration data.
- [ ] Test on real multispectral hardware or a labelled dataset.

## Green acceptance criteria

- [ ] Real sensor data is processed end to end.
- [ ] Feature remains disabled without supported sensors.

---

# 8.8 Federated learning

## Required work

- [ ] Define client enrollment and trust model.
- [ ] Implement signed model updates.
- [ ] Add update validation and poisoning protection.
- [ ] Implement secure aggregation or clearly document limitations.
- [ ] Add round scheduling, participation, failure, and rollback.
- [ ] Test with multiple isolated clients.

## Green acceptance criteria

- [ ] Multiple clients complete a real training round.
- [ ] Invalid or malicious updates are rejected.
- [ ] Global model improves against a benchmark.

---

# 8.9 Model A/B testing

## Required work

- [ ] Define traffic assignment.
- [ ] Make assignment deterministic.
- [ ] Record model used for every inference.
- [ ] Define comparison metrics.
- [ ] Add experiment start, stop, pause, and rollback.
- [ ] Prevent experimental models from affecting all users unintentionally.

## Green acceptance criteria

- [ ] Experiment results are reproducible.
- [ ] Every event records its assigned model.
- [ ] Winning model requires approval before production promotion.

---

# 8.10 Synthetic data and temporal augmentation

## Required work

- [ ] Select generation or augmentation models.
- [ ] Add job queue and artifact storage.
- [ ] Record source dataset and transformations.
- [ ] Add quality and identity-leakage checks.
- [ ] Prevent synthetic samples from being treated as real visitor identities.
- [ ] Add human approval before training use.

## Green acceptance criteria

- [ ] Synthetic artifacts are labelled and separated from real biometric data.
- [ ] Quality metrics and approval records exist.
- [ ] Training impact is benchmarked.

---

# 8.11 Mobile and offline synchronization

## Required work

- [ ] Implement real push-notification provider integration.
- [ ] Define offline detection schema.
- [ ] Add idempotent synchronization.
- [ ] Resolve conflicts.
- [ ] Encrypt offline biometric data.
- [ ] Add device registration and revocation.
- [ ] Build and test the mobile or PWA client.

## Green acceptance criteria

- [ ] Offline events synchronize once without duplication.
- [ ] Lost or revoked devices cannot continue syncing.
- [ ] Push notifications work on supported platforms.

---

# 8.12 Advanced security page

## Required work

- [ ] Refactor the page to stable APIs or fully mount and test the Phase 3 security router.
- [ ] Use real LDAP configuration storage.
- [ ] Implement real encryption-key rotation.
- [ ] Re-encrypt data transactionally.
- [ ] Add key versioning and rollback.
- [ ] Generate compliance status from real checks.
- [ ] Generate audit reports from current data.

## Green acceptance criteria

- [ ] Key rotation is tested on backup data before production.
- [ ] Old data remains decryptable during controlled migration.
- [ ] Compliance status is based on runtime checks, not static labels.

---

# 9. Phase 5 — Production Validation

# 9.1 End-to-end scenarios

Create automated and manual tests for these complete workflows.

## Scenario 1 — Organization onboarding

- Register organization
- Login
- Add user
- Configure organization settings
- Add camera
- Enrol visitor
- Upload video
- Review detection

## Scenario 2 — Known visitor detection

- Enrol multiple face angles
- Process video
- Match visitor
- Create log
- Send realtime event
- Trigger configured alert
- Display analytics

## Scenario 3 — Unknown visitor

- Detect unknown face
- Create unidentified log
- Review manually
- Create new visitor from log
- Promote approved face image

## Scenario 4 — Spoof attempt

- Submit print or replay attack
- Liveness rejects it
- Create spoof-rejected log
- Trigger security alert
- Record audit entry

## Scenario 5 — Camera failure

- Disconnect RTSP camera
- Mark camera offline
- Retry connection
- Trigger alert
- Reconnect automatically

## Scenario 6 — GDPR deletion

- Create visitor with faces and logs
- Submit deletion request
- Export data
- Delete or anonymize applicable data
- Remove media
- Preserve required audit record

### Green acceptance criteria

- [ ] All scenarios pass using the production-like Docker environment.
- [ ] Test results are stored as evidence.

---

# 9.2 Performance targets

Define measurable targets for:

- Login response time
- Visitor search response time
- Face search latency at 1,000, 10,000, and 100,000 embeddings
- Video-processing FPS
- Realtime frame-processing latency
- Concurrent camera count
- WebSocket event throughput
- PDF generation time
- Bulk import size
- Queue throughput
- Database connection usage

### Green acceptance criteria

- [ ] Targets are documented.
- [ ] Load tests meet the agreed targets.
- [ ] Performance regressions are checked in CI or scheduled testing.

---

# 9.3 Security testing

Complete:

- [ ] Dependency vulnerability scanning.
- [ ] Secret scanning.
- [ ] Static application security testing.
- [ ] API authorization testing.
- [ ] SSRF testing for URLs and webhooks.
- [ ] File upload testing.
- [ ] SQL injection testing.
- [ ] Cross-tenant access testing.
- [ ] Rate-limit testing.
- [ ] Session replay testing.
- [ ] WebSocket authorization testing.
- [ ] Biometric media access testing.

### Green acceptance criteria

- [ ] No critical or high-severity unresolved issue remains.
- [ ] All security exceptions are documented and approved.

---

# 9.4 Deployment checklist

- [ ] PostgreSQL configured.
- [ ] pgvector configured.
- [ ] Redis configured when queue mode is required.
- [ ] Real AI model artifacts installed.
- [ ] Model checksums verified.
- [ ] Strict recognition enabled.
- [ ] Required secrets configured.
- [ ] SMTP configured.
- [ ] Object or secure media storage configured.
- [ ] HTTPS configured.
- [ ] Trusted hosts configured.
- [ ] Allowed origins configured.
- [ ] Database migrations applied.
- [ ] Backups configured.
- [ ] Monitoring configured.
- [ ] Log retention configured.
- [ ] Experimental flags disabled unless approved.

---

# 10. Recommended Feature Flags

Use separate flags rather than one large Phase 3 switch.

```env
ENABLE_EMOTION_RECOGNITION=0
ENABLE_ACTION_RECOGNITION=0
ENABLE_CROSS_CAMERA_REID=0
ENABLE_MULTIMODAL=0
ENABLE_3D_FACE=0
ENABLE_FEDERATED_LEARNING=0
ENABLE_VIT_RECOGNITION=0
ENABLE_MULTISPECTRAL=0
ENABLE_MODEL_AB_TESTING=0
ENABLE_SYNTHETIC_DATA=0
ENABLE_TEMPORAL_AUGMENTATION=0
ENABLE_MOBILE_SYNC=0
ENABLE_ADVANCED_SECURITY=0
```

For each flag:

- [ ] Backend route mounting must respect it.
- [ ] Frontend navigation must respect it.
- [ ] Health endpoint must report it.
- [ ] Tests must cover enabled and disabled states.

---

# 11. Suggested GitHub Issue Structure

Create one epic for each major group.

## Epic A — Core production hardening

- Navigation and route alignment
- Strict recognition
- Internal endpoint security
- PostgreSQL and pgvector enforcement
- Duplicate API consolidation
- CI and test baseline

## Epic B — Core business workflow

- Authentication
- Organizations and RBAC
- Users
- Visitors
- Face enrolment
- Cameras
- Video processing
- Logs and review
- Realtime feed
- Alerts
- Analytics and reports

## Epic C — Compliance and integrations

- Audit logs
- GDPR
- Consent
- Retention
- Webhooks
- API keys
- LDAP and SSO

## Epic D — AI runtime quality

- Detection benchmark
- Tracking benchmark
- Recognition benchmark
- Liveness benchmark
- Data quality
- Model registry and retraining

## Epic E — Experimental modules

Create one issue per experimental feature. Do not combine all Phase 3 modules into one issue.

Each issue should include:

```markdown
## Problem

## Current Behavior

## Expected Behavior

## Frontend Files

## Backend Files

## Database Changes

## AI or External Dependencies

## Security Requirements

## Acceptance Criteria

## Unit Tests

## Integration Tests

## End-to-End Tests

## Documentation Changes
```

---

# 12. Immediate Work List

Start with these tasks in this exact order.

1. [ ] Create `docs/project-truth/feature-status.md`.
2. [ ] Run and record all backend and frontend tests.
3. [ ] Hide or relocate navigation items whose endpoints are disabled.
4. [ ] Refactor the Security page to stable endpoints.
5. [ ] Enable strict recognition in production.
6. [ ] Make readiness fail when real recognition is unavailable.
7. [ ] Verify every internal endpoint requires a service key or device token.
8. [ ] Select canonical camera, SSO, and GDPR route families.
9. [ ] Enforce PostgreSQL and pgvector in production.
10. [ ] Complete face enrolment transaction cleanup.
11. [ ] Benchmark person detection, tracking, and face recognition.
12. [ ] Complete end-to-end known, unknown, and manual-review workflows.
13. [ ] Complete liveness testing with real spoof samples.
14. [ ] Complete camera reconnection and concurrent-stream testing.
15. [ ] Complete alerts, reports, GDPR, webhooks, and audit verification.
16. [ ] Complete one experimental module at a time.
17. [ ] Run production-like UAT and performance tests.
18. [ ] Update all project-truth documents.

---

# 13. Final Completion Rule

Do not mark the complete SentinelCV system green until:

- [ ] All core features are green.
- [ ] Every visible feature is available and working.
- [ ] Experimental features are either green or hidden behind disabled flags.
- [ ] No weak biometric fallback can run in production.
- [ ] All required tests pass.
- [ ] Production health checks reflect real dependencies.
- [ ] Security and tenant isolation are verified.
- [ ] Performance targets are met.
- [ ] UAT evidence is recorded.
- [ ] Documentation matches the deployed system.

The fastest correct path is to make the **core platform fully green first**, then enable and complete the advanced AI modules individually.
