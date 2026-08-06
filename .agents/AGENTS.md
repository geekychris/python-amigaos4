# Workspace Rules & Guidelines

## Branch Scoping & Feature Isolation Rule
- Always track the specific feature or system area being modified.
- All code changes, fixes, and additions must be developed and checked into separate, focused, and small git branches corresponding to that specific feature/domain (e.g., `installer` branch for installer work, `pip` branch for PIP/packaging work, `e1000` branch for driver work).
- Keep branches atomic and feature-scoped to ensure simple, clean pull requests and easy merge workflows.
