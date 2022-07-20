
# TODO replace websocket server with netcat


# With this command we can hit the websocket:
curl --include \
   --no-buffer \
   --header "Connection: Upgrade" \
   --header "Upgrade: websocket" \
   --header "Host: example.com:80" \
   --header "Origin: http://example.com:80" \
   --header "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
   --header "Sec-WebSocket-Version: 13" \
   http://[TCP_REQUIRER_MOCK_IP]:8000/ws -vv


# Attempting to hit the websocket via traefik:
curl --include \
   --no-buffer \
   --header "Connection: Upgrade" \
   --header "Upgrade: websocket" \
   --header "Host: example.com:80" \
   --header "Origin: http://example.com:80" \
   --header "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
   --header "Sec-WebSocket-Version: 13" \
   -H "Host: my.it:42" http://[TRAEFIK_IP]:8080 -vv
