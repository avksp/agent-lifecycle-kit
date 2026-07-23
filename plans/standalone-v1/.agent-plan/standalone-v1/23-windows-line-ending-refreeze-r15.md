# Windows line-ending CI refreeze r15

Revision 15 closes a CI portability ownership gap found after revision 14 was
merged and Linux/macOS checks passed, while Windows checks failed on checkout
line-ending conversion.

Problem:

- Windows checkout converted tracked JSON and markdown text from LF to CRLF;
- synthetic fixture content-addressing compares exact byte size and SHA-256, so
  CRLF conversion changed the tested file identity;
- the skill-pack thinness test checked LF frontmatter literally;
- adding a root `.gitattributes` file is the correct repository-level fix, but
  the file was not assigned to any frozen workstream.

Resolution:

- keep product scope, task DAG, adapter maturity, release claims and production
  promotion boundary unchanged;
- assign `.gitattributes` ownership to WS-01 as repository foundation and
  neutrality/CI configuration;
- keep content-addressing strict by preserving raw byte checks for synthetic
  fixtures;
- make the markdown skill-pack metadata check tolerant of CRLF in decoded text;
- require fresh current-tree tests, neutrality scan, release verification and
  ownership audit before the next push.

Execution impact:

- no runtime behavior or public API is expanded by this refreeze;
- release status remains source-release `EXPERIMENTAL`;
- `VERIFIED` and production promotion still require external live receipts and
  signed platform evidence.
