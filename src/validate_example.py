import lattice

lattice.generate_meta_schemas(['build/ibpsa-bde-climate/meta.schema.json'],['examples/ibpsa-bde/IBPSA-BDE-Climate.schema.yaml'])
lattice.meta_validate_dir('examples/ibpsa-bde/', 'build/ibpsa-bde-climate/')