# Workspace Rules & Guidelines

## Branch Scoping & Feature Isolation Rule
- Always track the specific feature or system area being modified.
- All code changes, fixes, and additions must be developed and checked into separate, focused, and small git branches corresponding to that specific feature/domain (e.g., `installer` branch for installer work, `pip` branch for PIP/packaging work, `e1000` branch for driver work).
- Keep branches atomic and feature-scoped to ensure simple, clean pull requests and easy merge workflows.

## Main Branch Upstream Check Rule
- Before modifying or implementing changes to any file, ALWAYS check the `main` branch (and fetch `origin/main`) to see if the file has changed upstream.
- Inspect any recent commits on `main` affecting target files (`git log origin/main -n 5 -- <file>`) to ensure all upstream fixes are accounted for and prevent regressions or merge conflicts.
