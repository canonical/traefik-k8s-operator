---
myst:
  html_meta:
    "description lang=en": "Cryptographic technology used by the Traefik charm, including TLS settings, private key generation, and BasicAuth password hashing."
---

(reference_cryptography)=

# Cryptographic overview

This page describes how the Traefik charm uses cryptographic technology, and which parameters
are set by the charm or can be configured by the user. Use it to assess the exposure of the
charm to cryptographic attack vectors.

The following topics are out of scope:

- The cryptographic implementation of the Traefik workload itself. Refer to the
  [Traefik documentation](https://doc.traefik.io/traefik/).
- Encryption of data at rest.

For an overview of how TLS is applied to traffic flowing through Traefik, see
{ref}`explanation_tls`. For security best practices, see {ref}`explanation_security`.

## TLS termination

When upstream TLS is enabled, Traefik terminates TLS for every route it serves. The charm
renders the following TLS options into Traefik's dynamic configuration. These values are
hardcoded, are based on
[Mozilla's intermediate compatibility profile](https://wiki.mozilla.org/Security/Server_Side_TLS#Intermediate_compatibility_.28recommended.29),
and are not user-configurable:

- Minimum TLS version: TLS 1.2. TLS 1.3 is also supported.
- Elliptic curve preferences: `X25519`, `CurveP256`, `CurveP384`.
- Cipher suites for TLS 1.2:
  - `TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256`
  - `TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256`
  - `TLS_ECDHE_ECDSA_WITH_AES_256_GCM_SHA384`
  - `TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384`
  - `TLS_ECDHE_ECDSA_WITH_CHACHA20_POLY1305`
  - `TLS_ECDHE_RSA_WITH_CHACHA20_POLY1305`

TLS 1.3 cipher suites aren't configurable in Traefik and use the Go standard library defaults.

## Certificates and private keys

The charm can get a server certificate in one of two ways.

### The `certificates` integration

When integrated with a certificate provider over the
[`certificates`](https://charmhub.io/traefik-k8s/integrations#certificates) relation, the charm
uses the [`tls_certificates` charm library](https://github.com/canonical/tls-certificates-interface),
which relies on the [`cryptography`](https://pypi.org/project/cryptography/) Python package, to:

- Generate an RSA private key with the `rsa.generate_private_key` function, using the following
  hardcoded parameters:
  - `key_size = 2048`
  - `public_exponent = 65537`
- Sign the certificate signing request (CSR) with SHA-256.

A single private key is generated for the application and stored in a Juju secret owned by the
application. The leader unit shares the issued certificates with the other units through the peer
relation, and the private key through a Juju secret. Private keys are never written to relation
data in plain text. To serve TLS, the charm writes the certificate and private key to the
`/opt/traefik/juju/` directory in the Traefik workload container.

The subject of the CSR can be customized with the `csr-subject-attributes` configuration option.

### The `tls-cert`, `tls-key`, and `tls-ca` configuration options

Alternatively, the user can provide a certificate, private key, and CA certificate directly with
the `tls-cert`, `tls-key`, and `tls-ca` configuration options. The charm doesn't generate or
validate the key's algorithm or size, so the user is responsible for providing a key that meets
their security requirements.

```{warning}
Juju configuration values aren't stored as secrets. Any user with access to the model's
configuration can read the private key passed through `tls-key`. Prefer the `certificates`
integration where possible.
```

## Trust of downstream applications

When an application requiring ingress uses the `https` scheme, Traefik verifies the
application's certificate. Certificate verification is always enabled (`insecureSkipVerify`
is `false`) and can't be disabled through the charm.

CA certificates received over the `receive-ca-cert` relation, and the CA certificate of
Traefik's own certificate, are installed into the workload container's system trust store with
`update-ca-certificates`. Traefik uses this trust store to verify downstream applications.

## BasicAuth

The `basic_auth_user` configuration option enables the
[BasicAuth middleware](https://doc.traefik.io/traefik/reference/routing-configuration/http/middlewares/basicauth/)
on all routes. The option accepts a `<username>:<hashed-password>` string. The charm doesn't hash
the password itself, but passes the string as-is to Traefik, which supports the following hashing
algorithms:

- bcrypt
- SHA1
- MD5

We recommend using bcrypt, for example by running `htpasswd -nbB <username> <password>`. MD5
and SHA1 are considered weak and should be avoided. See {ref}`how_to_enable_basicauth`.

BasicAuth credentials are sent in every request, so only enable BasicAuth together with upstream
TLS.

## Packages and technology used

| Purpose | Package or tool | Details |
| --- | --- | --- |
| TLS termination and origination | Traefik workload (Go `crypto/tls`) | TLS 1.2 minimum, cipher suites and curves listed above |
| Private key generation | [`cryptography`](https://github.com/pyca/cryptography/) through the `tls_certificates` library | RSA, 2048 bits, public exponent 65537 |
| CSR signing | [`cryptography`](https://github.com/pyca/cryptography/) through the `tls_certificates` library | SHA-256 |
| Private key storage | Juju secrets | Application-owned secret |
| Trust of downstream CA certificates | `update-ca-certificates` | System trust store in the workload container |
| BasicAuth password hashing | Provided by the user, for example with `htpasswd` | bcrypt (recommended), SHA1, or MD5 |
