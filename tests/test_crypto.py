"""PEM панели читается клиентами, содержит согласованные ключи и SAN."""

from __future__ import annotations

import ipaddress
from datetime import UTC, datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

from app.utils.crypto import generate_certificate, get_cert_SANs


def test_generated_certificate_matches_private_key():
    """Ошибка генерации, размера или подписи ломает подключение TLS-ноды."""
    pem = generate_certificate()
    cert = x509.load_pem_x509_certificate(pem["cert"].encode())
    key = serialization.load_pem_private_key(pem["key"].encode(), password=None)
    assert isinstance(key, rsa.RSAPrivateKey)
    assert key.key_size == 4096
    public_key = cert.public_key()
    assert public_key.public_numbers() == key.public_key().public_numbers()
    assert cert.subject == cert.issuer
    assert cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value == "Gozargah"
    assert cert.signature_hash_algorithm.name == "sha512"
    public_key.verify(cert.signature, cert.tbs_certificate_bytes, padding.PKCS1v15(), cert.signature_hash_algorithm)


def test_certificate_sans_preserve_dns_and_ip():
    """Чтение SAN сохраняет имя узла и IP, не подменяя тип адреса."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "node.example.test")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("node.example.test"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    assert get_cert_SANs(cert.public_bytes(serialization.Encoding.PEM)) == [
        "node.example.test",
        ipaddress.ip_address("127.0.0.1"),
    ]
