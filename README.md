# Climate Information Data Model Specification

An open source data model specification for climate information developed through a stakeholder consensus process by the IBPSA-USA Building Data Exchange Committee. An example JSON file is included with this document (example-20211111.json). Access the first version of the document here: https://ibpsa-usa.github.io/climate-information/

The second version of this document is intended to be an informative addendum to ASHRAE Standard 169. It will provide expanded and updated data model specifications for climate data, based on the data model initially was developed through a stakeholder consensus process by the IBPSA-USA Building Data Exchange Committee. It is based on the standard framework and vocabulary provided in ASHRAE Standard 205-2023. 

Notes on this version of the data model and its expected evolution:
- The committee chose not to define an authoritative minimum viable data model, thus allowing users of the data model (data providers and consumers) to select the relevant variables and time periods according to their applications.
- The data elements are intended to reflect the common use cases of building thermal and daylight modeling. Other use cases may require a different set of data elements for their purposes and readers are invited to submit for consideration variables of interest to them that are not included in this model.
- Currently the data model only covers metadata fields, location, and time series variables with regular and irregular time intervals. Future versions are expected to include structures for statistically-derived design conditions.
- This document does not separately consider how the data model should be serialized or the file formats that should be used for publication.

Last updated: 2024-Aug-06
