(how_to_force_https_redirect)=
(how-to-force-https-redirect)=
# Force HTTPS redirect

By default, the traefik charm sets up traefik in a way that allows both HTTP and HTTPS access.
To force HTTPS redirect, you need to modify the requirer charm's code.

```{note}
This feature was introduced in revision 127 ([PR#178](https://github.com/canonical/traefik-k8s-operator/pull/178)).
```

### Pack a charm with HTTPS redirection enabled
Let's take [alertmanager](https://github.com/canonical/alertmanager-k8s-operator) for example. It already imports and uses ingress per app:
```python
from charms.traefik_k8s.v1.ingress import IngressPerAppRequirer

# --snip--

        self.ingress = IngressPerAppRequirer(
            self, port=self.api_port
        )
```

All you need to do is add another constructor argument:

```python
        self.ingress = IngressPerAppRequirer(
            self, port=self.api_port, redirect_https=True
        )
```


### Set up a tls demo model
Deploy [traefik](https://charmhub.io/traefik-k8s/), [alertmanager](https://charmhub.io/alertmanager-k8s) and [self-signed-certificates](https://charmhub.io/self-signed-certificates), similar to how it is described in the "[TLS termination using a local ca](https://discourse.charmhub.io/t/traefik-k8s-docs-tls-termination-using-a-local-ca/10779)" tutorial.

[details=Detailed juju commands for setup]

```bash
# Your locally built charm with the new constructor arg
juju deploy ./alertmanager-k8s_ubuntu-20.04-amd64.charm alertmanager --resource alertmanager-image=ubuntu/prometheus-alertmanager:0.23-22.04_beta

# All the rest from charmhub
juju deploy --channel=edge traefik-k8s traefik --config external_hostname=demo.local
juju deploy --channel=edge self-signed-certificates ca

juju relate traefik ca
juju relate alertmanager traefik

juju show-unit --format json traefik/0 \
  | jq -r '."traefik/0"."relation-info"[0]."application-data".certificates' \
  | jq -r '.[0].certificate' > /tmp/local.cert
```
[/details]

### Verification
After relating the charms and storing the certificate locally, you should see a [`301 Moved Permanently`](https://en.wikipedia.org/wiki/HTTP_301)  when you try to curl port 80:

```bash
$ TRAEFIK_IP=$(\
  juju status --format json traefik \
  | jq -r ".applications.traefik.address"\
)

$ curl http://$TRAEFIK_IP/tls-demo-alertmanager/-/ready
Moved Permanently
```

Or, similarly,

```
$ curl --resolve "demo.local:80:$TRAEFIK_IP" \
   http://demo.local:80/tls-demo-alertmanager/-/ready
Moved Permanently
```

And now curl should be able to reach the endpoint, even though it's `http` and not `https`:

```bash
$ curl -L \
     --fail-with-body \
     --capath /tmp \
     --cacert /tmp/local.cert \
     http://demo.local/tls-demo-alertmanager/-/ready
OK
```

If you're using the `demo.local` example, you may need to temporarily add Traefik's IP to `/etc/hosts` to have `curl` match the cert when following the redirect:

```bash
$ cat /etc/hosts  
# --snip--
10.43.8.34 demo.local  # $TRAEFIK_IP
```

