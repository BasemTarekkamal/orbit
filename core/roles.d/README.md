# Community roles

Each folder here is a role anyone can hire from, shown on the hiring page with the kit's own roles.

    roles.d/<role-id>/
      role.json          {"title", "role", "scope", "abilities", "model", "try", "rules", "connectors"}
      skills/<name>/SKILL.md   the know-how the role starts with (the same format as core/skills)

Make one from a crew member you trained: Manage → "Save as a role", then `orbit roles export <role-id> <folder>`,
and open a pull request adding the folder here. Keep it generic: no names, accounts, links to your own pages,
numbers from your business, or anything private. Reviewers check that before merging.
