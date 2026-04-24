COUNT=0
while [ 3 -gt $COUNT ]; do
    if juju wait-for application traefik --query='status=="active"' --timeout=1m && juju wait-for application traefik-rgw --query='status=="active"' --timeout=1m; then
      ((COUNT++))
      echo "Both applications are active. Current count: $COUNT"
    else
      COUNT=0
    fi
    sleep 10
done
