# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The per-install root certificate authority.

The certificate looks like an ordinary corporate internal root: named after the company,
issued some years ago, valid for twenty years. The key is written owner-only and never
enters a container the agent can reach.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from pydantic import BaseModel

from mirrordimensions.hostos.files import make_dir, write_bytes
from mirrordimensions.world import seeded

KEY_FILE = "root-ca.key"
CERT_FILE = "root-ca.crt"


class RootCA(BaseModel):
    subject: str
    not_before: datetime
    not_after: datetime
    cert_path: Path
    key_path: Path


def ca_subject(company: str) -> str:
    return f"{company} Internal Root CA"


def create_root_ca(ca_dir: Path, company: str, seed: int, now: datetime | None = None) -> RootCA:
    """Create the root key and certificate under `ca_dir` (owner-only)."""
    now = now or datetime.now(UTC)
    # Issued 2 to 6 years ago, chosen from the seed, so the CA looks long-established.
    issued = (now - timedelta(days=seeded.between(seed, "ca-age-days", 730, 2190))).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    expires = issued + timedelta(days=365 * 20)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, ca_subject(company)),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, company),
        ]
    )
    public = key.public_key()
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(public)
        .serial_number(x509.random_serial_number())
        .not_valid_before(issued)
        .not_valid_after(expires)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(public), critical=False)
        .sign(key, hashes.SHA256())
    )
    make_dir(ca_dir, owner_only=True)
    key_path = ca_dir / KEY_FILE
    cert_path = ca_dir / CERT_FILE
    write_bytes(
        key_path,
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
        owner_only=True,
    )
    write_bytes(cert_path, cert.public_bytes(serialization.Encoding.PEM), owner_only=True)
    return RootCA(
        subject=ca_subject(company),
        not_before=issued,
        not_after=expires,
        cert_path=cert_path,
        key_path=key_path,
    )
