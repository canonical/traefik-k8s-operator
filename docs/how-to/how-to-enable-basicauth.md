(how_to_enable_basicauth)=

# How to enable BasicAuth

```{note}
This feature is available in traefik-k8s starting from revision 206.
```

In order to enable BasicAuth in `traefik-k8s` you will need to:

# Generate a user string

First you will need to  generate a user string with the right format:
> `<username>:<hashed-password>`

where the password must be hashed with either MD5, SHA1, or BCrypt. 

We recommend using `htpasswd` to generate the user string:

> (on ubuntu) `$ sudo apt-get install apache2-utils`

> `$ htpasswd -nbB YOUR_USERNAME YOUR_PASSWORD`

For example, running with `admin/admin:
> `$ htpasswd -nbB admin admin`
> `admin:$2y$05$ChsVYFWoLO7YbNnRZSS2IeLcKzL1jgfdOdCfyhtz4tcPOvmTkQYPy `

```{note}TIP: Use a strong password.```


# Pass the user string to `traefik-k8s`

> `$ juju config traefik-k8s basic_auth_user='<YOUR_USER_STRING>'`

```{note} Remember to escape the user string! The hash can contain some odd characters that may confuse your shell.```

Wait for traefik to process the action and ta-da! you should now have enabled BasicAuth. Any url you try to access through this traefik instance will request the username/password combination you chose.

```{note} We don't yet support multiple users or per-route auth. Need that? [Let us know!](https://github.com/canonical/traefik-k8s-operator/issues) For the time being, you can consider deploying multiple `traefik`s to segment your namespace with separate user domains. ```

