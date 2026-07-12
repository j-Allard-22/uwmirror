# Releasing uwmirror

Releases are tag-triggered: pushing a `vX.Y.Z` tag runs
[`.github/workflows/release.yml`](../.github/workflows/release.yml), which
builds the wheel/sdist and the standalone `uwmirror.exe`, publishes to PyPI via
OIDC trusted publishing, and creates a GitHub Release with the exe attached and
the CHANGELOG section as notes.

## One-time setup: PyPI trusted publisher

PyPI publishing uses OIDC (no API tokens). Before the **first** release, register
a *pending* trusted publisher — "pending" because the `uwmirror` project doesn't
exist on PyPI yet; it is created automatically on the first successful publish.

1. Have a [PyPI](https://pypi.org) account **with 2FA enabled** (required to reach
   the publishing settings).
2. Go to **Account → Publishing**: <https://pypi.org/manage/account/publishing/>.
3. Under "Add a new pending publisher", choose **GitHub** and fill in exactly:
   - **PyPI Project Name:** `uwmirror`
   - **Owner:** `j-Allard-22`
   - **Repository name:** `uwmirror`
   - **Workflow name:** `release.yml` (the filename only, not a path)
   - **Environment name:** `pypi` (must match `environment: pypi` in the publish job)
4. Submit. It is active immediately — no approval wait.

Notes:
- A pending publisher does **not** reserve the name. Confirm `uwmirror` is still
  unclaimed on PyPI just before tagging; if someone else claims it first, the
  registration is invalidated.
- Optionally create a GitHub Actions **Environment** named `pypi` (repo →
  Settings → Environments) to add a manual-approval gate before publishing. The
  workflow creates it on first run if you don't.

## Cutting a release

1. Bump `__version__` in [`src/uwmirror/__init__.py`](../src/uwmirror/__init__.py)
   (hatchling reads it; SemVer).
2. In [`CHANGELOG.md`](../CHANGELOG.md), move items from `[Unreleased]` into a new
   dated `## [X.Y.Z] - YYYY-MM-DD` section and update the compare links. The
   GitHub Release notes are extracted from this section, so keep the heading
   format `## [X.Y.Z]`.
3. Run the gates locally: `ruff check . && ruff format --check . && mypy && pytest`.
4. Commit, then tag and push:
   ```powershell
   git tag -a vX.Y.Z -m "uwmirror vX.Y.Z"
   git push origin main
   git push origin vX.Y.Z
   ```
5. Watch the **Release** workflow. On success it publishes to
   <https://pypi.org/project/uwmirror/> and creates the GitHub Release with
   `uwmirror.exe` + the wheel/sdist attached.

If `publish` fails, it's almost always the trusted publisher not being
registered (see above) or an environment-name mismatch. Fix it, then re-run the
failed job or delete and re-push the tag.

## Signing the released exe (optional)

The released `uwmirror.exe` is unsigned. Code signing (Azure Artifact Signing or
SignPath Foundation) shows a verified publisher name and builds SmartScreen
reputation across releases — see [build-exe.md](build-exe.md) for the options and
a ready-to-paste, secrets-gated CI step.
