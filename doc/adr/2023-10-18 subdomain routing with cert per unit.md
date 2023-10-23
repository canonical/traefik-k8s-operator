# Obtain a separate cert per every unit when using subdomain routing

## Context and Problem Statement
Until now, the TLS cert solution was designed with only path routing in mind.
When using Traefik in the subdomain routing mode, all Ingress will use
Traefik's default certificate, because charm code only obtains one cert (for
the external hostname), and traefik obviously cannot match that cert with
subdomains.

https://github.com/canonical/traefik-k8s-operator/issues/244

## Considered Options

- One cert per app/unit (no wildcards)
- Only one cert (as many wildcard SANs as necessary)
- Only one cert (keep appending subdomains; no wildcards)
- One cert per app (wildcard SANs only for ingress-per-unit)
- One cert per app (keep appending IPU subdomains; no wildcards)

## Decision Outcome

Chosen option: "One cert per app/unit (no wildcards)", because we must support
the use-case of strict subdomain routing (no wildcards).

### Consequences

* Good, because no wildcard certs (more secure).
* Good, because not limited by SAN count per cert.
* Bad, because may get rate limited by the CA.
  * IPA: new CSR (CRR) for every added (removed) app
  * IPU: new CSR (CRR) for every added (removed) unit
* Bad, because if we are not careful, the rate limit could break the only cert
  in use.

## Pros and Cons of the Options

### One cert per app/unit (no wildcards)
```
IPA: model-app.example.com
IPU: model-app-0.example.com

SAN example: model-app-0.example.com
```

* Good, because no wildcard certs (more secure).
* Good, because not limited by SAN count per cert.
* Bad, because may get rate limited by the CA.

### Only one cert (as many wildcard SANs as necessary)
```
IPA: model-app.example.com
IPU: model-app-0.example.com

SAN example: *.example.com
```

* Good, because won't get rate limited by the CA.
* Good, because simple to implement.
* Bad, because the number of SANs per cert is limited.
* Bad, because a wildcard cert is too permissive.

### Only one cert (keep appending subdomains; no wildcards)
```
IPA: model-app.example.com
IPU: model-app-0.example.com

SAN example: app1.example.com, app2.example.com
```

* Good, because no wildcard certs (more secure).
* Bad, because the number of SANs per cert is limited.
* Bad, because may get rate limited by the CA.
* Bad, because depends on the order things are done on an ACME server: if the
  server first revokes the previous certificate, it could create outages.

### One cert per app (wildcard SANs only for ingress-per-unit)
```
IPA: app.model.example.com
IPU: app-0.app.model.example.com

SAN example (IPA): app.model.example.com
SAN example (IPU): *.app.model.example.com
```

* Bad, because the number of SANs per cert is limited.
* Bad, because may get rate limited by the CA.

### One cert per app (keep appending IPU subdomains; no wildcards)
```
IPA: model-app.example.com
IPU: model-app-0.example.com

SAN example (IPA): app1.model.example.com
SAN example (IPU): app2-0.app2.model.example.com, app2-1.app2.model.example.com
```

* Good, because no wildcard certs (more secure).
* Bad, because the number of SANs per cert is limited.
* Bad, because may get rate limited by the CA.


## More Information

```bash
# Count SANs with:
echo | openssl s_client -showcerts -connect google.com:443 | openssl x509 -noout -text | grep DNS | tr ',' '\n' | wc -l
```

- Google has 134 subdomains in one cert (and they also use wildcard SANs)
- Wikipedia has 41 subdomains in one cert (and they also use wildcard SANs)
- Wordpress and blogger have wildcard SAN.
- StackExchange projects have wildcard SAN.
- Government and bank websites have a separate cert per subdomain (and they do not use wildcard SANs)
- Let's Encrypt limits to 100 SANs per cert ([ref](https://community.letsencrypt.org/t/why-sans-are-limited-to-100-domains-only/154930))
- Wildcard certs don't allow HTTP challenge, nor ALPN validation using ACME
  protocol, only DNS challenge is supported
  (https://letsencrypt.org/docs/challenge-types/).
- For now, the only `tls-certificates` providers in the ecosystem are using the
  DNS-01 challenge.
