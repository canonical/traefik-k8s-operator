(how_to_contribute)=

# How to contribute

```{note}
See [CONTRIBUTING.md](https://github.com/canonical/traefik-k8s-operator/blob/main/CONTRIBUTING.md)
for information on contributing to the source code.
```

Our documentation is stored in the `docs` directory alongside the [source code on GitHub](https://github.com/canonical/traefik-k8s-operator/).
It is based on the Canonical starter pack
and hosted on [Read the Docs](https://about.readthedocs.com/). In structuring,
the documentation employs the [Diátaxis](https://diataxis.fr/) approach.

Click on the "Contribute to this page" icon at the top of each page to propose changes. This button
will bring you directly to the source on GitHub. Similarly, you may click on "Give feedback" to provide
suggestions or feedback about any page in the documentation.

On GitHub, you may open a pull request with your documentation changes, or you can
[file a bug](https://github.com/canonical/traefik-k8s-operator/issues) to provide constructive feedback or suggestions.

For syntax help and guidelines,
refer to the
{ref}`Canonical MyST style guide <starter-pack:myst_style_guide>`.

To run the documentation locally before submitting your changes:

```bash
cd docs
make run
```

## Automatic checks

GitHub runs automatic checks on the documentation
to verify spelling, validate links and style guide compliance.

You can (and should) run the same checks locally:

```bash
make spelling
make linkcheck
make vale
make lint-md
```