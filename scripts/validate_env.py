#!/usr/bin/env python3
"""
US-DEP-003: Environment Variables Validation
Purpose: Validate all required environment variables are set and correct
Usage: python scripts/validate_env.py --env-file .env.production
"""

import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple


class EnvironmentValidator:
    """Validate production environment configuration"""

    SUPPORTED_ENVIRONMENTS = {"production", "staging"}
    DATABASE_URL_KEYS = (
        "DATABASE_URL",
        "POSTGRES_URL_NON_POOLING",
        "POSTGRES_URL",
        "POSTGRES_PRISMA_URL",
    )

    # Required variables organized by category
    REQUIRED_VARS = {
        "CORE": [
            ("ENVIRONMENT", tuple(SUPPORTED_ENVIRONMENTS)),
            ("DEBUG", ("true", "false")),
            ("LOG_LEVEL", str),
            ("APP_NAME", str),
        ],
        "DATABASE": [
            ("DB_POOL_SIZE", int),
            ("DB_MAX_OVERFLOW", int),
            ("DB_POOL_RECYCLE", int),
            ("DB_POOL_PRE_PING", ("true", "false")),
            ("DB_CONNECT_TIMEOUT", int),
            ("DB_POOL_WARN_UTILIZATION", float),
            ("DB_POOL_CRITICAL_UTILIZATION", float),
            ("DB_CONNECTION_WARN_UTILIZATION", float),
            ("DB_CONNECTION_CRITICAL_UTILIZATION", float),
            ("DB_SLOW_QUERY_THRESHOLD_MS", float),
        ],
        "REDIS": [
            ("REDIS_URL", "redis://"),
            ("CACHE_TTL_SECONDS", int),
            ("SESSION_TIMEOUT_MINUTES", int),
            ("REDIS_DEFAULT_TTL", int),
            ("REDIS_EMBEDDING_TTL", int),
            ("REDIS_SESSION_TTL", int),
            ("REDIS_SEARCH_RESULT_TTL", int),
            ("REDIS_POOL_MAX_CONNECTIONS", int),
        ],
        "SECURITY": [
            ("SECRET_KEY", str),  # Must not be default
            ("JWT_ALGORITHM", "HS256"),
            ("JWT_EXPIRATION_MINUTES", int),
            ("REFRESH_TOKEN_EXPIRATION_DAYS", int),
            ("JWT_SECRET_KEY", str),
            ("BCRYPT_COST_FACTOR", int),
        ],
        "AI_SERVICES": [
            ("AI_SERVICE_URL", "http://"),
            ("YOLO_MODEL_PATH", str),
            ("YOLO_CONFIDENCE_THRESHOLD", float),
            ("LIVENESS_CONFIDENCE_THRESHOLD", float),
            ("RECOGNITION_SIMILARITY_THRESHOLD", float),
        ],
        "FRONTEND": [
            ("NEXT_PUBLIC_API_URL", "http"),
            ("NEXT_PUBLIC_WEBSOCKET_URL", "ws"),
            ("NEXT_PUBLIC_ENVIRONMENT", str),
        ],
        "CORS": [
            ("ALLOWED_ORIGINS", str),
            ("ALLOWED_HOSTS", str),
            ("CORS_CREDENTIALS", ("true", "false")),
            ("FORCE_HTTPS", ("true", "false")),
            ("SECURE_COOKIES", ("true", "false")),
        ],
        "STORAGE": [
            ("STORAGE_TYPE", str),
            ("UPLOAD_DIR", str),
            ("MAX_UPLOAD_SIZE_MB", int),
            ("ALLOWED_UPLOAD_TYPES", str),
        ],
    }
    
    def __init__(self, env_file: str = ".env.production"):
        self.env_file = env_file
        self.results = {"passed": [], "failed": [], "warnings": []}
        self.env_vars = {}
        
    def log(self, message: str, level: str = "INFO"):
        """Log validation message"""
        colors = {
            "INFO": "\033[94m",    # Blue
            "OK": "\033[92m",      # Green
            "WARNING": "\033[93m", # Yellow
            "ERROR": "\033[91m",   # Red
            "RESET": "\033[0m"     # Reset
        }
        
        color = colors.get(level, colors["INFO"])
        symbol = {
            "INFO": "i",
            "OK": "v",
            "WARNING": "!",
            "ERROR": "x"
        }.get(level, "*")
        
        try:
            # Clean message of problematic characters
            safe_message = message.encode('ascii', 'replace').decode('ascii')
            print(f"{color}{symbol} {safe_message}{colors['RESET']}")
        except Exception:
            print(f"{symbol} {message[:100]}")
    
    def load_env_file(self) -> bool:
        """Load and parse .env file"""
        self.log(f"Loading environment file: {self.env_file}")
        
        if not os.path.exists(self.env_file):
            self.log(f"File not found: {self.env_file}", "ERROR")
            self.results["failed"].append(f"Environment file not found: {self.env_file}")
            return False
        
        try:
            with open(self.env_file, 'r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    line = line.strip()
                    
                    # Skip comments and empty lines
                    if not line or line.startswith('#'):
                        continue
                    
                    # Parse key=value
                    if '=' in line:
                        key, value = line.split('=', 1)
                        self.env_vars[key.strip()] = value.strip()
            
            self.log(f"Loaded {len(self.env_vars)} variables", "OK")
            self.results["passed"].append(f"Loaded {len(self.env_vars)} environment variables")
            return True
            
        except Exception as e:
            self.log(f"Error reading env file: {e}", "ERROR")
            self.results["failed"].append(f"Error reading env file: {e}")
            return False
    
    def validate_required_vars(self) -> bool:
        """Validate all required variables are present"""
        self.log("\nValidating required variables...")
        
        all_valid = True
        
        for category, vars_list in self.REQUIRED_VARS.items():
            self.log(f"\n  [{category}]")
            
            for var_info in vars_list:
                var_name = var_info[0]
                expected = var_info[1]
                
                # Check if variable exists
                if var_name not in self.env_vars:
                    self.log(f"    ✗ {var_name}: MISSING", "ERROR")
                    self.results["failed"].append(f"{var_name} is required but missing")
                    all_valid = False
                    continue
                
                value = self.env_vars[var_name]
                
                # Type validation
                if isinstance(expected, type):
                    try:
                        if expected == int:
                            int(value)
                        elif expected == float:
                            float(value)
                        elif expected == str:
                            # Just verify it's not empty or default
                            if not value or value == "CHANGE_ME":
                                self.log(f"    ✗ {var_name}: Invalid value (CHANGE_ME)", "ERROR")
                                self.results["failed"].append(f"{var_name} still has default value")
                                all_valid = False
                            else:
                                self.log(f"    ✓ {var_name}: {expected.__name__}", "OK")
                                self.results["passed"].append(f"{var_name} valid")
                    except ValueError:
                        self.log(f"    ✗ {var_name}: Invalid type (expected {expected.__name__})", "ERROR")
                        self.results["failed"].append(f"{var_name} type mismatch")
                        all_valid = False
                
                # Allowed values validation
                elif isinstance(expected, (list, tuple, set)):
                    normalized = value.strip().lower()
                    allowed = {str(item).lower() for item in expected}
                    if normalized in allowed:
                        self.log(f"    ✓ {var_name}: {value}", "OK")
                        self.results["passed"].append(f"{var_name} valid")
                    else:
                        self.log(
                            f"    ✗ {var_name}: Expected one of {sorted(allowed)}, got '{value}'",
                            "ERROR",
                        )
                        self.results["failed"].append(f"{var_name} value mismatch")
                        all_valid = False

                # String validation (prefix check)
                elif isinstance(expected, str):
                    if value.startswith(expected):
                        self.log(f"    ✓ {var_name}: {value[:50]}...", "OK")
                        self.results["passed"].append(f"{var_name} valid")
                    else:
                        self.log(f"    ✗ {var_name}: Expected prefix '{expected}', got '{value[:30]}...'", "ERROR")
                        self.results["failed"].append(f"{var_name} value mismatch")
                        all_valid = False
        
        return all_valid
    
    def validate_no_secrets_in_code(self) -> bool:
        """Check source code doesn't have hardcoded secrets"""
        self.log("\nChecking for hardcoded secrets in code...")
        
        sensitive_patterns = [
            "password=",
            "secret_key=",
            "api_key=",
            "token="
        ]
        
        src_files = Path("backend").glob("**/*.py")
        issues_found = False
        
        for filepath in src_files:
            try:
                with open(filepath, 'r') as f:
                    for line_num, line in enumerate(f, 1):
                        lower_line = line.lower()
                        for pattern in sensitive_patterns:
                            if pattern in lower_line and "os.getenv" not in line:
                                self.log(
                                    f"    ! Potential secret in {filepath}:{line_num}: {line.strip()[:60]}...",
                                    "WARNING"
                                )
                                self.results["warnings"].append(
                                    f"Potential hardcoded secret in {filepath}:{line_num}"
                                )
                                issues_found = True
            except Exception as e:
                pass  # Skip binary files
        
        if not issues_found:
            self.log("    ✓ No hardcoded secrets detected", "OK")
            self.results["passed"].append("No hardcoded secrets in code")
        
        return not issues_found
    
    def validate_security_settings(self) -> bool:
        """Validate critical security settings"""
        self.log("\nValidating security settings...")
        
        all_valid = True
        environment = self.env_vars.get("ENVIRONMENT", "").strip().lower()
        is_production = environment == "production"
        
        # Check FORCE_HTTPS
        if self.env_vars.get("FORCE_HTTPS") != "true":
            if is_production:
                self.log("    ✗ FORCE_HTTPS must be 'true' in production", "ERROR")
                self.results["failed"].append("FORCE_HTTPS must be 'true' in production")
                all_valid = False
            else:
                self.log("    ! FORCE_HTTPS not set to 'true'", "WARNING")
                self.results["warnings"].append("FORCE_HTTPS should be 'true' in production")
        else:
            self.log("    ✓ FORCE_HTTPS=true", "OK")
        
        # Check SECURE_COOKIES
        if self.env_vars.get("SECURE_COOKIES") != "true":
            if is_production:
                self.log("    ✗ SECURE_COOKIES must be 'true' in production", "ERROR")
                self.results["failed"].append("SECURE_COOKIES must be 'true' in production")
                all_valid = False
            else:
                self.log("    ! SECURE_COOKIES not set to 'true'", "WARNING")
                self.results["warnings"].append("SECURE_COOKIES should be 'true' in production")
        else:
            self.log("    ✓ SECURE_COOKIES=true", "OK")
        
        # Check DEBUG
        if self.env_vars.get("DEBUG") != "false":
            if is_production:
                self.log("    ✗ DEBUG must be 'false' in production", "ERROR")
                self.results["failed"].append("DEBUG must be 'false' in production")
                all_valid = False
            else:
                self.log("    ! DEBUG not set to 'false'", "WARNING")
                self.results["warnings"].append("DEBUG should be 'false' for staging")
        else:
            self.log("    ✓ DEBUG=false", "OK")
        
        # Check SECRET_KEY is not default
        secret_key = self.env_vars.get("SECRET_KEY", "")
        if len(secret_key) < 20:
            self.log("    ✗ SECRET_KEY too short (must be 20+ chars)", "ERROR")
            self.results["failed"].append("SECRET_KEY too short")
            all_valid = False
        elif secret_key.startswith("CHANGE_ME"):
            self.log("    ✗ SECRET_KEY still has default value", "ERROR")
            self.results["failed"].append("SECRET_KEY has default value")
            all_valid = False
        else:
            self.log(f"    ✓ SECRET_KEY set ({len(secret_key)} chars)", "OK")
        
        return all_valid
    
    def validate_database_url(self) -> bool:
        """Validate database URL format"""
        self.log("\nValidating database configuration...")

        db_var = next(
            (
                name
                for name in self.DATABASE_URL_KEYS
                if self.env_vars.get(name, "").strip()
            ),
            None,
        )
        db_url = self.env_vars.get(db_var, "").strip() if db_var else ""

        if not db_url:
            expected = ", ".join(self.DATABASE_URL_KEYS)
            self.log(f"    âœ— No database URL set ({expected})", "ERROR")
            self.results["failed"].append("Database URL missing")
            return False

        normalized_db_url = (
            "postgresql://" + db_url[len("postgres://"):]
            if db_url.startswith("postgres://")
            else db_url
        )

        if not normalized_db_url.startswith("postgresql://"):
            self.log("    âœ— Database URL must use postgres:// or postgresql:// in production", "ERROR")
            self.results["failed"].append("Database URL must use PostgreSQL")
            return False

        if "localhost" in normalized_db_url or "127.0.0.1" in normalized_db_url:
            self.log(f"    ! {db_var} uses localhost (should be remote for production)", "WARNING")
            self.results["warnings"].append(f"{db_var} should point to remote server")

        self.log(f"    âœ“ {db_var} format valid", "OK")
        return True
        
        db_url = self.env_vars.get("DATABASE_URL", "")
        
        if not db_url:
            self.log("    ✗ DATABASE_URL not set", "ERROR")
            self.results["failed"].append("DATABASE_URL missing")
            return False
        
        if not db_url.startswith("postgresql://"):
            self.log("    ✗ DATABASE_URL must use postgresql:// (not SQLite) in production", "ERROR")
            self.results["failed"].append("DATABASE_URL must use PostgreSQL")
            return False
        
        # Check for localhost (should use remote for prod)
        if "localhost" in db_url or "127.0.0.1" in db_url:
            self.log("    ! DATABASE_URL uses localhost (should be remote for production)", "WARNING")
            self.results["warnings"].append("DATABASE_URL should point to remote server")
        
        self.log("    ✓ DATABASE_URL format valid", "OK")
        return True
    
    def validate_api_urls(self) -> bool:
        """Validate API and frontend URLs"""
        self.log("\nValidating API/Frontend URLs...")

        api_url = self.env_vars.get("NEXT_PUBLIC_API_URL", "")
        ws_url = self.env_vars.get("NEXT_PUBLIC_WEBSOCKET_URL", "")
        environment = self.env_vars.get("ENVIRONMENT", "").strip().lower()
        is_production = environment == "production"

        if is_production and not api_url.startswith("https://"):
            self.log("    ✗ NEXT_PUBLIC_API_URL must use HTTPS in production", "ERROR")
            self.results["failed"].append("API URL must use HTTPS in production")
        elif not api_url.startswith("http://") and not api_url.startswith("https://"):
            self.log("    ✗ NEXT_PUBLIC_API_URL must start with http:// or https://", "ERROR")
            self.results["failed"].append("API URL format invalid")
        else:
            self.log("    ✓ API URL format valid", "OK")

        if ws_url:
            if is_production and not ws_url.startswith("wss://"):
                self.log("    ✗ NEXT_PUBLIC_WEBSOCKET_URL must use WSS in production", "ERROR")
                self.results["failed"].append("WebSocket URL must use WSS in production")
            elif not ws_url.startswith("ws://") and not ws_url.startswith("wss://"):
                self.log("    ✗ NEXT_PUBLIC_WEBSOCKET_URL must start with ws:// or wss://", "ERROR")
                self.results["failed"].append("WebSocket URL format invalid")
            else:
                self.log("    ✓ WebSocket URL format valid", "OK")

        return True

    def validate_feature_settings(self) -> bool:
        """Validate conditional settings based on feature flags."""
        self.log("\nValidating feature-dependent settings...")

        all_valid = True

        environment = self.env_vars.get("ENVIRONMENT", "").strip().lower()
        public_environment = self.env_vars.get("NEXT_PUBLIC_ENVIRONMENT", "").strip().lower()
        if environment and public_environment and environment != public_environment:
            self.log(
                f"    ! NEXT_PUBLIC_ENVIRONMENT ({public_environment}) does not match ENVIRONMENT ({environment})",
                "WARNING",
            )
            self.results["warnings"].append("NEXT_PUBLIC_ENVIRONMENT should match ENVIRONMENT")

        def _require(var_name: str, label: str) -> None:
            nonlocal all_valid
            value = self.env_vars.get(var_name, "").strip()
            if not value or value.startswith("CHANGE_ME"):
                self.log(f"    ✗ {label} missing or default ({var_name})", "ERROR")
                self.results["failed"].append(f"{var_name} missing or default")
                all_valid = False

        def _require_any(var_names: List[str], label: str) -> None:
            nonlocal all_valid
            for var_name in var_names:
                value = self.env_vars.get(var_name, "").strip()
                if value and not value.startswith("CHANGE_ME"):
                    return
            joined = ", ".join(var_names)
            self.log(f"    âœ— {label} missing or default ({joined})", "ERROR")
            self.results["failed"].append(f"{label} missing or default")
            all_valid = False

        def _require_int(var_name: str, label: str) -> None:
            nonlocal all_valid
            value = self.env_vars.get(var_name, "").strip()
            try:
                int(value)
            except ValueError:
                self.log(f"    ✗ {label} must be an integer ({var_name})", "ERROR")
                self.results["failed"].append(f"{var_name} must be integer")
                all_valid = False

        if self.env_vars.get("SENTRY_ENABLED") == "true":
            _require("SENTRY_DSN", "Sentry DSN")

        if self.env_vars.get("PROMETHEUS_ENABLED") == "true":
            _require_int("PROMETHEUS_PORT", "Prometheus port")

        if self.env_vars.get("LOG_TO_FILE") == "true":
            _require("LOG_FILE_PATH", "Log file path")

        if self.env_vars.get("EMAIL_ENABLED") == "true":
            _require("SMTP_SERVER", "SMTP server")
            _require("SMTP_USER", "SMTP user")
            _require("SMTP_PASSWORD", "SMTP password")
            _require("SMTP_FROM_EMAIL", "SMTP from email")

        storage_type = self.env_vars.get("STORAGE_TYPE", "local").strip().lower()
        if storage_type in {"s3", "r2"}:
            _require_any(["OBJECT_STORAGE_BUCKET", "R2_BUCKET", "AWS_S3_BUCKET"], "Object storage bucket")
            _require_any(
                ["OBJECT_STORAGE_ENDPOINT_URL", "R2_ENDPOINT_URL", "AWS_S3_ENDPOINT_URL"],
                "Object storage endpoint",
            )
            _require_any(
                ["OBJECT_STORAGE_ACCESS_KEY_ID", "R2_ACCESS_KEY_ID", "AWS_ACCESS_KEY_ID"],
                "Object storage access key",
            )
            _require_any(
                ["OBJECT_STORAGE_SECRET_ACCESS_KEY", "R2_SECRET_ACCESS_KEY", "AWS_SECRET_ACCESS_KEY"],
                "Object storage secret key",
            )
            if storage_type == "s3":
                _require_any(["OBJECT_STORAGE_REGION", "AWS_S3_REGION"], "Object storage region")

        if self.env_vars.get("RATE_LIMIT_ENABLED") == "true":
            _require_int("RATE_LIMIT_REQUESTS_PER_MINUTE", "Rate limit per minute")
            _require_int("RATE_LIMIT_REQUESTS_PER_HOUR", "Rate limit per hour")

        if self.env_vars.get("GDPR_ENABLED") == "true":
            _require_int("DATA_RETENTION_DAYS", "Data retention days")
            _require_int("AUDIT_LOG_RETENTION_DAYS", "Audit log retention days")

        return all_valid

    def validate_encrypted_env_settings(self) -> bool:
        """Validate optional encrypted environment runtime loading settings."""
        self.log("\nValidating encrypted env runtime settings...")

        encrypted_env_file = self.env_vars.get("SENTINELCV_ENCRYPTED_ENV_FILE", "").strip()
        env_key = self.env_vars.get("SENTINELCV_ENV_KEY", "").strip()
        env_key_file = self.env_vars.get("SENTINELCV_ENV_KEY_FILE", "").strip()

        if not encrypted_env_file:
            self.log("    ✓ Encrypted env runtime loading not enabled", "OK")
            return True

        self.log(f"    ✓ SENTINELCV_ENCRYPTED_ENV_FILE set: {encrypted_env_file}", "OK")

        if not env_key and not env_key_file:
            self.log("    ✗ Encrypted env enabled but no key source configured", "ERROR")
            self.results["failed"].append(
                "Set SENTINELCV_ENV_KEY or SENTINELCV_ENV_KEY_FILE when SENTINELCV_ENCRYPTED_ENV_FILE is used"
            )
            return False

        if env_key and env_key_file:
            self.log("    ! Both SENTINELCV_ENV_KEY and SENTINELCV_ENV_KEY_FILE are set (key file will be ignored by runtime if key is present)", "WARNING")
            self.results["warnings"].append("Both encrypted env key sources are configured")

        if env_key_file:
            if os.path.exists(env_key_file):
                self.log(f"    ✓ Key file exists: {env_key_file}", "OK")
            else:
                self.log(f"    ! Key file path not found from current host: {env_key_file}", "WARNING")
                self.results["warnings"].append("Encrypted env key file path not found on current host")

        return True
    
    def run_all_validations(self) -> Dict:
        """Execute all validation checks"""
        self.log("=" * 70)
        self.log("SentinelCV Environment Validation", "INFO")
        self.log("=" * 70)
        
        # Load environment file
        if not self.load_env_file():
            return self.results
        
        # Run all validations
        self.validate_required_vars()
        self.validate_no_secrets_in_code()
        self.validate_security_settings()
        self.validate_database_url()
        self.validate_api_urls()
        self.validate_encrypted_env_settings()
        self.validate_feature_settings()
        
        # Summary
        self.log("\n" + "=" * 70)
        self.log(f"✓ PASSED: {len(self.results['passed'])} checks", "OK")
        self.log(f"✗ FAILED: {len(self.results['failed'])} checks", "ERROR")
        self.log(f"! WARNINGS: {len(self.results['warnings'])} warnings", "WARNING")
        self.log("=" * 70)
        
        if self.results['failed']:
            self.log("\nFailed Checks:", "ERROR")
            for msg in self.results['failed']:
                self.log(f"  - {msg}", "ERROR")
        
        if self.results['warnings']:
            self.log("\nWarnings:", "WARNING")
            for msg in self.results['warnings']:
                self.log(f"  - {msg}", "WARNING")
        
        return self.results
    
    def is_valid(self) -> bool:
        """Returns True if all validations passed"""
        return len(self.results['failed']) == 0


def main():
    import argparse

    default_env_file = '.env.staging' if os.path.exists('.env.staging') else '.env.production'
    parser = argparse.ArgumentParser(description="Validate environment variables")
    parser.add_argument('--env-file', default=default_env_file, help='Path to .env file')
    args = parser.parse_args()
    
    validator = EnvironmentValidator(args.env_file)
    results = validator.run_all_validations()
    
    sys.exit(0 if validator.is_valid() else 1)


if __name__ == "__main__":
    main()
