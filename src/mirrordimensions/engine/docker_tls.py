# SPDX-License-Identifier: Apache-2.0
"""Mutual TLS for an engine whose Docker API listens on TCP (the wsl driver, decision 0003).

`mirror engine setup` makes a private CA, a server certificate for 127.0.0.1 that the
engine's Docker daemon presents, and a client certificate only the host's control plane
holds. The daemon refuses any connection without that client certificate. The CA's key is
not kept: nothing needs to sign again until the engine is set up again.
"""

from __future__ import annotations

import datetime
import ipaddress
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from mirrordimensions.hostos.files import make_dir, write_text

VALID_DAYS = 3650
# The host's copies, in the file names Docker's own clients use.
CA_FILE, CERT_FILE, KEY_FILE = "ca.pem", "cert.pem", "key.pem"


@dataclass(frozen=True)
class ServerFiles:
    """What the engine's daemon needs, as text to write into the engine."""

    ca: str
    cert: str
    key: str


def _pem_key(key: ec.EllipticCurvePrivateKey) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def _pem_cert(cert: x509.Certificate) -> str:
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def _name(common: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common)])


def _leaf(
    ca: x509.Certificate,
    ca_key: ec.EllipticCurvePrivateKey,
    common: str,
    usage: x509.ObjectIdentifier,
    now: datetime.datetime,
    ip: str | None = None,
) -> tuple[x509.Certificate, ec.EllipticCurvePrivateKey]:
    key = ec.generate_private_key(ec.SECP256R1())
    builder = (
        x509.CertificateBuilder()
        .subject_name(_name(common))
        .issuer_name(ca.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=VALID_DAYS))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([usage]), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
    )
    if ip is not None:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(ip))]),
            critical=False,
        )
    return builder.sign(ca_key, hashes.SHA256()), key


def create(client_dir: Path, address: str = "127.0.0.1") -> ServerFiles:
    """Write the client's files (owner-only) and return the server's."""
    now = datetime.datetime.now(datetime.UTC)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca = (
        x509.CertificateBuilder()
        .subject_name(_name("engine docker CA"))
        .issuer_name(_name("engine docker CA"))
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=VALID_DAYS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
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
        .sign(ca_key, hashes.SHA256())
    )
    server, server_key = _leaf(ca, ca_key, "engine", ExtendedKeyUsageOID.SERVER_AUTH, now, address)
    client, client_key = _leaf(ca, ca_key, "control plane", ExtendedKeyUsageOID.CLIENT_AUTH, now)
    make_dir(client_dir, owner_only=True)
    write_text(client_dir / CA_FILE, _pem_cert(ca))
    write_text(client_dir / CERT_FILE, _pem_cert(client))
    write_text(client_dir / KEY_FILE, _pem_key(client_key), owner_only=True)
    return ServerFiles(ca=_pem_cert(ca), cert=_pem_cert(server), key=_pem_key(server_key))


def client_files(client_dir: Path) -> tuple[str, str, str] | None:
    """(ca, cert, key) paths, or None when setup has not made them."""
    paths = [client_dir / name for name in (CA_FILE, CERT_FILE, KEY_FILE)]
    if not all(p.is_file() for p in paths):
        return None
    return str(paths[0]), str(paths[1]), str(paths[2])
