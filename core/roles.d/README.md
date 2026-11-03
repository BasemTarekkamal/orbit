# Community roles

Each folder here is a role anyone can hire from, shown on the hiring page with the kit's own roles.

    roles.d/<role-id>/
      role.json          {"title", "role", "scope", "abilities", "model", "try", "rules", "connectors"}
      skills/<name>/SKILL.md   the know-how the role starts with (the same format as core/skills)

      experience.md       what the crew member it was trained on learned (a new hire gets it as EXPERIENCE.md)

Share one from a crew member you trained: their Manage tab → "Share what they know". Orbit drafts a copy with
everything private taken out, you edit it, and "Share with the Orbit community" opens a pull request adding it
here (with the GitHub CLI signed in) or the "Share a role" issue form to attach the file to. Reviewers check
that it's generic before merging: no names, accounts, links to your own pages, numbers from your business, or
anything private. Merged roles reach every Orbit with the next update.
