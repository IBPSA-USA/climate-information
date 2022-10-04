"""
doit task/build automation
"""

import os
from doit.tools import create_folder

import lattice

PROJECT_TITLE = "ClimateInformation"

BUILD_PATH = "build"
SCHEMA_DIR_PATH = "schema"
SCHEMA_PATH = os.path.join(SCHEMA_DIR_PATH,f"{PROJECT_TITLE}.schema.yaml")
META_SCHEMA_OUTPUT_DIR_PATH = os.path.join(BUILD_PATH,"meta_schema")
META_SCHEMA_OUTPUT_PATH = os.path.join(META_SCHEMA_OUTPUT_DIR_PATH,"meta.schema.json")
JSON_SCHEMA_DIR_PATH = os.path.join(BUILD_PATH,"json_schema")
JSON_SCHEMA_OUTPUT_PATH = os.path.join(JSON_SCHEMA_DIR_PATH,f"{PROJECT_TITLE}.schema.json")
DOCS_DIR_PATH = "docs"
DOCS_OUTPUT_DIR_PATH = os.path.join(BUILD_PATH,"docs")
DOCS_OUTPUT_PATH = os.path.join(DOCS_OUTPUT_DIR_PATH,f"{PROJECT_TITLE}.md")

EXAMPLE_FILES_DIR_PATH = "examples"
EXAMPLE_FILES = ["USA_IL_Chicago.json"]

def task_generate_meta_schema():
  '''Generates the meta-schema'''
  return {
    'file_dep': [SCHEMA_PATH],
    'targets': [META_SCHEMA_OUTPUT_DIR_PATH],
    'actions': [
      (create_folder, [META_SCHEMA_OUTPUT_DIR_PATH]),
      (lattice.generate_meta_schemas,[[META_SCHEMA_OUTPUT_PATH], [SCHEMA_PATH]])
      ]
  }

def task_validate_schema():
  '''Validates the schema against the meta schema'''
  return {
    'task_dep': ['generate_meta_schema'],
    'actions': [
      (lattice.meta_validate_dir,[SCHEMA_DIR_PATH, META_SCHEMA_OUTPUT_DIR_PATH])
      ]
  }

def task_generate_json_schema():
  '''Generates the corresponding JSON Schema'''
  return {
    'file_dep': [SCHEMA_PATH],
    'targets': [JSON_SCHEMA_OUTPUT_PATH],
    'task_dep': ['validate_schema'],
    'actions': [
      (lattice.generate_json_schemas,[SCHEMA_DIR_PATH, JSON_SCHEMA_DIR_PATH])
      ]
  }

def task_validate_example_files():
  '''Validates the example files against the JSON schema (and other validation steps)'''
  return {
    'task_dep': ['generate_json_schema'],
    'actions': [
      (lattice.validate_json_file,[os.path.join(EXAMPLE_FILES_DIR_PATH, example), JSON_SCHEMA_OUTPUT_PATH]) for example in EXAMPLE_FILES
      ]
  }


def task_generate_markdown_documentation():
  '''Generates Markdown Documentation'''
  return {
    'file_dep': [SCHEMA_PATH],
    'targets': [DOCS_OUTPUT_PATH],
    'task_dep': ['validate_schema'],
    'actions': [
      (create_folder, [DOCS_OUTPUT_DIR_PATH]),
      (lattice.process_templates,[DOCS_DIR_PATH, DOCS_OUTPUT_DIR_PATH])
      ]
  }
