# Mandatory Config Options
model_name = "put your model-name here"

# Optional Configuration
channel = "put the charm channel here"
traefik-config = {
  enable_experimental_forward_auth = "put True here to enables `forward-auth` middleware capabilities as an experimental feature"
  external_hostname                = "put The DNS name to be used by Traefik ingress here"
  routing_mode                     = "The routing mode allows you to specify how Traefik going to generate routes: path or subdomain"
}