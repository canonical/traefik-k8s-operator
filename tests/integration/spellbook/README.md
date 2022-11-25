# About this folder
In `conftest.py` there's a `build_charm_or_fetch_cached` function that:

- checks if a `<charm-name>.charm` file is present in this folder
- if so, returns that package
- if not, builds the charm and puts it here, then returns the package

This means that you can iterate on test code quickly, but whenever there's changes to the charm code, you'll need to clear the cache manually.

You can enable using the cache by (temporarily) setting `conftest.CACHE_CHARMS = True`.
This feature is by default disabled.