# AutoPkg Recipe Index

[![build](https://github.com/autopkg/index/actions/workflows/build.yml/badge.svg)](https://github.com/autopkg/index/actions/workflows/build.yml)

This repository hosts a GitHub Actions workflow that builds a JSON index of all recipes in the AutoPkg organization on GitHub and powers fast and accurate `autopkg search` functionality (since AutoPkg v2.9.0). The index is also used by [Recipe Robot](https://github.com/homebysix/recipe-robot) (since v2.3.0).

The index is rebuilt every 4 hours by `build_index.py`, and the workflow is defined in `.github/workflows/build.yml`.
