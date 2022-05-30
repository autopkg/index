# AutoPkg Recipe Index

**NOTE**: This repository is a work in progress, and is not yet connected to the `search` function of any AutoPkg release.

This repository hosts a GitHub Actions workflow that builds a JSON index of all recipes in the AutoPkg organization on GitHub, for the purpose of fast and accurate `autopkg search` functionality. The index is rebuilt every 4 hours.

The script that builds the index is `build_index.py`, and the workflow is defined in `.github/workflows/build.yml`.
