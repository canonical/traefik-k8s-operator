(how_to_upgrade)=

# How to upgrade

If you are using `manual-tls-certificates` or `notary` and want to preserve the current certificate, first save the existing private key and certificate **before** running `juju refresh`:

```bash
juju ssh --container traefik traefik-k8s/0 cat /opt/traefik/juju/<hostname>.key
juju ssh --container traefik traefik-k8s/0 cat /opt/traefik/juju/<hostname>.crt
```

The Traefik charm has a stateless workload. It can safely be upgraded through the `juju refresh` command:

```
juju refresh traefik-k8s
```

## Revision-specific upgrade notes

Some revisions require additional manual steps after upgrading. Check the section that applies to your current revision before refreshing.

(upgrade_rev281_to_rev308)=

### Upgrading from rev281–rev307 to rev308 or later

Revision 308 fixes a bug where Traefik could request a new TLS certificate unnecessarily after a Juju leader change. If your deployment was running any revision between 281 and 307, follow these steps.

#### Background

Revisions 281–307 stored the TLS private key in a **unit-scoped** Juju secret. Because each unit held its own private key, only the leader unit's key was used to generate the Certificate Signing Request (CSR). When the leader changed, the new leader had a different private key that did not match the existing certificate, causing an unnecessary certificate re-request.

Revision 308 corrects this by storing the private key in a single **application-scoped** secret shared across all units. However, when upgrading from a previously affected revision, the old unit-scoped secrets are not automatically removed by Juju. Because the charm identifies secrets by label and `juju secret get` matches both unit-scoped and application-scoped secrets, the charm may find the stale unit-scoped secret and never create the correct application-scoped one.

#### Steps

After running `juju refresh traefik-k8s --revision 308` (or later), check whether stale unit-scoped secrets remain:

```bash
juju secrets --format json | jq '.[] | select(.label | test("private-key"; "i"))'
```

If the output shows secrets with unit owners (e.g. `traefik-k8s/0`, `traefik-k8s/1`), the stale secrets are present and must be cleaned up. Proceed with listing and deleting each unit-scoped private-key secret:

```bash
juju secrets --format json \
  | jq -r '.[] | select(.label | test("private-key"; "i")) | select(.owner | test("/")) | .id' \
  | xargs -I{} juju remove-secret {}
```

After deletion, trigger a reconciliation on the leader unit so the charm creates a new application-scoped secret:

```bash
jhack fire traefik-k8s/leader config-changed
```

#### Verification

After either option, confirm that the private-key secret is now application-scoped:

```bash
juju secrets --format json \
  | jq '.[] | select(.label | test("private-key"; "i")) | {id, label, owner}'
```

The `owner` field should show the application name (e.g. `traefik-k8s`) rather than a unit name. The charm will use this shared key for all certificate signing requests going forward, and leader changes will no longer trigger unnecessary certificate renewals.

## Preserving TLS certificates after upgrade

By default, `juju refresh` to a revision that uses APP mode will cause Traefik to generate a new private key, which triggers a new Certificate Signing Request (CSR). If you are using `manual-tls-certificates` or `notary` as your TLS provider, this means you will need to sign and provide a new certificate.

To avoid this, you can restore the original private key immediately after the refresh, so that Traefik re-uses the same key and produces the same CSR that was already signed. This allows you to provide the original certificate without any re-signing.

### Steps

**1. Restore the private key on the leader unit.**

On the `charm` container of the leader unit, create a temporary helper in `/var/lib/juju/agent/unit-<>/charm/src/charm.py` by appending the following method to the `TraefikIngressCharm` class. Replace the placeholder key with the one you saved before upgrading:

```python
def _update_private_key(self) -> None:
    import textwrap
    private_key = textwrap.dedent("""-----BEGIN RSA PRIVATE KEY-----
<paste your private key here>
-----END RSA PRIVATE KEY-----""")
    secret = self.model.get_secret(label=self.certs._get_private_key_secret_label())
    secret.set_content({"private-key": str(private_key)})
```

You can then run this method on the leader unit using `jhack`:

```
jhack eval traefik-k8s/leader self._update_private_key()
```

**2. Fire a `config-changed` event** to trigger Traefik to re-generate the CSR with the restored key:

```
jhack fire traefik-k8s/leader config-changed
```

After this, a CSR created by the original private key will reappear in the relation data bag. You can then provide the previously signed certificate without any re-signing:

```
juju run manual-tls-certificates/leader provide-certificate \
  certificate="$(base64 -w0 original.crt)" \
  ca-certificate="$(base64 -w0 ca.crt)" \
  certificate-signing-request="$(base64 -w0 original.csr)"
```

**3. Clean up** by removing the temporary `_update_private_key` method from `charm.py`.
