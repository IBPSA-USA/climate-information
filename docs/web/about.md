This document provides data model specifications for climate data. It was developed through a stakeholder consensus process by the IBPSA-USA Building Data Exchange Committee. It is based on the standard framework and vocabulary provided in the ANSI/ASHRAE/IBPSA Standard 232.

Some notes about this version and its expected evolution:

- The committee chose not to define an authoritative minimum viable data model, thus allowing users of the data model (data providers and consumers) to select the relevant variables and time periods according to their applications.
- The data elements are intended to reflect the common use cases of building thermal and daylight modeling. Other use cases may require a different set of data elements for their purposes.
- Currently the data model only covers metadata fields, location, and time series variables with regular and irregular time intervals. Future versions are expected to include structures for statistically-derived design conditions.
- This document does not separately consider how the data model should be serialized or the file formats that should be used for publication.

## Open Questions

The following questions and decisions from the committee's consensus process remain open or are recorded for reference, and are expected to be resolved in future revisions.

1. Are there other variables, calculations, or use cases to support -- for example, variables specific to district heating/cooling network design?
1. Which use cases should the schema cover? Not everything need be explicit in the model itself; providers are encouraged to document specifics for their users.
1. Which products, beyond the schema itself, are needed to make it usable (helpers, example datasets such as the ASHRAE design data)?
1. Should the model support historical trends? The committee felt it was not essential (ref: the ASHRAE design conditions table).
1. Should the model support design days, or daily (365-value) series? The committee saw no need for daily values.
1. Derived variables and extensibility. The working principle is that variables derivable from measured variables by a deterministic calculation stay out of the base model, with guidance for providers to pre-compute them into use-case "flavours" (e.g. an ASHRAE-flavour output adding enthalpy, ranges, and return periods). Open: should derived variables be (a) defined-but-optional in the base model, (b) supported only via documented extensibility/custom fields, or (c) split into a separate auxiliary model? The current exclusion list is in the format-mapping notes under `extra_docs/`. Return periods were decided out (19 Dec 2025); if reintroduced, the notes should reference the calculation method (a mixture of the empirical distribution and a nominal Gumbel distribution), and we should consider naming them by the corresponding probability.
1. Confidence intervals: how should they be expressed per quantity -- as an arbitrary range, and as a confidence level, a confidence interval, or "n-sigma"?

## Working Group

### Version 2
- Parag Cameron-Rastogi (Working Group Chair)
- Neal Kruis
- Chip Barnaby
- Dru Crawley
- Michael Roth

### Version 1

- Parag Rastogi (Working Group Chair)
- Sagar Rao (Building Data Exchange Committee Chair)
- Neal Kruis (Building Data Exchange Committee Vice-Chair)
- Dru Crawley
- Chip Barnaby
- Ben Brannon
- Suhaas Mathur (Building Data Exchange Committee Secretary)
- Tim McDowell

## Contributors

### Version 2

- Sagar Rao

### Version 1

- Evyatar Erell
- John Mardaljevic
- Jan Wienold
- Eleonora Brembilla
- Chris Mackey
- Matthew Dahlhausen
- Michael Roth
- Tianzhen Hong
- Joshua New
- Dorit Aviv
- Forrest Meggers

## Acknowledgements

This data model specification was developed with support from the U.S. Department of Energy.
