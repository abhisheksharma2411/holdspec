# Publishing this artifact

## 1. Push to GitHub -- done

Published at <https://github.com/abhisheksharma2411/holdspec>, public, with the
`v1.0.0` release cut from the tag that points at the commit the paper's results
were produced from: <https://github.com/abhisheksharma2411/holdspec/releases/tag/v1.0.0>

## 2. Mint a DOI for the code on Zenodo

1. Sign in at <https://zenodo.org> with the GitHub account.
2. Under *Settings -> GitHub*, switch the toggle on for `abhisheksharma2411/holdspec`.
3. The `v1.0.0` release already exists but predates the toggle, so Zenodo has not
   seen it. Cut a `v1.0.1` release (or delete and re-create `v1.0.0` from the
   GitHub UI) to trigger the archive. Zenodo mints the DOI automatically.
4. Put the DOI in `paper/zenodo_doi.txt` (one line, no other content) and add it
   to `CITATION.cff` as a `doi:` field, then run `make paper`. The LaTeX reads
   the DOI from that file through a generated macro, so the `.tex` never needs
   hand-editing.

## 3. There is no separate dataset deposit

This artifact has no dataset. The provider profiles are read from public
documentation and are version-controlled in `src/holdspec/profiles.py` with a URL
and a verbatim quote per field; every workload is generated from the model at run
time. A dataset DOI would point at nothing that is not already in the code
deposit, so only one DOI is minted.

## 4. Checks before any further push

```bash
make reproduce          # clean tree through to the PDF
git status --porcelain  # expected to be empty
```
