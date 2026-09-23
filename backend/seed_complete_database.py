#!/usr/bin/env python
"""
Comprehensive Database Seeding Script
Seeds all 42 future enhancements and supporting data for complete 15-tab functionality
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


def _resolve_seed_password(env_name: str) -> tuple[str, bool]:
    supplied = (os.getenv(env_name) or "").strip()
    if supplied:
        return supplied, False
    return secrets.token_urlsafe(18), True


def seed_database():
    print("=" * 70)
    print("COMPREHENSIVE DATABASE SEEDING - ALL 42 ENHANCEMENTS + DATA")
    print("=" * 70)

    # Create tables
    print("\n1. Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("   [OK] Tables created")

    db = SessionLocal()
    admin_password, admin_generated = _resolve_seed_password("SEED_ADMIN_PASSWORD")
    staff_password, staff_generated = _resolve_seed_password("SEED_STAFF_PASSWORD")
    created_credentials: list[tuple[str, str, str, bool]] = []

    try:
        # 1. CREATE ORGANIZATION
        print("\n2. Creating organization...")
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
            print(f"   [OK] Organization created: {org.id}")
        else:
            print(f"   [OK] Organization already exists")
        
        # 2. CREATE USERS
        print("\n3. Creating users...")
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
            print(f"   [OK] Admin user created")
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
            print(f"   [OK] Staff user created")
            created_credentials.append(("staff", staff.email, staff_password, staff_generated))
        
        # 3. CREATE ALL 42 ENHANCEMENTS
        print("\n4. Creating 42 future enhancements...")
        
        enhancements_data = [
            # PHASE 1: Quick Wins (1-3 months)
            ("US-FUT-001", "multimodal", "Multimodal Learning", 
             "Integrate audio, text embeddings with face recognition", "short_term", "critical"),
            ("US-FUT-002", "augmentation", "Advanced Data Augmentation", 
             "Geometric transforms, color jittering, cutout simulation", "short_term", "high"),
            ("US-FUT-003", "optimization", "Model Quantization", 
             "INT8 quantization for faster inference", "short_term", "high"),
            ("US-FUT-004", "model_arch", "Vision Transformers (ViT)", 
             "Integrate Vision Transformer backbone", "short_term", "high"),
            ("US-FUT-005", "model_arch", "Ensemble Methods", 
             "Voting and averaging ensemble strategies", "short_term", "medium"),
            ("US-FUT-006", "learning", "Self-Supervised Learning", 
             "SimCLR, MoCo pre-training", "short_term", "high"),
            ("US-FUT-007", "learning", "Continual Learning", 
             "Incremental learning without catastrophic forgetting", "short_term", "medium"),
            ("US-FUT-008", "augmentation", "Demographic Balancing", 
             "Auto-balance dataset by gender, age, ethnicity", "short_term", "critical"),
            ("US-FUT-009", "robustness", "Adversarial Training", 
             "Robust against adversarial attacks", "short_term", "medium"),
            ("US-FUT-010", "learning", "Hyperparameter Optimization", 
             "Bayesian optimization for hyperparameters", "short_term", "medium"),
            ("US-FUT-011", "robustness", "Occlusion Handling", 
             "Recognize faces with occlusions (masks, sunglasses)", "short_term", "high"),
            
            # PHASE 2: Core Improvements (3-6 months)
            ("US-FUT-012", "fairness", "Bias Detection Audit", 
             "Systematic bias analysis across demographics", "medium_term", "critical"),
            ("US-FUT-013", "fairness", "Fairness Constraints", 
             "Training constraints for demographic parity", "medium_term", "high"),
            ("US-FUT-014", "emerging", "Quantum Computing Exploration", 
             "Quantum algorithms for similarity search", "medium_term", "low"),
            ("US-FUT-015", "explainability", "SHAP Explanations", 
             "Feature importance via SHAP values", "medium_term", "high"),
            ("US-FUT-016", "privacy", "Federated Learning", 
             "Distributed training across edge devices", "medium_term", "medium"),
            ("US-FUT-017", "privacy", "Differential Privacy", 
             "Privacy-preserving training", "medium_term", "high"),
            ("US-FUT-018", "system", "Multi-GPU Support", 
             "Distributed training across multiple GPUs", "medium_term", "high"),
            ("US-FUT-019", "augmentation", "Synthetic Data Generation", 
             "GANs for generating synthetic faces", "medium_term", "medium"),
            ("US-FUT-020", "augmentation", "Face Interpolation", 
             "Morphing between embeddings for augmentation", "medium_term", "low"),
            ("US-FUT-021", "augmentation", "Temporal Augmentation", 
             "Video-based augmentation techniques", "medium_term", "low"),
            ("US-FUT-022", "cv_advanced", "3D Face Reconstruction", 
             "Reconstruct 3D face models from 2D images", "medium_term", "medium"),
            ("US-FUT-023", "model_arch", "Hybrid Architectures", 
             "Combining multiple model architectures", "medium_term", "high"),
            ("US-FUT-024", "robustness", "Adversarial Defense", 
             "Defense mechanisms against attacks", "medium_term", "medium"),
            ("US-FUT-025", "accuracy", "Multi-angle Recognition", 
             "Recognize from multiple viewing angles", "medium_term", "high"),
            ("US-FUT-026", "accuracy", "Consensus Voting", 
             "Vote across multiple models/angles", "medium_term", "high"),
            ("US-FUT-027", "accuracy", "Temporal Smoothing", 
             "Improve accuracy using temporal context", "medium_term", "medium"),
            ("US-FUT-028", "system", "Model Caching", 
             "Cache embeddings for faster re-identification", "medium_term", "medium"),
            
            # PHASE 3: Advanced Features (6-12 months)
            ("US-FUT-029", "system", "Real-time Streaming", 
             "Process video streams with minimal latency", "long_term", "high"),
            ("US-FUT-030", "scalability", "Distributed Processing", 
             "Distribute detection across multiple workers", "long_term", "high"),
            ("US-FUT-031", "performance", "Latency Optimization", 
             "Target <100ms per face detection", "long_term", "high"),
            ("US-FUT-032", "performance", "Throughput Scaling", 
             "Handle 100+ FPS on single GPU", "long_term", "high"),
            ("US-FUT-033", "cv_advanced", "3D Face Recognition", 
             "Use depth maps and point clouds", "long_term", "medium"),
            ("US-FUT-034", "cv_advanced", "Infrared & Multi-Spectral", 
             "Recognize in infrared and other spectra", "long_term", "medium"),
            ("US-FUT-035", "cv_advanced", "Emotion Recognition", 
             "Detect emotions from facial expressions", "long_term", "low"),
            ("US-FUT-036", "cv_advanced", "Action/Gesture Recognition", 
             "Detect actions and hand gestures", "long_term", "low"),
            ("US-FUT-037", "privacy", "Homomorphic Encryption", 
             "Encrypted inference without decryption", "long_term", "low"),
            ("US-FUT-038", "explainability", "LIME Explanations", 
             "Local interpretable explanations", "long_term", "medium"),
            ("US-FUT-039", "explainability", "Attention Maps", 
             "Visualize model attention regions", "long_term", "medium"),
            ("US-FUT-040", "ux", "Web Dashboard", 
             "Interactive monitoring dashboard", "long_term", "high"),
            ("US-FUT-041", "edge", "Edge Device Support", 
             "Deploy on edge devices (Jetson, etc.)", "long_term", "high"),
            ("US-FUT-042", "cv_advanced", "Liveness Detection", 
             "Anti-spoofing for real-time face detection", "long_term", "critical"),
        ]
        
        # Delete existing enhancements for this org to ensure fresh data
        db.query(FutureEnhancement).filter(FutureEnhancement.organization_id == org.id).delete()
        db.flush()
        
        # Create all 42 enhancements
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
        print(f"   [OK] Created {len(enhancements_data)} enhancements")
        
        # 4. CREATE RATE LIMIT RULES
        print("\n5. Creating rate limit rules...")
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
        print(f"   [OK] Created {len(rules)} rate limit rules")
        
        # 5. CREATE CARBON METRICS
        print("\n6. Creating carbon metrics...")
        db.query(CarbonMetrics).filter(CarbonMetrics.organization_id == org.id).delete()
        db.flush()
        
        now = datetime.now(timezone.utc)
        for i in range(12):
            period_start = now - timedelta(days=30*i)
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
                optimization_notes="Regular optimization cycles"
            )
            db.add(metric)
        db.flush()
        print(f"   [OK] Created 12 months of carbon metrics")
        
        db.commit()
        print("\n" + "=" * 70)
        print("DATABASE SEEDING COMPLETE!")
        print("=" * 70)
        if created_credentials:
            print("\nCreated Login Credentials (shown once):")
            for role, email, password, generated in created_credentials:
                source = "generated" if generated else "from environment"
                print(f"  {role.title():<6} {email}  Password: {password} ({source})")
            print("  Tip: set SEED_ADMIN_PASSWORD / SEED_STAFF_PASSWORD to control seeded credentials.")
        else:
            print("\nNo new credentials were generated. Existing seeded users were preserved.")
        print("\nDataset Summary:")
        print(f"  Organizations: {db.query(Organization).count()}")
        print(f"  Users: {db.query(User).count()}")
        print(f"  Future Enhancements: {db.query(FutureEnhancement).count()}")
        print(f"  Rate Limit Rules: {db.query(RateLimitRule).count()}")
        print(f"  Carbon Metrics: {db.query(CarbonMetrics).count()}")
        print("=" * 70)
        
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_database()
