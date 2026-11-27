(how_to_troubleshoot_gateway_address_unavailable)=

<!-- vale Canonical.007-Headings-sentence-case = NO -->

# How to troubleshoot "Gateway Address Unavailable"

<!-- vale Canonical.007-Headings-sentence-case = YES -->

Whenever Traefik is used to ingress your Kubernetes workloads, you risk encountering the dreaded
"Gateway Address Unavailable" message. This message means that Traefik has not been given an
external IP address by Kubernetes, so it cannot tell other applications where it can be reached.
This guide helps you find the cause and fix it.

```{warning}
In this article, we will assume that you are running MicroK8s on either a bare-metal or virtual machine.
If your setup differs from this, parts of the how-to guide may still apply, although you will need to
tailor the exact steps and commands to your setup.
```

## Overview

Traefik gets its external address from a Kubernetes service of type `LoadBalancer`, which is
backed by the [MetalLB MicroK8s addon](https://canonical.com/microk8s/docs/addon-metallb). Check
the following causes, in this order:

1. {ref}`Traefik was deployed without trust <gateway_no_trust>`
2. {ref}`The MetalLB addon isn't enabled <gateway_metallb_disabled>`
3. {ref}`No external IP address is assigned to the Traefik service <gateway_no_external_ip>`
4. {ref}`No available IP in the address pool <gateway_no_ip_in_pool>`
5. {ref}`Juju reverted the service type to ClusterIP <gateway_clusterip>`

When you have fixed the problem, go to {ref}`gateway_verification`. If none of these steps
help, see {ref}`gateway_getting_help`.

(gateway_no_trust)=

## Traefik was deployed without `--trust`

Traefik manages its own `LoadBalancer` Kubernetes service, which requires elevated
(cluster-scoped) Kubernetes permissions. If Traefik is deployed without the `--trust` flag (or
`juju trust` is not run afterwards), the charm cannot create or update this service. The
Kubernetes API answers with a `403 Forbidden` error, and the unit goes into `blocked` status.

Check with:

```bash
juju status
```

Confirm that Traefik was deployed without `trust` by checking that the Traefik unit is
`blocked` with the message ``Insufficient permissions, try: `juju trust <traefik> --scope=cluster` ``,
and that `juju debug-log` shows the error
`Insufficient permissions to reconcile the LoadBalancer service, is the charm deployed with --trust?`.

Fix it by granting trust. The charm then reconciles the service on the next event:

```bash
juju trust <traefik> --scope=cluster
```

(gateway_metallb_disabled)=

## The MetalLB addon isn't enabled

Check with:

```bash
microk8s status -a metallb
```

If it is disabled, you can enable it with:

```bash
IPADDR=$(ip -4 -j route get 2.2.2.2 | jq -r '.[] | .prefsrc')
microk8s enable metallb:$IPADDR-$IPADDR
```

This command will fetch the IPv4 address assigned to your host, and hand it to MetalLB as an assignable IP. If the address range you want to hand to MetalLB differs from your host IP, alter the `$IPADDR` variable to instead specify the range you want to assign, for instance `IPADDR=10.0.0.1-10.0.0.100`.

(gateway_no_external_ip)=

## No external IP address is assigned to the Traefik service

Check whether the Traefik service has an external IP assigned to it:

```bash
JUJU_APP_NAME="traefik"
kubectl get svc -A -o wide | grep -E "^NAMESPACE|$JUJU_APP_NAME"
```

The `TYPE` column must read `LoadBalancer`, and the `EXTERNAL-IP` column must contain an
address rather than `<pending>` or `<none>`. See {ref}`gateway_verification` for an example.

Depending on what you see:

- `TYPE` is `ClusterIP`: follow {ref}`gateway_clusterip`.
- `EXTERNAL-IP` is `<pending>`: MetalLB has no address to give. Follow
  {ref}`gateway_no_ip_in_pool`.
- The service is missing entirely: follow {ref}`gateway_no_trust`.

(gateway_no_ip_in_pool)=

## No available IP in the address pool

The number of services requiring a `LoadBalancer` IP address is higher than the number of IP
addresses allocated to the MetalLB pool.

This frequently happens when:

- MetalLB has only one IP in its range but you deployed two instances of Traefik, or Traefik is forcefully removed (`--force --no-wait`) and then a new Traefik app is deployed immediately after.
- The [`ingress`](https://canonical.com/microk8s/docs/addon-ingress) addon is enabled. It's possible that NGINX from the ingress addon has claimed the ExternalIP.

Check with:

```bash
kubectl get ipaddresspool -n metallb-system -o yaml && kubectl get all -n metallb-system
```

To see which services already hold an address:

```bash
kubectl get svc -A | grep LoadBalancer
```

Fix it by freeing an address or by giving MetalLB a larger range:

- **Free an address.** If a `LoadBalancer` service that you no longer need holds the address,
  remove the application that owns it. If NGINX from the `ingress` addon has claimed the address,
  disable it with `microk8s disable ingress`, then disable and re-enable MetalLB.
- **Extend the range.** If every address in the pool is in use by services that you need,
  re-enable MetalLB with a larger range:

  ```bash
  FROM_IP="..."
  TO_IP="..."
  microk8s enable metallb:$FROM_IP-$TO_IP
  ```

  ```{warning}
  The range must be routable from the clients that will reach Traefik, and must not overlap with
  addresses used by other hosts or by your DHCP server.
  ```

(gateway_clusterip)=

## Juju reverted the service type to `ClusterIP`

Juju controller cycling may cause the type to revert from `LoadBalancer` back to `ClusterIP`.

Check with:

```bash
kubectl get svc -A -o wide | grep -E "^NAMESPACE|LoadBalancer"
```

If Traefik isn't listed (it's not `LoadBalancer`), recreate the pod to have the charm retrigger
the assignment of the external IP:

```bash
kubectl delete pod -n <model-name> <traefik-app-name>-0
```

Kubernetes recreates the pod, and the service should be `LoadBalancer` again.

(gateway_verification)=

## Verification

Verify that the Traefik Kubernetes service now has been assigned an external IP:

```{terminal}
microk8s.kubectl get services -A

NAMESPACE         NAME                     TYPE           CLUSTER-IP       EXTERNAL-IP                 PORT(S)
cos               traefik                  LoadBalancer   10.152.183.130   10.70.43.245                80:32343/TCP,443:30698/TCP   4d3h
                                                                                👆 - This one!
                                                                                
```

Verify that Traefik is functioning correctly by trying to trigger one of your paths. If you have COS Lite deployed, you may check that if works as expected using the Catalogue charm:

```
curl http://<TRAEFIKS_EXTERNAL_IP>/<YOUR_MODEL_NAME>-catalogue/
```

For example, `curl http://10.70.43.245/cos-catalogue/`.

This command should return a long HTML code block if everything works as expected.

(gateway_getting_help)=

## Getting help

If the problem persists,
[file an issue](https://github.com/canonical/traefik-k8s-operator/issues) or ask for help on the
[Matrix chat](https://matrix.to/#/#charmhub-charmdev:ubuntu.com). Include the output of:

```bash
juju status
juju debug-log --replay --include <traefik-app-name>
kubectl get svc -A -o wide
kubectl get ipaddresspool -n metallb-system -o yaml
```
