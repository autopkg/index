# AutoPkg Recipe Index

[![build](https://github.com/autopkg/index/actions/workflows/build.yml/badge.svg)](https://github.com/autopkg/index/actions/workflows/build.yml)

This repository hosts a GitHub Actions workflow that builds a JSON index of all recipes in the AutoPkg organization on GitHub, for the purpose of fast and accurate `autopkg search` functionality. The index is also used by [Recipe Robot](https://github.com/homebysix/recipe-robot).

The index is rebuilt every 4 hours. The script that builds the index is `build_index.py`, and the workflow is defined in `.github/workflows/build.yml`.
