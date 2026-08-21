"""
doit task/build automation
"""

import os

import yaml
from lattice import Lattice
from lattice.docs.mkdocs_web import MkDocsWeb


# Lattice hard-codes the mkdocs `markdown_extensions` list in MkDocsWeb.make_config()
# and leaves mermaid out, so the ```mermaid fences in docs/ClimateInformation.md.j2 ship
# as literal <pre><code class="language-mermaid"> blocks -- the diagram source as text.
# mkdocs-material renders mermaid only when pymdownx.superfences declares it as a custom
# fence, so append that declaration here. It has to be patched onto make_config rather
# than edited into the generated mkdocs.yml: lattice writes the config and shells out to
# `mkdocs build` inside the same call, leaving no point in between to touch the file.


class _PythonName(str):
    """A string that serialises as the `!!python/name:<value>` tag mkdocs expects."""


yaml.add_representer(
    _PythonName,
    lambda dumper, data: dumper.represent_scalar(f"tag:yaml.org,2002:python/name:{data}", ""),
)

_make_config_without_mermaid = MkDocsWeb.make_config


def _make_config_with_mermaid(self):
    config = _make_config_without_mermaid(self)
    config["markdown_extensions"].append(
        {
            "pymdownx.superfences": {
                "custom_fences": [
                    {
                        "name": "mermaid",
                        "class": "mermaid",
                        "format": _PythonName("pymdownx.superfences.fence_code_format"),
                    }
                ]
            }
        }
    )
    return config


MkDocsWeb.make_config = _make_config_with_mermaid


# Lattice's default build_validation=True runs validate_example_files() eagerly at
# import time, so any known-broken example would crash `doit list` (or any other
# task) before doit's task graph even runs -- not just the validate_example_files
# task itself. Run every build_validation step except that last one here instead,
# and leave example validation to task_validate_example_files below, where a
# failure is an ordinary doit task failure rather than an import-time crash.
climate_data_model = Lattice(build_validation=False)
climate_data_model.generate_meta_schemas()
climate_data_model.validate_schemas()
climate_data_model.generate_json_schemas()

# USA_IL_Chicago-v1.json predates the current schema entirely (2021, a different
# schema identity than any version this schema.yaml has ever declared) and needs a
# real migration, not a mechanical field-rename -- deferred, tracked as
# IBPSA-USA/climate-information#8 rather than silently deleting or moving a file
# that may still be a useful historical reference.
_LEGACY_EXAMPLES = {climate_data_model.root_directory / "examples/curated/USA_IL_Chicago-v1.json"}
climate_data_model.examples = [p for p in climate_data_model.examples if p not in _LEGACY_EXAMPLES]


def task_validate_example_files():
    """Validates the example files against the JSON schema (and other validation steps)"""
    return {
        "file_dep": climate_data_model.examples
        + [schema.schema.file_path for schema in climate_data_model.schema_info],
        "actions": [(climate_data_model.validate_example_files, [])],
    }


def task_generate_web_docs():
    """Generates Markdown Documentation"""
    return {
        "file_dep": [schema.schema.file_path for schema in climate_data_model.schema_info]
        + [template.path for template in climate_data_model.doc_templates],
        "targets": [os.path.join(climate_data_model.web_docs_directory_path, "public")],
        "actions": [(climate_data_model.generate_web_documentation, [])],
    }
