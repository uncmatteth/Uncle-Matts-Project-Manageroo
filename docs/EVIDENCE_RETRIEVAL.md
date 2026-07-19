# Evidence Retrieval Architecture

Manageroo does not have AI memory. Manageroo retrieves evidence.

Evidence providers may include:

- current repository state;
- Manageroo run artifacts;
- project decisions;
- GitNexus repository intelligence;
- GBrain knowledge sources;
- future external providers.

Every evidence item should preserve provenance:

- source;
- location;
- authority;
- confidence;
- freshness;
- retrieval metadata.

Evidence helps a worker receive better context. It does not authorize completion. Manageroo remains the authority for scope, verification, proof, and release decisions.

Ranking should prefer current, verified, authoritative evidence over older historical information.
