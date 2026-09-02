# Publishing this artifact

No GitHub or Zenodo credentials were used while building this, so the repository
is committed and tagged locally. Everything below is one step each.

## 1. Push to GitHub

```bash
cd holdspec
git remote add origin https://github.com/abhisheksharma2411/holdspec.git
git push -u origin main
git push origin v1.0.0
```

The tag `v1.0.0` already exists locally and points at the commit the paper's
results were produced from.

## 2. Mint a DOI for the code on Zenodo

1. Sign in at <https://zenodo.org> with the GitHub account.
2. Under *Settings -> GitHub*, switch the toggle on for `abhisheksharma2411/holdspec`.
3. Re-publish the release: `gh release create v1.0.0 --title "HoldSpec 1.0.0" --notes-file RELEASE_NOTES.md`
   (or press *Draft a new release* in the GitHub UI and select the existing tag).
   Zenodo archives the tag and mints the DOI automatically.
4. Copy the DOI into two places, then rebuild the paper:
   - `paper/holdspec.tex`, in the Artifact Availability section, replacing
     `\zenodocode`
   - `CITATION.cff`, as a `doi:` field

## 3. There is no separate dataset deposit

This artifact has no dataset. The provider profiles are read from public
documentation and are version-controlled in `src/holdspec/profiles.py` with a URL
and a verbatim quote per field; every workload is generated from the model at run
time. A dataset DOI would point at nothing that is not already in the code
deposit, so only one DOI is minted.

## 4. Checks before pushing

```bash
make reproduce          # clean tree through to the PDF
git status --porcelain  # expected to be empty
```
