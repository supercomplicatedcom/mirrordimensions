# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Leaf certificates for each hostname in the world, signed by the install's root CA.

They are minted on the host, so the CA key never enters the gateway. They look like
certificates an internal corporate CA issues: issued some weeks ago, valid for a year,
the hostname as the only name, the same key usages a web server certificate carries.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from pydantic import BaseModel

from mirrordimensions.errors import MirrorError
from mirrordimensions.hostos.files import make_dir, write_bytes
from mirrordimensions.network.ca import CERT_FILE, KEY_FILE
from mirrordimensions.world import seeded


class Leaf(BaseModel):
    hostname: str
    pem: bytes  # certificate followed by its private key, as the gateway loads it


def load_ca(ca_dir: Path) -> tuple[x509.Certificate, rsa.RSAPrivateKey]:
    try:
        cert = x509.load_pem_x509_certificate((ca_dir / CERT_FILE).read_bytes())
        key = serialization.load_pem_private_key((ca_dir / KEY_FILE).read_bytes(), password=None)
    except OSError as exc:
        raise MirrorError(
            "The project's root CA is missing.",
            f"Could not read {ca_dir}: {exc.strerror}.",
            "Run mirror init in a new folder, or restore .mirror/ca/ from a backup.",
        ) from exc
    if not isinstance(key, rsa.RSAPrivateKey):
        raise MirrorError(
            "The root CA key is not an RSA key.", str(ca_dir), "Re-create the project."
        )
    return cert, key


def mint_leaf(
    ca_cert: x509.Certificate,
    ca_key: rsa.RSAPrivateKey,
    hostname: str,
    seed: int,
    now: datetime | None = None,
) -> Leaf:
    now = now or datetime.now(UTC)
    issued = (now - timedelta(days=seeded.between(seed, f"leaf-age:{hostname}", 20, 160))).replace(
        hour=seeded.between(seed, f"leaf-hour:{hostname}", 0, 23), minute=0, second=0, microsecond=0
    )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(issued)
        .not_valid_after(issued + timedelta(days=397))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )
    pem = cert.public_bytes(serialization.Encoding.PEM) + key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    return Leaf(hostname=hostname, pem=pem)


def ensure_leaves(ca_dir: Path, leaf_dir: Path, hostnames: list[str], seed: int) -> list[Leaf]:
    """Mint missing leaves and reuse existing ones, so a hostname keeps its certificate."""
    make_dir(leaf_dir, owner_only=True)
    ca_cert, ca_key = load_ca(ca_dir)
    leaves: list[Leaf] = []
    for hostname in sorted(set(hostnames)):
        path = leaf_dir / f"{hostname}.pem"
        if path.is_file():
            leaves.append(Leaf(hostname=hostname, pem=path.read_bytes()))
            continue
        leaf = mint_leaf(ca_cert, ca_key, hostname, seed)
        write_bytes(path, leaf.pem, owner_only=True)
        leaves.append(leaf)
    return leaves
