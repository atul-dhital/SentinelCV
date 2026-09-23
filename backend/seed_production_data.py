#!/usr/bin/env python
"""
Production-Level Database Seeding Script
Seeds all data required for 15-tab system with realistic production data
"""

import sys
import os
import secrets
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.base import SessionLocal, Base, engine
from models.models import (
    Organization, User, FutureEnhancement, RateLimitRule, CarbonMetrics
)
from core.security import get_password_hash
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import text
import json


def _resolve_seed_password(env_name: str) -> tuple[str, bool]:
    supplied = (os.getenv(env_name) or "").strip()
    if supplied:
        return supplied, False
    return secrets.token_urlsafe(18), True


def seed_database():
    print("=" * 80)
    print("PRODUCTION-LEVEL DATABASE SEEDING")
    print("=" * 80)

    # Create tables
    print("\n[1/7] Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("      [OK] All tables created")

    db = SessionLocal()
    admin_password, admin_generated = _resolve_seed_password("SEED_ADMIN_PASSWORD")
    staff_password, staff_generated = _resolve_seed_password("SEED_STAFF_PASSWORD")
    created_credentials: list[tuple[str, str, str, bool]] = []

    try:
        # 1. CREATE ORGANIZATION
        print("\n[2/7] Setting up organization...")
        org = db.query(Organization).filter(Organization.name == "Test Org").first()
        if not org:
            org = Organization(
                id=str(uuid.uuid4()),
                name="Test Org",
                api_key=str(uuid.uuid4()),
                face_confidence_threshold=0.6,
                log_retention_days=90
            )
            db.add(org)
            db.flush()
            print(f"      [OK] Organization created")
        else:
            print(f"      [OK] Organization exists")
        
        # 2. CREATE USERS
        print("\n[3/7] Setting up users...")
        admin = db.query(User).filter(User.email == "admin@test.com").first()
        if not admin:
            admin = User(
                id=str(uuid.uuid4()),
                organization_id=org.id,
                email="admin@test.com",
                full_name="Admin User",
                password_hash=get_password_hash(admin_password),
                role="admin",
                is_active=True
            )
            db.add(admin)
            db.flush()
            created_credentials.append(("admin", admin.email, admin_password, admin_generated))
        
        staff = db.query(User).filter(User.email == "staff@test.com").first()
        if not staff:
            staff = User(
                id=str(uuid.uuid4()),
                organization_id=org.id,
                email="staff@test.com",
                full_name="Staff User",
                password_hash=get_password_hash(staff_password),
                role="staff",
                is_active=True
            )
            db.add(staff)
            db.flush()
            created_credentials.append(("staff", staff.email, staff_password, staff_generated))
        
        print(f"      [OK] 2 users configured")
        
        # 3. CREATE ALL 42 ENHANCEMENTS
        print("\n[4/7] Seeding 42 future enhancements...")
        
        enhancements_data = [
            # PHASE 1: Quick Wins (1-3 months)
            ("US-FUT-001", "multimodal", "Multimodal Learning Integration", 
             "Combine facial recognition with gait analysis, voice recognition, and behavioral patterns for robust identification.", "short_term", "critical"),
            ("US-FUT-002", "augmentation", "Advanced Data Augmentation", 
             "Implement CutMix, MixUp, and advanced geometric transformations", "short_term", "high"),
            ("US-FUT-003", "optimization", "Model Quantization", 
             "INT8/INT16 quantization for faster inference and reduced model size", "short_term", "high"),
            ("US-FUT-004", "model_arch", "Vision Transformers (ViT)", 
             "Integrate Vision Transformer backbone for better accuracy", "short_term", "high"),
            ("US-FUT-005", "model_arch", "Ensemble Methods", 
             "Voting and averaging ensemble strategies for improved robustness", "short_term", "medium"),
            ("US-FUT-006", "learning", "Self-Supervised Learning", 
             "SimCLR and MoCo pre-training techniques", "short_term", "high"),
            ("US-FUT-007", "learning", "Continual Learning", 
             "Incremental learning without catastrophic forgetting", "short_term", "medium"),
            ("US-FUT-008", "augmentation", "Demographic Balancing", 
             "Auto-balance training dataset by gender, age, ethnicity", "short_term", "critical"),
            ("US-FUT-009", "robustness", "Adversarial Training", 
             "Training robust models against adversarial attacks", "short_term", "medium"),
            ("US-FUT-010", "learning", "Hyperparameter Optimization", 
             "Bayesian optimization for automated hyperparameter tuning", "short_term", "medium"),
            ("US-FUT-011", "robustness", "Occlusion Handling", 
             "Recognize faces with occlusions (masks, sunglasses, hats)", "short_term", "high"),
            
            # PHASE 2: Core Improvements (3-6 months)
            ("US-FUT-012", "fairness", "Bias Detection Audit", 
             "Systematic bias analysis across demographic groups", "medium_term", "critical"),
            ("US-FUT-013", "fairness", "Fairness Constraints", 
             "Enforce demographic parity during training", "medium_term", "high"),
            ("US-FUT-014", "emerging", "Quantum Computing Exploration", 
             "Quantum algorithms for similarity search optimization", "medium_term", "low"),
            ("US-FUT-015", "explainability", "SHAP Explanations", 
             "Feature importance and decision explanations via SHAP values", "medium_term", "high"),
            ("US-FUT-016", "privacy", "Federated Learning", 
             "Distributed training across edge devices", "medium_term", "medium"),
            ("US-FUT-017", "privacy", "Differential Privacy", 
             "Privacy-preserving training with formal privacy guarantees", "medium_term", "high"),
            ("US-FUT-018", "system", "Multi-GPU Support", 
             "Distributed training across multiple GPUs/TPUs", "medium_term", "high"),
            ("US-FUT-019", "augmentation", "Synthetic Data Generation", 
             "GAN-based synthetic face generation for augmentation", "medium_term", "medium"),
            ("US-FUT-020", "augmentation", "Face Interpolation", 
             "Morphing between embeddings for smooth augmentation", "medium_term", "low"),
            ("US-FUT-021", "augmentation", "Temporal Augmentation", 
             "Video-based augmentation techniques for temporal consistency", "medium_term", "low"),
            ("US-FUT-022", "cv_advanced", "3D Face Reconstruction", 
             "Reconstruct 3D face models from 2D images", "medium_term", "medium"),
            ("US-FUT-023", "model_arch", "Hybrid Architectures", 
             "Combine multiple model architectures for optimal performance", "medium_term", "high"),
            ("US-FUT-024", "robustness", "Adversarial Defense", 
             "Certified defenses against adversarial attacks", "medium_term", "medium"),
            ("US-FUT-025", "accuracy", "Multi-angle Recognition", 
             "Recognize faces from multiple viewing angles", "medium_term", "high"),
            ("US-FUT-026", "accuracy", "Consensus Voting", 
             "Multi-model voting for improved accuracy", "medium_term", "high"),
            ("US-FUT-027", "accuracy", "Temporal Smoothing", 
             "Temporal context for video stream accuracy improvement", "medium_term", "medium"),
            ("US-FUT-028", "system", "Embedding Caching", 
             "Cache embeddings for faster re-identification queries", "medium_term", "medium"),
            
            # PHASE 3: Advanced Features (6-12 months)
            ("US-FUT-029", "system", "Real-time Streaming", 
             "Sub-100ms processing for video streams", "long_term", "high"),
            ("US-FUT-030", "scalability", "Distributed Processing", 
             "Distribute detections across multiple worker nodes", "long_term", "high"),
            ("US-FUT-031", "performance", "Latency Optimization", 
             "Target <100ms per face detection and matching", "long_term", "high"),
            ("US-FUT-032", "performance", "Throughput Scaling", 
             "Handle 100+ FPS on single GPU", "long_term", "high"),
            ("US-FUT-033", "cv_advanced", "3D Face Recognition", 
             "Use depth maps and point clouds for recognition", "long_term", "medium"),
            ("US-FUT-034", "cv_advanced", "Infrared & Multi-Spectral", 
             "Recognize in infrared and multi-spectral wavelengths", "long_term", "medium"),
            ("US-FUT-035", "cv_advanced", "Emotion Recognition", 
             "Detect and classify emotions from facial expressions", "long_term", "low"),
            ("US-FUT-036", "cv_advanced", "Action/Gesture Recognition", 
             "Detect actions and hand gestures in addition to faces", "long_term", "low"),
            ("US-FUT-037", "privacy", "Homomorphic Encryption", 
             "Encrypted inference without decryption", "long_term", "low"),
            ("US-FUT-038", "explainability", "LIME Explanations", 
             "Local interpretable explanations for predictions", "long_term", "medium"),
            ("US-FUT-039", "explainability", "Attention Visualization", 
             "Visualize model attention and focus regions", "long_term", "medium"),
            ("US-FUT-040", "ux", "Web Dashboard", 
             "Real-time monitoring dashboard for system metrics", "long_term", "high"),
            ("US-FUT-041", "edge", "Edge Device Deployment", 
             "Deploy on Jetson, TPU edge, and ARM processors", "long_term", "high"),
            ("US-FUT-042", "cv_advanced", "Liveness Detection", 
             "Anti-spoofing with presentation attack detection", "long_term", "critical"),
        ]
        
        # Delete and recreate enhancements
        db.query(FutureEnhancement).filter(FutureEnhancement.organization_id == org.id).delete()
        db.flush()
        
        for story_id, category, title, desc, phase, priority in enhancements_data:
            enh = FutureEnhancement(
                id=str(uuid.uuid4()),
                organization_id=org.id,
                story_id=story_id,
                category=category,
                title=title,
                description=desc,
                status="planned",
                priority=priority,
                roadmap_phase=phase,
                enabled=False,
                config={}
            )
            db.add(enh)
        db.flush()
        print(f"      [OK] {len(enhancements_data)} enhancements created")
        
        # 4. CREATE RATE LIMIT RULES
        print("\n[5/7] Setting up rate limit rules...")
        db.query(RateLimitRule).filter(RateLimitRule.organization_id == org.id).delete()
        db.flush()
        
        rules = [
            RateLimitRule(
                id=str(uuid.uuid4()),
                organization_id=org.id,
                endpoint_pattern="/api/v1/*",
                max_requests=1000,
                window_seconds=3600,
                is_active=True
            ),
            RateLimitRule(
                id=str(uuid.uuid4()),
                organization_id=org.id,
                endpoint_pattern="/api/v1/face-upload",
                max_requests=100,
                window_seconds=3600,
                is_active=True
            ),
            RateLimitRule(
                id=str(uuid.uuid4()),
                organization_id=org.id,
                endpoint_pattern="/api/v1/detection/*",
                max_requests=500,
                window_seconds=60,
                is_active=True
            ),
        ]
        for rule in rules:
            db.add(rule)
        db.flush()
        print(f"      [OK] {len(rules)} rate limit rules created")
        
        # 5. CREATE CARBON METRICS
        print("\n[6/7] Seeding carbon & sustainability metrics...")
        db.query(CarbonMetrics).filter(CarbonMetrics.organization_id == org.id).delete()
        db.flush()
        
        now = datetime.now(timezone.utc)
        for i in range(12):
            period_start = now - timedelta(days=30*(i+1))
            period_end = period_start + timedelta(days=30)
            
            metric = CarbonMetrics(
                id=str(uuid.uuid4()),
                organization_id=org.id,
                period_start=period_start,
                period_end=period_end,
                gpu_hours=50.0 + (i * 5),
                cpu_hours=200.0 + (i * 10),
                estimated_kwh=300.0 + (i * 20),
                estimated_co2_kg=150.0 + (i * 10),
                training_runs=5 + i,
                inference_count=50000 + (i * 5000),
                optimization_notes=f"Optimization cycle {i+1}: Model quantization and pruning applied"
            )
            db.add(metric)
        db.flush()
        print(f"      [OK] 12 months of carbon metrics created")
        
        # 6. CREATE BIAS AUDIT DATA
        print("\n[7/7] Seeding bias audit & explainability data...")
        
        # Clear existing bias audit data
        db.execute(text("DELETE FROM bias_audits WHERE organization_id = :org_id"), {"org_id": org.id})
        db.execute(text("DELETE FROM explainability_results WHERE organization_id = :org_id"), {"org_id": org.id})
        db.flush()
        
        # Add demographic bias audit results
        demographic_groups = [
            ("Male", 0.965, 0.015, 0.020),
            ("Female", 0.958, 0.022, 0.025),
            ("Age 18-30", 0.972, 0.010, 0.015),
            ("Age 31-50", 0.961, 0.018, 0.022),
            ("Age 51+", 0.945, 0.035, 0.040),
            ("Ethnicity A", 0.963, 0.016, 0.021),
            ("Ethnicity B", 0.957, 0.024, 0.028),
            ("Ethnicity C", 0.949, 0.031, 0.035),
        ]
        
        for demographic, accuracy, fpr, fnr in demographic_groups:
            db.execute(text(
                "INSERT INTO bias_audits (id, organization_id, demographic_group, accuracy_rate, false_positive_rate, false_negative_rate, inference_count, timestamp, config) "
                "VALUES (:id, :org_id, :demo, :acc, :fpr, :fnr, :count, :ts, :cfg)"
            ), {
                "id": str(uuid.uuid4()),
                "org_id": org.id,
                "demo": demographic,
                "acc": accuracy,
                "fpr": fpr,
                "fnr": fnr,
                "count": 10000 + (int(accuracy * 100000) % 5000),
                "ts": datetime.now(timezone.utc),
                "cfg": json.dumps({"audit_method": "stratified_sampling"})
            })
        
        db.flush()
        print(f"      [OK] 8 demographic bias audit results created")
        
        # Add explainability results (SHAP, LIME, Attention)
        explainability_methods = [
            ("SHAP", {"top_features": ["face_embedding_1", "face_embedding_2", "face_embedding_3"], "values": [0.35, 0.28, 0.22]}),
            ("LIME", {"explanation": "Local linear approximation explains decision boundary", "weight": 0.92}),
            ("Attention", {"regions": ["face_center", "eye_region", "nose_tip"], "focus": "high_confidence_regions"}),
        ]
        
        for method, exp_data in explainability_methods:
            for i in range(3):
                db.execute(text(
                    "INSERT INTO explainability_results (id, organization_id, detection_id, method, explanation_data, confidence_breakdown, created_at) "
                    "VALUES (:id, :org_id, :det_id, :method, :exp_data, :conf, :ts)"
                ), {
                    "id": str(uuid.uuid4()),
                    "org_id": org.id,
                    "det_id": f"detection_{uuid.uuid4().hex[:8]}",
                    "method": method,
                    "exp_data": json.dumps(exp_data),
                    "conf": json.dumps({"confidence": 0.95 + (i * 0.01), "threshold": 0.85}),
                    "ts": datetime.now(timezone.utc) - timedelta(days=i)
                })
        
        db.flush()
        print(f"      [OK] Explainability results (SHAP, LIME, Attention) created")
        
        # Commit all changes
        db.commit()
        
        print("\n" + "=" * 80)
        print("DATABASE SEEDING COMPLETE - PRODUCTION READY!")
        print("=" * 80)
        if created_credentials:
            print("\nCreated Login Credentials (shown once):")
            for role, email, password, generated in created_credentials:
                source = "generated" if generated else "from environment"
                print(f"  {role.title():<6} {email}  Password: {password} ({source})")
            print("  Tip: set SEED_ADMIN_PASSWORD / SEED_STAFF_PASSWORD to control seeded credentials.")
        else:
            print("\nNo new credentials were generated. Existing seeded users were preserved.")
        print("\nFinal Dataset Summary:")
        print(f"  Organizations: 1")
        print(f"  Users: 2 (admin + staff)")
        print(f"  Future Enhancements: 42 (all phases)")
        print(f"  Rate Limit Rules: 3")
        print(f"  Carbon Metrics: 12 months")
        print(f"  Bias Audit Results: 8 demographic groups")
        print(f"  Explainability Methods: 3 (SHAP, LIME, Attention)")
        print("\nReady for all 15 tabs!")
        print("=" * 80)
        
    except Exception as e:
        print(f"\nERROR during seeding: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    seed_database()
