# Glass Library & Model and Mold Toolkit

A Streamlit multipage studio toolkit for kiln-glass design, Bullseye glass reference work, mold planning, 3D model generation, SVG preparation, and printable fabrication documentation.

The project has grown into four connected work areas:

- a searchable glass library with reflected/transmitted sample data, color tools, comparison views, and printable datasheets
- glass prediction tools for layered sheet reads, frit mixes, depth views, opacity, and optical response
- model and mold utilities for cameo, vessel, pate de verre, frame, tile, panel, and crop workflows
- SVG tiling/cropping tools for preparing artwork and fabrication layouts

The app also includes a lightweight localization layer for Streamlit UI text, sidebar navigation, forms, dashboards, reference pages, and locale-aware date/time display.

## App Areas

### Home and Documentation

- `Home.py`: app entry point and custom navigation hub
- `pages/14_Documentation.py`: studio workflow notes, materials references, glossary placeholders, and safety sections
- `i18n.py`: shared localization, language selector, navigation labels, and date/time helpers

### Glass Library

- `pages/6_Glass_Library.py`: searchable and sortable glass browser with family, mode, striker, element, and reaction filters
- `pages/8_Glass_Detail.py`: full glass datasheet with reflected/transmitted images, measurements, optical curves, depth side view, notes, and PDF export
- `pages/7_Glass_Color_Wheel.py`: HSB color wheel, harmony overlay, selected sample details, and element/reactivity summaries
- `pages/15_Glass_Compare.py`: side-by-side comparison for selected samples with reflected/transmitted overlays and difference summaries

### Reference Sheets

- `pages/9_Opalescent_Reference.py`: printable opalescent family reference
- `pages/10_Transparent_Reference.py`: printable transparent family reference
- `pages/11_Tint_Reference.py`: printable tint family reference
- `utilities/reference_pdf.py`: PDF builder for reference sheets
- `utilities/glass_detail_pdf.py`: PDF builder for individual glass datasheets

### Glass Prediction and Exploration

- `pages/16_Layered_Glass_Predictor.py`: predicts the visual read of one glass layered over another
- `pages/17_Frit_Mix_Explorer.py`: estimates mixed frit color reads and layered frit-over-base behavior
- `pages/18_Glass_Depth_Side_View.py`: explores color attenuation and depth behavior through glass thickness

### Model and Mold Tools

- `pages/1_Cameo_Model_Generator.py`: cameo mold model generator from artwork/heightmap input
- `pages/4_Vessel_Model_Generator.py`: vessel model generator with profile, relief, wall, rim, and image mapping controls
- `pages/2_Model_Tiles_Panels.py`: slices larger STL/model work into tiles or panels
- `pages/5_Mesh_Crop.py`: STL proxy crop workflow
- `pages/3_Mold_Worksheet.py`: cameo mold worksheet and material calculations
- `pages/19_Pate_de_verre_Mold_Worksheet.py`: vessel/pate de verre mold worksheet, volume estimates, and material planning
- `pages/22_Print_Optional_Frame.py`: print frame fabrication planning, pre-visualization, weights, and checklist output

### SVG Tools

- `pages/20_SVG_Tiles.py`: SVG tiling workflow with optional `vpype` processing
- `pages/21_SVG_Crop.py`: SVG crop workflow
- `svg/`: sample and working SVG assets

### Utilities

- `utilities/i18n_audit.py`: translation coverage checker
- `utilities/flatten_images.py`: image flattening/preview helper
- `utilities/pad_jpg_ids.py`, `utilities/rename_images_to_6digits.py`, `utilities/rename.py`: image naming and migration helpers
- `utilities/migrate_to_two_table_schema.py`, `utilities/migrate_to_two_table_schema_v2.py`: database migration helpers
- `utilities/model-slicer-app.py`: standalone/legacy model slicing utility

## Project Structure

```text
glass_model_and_mold_toolkit/
├── Home.py
├── i18n.py
├── requirements.txt
├── pages/
│   ├── 1_Cameo_Model_Generator.py
│   ├── 2_Model_Tiles_Panels.py
│   ├── ...
│   └── 22_Print_Optional_Frame.py
├── private_pages/
├── utilities/
├── data/
│   ├── glass_library.sqlite
│   ├── mold_records.db
│   └── fabrication_records.db
├── images/
│   ├── icons/
│   ├── full/
│   └── _placeholders/
├── output/
└── svg/
```

