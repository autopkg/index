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

"""build.py

Clones all active repos in the AutoPkg organization, then builds a search index
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


# Version of this script
__version__ = "0.0.3"

# Project-relative path to latest index file
INDEX_PATH = "v1/index.json"


def get_all_repos():
    """Get API data on all repos in AutoPkg org."""
    repos = []
    url = "https://api.github.com/orgs/autopkg/repos"
    headers = {
        "user-agent": f"autopkg-search-index/{__version__}",
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
    excl_names = ("autopkg/autopkg", "autopkg/index", "autopkg/setup-autopkg-actions")
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
    """Given a variable name wrapped in percents, resolve to the actual variable value.

    NOTE: We are not currently traversing parents to resolve variables, because recipes
    that require this for search-relevant values like app name and description are rare.
    """

    var_name = var_name.strip("%")
    return recipe_dict.get("Input", {}).get(var_name)


def extract_type_metadata(index_entry, input_dict):
    """Extract type-specific metadata based on recipe type.

    Args:
        index_entry: Dictionary containing the recipe's index entry
        input_dict: The recipe's Input dictionary
    """
    # Maps (recipe_type, field_name) -> (source_path, input_key)
    metadata_map = {
        "munki": {
            "app_display_name": ("pkginfo", "display_name"),
            "app_description": ("pkginfo", "description"),
        },
        "jss": {
            "app_display_name": ("Input", "SELF_SERVICE_DISPLAY_NAME"),
            "app_description": ("Input", "SELF_SERVICE_DESCRIPTION"),
        },
        # Based on examples from grahampugh-recipes
        "jamf": {
            "app_display_name": ("Input", "SELF_SERVICE_DISPLAY_NAME"),
            "app_description": ("Input", "SELF_SERVICE_DESCRIPTION"),
        },
        # Based on examples from almenscorner-recipes
        "intune": {
            "app_display_name": ("Input", "display_name"),
            "app_description": ("Input", "description"),
        },
        # Based on examples from WorkSpaceOneImporter-recipes
        "ws1": {
            "app_display_name": ("pkginfo", "display_name"),
            "app_description": ("pkginfo", "description"),
        },
    }

    recipe_type = index_entry.get("inferred_type")
    if recipe_type in metadata_map:
        for field_name, (source, key) in metadata_map[recipe_type].items():
            if source == "pkginfo":
                pkginfo = input_dict.get("pkginfo", {})
                index_entry[field_name] = pkginfo.get(key)
            else:
                index_entry[field_name] = input_dict.get(key)


def build_search_index(repos):
    """Given a list of repo info from the GitHub API, build recipe search index."""
    index = {
        "identifiers": {},
        "shortnames": {},
    }
    children = []
    parsing_errors = []
    warnings = {
        "yaml_parse_errors": [],
        "plist_parse_errors": [],
        "empty_recipes": [],
        "unresolved_variables": [],
        "missing_parents": [],
    }
    for repo in repos:
        # Find recipe files up to 2 levels deep
        recipes = []
        for ext in ("recipe", "recipe.plist", "recipe.yaml"):
            recipes.extend(glob(f"repos/{repo['full_name']}/*/*.{ext}"))
            recipes.extend(glob(f"repos/{repo['full_name']}/*/*/*.{ext}"))

        # Filter out any directories
        recipes = [r for r in recipes if os.path.isfile(r)]

        # Get indexable data from recipe files
        for recipe in recipes:
            index_entry = {}
            if recipe.endswith(".yaml"):
                try:
                    with open(recipe, "rb") as openfile:
                        recipe_dict = yaml.safe_load(openfile)
                except (yaml.YAMLError,) as e:
                    error_msg = f"Unable to parse {recipe} as YAML: {e}"
                    print(f"::warning file={recipe}::{error_msg}")
                    parsing_errors.append(error_msg)
                    warnings["yaml_parse_errors"].append(error_msg)
                    continue
            else:
                try:
                    with open(recipe, "rb") as openfile:
                        recipe_dict = plistlib.load(openfile)
                except (plistlib.InvalidFileException, ExpatError, ValueError) as e:
                    error_msg = f"Unable to parse {recipe} as plist: {e}"
                    print(f"::warning file={recipe}::{error_msg}")
                    parsing_errors.append(error_msg)
                    warnings["plist_parse_errors"].append(error_msg)
                    continue

            # Treat empty recipes as errors
            if recipe_dict is None:
                error_msg = f"Empty or invalid recipe file: {recipe}"
                print(f"::warning file={recipe}::{error_msg}")
                parsing_errors.append(error_msg)
                warnings["empty_recipes"].append(error_msg)
                continue

            # Don't index deprecated recipes
            if any(
                x.get("Processor") == "DeprecationWarning"
                for x in recipe_dict.get("Process", [])
            ):
                continue

            # Generally applicable metadata
            input_dict = recipe_dict.get("Input") or {}
            index_entry["name"] = input_dict.get("NAME")
            index_entry["description"] = recipe_dict.get("Description")
            index_entry["repo"] = repo["full_name"]
            index_entry["path"] = os.path.relpath(recipe, f"repos/{repo['full_name']}")
            if recipe_dict.get("ParentRecipe"):
                index_entry["parent"] = recipe_dict["ParentRecipe"]
                children.append(
                    (recipe_dict["Identifier"], recipe_dict["ParentRecipe"])
                )

            # Get inferred type of recipe
            type_pattern = r"\/([\w\- ]+\.([\w\- ]+))\.recipe(\.yaml|\.plist)?$"
            match = re.search(type_pattern, index_entry["path"])
            if match:
                index_entry["shortname"] = match.group(1)
                index_entry["inferred_type"] = match.group(2)

            # Type-specific metadata extraction such as display name and description
            extract_type_metadata(index_entry, input_dict)

            # Resolve any substitution variables in the index entry
            for k, v in index_entry.items():
                if isinstance(v, str) and v.startswith("%") and v.endswith("%"):
                    resolved_value = resolve_var(recipe_dict, v)
                    if resolved_value is None:
                        warning_msg = (
                            f"Unable to resolve variable {v} in field '{k}' in {recipe}"
                        )
                        print(
                            f"::warning file={recipe}::Unable to resolve variable {v} in field '{k}'"
                        )
                        warnings["unresolved_variables"].append(warning_msg)
                    index_entry[k] = resolved_value

            # Strip whitespace from all string values in the index entry
            for k, v in index_entry.items():
                if isinstance(v, str):
                    index_entry[k] = v.strip()

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
            warning_msg = f"{child[0]} refers to missing parent recipe {child[1]}."
            print(f"::warning::{warning_msg}")
            warnings["missing_parents"].append(warning_msg)
        else:
            if "children" in index["identifiers"][child[1]]:
                index["identifiers"][child[1]]["children"].append(child[0])
            else:
                index["identifiers"][child[1]]["children"] = [child[0]]

    # Report build summary
    total_recipes = len(index["identifiers"])
    print()
    print("BUILD SUMMARY:")
    print(f"Total recipes added to index: {total_recipes}")
    print()

    # Report warnings grouped by type
    total_warnings = sum(len(v) for v in warnings.values())
    if total_warnings > 0:
        print("WARNING SUMMARY:")
        print(f"Total warnings: {total_warnings}")

        warning_labels = {
            "yaml_parse_errors": "YAML parsing errors",
            "plist_parse_errors": "Plist parsing errors",
            "empty_recipes": "Empty recipe files",
            "unresolved_variables": "Unresolved variables",
            "missing_parents": "Missing parent recipes",
        }

        for warning_type, warning_list in warnings.items():
            if warning_list:
                print(f"{warning_labels[warning_type]}: {len(warning_list)}")
        print()

    # Write index file
    with open(INDEX_PATH, "w", encoding="utf-8") as openfile:
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

    # Report parsing errors but continue with index creation
    if error_count > 0:
        print(
            f"::warning::Index build completed. Skipped {error_count} "
            "recipes with parsing errors"
        )
    else:
        print("::notice::Index build completed successfully with no parsing errors")


if __name__ == "__main__":
    main()
