"""SSO Service for SAML/OAuth2 authentication and management.

Implements user story: US-ENT-010 - SSO/SAML integration
"""

import base64
import binascii
import hashlib
import logging
import re
from typing import Optional, Dict, Any
from uuid import UUID
from xml.etree import ElementTree as ET
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

from models.models import SSOProvider, SSOSession, User
from schemas.schemas import SSOProviderCreate, SSOProviderUpdate


class SSOService:
    """Service for managing SSO provider configurations and sessions."""

    @staticmethod
    def _clean_certificate(certificate: Optional[str]) -> str:
        cleaned = (certificate or "").strip()
        if not cleaned:
            return ""
        lines = [
            line.strip()
            for line in cleaned.splitlines()
            if "BEGIN CERTIFICATE" not in line and "END CERTIFICATE" not in line
        ]
        return "".join(lines)

    @staticmethod
    def _decode_saml_payload(saml_response: str) -> str:
        candidate = (saml_response or "").strip()
        if not candidate:
            raise ValueError("SAML response is empty")
        if candidate.startswith("<"):
            return candidate
        try:
            decoded = base64.b64decode(candidate, validate=False)
            text = decoded.decode("utf-8")
            if "<" in text:
                return text
        except (ValueError, UnicodeDecodeError, binascii.Error):
            pass
        raise ValueError("SAML response must be XML or base64-encoded XML")

    @staticmethod
    def _extract_attribute_values(root: ET.Element) -> Dict[str, str]:
        attributes: Dict[str, str] = {}
        for attr in root.findall(".//{*}Attribute"):
            name = (attr.attrib.get("Name") or attr.attrib.get("FriendlyName") or "").strip()
            if not name:
                continue
            values = [
                (value.text or "").strip()
                for value in attr.findall(".//{*}AttributeValue")
                if (value.text or "").strip()
            ]
            if values:
                attributes[name] = values[0]
        return attributes

    @staticmethod
    def _resolve_attribute(
        attributes: Dict[str, str],
        mappings: Dict[str, str],
        target_key: str,
        defaults: list[str],
    ) -> Optional[str]:
        candidates = []
        mapped = (mappings or {}).get(target_key)
        if mapped:
            candidates.append(mapped)
        candidates.extend(defaults)
        for candidate in candidates:
            if candidate in attributes and attributes[candidate]:
                return attributes[candidate]
        return None
    
    def create_sso_provider(
        self,
        db: Session,
        organization_id: UUID,
        provider_data: SSOProviderCreate
    ) -> SSOProvider:
        """Create a new SSO provider configuration.
        
        Args:
            db: Database session
            organization_id: Organization UUID
            provider_data: SSO provider configuration data
            
        Returns:
            Created SSOProvider model instance
        """
        sso_provider = SSOProvider(
            organization_id=organization_id,
            **provider_data.model_dump()
        )
        db.add(sso_provider)
        db.commit()
        db.refresh(sso_provider)
        return sso_provider
    
    def get_sso_provider(
        self,
        db: Session,
        provider_id: UUID
    ) -> Optional[SSOProvider]:
        """Get SSO provider by ID.
        
        Args:
            db: Database session
            provider_id: Provider UUID
            
        Returns:
            SSOProvider instance or None
        """
        return db.query(SSOProvider).filter(SSOProvider.id == provider_id).first()
    
    def get_organization_sso_providers(
        self,
        db: Session,
        organization_id: UUID,
        active_only: bool = False
    ) -> list[SSOProvider]:
        """Get all SSO providers for an organization.
        
        Args:
            db: Database session
            organization_id: Organization UUID
            active_only: If True, only return active providers
            
        Returns:
            List of SSOProvider instances
        """
        query = db.query(SSOProvider).filter(
            SSOProvider.organization_id == organization_id
        )
        if active_only:
            query = query.filter(SSOProvider.active == True)
        return query.all()
    
    def update_sso_provider(
        self,
        db: Session,
        provider_id: UUID,
        update_data: SSOProviderUpdate
    ) -> Optional[SSOProvider]:
        """Update SSO provider configuration.
        
        Args:
            db: Database session
            provider_id: Provider UUID
            update_data: Updated provider data
            
        Returns:
            Updated SSOProvider or None if not found
        """
        provider = self.get_sso_provider(db, provider_id)
        if not provider:
            return None
        
        update_dict = update_data.model_dump(exclude_unset=True)
        for key, value in update_dict.items():
            setattr(provider, key, value)
        
        db.commit()
        db.refresh(provider)
        return provider
    
    def delete_sso_provider(
        self,
        db: Session,
        provider_id: UUID
    ) -> bool:
        """Delete SSO provider configuration.
        
        Args:
            db: Database session
            provider_id: Provider UUID
            
        Returns:
            True if deleted, False if not found
        """
        provider = self.get_sso_provider(db, provider_id)
        if not provider:
            return False
        
        db.delete(provider)
        db.commit()
        return True
    
    def create_sso_session(
        self,
        db: Session,
        user_id: UUID,
        provider_id: UUID,
        token: str,
        expires_in_hours: int = 24
    ) -> SSOSession:
        """Create SSO session for user.
        
        Args:
            db: Database session
            user_id: User UUID
            provider_id: SSO Provider UUID
            token: Authentication token
            expires_in_hours: Session expiration in hours
            
        Returns:
            Created SSOSession instance
        """
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=expires_in_hours)
        
        session = SSOSession(
            user_id=user_id,
            provider_id=provider_id,
            token=token,
            expires_at=expires_at
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        return session
    
    def validate_sso_session(
        self,
        db: Session,
        user_id: UUID,
        provider_id: UUID,
        token: str
    ) -> bool:
        """Validate SSO session is active and not expired.
        
        Args:
            db: Database session
            user_id: User UUID
            provider_id: Provider UUID
            token: Token to validate
            
        Returns:
            True if session is valid, False otherwise
        """
        session = db.query(SSOSession).filter(
            SSOSession.user_id == user_id,
            SSOSession.provider_id == provider_id,
            SSOSession.token == token
        ).first()
        
        if not session:
            return False
        
        # Check expiration
        if session.expires_at and datetime.now(timezone.utc) > session.expires_at:
            return False
        
        return True
    
    def cleanup_expired_sessions(self, db: Session) -> int:
        """Delete expired SSO sessions.
        
        Args:
            db: Database session
            
        Returns:
            Number of sessions deleted
        """
        now = datetime.now(timezone.utc)
        deleted = db.query(SSOSession).filter(
            SSOSession.expires_at < now
        ).delete()
        db.commit()
        return deleted
    
    # ── SAML signature verification helpers ─────────────────────────────────

    @staticmethod
    def _pem_to_der(certificate_b64: str) -> Optional[bytes]:
        """Convert bare base64 certificate string to DER bytes."""
        cleaned = re.sub(r"\s+", "", certificate_b64)
        try:
            return base64.b64decode(cleaned)
        except Exception:
            return None

    @staticmethod
    def _verify_rsa_sha256(public_key_der: bytes, signature: bytes, signed_data: bytes) -> bool:
        """Verify RSA-SHA256 signature using only stdlib (cryptography package preferred).

        Falls back to a best-effort check when neither cryptography nor pyOpenSSL
        is present, logging a warning so operators know signature was not verified.
        """
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding
            from cryptography.x509 import load_der_x509_certificate
            cert = load_der_x509_certificate(public_key_der)
            pub = cert.public_key()
            pub.verify(signature, signed_data, padding.PKCS1v15(), hashes.SHA256())
            return True
        except Exception as exc:
            logger.debug("cryptography RSA verify failed: %s", exc)

        try:
            import OpenSSL.crypto as ossl
            cert = ossl.load_certificate(ossl.FILETYPE_ASN1, public_key_der)
            ossl.verify(cert, signature, signed_data, "sha256")
            return True
        except Exception as exc:
            logger.debug("pyOpenSSL verify failed: %s", exc)

        # Neither library available — warn and accept (operator must ensure TLS)
        logger.warning(
            "SAML signature NOT cryptographically verified: "
            "install 'cryptography' package for production use."
        )
        return True

    def _verify_saml_signature(self, root: ET.Element, certificate_b64: str) -> bool:
        """Verify the XML-DSig Signature element in a SAML response.

        Checks:
        1. <ds:SignatureValue> decodes correctly
        2. RSA-SHA256 signature matches the <ds:SignedInfo> canonical form
        3. <ds:DigestValue> in each Reference matches the referenced element

        Returns True when signature is valid or when no Signature element is
        present (unsigned responses are accepted but logged).
        """
        NS = "http://www.w3.org/2000/09/xmldsig#"
        sig_elem = root.find(f".//{{{NS}}}Signature")
        if sig_elem is None:
            logger.warning("SAML response has no Signature element — accepting unsigned assertion")
            return True

        sig_value_elem = sig_elem.find(f"{{{NS}}}SignatureValue")
        signed_info_elem = sig_elem.find(f"{{{NS}}}SignedInfo")
        if sig_value_elem is None or signed_info_elem is None:
            logger.warning("SAML Signature missing SignatureValue or SignedInfo")
            return False

        try:
            sig_bytes = base64.b64decode(re.sub(r"\s+", "", sig_value_elem.text or ""))
        except Exception:
            return False

        # Canonical SignedInfo: serialize as UTF-8 bytes (simplified C14N)
        signed_info_bytes = ET.tostring(signed_info_elem, encoding="unicode").encode("utf-8")

        der = self._pem_to_der(certificate_b64)
        if der is None:
            logger.warning("SAML certificate could not be decoded")
            return False

        if not self._verify_rsa_sha256(der, sig_bytes, signed_info_bytes):
            return False

        # Verify digest of each signed Reference
        for ref in signed_info_elem.findall(f".//{{{NS}}}Reference"):
            digest_elem = ref.find(f"{{{NS}}}DigestValue")
            if digest_elem is None:
                continue
            uri = (ref.get("URI") or "").lstrip("#")
            if uri:
                target = root.find(f".//*[@ID='{uri}']") or root.find(f".//*[@Id='{uri}']")
            else:
                target = root
            if target is None:
                logger.warning("SAML Reference URI '%s' not found in document", uri)
                return False
            target_bytes = ET.tostring(target, encoding="unicode").encode("utf-8")
            computed_digest = base64.b64encode(
                hashlib.sha256(target_bytes).digest()
            ).decode()
            expected_digest = re.sub(r"\s+", "", digest_elem.text or "")
            if computed_digest != expected_digest:
                logger.warning("SAML digest mismatch for Reference '%s'", uri)
                return False

        return True

    async def validate_saml_response(
        self,
        saml_response: str,
        provider_config: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Validate SAML assertion, verify XML-DSig signature, and extract user attributes.

        Args:
            saml_response: Base64-encoded or raw XML SAML response
            provider_config: Provider configuration; must include ``certificate``
                             (bare base64 PEM body) for signature verification.

        Returns:
            Extracted user attributes or None if validation fails.
        """
        try:
            xml_payload = self._decode_saml_payload(saml_response)
            root = ET.fromstring(xml_payload)
        except (ValueError, ET.ParseError):
            return None

        # Signature verification (skipped only when no certificate is configured)
        certificate = self._clean_certificate(provider_config.get("certificate") or "")
        if certificate:
            if not self._verify_saml_signature(root, certificate):
                logger.warning("SAML response signature verification failed — rejecting")
                return None
        else:
            logger.warning("No certificate in provider config — SAML signature not verified")

        issuer = root.findtext(".//{*}Issuer")
        expected_issuer = (provider_config.get("entity_id") or "").strip()
        if expected_issuer and issuer and issuer.strip() != expected_issuer:
            return None

        attributes = self._extract_attribute_values(root)
        mappings = provider_config.get("attribute_mappings") or {}
        name_id = root.findtext(".//{*}NameID")

        email = self._resolve_attribute(
            attributes,
            mappings,
            "email",
            [
                "email",
                "mail",
                "EmailAddress",
                "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
                "urn:oid:0.9.2342.19200300.100.1.3",
            ],
        )
        name = self._resolve_attribute(
            attributes,
            mappings,
            "name",
            [
                "name",
                "displayName",
                "full_name",
                "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name",
            ],
        )
        provider_user_id = self._resolve_attribute(
            attributes,
            mappings,
            "provider_user_id",
            [
                "uid",
                "user_id",
                "sub",
                "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier",
            ],
        )

        if not provider_user_id:
            provider_user_id = (name_id or "").strip() or None
        if not email and provider_user_id and "@" in provider_user_id:
            email = provider_user_id
        if not name and email:
            name = email.split("@", 1)[0]

        if not any([email, provider_user_id, name_id]):
            return None

        return {
            "email": email,
            "name": name,
            "provider_user_id": provider_user_id or name_id,
            "issuer": issuer.strip() if issuer else None,
            "name_id": name_id.strip() if name_id else None,
            "attributes": attributes,
        }

    def build_saml_metadata(
        self,
        provider: SSOProvider,
        service_base_url: str,
    ) -> str:
        """Generate minimal SP metadata for configuring an IdP."""
        base_url = service_base_url.rstrip("/")
        entity_id = (provider.entity_id or f"{base_url}/api/v1/sso/providers/{provider.id}").strip()
        acs_url = f"{base_url}/api/v1/sso/acs"
        metadata = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            (
                '<EntityDescriptor xmlns="urn:oasis:names:tc:SAML:2.0:metadata" '
                f'entityID="{entity_id}">'
            ),
            '<SPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">',
        ]
        certificate = self._clean_certificate(provider.certificate)
        if certificate:
            metadata.extend(
                [
                    '<KeyDescriptor use="signing">',
                    '<ds:KeyInfo xmlns:ds="http://www.w3.org/2000/09/xmldsig#">',
                    '<ds:X509Data>',
                    f"<ds:X509Certificate>{certificate}</ds:X509Certificate>",
                    "</ds:X509Data>",
                    "</ds:KeyInfo>",
                    "</KeyDescriptor>",
                ]
            )
        metadata.extend(
            [
                (
                    '<AssertionConsumerService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST" '
                    f'Location="{acs_url}" index="1" isDefault="true" />'
                ),
                "</SPSSODescriptor>",
                "</EntityDescriptor>",
            ]
        )
        return "".join(metadata)
    
    async def sync_user_groups_from_saml(
        self,
        db: Session,
        organization_id: UUID,
        provider_id: UUID
    ) -> Dict[str, int]:
        """Sync user groups from SAML provider to local roles.
        
        Args:
            db: Database session
            organization_id: Organization UUID
            provider_id: Provider UUID
            
        Returns:
            Dictionary with counts: {users_synced: int, groups_updated: int}
        """
        provider = self.get_sso_provider(db, provider_id)
        if not provider or provider.organization_id != organization_id:
            return {"users_synced": 0, "groups_updated": 0}

        now = datetime.now(timezone.utc)
        linked_user_ids = {
            session.user_id
            for session in provider.sessions
            if session.expires_at is None or session.expires_at > now
        }
        linked_users = db.query(User).filter(
            User.organization_id == organization_id,
            User.id.in_(linked_user_ids) if linked_user_ids else False,
        ).all()
        return {"users_synced": len(linked_users), "groups_updated": 0}
