from cryptography import x509
from cryptography.x509.oid import ExtensionOID

from fleasion import linux_proxy_helper_daemon, macos_proxy_helper_daemon
from fleasion.proxy.server import CLIENT_SETTINGS_HOSTS, INTERCEPT_HOSTS
from fleasion.utils.certs import generate_ca, generate_multi_host_cert


def test_all_hosts_file_proxy_hosts_have_certificate_coverage(tmp_path):
    """Keep proxy-host allowlists and the fallback TLS certificate in sync."""
    assert CLIENT_SETTINGS_HOSTS <= INTERCEPT_HOSTS
    assert macos_proxy_helper_daemon.ALLOWED_HOSTS == set(INTERCEPT_HOSTS)
    assert linux_proxy_helper_daemon.ALLOWED_PROXY_HOSTS == INTERCEPT_HOSTS

    ca_cert_path, ca_key_path = generate_ca(tmp_path)
    cert_path, _key_path = generate_multi_host_cert(
        "intercept-default",
        INTERCEPT_HOSTS,
        ca_cert_path,
        ca_key_path,
        tmp_path,
    )
    certificate = x509.load_pem_x509_certificate(cert_path.read_bytes())
    san_hosts = {
        name.value.lower()
        for name in certificate.extensions.get_extension_for_oid(
            ExtensionOID.SUBJECT_ALTERNATIVE_NAME
        ).value
        if isinstance(name, x509.DNSName)
    }

    assert san_hosts == set(INTERCEPT_HOSTS)
