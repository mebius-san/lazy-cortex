---
Aliases: [ "#{{TAG_PATH}}" ]
---

# Summary

{{SUMMARY}}

# Index
```dataviewjs
const cur = dv.current();
let tag = (cur.file.aliases ?? []).find(a => typeof a === "string" && a.trim().startsWith("#"));

if (!tag) {
  const name = cur.file.name.trim();
  tag = name.startsWith("#") ? name : ("#" + name);
}

const pages = dv.pages()
  .where(p => (p.file.tags ?? []).includes(tag))
  .where(p => !p.file.path.startsWith("Ω System/"))
  .sort(p => p.file.path, "asc")
  .map(p => p.file.link);

dv.list(pages);
```
