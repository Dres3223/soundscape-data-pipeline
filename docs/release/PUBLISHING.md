# Publishing the derived datasets

The derived data is published as a **GitHub release** of this repository,
tagged `data-v<version>`, with one zip per dataset. Each dataset has its own
licence, stated in its README and `LICENSE.txt`:

| Zip | Content | Licence | Why |
|---|---|---|---|
| `soundscape-indices-v<version>.zip` | Recordings, quality flags, acoustic indices | CC BY 4.0 | Same as the source recordings |
| `soundscape-detections-v<version>.zip` | BirdNET detections, species mart, validation | CC BY-NC-SA 4.0 | Licence of BirdNET's model weights |

No audio is published: anyone can get it from the source datasets. A
release can be edited or deleted later; it has no DOI.

## 1. Build the files

```bash
make run       # or the Airflow DAG, then dbt build
make release   # writes data/release/ and checks the checksums
```

## 2. Tag the code that made them

```bash
git tag -a data-v1.0.0 -m "Derived dataset v1.0.0"
git push origin data-v1.0.0
```

## 3. Create the release

On GitHub: *Releases* → *Draft a new release* → choose the tag `data-v1.0.0`.

- **Title:** Derived dataset v1.0.0
- **Description:** what is in each zip, its licence, and a link to the
  READMEs inside them; mark that the detections are automatic and miss most
  birds (`docs/validation.md`).
- **Assets:** the two zips from `data/release/`.
- Untick *Set as the latest release* if a code release should stay first.

With the GitHub CLI, the same in one command:

```bash
gh release create data-v1.0.0 data/release/soundscape-*-v1.0.0.zip \
  --title "Derived dataset v1.0.0" --notes-file <notes.md>
```

## 4. A new version

Raise `VERSION` in `src/soundscape/export.py`, rebuild, tag `data-v<new>` and
create a new release. Keep the old ones: results cited with a version must
stay downloadable.

## If a DOI is wanted later

Zenodo gives a permanent DOI, but a published record cannot be deleted. Since
a Zenodo record has a single licence, the two zips would need two records,
linked to each other (*Is supplement to* / *Is supplemented by*) and to the
sources (*Is derived from* `10.5281/zenodo.17122738`; the detections also
`10.5281/zenodo.17064353`). Try it first on https://sandbox.zenodo.org.
