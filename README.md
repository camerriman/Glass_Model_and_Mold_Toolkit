# Glass Library & Model and Mold Toolkit

A Streamlit multipage app for glass mold-making, model generation, SVG utilities, and a Bullseye glass reference library.

The app also includes a built-in localization layer for Streamlit UI text, sidebar navigation, forms, dashboards, and locale-aware date/time display.

The project combines:

- mold and model generators for cameo and vessel workflows
- mesh tiling, paneling, and cropping tools
- a glass sample library backed by SQLite
- printable reference sheets and datasheet PDFs
- SVG crop and tiling tools with optional `vpype` processing

## Main Areas

- `Home.py`: multipage app entry point
- `i18n.py`: shared localization module, language selector, and date/time formatting helpers
- `pages/1_Cameo_Model_Generator.py`: cameo mold model workflow
- `pages/4_Vessel_Model_Generator.py`: vessel mold model workflow
- `pages/2_Model_Tiles_Panels.py`: mesh slicing into panels or tiles
- `pages/5_Mesh_Crop.py`: STL proxy crop tool
- `pages/6_Glass_Library.py`: library browser
- `pages/7_Glass_Color_Wheel.py`: HSB color wheel and harmony overlay
- `pages/8_Glass_Detail.py`: full sample datasheet + PDF export
- `pages/15_Glass_Compare.py`: side-by-side glass comparison with difference summaries
- `pages/9_Opalescent_Reference.py`, `pages/10_Transparent_Reference.py`, `pages/11_Tint_Reference.py`: printable family reference sheets
- `pages/12_Add_Glass_Sample.py`, `pages/13_Edit_Glass_Sample.py`: glass catalog maintenance
- `pages/20_SVG_Tiles.py`, `pages/21_SVG_Crop.py`: SVG workflow tools
- `utilities/i18n_audit.py`: translation coverage checker for supported UI languages

## Project Structure

```text
glass_model_and_mold_toolkit/
├── Home.py
├── i18n.py
├── pages/
├── utilities/
├── data/
│   ├── glass_library.sqlite
│   └── mold_records.db
├── images/
└── svg/
```

## Requirements

The app uses the Python packages listed in `requirements.txt`.

Notable runtime dependencies:

- `streamlit` for the app shell
- `trimesh`, `scipy`, `numpy` for model generation and mesh work
- `plotly`, `matplotlib` for visualisation
- `Pillow` for image processing and PDF rendering
- `opencv-python-headless` for the mesh crop workflow
- `streamlit-quill` for rich-text editing on glass sample pages
- `lxml` and `vpype` for SVG processing
- `manifold3d` for more reliable mesh boolean operations

## Localization

The app uses a lightweight key-based localization system instead of a full gettext-style catalog workflow.

Current UI languages:

- English
- Spanish
- Italian
- German
- French

Localization responsibilities:

- `i18n.py` stores supported languages, locale mappings, translation dictionaries, and formatting helpers.
- Pages render user-facing copy through stable translation keys via `t("...")`.
- Displayed dates and times are formatted according to the active language/locale.
- Units such as `F/C` remain separate from language selection.
- Stored database values remain canonical and are not rewritten for localization.

To audit translation coverage for a language:

```bash
python3 utilities/i18n_audit.py fr
```

A completed language should report `Missing keys: 0`.

To add another language:

1. Add the language code to `SUPPORTED_LANGUAGES` in `i18n.py`.
2. Add its locale to `LOCALES_BY_LANGUAGE`.
3. Add selector display names such as `language_name.fr`.
4. Add month names if needed for localized date formatting.
5. Add the translation dictionary in `i18n.py`.
6. Run the audit helper until the language reports `Missing keys: 0`.

## Local Setup

### 1. Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run the app

```bash
streamlit run Home.py
```

The app entry point is `Home.py`. Run it from the repository root and keep the filename casing exact.

## Data and Assets

This app expects these folders to exist in the repo:

- `data/`
- `images/`
- `svg/`

For the glass library pages to work on a hosted deployment, the repository should include:

- `data/glass_library.sqlite`
- `images/icons/`
- `images/full/`
- `images/_placeholders/`

If those are missing, the app will still load, but the glass-library features will be incomplete.

## Streamlit Community Cloud Deployment

This app is suitable for deployment on Streamlit Community Cloud.

### Recommended settings

- Repository: the GitHub repository containing this project
- Branch: the deployment branch
- Main file path: `Home.py`
- Python version: 3.12 recommended

### Deployment notes

- `requirements.txt` is prepared for Streamlit deployment.
- The app uses local SQLite databases, so the `.sqlite` files must be committed for hosted data access.
- The app includes many image assets, so repository size may affect deployment and update performance.
- SVG pages use `vpype`, which is included in `requirements.txt`.
- Mesh slicing defaults to the `manifold` engine through `manifold3d`.
- The mesh crop page also depends on `opencv-python-headless`.
- UI localization is session-based and does not modify stored database content.
- External mesh engines such as Blender or OpenSCAD are not bundled by this repo and should be treated as optional local-only engines.

## What the STL Files Are For

The STL output in this project is the beginning of the mold workflow, not the end of the design process.

Typical use:

1. Prepare artwork or a heightmap image.
2. Generate an STL from the app.
3. Print the model by FDM or resin, depending on the workflow.
4. Use the print to create an intermediate mold or expendable negative.
5. Build the refractory mold from that intermediate form.
6. Cast and fire the final glass piece.

## Printing Notes

### FDM

Useful when the printed model is structural, large, or mainly serving a mold-making role.

### Resin

Useful when very fine relief detail matters more than build volume or convenience.

## PDFs and Reference Sheets

The glass reference pages and glass detail page generate printer-ready PDFs directly from the app. This avoids browser print layout problems and keeps output consistent for studio use and archiving.