## Requirements

Install the Python packages listed in `requirements.txt`.

Notable dependencies:

- `streamlit` for the multipage app shell
- `pandas` and `sqlite3` for catalog, measurement, worksheet, and fabrication data
- `numpy`, `scipy`, `trimesh`, `manifold3d`, and `networkx` for geometry/model workflows
- `plotly` and `matplotlib` for charts and visual analysis
- `Pillow` and `opencv-python-headless` for image handling and mesh crop support
- `reportlab` for printable fabrication checklist PDFs
- `lxml` and `vpype` for SVG processing

## Local Setup

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the app from the repository root:

```bash
streamlit run Home.py
```

The Streamlit entry point is `Home.py`. Keep the filename casing exact, especially for hosted deployment.

## Data and Assets

The glass library depends on local SQLite data and image assets:

- `data/glass_library.sqlite`
- `images/icons/`
- `images/full/`
- `images/_placeholders/`

Mold and fabrication worksheets use:

- `data/mold_records.db`
- `data/fabrication_records.db`

The app can still open if some assets are missing, but related library images, worksheets, or reference features will be incomplete.

`private_pages/` contains local/admin-only glass sample editor tools. These files are intentionally kept outside Streamlit's `pages/` directory so they are not exposed in the public multipage app.

## Glass Library Notes

Glass records are organized around catalog data plus reflected and transmitted measurements. Several pages intentionally compare these two lighting modes because opal, transparent, and tint glasses can read differently depending on light direction, thickness, layering, surface finish, and source color temperature.

For opalescent glass, the detail page includes an explanatory note below the reflected/transmitted image panels. This helps clarify why a sample may look pale, blue, white, or milky in reflected light while appearing warmer, darker, amber, gray, or more translucent when backlit.

## PDFs and Printing

The app generates printer-ready PDFs for:

- individual glass datasheets
- opalescent, transparent, and tint reference sheets

These generated PDFs are intended to avoid browser print layout inconsistencies and keep studio reference output stable for archiving, sample books, and shop use.

## Localization

The app uses a key-based localization system rather than a gettext catalog workflow.

Current UI languages:

- English
- Spanish
- Italian
- German
- French

Localization responsibilities:

- `i18n.py` stores supported languages, locale mappings, translation dictionaries, and formatting helpers.
- Pages render user-facing copy through stable translation keys via `t("...")` or `tr("...")`.
- Displayed dates and times are formatted according to the active language/locale.
- Units such as Fahrenheit/Celsius remain separate from language selection.
- Stored database values remain canonical and are not rewritten for localization.

Audit translation coverage for a language:

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

## Streamlit Community Cloud Deployment

Recommended settings:

- Repository: this GitHub repository
- Branch: the deployment branch
- Main file path: `Home.py`
- Python version: 3.12 recommended

Deployment notes:

- `requirements.txt` is prepared for Streamlit deployment.
- The SQLite databases must be committed if hosted glass/library/worksheet data should be available.
- The repository includes many image assets, so repository size can affect deployment and update time.
- SVG pages depend on `vpype`.
- Mesh/model workflows use Python geometry libraries and default to the `manifold` path where applicable.
- External tools such as Blender or OpenSCAD are not bundled and should be treated as optional local-only engines.
- UI localization is session-based and does not modify stored database content.

## STL and Mold Workflow

The STL output in this project is usually the beginning of a kiln-glass mold workflow, not the final design artifact.

Typical use:

1. Prepare artwork, a heightmap, or a vessel/profile concept.
2. Generate an STL or fabrication plan in the app.
3. Print the model by FDM or resin, depending on scale and detail.
4. Use the print to create an intermediate mold, negative, support, frame, or master.
5. Build the refractory mold or pate de verre setup from the intermediate form.
6. Cast, pack, fuse, fire, and anneal the final glass piece according to the studio process.

FDM is generally useful for larger structural tooling, support plugs, frames, and draft models. Resin is generally useful for smaller pieces where surface detail and crisp relief matter more than build volume.

## Repository Notes

- Generated `__pycache__/` files and local OS metadata are not part of the app source and should generally stay out of commits.
- `output/` is for generated artifacts such as PDFs and should be reviewed before committing.
- Database and image migrations should be tested locally before updating hosted data.
