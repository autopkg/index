#!/bin/env python3
# encoding: utf-8

# Copyright 2022-2025 Elliot Jordan
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""build_index.py

Clones all active repos in the AutoPkg organization, then builds an index
based on the recipes' metadata.
"""


import json
import os
import plistlib
import re
import subprocess
from glob import glob
from xml.parsers.expat import ExpatError

import requests
import yaml


def get_all_repos():
    """Get API data on all repos in AutoPkg org."""
    repos = []
    url = "https://api.github.com/orgs/autopkg/repos"
    headers = {
        "user-agent": "autopkg-search-index/0.0.1",
        "accept": "application/vnd.github.v3+json",
        "authorization": f"token {os.environ['PA_TOKEN']}",
    }

    # Loop through paginated results until there are no more pages
    page = 1
    while True:
        params = {"per_page": "100", "page": page}
        response = requests.get(url, params=params, headers=headers).json()
        if not response:
            break
        repos.extend(response)
        page += 1

    # Filter out repos that are archived, private, or otherwise skippable
    excl_reasons = ("private", "fork", "archived", "disabled", "is_template")
    repos = [x for x in repos if not any([x.get(r) for r in excl_reasons])]
    excl_names = ("autopkg/autopkg", "autopkg/index")
    repos = [x for x in repos if x["full_name"] not in excl_names]

    return repos


def clone_all_repos(repos):
    """Clone repos that are not private, archived, or otherwise skippable"""
    for repo in repos:
        if os.path.isdir(f"repos/{repo['full_name']}"):
            continue
        clone_cmd = [
            "git",
            "clone",
            "--depth=1",
            repo["clone_url"],
            f"repos/{repo['full_name']}",
        ]
        subprocess.run(clone_cmd, check=True)


def resolve_var(recipe_dict, var_name):
    """Given a variable name wrapped in percents, resolve to the actual variable value."""

    var_name = var_name.strip("%")
    return recipe_dict.get("Input", {}).get(var_name)


def build_search_index(repos):
    """Given a list of repo info from the GitHub API, build recipe search index."""
    index = {
        "identifiers": {},
        "shortnames": {},
    }
    children = []
    parsing_errors = []
    for repo in repos:
        # Find recipe files up to 2 levels deep
        recipes = glob(f"repos/{repo['full_name']}/*/*.recipe")
        recipes += glob(f"repos/{repo['full_name']}/*/*/*.recipe")
        recipes += glob(f"repos/{repo['full_name']}/*/*.recipe.plist")
        recipes += glob(f"repos/{repo['full_name']}/*/*/*.recipe.plist")
        recipes += glob(f"repos/{repo['full_name']}/*/*.recipe.yaml")
        recipes += glob(f"repos/{repo['full_name']}/*/*/*.recipe.yaml")

        # Filter out any directories
        recipes = [r for r in recipes if os.path.isfile(r)]

        # Get indexable data from recipe files
        for recipe in recipes:
            index_entry = {}
            if recipe.endswith(".yaml"):
                try:
                    with open(recipe, "rb") as openfile:
                        recipe_dict = yaml.safe_load(openfile)
                except yaml.scanner.ScannerError as e:
                    error_msg = f"Unable to parse {recipe} as YAML: {e}"
                    print(f"::warning file={recipe}::{error_msg}")
                    parsing_errors.append(error_msg)
                    continue
                if recipe_dict is None:
                    error_msg = f"Empty or invalid YAML file: {recipe}"
                    print(f"::warning file={recipe}::{error_msg}")
                    parsing_errors.append(error_msg)
                    continue
            else:
                try:
                    with open(recipe, "rb") as openfile:
                        recipe_dict = plistlib.load(openfile)
                except (plistlib.InvalidFileException, ExpatError, ValueError) as e:
                    error_msg = f"Unable to parse {recipe} as plist: {e}"
                    print(f"::warning file={recipe}::{error_msg}")
                    parsing_errors.append(error_msg)
                    continue
                if recipe_dict is None:
                    error_msg = f"Empty or invalid plist file: {recipe}"
                    print(f"::warning file={recipe}::{error_msg}")
                    parsing_errors.append(error_msg)
                    continue

            # Generally applicable metadata
            input_dict = recipe_dict.get("Input", {})
            index_entry["name"] = input_dict.get("NAME")
            index_entry["description"] = recipe_dict.get("Description")
            index_entry["repo"] = repo["full_name"]
            index_entry["path"] = os.path.relpath(recipe, f"repos/{repo['full_name']}")
            if recipe_dict.get("ParentRecipe"):
                index_entry["parent"] = recipe_dict["ParentRecipe"]
                children.append(
                    (recipe_dict["Identifier"], recipe_dict["ParentRecipe"])
                )
            if any(
                [
                    x.get("Processor") == "DeprecationWarning"
                    for x in recipe_dict.get("Process", [{}])
                ]
            ):
                index_entry["deprecated"] = True

            # Get inferred type of recipe
            type_pattern = r"\/([\w\- ]+\.([\w\- ]+))\.recipe(\.yaml|\.plist)?$"
            match = re.search(type_pattern, index_entry["path"])
            if match:
                index_entry["shortname"] = match.group(1)
                index_entry["inferred_type"] = match.group(2)

            # Munki-specific metadata
            if index_entry.get("inferred_type") == "munki":
                pkginfo = input_dict.get("pkginfo", {})
                index_entry["munki_display_name"] = pkginfo.get("display_name")
                index_entry["munki_description"] = pkginfo.get("description")

            # Jamf-specific metadata
            if index_entry.get("inferred_type") in ("jss", "jamf"):
                index_entry["jamf_display_name"] = input_dict.get(
                    "SELF_SERVICE_DISPLAY_NAME"
                )
                index_entry["jamf_description"] = input_dict.get(
                    "SELF_SERVICE_DESCRIPTION"
                )

            # Resolve any substitution variables in the index entry
            for k, v in index_entry.items():
                if isinstance(v, str) and v.startswith("%") and v.endswith("%"):
                    index_entry[k] = resolve_var(recipe_dict, v)

            # Save entry to identifier index
            index["identifiers"][recipe_dict.get("Identifier")] = index_entry

            # Save entry to shortnames index
            if index_entry.get("shortname"):
                if index_entry["shortname"] in index["shortnames"]:
                    index["shortnames"][index_entry["shortname"]].append(
                        recipe_dict.get("Identifier")
                    )
                else:
                    index["shortnames"][index_entry["shortname"]] = [
                        recipe_dict.get("Identifier")
                    ]

    # Add children list to parent recipes' index entries
    for child in children:
        if child[1] not in index["identifiers"]:
            print(f"WARNING: {child[0]} refers to missing parent recipe {child[1]}.")
        else:
            if "children" in index["identifiers"][child[1]]:
                index["identifiers"][child[1]]["children"].append(child[0])
            else:
                index["identifiers"][child[1]]["children"] = [child[0]]

    # Report parsing errors and potentially fail
    if parsing_errors:
        print(f"\n::warning::Found {len(parsing_errors)} recipe parsing errors:")
        for error in parsing_errors:
            print(f"  - {error}")

    # Write index file
    with open("index.json", "w", encoding="utf-8") as openfile:
        openfile.write(json.dumps(index, indent=2))

    return len(parsing_errors)


def main():
    """Main process."""

    # Set http.postBuffer to 1 GB
    gitconfig_cmd = ["git", "config", "--global", "http.postBuffer", "1024M"]
    subprocess.run(gitconfig_cmd, check=False)

    # Get repo info from GitHub API
    repos = get_all_repos()

    # Clone all repos
    clone_all_repos(repos)

    # Build and write search index
    error_count = build_search_index(repos)

    # Exit with error code if there were parsing errors (optional)
    if error_count > 0:
        print(f"::notice::Index build completed with {error_count} parsing errors")
        raise SystemExit(f"Build failed due to {error_count} recipe parsing errors")


if __name__ == "__main__":
    main()
