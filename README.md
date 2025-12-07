# AutoPkg Recipe Index

[![build](https://github.com/autopkg/index/actions/workflows/build.yml/badge.svg)](https://github.com/autopkg/index/actions/workflows/build.yml)

This repository hosts a GitHub Actions workflow that builds a JSON index of all recipes in the AutoPkg organization on GitHub, for the future goal of fast and accurate `autopkg search` functionality. The index is used by [Recipe Robot](https://github.com/homebysix/recipe-robot) (since v2.3.0).

The index is rebuilt every 4 hours. The script that builds the index is `build_index.py`, and the workflow is defined in `.github/workflows/build.yml`.

This is a test edit.
