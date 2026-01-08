(how_to_enable_basicauth)=

# How to enable BasicAuth

```{note}
This feature is available in traefik-k8s starting from revision 206.
```

In order to enable BasicAuth in `traefik-k8s` you will need to:

## Generate a user string

First you will need to  generate a user string with the format
`<username>:<hashed-password>`,
where the password must be hashed with either MD5, SHA1, or BCrypt. 

We recommend using `htpasswd` to generate the user string:

```
htpasswd -nbB YOUR_USERNAME YOUR_PASSWORD
```

For example, running with `admin/admin`:

```{terminal}
htpasswd -nbB admin admin

admin:$2y$05$ChsVYFWoLO7YbNnRZSS2IeLcKzL1jgfdOdCfyhtz4tcPOvmTkQYPy
```

```{tip}
Use a strong password.
```

## Pass the user string to `traefik-k8s`

```
juju config traefik-k8s basic_auth_user='<YOUR_USER_STRING>'
```

```{note}
Remember to escape the user string! The hash can contain some odd characters that may confuse your shell.
```

Wait for Traefik to process the action, and now you should now have enabled BasicAuth. Any URL you try to access through this Traefik instance will request the username and password combination you chose.

```{note}
We don't yet support multiple users or per-route auth. Need that? [Let us know!](https://github.com/canonical/traefik-k8s-operator/issues)

For the time being, you can consider deploying multiple `traefik`s to segment your namespace with separate user domains.
```

