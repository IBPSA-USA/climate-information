"""
doit task/build automation
"""

import os
from doit.tools import create_folder

from lattice import Lattice

climate_data_model = Lattice()

def task_validate_example_files():
  '''Validates the example files against the JSON schema (and other validation steps)'''
  return {
    'file_dep': climate_data_model.examples + [schema.path for schema in climate_data_model.schemas],
    'actions': [(climate_data_model.validate_example_files,[])]
  }

def task_generate_web_docs():
  '''Generates Markdown Documentation'''
  return {
    'file_dep': [schema.path for schema in climate_data_model.schemas] + [template.path for template in climate_data_model.doc_templates],
    'targets': [os.path.join(climate_data_model.web_docs_directory_path,"public")],
    'actions': [(climate_data_model.generate_web_documentation,[])]
  }
